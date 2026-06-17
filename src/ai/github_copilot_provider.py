"""GitHub Copilot AI provider using token exchange.

Uses the GitHub Copilot API with OAuth device flow authentication
and internal token exchange. Vision/OCR uses different endpoints based on model:
- Claude models: /v1/messages with Anthropic format
- GPT-5.x models: /v1/responses with OpenAI Responses format
"""

import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from .base_provider import (
    CLEANUP_PROMPT,
    AIProviderError,
    AIRateLimitError,
    BaseAIProvider,
    get_transcription_prompt,
)

# Token exchange endpoint and headers
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_HEADERS = {
    "Accept": "application/json",
    "Copilot-Integration-Id": "vscode-chat",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "X-Github-Api-Version": "2025-04-01",
}

# Default endpoint for individual Copilot users
DEFAULT_COPILOT_ENDPOINT = "https://api.individual.githubcopilot.com"


def _is_claude_model(model_id: str) -> bool:
    """Check if model is a Claude model (uses Anthropic format)."""
    return "claude" in model_id.lower()


def _is_responses_api_model(model_id: str) -> bool:
    """Check if model supports the OpenAI Responses API for vision."""
    # GPT-5.x models support /v1/responses, GPT-4.x does not
    lower = model_id.lower()
    return lower.startswith("gpt-5") or lower.startswith("o1") or lower.startswith("o3")


