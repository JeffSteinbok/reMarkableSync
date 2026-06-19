"""GitHub Models / OpenAI-compatible AI provider.

Works with:
- GitHub Models (https://models.inference.ai.azure.com) using a GitHub
  personal-access-token (PAT) as the API key.
- Azure OpenAI deployments and any other OpenAI-compatible endpoint.

Requires the ``openai`` Python package and a ``GITHUB_TOKEN`` (or
``OPENAI_API_KEY``) environment variable (or the ``api_key`` argument).
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
    parse_retry_after,
)


class GitHubModelsProvider(BaseAIProvider):
    """AI provider using the GitHub Copilot API.

    Uses the GitHub Copilot endpoint which supports GPT-4o, Claude, Gemini,
    and other models via an OpenAI-compatible interface.
    """

    GITHUB_COPILOT_ENDPOINT = "https://api.githubcopilot.com"
    # Legacy endpoints (kept for reference)
    GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference"
    LEGACY_AZURE_ENDPOINT = "https://models.inference.ai.azure.com"
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key: str = "", model: str = "", endpoint: str = ""):
        """Initialise the GitHub Copilot provider.

        Args:
            api_key: GitHub PAT or OAuth token. Falls back to the
                ``GITHUB_TOKEN`` env-var.
            model: Model identifier. Defaults to ``gpt-4o``.
            endpoint: Base URL for the inference endpoint. Defaults to the
                GitHub Copilot endpoint.
        """
        self.api_key = (
            api_key or os.environ.get("GITHUB_TOKEN", "") or os.environ.get("OPENAI_API_KEY", "")
        )
        self.model = model or self.DEFAULT_MODEL
        self.endpoint = endpoint or self.GITHUB_COPILOT_ENDPOINT
        self._client = None
        self._init_client()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_client(self) -> None:
        if not self.api_key:
            return
        try:
            from openai import OpenAI  # type: ignore

            self._client = OpenAI(
                base_url=self.endpoint,
                api_key=self.api_key,
                default_headers={"Copilot-Integration-Id": "vscode-chat"},
            )
        except ImportError:
            logging.warning("openai package not installed – run: pip install openai")

    def is_available(self) -> bool:
        return self._client is not None and bool(self.api_key)

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def transcribe_handwriting(self, image_paths: List[Path], context: str = "") -> str:
        """Send page images to the vision model for handwriting recognition."""
        if not self.is_available():
            return ""

        content: list = []
        for img_path in image_paths:
            if not img_path.exists():
                continue
            with open(img_path, "rb") as fh:
                img_b64 = base64.standard_b64encode(fh.read()).decode("utf-8")
            mime = "image/jpeg" if img_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{img_b64}"},
                }
            )

        if not content:
            return ""

        prompt = TRANSCRIPTION_PROMPT
        if context:
            prompt += f"\n\nNotebook context: {context}"
        content.append({"type": "text", "text": prompt})

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                max_tokens=4096,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            logging.debug("GitHub Copilot transcription error: %s", exc)
            retry = parse_retry_after(exc)
            if retry is not None:
                raise AIRateLimitError(str(exc), retry_after=retry) from exc
            raise AIProviderError(f"GitHub Copilot transcription failed: {exc}") from exc

    def cleanup_text(self, raw_text: str, context: str = "") -> str:
        """Ask the model to clean up and structure raw transcribed text."""
        if not self.is_available() or not raw_text.strip():
            return raw_text

        prompt = CLEANUP_PROMPT
        if context:
            prompt += f"\n\nNotebook context: {context}"

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You format handwritten notes into clean Markdown.",
                    },
                    {
                        "role": "user",
                        "content": f"{prompt}\n\n---\n{raw_text}",
                    },
                ],
                max_tokens=4096,
            )
            return response.choices[0].message.content or raw_text
        except Exception as exc:  # noqa: BLE001
            logging.error("GitHub Models cleanup error: %s", exc)
            retry = parse_retry_after(exc)
            if retry is not None:
                raise AIRateLimitError(str(exc), retry_after=retry) from exc
            raise AIProviderError(f"GitHub Models cleanup failed: {exc}") from exc
