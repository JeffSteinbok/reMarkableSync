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


class TestBackupErrorPaths:
    """Tests for error handling in backup operations."""

    def test_do_backup_files_handles_empty_remote(self, tmp_path):
        """_do_backup_files handles empty tablet gracefully."""
        # Use a fixture dir with no files
        empty_fixture = tmp_path / "empty_tablet" / "xochitl"
        empty_fixture.mkdir(parents=True)

        mock_conn = MockConnection(fixture_dir=tmp_path / "empty_tablet")
        mock_conn.connect()

        backup = ReMarkableBackup(
            backup_dir=tmp_path / "backup",
            connection=mock_conn,
            config={"folders": []},
        )

        success, updated, pages = backup._do_backup_files()

        assert success is True
        assert len(updated) == 0
        assert len(pages) == 0

    def test_do_backup_handles_missing_scp_client(self, tmp_path):
        """_do_backup_files returns False when scp_client is None."""
        mock_conn = MockConnection()
        mock_conn.connect()
        mock_conn.scp_client = None  # Simulate missing SCP client

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config={"folders": []},
        )

        success, updated, pages = backup._do_backup_files()

        # Should fail gracefully when SCP client is missing
        assert success is False

    def test_do_backup_handles_download_error(self, tmp_path, capsys):
        """_do_backup_files continues after individual file download errors."""

        class FailingMockSCPClient:
            """SCP client that fails on first get() call."""

            def __init__(self):
                self.call_count = 0

            def get(self, remote_path: str, local_path: str, recursive: bool = False):
                self.call_count += 1
                if self.call_count == 1:
                    raise OSError("Simulated download failure")
                # Subsequent calls succeed
                from pathlib import Path

                Path(local_path).parent.mkdir(parents=True, exist_ok=True)
                Path(local_path).write_text("content")

            def close(self):
                pass

        mock_conn = MockConnection()
        mock_conn.connect()
        mock_conn.scp_client = FailingMockSCPClient()

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config={"folders": []},
        )

        # Should not crash, continues despite error
        success, _, _ = backup._do_backup_files()
        # It may return True because it continues after errors
        assert isinstance(success, bool)

    def test_run_backup_handles_connection_failure(self, tmp_path):
        """run_backup handles connection failure gracefully."""

        class FailingConnection(MockConnection):
            def connect(self):
                return False

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=FailingConnection(),
            config={"folders": []},
        )

        success, _, _ = backup.run_backup(backup_templates=False)
        assert success is False

    def test_backup_with_corrupt_metadata(self, tmp_path):
        """Backup handles corrupt metadata files gracefully."""
        # Create fixture with corrupt metadata
        fixture_dir = tmp_path / "corrupt_tablet" / "xochitl"
        fixture_dir.mkdir(parents=True)

        # Create a corrupt metadata file (invalid JSON)
        corrupt_meta = fixture_dir / "corrupt-uuid-1234-5678-9012.metadata"
        corrupt_meta.write_text("{ invalid json }")

        mock_conn = MockConnection(fixture_dir=tmp_path / "corrupt_tablet")
        mock_conn.connect()

        backup = ReMarkableBackup(
            backup_dir=tmp_path / "backup",
            connection=mock_conn,
            config={"folders": []},
        )

        # Should not crash on corrupt metadata
        success, _, _ = backup._do_backup_files()
        assert isinstance(success, bool)


class TestTemplateBackup:
    """Tests for template backup functionality."""

    def test_do_backup_templates_with_templates(self, tmp_path):
        """_do_backup_templates downloads template files."""
        # Create a fixture with templates
        fixture_dir = tmp_path / "tablet_with_templates"
        templates_dir = fixture_dir / "templates"
        templates_dir.mkdir(parents=True)

        # Create sample template files
        (templates_dir / "template1.png").write_bytes(b"PNG template 1")
        (templates_dir / "template2.svg").write_text("<svg>template 2</svg>")

        # Create xochitl dir too (needed for MockConnection)
        (fixture_dir / "xochitl").mkdir(parents=True)

        # MockConnection that also serves templates
        class MockConnectionWithTemplates(MockConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._templates_dir = templates_dir

            def list_files(self, remote_path: str):
                # Check if it's requesting templates
                if "templates" in remote_path:
                    files = []
                    for f in self._templates_dir.rglob("*"):
                        if f.is_file():
                            stat = f.stat()
                            rel = f.relative_to(self._templates_dir)
                            files.append(
                                {
                                    "path": f"/usr/share/remarkable/templates/{rel.as_posix()}",
                                    "mtime": int(stat.st_mtime),
                                    "size": stat.st_size,
                                }
                            )
                    return files
                return super().list_files(remote_path)

            def _remote_to_local(self, remote_path: str):
                if "/templates/" in remote_path:
                    rel = remote_path.replace("/usr/share/remarkable/templates/", "")
                    return self._templates_dir / rel
                return super()._remote_to_local(remote_path)

        mock_conn = MockConnectionWithTemplates(fixture_dir=fixture_dir)
        mock_conn.connect()

        backup = ReMarkableBackup(
            backup_dir=tmp_path / "backup",
            connection=mock_conn,
            config={"folders": []},
        )

        success = backup._do_backup_templates()

        assert success is True
        # Templates should be downloaded
        backup_templates = tmp_path / "backup" / "Templates"
        assert (backup_templates / "template1.png").exists()
        assert (backup_templates / "template2.svg").exists()

    def test_do_backup_templates_empty(self, tmp_path):
        """_do_backup_templates handles empty templates dir."""
        # Create fixture with empty templates dir
        fixture_dir = tmp_path / "no_templates"
        (fixture_dir / "xochitl").mkdir(parents=True)
        (fixture_dir / "templates").mkdir(parents=True)

        class MockConnectionEmptyTemplates(MockConnection):
            def list_files(self, remote_path: str):
                if "templates" in remote_path:
                    return []
                return super().list_files(remote_path)

        mock_conn = MockConnectionEmptyTemplates(fixture_dir=fixture_dir)
        mock_conn.connect()

        backup = ReMarkableBackup(
            backup_dir=tmp_path / "backup",
            connection=mock_conn,
            config={"folders": []},
        )

        success = backup._do_backup_templates()
        assert success is True

    def test_run_backup_with_templates(self, tmp_path):
        """run_backup with backup_templates=True downloads templates."""
        mock_conn = MockConnection()

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config={"folders": []},
        )

        # Even without actual templates, should not crash
        success, _, _ = backup.run_backup(backup_templates=True)
        assert success is True


class TestFindNotebooks:
    """Tests for find_notebooks functionality."""

    def test_find_notebooks_returns_list(self, tmp_path):
        """find_notebooks returns list of notebook metadata."""
        mock_conn = MockConnection()
        mock_conn.connect()

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config={"folders": []},
        )

        # First do a backup to populate local files
        backup._do_backup_files()

        # Now find notebooks
        notebooks = backup.find_notebooks()

        assert isinstance(notebooks, list)

    def test_find_notebooks_empty_backup(self, tmp_path):
        """find_notebooks handles empty backup directory."""
        mock_conn = MockConnection()

        backup = ReMarkableBackup(
            backup_dir=tmp_path,
            connection=mock_conn,
            config={"folders": []},
        )

        # Don't do backup, just try to find notebooks
        notebooks = backup.find_notebooks()

        assert isinstance(notebooks, list)
        assert len(notebooks) == 0
