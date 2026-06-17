"""Logging configuration utilities."""

import logging
import os
import platform
import sys
from datetime import datetime
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# Log rotation settings
MAX_LOG_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB per file
MAX_LOG_BACKUP_COUNT = 3  # Keep 3 rotated files (total 4 including current)

# Custom level higher than CRITICAL — effectively silences the console
_NONE_LEVEL = logging.CRITICAL + 10


def _write_session_header(file_handler: RotatingFileHandler) -> None:
    """Write a session header to the log file for easy identification."""
    try:
        from src.__version__ import __version__
    except ImportError:
        __version__ = "unknown"

    # Get command line
    cmd = " ".join(sys.argv)

    # Build header
    separator = "=" * 70
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "",
        separator,
        f"SESSION START: {timestamp}",
        separator,
        f"Command: {cmd}",
        f"Version: RemarkableSync v{__version__}",
        f"Python: {platform.python_version()}",
        f"Platform: {platform.system()} {platform.release()}",
        separator,
        "",
    ]

    # Write directly to file handler
    for line in lines:
        record = logging.LogRecord(
            name="session",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=line,
            args=(),
            exc_info=None,
        )
        file_handler.emit(record)


class LogLevel(str, Enum):
    """Log verbosity levels (short 3-char names)."""

    DBG = "DBG"
    INF = "INF"
    WRN = "WRN"
    ERR = "ERR"
    NONE = "NONE"

    @property
    def python_level(self) -> int:
        return _LEVEL_MAP[self]


_LEVEL_MAP = {
    LogLevel.DBG: logging.DEBUG,
    LogLevel.INF: logging.INFO,
    LogLevel.WRN: logging.WARNING,
    LogLevel.ERR: logging.ERROR,
    LogLevel.NONE: _NONE_LEVEL,
}


def is_interactive() -> bool:
    """Return True if running in an interactive terminal."""
    if sys.stdout.isatty() or sys.stderr.isatty():
        return True
    if os.environ.get("WT_SESSION"):  # Windows Terminal
        return True
    if os.environ.get("TERM_PROGRAM"):  # VS Code, iTerm2, etc.
        return True
    if os.environ.get("ANSICON"):  # ConEmu/ANSICON
        return True
    if os.name == "nt":
        try:
            import msvcrt

            return msvcrt.get_osfhandle(sys.stderr.fileno()) != -1
        except (OSError, ValueError, AttributeError):
            pass
    return False


def setup_logging(
    log_level: LogLevel = LogLevel.NONE,
    log_dir: Optional[Path] = None,
):
    """Configure logging with Rich handler for colored, progress-bar-safe output.

    Args:
        log_level: Console verbosity level. Default ``NONE`` suppresses all
            console log output; user-facing status uses ``print_status``.
        log_dir: If provided, a ``remarkablesync.log`` file is written here
            at DEBUG level regardless of the console log level.
    """
    if isinstance(log_level, str):
        log_level = LogLevel(log_level.upper())

    # Use short 3-char level names for consistent column width
    logging.addLevelName(logging.DEBUG, "DBG")
    logging.addLevelName(logging.INFO, "INF")
    logging.addLevelName(logging.WARNING, "WRN")
    logging.addLevelName(logging.ERROR, "ERR")
    logging.addLevelName(logging.CRITICAL, "CRT")

    console_level = log_level.python_level
    interactive = is_interactive()

    root = logging.getLogger()
    # Preserve tray log handlers across re-initialization
    preserved = [h for h in root.handlers if h.__class__.__name__ == "_TrayLogHandler"]
    root.handlers.clear()
    for h in preserved:
        root.addHandler(h)
    # Root logger at DEBUG so the file handler sees everything
    root.setLevel(logging.DEBUG)

    # --- Console handler (only added when log_level is not NONE) ---
    if console_level < _NONE_LEVEL:
        if interactive:
            from .console import get_rich_logging_handler

            console_handler = get_rich_logging_handler()
        else:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
        console_handler.setLevel(console_level)
        root.addHandler(console_handler)

    # --- File handler with rotation (always DEBUG) ---
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "remarkablesync.log"
        file_handler = RotatingFileHandler(
            log_file,
            mode="a",
            maxBytes=MAX_LOG_SIZE_BYTES,
            backupCount=MAX_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(file_handler)

        # Write session header to log file for easy identification
        _write_session_header(file_handler)

    logging.debug(
        "Interactive: %s, Console log level: %s, Log dir: %s", interactive, log_level.value, log_dir
    )

    # Suppress verbose debug messages from third-party libraries
    logging.getLogger("svglib.svglib").setLevel(logging.WARNING)
    logging.getLogger("reportlab").setLevel(logging.WARNING)
    # Suppress all paramiko output — connection errors are caught and reported
    # via our own ERR - status messages; raw paramiko logs are noise.
    for _name in ("paramiko", "paramiko.transport", "paramiko.auth", "paramiko.channel"):
        _lg = logging.getLogger(_name)
        _lg.setLevel(logging.CRITICAL)
        _lg.propagate = False
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
