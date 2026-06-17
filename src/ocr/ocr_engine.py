"""OCR engine for extracting text from ReMarkable notebook PDFs.

Strategy
--------
1. Convert PDF pages to PNG images using PyMuPDF (preferred) or pdf2image/Poppler.
2. Send the images to a configured AI provider for vision-based handwriting
   transcription.

External dependencies (all optional – graceful degradation if missing):
- ``PyMuPDF`` (``pip install pymupdf``) – recommended, no system deps
- ``pdf2image``  + Poppler system package (legacy fallback)
"""

import logging
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from ..ai.base_provider import BaseAIProvider


class OCREngine:
    """Extract text from notebook PDF files using AI vision."""

    # Target chunk height in pixels for OCR (smaller chunks = better recognition)
    CHUNK_TARGET_HEIGHT = 800
    CHUNK_OVERLAP_PCT = 0.15

    def __init__(
        self,
        ai_provider: Optional[BaseAIProvider] = None,
        use_ai: bool = True,
        image_dpi: int = 300,
    ):
        """Initialise the OCR engine.

        Args:
            ai_provider: Configured AI provider instance.
            use_ai: When *False* skip AI even if a provider is configured.
            image_dpi: Resolution used when rasterising PDF pages.
        """
        self.ai_provider = ai_provider
        self.use_ai = use_ai and ai_provider is not None and ai_provider.is_available()
        self.image_dpi = image_dpi

    # ------------------------------------------------------------------
    # PDF → images
    # ------------------------------------------------------------------

    def pdf_to_images(self, pdf_path: Path, output_dir: Path) -> List[Path]:
        """Rasterise every page of *pdf_path* to a PNG file.

        Tries PyMuPDF first (pure pip, no system deps), then falls back to
        pdf2image + Poppler.

        Args:
            pdf_path: Path to the source PDF.
            output_dir: Directory where page images are written.

        Returns:
            Ordered list of image paths; empty list when neither renderer
            is available or conversion fails.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Try PyMuPDF first (preferred — no system dependencies)
        images = self._pdf_to_images_pymupdf(pdf_path, output_dir)
        if images:
            return images

        # Fallback to pdf2image + Poppler
        return self._pdf_to_images_pdf2image(pdf_path, output_dir)

    def _pdf_to_images_pymupdf(self, pdf_path: Path, output_dir: Path) -> List[Path]:
        """Rasterise PDF using PyMuPDF (fitz)."""
        try:
            import fitz  # type: ignore  # PyMuPDF
        except ImportError:
            logging.debug("PyMuPDF not installed, trying pdf2image fallback.")
            return []

        try:
            doc = fitz.open(str(pdf_path))
            image_paths: List[Path] = []
            zoom = self.image_dpi / 72.0  # PDF default is 72 DPI
            matrix = fitz.Matrix(zoom, zoom)

            for idx, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=matrix)
                img_path = output_dir / f"page_{idx:03d}.png"
                pix.save(str(img_path))
                image_paths.append(img_path)

            doc.close()
            logging.debug("PyMuPDF rasterised %d pages from %s", len(image_paths), pdf_path.name)
            return image_paths
        except Exception as exc:  # noqa: BLE001
            logging.error("PyMuPDF failed for %s: %s", pdf_path.name, exc)
            return []

    def _pdf_to_images_pdf2image(self, pdf_path: Path, output_dir: Path) -> List[Path]:
        """Rasterise PDF using pdf2image + Poppler (legacy fallback)."""
        try:
            from pdf2image import convert_from_path  # type: ignore
        except ImportError:
            logging.warning(
                "Neither PyMuPDF nor pdf2image is installed – cannot rasterise PDF. "
                "Run: pip install pymupdf  (recommended)"
            )
            return []

        try:
            pages = convert_from_path(str(pdf_path), dpi=self.image_dpi)
            image_paths: List[Path] = []
            for idx, page in enumerate(pages, start=1):
                img_path = output_dir / f"page_{idx:03d}.png"
                page.save(str(img_path), "PNG")
                image_paths.append(img_path)
            logging.debug("pdf2image rasterised %d pages from %s", len(image_paths), pdf_path.name)
            return image_paths
        except Exception as exc:  # noqa: BLE001
            logging.error("pdf2image failed for %s: %s", pdf_path.name, exc)
            return []

    def _chunk_image(self, img_path: Path, output_dir: Path) -> List[Path]:
        """Split a tall image into overlapping vertical chunks for better OCR.

        Returns list of chunk image paths, or [img_path] if no chunking needed.
        """
        try:
            from PIL import Image
        except ImportError:
            logging.debug("PIL not available for chunking, using original image")
            return [img_path]

        try:
            with Image.open(img_path) as img:
                w, h = img.size
                num_chunks = max(1, h // self.CHUNK_TARGET_HEIGHT)

                if num_chunks <= 1:
                    return [img_path]

                logging.debug(
                    "Splitting %s (%dx%d) into %d chunks with %d%% overlap",
                    img_path.name,
                    w,
                    h,
                    num_chunks,
                    int(self.CHUNK_OVERLAP_PCT * 100),
                )

                chunk_paths: List[Path] = []
                base_chunk_h = h // num_chunks
                overlap_px = int(base_chunk_h * self.CHUNK_OVERLAP_PCT)

                for i in range(num_chunks):
                    y_start = max(0, i * base_chunk_h - (overlap_px if i > 0 else 0))
                    y_end = min(
                        h, (i + 1) * base_chunk_h + (overlap_px if i < num_chunks - 1 else 0)
                    )

                    chunk = img.crop((0, y_start, w, y_end))
                    chunk_path = output_dir / f"{img_path.stem}_chunk{i+1:02d}.png"
                    chunk.save(chunk_path)
                    chunk_paths.append(chunk_path)
                    logging.debug(
                        "  Chunk %d: %s (%dx%d)", i + 1, chunk_path.name, w, y_end - y_start
                    )

                return chunk_paths
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to chunk image %s: %s", img_path.name, exc)
            return [img_path]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_text(
        self,
        pdf_path: Path,
        notebook_name: str = "",
        page_pdfs: Optional[List[Path]] = None,
        on_page_done: Optional[callable] = None,
    ) -> Tuple[str, str]:
        """Extract text from a notebook PDF using AI vision.

        Returns:
            ``(raw_text, processed_text)`` tuple.
        """
        if not self.use_ai or not self.ai_provider:
            logging.warning("No AI provider configured – OCR skipped for '%s'", notebook_name)
            return "", ""

        if not page_pdfs and not pdf_path.exists():
            logging.warning("PDF not found for OCR: %s", pdf_path)
            return "", ""

        with tempfile.TemporaryDirectory(prefix="rs_ocr_") as tmp_str:
            tmp_dir = Path(tmp_str)

            total = len(page_pdfs) if page_pdfs else 1

            logging.info("Running AI handwriting recognition for '%s'", notebook_name)
            all_raw_parts: List[str] = []

            if page_pdfs:
                for idx, pp in enumerate(page_pdfs, start=1):
                    if not pp.exists():
                        continue
                    page_dir = tmp_dir / f"page_{idx:03d}"
                    page_images = self.pdf_to_images(pp, page_dir)
                    if page_images:
                        # Chunk each page image for better OCR
                        for img_path in page_images:
                            chunks = self._chunk_image(img_path, page_dir)
                            for ci, chunk_path in enumerate(chunks):
                                chunk_ctx = f"{notebook_name} (page {idx}"
                                if len(chunks) > 1:
                                    chunk_ctx += f", part {ci + 1}/{len(chunks)}"
                                chunk_ctx += ")"
                                raw_part = self.ai_provider.transcribe_handwriting(
                                    [chunk_path], context=chunk_ctx
                                )
                                if raw_part:
                                    all_raw_parts.append(raw_part)
                    if on_page_done:
                        on_page_done(idx, total)
            else:
                all_images = self.pdf_to_images(pdf_path, tmp_dir)
                if all_images:
                    # Chunk each page image for better OCR
                    for img_path in all_images:
                        chunks = self._chunk_image(img_path, tmp_dir)
                        for ci, chunk_path in enumerate(chunks):
                            chunk_ctx = notebook_name
                            if len(chunks) > 1:
                                chunk_ctx += f" (part {ci + 1}/{len(chunks)})"
                            raw_part = self.ai_provider.transcribe_handwriting(
                                [chunk_path], context=chunk_ctx
                            )
                            if raw_part:
                                all_raw_parts.append(raw_part)
                if on_page_done:
                    on_page_done(1, 1)

            if all_raw_parts:
                raw = "\n\n".join(all_raw_parts)
                processed = self.ai_provider.cleanup_text(raw, context=notebook_name)
                return raw, processed

            logging.warning("AI transcription returned empty for '%s'", notebook_name)
            return "", ""
