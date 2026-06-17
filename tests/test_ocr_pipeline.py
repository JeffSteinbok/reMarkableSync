"""
Tests for the OCR pipeline using mock AI provider.

Exercises the full PDF → PNG → AI → text pipeline without API keys
or network calls.
"""

import tempfile
from pathlib import Path

import pytest

from tests.mock_ai_provider import MockAIProvider


class TestOCREngine:
    """Tests for OCREngine with mocked AI."""

    def test_pdf_to_images_pymupdf(self):
        """PyMuPDF renders a test PDF to PNG images."""
        from src.ocr.ocr_engine import OCREngine

        engine = OCREngine(image_dpi=72)
        pdf_path = Path("tests/fixtures/sample_test.pdf")
        if not pdf_path.exists():
            pytest.skip("sample_test.pdf not generated yet")

        with tempfile.TemporaryDirectory() as tmp:
            images = engine.pdf_to_images(pdf_path, Path(tmp))
            assert len(images) >= 1
            for img in images:
                assert img.exists()
                assert img.suffix == ".png"
                assert img.stat().st_size > 100

    def test_extract_text_with_mock_ai(self):
        """Full pipeline: PDF → images → mock AI → text output."""
        from src.ocr.ocr_engine import OCREngine

        pdf_path = Path("tests/fixtures/sample_test.pdf")
        if not pdf_path.exists():
            pytest.skip("sample_test.pdf not generated yet")

        mock_provider = MockAIProvider(
            transcription="- Buy groceries\n- Call dentist",
            cleanup="# Todo\n\n- Buy groceries\n- Call dentist",
        )
        engine = OCREngine(ai_provider=mock_provider, use_ai=True)

        raw, processed = engine.extract_text(pdf_path, notebook_name="Shopping List")

        # With chunking, raw text may be repeated per chunk
        assert "- Buy groceries" in raw
        assert "- Call dentist" in raw
        assert processed == "# Todo\n\n- Buy groceries\n- Call dentist"
        # Chunking may split into multiple calls
        assert mock_provider.transcribe_call_count >= 1
        assert mock_provider.cleanup_call_count == 1

    def test_extract_text_ai_unavailable_falls_through(self):
        """When AI returns empty, engine falls back (no crash)."""
        from src.ocr.ocr_engine import OCREngine

        pdf_path = Path("tests/fixtures/sample_test.pdf")
        if not pdf_path.exists():
            pytest.skip("sample_test.pdf not generated yet")

        # Provider that returns empty transcription
        mock_provider = MockAIProvider(transcription="")
        engine = OCREngine(ai_provider=mock_provider, use_ai=True)

        raw, processed = engine.extract_text(pdf_path, notebook_name="Empty")
        # Should not crash — falls through to pytesseract (which may also be unavailable)
        # In that case both are empty strings
        assert isinstance(raw, str)
        assert isinstance(processed, str)

    def test_mock_provider_records_image_paths(self):
        """Mock provider records which images were sent for transcription."""
        from src.ocr.ocr_engine import OCREngine

        pdf_path = Path("tests/fixtures/sample_test.pdf")
        if not pdf_path.exists():
            pytest.skip("sample_test.pdf not generated yet")

        mock_provider = MockAIProvider()
        engine = OCREngine(ai_provider=mock_provider, use_ai=True)
        engine.extract_text(pdf_path)

        # Should have been called with at least one PNG path (may be chunked)
        assert mock_provider.transcribe_call_count >= 1
        paths = mock_provider._transcribe_calls[0]
        assert len(paths) >= 1
        assert all(p.suffix == ".png" for p in paths)

    def test_no_pdf_returns_empty(self):
        """Non-existent PDF returns empty strings without crashing."""
        from src.ocr.ocr_engine import OCREngine

        mock_provider = MockAIProvider()
        engine = OCREngine(ai_provider=mock_provider, use_ai=True)

        raw, processed = engine.extract_text(Path("/nonexistent/file.pdf"))
        assert raw == ""
        assert processed == ""
        assert mock_provider.transcribe_call_count == 0
