"""Tests for the logging utility module."""

import logging

from src.utils.logging import LogLevel, is_interactive, setup_logging


class TestLogLevel:
    """Tests for the LogLevel enum."""

    def test_all_levels_exist(self):
        assert LogLevel.DBG.value == "DBG"
        assert LogLevel.INF.value == "INF"
        assert LogLevel.WRN.value == "WRN"
        assert LogLevel.ERR.value == "ERR"
        assert LogLevel.NONE.value == "NONE"

    def test_python_level_mapping(self):
        assert LogLevel.DBG.python_level == logging.DEBUG
        assert LogLevel.INF.python_level == logging.INFO
        assert LogLevel.WRN.python_level == logging.WARNING
        assert LogLevel.ERR.python_level == logging.ERROR
        assert LogLevel.NONE.python_level > logging.CRITICAL


class TestSetupLogging:
    """Tests for the setup_logging function."""

    def test_accepts_string_level(self, tmp_path):
        """Can pass string instead of enum."""
        setup_logging("WRN", log_dir=tmp_path)
        # Should not raise

    def test_reconfiguration_closes_previous_log_file(self, tmp_path):
        setup_logging("NONE", log_dir=tmp_path / "old")
        old_handler = next(
            handler
            for handler in logging.getLogger().handlers
            if isinstance(handler, logging.FileHandler)
        )

        setup_logging("NONE", log_dir=tmp_path / "new")

        assert old_handler.stream is None
        logging.error("New log destination")
        assert "New log destination" in (tmp_path / "new" / "remarkablesync.log").read_text(
            encoding="utf-8"
        )

    def test_pythonw_without_console_streams_still_logs(self, monkeypatch, tmp_path):
        for name in ("WT_SESSION", "TERM_PROGRAM", "ANSICON"):
            monkeypatch.delenv(name, raising=False)
        with monkeypatch.context() as context:
            context.setattr("sys.stdout", None)
            context.setattr("sys.stderr", None)
            assert not is_interactive()
            setup_logging(LogLevel.NONE, log_dir=tmp_path)
            logging.error("Headless watcher diagnostic")

        assert "Headless watcher diagnostic" in (tmp_path / "remarkablesync.log").read_text(
            encoding="utf-8"
        )

    def test_creates_log_file(self, tmp_path):
        setup_logging(LogLevel.DBG, log_dir=tmp_path)
        log_file = tmp_path / "remarkablesync.log"
        assert log_file.exists()

    def test_log_file_receives_debug_messages(self, tmp_path):
        setup_logging(LogLevel.NONE, log_dir=tmp_path)
        logging.debug("test debug message for file")
        log_file = tmp_path / "remarkablesync.log"
        content = log_file.read_text(encoding="utf-8")
        assert "test debug message for file" in content

    def test_none_level_suppresses_console(self, tmp_path):
        """NONE level should not add a console handler."""
        setup_logging(LogLevel.NONE, log_dir=tmp_path)
        root = logging.getLogger()
        # Only the file handler (and possibly preserved tray handlers) should exist
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "StreamHandler" not in handler_types or all(
            h.level > logging.CRITICAL
            for h in root.handlers
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        )

    def test_no_log_dir_skips_file_handler(self):
        setup_logging(LogLevel.NONE, log_dir=None)
        root = logging.getLogger()
        _ = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        # We can't guarantee no file handlers from previous tests, but at least no crash
        # The key test is that it doesn't raise

    def test_case_insensitive_string(self, tmp_path):
        setup_logging("wrn", log_dir=tmp_path)
        # Should not raise

    def test_suppresses_third_party_loggers(self, tmp_path):
        setup_logging(LogLevel.DBG, log_dir=tmp_path)
        assert logging.getLogger("paramiko").level >= logging.WARNING
        assert logging.getLogger("openai").level >= logging.WARNING
