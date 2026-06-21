"""TrOCR local OCR provider.

Runs Microsoft's TrOCR (Transformer-based OCR) model locally, with no API
key or network access required after the initial model download.

Requires ``transformers`` and ``torch``::

    pip install transformers torch

The first call to :meth:`transcribe_handwriting` will download the model
(~300 MB for ``microsoft/trocr-base-handwritten``) into the HuggingFace cache
(``~/.cache/huggingface`` by default).
"""

import logging
from pathlib import Path
from typing import List, Optional

from .base_provider import BaseAIProvider

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "microsoft/trocr-base-handwritten"

# Height in pixels to slice each input image into bands.
# TrOCR works best on single-line crops; 80 px is a practical heuristic for
# typical reMarkable handwriting rendered at 300 DPI.
_BAND_HEIGHT_PX = 80


class TrOCRProvider(BaseAIProvider):
    """Offline handwriting OCR using Microsoft TrOCR.

    Runs entirely on the local machine — no internet access is needed after
    the one-time model download (~300 MB).  Because TrOCR is a recognition-
    only model (no language model component), :meth:`cleanup_text` returns the
    raw text unchanged.
    """

    def __init__(self, model_name: str = "", device: str = "cpu"):
        """Initialise the TrOCR provider.

        Args:
            model_name: HuggingFace model identifier.  Defaults to
                ``microsoft/trocr-base-handwritten``.
            device: PyTorch device string, e.g. ``"cpu"`` or ``"cuda"``.
        """
        self.model_name = model_name or _DEFAULT_MODEL
        self.device = device
        self._processor = None
        self._model = None
        self._available: Optional[bool] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_model(self) -> bool:
        """Lazy-load the TrOCR processor and model.

        Returns:
            True if the model loaded successfully, False otherwise.
        """
        if self._model is not None:
            return True
        if self._available is False:
            return False

        try:
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel  # type: ignore

            logger.info("Loading TrOCR model '%s' (this may take a moment)…", self.model_name)
            self._processor = TrOCRProcessor.from_pretrained(self.model_name)
            self._model = VisionEncoderDecoderModel.from_pretrained(self.model_name)
            self._model.to(self.device)
            self._model.eval()
            logger.info("TrOCR model loaded successfully.")
            self._available = True
            return True
        except ImportError:
            logger.warning(
                "transformers / torch not installed — run: pip install transformers torch"
            )
            self._available = False
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load TrOCR model '%s': %s", self.model_name, exc)
            self._available = False
            return False

    def _run_trocr_on_image(self, pil_image) -> str:
        """Run TrOCR inference on a single PIL image.

        The image is sliced into horizontal bands and each band is passed
        through TrOCR independently; the results are then joined with newlines.

        Args:
            pil_image: A ``PIL.Image`` in RGB mode.

        Returns:
            Transcribed text, or empty string on failure.
        """
        import torch  # type: ignore

        w, h = pil_image.size
        num_bands = max(1, h // _BAND_HEIGHT_PX)
        band_h = h // num_bands

        lines: List[str] = []
        for i in range(num_bands):
            y0 = i * band_h
            y1 = y0 + band_h if i < num_bands - 1 else h
            band = pil_image.crop((0, y0, w, y1)).convert("RGB")

            try:
                pixel_values = self._processor(images=band, return_tensors="pt").pixel_values
                pixel_values = pixel_values.to(self.device)

                with torch.no_grad():
                    generated_ids = self._model.generate(pixel_values)

                text = self._processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
                text = text.strip()
                if text:
                    lines.append(text)
            except Exception as exc:  # noqa: BLE001
                logger.debug("TrOCR band %d/%d failed: %s", i + 1, num_bands, exc)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # BaseAIProvider interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if transformers and torch are importable.

        Does *not* download the model — the download happens on the first call
        to :meth:`transcribe_handwriting`.
        """
        if self._available is not None:
            return self._available
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401

            self._available = True
        except ImportError:
            self._available = False
        return self._available

    def transcribe_handwriting(self, image_paths: List[Path], context: str = "") -> str:
        """Transcribe handwriting from page images using TrOCR.

        Args:
            image_paths: Ordered list of page image file paths (PNG/JPEG).
            context: Notebook name or other hint (not used by TrOCR).

        Returns:
            Raw transcribed text; empty string if unavailable or on error.
        """
        if not self._load_model():
            return ""

        try:
            from PIL import Image  # type: ignore
        except ImportError:
            logger.warning("Pillow not installed — run: pip install Pillow")
            return ""

        parts: List[str] = []
        for img_path in image_paths:
            if not img_path.exists():
                continue
            try:
                with Image.open(img_path) as img:
                    text = self._run_trocr_on_image(img.convert("RGB"))
                    if text:
                        parts.append(text)
            except Exception as exc:  # noqa: BLE001
                logger.debug("TrOCR failed for %s: %s", img_path.name, exc)

        return "\n\n".join(parts)

    def cleanup_text(self, raw_text: str, context: str = "") -> str:
        """Return *raw_text* unchanged.

        TrOCR is a recognition-only model; there is no language-model step to
        clean up or restructure the output.
        """
        return raw_text
