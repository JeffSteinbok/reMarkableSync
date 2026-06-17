"""Tests for CLI command entry-point modules.

Covers backup_command, convert_command, sync_command, and watch_command.
All I/O-heavy dependencies (SSH connections, file system writes, tablet
communication) are mocked.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, **overrides) -> Path:
    """Write a minimal config.json and return its path."""
    cfg = {
        "connection_mode": "usb",
        "wifi_host": "",
        "password": "",
        "backup_dir": str(tmp_path / "backup"),
        "pdf_dir": str(tmp_path / "pdf"),
        "folders": [],
        "sync_actions": ["backup", "pdf"],
        "ocr_enabled": False,
        "output_dir": "",
        "embed_images": False,
        "ai_provider": "github",
        "ai_model": "",
        "pre_sync_command": "",
        "post_sync_command": "",
    }
    cfg.update(overrides)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg_path


# ---------------------------------------------------------------------------
# backup_command
# ---------------------------------------------------------------------------


class TestRunBackupCommand:
    """Tests for backup_command.run_backup_command()."""

    def _run(self, tmp_path, **kwargs):
        from src.commands.backup_command import run_backup_command

        defaults = {
            "backup_dir": tmp_path / "backup",
            "password": None,
            "log_level": "WRN",
            "skip_templates": False,
            "force": False,
        }
        defaults.update(kwargs)
        defaults["backup_dir"].mkdir(parents=True, exist_ok=True)
        return run_backup_command(**defaults)

    @patch("src.commands.backup_command.ReMarkableBackup")
    def test_successful_backup_returns_zero(self, mock_backup_cls, tmp_path):
        mock_backup = MagicMock()
        mock_backup.run_backup.return_value = (True, set(), {})
        mock_backup.files_dir = tmp_path / "backup" / "Notebooks"
        mock_backup.templates_dir = tmp_path / "backup" / "Templates"
        mock_backup_cls.return_value = mock_backup

        result = self._run(tmp_path)
        assert result == 0

    @patch("src.commands.backup_command.ReMarkableBackup")
    def test_failed_backup_returns_one(self, mock_backup_cls, tmp_path):
        mock_backup = MagicMock()
        mock_backup.run_backup.return_value = (False, set(), {})
        mock_backup_cls.return_value = mock_backup

        result = self._run(tmp_path)
        assert result == 1

    @patch("src.commands.backup_command.ReMarkableBackup")
    def test_keyboard_interrupt_returns_130(self, mock_backup_cls, tmp_path):
        mock_backup = MagicMock()
        mock_backup.run_backup.side_effect = KeyboardInterrupt
        mock_backup_cls.return_value = mock_backup

        result = self._run(tmp_path)
        assert result == 130

    @patch("src.commands.backup_command.ReMarkableBackup")
    def test_unexpected_exception_returns_one(self, mock_backup_cls, tmp_path):
        mock_backup = MagicMock()
        mock_backup.run_backup.side_effect = RuntimeError("Connection refused")
        mock_backup_cls.return_value = mock_backup

        result = self._run(tmp_path)
        assert result == 1

    @patch("src.commands.backup_command.ReMarkableBackup")
    def test_skip_templates_flag_passed(self, mock_backup_cls, tmp_path):
        mock_backup = MagicMock()
        mock_backup.run_backup.return_value = (True, set(), {})
        mock_backup.files_dir = tmp_path / "backup" / "Notebooks"
        mock_backup.templates_dir = tmp_path / "backup" / "Templates"
        mock_backup_cls.return_value = mock_backup

        self._run(tmp_path, skip_templates=True)

        call_kwargs = mock_backup.run_backup.call_args.kwargs
        assert call_kwargs.get("backup_templates") is False

    @patch("src.commands.backup_command.ReMarkableBackup")
    def test_wifi_mode_reported(self, mock_backup_cls, tmp_path, capsys):
        mock_backup = MagicMock()
        mock_backup.run_backup.return_value = (True, set(), {})
        mock_backup.files_dir = tmp_path / "backup" / "Notebooks"
        mock_backup.templates_dir = tmp_path / "backup" / "Templates"
        mock_backup_cls.return_value = mock_backup

        self._run(tmp_path, use_wifi=True, wifi_host="192.168.1.100")
        captured = capsys.readouterr()
        assert "Wi-Fi" in captured.out


# ---------------------------------------------------------------------------
# convert_command
# ---------------------------------------------------------------------------


class TestRunConvertCommand:
    """Tests for convert_command.run_convert_command()."""

    def _run(self, tmp_path, **kwargs):
        from src.commands.convert_command import run_convert_command

        backup_dir = tmp_path / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        output_dir = tmp_path / "pdf"
        output_dir.mkdir(parents=True, exist_ok=True)

        defaults = {
            "backup_dir": backup_dir,
            "output_dir": output_dir,
            "log_level": "WRN",
            "force_all": False,
            "sample": None,
            "notebook": None,
        }
        defaults.update(kwargs)
        return run_convert_command(**defaults)

    def test_missing_backup_dir_returns_one(self, tmp_path):
        from src.commands.convert_command import run_convert_command

        result = run_convert_command(
            backup_dir=tmp_path / "no_such_dir",
            output_dir=tmp_path / "pdf",
            log_level="WRN",
            force_all=False,
            sample=None,
            notebook=None,
        )
        assert result == 1

    @patch("src.commands.convert_command.run_conversion")
    def test_successful_conversion_returns_zero(self, mock_convert, tmp_path):
        mock_convert.return_value = (True, {}, [])
        result = self._run(tmp_path)
        assert result == 0

    @patch("src.commands.convert_command.run_conversion")
    def test_failed_conversion_returns_one(self, mock_convert, tmp_path):
        mock_convert.return_value = (False, {}, [])
        result = self._run(tmp_path)
        assert result == 1

    @patch("src.commands.convert_command.run_conversion")
    def test_keyboard_interrupt_returns_130(self, mock_convert, tmp_path):
        mock_convert.side_effect = KeyboardInterrupt
        result = self._run(tmp_path)
        assert result == 130

    @patch("src.commands.convert_command.run_conversion")
    def test_exception_returns_one(self, mock_convert, tmp_path):
        mock_convert.side_effect = RuntimeError("Boom")
        result = self._run(tmp_path)
        assert result == 1

    @patch("src.commands.convert_command.run_conversion")
    def test_sample_passed_to_run_conversion(self, mock_convert, tmp_path):
        mock_convert.return_value = (True, {}, [])
        self._run(tmp_path, sample=3)
        call_kwargs = mock_convert.call_args.kwargs
        assert call_kwargs.get("sample") == 3

    @patch("src.commands.convert_command.run_conversion")
    def test_notebook_filter_passed(self, mock_convert, tmp_path):
        mock_convert.return_value = (True, {}, [])
        self._run(tmp_path, notebook="My Notes")
        call_kwargs = mock_convert.call_args.kwargs
        assert call_kwargs.get("notebook_filter") == "My Notes"

    def test_no_output_dir_and_no_config_returns_one(self, tmp_path):
        from src.commands.convert_command import run_convert_command

        backup_dir = tmp_path / "backup"
        backup_dir.mkdir(parents=True)

        with patch("src.config.load_config", return_value={"pdf_dir": ""}):
            result = run_convert_command(
                backup_dir=backup_dir,
                output_dir=None,
                log_level="WRN",
                force_all=False,
                sample=None,
                notebook=None,
            )
        assert result == 1

    @patch("src.commands.convert_command.run_conversion")
    def test_uses_existing_configured_backup_dir_when_cli_default_missing(
        self, mock_convert, tmp_path, monkeypatch
    ):
        from src.commands.convert_command import run_convert_command

        # Change to tmp_path so ./remarkable_backup doesn't exist
        monkeypatch.chdir(tmp_path)

        mock_convert.return_value = (True, {}, [])
        configured_backup = tmp_path / "configured_backup"
        configured_backup.mkdir(parents=True)
        output_dir = tmp_path / "pdf"
        output_dir.mkdir(parents=True)

        with patch("src.config.load_config", return_value={"backup_dir": str(configured_backup)}):
            result = run_convert_command(
                backup_dir=Path("./remarkable_backup"),
                output_dir=output_dir,
                log_level="WRN",
                force_all=False,
                sample=None,
                notebook=None,
            )

        assert result == 0
        assert mock_convert.call_args.kwargs["backup_dir"] == configured_backup

    @patch("src.commands.convert_command.run_conversion")
    def test_creates_configured_backup_dir_when_cli_default_missing(
        self, mock_convert, tmp_path, monkeypatch
    ):
        from src.commands.convert_command import run_convert_command

        # Change to tmp_path so ./remarkable_backup doesn't exist
        monkeypatch.chdir(tmp_path)

        mock_convert.return_value = (True, {}, [])
        configured_backup = tmp_path / "configured_backup"
        output_dir = tmp_path / "pdf"
        output_dir.mkdir(parents=True)

        with patch("src.config.load_config", return_value={"backup_dir": str(configured_backup)}):
            result = run_convert_command(
                backup_dir=Path("./remarkable_backup"),
                output_dir=output_dir,
                log_level="WRN",
                force_all=False,
                sample=None,
                notebook=None,
            )

        assert result == 0
        assert configured_backup.exists()
        assert configured_backup.is_dir()
        assert mock_convert.call_args.kwargs["backup_dir"] == configured_backup

    @patch("src.commands.convert_command.run_conversion")
    def test_absolute_default_backup_dir_still_falls_back_to_config(
        self, mock_convert, tmp_path, monkeypatch
    ):
        from src.commands.convert_command import run_convert_command

        mock_convert.return_value = (True, {}, [])
        configured_backup = tmp_path / "configured_backup"
        configured_backup.mkdir(parents=True)
        output_dir = tmp_path / "pdf"
        output_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)

        with patch("src.config.load_config", return_value={"backup_dir": str(configured_backup)}):
            result = run_convert_command(
                backup_dir=tmp_path / "remarkable_backup",
                output_dir=output_dir,
                log_level="WRN",
                force_all=False,
                sample=None,
                notebook=None,
            )

        assert result == 0
        assert mock_convert.call_args.kwargs["backup_dir"] == configured_backup

    @patch("src.commands.convert_command.run_conversion")
    def test_explicit_missing_backup_dir_does_not_fallback_to_config(self, mock_convert, tmp_path):
        from src.commands.convert_command import run_convert_command

        mock_convert.return_value = (True, {}, [])
        configured_backup = tmp_path / "configured_backup"
        configured_backup.mkdir(parents=True)
        output_dir = tmp_path / "pdf"
        output_dir.mkdir(parents=True)

        with patch("src.config.load_config", return_value={"backup_dir": str(configured_backup)}):
            result = run_convert_command(
                backup_dir=tmp_path / "missing_backup",
                output_dir=output_dir,
                log_level="WRN",
                force_all=False,
                sample=None,
                notebook=None,
            )

        assert result == 1
        assert not mock_convert.called

    @patch("src.commands.convert_command.run_conversion")
    def test_updated_only_file_parsed_as_uuids(self, mock_convert, tmp_path):
        """updated_notebooks.txt UUIDs are passed as updated_uuids set."""
        mock_convert.return_value = (True, {}, [])

        backup_dir = tmp_path / "backup"
        backup_dir.mkdir(parents=True)
        output_dir = tmp_path / "pdf"
        output_dir.mkdir(parents=True)

        updated_file = backup_dir / "updated_notebooks.txt"
        updated_file.write_text("uuid-a\nuuid-b\n", encoding="utf-8")

        from src.commands.convert_command import run_convert_command

        run_convert_command(
            backup_dir=backup_dir,
            output_dir=output_dir,
            log_level="WRN",
            force_all=False,
            sample=None,
            notebook=None,
        )

        call_kwargs = mock_convert.call_args.kwargs
        uuids = call_kwargs.get("updated_uuids")
        assert uuids == {"uuid-a", "uuid-b"}


# ---------------------------------------------------------------------------
# sync_command
# ---------------------------------------------------------------------------


class TestRunSyncCommand:
    """Tests for sync_command.run_sync_command()."""

    def _run(self, tmp_path, **kwargs):
        from src.commands.sync_command import run_sync_command

        backup_dir = tmp_path / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)

        defaults = {
            "backup_dir": backup_dir,
            "password": None,
            "log_level": "WRN",
            "skip_templates": False,
            "force_backup": False,
            "force_convert": False,
        }
        defaults.update(kwargs)
        return run_sync_command(**defaults)

    @patch("src.commands.sync_command.ReMarkableBackup")
    @patch("src.config.load_config")
    def test_successful_sync_returns_zero(self, mock_cfg, mock_backup_cls, tmp_path):
        mock_cfg.return_value = {
            "pdf_dir": str(tmp_path / "pdf"),
            "pre_sync_command": "",
            "post_sync_command": "",
        }
        mock_backup = MagicMock()
        mock_backup.run_backup.return_value = (True, set(), {})
        mock_backup.files_dir = tmp_path / "backup" / "Notebooks"
        mock_backup.templates_dir = tmp_path / "backup" / "Templates"
        mock_backup_cls.return_value = mock_backup
        (tmp_path / "pdf").mkdir(parents=True)

        result = self._run(tmp_path)
        assert result == 0

    @patch("src.commands.sync_command.ReMarkableBackup")
    @patch("src.config.load_config")
    def test_backup_failure_returns_one(self, mock_cfg, mock_backup_cls, tmp_path):
        mock_cfg.return_value = {
            "pdf_dir": str(tmp_path / "pdf"),
            "pre_sync_command": "",
            "post_sync_command": "",
        }
        mock_backup = MagicMock()
        mock_backup.run_backup.return_value = (False, set(), {})
        mock_backup_cls.return_value = mock_backup

        result = self._run(tmp_path)
        assert result == 1

    @patch("src.commands.sync_command.ReMarkableBackup")
    @patch("src.config.load_config")
    def test_keyboard_interrupt_returns_130(self, mock_cfg, mock_backup_cls, tmp_path):
        mock_cfg.return_value = {"pdf_dir": "", "pre_sync_command": "", "post_sync_command": ""}
        mock_backup = MagicMock()
        mock_backup.run_backup.side_effect = KeyboardInterrupt
        mock_backup_cls.return_value = mock_backup

        result = self._run(tmp_path)
        assert result == 130

    @patch("src.commands.sync_command.ReMarkableBackup")
    @patch("src.config.load_config")
    def test_exception_returns_one(self, mock_cfg, mock_backup_cls, tmp_path):
        mock_cfg.return_value = {"pdf_dir": "", "pre_sync_command": "", "post_sync_command": ""}
        mock_backup = MagicMock()
        mock_backup.run_backup.side_effect = RuntimeError("Timeout")
        mock_backup_cls.return_value = mock_backup

        result = self._run(tmp_path)
        assert result == 1

    @patch("src.commands.sync_command.ReMarkableBackup")
    @patch("src.config.load_config")
    def test_force_convert_passed_to_backup(self, mock_cfg, mock_backup_cls, tmp_path):
        mock_cfg.return_value = {"pdf_dir": "", "pre_sync_command": "", "post_sync_command": ""}
        mock_backup = MagicMock()
        mock_backup.run_backup.return_value = (True, set(), {})
        mock_backup.files_dir = tmp_path / "Notebooks"
        mock_backup.templates_dir = tmp_path / "Templates"
        mock_backup_cls.return_value = mock_backup

        self._run(tmp_path, force_convert=True)

        call_kwargs = mock_backup.run_backup.call_args.kwargs
        assert call_kwargs.get("force_convert_all") is True


# ---------------------------------------------------------------------------
# backup_manager
# ---------------------------------------------------------------------------


class TestBackupManager:
    """Tests for backup_manager conversion integration behavior."""

    @patch("src.config.load_config")
    @patch("src.rm_pdf_converter.run_conversion")
    def test_run_pdf_conversion_accepts_three_value_return(
        self, mock_run_conversion, mock_cfg, tmp_path
    ):
        from src.backup.backup_manager import ReMarkableBackup

        mock_cfg.return_value = {"pdf_dir": str(tmp_path / "pdf"), "folders": []}
        mock_run_conversion.return_value = (True, {}, [])
        (tmp_path / "pdf").mkdir(parents=True)

        backup = ReMarkableBackup(tmp_path / "backup")
        result = backup.run_pdf_conversion({"uuid-1"}, force_convert_all=False, updated_pages={})

        assert result is True
        assert mock_run_conversion.called


# ---------------------------------------------------------------------------
# watch_command — launch args
# ---------------------------------------------------------------------------


class TestWatchLaunchArgs:
    """Tests for watch background-launch command construction."""

    def test_script_entrypoint_launches_script_directly(self, monkeypatch, tmp_path):
        """A real .py entrypoint can be launched directly."""
        from src.commands import watch_command

        script = tmp_path / "reMarkableSync.py"
        script.write_text("print('ok')", encoding="utf-8")

        monkeypatch.setattr(sys, "argv", [str(script)])
        monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
        monkeypatch.setattr(watch_command.sys, "platform", "win32")

        args = watch_command._build_watch_launch_args()

        assert args == [str(tmp_path / "python.exe"), str(script), "watch", "--foreground"]

    def test_console_launcher_uses_module_mode(self, monkeypatch, tmp_path):
        """Installed console-script .exe launchers must be invoked via -m."""
        from src.commands import watch_command

        launcher = tmp_path / "reMarkableSync.exe"
        launcher.write_text("", encoding="utf-8")

        monkeypatch.setattr(sys, "argv", [str(launcher)])
        monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
        monkeypatch.setattr(watch_command.sys, "platform", "win32")

        args = watch_command._build_watch_launch_args()

        assert args == [
            str(tmp_path / "python.exe"),
            "-m",
            "reMarkableSync",
            "watch",
            "--foreground",
        ]

    def test_get_watch_command_line_quotes_module_launch(self, monkeypatch, tmp_path):
        """Startup command line should use the same safe launch path."""
        from src.commands import watch_command

        launcher = tmp_path / "Scripts" / "reMarkableSync.exe"
        python = tmp_path / "Python 313" / "python.exe"

        monkeypatch.setattr(sys, "argv", [str(launcher)])
        monkeypatch.setattr(sys, "executable", str(python))
        monkeypatch.setattr(watch_command.sys, "platform", "win32")

        cmd_line = watch_command._get_watch_command_line()

        assert "-m reMarkableSync watch --foreground" in cmd_line
        assert str(python) in cmd_line


# ---------------------------------------------------------------------------
# watch_command — FileLock
# ---------------------------------------------------------------------------


class TestFileLock:
    """Tests for the watch_command FileLock."""

    def test_acquire_and_release(self, tmp_path):
        from src.commands.watch_command import FileLock

        lock = FileLock(tmp_path / ".test.lock")
        assert lock.acquire() is True
        lock.release()
        assert not (tmp_path / ".test.lock").exists()

    def test_double_acquire_fails(self, tmp_path):
        from src.commands.watch_command import FileLock

        lock1 = FileLock(tmp_path / ".test.lock")
        lock2 = FileLock(tmp_path / ".test.lock")
        assert lock1.acquire() is True
        try:
            result = lock2.acquire()
            assert result is False
        finally:
            lock1.release()

    def test_release_without_acquire_is_safe(self, tmp_path):
        from src.commands.watch_command import FileLock

        lock = FileLock(tmp_path / ".test.lock")
        lock.release()  # Should not raise


# ---------------------------------------------------------------------------
# watch_command — run_watch_command (smoke test, no infinite loop)
# ---------------------------------------------------------------------------


class TestRunWatchCommand:
    """Tests for run_watch_command() — exercises setup logic with mocked loop."""

    def _make_handler_mock(self):
        """Return a mock handler that won't confuse Python's logging system."""
        import logging as _logging

        h = MagicMock(spec=_logging.Handler)
        h.level = _logging.NOTSET
        return h

    def test_quit_immediately_returns_zero(self, tmp_path, capsys):
        """Simulate quitting right away via the quit_event."""
        from src.commands.watch_command import run_watch_command

        call_count = [0]

        def _run_once():
            call_count[0] += 1
            return 0

        tray_mock = MagicMock()
        tray_mock.quit_event.is_set.side_effect = [True]  # quit immediately
        tray_mock.paused = False
        tray_mock.interval = 300

        handler_mock = self._make_handler_mock()

        with (
            patch("src.commands.watch_command._WatchTray", return_value=tray_mock),
            patch("src.commands.watch_command._TrayLogHandler", return_value=handler_mock),
            patch("src.commands.watch_command._interruptible_sleep"),
        ):
            result = run_watch_command(
                interval=300,
                backup_dir=tmp_path / "backup",
                run_once=_run_once,
                log_level="WRN",
                use_systray=False,
            )

        assert result == 0

    def test_run_once_called_on_each_iteration(self, tmp_path):
        """run_once should be called once per loop iteration (quit after first)."""
        from src.commands.watch_command import run_watch_command

        call_count = [0]

        def _run_once():
            call_count[0] += 1
            return 0

        # quit_event: False (run loop body) → True (quit at top of next iteration)
        tray_mock = MagicMock()
        tray_mock.quit_event.is_set.side_effect = [False, True]
        tray_mock.paused = False
        tray_mock.interval = 300
        tray_mock.sync_now_event.is_set.return_value = False

        lock_mock = MagicMock()
        lock_mock.acquire.return_value = True

        handler_mock = self._make_handler_mock()

        with (
            patch("src.commands.watch_command._WatchTray", return_value=tray_mock),
            patch("src.commands.watch_command._TrayLogHandler", return_value=handler_mock),
            patch("src.commands.watch_command._interruptible_sleep"),
            patch("src.commands.watch_command.FileLock", return_value=lock_mock),
        ):
            run_watch_command(
                interval=300,
                backup_dir=tmp_path / "backup",
                run_once=_run_once,
                log_level="WRN",
                use_systray=False,
            )

        assert call_count[0] == 1

    def test_failed_run_once_increments_backoff(self, tmp_path):
        """A failing run_once should trigger exponential back-off on next cycle."""
        from src.commands.watch_command import run_watch_command

        def _run_once():
            return 1  # failure

        # quit_event: False (run once) → True (quit next iteration)
        tray_mock = MagicMock()
        tray_mock.quit_event.is_set.side_effect = [False, True]
        tray_mock.paused = False
        tray_mock.interval = 300
        tray_mock.sync_now_event.is_set.return_value = False

        lock_mock = MagicMock()
        lock_mock.acquire.return_value = True

        handler_mock = self._make_handler_mock()

        with (
            patch("src.commands.watch_command._WatchTray", return_value=tray_mock),
            patch("src.commands.watch_command._TrayLogHandler", return_value=handler_mock),
            patch("src.commands.watch_command._interruptible_sleep"),
            patch("src.commands.watch_command.FileLock", return_value=lock_mock),
        ):
            run_watch_command(
                interval=300,
                backup_dir=tmp_path / "backup",
                run_once=_run_once,
                log_level="WRN",
                use_systray=False,
            )

        # After a failure, set_status("Failure") should have been called
        tray_mock.set_status.assert_any_call("Failure", sync_ok=False)
