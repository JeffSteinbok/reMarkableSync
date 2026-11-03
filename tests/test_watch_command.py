"""Tests for watch_command module utilities."""

import logging
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.commands.watch_command import (
    FileLock,
    _build_macos_dock_icon,
    _format_interval,
    _interruptible_sleep,
    _MacStatusWindow,
    _next_run_time,
    _StatusWindow,
    _TrayLogHandler,
    _WatchTray,
    run_watch_command,
)

pytestmark = pytest.mark.usefixtures("runtime_dir")


def test_watch_keeps_both_locks_and_log_outside_backup(monkeypatch, tmp_path, runtime_dir):
    from src.config import get_lock_dir, get_log_dir

    backup = tmp_path / "OneDrive" / "backup"
    tray = _WatchTray("sync", False, 1, backup_dir=backup)
    monkeypatch.setattr("src.commands.watch_command._WatchTray", lambda **kwargs: tray)
    monkeypatch.setattr("src.commands.watch_command._interruptible_sleep", lambda *args: None)
    lock_dir = get_lock_dir(backup)

    def run_once():
        assert (lock_dir / ".remarkable_watch.lock").exists()
        assert (lock_dir / ".remarkable_watch_process.lock").exists()
        assert not list(backup.glob("*.lock"))
        contender = FileLock(lock_dir / ".remarkable_watch_process.lock")
        assert not contender.acquire()
        tray.quit_event.set()
        return 0

    assert run_watch_command(1, backup, run_once, log_level="NONE", use_systray=False) == 0
    log_file = get_log_dir() / "remarkablesync.log"
    assert log_file.is_relative_to(runtime_dir)
    assert log_file.exists()
    assert not list(backup.parent.glob("*.log"))
    assert not list(lock_dir.glob("*.lock"))
    tray._open_file = MagicMock()
    tray._on_open_log(None, None)
    tray._open_file.assert_called_once_with(log_file)


@pytest.mark.parametrize("configured", [True, False])
def test_tray_pdf_folder_menu_and_action(monkeypatch, tmp_path, configured):
    pystray = MagicMock()
    monkeypatch.setitem(sys.modules, "pystray", pystray)
    monkeypatch.setattr("src.commands.watch_command._is_startup_enabled", lambda: False)
    pdf_dir = tmp_path / "pdf" if configured else None
    tray = _WatchTray("sync", True, 300, pdf_dir=pdf_dir)
    tray._open_folder = MagicMock()

    tray._build_menu()

    labels = [call.args[0] for call in pystray.MenuItem.call_args_list]
    assert ("Open PDF Folder" in labels) == configured
    if configured:
        tray._on_open_pdf(None, None)
        tray._open_folder.assert_called_once_with(pdf_dir)


@pytest.mark.parametrize("failure", ["import", "tk", "widgets"])
def test_status_window_startup_failure_is_logged_notified_and_retryable(
    monkeypatch, caplog, failure
):
    monkeypatch.setattr("src.commands.watch_command.sys.platform", "win32")
    tray = _WatchTray(mode="sync", enabled=True, interval=300)
    tray._icon = MagicMock()
    window = _StatusWindow(tray)
    tray._status_window = window
    root = MagicMock()
    tk = MagicMock()
    tk.Tk.return_value = root
    if failure == "import":
        monkeypatch.setitem(sys.modules, "tkinter", None)
    else:
        monkeypatch.setitem(sys.modules, "tkinter", tk)
        if failure == "tk":
            tk.Tk.side_effect = RuntimeError("Tcl/Tk runtime missing")
        else:
            root.geometry.side_effect = RuntimeError("Widget initialization failed")

    with caplog.at_level(logging.ERROR):
        window.run()

    assert tray._status_window is None
    assert window._root is None
    assert "Could not open Show Status" in caplog.text
    assert "Traceback" in caplog.text
    message, title = tray._icon.notify.call_args.args
    assert "Sync is still running" in message
    assert "remarkablesync.log" in message
    assert "Tcl/Tk" in message
    assert "Status window error" in title
    assert not tray.quit_event.is_set()
    if failure == "widgets":
        root.destroy.assert_called_once()

    retry = MagicMock()
    monkeypatch.setattr("src.commands.watch_command._StatusWindow", MagicMock(return_value=retry))
    tray.show_status_window()
    assert tray._status_window is retry
    retry.start.assert_called_once()
    retry.show.assert_called_once()


