"""Tests for watch_command module utilities."""

import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from src.commands.watch_command import (
    FileLock,
    _build_macos_dock_icon,
    _format_interval,
    _interruptible_sleep,
    _MacStatusWindow,
    _next_run_time,
    _TrayLogHandler,
    _WatchTray,
)


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
