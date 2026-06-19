"""Tests for fixes to agent-tagged issues.

Covers:
- Issue #19: Progress bar shows "page 0 of X" (incorrect initial description)
- Issue #18: SSH/USB connection failure shows only one red line to the user
- Issue #13: Support pre-sync and post-sync commands
"""

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Issue #19 – Progress bar initial description
# ---------------------------------------------------------------------------


class TestProgressBarInitialDescription:
    """Issue #19: The initial progress description must never show 'page 0 of N'."""

    def test_pdf_md_converter_initial_description_not_zero(self, tmp_path):
        """MarkdownExporter.export_all must NOT start with 'page 0 of X'."""
        from src.pdf_md_converter import MarkdownExporter

        # Build minimal notebook dict
        notebooks = [
            {
                "uuid": "test-uuid",
                "name": "TestNotebook",
                "type": "DocumentType",
                "folder_path": "",
                "metadata_file": None,
            }
        ]

        exporter = MarkdownExporter(
            output_dir=tmp_path / "output",
            backup_dir=tmp_path / "backup",
        )

        descriptions_seen = []

        # Capture all progress descriptions that are set

        import src.utils.console as console_mod

        original_create = console_mod.create_progress

        def capturing_create_progress(*args, **kwargs):
            p = original_create(*args, **kwargs)
            original_update = p.update

            def spy_update(task_id, **kw):
                desc = kw.get("description")
                if desc is not None:
                    descriptions_seen.append(desc)
                return original_update(task_id, **kw)

            p.update = spy_update
            return p

        with patch.object(console_mod, "create_progress", side_effect=capturing_create_progress):
            # pdf_output_dir must exist; no notebooks will actually be processed
            (tmp_path / "pdf").mkdir()
            exporter.export_all(
                notebooks=notebooks,
                pdf_output_dir=tmp_path / "pdf",
                force=True,
            )

        # No description should contain "page 0 of"
        for desc in descriptions_seen:
            assert "page 0 of" not in desc, f"Found 'page 0 of' in progress description: {desc!r}"

    def test_rm_pdf_converter_initial_description_not_zero(self, tmp_path):
        """run_conversion must NOT set progress description to 'page 0 of X'."""
        from src.rm_pdf_converter import run_conversion

        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        output_dir = tmp_path / "pdf"
        output_dir.mkdir()

        descriptions_seen = []

        import src.utils.console as console_mod

        original_create = console_mod.create_progress

        def capturing_create_progress(*args, **kwargs):
            p = original_create(*args, **kwargs)
            original_update = p.update

            def spy_update(task_id, **kw):
                desc = kw.get("description")
                if desc is not None:
                    descriptions_seen.append(desc)
                return original_update(task_id, **kw)

            p.update = spy_update
            return p

        with patch.object(console_mod, "create_progress", side_effect=capturing_create_progress):
            with patch("src.rm_pdf_converter.find_notebooks", return_value=[]):
                with patch(
                    "src.rm_pdf_converter.organize_notebooks_by_structure",
                    return_value={"documents_to_convert": []},
                ):
                    run_conversion(backup_dir=backup_dir, output_dir=output_dir)

        for desc in descriptions_seen:
            assert "page 0 of" not in desc, f"Found 'page 0 of' in progress description: {desc!r}"


# ---------------------------------------------------------------------------
# Issue #18 – SSH connection failure → single red line
# ---------------------------------------------------------------------------


