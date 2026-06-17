"""watch command – run sync/export on a periodic schedule with system tray.

Cross-platform file locking, exponential back-off on failures, and a
system-tray icon with status + menu (Sync Now, Pause/Resume, interval
picker, run-at-startup toggle, folder shortcuts, Quit).
"""

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from ..utils.logging import setup_logging

# Back-off parameters
_INITIAL_BACKOFF = 60  # seconds
_MAX_BACKOFF = 3600  # 1 hour
_BACKOFF_FACTOR = 2

# Interval choices: (label, seconds)  — 0 means "Manual" (Sync Now only)
INTERVAL_CHOICES = [
    ("Every 5 minutes", 5 * 60),
    ("Every 30 minutes", 30 * 60),
    ("Every 1 hour", 60 * 60),
    ("Every 4 hours", 4 * 60 * 60),
    ("Every 8 hours", 8 * 60 * 60),
    ("Manual only", 0),
]

# Registry key for Windows startup
_STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_REG_NAME = "reMarkableSync"


# ---------------------------------------------------------------------------
# Cross-platform file lock
# ---------------------------------------------------------------------------


class FileLock:
    """Simple advisory file lock (Windows + Unix)."""

    def __init__(self, lock_path: Path):
        self._lock_path = lock_path
        self._fh = None

    def acquire(self) -> bool:
        try:
            self._fh = open(self._lock_path, "w", encoding="utf-8")
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fh.write(f"{datetime.now(timezone.utc).isoformat()}\n")
            self._fh.flush()
            return True
        except OSError:
            if self._fh:
                self._fh.close()
                self._fh = None
            return False

    def release(self) -> None:
        if self._fh:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._fh, fcntl.LOCK_UN)
            except OSError:
                pass
            self._fh.close()
            self._fh = None
            try:
                self._lock_path.unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Run-at-startup helpers (Windows registry, macOS launchd, Linux autostart)
# ---------------------------------------------------------------------------


def _get_watch_command_line() -> str:
    """Build the command line that would re-launch watch mode."""
    script = Path(sys.argv[0]).resolve()
    return f'"{sys.executable}" "{script}" watch'


def _is_startup_enabled() -> bool:
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY, 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, _STARTUP_REG_NAME)
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False
    elif sys.platform == "darwin":
        plist = Path.home() / "Library/LaunchAgents/com.remarkablesync.watch.plist"
        return plist.exists()
    else:
        autostart = Path.home() / ".config/autostart/remarkablesync-watch.desktop"
        return autostart.exists()