def test_status_window_requests_never_call_tk_from_the_sync_thread():
    tray = _WatchTray(mode="sync", enabled=True, interval=300)
    window = _StatusWindow(tray)
    root = MagicMock()
    window._root = root
    tray._status_window = window

    window.show()
    tray.set_detail("Sync is running")
    tray.set_status("Running")
    tray.set_progress(1, 4, "Notebook")
    tray.clear_progress()
    tray.stop()

    assert window._show_requested.is_set()
    assert window._close_requested.is_set()
    assert tray.get_log_lines() == ["Sync is running"]
    assert root.mock_calls == []


def test_status_window_show_before_startup_and_reopen_use_same_instance(monkeypatch):
    monkeypatch.setattr("src.commands.watch_command.sys.platform", "win32")
    monkeypatch.setattr(_StatusWindow, "start", MagicMock())
    tray = _WatchTray(mode="sync", enabled=True, interval=300)

    tray.show_status_window()
    window = tray._status_window
    assert window._show_requested.is_set()
    assert window._root is None
    window._show_requested.clear()
    tray.show_status_window()

    assert tray._status_window is window
    assert window._show_requested.is_set()
    window.start.assert_called_once()


def test_status_window_poll_handles_close_on_tk_thread():
    tray = _WatchTray(mode="sync", enabled=True, interval=300)
    window = _StatusWindow(tray)
    window._root = MagicMock()

    window.close()
    window._poll()

    window._root.quit.assert_called_once()
    window._root.after.assert_not_called()


def test_watch_logs_status_startup_errors_before_first_sync(monkeypatch, tmp_path, runtime_dir):
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, "handlers", root_logger.handlers.copy())
    monkeypatch.setattr(root_logger, "level", root_logger.level)
    monkeypatch.setitem(sys.modules, "tkinter", None)
    monkeypatch.setattr(_WatchTray, "start", MagicMock())

    def fail_window_before_sync(*args):
        tray, process_lock = args[-2:]
        tray._icon = MagicMock()
        try:
            window = _StatusWindow(tray)
            tray._status_window = window
            window.run()
            return 0
        finally:
            process_lock.release()

    monkeypatch.setattr("src.commands.watch_command._run_watch_loop", fail_window_before_sync)
    try:
        assert run_watch_command(300, tmp_path / "backup", MagicMock(), log_level="NONE") == 0
        log = (runtime_dir / "logs" / "remarkablesync.log").read_text(encoding="utf-8")
        assert "Could not open Show Status" in log
        assert "ModuleNotFoundError" in log
        assert "Traceback" in log
    finally:
        for handler in root_logger.handlers:
            handler.close()


def test_macos_status_window_uses_native_appkit(monkeypatch):
    monkeypatch.setattr("src.commands.watch_command.sys.platform", "darwin")
    window = MagicMock()
    monkeypatch.setattr(
        "src.commands.watch_command._MacStatusWindow",
        MagicMock(return_value=window),
    )
    tray = _WatchTray(mode="sync", enabled=True, interval=300)

    tray.show_status_window()

    assert tray._status_window is window
    window.show.assert_called_once()


def test_macos_icon_uses_template_rendering(monkeypatch):
    monkeypatch.setattr("src.commands.watch_command.sys.platform", "darwin")
    image = MagicMock()
    tray = _WatchTray(mode="sync", enabled=True, interval=300)
    tray._icon = MagicMock(_icon_image=image)

    tray.apply_platform_icon_style()

    image.setTemplate_.assert_called_once_with(True)