class TestConnectionFailureMessage:
    """Issue #18: A failed connection should show exactly one red error line."""

    def test_connect_failure_calls_print_error(self):
        """When all SSH attempts fail, print_error is called once."""
        import paramiko

        from src.backup.connection import ReMarkableConnection

        conn = ReMarkableConnection(host="10.11.99.1")
        # Give it a password so it doesn't prompt
        conn.password = "test_password"

        with (
            patch("socket.socket") as mock_socket_class,
            patch("src.backup.connection.paramiko.SSHClient") as mock_client_cls,
            patch("src.backup.connection.print_error") as mock_print_error,
        ):
            mock_socket = MagicMock()
            mock_socket_class.return_value = mock_socket

            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.connect.side_effect = paramiko.SSHException(
                "Error reading SSH protocol banner"
            )

            result = conn.connect()

        assert result is False
        mock_print_error.assert_called_once()
        # The single message should mention the host and give actionable advice
        msg = mock_print_error.call_args[0][0]
        assert "10.11.99.1" in msg
        assert "connected" in msg.lower() or "connection" in msg.lower()

    def test_connect_failure_does_not_raise(self):
        """SSH failure must not bubble up as an exception."""

        from src.backup.connection import ReMarkableConnection

        conn = ReMarkableConnection(host="10.11.99.1")
        conn.password = "test_password"

        with (
            patch("socket.socket") as mock_socket_class,
            patch("src.backup.connection.paramiko.SSHClient") as mock_client_cls,
            patch("src.backup.connection.print_error"),
        ):
            mock_socket = MagicMock()
            mock_socket_class.return_value = mock_socket
            mock_socket.connect.side_effect = OSError("Connection refused")

            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.connect.side_effect = OSError("Connection refused")
            result = conn.connect()

        assert result is False

    def test_paramiko_transport_log_level_is_critical(self):
        """paramiko.transport logger should be silenced at CRITICAL level after setup_logging."""
        import logging

        from src.utils.logging import setup_logging

        setup_logging("WRN")
        transport_logger = logging.getLogger("paramiko.transport")
        assert transport_logger.level == logging.CRITICAL


# ---------------------------------------------------------------------------
# Issue #13 – Pre-sync and post-sync commands
# ---------------------------------------------------------------------------


