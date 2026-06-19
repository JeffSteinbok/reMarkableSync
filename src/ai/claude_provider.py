"""Claude AI provider using the Anthropic API.

Requires the ``anthropic`` Python package and an ``ANTHROPIC_API_KEY``
environment variable (or the ``api_key`` constructor argument).
"""

import base64
import logging
import os
from pathlib import Path
from typing import List

from .base_provider import (
    CLEANUP_PROMPT,
    TRANSCRIPTION_PROMPT,
    AIProviderError,
    AIRateLimitError,
    BaseAIProvider,
)


class ClaudeProvider(BaseAIProvider):
    """AI provider backed by Anthropic Claude (vision + text models)."""

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str = "", model: str = ""):
        """Initialise the Claude provider.

        Args:
            api_key: Anthropic API key or OAuth token.  Falls back to the
                ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN`` environment
                variables when empty.
            model: Claude model identifier.  Defaults to
                ``claude-sonnet-4-6``.
        """
        self.api_key = (
            api_key
            or os.environ.get("ANTHROPIC_API_KEY", "")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        )
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
            import anthropic  # type: ignore

            # OAuth tokens (e.g. Claude Code) use auth_token; API keys use api_key
            if self.api_key.startswith("sk-ant-oat"):
                self._client = anthropic.Anthropic(auth_token=self.api_key)
            else:
                self._client = anthropic.Anthropic(api_key=self.api_key)
        except ImportError:
            logging.warning("anthropic package not installed – run: pip install anthropic")

    def is_available(self) -> bool:
        return self._client is not None and bool(self.api_key)

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def transcribe_handwriting(self, image_paths: List[Path], context: str = "") -> str:
        """Send page images to Claude for handwriting recognition."""
        if not self.is_available():
            return ""

        content: list = []
        for img_path in image_paths:
            if not img_path.exists():
                continue
            with open(img_path, "rb") as fh:
                img_b64 = base64.standard_b64encode(fh.read()).decode("utf-8")
            media_type = (
                "image/jpeg" if img_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            )
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": img_b64,
                    },
                }
            )

        if not content:
            return ""

        prompt = TRANSCRIPTION_PROMPT
        if context:
            prompt += f"\n\nNotebook context: {context}"
        content.append({"type": "text", "text": prompt})

        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": content}],
            )
            return message.content[0].text
        except Exception as exc:  # noqa: BLE001
            logging.error("Claude transcription API error: %s", exc)
            # Check for rate limit errors from Anthropic
            if _is_anthropic_rate_limit(exc):
                retry = _parse_anthropic_retry_after(exc)
                raise AIRateLimitError(str(exc), retry_after=retry) from exc
            raise AIProviderError(f"Claude transcription failed: {exc}") from exc

    def cleanup_text(self, raw_text: str, context: str = "") -> str:
        """Ask Claude to clean up and structure raw transcribed text."""
        if not self.is_available() or not raw_text.strip():
            return raw_text

        prompt = CLEANUP_PROMPT
        if context:
            prompt += f"\n\nNotebook context: {context}"

        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": f"{prompt}\n\n---\n{raw_text}",
                    }
                ],
            )
            return message.content[0].text
        except Exception as exc:  # noqa: BLE001
            logging.error("Claude cleanup API error: %s", exc)
            # Check for rate limit errors from Anthropic
            if _is_anthropic_rate_limit(exc):
                retry = _parse_anthropic_retry_after(exc)
                raise AIRateLimitError(str(exc), retry_after=retry) from exc
            raise AIProviderError(f"Claude cleanup failed: {exc}") from exc


def _is_anthropic_rate_limit(exc: Exception) -> bool:
    """Check if an exception is an Anthropic rate limit error."""
    try:
        from anthropic import RateLimitError

        return isinstance(exc, RateLimitError)
    except ImportError:
        # Fall back to string detection
        exc_str = str(exc)
        return "429" in exc_str or "rate" in exc_str.lower()


def _parse_anthropic_retry_after(exc: Exception) -> int:
    """Extract retry-after seconds from an Anthropic rate limit exception."""
    import re

    exc_str = str(exc)
    # Try to find retry-after in the error message
    match = re.search(r"retry.after[:\s]+(\d+)", exc_str, re.IGNORECASE)
    if match:
        return int(match.group(1))
    # Default backoff for Anthropic
    return 60