def _set_startup_enabled(enabled: bool) -> bool:
    """Enable or disable run-at-startup. Returns True on success."""
    cmd_line = _get_watch_command_line()

    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE
            )
            try:
                if enabled:
                    winreg.SetValueEx(key, _STARTUP_REG_NAME, 0, winreg.REG_SZ, cmd_line)
                else:
                    try:
                        winreg.DeleteValue(key, _STARTUP_REG_NAME)
                    except FileNotFoundError:
                        pass
                return True
            finally:
                winreg.CloseKey(key)
        except Exception as exc:
            logging.warning("Failed to update startup registry: %s", exc)
            return False

    elif sys.platform == "darwin":
        plist = Path.home() / "Library/LaunchAgents/com.remarkablesync.watch.plist"
        if enabled:
            plist.parent.mkdir(parents=True, exist_ok=True)
            plist.write_text(
                f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.remarkablesync.watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string>
    <string>{Path(sys.argv[0]).resolve()}</string>
    <string>watch</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
""",
                encoding="utf-8",
            )
            return True
        else:
            plist.unlink(missing_ok=True)
            return True

    else:
        desktop = Path.home() / ".config/autostart/remarkablesync-watch.desktop"
        if enabled:
            desktop.parent.mkdir(parents=True, exist_ok=True)
            desktop.write_text(
                f"""[Desktop Entry]
Type=Application
Name=reMarkableSync Watch
Exec={cmd_line}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
""",
                encoding="utf-8",
            )
            return True
        else:
            desktop.unlink(missing_ok=True)
            return True


# ---------------------------------------------------------------------------
# System tray with menu
# ---------------------------------------------------------------------------


class _WatchTray:
    """System tray icon with status indicator and context menu."""

    def __init__(
        self,
        mode: str,
        enabled: bool,
        interval: int,
        backup_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        on_interval_change: Optional[Callable[[int], None]] = None,
    ):
        self._mode = mode
        self._enabled = enabled
        self._backup_dir = backup_dir
        self._output_dir = output_dir
        self._on_interval_change = on_interval_change
        self._icon = None
        self._status = "Idle"
        self._detail = ""  # last activity line shown in menu
        self._last_sync: Optional[str] = None
        self._last_sync_ok: Optional[bool] = None
        self._next_sync: Optional[str] = None
        self._interval = interval  # 0 = manual
        # Threading events for menu actions
        self.sync_now_event = threading.Event()
        self.quit_event = threading.Event()
        self._paused = False
        # Recent log lines for the status window
        self._log_lines: list = []
        self._log_lock = threading.Lock()
        self._MAX_LOG_LINES = 50
        self._status_window: Optional["_StatusWindow"] = None
        self._show_lock = threading.Lock()
        # Progress tracking
        self._progress_current = 0
        self._progress_total = 0
        self._progress_label = ""

    @property
    def interval(self) -> int:
        return self._interval

    def set_interval(self, secs: int) -> None:
        """Update the interval and refresh the tray menu (idempotent)."""
        if secs == self._interval:
            return
        self._interval = secs
        self._rebuild_icon_menu()

    def _build_icon_image(self, color: str = None):
        """Load the app logo for tray icon, with colored status dot in corner."""
        from pathlib import Path

        from PIL import Image, ImageDraw

        # Try to load the logo
        logo_path = Path(__file__).parent.parent.parent / "docs" / "logo.png"
        if logo_path.exists():
            try:
                image = Image.open(logo_path).convert("RGBA")
                image = image.resize((64, 64), Image.LANCZOS)

                # Add a small colored status dot in corner
                if color:
                    draw = ImageDraw.Draw(image)
                    draw.ellipse((42, 42, 62, 62), fill=color, outline="white", width=2)

                return image
            except Exception:
                pass

        # Fallback to simple circle if logo not found
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        fill_color = color or "#4A90E2"
        draw.ellipse((8, 8, 56, 56), fill=fill_color)
        draw.ellipse((20, 20, 44, 44), fill=(255, 255, 255, 190))
        return image

    @property
    def paused(self) -> bool:
        return self._paused

    def set_detail(self, text: str) -> None:
        """Update the activity detail line shown in the tray menu."""
        # Truncate long lines for the menu
        self._detail = (text[:60] + "…") if len(text) > 60 else text
        if self._icon:
            try:
                self._icon.title = f"reMarkableSync - {self._detail}"
            except Exception:
                pass
            self._rebuild_icon_menu()

        # Store for status window
        with self._log_lock:
            self._log_lines.append(text)
            if len(self._log_lines) > self._MAX_LOG_LINES:
                self._log_lines = self._log_lines[-self._MAX_LOG_LINES :]

    def get_log_lines(self) -> list:
        with self._log_lock:
            return list(self._log_lines)

    def set_progress(self, current: int, total: int, label: str = "") -> None:
        """Update progress bar state."""
        self._progress_current = current
        self._progress_total = total
        self._progress_label = label

    def clear_progress(self) -> None:
        self._progress_current = 0
        self._progress_total = 0
        self._progress_label = ""

    def show_status_window(self) -> None:
        """Show the status window (creates it on first call, shows it after)."""
        if self._status_window is None:
            win = _StatusWindow(self)
            self._status_window = win
            win.start()
        elif self._status_window.is_alive():
            self._status_window.show()

    def _on_show_status(self, icon, item):
        # Must not block pystray's message handler thread
        if not self._show_lock.acquire(blocking=False):
            return
        try:
            self.show_status_window()
        finally:
            self._show_lock.release()

    # -- Menu callbacks --

    def _on_sync_now(self, icon, item):
        self.sync_now_event.set()

    def _on_pause_resume(self, icon, item):
        self._paused = not self._paused
        if self._paused:
            self.set_status("Paused")
        else:
            self.set_status("Idle")

    def _on_open_backup(self, icon, item):
        self._open_folder(self._backup_dir)

    def _on_open_output(self, icon, item):
        self._open_folder(self._output_dir)

    def _on_open_log(self, icon, item):
        if self._backup_dir:
            log_file = self._backup_dir.parent / "remarkablesync.log"
            if log_file.exists():
                self._open_file(log_file)

    def _on_quit(self, icon, item):
        self.quit_event.set()
        icon.stop()

    def _make_interval_handler(self, secs: int):
        def handler(icon, item):
            self._interval = secs
            label = _format_interval(secs) if secs else "manual"
            print(f"  Interval changed to {label}")
            self._rebuild_icon_menu()
            if self._on_interval_change is not None:
                try:
                    self._on_interval_change(secs)
                except Exception:
                    pass

        return handler

    def _on_toggle_startup(self, icon, item):
        current = _is_startup_enabled()
        ok = _set_startup_enabled(not current)
        if ok:
            state = "enabled" if not current else "disabled"
            print(f"  Run at startup {state}")
        self._rebuild_icon_menu()

    @staticmethod
    def _open_folder(folder: Optional[Path]):
        if not folder or not folder.exists():
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            logging.debug("Could not open folder: %s", exc)

    @staticmethod
    def _open_file(filepath: Path):
        """Open a file with the system default application."""
        try:
            if sys.platform == "win32":
                os.startfile(str(filepath))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(filepath)])
            else:
                subprocess.Popen(["xdg-open", str(filepath)])
        except Exception as exc:
            logging.debug("Could not open file: %s", exc)

    # -- Menu building --

    def _build_menu(self):
        import pystray

        # Status line
        # Status indicators
        status_icons = {
            "Idle": "🔵",
            "Running": "🟡",
            "Success": "🟢",
            "Failure": "🔴",
            "Backoff": "🟠",
            "Paused": "⏸️",
            "Stopped": "⏹️",
        }
        icon = status_icons.get(self._status, "🔵")
        parts = [f"{icon} {self._status}"]
        if self._last_sync:
            result = "✓" if self._last_sync_ok else "✗"
            parts.append(f"Last: {self._last_sync} {result}")
        if self._next_sync and not self._paused and self._interval > 0:
            parts.append(f"Next: {self._next_sync}")
        status_text = "  |  ".join(parts)

        pause_label = "Resume" if self._paused else "Pause"

        # Interval submenu
        interval_items = []
        for label, secs in INTERVAL_CHOICES:
            interval_items.append(
                pystray.MenuItem(
                    label,
                    self._make_interval_handler(secs),
                    checked=lambda item, s=secs: self._interval == s,
                    radio=True,
                )
            )
        interval_submenu = pystray.Menu(*interval_items)

        # Startup checkbox
        _is_startup_enabled()  # refresh state

        items = [
            pystray.MenuItem(status_text, self._on_show_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show Status", self._on_show_status, default=True),
            pystray.MenuItem(
                "Sync Now",
                self._on_sync_now,
                enabled=self._status in ("Idle", "Success", "Failure"),
            ),
            pystray.MenuItem(pause_label, self._on_pause_resume),
            pystray.MenuItem("Sync Interval", interval_submenu),
            pystray.Menu.SEPARATOR,
        ]

        if self._backup_dir:
            items.append(pystray.MenuItem("Open Backup Folder", self._on_open_backup))
        if self._output_dir:
            items.append(pystray.MenuItem("Open Markdown Folder", self._on_open_output))
        if self._backup_dir:
            items.append(pystray.MenuItem("Open Log File", self._on_open_log))
        if self._backup_dir or self._output_dir:
            items.append(pystray.Menu.SEPARATOR)

        items.append(
            pystray.MenuItem(
                "Run at Startup",
                self._on_toggle_startup,
                checked=lambda item: _is_startup_enabled(),
            )
        )
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit", self._on_quit))

        return pystray.Menu(*items)

    def _rebuild_icon_menu(self):
        if not self._icon:
            return
        try:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()
        except Exception:
            pass

    # -- Lifecycle --

    def start(self) -> None:
        if not self._enabled:
            return

        try:
            import pystray
        except Exception as exc:
            logging.info("System tray disabled (pystray unavailable): %s", exc)
            return

        try:
            self._icon = pystray.Icon(
                "remarkablesync-watch",
                self._build_icon_image("#4A90E2"),
                title="reMarkableSync",
                menu=self._build_menu(),
            )
            if hasattr(self._icon, "run_detached"):
                self._icon.run_detached()
            else:
                thread = threading.Thread(target=self._icon.run, daemon=True)
                thread.start()
        except Exception as exc:
            logging.info("System tray disabled (unable to initialize): %s", exc)
            self._icon = None

    def set_status(
        self,
        status: str,
        next_sync: Optional[str] = None,
        sync_ok: Optional[bool] = None,
    ) -> None:
        self._status = status

        if sync_ok is not None:
            self._last_sync = datetime.now().strftime("%m/%d/%Y %H:%M")
            self._last_sync_ok = sync_ok
        if next_sync is not None:
            self._next_sync = next_sync

        colors = {
            "Idle": "#4A90E2",
            "Running": "#FFD166",
            "Success": "#06D6A0",
            "Failure": "#EF476F",
            "Backoff": "#F97316",
            "Paused": "#9CA3AF",
            "Stopped": "#9CA3AF",
        }
        color = colors.get(status, "#4A90E2")

        if self._icon:
            try:
                self._icon.icon = self._build_icon_image(color)
                self._icon.title = f"reMarkableSync - {status}"
            except Exception:
                pass

        self._rebuild_icon_menu()

    def stop(self) -> None:
        if self._status_window and self._status_window.is_alive():
            self._status_window.close()
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None


# ---------------------------------------------------------------------------
# Status window (tkinter)
# ---------------------------------------------------------------------------


class _StatusWindow(threading.Thread):
    """Small tkinter window showing progress bar and recent log lines."""

    def __init__(self, tray: _WatchTray):
        super().__init__(daemon=True)
        self._tray = tray
        self._root = None

    def run(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        self._root = root
        root.title("reMarkableSync")
        root.geometry("576x320")
        root.resizable(True, True)
        root.configure(bg="#1e1e1e")

        # Hide from taskbar — make it a tool window
        root.attributes("-toolwindow", True)

        # Position near bottom-right of screen
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x = sw - 596
        y = sh - 400
        root.geometry(f"+{x}+{y}")

        # Set window icon to match tray icon
        try:
            icon_img = self._tray._build_icon_image("#4A90E2")
            from PIL import ImageTk

            self._icon_photo = ImageTk.PhotoImage(icon_img)
            root.iconphoto(True, self._icon_photo)
        except Exception:
            pass

        # Dark theme style
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            "dark.Horizontal.TProgressbar", troughcolor="#333", background="#4A90E2", thickness=20
        )
        style.configure("TLabel", background="#1e1e1e", foreground="#ccc", font=("Segoe UI", 10))

        # Status label (blue text)
        self._status_label = ttk.Label(
            root, text="Idle", style="TLabel", foreground="#4A90E2", font=("Segoe UI", 11, "bold")
        )
        self._status_label.pack(fill=tk.X, padx=10, pady=(10, 2))

        # Progress bar
        self._progress_var = tk.DoubleVar(value=0)
        self._progress_bar = ttk.Progressbar(
            root,
            variable=self._progress_var,
            maximum=100,
            style="dark.Horizontal.TProgressbar",
        )
        self._progress_bar.pack(fill=tk.X, padx=10, pady=4)

        # Progress label (e.g. "Page 3 of 21")
        self._progress_label = ttk.Label(root, text="", style="TLabel")
        self._progress_label.pack(fill=tk.X, padx=10, pady=(0, 4))

        # Log text area
        self._log_text = tk.Text(
            root,
            bg="#252525",
            fg="#ddd",
            font=("Consolas", 9),
            wrap=tk.WORD,
            state=tk.DISABLED,
            relief=tk.FLAT,
            highlightthickness=0,
            padx=6,
            pady=4,
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Scrollbar
        scrollbar = ttk.Scrollbar(self._log_text, command=self._log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.configure(yscrollcommand=scrollbar.set)

        # Hide on close instead of destroying
        root.protocol("WM_DELETE_WINDOW", self._hide)
        root.bind("<Escape>", lambda e: self._hide())

        # Start polling (runs forever)
        self._poll()

        root.mainloop()

    def show(self) -> None:
        """Show the window (called from any thread)."""
        if self._root:
            try:
                self._root.after(0, self._do_show)
            except Exception:
                pass

    def _do_show(self) -> None:
        """Show the window (must run on tkinter thread)."""
        if self._root:
            self._root.deiconify()
            self._root.lift()
            self._root.focus_force()

    def _hide(self) -> None:
        """Hide the window without destroying it."""
        if self._root:
            self._root.withdraw()

    def _poll(self) -> None:
        """Poll tray state and update the window every 500ms."""
        if not self._root:
            return

        try:
            import tkinter as tk

            # Update status
            tray = self._tray
            status = tray._status
            parts = [status]
            if tray._last_sync:
                result = "✓" if tray._last_sync_ok else "✗"
                parts.append(f"Last sync: {tray._last_sync} {result}")
            if tray._next_sync and tray._interval > 0:
                parts.append(f"Next: {tray._next_sync}")
            self._status_label.configure(text="  |  ".join(parts))

            # Update progress bar
            if tray._progress_total > 0:
                pct = (tray._progress_current / tray._progress_total) * 100
                self._progress_var.set(pct)
                self._progress_label.configure(
                    text=f"{tray._progress_label}  ({tray._progress_current}/{tray._progress_total})"
                )
            else:
                self._progress_var.set(0)
                self._progress_label.configure(text="")

            # Update log lines only if changed (preserve scroll/selection)
            lines = tray.get_log_lines()
            new_content = "\n".join(lines)
            current_content = self._log_text.get("1.0", "end-1c")
            if new_content != current_content:
                # Check if scrolled to bottom before update
                yview = self._log_text.yview()
                at_bottom = yview[1] >= 0.99

                self._log_text.configure(state=tk.NORMAL)
                self._log_text.delete("1.0", tk.END)
                self._log_text.insert(tk.END, new_content)
                self._log_text.configure(state=tk.DISABLED)

                # Auto-scroll only if was at bottom
                if at_bottom:
                    self._log_text.see(tk.END)

        except Exception:
            pass

        if self._root:
            self._root.after(500, self._poll)

    def close(self) -> None:
        """Destroy the window permanently (called on app quit)."""
        try:
            if self._root:
                self._root.after(0, self._root.destroy)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _TrayLogHandler(logging.Handler):
    """Log handler that feeds the last meaningful line to the tray menu."""

    # Only surface these levels — skip DEBUG noise
    _MIN_LEVEL = logging.INFO

    def __init__(self, tray: _WatchTray):
        super().__init__(level=self._MIN_LEVEL)
        self._tray = tray

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            # Skip noisy library loggers
            if record.name in ("openai", "httpcore", "httpx", "urllib3"):
                return
            self._tray.set_detail(msg)

            # Parse progress from page callbacks: "PDF: Work (page 3/21)" or "PDF: Work (page 3/21) [cached]"
            import re

            m = re.search(r"(PDF|MD): (.+?) \(page (\d+)/(\d+)\)", msg)
            if m:
                label = f"{m.group(1)}: {m.group(2)}"
                self._tray.set_progress(int(m.group(3)), int(m.group(4)), label)
        except Exception:
            pass


def _format_interval(seconds: int) -> str:
    if seconds <= 0:
        return "manual"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m" if m else f"{h}h"


def _next_run_time(seconds: int) -> str:
    """Return a human-readable timestamp for the next run."""
    t = datetime.now() + timedelta(seconds=seconds)
    return t.strftime("%m/%d/%Y %H:%M")


# ---------------------------------------------------------------------------
# Interruptible sleep
# ---------------------------------------------------------------------------


def _interruptible_sleep(seconds: int, tray: _WatchTray) -> None:
    """Sleep for *seconds*, but wake early on Sync Now, Quit, or Pause."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if tray.quit_event.is_set():
            return
        if tray.sync_now_event.is_set():
            tray.sync_now_event.clear()
            return
        if tray.paused:
            while tray.paused and not tray.quit_event.is_set():
                time.sleep(0.5)
            if tray.quit_event.is_set():
                return
            # Unpaused — run immediately
            return
        time.sleep(1)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_watch_command(
    interval: int,
    backup_dir: Path,
    run_once: Callable[[], int],
    log_level: str = "WRN",
    mode: str = "sync",
    use_systray: bool = True,
    output_dir: Optional[Path] = None,
    get_interval: Optional[Callable[[], int]] = None,
    on_interval_change: Optional[Callable[[int], None]] = None,
) -> int:
    """Run *run_once* repeatedly every *interval* seconds.

    Args:
        interval: Seconds between sync attempts (0 = manual only).
        backup_dir: Backup directory (used for lock-file placement).
        run_once: Callable that performs one sync pass and returns an exit
                  code (0 = success, non-zero = failure).
        log_level: Logging level string.
        mode: Human-readable mode label shown in log messages.
        use_systray: Enable a best-effort system tray status icon.
        output_dir: Markdown output directory (for "Open Markdown Folder").
        get_interval: Optional callable returning the interval (seconds) to
                  use. Called at the start of each cycle so config-file edits
                  take effect without restarting.
        on_interval_change: Optional callback invoked with the new interval
                  (seconds) when it is changed via the tray menu, so the change
                  can be persisted to config.

    Returns:
        Exit code (0).  Returns when interrupted via Ctrl-C or tray Quit.
    """
    setup_logging(log_level)
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Prevent multiple watch instances from running simultaneously
    process_lock_path = backup_dir / ".remarkable_watch_process.lock"
    process_lock = FileLock(process_lock_path)
    if not process_lock.acquire():
        print("Another reMarkableSync watch instance is already running.")
        print("Please quit the existing instance first (system tray → Quit).")
        return 1

    tray = _WatchTray(
        mode=mode,
        enabled=use_systray,
        interval=interval,
        backup_dir=backup_dir,
        output_dir=output_dir,
        on_interval_change=on_interval_change,
    )
    tray.start()

    # Install log handler that feeds activity into the tray menu
    tray_handler = _TrayLogHandler(tray)
    logging.getLogger().addHandler(tray_handler)

    lock_path = backup_dir / ".remarkable_watch.lock"

    print(f"reMarkableSync Watch ({mode})")
    print("=" * 70)
    label = _format_interval(interval) if interval else "manual (Sync Now only)"
    print(f"  Interval   : {label}")
    print(f"  Backup dir : {backup_dir.absolute()}")
    if output_dir:
        print(f"  Output dir : {output_dir.absolute()}")
    print("  Press Ctrl-C to stop.\n")

    consecutive_failures = 0
    current_backoff = 0

    # Short startup delay so the tray icon is visible before first sync
    _STARTUP_DELAY = 5
    print(f"  Starting first sync in {_STARTUP_DELAY}s...")
    _interruptible_sleep(_STARTUP_DELAY, tray)

    try:
        while True:
            if tray.quit_event.is_set():
                break

            # Paused — spin until unpaused or quit
            if tray.paused:
                time.sleep(1)
                continue

            # Re-read interval from config so edits apply on the next cycle.
            if get_interval is not None:
                try:
                    tray.set_interval(get_interval())
                except Exception:
                    pass

            # Manual mode — wait for Sync Now
            current_interval = tray.interval
            if current_interval == 0:
                tray.set_status("Idle")
                while not tray.sync_now_event.is_set() and not tray.quit_event.is_set():
                    time.sleep(1)
                if tray.quit_event.is_set():
                    break
                tray.sync_now_event.clear()

            # Apply back-off after failures
            if current_backoff > 0:
                tray.set_status("Backoff")
                logging.warning(
                    "Backing off for %s after %d consecutive failure(s).",
                    _format_interval(current_backoff),
                    consecutive_failures,
                )
                _interruptible_sleep(current_backoff, tray)
                if tray.quit_event.is_set():
                    break

            # Acquire lock to prevent overlapping runs
            lock = FileLock(lock_path)
            if not lock.acquire():
                tray.set_status("Idle")
                logging.warning("Another sync is already running (lock file exists). Skipping.")
                if current_interval > 0:
                    _interruptible_sleep(current_interval, tray)
                continue

            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  [{ts}] Starting {mode}...")
            tray.set_status("Running")

            try:
                exit_code = run_once()
                tray.clear_progress()
                if exit_code == 0:
                    consecutive_failures = 0
                    current_backoff = 0
                    ts2 = datetime.now().strftime("%H:%M:%S")
                    if current_interval > 0:
                        next_ts = _next_run_time(current_interval)
                        tray.set_status("Success", next_sync=next_ts, sync_ok=True)
                        print(f"  [{ts2}] ✓ {mode} succeeded. Next at {next_ts}.\n")
                    else:
                        tray.set_status("Success", sync_ok=True)
                        print(f"  [{ts2}] ✓ {mode} succeeded.\n")
                else:
                    tray.set_status("Failure", sync_ok=False)
                    consecutive_failures += 1
                    current_backoff = min(
                        _INITIAL_BACKOFF * (_BACKOFF_FACTOR ** (consecutive_failures - 1)),
                        _MAX_BACKOFF,
                    )
                    ts2 = datetime.now().strftime("%H:%M:%S")
                    print(
                        f"  [{ts2}] ✗ {mode} failed (exit {exit_code}). "
                        f"Failures: {consecutive_failures}.\n"
                    )
            except Exception as exc:
                tray.set_status("Failure", sync_ok=False)
                consecutive_failures += 1
                current_backoff = min(
                    _INITIAL_BACKOFF * (_BACKOFF_FACTOR ** (consecutive_failures - 1)),
                    _MAX_BACKOFF,
                )
                logging.error("Unexpected error during %s: %s", mode, exc)
            finally:
                lock.release()

            # Wait for next cycle (interruptible by Sync Now / Quit)
            if current_interval > 0:
                next_ts = _next_run_time(current_interval)
                tray.set_detail("")
                tray.set_status(
                    "Idle" if consecutive_failures == 0 else "Failure",
                    next_sync=next_ts,
                )
                _interruptible_sleep(current_interval, tray)

    except KeyboardInterrupt:
        pass

    print("\n  [STOPPED] Watch mode stopped.")
    logging.getLogger().removeHandler(tray_handler)
    tray.set_status("Stopped")
    tray.stop()
    process_lock.release()
    return 0