class GitHubCopilotProvider(BaseAIProvider):
    """AI provider using GitHub Copilot API with token exchange.

    Authenticates using a GitHub OAuth token (from device flow with Copilot
    client ID), exchanges it for a short-lived Copilot API token, and
    calls the Copilot API using the OpenAI SDK.
    """

    DEFAULT_MODEL = "claude-sonnet-4.5"

    def __init__(self, api_key: str = "", model: str = "", **kwargs):
        """Initialise the GitHub Copilot provider.

        Args:
            api_key: GitHub OAuth token (from device flow with Copilot client ID).
                     Falls back to GITHUB_TOKEN env var.
            model: Model identifier. Defaults to claude-sonnet-4.5.
            **kwargs: Ignored (for compatibility).
        """
        import os

        self._github_token = api_key or os.environ.get("GITHUB_TOKEN", "")
        self.model = model or self.DEFAULT_MODEL
        self._copilot_token: Optional[str] = None
        self._copilot_endpoint: Optional[str] = None
        self._token_expires_at: float = 0
        self._client = None

    def _ensure_copilot_token(self) -> bool:
        """Exchange GitHub token for Copilot token if needed.

        Returns True if we have a valid Copilot token.
        """
        # Check if we have a valid cached token (with 60s buffer)
        if self._copilot_token and time.time() < self._token_expires_at - 60:
            return True

        if not self._github_token:
            logging.warning("No GitHub token available for Copilot API")
            return False

        # Exchange for Copilot token
        headers = {
            **COPILOT_HEADERS,
            "Authorization": f"Bearer {self._github_token}",
        }
        try:
            resp = requests.get(COPILOT_TOKEN_URL, headers=headers, timeout=30)
            if resp.status_code == 404:
                logging.error("Copilot API not available. Check your Copilot subscription.")
                return False
            if resp.status_code in (401, 403):
                logging.error("GitHub token not authorized for Copilot. Re-run config.")
                return False
            resp.raise_for_status()

            data = resp.json()
            self._copilot_token = data.get("token")
            if not self._copilot_token:
                logging.error("No token in Copilot response")
                return False

            # Parse expiration and endpoint from token
            # Token format: tid=...;exp=TIMESTAMP;...;proxy-ep=ENDPOINT;...
            self._token_expires_at = self._parse_token_expiry(self._copilot_token)
            self._copilot_endpoint = self._parse_token_endpoint(self._copilot_token)

            # Initialize OpenAI client with Copilot endpoint
            self._init_client()
            return True

        except requests.RequestException as exc:
            logging.error("Copilot token exchange failed: %s", exc)
            return False

    def _parse_token_expiry(self, token: str) -> float:
        """Extract expiration timestamp from Copilot token."""
        match = re.search(r"exp=(\d+)", token)
        if match:
            return float(match.group(1))
        return time.time() + 1800  # Default 30 min

    def _parse_token_endpoint(self, token: str) -> str:
        """Extract API endpoint from Copilot token.

        The token contains proxy-ep=proxy.xxx.githubcopilot.com
        We convert proxy. to api. for the actual API calls.
        """
        match = re.search(r"proxy-ep=([^;]+)", token)
        if match:
            endpoint = match.group(1)
            if not endpoint.startswith("http"):
                endpoint = f"https://{endpoint}"
            # Convert proxy. to api. for API calls
            endpoint = re.sub(r"^(https?://)proxy\.", r"\1api.", endpoint)
            return endpoint
        return DEFAULT_COPILOT_ENDPOINT

    def _init_client(self) -> None:
        """Initialize the OpenAI client with Copilot endpoint."""
        if not self._copilot_token or not self._copilot_endpoint:
            return
        try:
            from openai import OpenAI

            self._client = OpenAI(
                base_url=self._copilot_endpoint,
                api_key=self._copilot_token,
                default_headers={"Copilot-Integration-Id": "vscode-chat"},
            )
        except ImportError:
            logging.warning("openai package not installed – run: pip install openai")

    def is_available(self) -> bool:
        """Check if the provider is configured and can authenticate."""
        return bool(self._github_token) and self._ensure_copilot_token()

    def transcribe_handwriting(self, image_paths: List[Path], context: str = "") -> str:
        """Send page images to vision model for handwriting recognition.

        Routes to the appropriate endpoint based on model type:
        - Claude models: /v1/messages with Anthropic format
        - GPT-5.x models: /v1/responses with OpenAI Responses format
        """
        if not self._ensure_copilot_token():
            return ""

        prompt = get_transcription_prompt()
        if context:
            prompt += f"\n\nNotebook context: {context}"

        # Route based on model type
        if _is_claude_model(self.model):
            return self._transcribe_anthropic(image_paths, prompt)
        elif _is_responses_api_model(self.model):
            return self._transcribe_openai_responses(image_paths, prompt)
        else:
            # Fallback: try Anthropic format (most reliable for vision)
            logging.warning("Model %s may not support vision. Trying Anthropic format.", self.model)
            return self._transcribe_anthropic(image_paths, prompt)

    def _transcribe_anthropic(self, image_paths: List[Path], prompt: str) -> str:
        """Transcribe using Anthropic /v1/messages endpoint (for Claude)."""
        content: list = []
        for img_path in image_paths:
            if not img_path.exists():
                continue
            with open(img_path, "rb") as fh:
                img_b64 = base64.standard_b64encode(fh.read()).decode("utf-8")
            mime = "image/jpeg" if img_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": img_b64},
                }
            )

        if not content:
            return ""
        content.append({"type": "text", "text": prompt})

        headers = {
            "Authorization": f"Bearer {self._copilot_token}",
            "Content-Type": "application/json",
            "Copilot-Integration-Id": "vscode-chat",
            "Copilot-Vision-Request": "true",
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": content}],
            "stream": True,
        }

        try:
            resp = requests.post(
                f"{self._copilot_endpoint}/v1/messages",
                headers=headers,
                json=payload,
                timeout=120,
                stream=True,
            )
            resp.raise_for_status()

            full_text = ""
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    try:
                        data = json.loads(line_str[6:])
                        if data.get("type") == "content_block_delta":
                            full_text += data.get("delta", {}).get("text", "")
                    except json.JSONDecodeError:
                        pass
            return full_text

        except Exception as exc:
            logging.error("Copilot Anthropic transcription error: %s", exc)
            retry = _parse_retry_after(exc)
            if retry is not None:
                raise AIRateLimitError(str(exc), retry_after=retry) from exc
            raise AIProviderError(f"GitHub Copilot transcription failed: {exc}") from exc

    def _transcribe_openai_responses(self, image_paths: List[Path], prompt: str) -> str:
        """Transcribe using OpenAI /v1/responses endpoint (for GPT-5.x)."""
        content: list = [{"type": "input_text", "text": prompt}]
        for img_path in image_paths:
            if not img_path.exists():
                continue
            with open(img_path, "rb") as fh:
                img_b64 = base64.standard_b64encode(fh.read()).decode("utf-8")
            mime = "image/jpeg" if img_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            content.append({"type": "input_image", "image_url": f"data:{mime};base64,{img_b64}"})

        if len(content) == 1:  # Only prompt, no images
            return ""

        headers = {
            "Authorization": f"Bearer {self._copilot_token}",
            "Content-Type": "application/json",
            "Copilot-Integration-Id": "vscode-chat",
            "Copilot-Vision-Request": "true",
        }
        payload = {
            "model": self.model,
            "max_output_tokens": 4096,
            "input": [{"type": "message", "role": "user", "content": content}],
            "stream": True,
        }

        try:
            resp = requests.post(
                f"{self._copilot_endpoint}/v1/responses",
                headers=headers,
                json=payload,
                timeout=120,
                stream=True,
            )
            resp.raise_for_status()

            full_text = ""
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    try:
                        data = json.loads(line_str[6:])
                        # OpenAI Responses uses "output_text" delta
                        if data.get("type") == "response.output_text.delta":
                            full_text += data.get("delta", "")
                    except json.JSONDecodeError:
                        pass
            return full_text

        except Exception as exc:
            logging.error("Copilot OpenAI Responses transcription error: %s", exc)
            retry = _parse_retry_after(exc)
            if retry is not None:
                raise AIRateLimitError(str(exc), retry_after=retry) from exc
            raise AIProviderError(f"GitHub Copilot transcription failed: {exc}") from exc

    def cleanup_text(self, raw_text: str, context: str = "") -> str:
        """Ask the model to clean up and structure raw transcribed text."""
        if not self._ensure_copilot_token() or not self._client:
            return raw_text

        if not raw_text.strip():
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
        except Exception as exc:
            logging.error("Copilot cleanup error: %s", exc)
            retry = _parse_retry_after(exc)
            if retry is not None:
                raise AIRateLimitError(str(exc), retry_after=retry) from exc
            raise AIProviderError(f"GitHub Copilot cleanup failed: {exc}") from exc


