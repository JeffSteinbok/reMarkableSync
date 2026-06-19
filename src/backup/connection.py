"""
reMarkable tablet connection coordinator.

Provides a high-level interface for connecting to reMarkable tablets,
coordinating SSH sessions, credentials, and pre/post sync commands.

This is a facade that orchestrates:
- SSHSession for low-level SSH/SCP operations
- CredentialStore for password management
- TabletFilesystem for file operations
"""

import logging
import socket
from typing import Dict, List, Optional, Tuple

import click
import paramiko

from ..utils.console import print_error, print_success, print_warn
from .credential_store import create_credential_store
from .protocols import DEFAULT_TABLET_CONFIG, CredentialStoreProtocol, TabletConfig
from .ssh_session import SSHSession
from .tablet_filesystem import TabletFilesystem

# Default USB networking address assigned by the reMarkable USB driver
USB_HOST = DEFAULT_TABLET_CONFIG.usb_host

# mDNS/Bonjour hostname that many reMarkable tablets advertise on the LAN
MDNS_HOSTNAME = DEFAULT_TABLET_CONFIG.mdns_hostname


def discover_tablet_host(timeout: float = 3.0) -> Optional[str]:
    """Attempt to discover a reMarkable tablet on the local network.

    Tries to resolve the well-known mDNS hostname ``remarkable.local``.
    If that fails, tries the USB address as a last resort.

    Args:
        timeout: Seconds to wait for each resolution attempt.

    Returns:
        IP address string if found, or ``None`` if discovery failed.
    """
    candidates = [MDNS_HOSTNAME, USB_HOST]
    for candidate in candidates:
        try:
            socket.setdefaulttimeout(timeout)
            addr = socket.gethostbyname(candidate)
            logging.info("Tablet discovered at %s (%s)", addr, candidate)
            return addr
        except OSError:
            logging.debug("Discovery failed for candidate %s", candidate)
    return None


