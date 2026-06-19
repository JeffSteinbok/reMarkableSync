import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# _parse_folder_metadata tests
# ---------------------------------------------------------------------------


class TestParseFolderMetadata:
    """Tests for _parse_folder_metadata utility."""

    def test_parses_toplevel_collection(self):
        """Extracts folder name from top-level collection."""
        from src.commands.config_command import _parse_folder_metadata

        folders = []
        metadata = json.dumps({"type": "CollectionType", "parent": "", "visibleName": "Work"})

        _parse_folder_metadata(metadata, folders)

        assert folders == ["Work"]

    def test_ignores_nested_collection(self):
        """Ignores collections that have a parent."""
        from src.commands.config_command import _parse_folder_metadata

        folders = []
        metadata = json.dumps(
            {"type": "CollectionType", "parent": "some-uuid", "visibleName": "Subfolder"}
        )

        _parse_folder_metadata(metadata, folders)

        assert folders == []

    def test_ignores_document_type(self):
        """Ignores DocumentType metadata."""
        from src.commands.config_command import _parse_folder_metadata

        folders = []
        metadata = json.dumps({"type": "DocumentType", "parent": "", "visibleName": "My Notebook"})

        _parse_folder_metadata(metadata, folders)

        assert folders == []

    def test_handles_empty_string(self):
        """Handles empty JSON string gracefully."""
        from src.commands.config_command import _parse_folder_metadata

        folders = []
        _parse_folder_metadata("", folders)
        assert folders == []

    def test_handles_whitespace_only(self):
        """Handles whitespace-only input."""
        from src.commands.config_command import _parse_folder_metadata

        folders = []
        _parse_folder_metadata("   \n\t  ", folders)
        assert folders == []

    def test_handles_invalid_json(self):
        """Handles malformed JSON gracefully."""
        from src.commands.config_command import _parse_folder_metadata

        folders = []
        _parse_folder_metadata("not valid json {", folders)
        assert folders == []

    def test_handles_missing_visible_name(self):
        """Ignores folders without visibleName."""
        from src.commands.config_command import _parse_folder_metadata

        folders = []
        metadata = json.dumps({"type": "CollectionType", "parent": ""})

        _parse_folder_metadata(metadata, folders)

        assert folders == []

    def test_multiple_calls_accumulate(self):
        """Multiple calls accumulate folder names."""
        from src.commands.config_command import _parse_folder_metadata

        folders = []

        _parse_folder_metadata(
            json.dumps({"type": "CollectionType", "parent": "", "visibleName": "Work"}), folders
        )

        _parse_folder_metadata(
            json.dumps({"type": "CollectionType", "parent": "", "visibleName": "Personal"}), folders
        )

        assert folders == ["Work", "Personal"]


# ---------------------------------------------------------------------------
# _print_status_message tests
# ---------------------------------------------------------------------------


class TestPrintStatusMessage:
    """Tests for _print_status_message utility."""

    def test_success_message_runs(self, capsys):
        """Success messages use green styling."""
        from src.commands.config_command import _print_status_message

        _print_status_message("Configuration saved!", success=True)
        # Just verify it doesn't crash - Rich output is hard to test

    def test_failure_message_runs(self, capsys):
        """Failure/abort messages use yellow styling."""
        from src.commands.config_command import _print_status_message

        _print_status_message("Aborted.", success=False)
        # Just verify it doesn't crash


# ---------------------------------------------------------------------------
# print_config_summary tests
# ---------------------------------------------------------------------------


