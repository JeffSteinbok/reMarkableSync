"""
Low-level SSH session management for reMarkable tablet connections.

This module provides the core SSH/SCP functionality without any
reMarkable-specific logic or credential management.
"""

import logging
import socket
from typing import Optional, Protocol, Tuple

import paramiko
from scp import SCPClient

# Suppress paramiko noise
for _n in ("paramiko", "paramiko.transport", "paramiko.auth", "paramiko.channel"):
    _l = logging.getLogger(_n)
    _l.setLevel(logging.CRITICAL)
    _l.propagate = False


class SSHSessionProtocol(Protocol):
    """Protocol for SSH session implementations."""

    @property
    def is_connected(self) -> bool:
        """Whether the session is currently connected."""
        ...

    def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        timeout: int = 10,
    ) -> bool:
        """Establish SSH connection."""
        ...

    def disconnect(self) -> None:
        """Close SSH connection."""
        ...

    def execute(self, command: str) -> Tuple[str, str, int]:
        """Execute command and return (stdout, stderr, exit_code)."""
        ...

    def get_file(self, remote_path: str, local_path: str) -> None:
        """Download file via SCP."""
        ...


class SSHSession:
    """Low-level SSH session for remote command execution and file transfer.

    This class handles only the SSH/SCP transport layer. It does not handle:
    - Credential storage or prompting
    - Pre/post sync commands
    - ReMarkable-specific paths or protocols

    Example:
        session = SSHSession()
        if session.connect("10.11.99.1", 22, "root", "password"):
            stdout, stderr, code = session.execute("ls -la")
            session.disconnect()
    """

    def __init__(self):
        """Initialize an empty SSH session."""
        self._ssh_client: Optional[paramiko.SSHClient] = None
        self._scp_client: Optional[SCPClient] = None
        self._host: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        """Whether the session is currently connected."""
        return self._ssh_client is not None

    @property
    def scp_client(self) -> Optional[SCPClient]:
        """Access the SCP client for direct file operations."""
        return self._scp_client

    def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        timeout: int = 10,
        banner_timeout: int = 10,
        auth_timeout: int = 15,
    ) -> bool:
        """Establish SSH connection to remote host.

        Args:
            host: Remote hostname or IP address.
            port: SSH port (usually 22).
            username: SSH username.
            password: SSH password.
            timeout: Connection timeout in seconds.
            banner_timeout: SSH banner timeout in seconds.
            auth_timeout: Authentication timeout in seconds.

        Returns:
            True if connection successful, False otherwise.

        Raises:
            paramiko.AuthenticationException: If authentication fails.
        """
        self._host = host

        # Quick TCP check before full SSH handshake
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            sock.close()
        except (socket.timeout, OSError) as e:
            logging.info("TCP connect to %s:%d failed: %s", host, port, e)
            return False

        try:
            self._ssh_client = paramiko.SSHClient()
            self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            logging.info("SSH connecting to %s:%d with timeout %ds...", host, port, timeout)
            self._ssh_client.connect(
                hostname=host,
                username=username,
                password=password,
                port=port,
                timeout=timeout,
                banner_timeout=banner_timeout,
                auth_timeout=auth_timeout,
                allow_agent=False,
                look_for_keys=False,
            )

            transport = self._ssh_client.get_transport()
            if transport is None:
                raise ConnectionError("Failed to get SSH transport")

            self._scp_client = SCPClient(transport)
            logging.info("SSH connected to %s", host)
            return True

        except paramiko.AuthenticationException:
            # Let auth exceptions bubble up for caller to handle
            self._cleanup()
            raise

        except (paramiko.SSHException, OSError) as e:
            logging.debug("SSH connection to %s failed: %s", host, e)
            self._cleanup()
            return False

    def disconnect(self) -> None:
        """Close SSH and SCP connections."""
        if self._scp_client:
            try:
                self._scp_client.close()
            except Exception:
                pass
            self._scp_client = None

        if self._ssh_client:
            try:
                self._ssh_client.close()
            except Exception:
                pass
            self._ssh_client = None

        logging.info("SSH disconnected from %s", self._host)
        self._host = None

    def execute(self, command: str) -> Tuple[str, str, int]:
        """Execute command on remote host via SSH.

        Args:
            command: Shell command to execute.

        Returns:
            Tuple of (stdout, stderr, exit_code).

        Raises:
            ConnectionError: If not connected.
        """
        if not self._ssh_client:
            raise ConnectionError("Not connected")

        _, stdout, stderr = self._ssh_client.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()

        return stdout.read().decode(), stderr.read().decode(), exit_code

    def get_file(self, remote_path: str, local_path: str) -> None:
        """Download file from remote host via SCP.

        Args:
            remote_path: Path to file on remote host.
            local_path: Local path to save file.

        Raises:
            ConnectionError: If not connected.
            scp.SCPException: If transfer fails.
        """
        if not self._scp_client:
            raise ConnectionError("Not connected")

        self._scp_client.get(remote_path, local_path)

    def _cleanup(self) -> None:
        """Clean up any partial connection state."""
        if self._ssh_client:
            try:
                self._ssh_client.close()
            except Exception:
                pass
            self._ssh_client = None
        self._scp_client = None