def _parse_retry_after(exc: Exception) -> Optional[int]:
    """Extract retry-after seconds from a rate-limit exception."""
    try:
        from openai import RateLimitError

        if not isinstance(exc, RateLimitError):
            return None
    except ImportError:
        exc_str = str(exc)
        if "429" not in exc_str and "RateLimit" not in exc_str:
            return None

    exc_str = str(exc)
    match = re.search(r"[Pp]lease wait (\d+) seconds", exc_str)
    if match:
        return int(match.group(1))
    return 60


def get_available_models(github_token: str, vision_only: bool = False) -> List[Tuple[str, str]]:
    """Fetch available models from Copilot API.

    Args:
        github_token: GitHub OAuth token (from Copilot device flow)
        vision_only: If True, only return models that support vision

    Returns:
        List of (model_id, display_name) tuples, or empty list on failure.
    """
    if not github_token:
        return []

    # First exchange for Copilot token
    headers = {
        **COPILOT_HEADERS,
        "Authorization": f"Bearer {github_token}",
    }
    try:
        resp = requests.get(COPILOT_TOKEN_URL, headers=headers, timeout=30)
        if resp.status_code != 200:
            logging.debug("Token exchange failed: %s", resp.status_code)
            return []

        data = resp.json()
        copilot_token = data.get("token")
        if not copilot_token:
            return []

        # Parse endpoint from token (convert proxy. to api.)
        match = re.search(r"proxy-ep=([^;]+)", copilot_token)
        if match:
            endpoint = match.group(1)
            if not endpoint.startswith("http"):
                endpoint = f"https://{endpoint}"
            endpoint = re.sub(r"^(https?://)proxy\.", r"\1api.", endpoint)
        else:
            endpoint = DEFAULT_COPILOT_ENDPOINT

        # Fetch models
        models_resp = requests.get(
            f"{endpoint}/models",
            headers={
                "Authorization": f"Bearer {copilot_token}",
                "Copilot-Integration-Id": "vscode-chat",
            },
            timeout=10,
        )
        if models_resp.status_code != 200:
            return []

        models_data = models_resp.json()
        models = []
        for m in models_data.get("data", models_data.get("models", [])):
            model_id = m.get("id") or m.get("name")
            if not model_id:
                continue

            caps = m.get("capabilities", {})
            supports = caps.get("supports", {})
            has_vision = supports.get("vision", False)

            # Skip non-vision models if vision_only requested
            if vision_only and not has_vision:
                continue

            # For vision models, check if we can actually use them
            if has_vision:
                can_use = _is_claude_model(model_id) or _is_responses_api_model(model_id)
                if vision_only and not can_use:
                    continue  # Skip models we can't use for vision

            display = model_id
            if has_vision:
                display += " (vision)"
            models.append((model_id, display))

        return models

    except Exception as exc:
        logging.debug("Failed to fetch Copilot models: %s", exc)
        return []


def check_copilot_auth(github_token: str) -> Tuple[bool, str]:
    """Check if a GitHub token can authenticate with Copilot API.

    Returns:
        Tuple of (success, message)
    """
    if not github_token:
        return False, "No GitHub token provided"

    headers = {
        **COPILOT_HEADERS,
        "Authorization": f"Bearer {github_token}",
    }
    try:
        resp = requests.get(COPILOT_TOKEN_URL, headers=headers, timeout=30)
        if resp.status_code == 404:
            return False, "Copilot API not available. Check your Copilot subscription."
        if resp.status_code == 401:
            return False, "Token invalid or expired."
        if resp.status_code == 403:
            return False, "Token not authorized for Copilot. Need token from Copilot device flow."
        if resp.status_code == 200:
            return True, "Authenticated successfully"
        return False, f"Unexpected status: {resp.status_code}"
    except requests.RequestException as exc:
        return False, f"Request failed: {exc}"
