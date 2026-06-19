"""Abstract base class for AI providers.

All AI providers used by RemarkableSync (Claude, GitHub Models, etc.)
must subclass ``BaseAIProvider`` and implement the three abstract methods.
"""

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional


class AIProviderError(Exception):
    """Raised when an AI provider API call fails."""


class AIRateLimitError(AIProviderError):
    """Raised on 429 rate-limit responses. Contains retry_after hint."""

    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Shared prompt templates
# ---------------------------------------------------------------------------

TRANSCRIPTION_PROMPT = (
    "You are an expert at reading handwritten notes.\n"
    "Carefully transcribe ALL text from this handwritten page image.\n"
    "Guidelines:\n"
    "- Preserve the structure and layout as much as possible.\n"
    "- Use Markdown formatting (# for headings, - for bullets) where appropriate.\n"
    "- If you see diagrams or drawings, briefly describe them in [square brackets].\n"
    "- Maintain paragraph breaks from the original.\n"
    "- Correct obvious spelling errors but preserve the writer's intent.\n"
    "- Do NOT wrap output in code fences (no ``` blocks).\n"
    "Output ONLY the transcribed text, no explanations or meta-commentary."
)

CLEANUP_PROMPT = (
    "You are an expert at organising handwritten notes into clean Markdown.\n"
    "Take the following raw transcribed text and:\n"
    "1. Fix any transcription errors.\n"
    "2. Add appropriate Markdown headings based on content structure.\n"
    "3. Convert lists to proper Markdown bullets or numbered items.\n"
    "4. Highlight action items with **bold** or a > blockquote.\n"
    "5. Preserve ALL information – do not summarise or omit content.\n\n"
    "Output ONLY the formatted Markdown, no explanations.\n"
    "Do NOT wrap the output in code fences (no ``` blocks)."
)


def get_transcription_prompt() -> str:
    """Get the full transcription prompt, including any custom instructions.

    Loads custom instructions from the user's config directory and appends
    them to the base transcription prompt.

    Returns:
        The complete transcription prompt.
    """
    from src.config import load_custom_instructions

    prompt = TRANSCRIPTION_PROMPT
    custom = load_custom_instructions()
    if custom:
        prompt += f"\n\nAdditional instructions:\n{custom}"
    return prompt


# ---------------------------------------------------------------------------
# Shared utility functions for AI providers
# ---------------------------------------------------------------------------


def parse_retry_after(exc: Exception) -> Optional[int]:
    """Extract retry-after seconds from a rate-limit exception.

    Checks for the OpenAI SDK ``RateLimitError`` type first, then
    falls back to string matching on the message.

    This is a shared utility used by multiple AI providers to handle
    rate limiting consistently.

    Args:
        exc: The exception to parse for retry information.

    Returns:
        Seconds to wait before retrying, or None if this isn't a rate-limit error.
    """
    try:
        from openai import RateLimitError

        if not isinstance(exc, RateLimitError):
            return None
    except ImportError:
        # No SDK — fall back to string detection
        exc_str = str(exc)
        if "429" not in exc_str and "RateLimit" not in exc_str:
            return None

    exc_str = str(exc)
    match = re.search(r"[Pp]lease wait (\d+) seconds", exc_str)
    if match:
        return int(match.group(1))
    # Default backoff if we can detect 429 but no explicit wait time
    return 60


class BaseAIProvider(ABC):
    """Abstract base for all AI LLM / vision providers."""

    @abstractmethod
    def transcribe_handwriting(self, image_paths: List[Path], context: str = "") -> str:
        """Transcribe handwriting from one or more page images.

        Args:
            image_paths: Ordered list of page image file paths (PNG/JPEG).
            context: Optional notebook name or other contextual hint.

        Returns:
            Raw transcribed text, empty string on failure.
        """
        raise NotImplementedError

    @abstractmethod
    def cleanup_text(self, raw_text: str, context: str = "") -> str:
        """Clean up and structure raw OCR/HTR output using the LLM.

        Args:
            raw_text: Raw text from transcription or pytesseract.
            context: Optional notebook name or other contextual hint.

        Returns:
            Formatted Markdown text; returns *raw_text* unchanged on failure.
        """
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when the provider is properly configured and ready."""
        raise NotImplementedError
