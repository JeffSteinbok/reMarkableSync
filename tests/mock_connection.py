"""
Mock ReMarkable tablet connection for testing.

Provides a drop-in replacement for ReMarkableConnection that serves files
from a local fixture directory, simulating the tablet's SSH filesystem.
"""

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Import the protocol to ensure MockConnection stays in sync
from src.backup.protocols import DEFAULT_TABLET_CONFIG, TabletConfig

# Path to the fixture tablet filesystem
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "fake_tablet"
XOCHITL_DIR = FIXTURES_DIR / "xochitl"

# Mirrors the tablet's remote path (from default tablet config)
REMOTE_XOCHITL = DEFAULT_TABLET_CONFIG.xochitl_dir


class MockConnection:
    """Mock replacement for ReMarkableConnection.

    Reads from the local fixtures directory instead of connecting via SSH.
    Implements the ConnectionProtocol interface so it can be used
    as a drop-in substitute in tests.

    Note: This class intentionally implements ConnectionProtocol to ensure
    it stays in sync with the real ReMarkableConnection interface.
    """

    KEYRING_SERVICE = "RemarkableSync"
    KEYRING_USERNAME = "remarkable_ssh"

    def __init__(
        self,
        host: str = "10.11.99.1",
        username: str = "root",
        port: int = 22,
        password: str | None = None,
        use_wifi: bool = False,
        wifi_host: str = "",
        fixture_dir: Path | None = None,
        tablet_config: TabletConfig | None = None,
    ):
        self.host = host
        self.username = username
        self.port = port
        self.password = password or "mock-password"
        self.password_saved = False
        self._connected = False
        self._fixture_dir = fixture_dir or FIXTURES_DIR
        self._xochitl_dir = self._fixture_dir / "xochitl"
        self._tablet_config = tablet_config or DEFAULT_TABLET_CONFIG

    def get_saved_password(self) -> str | None:
        return "mock-password"

    def save_password(self, password: str) -> bool:
        self.password_saved = True
        return True

    def delete_saved_password(self) -> bool:
        return True

    def get_password(self) -> str:
        return self.password or "mock-password"

    def connect(self) -> bool:
        """Simulate a successful connection."""
        self._connected = True
        return True

    def disconnect(self):
        """Simulate disconnection."""
        self._connected = False

    def execute_command(self, command: str) -> Tuple[str, str, int]:
        """Simulate executing a command on the tablet.

        Supports the commands typically used by the backup system:
        - find ... -exec stat ... (for listing files)
        - cat (for reading file contents)
        """
        if not self._connected:
            raise ConnectionError("Not connected to mock tablet")

        # Handle 'find ... -exec stat' for file listing
        if "find" in command and "stat" in command:
            return self._handle_find_stat(command)

        # Handle 'cat' for reading files
        if command.startswith("cat "):
            return self._handle_cat(command)

        return "", f"Mock: unrecognized command: {command}", 1

    def list_files(self, remote_path: str) -> List[Dict]:
        """List files from the fixture directory, mimicking tablet output."""
        if not self._connected:
            raise ConnectionError("Not connected to mock tablet")

        # Map remote path to local fixture path
        local_path = self._remote_to_local(remote_path)
        if not local_path or not local_path.exists():
            return []

        files = []
        for f in local_path.rglob("*"):
            if f.is_file():
                stat = f.stat()
                # Build the "remote" path as the tablet would report it
                rel = f.relative_to(self._fixture_dir)
                remote_file_path = f"/home/root/.local/share/remarkable/{rel.as_posix()}"
                files.append(
                    {
                        "path": remote_file_path,
                        "mtime": int(stat.st_mtime),
                        "size": stat.st_size,
                    }
                )

        return files

    def get(self, remote_path: str, local_path: str, recursive: bool = False):
        """Simulate SCP file download by copying from fixtures."""
        src = self._remote_to_local(remote_path)
        if src is None or not src.exists():
            raise FileNotFoundError(f"Mock: remote file not found: {remote_path}")

        dst = Path(local_path)
        if src.is_dir():
            if recursive:
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                raise IsADirectoryError(f"Mock: {remote_path} is a directory, use recursive=True")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # ------------------------------------------------------------------
    # Helpers for folder listing (used by config command)
    # ------------------------------------------------------------------

    def get_top_level_folders(self) -> List[Dict[str, str]]:
        """Return top-level folder names and UUIDs from fixture metadata.

        This is a convenience method for tests that mirrors what backup_manager
        does when scanning the tablet.
        """
        folders = []
        for meta_file in self._xochitl_dir.glob("*.metadata"):
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("type") == "CollectionType" and meta.get("parent", "") == "":
                folders.append(
                    {
                        "uuid": meta_file.stem,
                        "name": meta.get("visibleName", ""),
                    }
                )
        return sorted(folders, key=lambda x: x["name"])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _remote_to_local(self, remote_path: str) -> Optional[Path]:
        """Map a remote tablet path to the local fixture path."""
        prefix = "/home/root/.local/share/remarkable/"
        if remote_path.startswith(prefix):
            rel = remote_path[len(prefix) :]
            return self._fixture_dir / rel
        # Try xochitl shorthand
        if remote_path.startswith(REMOTE_XOCHITL):
            rel = remote_path[len(REMOTE_XOCHITL) :].lstrip("/")
            return self._xochitl_dir / rel if rel else self._xochitl_dir
        return None

    def _handle_find_stat(self, command: str) -> Tuple[str, str, int]:
        """Simulate 'find <path> -type f -exec stat -c '%Y %s %n' {} ;'"""
        # Extract the path from the command
        parts = command.split()
        try:
            path_idx = parts.index("find") + 1
            remote_path = parts[path_idx]
        except (ValueError, IndexError):
            return "", "Mock: could not parse find command", 1

        local_path = self._remote_to_local(remote_path)
        if not local_path or not local_path.exists():
            return "", f"find: '{remote_path}': No such file or directory", 1

        lines = []
        for f in local_path.rglob("*"):
            if f.is_file():
                stat = f.stat()
                rel = f.relative_to(self._fixture_dir)
                remote_file_path = f"/home/root/.local/share/remarkable/{rel.as_posix()}"
                lines.append(f"{int(stat.st_mtime)} {stat.st_size} {remote_file_path}")

        return "\n".join(lines), "", 0

    def _handle_cat(self, command: str) -> Tuple[str, str, int]:
        """Simulate 'cat <path>'"""
        remote_path = command[4:].strip().strip("'\"")
        local_path = self._remote_to_local(remote_path)
        if not local_path or not local_path.exists():
            return "", f"cat: {remote_path}: No such file or directory", 1

        content = local_path.read_text(encoding="utf-8")
        return content, "", 0
