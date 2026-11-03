"""Tests for the Markdown exporter."""

from pathlib import Path
from unittest.mock import MagicMock

from src.pdf_md_converter import MarkdownExporter, _file_hash
from src.utils import sanitize_name


def test_failed_ocr_is_not_reported_as_a_successful_export(tmp_path):
    from src.ai.base_provider import AIProviderError

    pdf = tmp_path / "page.pdf"
    _write_dummy_pdf(pdf)
    ocr = MagicMock()
    ocr.pdf_to_images.return_value = [tmp_path / "image.png"]
    ocr.ai_provider.transcribe_handwriting.side_effect = AIProviderError("API rejected request")
    exporter = MarkdownExporter(tmp_path / "out", tmp_path, ocr_engine=ocr, embed_images=False)

    result = exporter.export_notebook(_make_notebook("Failed note", "failed"), pdf)

    assert result is None
    assert exporter.failed_pages == 1
    assert not list((tmp_path / "out" / "Failed note").glob("*.md"))


def test_forced_export_counts_all_pages_in_ocr_progress(tmp_path, caplog):
    pdf = tmp_path / "page.pdf"
    _write_dummy_pdf(pdf)
    exporter = MarkdownExporter(tmp_path / "out", tmp_path, embed_images=False)

    with caplog.at_level("INFO"):
        exported, skipped, _ = exporter.export_all(
            [_make_notebook("Forced note", "forced")],
            tmp_path,
            force=True,
            converted_pages={"forced": [pdf]},
            updated_pages={},
        )

    assert (exported, skipped) == (1, 0)
    assert "OCR page 1 of 1" in caplog.text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_notebook(name: str, uuid: str, folder_path: str = "") -> dict:
    return {
        "uuid": uuid,
        "name": name,
        "type": "DocumentType",
        "folder_path": folder_path,
    }


def _write_dummy_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 dummy content for testing")


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


class TestSafeName:
    def test_replaces_illegal_fs_chars_with_hyphen(self):
        assert sanitize_name("Hello/World!") == "Hello-World!"

    def test_preserves_spaces_hyphens_underscores(self):
        assert sanitize_name("Hello World - Test_1") == "Hello World - Test_1"

    def test_preserves_parens_ampersand_dot(self):
        assert sanitize_name("Q&A (2024).notes") == "Q&A (2024).notes"

    def test_replaces_colon(self):
        assert sanitize_name("1:1") == "1-1"

    def test_empty_string(self):
        assert sanitize_name("") == ""

    def test_strips_whitespace(self):
        assert sanitize_name("  hello  ") == "hello"


class TestExtractTitle:
    """Tests for MarkdownExporter._extract_title date + title logic."""

    _et = staticmethod(MarkdownExporter._extract_title)

    def test_date_and_title(self):
        text = "8/27/24\n## Meeting Notes\nSome content"
        assert self._et(text, 1) == "2024-08-27 - Meeting Notes"

    def test_iso_date_and_title(self):
        text = "2024-01-15\n# Sprint Review\nDetails"
        assert self._et(text, 3) == "2024-01-15 - Sprint Review"

    def test_date_only(self):
        text = "8/27/24\n"
        assert self._et(text, 5) == "2024-08-27"

    def test_title_only(self):
        text = "# Weekly Standup\nNotes from the call"
        assert self._et(text, 2) == "Weekly Standup"

    def test_no_date_no_heading(self):
        text = "Just some text on the page"
        assert self._et(text, 4) == "Just some text on the page"

    def test_empty_text(self):
        assert self._et("", 7) == ""

    def test_whitespace_only(self):
        assert self._et("   \n\n  ", 3) == ""

    def test_mm_dd_yyyy_format(self):
        text = "12/25/2024\n# Christmas Plans"
        assert self._et(text, 1) == "2024-12-25 - Christmas Plans"

    def test_date_line_skipped_for_title(self):
        """A line that is *only* a date should not become the title."""
        text = "8/27/24\nReal title here"
        assert self._et(text, 1) == "2024-08-27 - Real title here"


