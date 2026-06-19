"""
Tests for ReMarkableConnection with mocked SSH/SCP.

Uses pytest-mock to mock paramiko and SCP for testing connection logic
without requiring a real reMarkable tablet.
"""

import socket
from unittest.mock import MagicMock, patch

import paramiko
import pytest

from src.backup import InMemoryCredentialStore
from src.backup.connection import (
    USB_HOST,
    ReMarkableConnection,
    discover_tablet_host,
)


class TestDiscoverTabletHost:
    """Tests for tablet discovery functionality."""

    def test_discover_finds_mdns_hostname(self):
        """discover_tablet_host returns IP when mDNS resolves."""
        with patch("socket.gethostbyname") as mock_resolve:
            mock_resolve.return_value = "192.168.1.100"

            result = discover_tablet_host(timeout=1.0)

            assert result == "192.168.1.100"
            # Should have tried remarkable.local first
            assert mock_resolve.call_count >= 1

    def test_discover_falls_back_to_usb(self):
        """discover_tablet_host falls back to USB address."""
        with patch("socket.gethostbyname") as mock_resolve:
            # First call (mDNS) fails, second (USB) succeeds
            mock_resolve.side_effect = [
                OSError("mDNS failed"),
                "10.11.99.1",
            ]

            result = discover_tablet_host(timeout=1.0)

            assert result == "10.11.99.1"

    def test_discover_returns_none_when_all_fail(self):
        """discover_tablet_host returns None when no candidates resolve."""
        with patch("socket.gethostbyname") as mock_resolve:
            mock_resolve.side_effect = OSError("All failed")

            result = discover_tablet_host(timeout=1.0)

            assert result is None


class TestReMarkableConnectionInit:
    """Tests for ReMarkableConnection initialization."""

    def test_default_host_is_usb(self):
        """Default host is USB networking address."""
        conn = ReMarkableConnection()
        assert conn.host == USB_HOST

    def test_wifi_host_overrides_default(self):
        """Wi-Fi host is used when use_wifi=True."""
        conn = ReMarkableConnection(
            use_wifi=True,
            wifi_host="192.168.1.50",
        )
        assert conn.host == "192.168.1.50"

    def test_wifi_without_host_triggers_discovery(self):
        """Wi-Fi mode without host attempts auto-discovery."""
        with patch("src.backup.connection.discover_tablet_host") as mock_discover:
            mock_discover.return_value = "192.168.1.100"

            conn = ReMarkableConnection(use_wifi=True, wifi_host="")

            assert conn.host == "192.168.1.100"
            mock_discover.assert_called_once()

    def test_wifi_discovery_failure_falls_back_to_usb(self):
        """Wi-Fi mode falls back to USB when discovery fails."""
        with patch("src.backup.connection.discover_tablet_host") as mock_discover:
            mock_discover.return_value = None

            conn = ReMarkableConnection(use_wifi=True, wifi_host="")

            assert conn.host == USB_HOST

    def test_accepts_injected_credential_store(self):
        """ReMarkableConnection accepts injected credential store."""
        cred_store = InMemoryCredentialStore()

        conn = ReMarkableConnection(credential_store=cred_store)

        assert conn._credential_store is cred_store


class TestReMarkableConnectionCredentials:
    """Tests for credential management."""

    def test_save_password_uses_credential_store(self):
        """save_password delegates to credential store."""
        cred_store = InMemoryCredentialStore()
        conn = ReMarkableConnection(credential_store=cred_store)

        result = conn.save_password("secret123")

        assert result is True
        assert conn.password_saved is True
        assert cred_store.get_password(conn.KEYRING_SERVICE, conn.KEYRING_USERNAME) == "secret123"

    def test_get_saved_password_returns_stored(self):
        """get_saved_password retrieves from credential store."""
        cred_store = InMemoryCredentialStore()
        cred_store.set_password("reMarkableSync", "reMarkable_ssh", "stored_pw")

        conn = ReMarkableConnection(credential_store=cred_store)

        assert conn.get_saved_password() == "stored_pw"

    def test_get_saved_password_returns_none_when_empty(self):
        """get_saved_password returns None when no password stored."""
        cred_store = InMemoryCredentialStore()
        conn = ReMarkableConnection(credential_store=cred_store)

        assert conn.get_saved_password() is None

    def test_delete_saved_password(self):
        """delete_saved_password removes from credential store."""
        cred_store = InMemoryCredentialStore()
        cred_store.set_password("reMarkableSync", "reMarkable_ssh", "pw")

        conn = ReMarkableConnection(credential_store=cred_store)
        result = conn.delete_saved_password()

        assert result is True
        assert conn.get_saved_password() is None