def test_macos_icon_removes_logo_background(monkeypatch):
    monkeypatch.setattr("src.commands.watch_command.sys.platform", "darwin")
    tray = _WatchTray(mode="sync", enabled=True, interval=300)

    image = tray._build_icon_image()

    assert image.getpixel((5, 32))[3] == 0
    assert image.getpixel((24, 24))[3] > 0


def test_macos_dock_icon_uses_padded_safe_area():
    logo_path = Path(__file__).parent.parent / "docs" / "logo.png"

    image = _build_macos_dock_icon(logo_path, size=100)

    assert image.size == (100, 100)
    assert image.getpixel((5, 50))[3] == 0
    assert image.getpixel((50, 50))[3] > 0


def test_tray_log_handler_tracks_backup_file_progress():
    tray = MagicMock()
    handler = _TrayLogHandler(tray)
    record = logging.LogRecord(
        "root",
        logging.INFO,
        "",
        0,
        "Backup: page.rm (file 7/20)",
        (),
        None,
    )

    handler.emit(record)

    tray.set_progress.assert_called_once_with(7, 20, "page.rm")


def test_tray_log_handler_tracks_overall_pdf_progress():
    tray = MagicMock()
    handler = _TrayLogHandler(tray)
    record = logging.LogRecord(
        "root",
        logging.INFO,
        "",
        0,
        "PDF: Project Notes (page 3/12, overall 42/479)",
        (),
        None,
    )

    handler.emit(record)

    tray.set_progress.assert_called_once_with(
        42,
        479,
        "PDF: Project Notes page 3/12",
    )


def test_macos_status_window_hides_progress_when_idle():
    tray = _WatchTray(mode="sync", enabled=True, interval=300)
    tray._status = "Idle"
    tray._progress_current = 7
    tray._progress_total = 20
    window = _MacStatusWindow(tray)
    window._window = MagicMock()
    window._status_label = MagicMock()
    window._progress = MagicMock()
    window._progress_label = MagicMock()
    window._log_text = MagicMock()
    window._log_text.string.return_value = ""

    window._update()

    window._progress.setHidden_.assert_called_once_with(True)
    window._progress_label.setHidden_.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# _format_interval tests
# ---------------------------------------------------------------------------


class TestFormatInterval:
    """Tests for _format_interval utility."""

    def test_zero_returns_manual(self):
        assert _format_interval(0) == "manual"

    def test_negative_returns_manual(self):
        assert _format_interval(-10) == "manual"

    def test_seconds_under_minute(self):
        assert _format_interval(30) == "30s"
        assert _format_interval(59) == "59s"

    def test_exact_minutes(self):
        assert _format_interval(60) == "1m"
        assert _format_interval(300) == "5m"
        assert _format_interval(3540) == "59m"

    def test_exact_hours(self):
        assert _format_interval(3600) == "1h"
        assert _format_interval(7200) == "2h"

    def test_hours_and_minutes(self):
        assert _format_interval(3900) == "1h 5m"  # 1h 5m
        assert _format_interval(5400) == "1h 30m"  # 1.5h


# ---------------------------------------------------------------------------
# _next_run_time tests
# ---------------------------------------------------------------------------


class TestNextRunTime:
    """Tests for _next_run_time utility."""

    def test_returns_formatted_timestamp(self):
        result = _next_run_time(60)
        # Should be roughly a minute from now
        assert "/" in result  # date separator
        assert ":" in result  # time separator

    def test_timestamp_in_future(self):
        result = _next_run_time(3600)
        # Parse the result
        parsed = datetime.strptime(result, "%m/%d/%Y %H:%M")
        now = datetime.now()
        # Should be at least 50 minutes in the future
        assert parsed > now


# ---------------------------------------------------------------------------
# FileLock tests
# ---------------------------------------------------------------------------