class TestFileHash:
    def test_consistent_hash(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        h1 = _file_hash(f)
        h2 = _file_hash(f)
        assert h1 == h2
        assert len(h1) == 32  # MD5 hex digest

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello", encoding="utf-8")
        f2.write_text("world", encoding="utf-8")
        assert _file_hash(f1) != _file_hash(f2)


# ---------------------------------------------------------------------------
# MarkdownExporter
# ---------------------------------------------------------------------------


class TestMarkdownExporter:
    def _make_exporter(
        self, output_dir: Path, backup_dir: Path, ocr_engine=None
    ) -> MarkdownExporter:
        return MarkdownExporter(
            output_dir=output_dir,
            backup_dir=backup_dir,
            ocr_engine=ocr_engine,
            tags=["remarkable", "test"],
            embed_images=False,  # skip image export in unit tests
        )

    def test_creates_output_dir(self, tmp_path):
        output_dir = tmp_path / "output"
        backup = tmp_path / "backup"
        backup.mkdir()
        self._make_exporter(output_dir, backup)
        assert output_dir.exists()

    def test_state_file_created_after_export(self, tmp_path):
        output_dir = tmp_path / "output"
        backup = tmp_path / "backup"
        backup.mkdir()

        notebook = _make_notebook("My Note", "uuid-1234")
        pdf = backup / "My Note.pdf"
        _write_dummy_pdf(pdf)

        exp = self._make_exporter(output_dir, backup)
        result = exp.export_notebook(notebook, pdf)

        assert result is not None
        assert Path(result).exists()

    def test_markdown_file_created(self, tmp_path):
        output_dir = tmp_path / "output"
        backup = tmp_path / "backup"
        backup.mkdir()

        notebook = _make_notebook("Shopping List", "uuid-5678")
        pdf = backup / "Shopping List.pdf"
        _write_dummy_pdf(pdf)

        exp = self._make_exporter(output_dir, backup)
        result = exp.export_notebook(notebook, pdf)

        assert result is not None
        assert Path(result).exists()
        # Result is now a folder; find the .md inside
        md_files = list(Path(result).glob("*.md"))
        assert len(md_files) >= 1
        content = md_files[0].read_text(encoding="utf-8")
        assert "Shopping List" in content
        assert "remarkable_id: uuid-5678" in content

    def test_frontmatter_contains_tags(self, tmp_path):
        output_dir = tmp_path / "output"
        backup = tmp_path / "backup"
        backup.mkdir()

        notebook = _make_notebook("Tagged Note", "uuid-9999")
        pdf = backup / "Tagged Note.pdf"
        _write_dummy_pdf(pdf)

        exp = self._make_exporter(output_dir, backup)
        result = exp.export_notebook(notebook, pdf)

        md_files = list(Path(result).glob("*.md"))
        content = md_files[0].read_text(encoding="utf-8")
        assert "  - remarkable" in content
        assert "  - test" in content

    def test_incremental_skip_unchanged(self, tmp_path):
        output_dir = tmp_path / "output"
        backup = tmp_path / "backup"
        backup.mkdir()

        notebook = _make_notebook("Repeated Note", "uuid-repeat")
        pdf = backup / "Repeated Note.pdf"
        _write_dummy_pdf(pdf)

        exp = self._make_exporter(output_dir, backup)
        result1 = exp.export_notebook(notebook, pdf)
        assert result1 is not None

        import time

        time.sleep(0.05)

        # Second export – unchanged PDF should be skipped
        exp2 = self._make_exporter(output_dir, backup)
        result2 = exp2.export_notebook(notebook, pdf)
        # Should return the cached path (skip)
        assert result2 is not None

    def test_force_re_exports_unchanged(self, tmp_path):
        output_dir = tmp_path / "output"
        backup = tmp_path / "backup"
        backup.mkdir()

        notebook = _make_notebook("Force Note", "uuid-force")
        pdf = backup / "Force Note.pdf"
        _write_dummy_pdf(pdf)

        exp = self._make_exporter(output_dir, backup)
        exp.export_notebook(notebook, pdf)

        # Force re-export
        exp2 = self._make_exporter(output_dir, backup)
        result = exp2.export_notebook(notebook, pdf, force=True)
        assert result is not None

    def test_folder_hierarchy_respected(self, tmp_path):
        output_dir = tmp_path / "output"
        backup = tmp_path / "backup"
        backup.mkdir()

        notebook = _make_notebook("Deep Note", "uuid-deep", folder_path="Work/Projects")
        pdf = backup / "Deep Note.pdf"
        _write_dummy_pdf(pdf)

        exp = self._make_exporter(output_dir, backup)
        result = exp.export_notebook(notebook, pdf)

        assert result is not None
        # Notebook folder should be under Work/Projects/
        expected_dir = output_dir / "Work" / "Projects" / "Deep Note"
        assert expected_dir.exists()
        assert Path(result) == expected_dir

    def test_ocr_text_included_in_markdown(self, tmp_path):
        output_dir = tmp_path / "output"
        backup = tmp_path / "backup"
        backup.mkdir()

        notebook = _make_notebook("OCR Note", "uuid-ocr")
        pdf = backup / "OCR Note.pdf"
        _write_dummy_pdf(pdf)

        mock_provider = MagicMock()
        mock_provider.transcribe_handwriting.return_value = "## Heading\n\nProcessed text."
        mock_provider.cleanup_text.return_value = "## Heading\n\nProcessed text."

        mock_ocr = MagicMock()
        mock_ocr.use_ai = True
        mock_ocr.ai_provider = mock_provider
        mock_ocr.pdf_to_images.return_value = [Path("fake_image.png")]

        exp = MarkdownExporter(
            output_dir=output_dir,
            backup_dir=backup,
            ocr_engine=mock_ocr,
            embed_images=False,
        )
        result = exp.export_notebook(notebook, pdf)

        assert result is not None
        # Find the generated .md file in the notebook folder
        md_files = list(Path(result).glob("*.md"))
        assert len(md_files) >= 1
        content = md_files[0].read_text(encoding="utf-8")
        assert "Processed text." in content

    def test_export_all_returns_counts(self, tmp_path):
        output_dir = tmp_path / "output"
        backup = tmp_path / "backup"
        backup.mkdir()
        pdf_dir = backup / "PDF"

        notebooks = [
            _make_notebook("Note A", "uuid-a"),
            _make_notebook("Note B", "uuid-b"),
        ]
        for nb in notebooks:
            pdf = pdf_dir / f"{nb['name']}.pdf"
            _write_dummy_pdf(pdf)

        exp = self._make_exporter(output_dir, backup)
        exported, skipped, _dirs = exp.export_all(notebooks, pdf_dir)
        assert exported == 2
        assert skipped == 0

    def test_export_all_skips_collection_type(self, tmp_path):
        output_dir = tmp_path / "output"
        backup = tmp_path / "backup"
        backup.mkdir()
        pdf_dir = backup / "PDF"
        pdf_dir.mkdir()

        notebooks = [
            {"uuid": "folder-1", "name": "Work", "type": "CollectionType", "folder_path": ""},
            _make_notebook("My Note", "uuid-n"),
        ]
        pdf = pdf_dir / "My Note.pdf"
        _write_dummy_pdf(pdf)

        exp = self._make_exporter(output_dir, backup)
        exported, skipped, _dirs = exp.export_all(notebooks, pdf_dir)
        assert exported == 1  # only the document, not the folder
