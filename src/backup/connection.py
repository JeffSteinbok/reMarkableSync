"""
reMarkable tablet SSH connection management.

Handles SSH and SCP connections to reMarkable tablets for file transfer
and remote command execution.

Connection modes
----------------
- USB (default): connects to 10.11.99.1 via the USB networking interface.
- Wi-Fi: connects to any user-supplied hostname/IP address.
- Discovery: optional mDNS/Bonjour discovery to locate the tablet on the LAN.
"""

import logging
import socket
from typing import Dict, List, Optional, Tuple

import click
import paramiko
from scp import SCPClient

from ..utils.console import print_error, print_success, print_warn

# Suppress paramiko noise regardless of when setup_logging is called
for _n in ("paramiko", "paramiko.transport", "paramiko.auth", "paramiko.channel"):
    _l = logging.getLogger(_n)
    _l.setLevel(logging.CRITICAL)
    _l.propagate = False

try:
    import keyring  # type: ignore

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    logging.warning("keyring library not available - password saving disabled")

# Default USB networking address assigned by the reMarkable USB driver
USB_HOST = "10.11.99.1"

# mDNS/Bonjour hostname that many reMarkable tablets advertise on the LAN
MDNS_HOSTNAME = "reMarkable.local"


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
    """Handles SSH connection to reMarkable tablet.

    Provides a robust connection interface with retry logic and error handling
    for connecting to reMarkable tablets via USB or Wi-Fi networking.
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
    ):
        """Initialize connection parameters.

        Args:
            host: reMarkable tablet IP address (default USB networking address).
                  Ignored when *use_wifi* is True and *wifi_host* is provided.
            username: SSH username (always 'root' for ReMarkable)
            port: SSH port (default 22)
            password: SSH password (will prompt if not provided)
            use_wifi: When True, prefer the Wi-Fi address over the USB address.
                      Falls back to USB if *wifi_host* is empty.
            wifi_host: IP address or hostname of the tablet on the local
                       network.  Ignored when *use_wifi* is False.
            pre_sync_command: Shell command to run before SSH connects.
            post_sync_command: Shell command to run after SSH disconnects.
        """
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
        self.ssh_client = None
        self.scp_client = None
        self.password = password
        self.password_saved = False
        self.pre_sync_command = pre_sync_command.strip()
        self.post_sync_command = post_sync_command.strip()

    def get_saved_password(self) -> str | None:
        """Get saved password from system keyring.

        Returns:
            str: Saved password or None if not found
        """
        if not KEYRING_AVAILABLE:
            return None

        try:
            return keyring.get_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)
        except Exception as e:
            logging.debug(f"Failed to retrieve saved password: {e}")
            return None

    def save_password(self, password: str) -> bool:
        """Save password to system keyring.

        Args:
            password: Password to save

        Returns:
            bool: True if saved successfully, False otherwise
        """
        if not KEYRING_AVAILABLE:
            return False

        try:
            keyring.set_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME, password)
            self.password_saved = True
            return True
        except Exception as e:
            logging.warning(f"Failed to save password: {e}")
            return False

    def delete_saved_password(self) -> bool:
        """Delete saved password from system keyring.

        Returns:
            bool: True if deleted successfully, False otherwise
        """
        if not KEYRING_AVAILABLE:
            return False

        try:
            keyring.delete_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)
            return True
        except Exception as e:
            logging.debug(f"Failed to delete saved password: {e}")
            return False

    def get_password(self) -> str:
        """Get SSH password from user input or saved keyring.

        The reMarkable tablet's SSH password is found in:
        Settings > Help > Copyright and licenses > GPLv3 Compliance

        Returns:
            str: The SSH password for tablet authentication
        """
        if not self.password:
            # Try to get saved password first
            saved_password = self.get_saved_password()
            if saved_password:
                print("Using saved SSH password...")
                self.password = saved_password
                return self.password

            # No saved password, prompt user
            print("To get your reMarkable SSH password:")
            print("1. Connect your tablet via USB")
            print("2. Go to Settings > Help > Copyright and licenses")
            print("3. Find the password under 'GPLv3 Compliance'")
            self.password = click.prompt("Enter SSH password", hide_input=True)

        return self.password

    def connect(self) -> bool:
        """Establish SSH connection to reMarkable tablet.

        Runs the pre-sync command (if configured) before opening the SSH
        connection, and the post-sync command (if configured) in disconnect().

        Returns:
            bool: True if connection successful, False otherwise
        """
        if self.pre_sync_command:
            from ..utils import run_shell_command

            print(f"  Running pre-sync: {self.pre_sync_command}")
            rc = run_shell_command(self.pre_sync_command)
            if rc != 0:
                print_error(f"  ERR - Pre-sync command failed (exit {rc})")
                return False
            print_success("  OK - Pre-sync done")

        max_password_retries = 3
        password_attempt = 0
        used_saved_password = False

        while password_attempt < max_password_retries:
            try:
                self.ssh_client = paramiko.SSHClient()
                self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                # Check if we're using a saved password
                saved_password = self.get_saved_password()
                if saved_password and not self.password:
                    used_saved_password = True

                password = self.get_password()

                # Try multiple connection approaches for ReMarkable compatibility
                # First attempt is quick (5s) to fail fast if tablet is unreachable
                connection_attempts = [
                    {"timeout": 5, "banner_timeout": 5, "auth_timeout": 10},
                    {"timeout": 15, "banner_timeout": 15, "auth_timeout": 15},
                ]
                total_timeout = sum(p["timeout"] for p in connection_attempts)

                print(f"  Connecting to {self.host} (up to {total_timeout}s)...")

                for i, params in enumerate(connection_attempts):
                    try:
                        # Quick TCP check before full SSH handshake
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(params["timeout"])
                        try:
                            sock.connect((self.host, self.port))
                            sock.close()
                        except (socket.timeout, OSError) as e:
                            logging.info("TCP connect failed on attempt %d: %s", i + 1, e)
                            if i < len(connection_attempts) - 1:
                                continue  # Try next timeout
                            raise  # Last attempt, let it bubble up

                        logging.info(
                            "Connection attempt %d with timeout %ds...", i + 1, params["timeout"]
                        )
                        self.ssh_client.connect(
                            hostname=self.host,
                            username=self.username,
                            password=password,
                            port=self.port,
                            timeout=params["timeout"],
                            banner_timeout=params["banner_timeout"],
                            auth_timeout=params["auth_timeout"],
                            allow_agent=False,
                            look_for_keys=False,
                        )

                        transport = self.ssh_client.get_transport()
                        if transport is None:
                            raise ConnectionError("Failed to get SSH transport")
                        self.scp_client = SCPClient(transport)
                        logging.info("Connected to reMarkable tablet at %s", self.host)

                        return True

                    except paramiko.AuthenticationException as e:
                        logging.warning("Authentication failed on attempt %d: %s", i + 1, e)
                        # Authentication failed - might be wrong password
                        if used_saved_password:
                            print_warn("  WRN - Saved password appears to be incorrect.")
                            if click.confirm(
                                "Would you like to enter a new password?", default=True
                            ):
                                # Delete the old saved password
                                self.delete_saved_password()
                                self.password = None
                                used_saved_password = False
                                password_attempt += 1
                                break  # Break inner loop to retry with new password
                            else:
                                if click.confirm("Try saved password again?", default=False):
                                    password_attempt += 1
                                    break
                                else:
                                    return False
                        else:
                            print_error(
                                "  ERR - Authentication failed. Please check your password."
                            )
                            self.password = None
                            password_attempt += 1
                            break
                    except (paramiko.SSHException, OSError) as e:
                        logging.debug("Connection attempt %d failed: %s", i + 1, e)
                        if self.ssh_client:
                            try:
                                self.ssh_client.close()
                            except (paramiko.SSHException, OSError):
                                pass
                            self.ssh_client = paramiko.SSHClient()
                            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                logging.debug("All connection attempts failed")

                print_error(
                    f"  ERR - Connection to {self.host} failed. "
                    "Check that the tablet is connected and try again."
                )
                return False

            except (paramiko.SSHException, OSError) as e:
                logging.debug("Failed to connect to ReMarkable: %s", e)
                print_error(
                    f"  ERR - Connection to {self.host} failed. "
                    "Check that the tablet is connected and try again."
                )
                return False

        print_error("  ERR - Maximum password retry attempts reached.")
        return False

    def disconnect(self):
        """Close SSH and SCP connections to reMarkable tablet."""
        print("  Disconnecting...")
        if self.scp_client:
            self.scp_client.close()
        if self.ssh_client:
            self.ssh_client.close()
        logging.info("Disconnected from reMarkable tablet")

        if self.post_sync_command:
            from ..utils import run_shell_command

            print(f"  Running post-sync: {self.post_sync_command}")
            rc = run_shell_command(self.post_sync_command)
            if rc != 0:
                print_error(f"  ERR - Post-sync command failed (exit {rc})")
            else:
                print_success("  OK - Post-sync done")

    def execute_command(self, command: str) -> Tuple[str, str, int]:
        """Execute command on reMarkable tablet via SSH.

        Args:
            command: Shell command to execute on the tablet

        Returns:
            Tuple of (stdout, stderr, exit_code)

        Raises:
            ConnectionError: If not connected to tablet
        """
        if not self.ssh_client:
            raise ConnectionError("Not connected to reMarkable tablet")

        _, stdout, stderr = self.ssh_client.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()

        return stdout.read().decode(), stderr.read().decode(), exit_code

    def list_files(self, remote_path: str) -> List[Dict]:
        """List files in remote directory with metadata.

        Uses the 'find' and 'stat' commands to get file modification times,
        sizes, and paths for incremental sync comparison.

        Args:
            remote_path: Remote directory path to scan

        Returns:
            List of dictionaries containing file metadata:
            - path: Full file path on tablet
            - mtime: Unix timestamp of last modification
            - size: File size in bytes
        """
        command = f"find {remote_path} -type f -exec stat -c '%Y %s %n' {{}} \\;"
        stdout, stderr, exit_code = self.execute_command(command)

        if exit_code != 0:
            logging.error("Failed to list files: %s", stderr)
            return []

        files = []
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(" ", 2)
            if len(parts) == 3:
                files.append({"path": parts[2], "mtime": int(parts[0]), "size": int(parts[1])})

        return files
