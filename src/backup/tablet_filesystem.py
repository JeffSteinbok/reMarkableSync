"""
Remote filesystem operations for reMarkable tablet.

Provides high-level file listing and metadata operations,
built on top of SSHSession.
"""

import logging
from typing import Dict, List, Protocol


class CommandExecutorProtocol(Protocol):
    """Protocol for command execution (satisfied by SSHSession)."""

    def execute(self, command: str) -> tuple[str, str, int]:
        """Execute command and return (stdout, stderr, exit_code)."""
        ...


class TabletFilesystem:
    """High-level filesystem operations for reMarkable tablet.

    Provides methods to list, query, and transfer files from the tablet.
    Uses an injected command executor (typically SSHSession) for transport.

    Example:
        session = SSHSession()
        session.connect(...)
        fs = TabletFilesystem(session)
        files = fs.list_files("/home/root/.local/share/remarkable/xochitl")
    """

    def __init__(self, executor: CommandExecutorProtocol):
        """Initialize filesystem with a command executor.

        Args:
            executor: Object implementing execute() for remote commands.
        """
        self._executor = executor

    def list_files(self, remote_path: str) -> List[Dict]:
        """List files in remote directory with metadata.

        Uses 'find' and 'stat' commands to get file modification times,
        sizes, and paths for incremental sync comparison.

        Args:
            remote_path: Remote directory path to scan.

        Returns:
            List of dictionaries containing file metadata:
            - path: Full file path on tablet
            - mtime: Unix timestamp of last modification
            - size: File size in bytes
        """
        command = f"find {remote_path} -type f -exec stat -c '%Y %s %n' {{}} \\;"
        stdout, stderr, exit_code = self._executor.execute(command)

        if exit_code != 0:
            logging.error("Failed to list files in %s: %s", remote_path, stderr)
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

    def file_exists(self, remote_path: str) -> bool:
        """Check if a file exists on the remote filesystem.

        Args:
            remote_path: Path to check.

        Returns:
            True if file exists, False otherwise.
        """
        command = f"test -f {remote_path} && echo 'yes' || echo 'no'"
        stdout, _, _ = self._executor.execute(command)
        return stdout.strip() == "yes"

    def read_file(self, remote_path: str) -> str:
        """Read contents of a remote file.

        Args:
            remote_path: Path to file on tablet.

        Returns:
            File contents as string.

        Raises:
            FileNotFoundError: If file does not exist.
        """
        command = f"cat {remote_path}"
        stdout, stderr, exit_code = self._executor.execute(command)

        if exit_code != 0:
            raise FileNotFoundError(f"Remote file not found: {remote_path} ({stderr.strip()})")

        return stdout

    def get_disk_usage(self, remote_path: str = "/home") -> Dict[str, int]:
        """Get disk usage statistics for a path.

        Args:
            remote_path: Path to check (default: /home).

        Returns:
            Dictionary with 'used', 'available', 'total' in bytes.
        """
        command = f"df -B1 {remote_path} | tail -1"
        stdout, _, exit_code = self._executor.execute(command)

        if exit_code != 0:
            return {"used": 0, "available": 0, "total": 0}

        parts = stdout.split()
        if len(parts) >= 4:
            return {
                "total": int(parts[1]),
                "used": int(parts[2]),
                "available": int(parts[3]),
            }

        return {"used": 0, "available": 0, "total": 0}
