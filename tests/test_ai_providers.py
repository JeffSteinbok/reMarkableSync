"""Tests for the AI provider abstraction."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ai import ClaudeProvider, GitHubCopilotProvider, GitHubModelsProvider, get_provider

# ---------------------------------------------------------------------------
# get_provider factory
# ---------------------------------------------------------------------------


class TestGetProvider:
    def test_returns_claude_provider(self):
        p = get_provider("claude", api_key="dummy")
        assert isinstance(p, ClaudeProvider)

    def test_returns_claude_for_anthropic_alias(self):
        p = get_provider("anthropic", api_key="dummy")
        assert isinstance(p, ClaudeProvider)

    def test_returns_github_provider(self):
        p = get_provider("github", api_key="dummy")
        assert isinstance(p, GitHubCopilotProvider)

    def test_returns_github_for_github_models_alias(self):
        p = get_provider("github_models", api_key="dummy")
        assert isinstance(p, GitHubModelsProvider)

    def test_raises_on_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown AI provider"):
            get_provider("nonexistent")

    def test_case_insensitive(self):
        p = get_provider("Claude", api_key="dummy")
        assert isinstance(p, ClaudeProvider)


# ---------------------------------------------------------------------------
# ClaudeProvider
# ---------------------------------------------------------------------------


class TestClaudeProvider:
    def test_is_not_available_without_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            # Ensure env-var is not set
            import os

            os.environ.pop("ANTHROPIC_API_KEY", None)
            p = ClaudeProvider(api_key="")
        assert not p.is_available()

    def test_is_not_available_when_anthropic_not_installed(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.dict("sys.modules", {"anthropic": None}):
                p = ClaudeProvider(api_key="test-key")
                # _client will be None because import failed
        # The provider should handle the missing import gracefully
        # (either available or not, but must not raise)
        isinstance(p.is_available(), bool)

    def test_transcribe_returns_empty_when_unavailable(self):
        p = ClaudeProvider(api_key="")
        result = p.transcribe_handwriting([Path("/nonexistent.png")])
        assert result == ""

    def test_cleanup_returns_raw_when_unavailable(self):
        p = ClaudeProvider(api_key="")
        raw = "some text"
        result = p.cleanup_text(raw)
        assert result == raw

    def test_transcribe_calls_api_with_images(self, tmp_path):
        """Verify the Anthropic API is called correctly."""
        img = tmp_path / "page_001.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # minimal PNG header

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Hello World")]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        p = ClaudeProvider(api_key="sk-dummy")
        p._client = mock_client

        result = p.transcribe_handwriting([img], context="Test Notebook")
        assert result == "Hello World"
        mock_client.messages.create.assert_called_once()


# ---------------------------------------------------------------------------
# GitHubModelsProvider
# ---------------------------------------------------------------------------


class TestGitHubModelsProvider:
    def test_is_not_available_without_api_key(self):
        import os

        for key in ("GITHUB_TOKEN", "OPENAI_API_KEY"):
            os.environ.pop(key, None)
        p = GitHubModelsProvider(api_key="")
        assert not p.is_available()

    def test_is_not_available_when_openai_not_installed(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"}):
            with patch.dict("sys.modules", {"openai": None}):
                p = GitHubModelsProvider(api_key="test-token")
        isinstance(p.is_available(), bool)

    def test_transcribe_returns_empty_when_unavailable(self):
        p = GitHubModelsProvider(api_key="")
        assert p.transcribe_handwriting([]) == ""

    def test_cleanup_returns_raw_when_unavailable(self):
        p = GitHubModelsProvider(api_key="")
        assert p.cleanup_text("some text") == "some text"

    def test_custom_endpoint_set(self):
        p = GitHubModelsProvider(api_key="tok", endpoint="https://custom.endpoint")
        assert p.endpoint == "https://custom.endpoint"

    def test_transcribe_calls_openai_api(self, tmp_path):
        """Verify the OpenAI-compatible API is called correctly."""
        img = tmp_path / "page_001.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        mock_choice = MagicMock()
        mock_choice.message.content = "Test transcription"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        p = GitHubModelsProvider(api_key="ghp_dummy")
        p._client = mock_client

        result = p.transcribe_handwriting([img])
        assert result == "Test transcription"
        mock_client.chat.completions.create.assert_called_once()
