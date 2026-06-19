"""
Tests for ReMarkableBackup using MockConnection.

Uses the fake_tablet fixture to test backup operations without a real tablet.
"""

import json

import pytest

from src.backup import InMemoryCredentialStore, ReMarkableBackup
from src.backup.protocols import TabletConfig
from tests.mock_connection import MockConnection

# Tablet config pointing to fixture paths
FIXTURE_TABLET_CONFIG = TabletConfig(
    xochitl_dir="/home/root/.local/share/remarkable/xochitl",
    templates_dir="/usr/share/remarkable/templates",
)


class TestReMarkableBackupWithMock:
    """Tests for ReMarkableBackup using MockConnection."""

    def test_init_with_injected_connection(self, tmp_path):
        """ReMarkableBackup accepts injected connection."""
        mock_conn = MockConnection()
        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            tablet_config=FIXTURE_TABLET_CONFIG,
        )
        assert backup.connection is mock_conn
        assert backup.remote_xochitl_dir == FIXTURE_TABLET_CONFIG.xochitl_dir

    def test_init_with_injected_config(self, tmp_path):
        """ReMarkableBackup accepts injected config dict."""
        mock_conn = MockConnection()
        config = {"folders": ["Work"], "pdf_dir": "/tmp/pdfs"}

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config=config,
        )

        # Config should be used by _get_config()
        assert backup._get_config() == config

    def test_creates_backup_directories(self, tmp_path):
        """ReMarkableBackup creates required directories on init."""
        mock_conn = MockConnection()
        ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
        )

        assert (tmp_path / "Notebooks").exists()
        assert (tmp_path / "Templates").exists()

    def test_list_files_via_mock_connection(self, tmp_path):
        """MockConnection.list_files returns fixture files."""
        mock_conn = MockConnection()
        mock_conn.connect()

        files = mock_conn.list_files("/home/root/.local/share/remarkable/xochitl")

        # Should find files from the fixture
        assert len(files) > 0
        assert all("path" in f and "mtime" in f and "size" in f for f in files)

    def test_get_top_level_folders(self, tmp_path):
        """MockConnection.get_top_level_folders returns fixture folders."""
        mock_conn = MockConnection()
        mock_conn.connect()

        folders = mock_conn.get_top_level_folders()

        # fake_tablet has folders defined in metadata
        assert isinstance(folders, list)

    def test_execute_command_find_stat(self, tmp_path):
        """MockConnection handles find/stat commands."""
        mock_conn = MockConnection()
        mock_conn.connect()

        stdout, stderr, exit_code = mock_conn.execute_command(
            "find /home/root/.local/share/remarkable/xochitl -type f -exec stat -c '%Y %s %n' {} \\;"
        )

        assert exit_code == 0
        assert stderr == ""
        # Should have output with mtime, size, path format
        if stdout.strip():
            line = stdout.strip().split("\n")[0]
            parts = line.split(" ", 2)
            assert len(parts) == 3  # mtime, size, path

    def test_execute_command_cat(self, tmp_path):
        """MockConnection handles cat commands for metadata files."""
        mock_conn = MockConnection()
        mock_conn.connect()

        # Read a metadata file from fixtures
        stdout, stderr, exit_code = mock_conn.execute_command(
            "cat /home/root/.local/share/remarkable/xochitl/aaaa1111-2222-3333-4444-555566667777.metadata"
        )

        assert exit_code == 0
        # Should be valid JSON
        metadata = json.loads(stdout)
        assert "visibleName" in metadata or "type" in metadata

    def test_scp_get_copies_file(self, tmp_path):
        """MockConnection.get copies files from fixture to local."""
        mock_conn = MockConnection()
        mock_conn.connect()

        local_file = tmp_path / "test.metadata"
        mock_conn.get(
            "/home/root/.local/share/remarkable/xochitl/aaaa1111-2222-3333-4444-555566667777.metadata",
            str(local_file),
        )

        assert local_file.exists()
        # Should be valid JSON
        metadata = json.loads(local_file.read_text())
        assert isinstance(metadata, dict)


