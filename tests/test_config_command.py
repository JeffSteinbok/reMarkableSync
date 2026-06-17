import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest


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
