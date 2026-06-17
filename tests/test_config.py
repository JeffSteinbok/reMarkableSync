"""
Tests for the config module and mock connection.

Verifies config save/load round-trips and that the mock connection
correctly serves fixture data.
"""

import json
from unittest.mock import patch

import pytest

from tests.mock_connection import MockConnection


class TestMockConnection:
    """Tests for the mock tablet connection."""

    def test_connect_disconnect(self):
        mock = MockConnection()
        assert mock.connect() is True
        mock.disconnect()

    def test_list_files(self):
        mock = MockConnection()
        mock.connect()
        files = mock.list_files("/home/root/.local/share/remarkable/xochitl")
        assert len(files) > 0
        for f in files:
            assert "path" in f
            assert "mtime" in f
            assert "size" in f
            assert f["path"].startswith("/home/root/.local/share/remarkable/xochitl/")

    def test_execute_find_stat(self):
        mock = MockConnection()
        mock.connect()
        stdout, stderr, exit_code = mock.execute_command(
            "find /home/root/.local/share/remarkable/xochitl -type f -exec stat -c '%Y %s %n' {} \\;"
        )
        assert exit_code == 0
        assert stderr == ""
        lines = [line for line in stdout.strip().split("\n") if line]
        assert len(lines) > 0
        # Each line should be: mtime size path
        for line in lines:
            parts = line.split(" ", 2)
            assert len(parts) == 3
            assert parts[0].isdigit()
            assert parts[1].isdigit()

    def test_execute_cat(self):
        mock = MockConnection()
        mock.connect()
        stdout, stderr, exit_code = mock.execute_command(
            "cat /home/root/.local/share/remarkable/xochitl/aaaa1111-2222-3333-4444-555566667777.metadata"
        )
        assert exit_code == 0
        data = json.loads(stdout)
        assert data["visibleName"] == "Work"
        assert data["type"] == "CollectionType"

    def test_get_top_level_folders(self):
        mock = MockConnection()
        mock.connect()
        folders = mock.get_top_level_folders()
        names = [f["name"] for f in folders]
        assert "Work" in names
        assert "Personal" in names
        assert "Quick sheets" in names
        # "Meeting Notes" is inside Work, should NOT appear
        assert "Meeting Notes" not in names

    def test_get_file_copy(self, tmp_path):
        mock = MockConnection()
        mock.connect()
        dest = tmp_path / "test.metadata"
        mock.get(
            "/home/root/.local/share/remarkable/xochitl/aaaa1111-2222-3333-4444-555566667777.metadata",
            str(dest),
        )
        assert dest.exists()
        data = json.loads(dest.read_text())
        assert data["visibleName"] == "Work"

    def test_not_connected_raises(self):
        mock = MockConnection()
        with pytest.raises(ConnectionError):
            mock.execute_command("ls")
        with pytest.raises(ConnectionError):
            mock.list_files("/home/root/.local/share/remarkable/xochitl")


class TestConfigModule:
    """Tests for the config save/load logic."""

    def test_load_defaults_when_no_file(self, tmp_path):
        from src.config import DEFAULT_CONFIG, load_config

        fake_path = tmp_path / "nonexistent" / "config.json"
        with patch("src.config.get_config_path", return_value=fake_path):
            config = load_config()
        assert config == DEFAULT_CONFIG

    def test_save_and_load_round_trip(self, tmp_path):
        from src.config import load_config, save_config

        fake_path = tmp_path / "remarkablesync" / "config.json"
        test_config = {
            "connection_mode": "wifi",
            "wifi_host": "192.168.1.50",
            "password": "secret",
            "folders": ["Work", "Personal"],
            "sync_actions": ["backup", "pdf", "ocr"],
            "ocr_enabled": True,
            "ocr_output_dir": "",
            "output_dir": "~/Documents/Markdown/Notes",
            "pdf_dir": "~/Documents/RemarkableSync/PDF",
            "ai_provider": "github",
            "embed_images": True,
            "ai_model": "",
            "ocr_custom_instructions": "",
            "pre_sync_command": "",
            "post_sync_command": "",
        }

        with patch("src.config.get_config_path", return_value=fake_path):
            save_config(test_config)
            loaded = load_config()

        assert loaded == test_config

    def test_load_merges_new_keys(self, tmp_path):
        """Config saved with older version (missing keys) gets defaults merged."""
        from src.config import load_config

        fake_path = tmp_path / "config.json"
        fake_path.parent.mkdir(parents=True, exist_ok=True)
        # Write a minimal config missing some keys
        fake_path.write_text(json.dumps({"connection_mode": "wifi"}))

        with patch("src.config.get_config_path", return_value=fake_path):
            loaded = load_config()

        assert loaded["connection_mode"] == "wifi"
        assert "sync_actions" in loaded  # merged from defaults
        assert loaded["sync_actions"] == ["backup", "pdf", "ocr"]  # default + cascade
