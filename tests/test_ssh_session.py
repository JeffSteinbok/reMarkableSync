"""
Tests for SSHSession and TabletFilesystem.

Tests the decomposed connection components.
"""

import socket
from unittest.mock import MagicMock, patch

import paramiko
import pytest

from src.backup.ssh_session import SSHSession
from src.backup.tablet_filesystem import TabletFilesystem


class TestSSHSession:
    """Tests for SSHSession low-level SSH operations."""

    def test_initial_state_not_connected(self):
        """New session is not connected."""
        session = SSHSession()
        assert session.is_connected is False
        assert session.scp_client is None

    def test_connect_success(self):
        """connect returns True on successful connection."""
        session = SSHSession()

        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock

            with patch("paramiko.SSHClient") as mock_ssh_class:
                mock_ssh = MagicMock()
                mock_ssh_class.return_value = mock_ssh
                mock_ssh.get_transport.return_value = MagicMock()

                with patch("scp.SCPClient"):
                    result = session.connect(
                        host="10.11.99.1",
                        port=22,
                        username="root",
                        password="test",
                    )

        assert result is True
        assert session.is_connected is True

    def test_connect_fails_on_tcp_error(self):
        """connect returns False when TCP connection fails."""
        session = SSHSession()

        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            mock_sock.connect.side_effect = socket.error("Connection refused")

            result = session.connect(
                host="10.11.99.1",
                port=22,
                username="root",
                password="test",
            )

        assert result is False
        assert session.is_connected is False

    def test_connect_raises_on_auth_error(self):
        """connect raises AuthenticationException on auth failure."""
        session = SSHSession()

        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock

            with patch("paramiko.SSHClient") as mock_ssh_class:
                mock_ssh = MagicMock()
                mock_ssh_class.return_value = mock_ssh
                mock_ssh.connect.side_effect = paramiko.AuthenticationException("Bad password")

                with pytest.raises(paramiko.AuthenticationException):
                    session.connect(
                        host="10.11.99.1",
                        port=22,
                        username="root",
                        password="wrong",
                    )

        assert session.is_connected is False

    def test_disconnect_cleans_up(self):
        """disconnect cleans up SSH and SCP clients."""
        session = SSHSession()
        session._ssh_client = MagicMock()
        session._scp_client = MagicMock()

        session.disconnect()

        assert session._ssh_client is None
        assert session._scp_client is None
        assert session.is_connected is False

    def test_execute_returns_output(self):
        """execute returns stdout, stderr, exit_code."""
        session = SSHSession()

        mock_ssh = MagicMock()
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.read.return_value = b"hello world"
        mock_stderr.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_ssh.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)
        session._ssh_client = mock_ssh

        stdout, stderr, code = session.execute("echo hello world")

        assert stdout == "hello world"
        assert stderr == ""
        assert code == 0

    def test_execute_raises_when_not_connected(self):
        """execute raises ConnectionError when not connected."""
        session = SSHSession()

        with pytest.raises(ConnectionError):
            session.execute("ls")

    def test_get_file_raises_when_not_connected(self):
        """get_file raises ConnectionError when not connected."""
        session = SSHSession()

        with pytest.raises(ConnectionError):
            session.get_file("/remote/file", "/local/file")


class TestTabletFilesystem:
    """Tests for TabletFilesystem operations."""

    def test_list_files_parses_output(self):
        """list_files parses stat output correctly."""
        mock_executor = MagicMock()
        mock_executor.execute.return_value = (
            "1700000000 1024 /path/file1.txt\n1700000001 2048 /path/file2.txt\n",
            "",
            0,
        )

        fs = TabletFilesystem(mock_executor)
        files = fs.list_files("/path")

        assert len(files) == 2
        assert files[0]["path"] == "/path/file1.txt"
        assert files[0]["mtime"] == 1700000000
        assert files[0]["size"] == 1024
        assert files[1]["path"] == "/path/file2.txt"

    def test_list_files_handles_empty_output(self):
        """list_files returns empty list for empty directory."""
        mock_executor = MagicMock()
        mock_executor.execute.return_value = ("", "", 0)

        fs = TabletFilesystem(mock_executor)
        files = fs.list_files("/empty")

        assert files == []

    def test_list_files_handles_error(self):
        """list_files returns empty list on command error."""
        mock_executor = MagicMock()
        mock_executor.execute.return_value = ("", "No such directory", 1)

        fs = TabletFilesystem(mock_executor)
        files = fs.list_files("/nonexistent")

        assert files == []

    def test_file_exists_returns_true(self):
        """file_exists returns True when file exists."""
        mock_executor = MagicMock()
        mock_executor.execute.return_value = ("yes\n", "", 0)

        fs = TabletFilesystem(mock_executor)
        result = fs.file_exists("/path/file.txt")

        assert result is True

    def test_file_exists_returns_false(self):
        """file_exists returns False when file doesn't exist."""
        mock_executor = MagicMock()
        mock_executor.execute.return_value = ("no\n", "", 0)

        fs = TabletFilesystem(mock_executor)
        result = fs.file_exists("/path/missing.txt")

        assert result is False

    def test_read_file_returns_contents(self):
        """read_file returns file contents."""
        mock_executor = MagicMock()
        mock_executor.execute.return_value = ('{"key": "value"}', "", 0)

        fs = TabletFilesystem(mock_executor)
        content = fs.read_file("/path/file.json")

        assert content == '{"key": "value"}'

    def test_read_file_raises_on_missing(self):
        """read_file raises FileNotFoundError for missing files."""
        mock_executor = MagicMock()
        mock_executor.execute.return_value = ("", "No such file", 1)

        fs = TabletFilesystem(mock_executor)

        with pytest.raises(FileNotFoundError):
            fs.read_file("/path/missing.txt")

    def test_get_disk_usage_parses_output(self):
        """get_disk_usage parses df output."""
        mock_executor = MagicMock()
        mock_executor.execute.return_value = (
            "/dev/root 8000000000 5000000000 3000000000 63% /home\n",
            "",
            0,
        )

        fs = TabletFilesystem(mock_executor)
        usage = fs.get_disk_usage("/home")

        assert usage["total"] == 8000000000
        assert usage["used"] == 5000000000
        assert usage["available"] == 3000000000

    def test_get_disk_usage_handles_error(self):
        """get_disk_usage returns zeros on error."""
        mock_executor = MagicMock()
        mock_executor.execute.return_value = ("", "error", 1)

        fs = TabletFilesystem(mock_executor)
        usage = fs.get_disk_usage("/home")

        assert usage == {"used": 0, "available": 0, "total": 0}