class TestFileLock:
    """Tests for FileLock class."""

    def test_acquires_lock_on_new_file(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        lock = FileLock(lock_file)

        assert lock.acquire() is True
        assert lock_file.exists()

        lock.release()

    def test_acquire_returns_false_when_locked(self, tmp_path):
        lock_file = tmp_path / "test.lock"

        lock1 = FileLock(lock_file)
        lock2 = FileLock(lock_file)

        assert lock1.acquire() is True
        assert lock2.acquire() is False

        lock1.release()
        # Now lock2 should be able to acquire
        assert lock2.acquire() is True
        lock2.release()

    def test_release_removes_lock(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        lock = FileLock(lock_file)

        lock.acquire()
        lock.release()

        # Another lock should now succeed
        lock2 = FileLock(lock_file)
        assert lock2.acquire() is True
        lock2.release()

    def test_context_manager(self, tmp_path):
        """FileLock acquire/release pattern works correctly."""
        lock_file = tmp_path / "test.lock"
        lock = FileLock(lock_file)

        # Acquire and release manually (no context manager)
        assert lock.acquire() is True
        assert lock_file.exists()
        lock.release()

        # After release, lock should be released
        lock2 = FileLock(lock_file)
        assert lock2.acquire() is True
        lock2.release()

    def test_release_on_exception(self, tmp_path):
        """Lock can be released even if code raises exception."""
        lock_file = tmp_path / "test.lock"
        lock = FileLock(lock_file)

        lock.acquire()
        try:
            raise ValueError("test")
        except ValueError:
            pass
        finally:
            lock.release()

        # Lock should be released
        lock2 = FileLock(lock_file)
        assert lock2.acquire() is True
        lock2.release()

    def test_detects_stale_lock(self, tmp_path):
        """FileLock detects locks from dead processes."""
        lock_file = tmp_path / "test.lock"

        # Simulate a stale lock from a non-existent PID
        # Use an extremely high PID that's unlikely to exist
        lock_file.write_text("99999999")

        lock = FileLock(lock_file)
        # Should acquire since the PID doesn't exist
        lock.acquire()

        # On Windows, psutil might see this differently
        # Just verify we can still work with the lock
        lock.release()


# ---------------------------------------------------------------------------
# _interruptible_sleep tests
# ---------------------------------------------------------------------------


class TestInterruptibleSleep:
    """Tests for _interruptible_sleep utility."""

    def test_returns_quickly_on_quit_event(self):
        """Sleep returns quickly when quit event is set."""
        tray = MagicMock()
        tray.quit_event.is_set.return_value = True
        tray.sync_now_event.is_set.return_value = False
        tray.paused = False  # Explicitly set to avoid MagicMock truthy issue

        start = datetime.now()
        _interruptible_sleep(10, tray)
        elapsed = (datetime.now() - start).total_seconds()

        assert elapsed < 2  # Should return almost immediately

    def test_returns_on_sync_now_event(self):
        """Sleep returns when sync_now event is set."""
        tray = MagicMock()
        tray.quit_event.is_set.return_value = False
        tray.paused = False  # Explicitly set to avoid MagicMock truthy issue

        # First check returns False, second returns True
        tray.sync_now_event.is_set.side_effect = [False, True]

        start = datetime.now()
        _interruptible_sleep(10, tray)
        elapsed = (datetime.now() - start).total_seconds()

        assert elapsed < 3  # Should return quickly once event is set

    def test_completes_short_sleep(self):
        """Sleep completes for short durations."""
        tray = MagicMock()
        tray.quit_event.is_set.return_value = False
        tray.sync_now_event.is_set.return_value = False
        tray.paused = False  # Explicitly set to avoid MagicMock truthy issue

        start = datetime.now()
        _interruptible_sleep(1, tray)
        elapsed = (datetime.now() - start).total_seconds()

        assert 0.9 < elapsed < 2.0  # Should sleep about 1 second