class ReMarkableConnection:
    """High-level connection coordinator for reMarkable tablet.

    Orchestrates SSH sessions, credential management, and sync commands.
    Implements ConnectionProtocol for dependency injection and testability.

    Example:
        conn = ReMarkableConnection()
        if conn.connect():
            files = conn.list_files("/path")
            conn.disconnect()
    """

    KEYRING_SERVICE = "reMarkableSync"
    KEYRING_USERNAME = "reMarkable_ssh"

    def __init__(
        self,
        host: str = USB_HOST,
        username: str = "root",
        port: int = 22,
        password: str | None = None,
        use_wifi: bool = False,
        wifi_host: str = "",
        pre_sync_command: str = "",
        post_sync_command: str = "",
        credential_store: Optional[CredentialStoreProtocol] = None,
        tablet_config: Optional[TabletConfig] = None,
        ssh_session: Optional[SSHSession] = None,
    ):
        """Initialize connection coordinator.

        Args:
            host: reMarkable tablet IP address (default USB networking address).
            username: SSH username (always 'root' for ReMarkable).
            port: SSH port (default 22).
            password: SSH password (will prompt if not provided).
            use_wifi: When True, prefer Wi-Fi address over USB.
            wifi_host: IP/hostname for Wi-Fi connection.
            pre_sync_command: Shell command to run before connecting.
            post_sync_command: Shell command to run after disconnecting.
            credential_store: Credential storage backend (default: system keyring).
            tablet_config: Tablet-specific configuration.
            ssh_session: Injectable SSH session for testing.
        """
        # Injected dependencies
        self._credential_store = credential_store or create_credential_store()
        self._tablet_config = tablet_config or DEFAULT_TABLET_CONFIG
        self._session = ssh_session or SSHSession()
        self._filesystem: Optional[TabletFilesystem] = None

        # Resolve effective host
        if use_wifi:
            if wifi_host:
                resolved_host = wifi_host
            else:
                logging.info("Wi-Fi mode enabled but no host specified - attempting auto-discovery")
                resolved_host = discover_tablet_host() or USB_HOST
        else:
            resolved_host = host

        self.host = resolved_host
        self.username = username
        self.port = port
        self.password = password
        self.password_saved = False
        self.pre_sync_command = pre_sync_command.strip()
        self.post_sync_command = post_sync_command.strip()

    # -------------------------------------------------------------------------
    # Credential management (delegated to CredentialStore)
    # -------------------------------------------------------------------------

    def get_saved_password(self) -> str | None:
        """Get saved password from credential storage."""
        return self._credential_store.get_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)

    def save_password(self, password: str) -> bool:
        """Save password to credential storage."""
        success = self._credential_store.set_password(
            self.KEYRING_SERVICE, self.KEYRING_USERNAME, password
        )
        if success:
            self.password_saved = True
        return success

    def delete_saved_password(self) -> bool:
        """Delete saved password from credential storage."""
        return self._credential_store.delete_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)

    def get_password(self) -> str:
        """Get SSH password from saved keyring or user input."""
        if not self.password:
            saved_password = self.get_saved_password()
            if saved_password:
                print("Using saved SSH password...")
                self.password = saved_password
                return self.password

            print("To get your reMarkable SSH password:")
            print("1. Connect your tablet via USB")
            print("2. Go to Settings > Help > Copyright and licenses")
            print("3. Find the password under 'GPLv3 Compliance'")
            self.password = click.prompt("Enter SSH password", hide_input=True)

        return self.password

    # -------------------------------------------------------------------------
    # Connection lifecycle
    # -------------------------------------------------------------------------

    @property
    def ssh_client(self):
        """Access underlying SSH client (for backward compatibility)."""
        return self._session._ssh_client if self._session else None

    @ssh_client.setter
    def ssh_client(self, value):
        """Set SSH client (for testing)."""
        if self._session:
            self._session._ssh_client = value

    @property
    def scp_client(self):
        """Access underlying SCP client (for backward compatibility)."""
        return self._session.scp_client if self._session else None

    @scp_client.setter
    def scp_client(self, value):
        """Set SCP client (for testing)."""
        if self._session:
            self._session._scp_client = value

    def connect(self) -> bool:
        """Establish SSH connection to reMarkable tablet.

        Runs pre-sync command if configured, then connects via SSH.

        Returns:
            True if connection successful, False otherwise.
        """
        # Run pre-sync command
        if self.pre_sync_command:
            from ..utils import run_shell_command

            print(f"  Running pre-sync: {self.pre_sync_command}")
            rc = run_shell_command(self.pre_sync_command)
            if rc != 0:
                print_error(f"  ERR - Pre-sync command failed (exit {rc})")
                return False
            print_success("  OK - Pre-sync done")

        # Try connecting with retries for password
        max_retries = 3
        attempt = 0
        used_saved_password = False

        while attempt < max_retries:
            saved_password = self.get_saved_password()
            if saved_password and not self.password:
                used_saved_password = True

            password = self.get_password()

            # Try connection with escalating timeouts
            timeouts = [(5, 5, 10), (15, 15, 15)]
            total_timeout = sum(t[0] for t in timeouts)
            print(f"  Connecting to {self.host} (up to {total_timeout}s)...")

            for timeout, banner_timeout, auth_timeout in timeouts:
                try:
                    if self._session.connect(
                        host=self.host,
                        port=self.port,
                        username=self.username,
                        password=password,
                        timeout=timeout,
                        banner_timeout=banner_timeout,
                        auth_timeout=auth_timeout,
                    ):
                        self._filesystem = TabletFilesystem(self._session)
                        return True

                except paramiko.AuthenticationException:
                    if used_saved_password:
                        print_warn("  WRN - Saved password appears to be incorrect.")
                        if click.confirm("Would you like to enter a new password?", default=True):
                            self.delete_saved_password()
                            self.password = None
                            used_saved_password = False
                            attempt += 1
                            break
                        elif not click.confirm("Try saved password again?", default=False):
                            return False
                        attempt += 1
                        break
                    else:
                        print_error("  ERR - Authentication failed. Please check your password.")
                        self.password = None
                        attempt += 1
                        break
            else:
                # All timeout attempts failed
                print_error(
                    f"  ERR - Connection to {self.host} failed. "
                    "Check that the tablet is connected and try again."
                )
                return False

        print_error("  ERR - Maximum password retry attempts reached.")
        return False

    def disconnect(self):
        """Close SSH connection and run post-sync command."""
        print("  Disconnecting...")
        self._session.disconnect()
        self._filesystem = None

        if self.post_sync_command:
            from ..utils import run_shell_command

            print(f"  Running post-sync: {self.post_sync_command}")
            rc = run_shell_command(self.post_sync_command)
            if rc != 0:
                print_error(f"  ERR - Post-sync command failed (exit {rc})")
            else:
                print_success("  OK - Post-sync done")

    # -------------------------------------------------------------------------
    # Remote operations (delegated to SSHSession and TabletFilesystem)
    # -------------------------------------------------------------------------

    def execute_command(self, command: str) -> Tuple[str, str, int]:
        """Execute command on reMarkable tablet via SSH.

        Args:
            command: Shell command to execute.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Raises:
            ConnectionError: If not connected.
        """
        return self._session.execute(command)

    def list_files(self, remote_path: str) -> List[Dict]:
        """List files in remote directory with metadata.

        Args:
            remote_path: Remote directory path to scan.

        Returns:
            List of file metadata dictionaries.
        """
        if self._filesystem:
            return self._filesystem.list_files(remote_path)

        # Fallback: parse directly if we have a session with ssh_client
        if self._session and self._session._ssh_client:
            command = f"find {remote_path} -type f -exec stat -c '%Y %s %n' {{}} \\;"
            stdout, stderr, exit_code = self._session.execute(command)

            if exit_code != 0:
                logging.error("Failed to list files: %s", stderr)
                return []

            files = []
            for line in stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(" ", 2)
                if len(parts) == 3:
                    files.append(
                        {
                            "path": parts[2],
                            "mtime": int(parts[0]),
                            "size": int(parts[1]),
                        }
                    )
            return files

        return []
