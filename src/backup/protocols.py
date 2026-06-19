"""
Protocol definitions for backup module abstractions.

Defines interfaces for connection, credential storage, and tablet configuration
to enable dependency injection and improve testability.
"""

from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable


@runtime_checkable
class ConnectionProtocol(Protocol):
    """Protocol defining the interface for tablet connections.

    Both ReMarkableConnection and MockConnection should implement this protocol.
    This enables dependency injection and ensures mock implementations stay in sync.
    """

    host: str
    username: str
    port: int
    password: Optional[str]
    password_saved: bool

    def get_saved_password(self) -> Optional[str]:
        """Get saved password from credential storage."""
        ...

    def save_password(self, password: str) -> bool:
        """Save password to credential storage."""
        ...

    def delete_saved_password(self) -> bool:
        """Delete saved password from credential storage."""
        ...

    def get_password(self) -> str:
        """Get SSH password from user input or saved storage."""
        ...

    def connect(self) -> bool:
        """Establish connection to the tablet."""
        ...

    def disconnect(self) -> None:
        """Close connection to the tablet."""
        ...

    def execute_command(self, command: str) -> Tuple[str, str, int]:
        """Execute command on the tablet.

        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        ...

    def list_files(self, remote_path: str) -> List[Dict]:
        """List files in remote directory with metadata.

        Returns:
            List of dicts with 'path', 'mtime', 'size' keys.
        """
        ...

    def get(self, remote_path: str, local_path: str, recursive: bool = False) -> None:
        """Download file(s) from the tablet."""
        ...


@runtime_checkable
class CredentialStoreProtocol(Protocol):
    """Protocol for credential storage backends.

    Abstracts keyring operations to enable testing without system keyring.
    """

    def get_password(self, service: str, username: str) -> Optional[str]:
        """Retrieve a stored password."""
        ...

    def set_password(self, service: str, username: str, password: str) -> bool:
        """Store a password."""
        ...

    def delete_password(self, service: str, username: str) -> bool:
        """Delete a stored password."""
        ...


class TabletConfig:
    """Configuration for tablet-specific paths and settings.

    Centralizes tablet-specific constants that were previously hardcoded,
    making it easier to support firmware updates or different tablet types.
    """

    def __init__(
        self,
        xochitl_dir: str = "/home/root/.local/share/remarkable/xochitl",
        templates_dir: str = "/usr/share/remarkable/templates",
        ssh_user: str = "root",
        ssh_port: int = 22,
        usb_host: str = "10.11.99.1",
        mdns_hostname: str = "reMarkable.local",
    ):
        """Initialize tablet configuration.

        Args:
            xochitl_dir: Path to notebook files on tablet
            templates_dir: Path to template files on tablet
            ssh_user: SSH username (always 'root' for reMarkable)
            ssh_port: SSH port (default 22)
            usb_host: USB networking address
            mdns_hostname: mDNS hostname for discovery
        """
        self.xochitl_dir = xochitl_dir
        self.templates_dir = templates_dir
        self.ssh_user = ssh_user
        self.ssh_port = ssh_port
        self.usb_host = usb_host
        self.mdns_hostname = mdns_hostname

    @classmethod
    def default(cls) -> "TabletConfig":
        """Create default configuration for reMarkable tablets."""
        return cls()


# Default tablet configuration instance
DEFAULT_TABLET_CONFIG = TabletConfig.default()
