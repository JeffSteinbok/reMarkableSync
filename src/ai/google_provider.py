"""Google AI provider using the Gemini API.

Supports both free-tier and paid Google AI Studio / Vertex AI access.

Requires the ``google-genai`` Python package and a ``GOOGLE_API_KEY``
environment variable (or the ``api_key`` constructor argument).
"""

import logging
import os
import re
from pathlib import Path
from typing import List

from .base_provider import (
    CLEANUP_PROMPT,
    AIProviderError,
    AIRateLimitError,
    BaseAIProvider,
    get_transcription_prompt,
)


class GoogleProvider(BaseAIProvider):
    """AI provider backed by Google Gemini (vision + text models)."""

    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: str = "", model: str = ""):
        """Initialise the Google provider.

        Args:
            api_key: Google AI API key.  Falls back to the ``GOOGLE_API_KEY``
                environment variable when empty.
            model: Gemini model identifier.  Defaults to ``gemini-2.5-flash``.
        """
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        self.model = model or self.DEFAULT_MODEL
        self._client = None
        self._init_client()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_client(self) -> None:
        if not self.api_key:
            return
        try:
            from google import genai  # type: ignore

            self._client = genai.Client(api_key=self.api_key)
        except ImportError:
            logging.warning("google-genai package not installed – run: pip install google-genai")

    def is_available(self) -> bool:
        return self._client is not None and bool(self.api_key)

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def transcribe_handwriting(self, image_paths: List[Path], context: str = "") -> str:
        """Send page images to Gemini for handwriting recognition."""
        if not self.is_available():
            return ""

        try:
            from PIL import Image  # type: ignore
        except ImportError:
            logging.warning("Pillow not installed – run: pip install Pillow")
            return ""

        content: list = []
        prompt = get_transcription_prompt()
        if context:
            prompt += f"\n\nNotebook context: {context}"
        content.append(prompt)

        for img_path in image_paths:
            if not img_path.exists():
                continue
            try:
                img = Image.open(img_path)
                content.append(img)
            except Exception as exc:  # noqa: BLE001
                logging.warning("Failed to load image %s: %s", img_path, exc)
                continue

        if len(content) == 1:  # Only prompt, no images
            return ""

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=content,
            )
            return response.text
        except Exception as exc:  # noqa: BLE001
            logging.error("Google transcription API error: %s", exc)
            if _is_google_rate_limit(exc):
                retry = _parse_google_retry_after(exc)
                raise AIRateLimitError(str(exc), retry_after=retry) from exc
            raise AIProviderError(f"Google transcription failed: {exc}") from exc

    def cleanup_text(self, raw_text: str, context: str = "") -> str:
        """Ask Gemini to clean up and structure raw transcribed text."""
        if not self.is_available() or not raw_text.strip():
            return raw_text

        prompt = CLEANUP_PROMPT
        if context:
            prompt += f"\n\nNotebook context: {context}"

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=f"{prompt}\n\n---\n{raw_text}",
            )
            return response.text
        except Exception as exc:  # noqa: BLE001
            logging.error("Google cleanup API error: %s", exc)
            if _is_google_rate_limit(exc):
                retry = _parse_google_retry_after(exc)
                raise AIRateLimitError(str(exc), retry_after=retry) from exc
            raise AIProviderError(f"Google cleanup failed: {exc}") from exc


def _is_google_rate_limit(exc: Exception) -> bool:
    """Check if an exception is a Google rate limit error."""
    exc_str = str(exc).lower()
    return "429" in exc_str or "quota" in exc_str or "rate" in exc_str


def _parse_google_retry_after(exc: Exception) -> int:
    """Extract retry-after seconds from a Google rate limit exception."""
    exc_str = str(exc)
    match = re.search(r"retry.after[:\s]+(\d+)", exc_str, re.IGNORECASE)
    if match:
        return int(match.group(1))
    # Default backoff for Google
    return 60