class TestReMarkableConnectionConnect:
    """Tests for SSH connection establishment."""

    def test_connect_fails_on_auth_error(self):
        """connect returns False on authentication failure."""
        cred_store = InMemoryCredentialStore()
        cred_store.set_password("reMarkableSync", "reMarkable_ssh", "wrong_pw")

        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock

            with patch("paramiko.SSHClient") as mock_ssh_class:
                mock_ssh = MagicMock()
                mock_ssh_class.return_value = mock_ssh
                mock_ssh.connect.side_effect = paramiko.AuthenticationException("Bad password")

                # Mock click.confirm to decline re-entering password
                with patch("click.confirm", return_value=False):
                    conn = ReMarkableConnection(credential_store=cred_store)
                    result = conn.connect()

        assert result is False

    def test_connect_fails_on_network_error(self):
        """connect returns False on network error."""
        cred_store = InMemoryCredentialStore()
        cred_store.set_password("reMarkableSync", "reMarkable_ssh", "pw")

        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            # TCP check fails
            mock_sock.connect.side_effect = socket.error("Connection refused")

            conn = ReMarkableConnection(credential_store=cred_store)
            result = conn.connect()

        assert result is False

    def test_connect_fails_if_pre_sync_fails(self):
        """connect returns False if pre_sync_command fails."""
        with patch("src.utils.run_shell_command") as mock_cmd:
            mock_cmd.return_value = 1  # Non-zero exit

            conn = ReMarkableConnection(pre_sync_command="failing_cmd")
            result = conn.connect()

        assert result is False

    def test_connect_calls_pre_sync_command(self):
        """connect executes pre_sync_command when set."""
        with patch("src.utils.run_shell_command") as mock_cmd:
            mock_cmd.return_value = 0

            with patch("socket.socket") as mock_socket_class:
                mock_sock = MagicMock()
                mock_socket_class.return_value = mock_sock
                mock_sock.connect.side_effect = socket.error("fail")

                conn = ReMarkableConnection(pre_sync_command="echo test")
                conn.connect()

        mock_cmd.assert_called_once_with("echo test")


class TestReMarkableConnectionDisconnect:
    """Tests for SSH disconnection."""

    def test_disconnect_closes_clients(self):
        """disconnect closes SSH and SCP clients."""
        conn = ReMarkableConnection()

        # Manually set up mock clients
        mock_scp = MagicMock()
        mock_ssh = MagicMock()
        conn.scp_client = mock_scp
        conn.ssh_client = mock_ssh

        conn.disconnect()

        mock_scp.close.assert_called_once()
        mock_ssh.close.assert_called_once()

    def test_disconnect_runs_post_sync_command(self):
        """disconnect runs post_sync_command after closing."""
        conn = ReMarkableConnection(post_sync_command="echo goodbye")

        # Set up minimal mocks
        conn.scp_client = MagicMock()
        conn.ssh_client = MagicMock()

        with patch("src.utils.run_shell_command") as mock_cmd:
            mock_cmd.return_value = 0
            conn.disconnect()

        mock_cmd.assert_called_with("echo goodbye")

    def test_disconnect_handles_no_connection(self):
        """disconnect handles case where never connected."""
        conn = ReMarkableConnection()
        # Should not raise
        conn.disconnect()


class TestReMarkableConnectionExecute:
    """Tests for remote command execution."""

    def test_execute_command_success(self):
        """execute_command returns stdout on success."""
        conn = ReMarkableConnection()

        # Manually set up mock SSH client
        mock_ssh = MagicMock()
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.read.return_value = b"command output"
        mock_stderr.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_ssh.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)
        conn.ssh_client = mock_ssh

        stdout, stderr, exit_code = conn.execute_command("ls -la")

        assert stdout == "command output"
        assert exit_code == 0

    def test_execute_command_returns_stderr(self):
        """execute_command returns stderr when command fails."""
        conn = ReMarkableConnection()

        mock_ssh = MagicMock()
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.read.return_value = b""
        mock_stderr.read.return_value = b"command not found"
        mock_stdout.channel.recv_exit_status.return_value = 127
        mock_ssh.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)
        conn.ssh_client = mock_ssh

        stdout, stderr, exit_code = conn.execute_command("nonexistent")

        assert stderr == "command not found"
        assert exit_code == 127

    def test_execute_command_raises_when_not_connected(self):
        """execute_command raises ConnectionError when not connected."""
        conn = ReMarkableConnection()

        with pytest.raises(ConnectionError):
            conn.execute_command("ls")


class TestReMarkableConnectionListFiles:
    """Tests for file listing functionality."""

    def test_list_files_parses_stat_output(self):
        """list_files parses 'find -exec stat' output correctly."""
        conn = ReMarkableConnection()

        stat_output = (
            "1700000000 1024 /home/root/.local/share/remarkable/xochitl/file1.metadata\n"
            "1700000001 2048 /home/root/.local/share/remarkable/xochitl/file2.content\n"
        )

        mock_ssh = MagicMock()
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.read.return_value = stat_output.encode()
        mock_stderr.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_ssh.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)
        conn.ssh_client = mock_ssh

        files = conn.list_files("/home/root/.local/share/remarkable/xochitl")

        assert len(files) == 2
        assert files[0]["path"].endswith("file1.metadata")
        assert files[0]["size"] == 1024
        assert files[1]["mtime"] == 1700000001

    def test_list_files_handles_empty_output(self):
        """list_files returns empty list for empty directory."""
        conn = ReMarkableConnection()

        mock_ssh = MagicMock()
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.read.return_value = b""
        mock_stderr.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_ssh.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)
        conn.ssh_client = mock_ssh

        files = conn.list_files("/some/path")

        assert files == []