class TestPrePostSyncCommands:
    """Issue #13: pre_sync_command and post_sync_command must be executed."""

    def test_run_shell_command_success(self):
        """run_shell_command returns 0 for a trivially successful command."""
        from src.utils import run_shell_command

        rc = run_shell_command("exit 0")
        assert rc == 0

    def test_run_shell_command_failure(self):
        """run_shell_command returns non-zero for a failing command."""
        from src.utils import run_shell_command

        rc = run_shell_command("exit 42")
        assert rc == 42

    def test_default_config_has_pre_post_sync_keys(self):
        """DEFAULT_CONFIG must contain pre_sync_command and post_sync_command."""
        from src.config import DEFAULT_CONFIG

        assert "pre_sync_command" in DEFAULT_CONFIG
        assert "post_sync_command" in DEFAULT_CONFIG
        assert DEFAULT_CONFIG["pre_sync_command"] == ""
        assert DEFAULT_CONFIG["post_sync_command"] == ""

    def test_config_round_trip_preserves_commands(self, tmp_path):
        """pre/post sync commands survive a save/load round-trip."""
        from unittest.mock import patch

        from src.config import load_config, save_config

        fake_path = tmp_path / "config.json"
        test_config = {
            "connection_mode": "usb",
            "wifi_host": "",
            "password": "",
            "folders": [],
            "sync_actions": ["backup"],
            "ocr_enabled": False,
            "ocr_output_dir": "",
            "output_dir": "",
            "embed_images": True,
            "pdf_dir": "",
            "ai_provider": "github",
            "ai_model": "",
            "pre_sync_command": "echo pre",
            "post_sync_command": "echo post",
        }

        with patch("src.config.get_config_path", return_value=fake_path):
            save_config(test_config)
            loaded = load_config()

        assert loaded["pre_sync_command"] == "echo pre"
        assert loaded["post_sync_command"] == "echo post"

    @patch("src.config.load_config")
    @patch("src.hybrid_converter.find_notebooks", return_value=[])
    @patch(
        "src.hybrid_converter.organize_notebooks_by_structure",
        return_value={"documents_to_convert": []},
    )
    @patch("src.commands.pipeline.ReMarkableBackup")
    def test_pipeline_runs_pre_sync_command(
        self, mock_backup_cls, mock_org, mock_find, mock_config, tmp_path
    ):
        """run_pipeline passes pre_sync_command to ReMarkableConnection which runs it in connect()."""
        from src.commands.pipeline import run_pipeline

        mock_config.return_value = {
            "pdf_dir": str(tmp_path / "pdf"),
            "folders": [],
            "pre_sync_command": "echo hello",
            "post_sync_command": "",
        }
        (tmp_path / "pdf").mkdir()
        (tmp_path / "backup").mkdir(parents=True, exist_ok=True)
        (tmp_path / "output").mkdir(parents=True, exist_ok=True)

        mock_backup = MagicMock()
        mock_backup.run_backup.return_value = (True, set(), {})
        mock_backup_cls.return_value = mock_backup

        run_pipeline(
            backup_dir=tmp_path / "backup",
            output_dir=tmp_path / "output",
            log_level="NONE",
            skip_backup=False,
            skip_convert=True,
            ai_provider="",
            use_ai_ocr=False,
        )

        mock_backup_cls.assert_called_once()
        _, kwargs = mock_backup_cls.call_args
        assert kwargs.get("pre_sync_command") == "echo hello"

    @patch("src.config.load_config")
    @patch("src.hybrid_converter.find_notebooks", return_value=[])
    @patch(
        "src.hybrid_converter.organize_notebooks_by_structure",
        return_value={"documents_to_convert": []},
    )
    @patch("src.commands.pipeline.ReMarkableBackup")
    def test_pipeline_aborts_when_pre_sync_fails(
        self, mock_backup_cls, mock_org, mock_find, mock_config, tmp_path
    ):
        """run_pipeline returns 1 when backup fails (e.g. pre_sync_command exits non-zero)."""
        from src.commands.pipeline import run_pipeline

        mock_config.return_value = {
            "pdf_dir": str(tmp_path / "pdf"),
            "folders": [],
            "pre_sync_command": "exit 1",
            "post_sync_command": "",
        }
        (tmp_path / "pdf").mkdir()
        (tmp_path / "backup").mkdir(parents=True, exist_ok=True)
        (tmp_path / "output").mkdir(parents=True, exist_ok=True)

        mock_backup = MagicMock()
        mock_backup.run_backup.return_value = (False, set(), {})
        mock_backup_cls.return_value = mock_backup

        result = run_pipeline(
            backup_dir=tmp_path / "backup",
            output_dir=tmp_path / "output",
            log_level="NONE",
            skip_backup=False,
            skip_convert=True,
            ai_provider="",
            use_ai_ocr=False,
        )

        assert result == 1

    @patch("src.config.load_config")
    @patch("src.hybrid_converter.find_notebooks", return_value=[])
    @patch(
        "src.hybrid_converter.organize_notebooks_by_structure",
        return_value={"documents_to_convert": []},
    )
    @patch("src.commands.pipeline.ReMarkableBackup")
    def test_pipeline_runs_post_sync_command(
        self, mock_backup_cls, mock_org, mock_find, mock_config, tmp_path
    ):
        """run_pipeline passes post_sync_command to ReMarkableConnection which runs it in disconnect()."""
        from src.commands.pipeline import run_pipeline

        mock_config.return_value = {
            "pdf_dir": str(tmp_path / "pdf"),
            "folders": [],
            "pre_sync_command": "",
            "post_sync_command": "echo done",
        }
        (tmp_path / "pdf").mkdir()
        (tmp_path / "backup").mkdir(parents=True, exist_ok=True)
        (tmp_path / "output").mkdir(parents=True, exist_ok=True)

        mock_backup = MagicMock()
        mock_backup.run_backup.return_value = (True, set(), {})
        mock_backup_cls.return_value = mock_backup

        result = run_pipeline(
            backup_dir=tmp_path / "backup",
            output_dir=tmp_path / "output",
            log_level="NONE",
            skip_backup=False,
            skip_convert=True,
            ai_provider="",
            use_ai_ocr=False,
        )

        assert result == 0
        mock_backup_cls.assert_called_once()
        _, kwargs = mock_backup_cls.call_args
        assert kwargs.get("post_sync_command") == "echo done"
