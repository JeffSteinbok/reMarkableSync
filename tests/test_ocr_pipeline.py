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

    def test_clamp_to_max_dimension_leaves_small_image_unchanged(self):
        """Images within the API limit are returned unmodified."""
        from PIL import Image

        from src.ocr.ocr_engine import OCREngine

        engine = OCREngine(ai_provider=MockAIProvider(), use_ai=True)
        img = Image.new("RGB", (500, 300))

        result = engine._clamp_to_max_dimension(img, "test")

        assert result is img
        assert result.size == (500, 300)

    def test_clamp_to_max_dimension_resizes_oversized_image(self):
        """Images exceeding MAX_IMAGE_DIMENSION are downscaled, preserving aspect ratio."""
        from PIL import Image

        from src.ocr.ocr_engine import OCREngine

        engine = OCREngine(ai_provider=MockAIProvider(), use_ai=True)
        img = Image.new("RGB", (2000, 9000))

        result = engine._clamp_to_max_dimension(img, "test page")

        longest_side = max(result.size)
        assert OCREngine.MAX_IMAGE_DIMENSION - 1 <= longest_side <= OCREngine.MAX_IMAGE_DIMENSION
        # Aspect ratio preserved (within rounding)
        assert abs(result.size[0] / result.size[1] - 2000 / 9000) < 0.01

    def test_chunk_image_clamps_oversized_unsplit_image(self):
        """A wide single-chunk image over the limit is resized when saved."""
        from PIL import Image

        from src.ocr.ocr_engine import OCREngine

        engine = OCREngine(ai_provider=MockAIProvider(), use_ai=True)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            img_path = tmp_dir / "wide.png"
            Image.new("RGB", (9000, 400)).save(img_path)

            chunks = engine._chunk_image(img_path, tmp_dir)

            assert chunks == [img_path]
            with Image.open(img_path) as saved:
                assert max(saved.size) <= OCREngine.MAX_IMAGE_DIMENSION
