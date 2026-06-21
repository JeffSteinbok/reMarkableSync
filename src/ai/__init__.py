"""AI provider package for RemarkableSync.

Exposes :func:`get_provider` as a simple factory and re-exports the three
public classes so callers can import them directly from ``src.ai``.
"""

from typing import Any

from .base_provider import AIProviderError, AIRateLimitError, BaseAIProvider
from .claude_provider import ClaudeProvider
from .github_copilot_provider import GitHubCopilotProvider
from .github_models_provider import GitHubModelsProvider
from .trocr_provider import TrOCRProvider

_REGISTRY: dict[str, type] = {
    "claude": ClaudeProvider,
    "anthropic": ClaudeProvider,
    "github": GitHubCopilotProvider,  # Use SDK-based provider
    "github_copilot": GitHubCopilotProvider,
    "github_models": GitHubModelsProvider,  # Legacy OpenAI-compatible
    "openai": GitHubModelsProvider,
    "trocr": TrOCRProvider,  # Local offline OCR, no API key required
    "local": TrOCRProvider,
}


def get_provider(provider_name: str, **kwargs: Any) -> BaseAIProvider:
    """Instantiate an AI provider by name.

    Args:
        provider_name: One of ``"claude"``, ``"anthropic"``, ``"github"``,
            ``"github_copilot"``, ``"github_models"``, or ``"openai"``.
        **kwargs: Keyword arguments forwarded to the provider constructor
            (e.g. ``api_key``, ``model``).

    Returns:
        Configured :class:`BaseAIProvider` instance.

    Raises:
        ValueError: When *provider_name* is not recognised.
    """
    cls = _REGISTRY.get(provider_name.lower())
    if cls is None:
        known = sorted({k for k in _REGISTRY if not k.startswith("_")})
        raise ValueError(f"Unknown AI provider '{provider_name}'. Choose from: {known}")
    return cls(**kwargs)


__all__ = [
    "AIProviderError",
    "AIRateLimitError",
    "BaseAIProvider",
    "ClaudeProvider",
    "GitHubCopilotProvider",
    "GitHubModelsProvider",
    "TrOCRProvider",
    "get_provider",
]
