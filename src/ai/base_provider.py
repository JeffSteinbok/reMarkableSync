"""Abstract base class for AI providers.

All AI providers used by RemarkableSync (Claude, GitHub Models, etc.)
must subclass ``BaseAIProvider`` and implement the three abstract methods.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List


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