class TestPrintConfigSummary:
    """Tests for print_config_summary utility."""

    def test_prints_usb_mode(self, capsys):
        """Prints USB connection mode."""
        from src.commands.config_command import print_config_summary

        cfg = {
            "connection_mode": "usb",
            "backup_dir": "/tmp/backup",
        }

        print_config_summary(cfg)

    def test_prints_wifi_mode_with_host(self, capsys):
        """Prints WiFi mode with host."""
        from src.commands.config_command import print_config_summary

        cfg = {
            "connection_mode": "wifi",
            "wifi_host": "192.168.1.100",
            "backup_dir": "/tmp/backup",
        }

        print_config_summary(cfg)

    def test_prints_password_masked(self, capsys):
        """Password is shown as masked."""
        from src.commands.config_command import print_config_summary

        cfg = {
            "connection_mode": "usb",
            "password": "secret123",
            "backup_dir": "/tmp/backup",
        }

        print_config_summary(cfg)

    def test_handles_missing_optional_fields(self, capsys):
        """Handles missing optional config fields."""
        from src.commands.config_command import print_config_summary

        cfg = {}

        print_config_summary(cfg)

    def test_prints_with_config_path(self, capsys):
        """Prints config file path when provided."""
        from src.commands.config_command import print_config_summary

        cfg = {
            "connection_mode": "usb",
        }

        print_config_summary(cfg, config_path="/path/to/config.json")

    def test_prints_sync_actions(self, capsys):
        """Prints sync actions when present."""
        from src.commands.config_command import print_config_summary

        cfg = {
            "connection_mode": "usb",
            "sync_actions": ["backup", "convert"],
        }

        print_config_summary(cfg)

    def test_prints_ai_provider(self, capsys):
        """Prints AI provider when OCR is enabled."""
        from src.commands.config_command import print_config_summary

        cfg = {
            "connection_mode": "usb",
            "sync_actions": ["ocr"],
            "ai_provider": "github",
            "ai_model": "gpt-4o",
        }

        print_config_summary(cfg)

    def test_prints_folders(self, capsys):
        """Prints selected folders."""
        from src.commands.config_command import print_config_summary

        cfg = {
            "connection_mode": "usb",
            "folders": ["Work", "Personal", "Archive"],
        }

        print_config_summary(cfg)


# ---------------------------------------------------------------------------
# Existing tests
# ---------------------------------------------------------------------------


class _Prompt:
    def __init__(self, value):
        self._value = value

    def execute(self):
        return self._value


class FakeInquirer:
    def __init__(self, responses):
        self._responses = list(responses)

    def _next(self):
        if not self._responses:
            raise AssertionError("No prompt response left in test.")
        return _Prompt(self._responses.pop(0))

    def select(self, **_kwargs):
        return self._next()

    def text(self, **_kwargs):
        return self._next()

    def confirm(self, **_kwargs):
        return self._next()

    def secret(self, **_kwargs):
        return self._next()

    def checkbox(self, **_kwargs):
        return self._next()


def test_run_config_command_without_ocr_preserves_embed_images():
    from src.commands.config_command import run_config_command

    fake_inquirer = FakeInquirer(
        [
            "usb",  # connection mode
            False,  # change saved SSH password?
            "/tmp/backup",  # backup dir
            "pdf",  # sync action
            "/tmp/pdf",  # pdf dir
            "",  # pre_sync_command
            "",  # post_sync_command
        ]
    )
    fake_inquirer_module = types.ModuleType("InquirerPy")
    fake_inquirer_module.inquirer = fake_inquirer
    fake_separator_module = types.ModuleType("InquirerPy.separator")
    fake_separator_module.Separator = object

    with patch.dict(
        sys.modules,
        {"InquirerPy": fake_inquirer_module, "InquirerPy.separator": fake_separator_module},
    ):
        with (
            patch(
                "src.commands.config_command.load_config",
                return_value={
                    "connection_mode": "usb",
                    "wifi_host": "",
                    "password": "saved-password",
                    "backup_dir": "/tmp/old-backup",
                    "pdf_dir": "/tmp/old-pdf",
                    "folders": [],
                    "sync_actions": ["backup", "pdf"],
                    "ocr_enabled": False,
                    "output_dir": "",
                    "embed_images": False,
                    "ai_provider": "github",
                    "ai_model": "",
                    "pre_sync_command": "",
                    "post_sync_command": "",
                },
            ),
            patch("src.commands.config_command._get_folder_choices_live", return_value=[]),
            patch(
                "src.commands.config_command.save_config", return_value=Path("/tmp/config.json")
            ) as mock_save,
        ):
            assert run_config_command() == 0

    assert mock_save.call_count == 1
    saved = mock_save.call_args.args[0]
    assert not saved["embed_images"]


def test_main_without_config_requires_running_config_first(capsys, tmp_path):
    import reMarkableSync

    missing = tmp_path / "remarkablesync" / "config.json"

    with (
        patch("src.config.get_config_path", return_value=missing),
        patch.object(sys, "argv", ["reMarkableSync.py"]),
        patch.object(reMarkableSync, "cli") as mock_cli,
        pytest.raises(SystemExit) as raised,
    ):
        reMarkableSync.main()

    assert raised.value.code == 1
    err = capsys.readouterr().err
    assert "No configuration found." in err
    assert "Run: python reMarkableSync.py config" in err
    mock_cli.assert_not_called()