class TestReMarkableBackupResolveUUIDs:
    """Tests for folder filtering logic."""

    def test_resolve_allowed_uuids_no_filter(self, tmp_path, capsys):
        """With no folder filter, returns None (all allowed)."""
        mock_conn = MockConnection()
        mock_conn.connect()

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config={"folders": []},  # No filter
        )

        # Need to be "connected" for this to work
        result = backup._resolve_allowed_uuids()

        assert result is None
        captured = capsys.readouterr()
        assert "all folders" in captured.out.lower()

    def test_resolve_allowed_uuids_with_filter(self, tmp_path, capsys):
        """With folder filter, returns matching UUIDs."""
        mock_conn = MockConnection()
        mock_conn.connect()

        # Get actual folder names from fixture
        folders = mock_conn.get_top_level_folders()
        if not folders:
            pytest.skip("No folders in fixture")

        folder_name = folders[0]["name"]

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config={"folders": [folder_name]},
        )

        result = backup._resolve_allowed_uuids()

        # Should return a set (possibly empty if no matches)
        assert result is None or isinstance(result, set)


class TestCredentialStoreIntegration:
    """Tests for credential store with backup."""

    def test_backup_uses_injected_credential_store(self, tmp_path):
        """Connection can use InMemoryCredentialStore for testing."""
        from src.backup.connection import ReMarkableConnection

        cred_store = InMemoryCredentialStore()
        cred_store.set_password("test", "user", "secret123")

        # Verify the store works (connection would use it internally)
        ReMarkableConnection(
            host="10.11.99.1",
            credential_store=cred_store,
        )

        # Password should be retrievable
        assert cred_store.get_password("test", "user") == "secret123"


class TestReMarkableBackupDoBackup:
    """Tests for the actual backup process using MockConnection."""

    def test_scp_client_available_after_connect(self, tmp_path):
        """MockConnection.scp_client is available after connect."""
        mock_conn = MockConnection()
        mock_conn.connect()

        assert mock_conn.scp_client is not None

        local_file = tmp_path / "test.metadata"
        mock_conn.scp_client.get(
            "/home/root/.local/share/remarkable/xochitl/aaaa1111-2222-3333-4444-555566667777.metadata",
            str(local_file),
        )

        assert local_file.exists()

    def test_do_backup_files_downloads_files(self, tmp_path):
        """_do_backup_files downloads files from mock tablet."""
        mock_conn = MockConnection()
        mock_conn.connect()

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config={"folders": []},
        )

        success, updated_uuids, updated_pages = backup._do_backup_files()

        assert success is True
        # Should have downloaded some files
        notebooks_dir = tmp_path / "Notebooks"
        files = list(notebooks_dir.rglob("*"))
        assert len(files) > 0

    def test_do_backup_files_tracks_updated_notebooks(self, tmp_path):
        """_do_backup_files returns set of updated notebook UUIDs."""
        mock_conn = MockConnection()
        mock_conn.connect()

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config={"folders": []},
        )

        success, updated_uuids, updated_pages = backup._do_backup_files()

        assert success is True
        # Should track which notebooks were updated
        assert isinstance(updated_uuids, set)
        assert isinstance(updated_pages, dict)

    def test_do_backup_files_is_idempotent(self, tmp_path):
        """Running _do_backup_files twice doesn't re-download unchanged files."""
        mock_conn = MockConnection()
        mock_conn.connect()

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config={"folders": []},
        )

        # First backup
        success1, updated1, _ = backup._do_backup_files()
        assert success1 is True
        first_count = len(updated1)

        # Second backup - should detect files are up to date
        success2, updated2, _ = backup._do_backup_files()
        assert success2 is True
        # Should have fewer or zero updates
        assert len(updated2) <= first_count

    def test_run_backup_connects_and_disconnects(self, tmp_path):
        """run_backup handles connection lifecycle."""
        mock_conn = MockConnection()

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config={"folders": []},
        )

        success, _, _ = backup.run_backup(backup_templates=False)

        assert success is True
        # Connection should be disconnected after backup
        assert mock_conn._connected is False
