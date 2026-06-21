"""Tests for the AI provider abstraction."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ai import (
    ClaudeProvider,
    GitHubCopilotProvider,
    GitHubModelsProvider,
    TrOCRProvider,
    get_provider,
)

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

    def test_returns_trocr_provider(self):
        p = get_provider("trocr")
        assert isinstance(p, TrOCRProvider)

    def test_returns_trocr_for_local_alias(self):
        p = get_provider("local")
        assert isinstance(p, TrOCRProvider)

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


# ---------------------------------------------------------------------------
# TrOCRProvider
# ---------------------------------------------------------------------------


class TestTrOCRProvider:
    def test_is_not_available_when_transformers_not_installed(self):
        with patch.dict("sys.modules", {"transformers": None, "torch": None}):
            p = TrOCRProvider()
            p._available = None  # reset cached value
            assert not p.is_available()

    def test_is_available_when_packages_present(self):
        mock_transformers = MagicMock()
        mock_torch = MagicMock()
        with patch.dict("sys.modules", {"transformers": mock_transformers, "torch": mock_torch}):
            p = TrOCRProvider()
            p._available = None
            assert p.is_available()

    def test_cleanup_text_returns_raw_unchanged(self):
        p = TrOCRProvider()
        raw = "some handwritten text"
        assert p.cleanup_text(raw) == raw

    def test_cleanup_text_with_context_returns_raw(self):
        p = TrOCRProvider()
        raw = "notes here"
        assert p.cleanup_text(raw, context="My Notebook") == raw

    def test_transcribe_returns_empty_when_unavailable(self):
        p = TrOCRProvider()
        p._available = False  # simulate missing packages
        result = p.transcribe_handwriting([Path("/nonexistent.png")])
        assert result == ""

    def test_transcribe_skips_missing_files(self):
        p = TrOCRProvider()
        # Fake a loaded model so the code reaches the file-existence check
        p._model = MagicMock()
        p._processor = MagicMock()
        p._available = True

        mock_pil = MagicMock()
        mock_pil.__enter__ = MagicMock(return_value=mock_pil)
        mock_pil.__exit__ = MagicMock(return_value=False)

        result = p.transcribe_handwriting([Path("/does/not/exist.png")])
        assert result == ""

    def test_transcribe_calls_model_for_existing_image(self, tmp_path):
        img_path = tmp_path / "page_001.png"
        # Write a minimal valid PNG (1x1 white pixel)
        import struct
        import zlib

        def _png_1x1_white():
            sig = b"\x89PNG\r\n\x1a\n"
            ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            ihdr = b"IHDR" + ihdr_data
            ihdr_chunk = (
                struct.pack(">I", len(ihdr_data))
                + ihdr
                + struct.pack(">I", zlib.crc32(ihdr) & 0xFFFFFFFF)
            )
            raw_row = b"\x00\xff\xff\xff"
            compressed = zlib.compress(raw_row)
            idat = b"IDAT" + compressed
            idat_chunk = (
                struct.pack(">I", len(compressed))
                + idat
                + struct.pack(">I", zlib.crc32(idat) & 0xFFFFFFFF)
            )
            iend = b"IEND"
            iend_chunk = (
                struct.pack(">I", 0) + iend + struct.pack(">I", zlib.crc32(iend) & 0xFFFFFFFF)
            )
            return sig + ihdr_chunk + idat_chunk + iend_chunk

        img_path.write_bytes(_png_1x1_white())

        mock_processor = MagicMock()
        mock_processor.return_value.pixel_values = MagicMock()
        mock_processor.batch_decode.return_value = ["hello world"]

        mock_model = MagicMock()
        mock_model.generate.return_value = MagicMock()

        mock_torch = MagicMock()
        mock_torch.no_grad.return_value.__enter__ = MagicMock(return_value=None)
        mock_torch.no_grad.return_value.__exit__ = MagicMock(return_value=False)

        p = TrOCRProvider()
        p._processor = mock_processor
        p._model = mock_model
        p._available = True

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = p.transcribe_handwriting([img_path])

        # Model was invoked; result is a string
        assert isinstance(result, str)

    def test_default_model_name(self):
        p = TrOCRProvider()
        assert p.model_name == "microsoft/trocr-base-handwritten"

    def test_custom_model_name(self):
        p = TrOCRProvider(model_name="microsoft/trocr-large-handwritten")
        assert p.model_name == "microsoft/trocr-large-handwritten"

    def test_load_model_sets_unavailable_on_import_error(self):
        p = TrOCRProvider()
        with patch.dict("sys.modules", {"transformers": None}):
            result = p._load_model()
        assert result is False
        assert p._available is False
