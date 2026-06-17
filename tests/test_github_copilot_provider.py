"""Tests for github_copilot_provider module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.ai.github_copilot_provider import (
    DEFAULT_COPILOT_ENDPOINT,
    GitHubCopilotProvider,
    _is_claude_model,
    _is_responses_api_model,
    check_copilot_auth,
    get_available_models,
)


class TestModelDetection:
    """Tests for model type detection functions."""

    def test_is_claude_model_true_for_claude(self):
        """Claude models are detected correctly."""
        assert _is_claude_model("claude-sonnet-4.5") is True
        assert _is_claude_model("claude-opus-4.5") is True
        assert _is_claude_model("Claude-Haiku-4.5") is True

    def test_is_claude_model_false_for_gpt(self):
        """GPT models are not Claude."""
        assert _is_claude_model("gpt-5-mini") is False
        assert _is_claude_model("gpt-4o") is False

    def test_is_responses_api_model_true_for_gpt5(self):
        """GPT-5.x models support responses API."""
        assert _is_responses_api_model("gpt-5-mini") is True
        assert _is_responses_api_model("gpt-5.4") is True
        assert _is_responses_api_model("GPT-5.5") is True

    def test_is_responses_api_model_true_for_o1_o3(self):
        """o1 and o3 models support responses API."""
        assert _is_responses_api_model("o1-preview") is True
        assert _is_responses_api_model("o3-mini") is True

    def test_is_responses_api_model_false_for_gpt4(self):
        """GPT-4.x models don't support responses API."""
        assert _is_responses_api_model("gpt-4o") is False
        assert _is_responses_api_model("gpt-4-turbo") is False

    def test_is_responses_api_model_false_for_claude(self):
        """Claude models don't support responses API."""
        assert _is_responses_api_model("claude-sonnet-4.5") is False


class TestGitHubCopilotProviderInit:
    """Tests for GitHubCopilotProvider initialization."""

    def test_init_with_api_key(self):
        """Provider initializes with provided API key."""
        provider = GitHubCopilotProvider(api_key="test-token", model="gpt-5-mini")
        assert provider._github_token == "test-token"
        assert provider.model == "gpt-5-mini"

    def test_init_defaults_to_claude_sonnet(self):
        """Provider defaults to claude-sonnet-4.5 model."""
        provider = GitHubCopilotProvider(api_key="test-token")
        assert provider.model == "claude-sonnet-4.5"

    @patch.dict("os.environ", {"GITHUB_TOKEN": "env-token"})
    def test_init_falls_back_to_env_var(self):
        """Provider falls back to GITHUB_TOKEN env var."""
        provider = GitHubCopilotProvider()
        assert provider._github_token == "env-token"

    def test_init_empty_without_token(self):
        """Provider initializes empty without token."""
        with patch.dict("os.environ", {}, clear=True):
            provider = GitHubCopilotProvider()
            assert provider._github_token == ""


class TestParseToken:
    """Tests for token parsing methods."""

    def test_parse_token_expiry_extracts_timestamp(self):
        """Expiry timestamp is extracted from token."""
        provider = GitHubCopilotProvider(api_key="test")
        token = "tid=abc;exp=1700000000;other=stuff"
        assert provider._parse_token_expiry(token) == 1700000000.0

    def test_parse_token_expiry_defaults_to_30_min(self):
        """Missing expiry defaults to 30 minutes from now."""
        provider = GitHubCopilotProvider(api_key="test")
        token = "tid=abc;no-expiry=here"
        result = provider._parse_token_expiry(token)
        # Should be roughly 30 min (1800 sec) from now
        import time

        assert result > time.time()
        assert result < time.time() + 1900

    def test_parse_token_endpoint_extracts_and_converts(self):
        """Endpoint is extracted and proxy. converted to api."""
        provider = GitHubCopilotProvider(api_key="test")
        token = "tid=abc;proxy-ep=proxy.individual.githubcopilot.com;exp=123"
        result = provider._parse_token_endpoint(token)
        assert result == "https://api.individual.githubcopilot.com"

    def test_parse_token_endpoint_handles_https_prefix(self):
        """Endpoint with https:// prefix is handled."""
        provider = GitHubCopilotProvider(api_key="test")
        token = "tid=abc;proxy-ep=https://proxy.test.com;exp=123"
        result = provider._parse_token_endpoint(token)
        assert result == "https://api.test.com"

    def test_parse_token_endpoint_defaults_on_missing(self):
        """Missing endpoint defaults to standard Copilot endpoint."""
        provider = GitHubCopilotProvider(api_key="test")
        token = "tid=abc;exp=123"
        result = provider._parse_token_endpoint(token)
        assert result == DEFAULT_COPILOT_ENDPOINT


class TestEnsureCopilotToken:
    """Tests for _ensure_copilot_token method."""

    def test_returns_false_without_github_token(self):
        """Returns False when no GitHub token available."""
        provider = GitHubCopilotProvider(api_key="")
        assert provider._ensure_copilot_token() is False

    def test_returns_true_with_cached_valid_token(self):
        """Returns True when valid cached token exists."""
        import time

        provider = GitHubCopilotProvider(api_key="test")
        provider._copilot_token = "cached-token"
        provider._token_expires_at = time.time() + 3600  # 1 hour from now
        assert provider._ensure_copilot_token() is True

    @patch("src.ai.github_copilot_provider.requests.get")
    def test_exchanges_token_successfully(self, mock_get):
        """Token exchange succeeds and extracts endpoint."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "token": "tid=x;exp=9999999999;proxy-ep=proxy.test.githubcopilot.com"
        }
        mock_get.return_value = mock_resp

        provider = GitHubCopilotProvider(api_key="github-token")

        with patch.object(provider, "_init_client"):
            result = provider._ensure_copilot_token()

        assert result is True
        assert provider._copilot_token is not None
        assert "api.test.githubcopilot.com" in provider._copilot_endpoint

    @patch("src.ai.github_copilot_provider.requests.get")
    def test_handles_404_copilot_unavailable(self, mock_get):
        """Returns False on 404 (Copilot not available)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        provider = GitHubCopilotProvider(api_key="github-token")
        assert provider._ensure_copilot_token() is False

    @patch("src.ai.github_copilot_provider.requests.get")
    def test_handles_401_unauthorized(self, mock_get):
        """Returns False on 401/403 (unauthorized)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp

        provider = GitHubCopilotProvider(api_key="github-token")
        assert provider._ensure_copilot_token() is False


class TestIsAvailable:
    """Tests for is_available method."""

    def test_returns_false_without_token(self):
        """Returns False when no GitHub token."""
        provider = GitHubCopilotProvider(api_key="")
        assert provider.is_available() is False

    @patch.object(GitHubCopilotProvider, "_ensure_copilot_token")
    def test_returns_true_when_token_exchange_succeeds(self, mock_ensure):
        """Returns True when token exchange succeeds."""
        mock_ensure.return_value = True
        provider = GitHubCopilotProvider(api_key="test-token")
        assert provider.is_available() is True


class TestGetAvailableModels:
    """Tests for get_available_models function."""

    def test_returns_empty_without_token(self):
        """Returns empty list without token."""
        assert get_available_models("") == []

    @patch("src.ai.github_copilot_provider.requests.get")
    def test_fetches_and_parses_models(self, mock_get):
        """Fetches models from API and parses response."""
        # First call: token exchange
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"token": "tid=x;exp=9999999999;proxy-ep=proxy.test.com"}

        # Second call: models list
        models_resp = MagicMock()
        models_resp.status_code = 200
        models_resp.json.return_value = {
            "data": [
                {
                    "id": "gpt-5-mini",
                    "capabilities": {"supports": {"vision": True}},
                },
                {
                    "id": "claude-sonnet-4.5",
                    "capabilities": {"supports": {"vision": True}},
                },
                {
                    "id": "gpt-4-turbo",
                    "capabilities": {"supports": {"vision": False}},
                },
            ]
        }

        mock_get.side_effect = [token_resp, models_resp]

        models = get_available_models("test-token")
        assert len(models) >= 2
        model_ids = [m[0] for m in models]
        assert "gpt-5-mini" in model_ids
        assert "claude-sonnet-4.5" in model_ids

    @patch("src.ai.github_copilot_provider.requests.get")
    def test_filters_vision_only_models(self, mock_get):
        """Filters to only vision-capable models when requested."""
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"token": "tid=x;exp=9999999999;proxy-ep=proxy.test.com"}

        models_resp = MagicMock()
        models_resp.status_code = 200
        models_resp.json.return_value = {
            "data": [
                {"id": "claude-sonnet-4.5", "capabilities": {"supports": {"vision": True}}},
                {"id": "text-only-model", "capabilities": {"supports": {"vision": False}}},
            ]
        }

        mock_get.side_effect = [token_resp, models_resp]

        models = get_available_models("test-token", vision_only=True)
        model_ids = [m[0] for m in models]
        assert "claude-sonnet-4.5" in model_ids
        assert "text-only-model" not in model_ids

    @patch("src.ai.github_copilot_provider.requests.get")
    def test_handles_token_exchange_failure(self, mock_get):
        """Returns empty list on token exchange failure."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp

        assert get_available_models("bad-token") == []


class TestCheckCopilotAuth:
    """Tests for check_copilot_auth function."""

    @patch("src.ai.github_copilot_provider.requests.get")
    def test_returns_true_on_success(self, mock_get):
        """Returns (True, message) on successful auth."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"token": "valid-token"}
        mock_get.return_value = mock_resp

        success, message = check_copilot_auth("test-token")
        assert success is True
        assert "success" in message.lower() or message == ""

    @patch("src.ai.github_copilot_provider.requests.get")
    def test_returns_false_on_401(self, mock_get):
        """Returns (False, message) on 401."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp

        success, message = check_copilot_auth("bad-token")
        assert success is False

    @patch("src.ai.github_copilot_provider.requests.get")
    def test_returns_false_on_404(self, mock_get):
        """Returns (False, message) on 404 (no Copilot access)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        success, message = check_copilot_auth("test-token")
        assert success is False


class TestTranscribeHandwriting:
    """Tests for transcribe_handwriting method."""

    @patch.object(GitHubCopilotProvider, "_ensure_copilot_token")
    def test_returns_empty_when_token_fails(self, mock_ensure):
        """Returns empty string when token exchange fails."""
        mock_ensure.return_value = False
        provider = GitHubCopilotProvider(api_key="test")

        result = provider.transcribe_handwriting([Path("/fake/image.png")])
        assert result == ""

    @patch.object(GitHubCopilotProvider, "_ensure_copilot_token")
    @patch.object(GitHubCopilotProvider, "_transcribe_anthropic")
    def test_routes_claude_to_anthropic_endpoint(self, mock_anthropic, mock_ensure):
        """Claude models use Anthropic endpoint."""
        mock_ensure.return_value = True
        mock_anthropic.return_value = "transcribed text"

        provider = GitHubCopilotProvider(api_key="test", model="claude-sonnet-4.5")
        result = provider.transcribe_handwriting([Path("/fake/image.png")])

        mock_anthropic.assert_called_once()
        assert result == "transcribed text"

    @patch.object(GitHubCopilotProvider, "_ensure_copilot_token")
    @patch.object(GitHubCopilotProvider, "_transcribe_openai_responses")
    def test_routes_gpt5_to_responses_endpoint(self, mock_responses, mock_ensure):
        """GPT-5.x models use Responses API endpoint."""
        mock_ensure.return_value = True
        mock_responses.return_value = "transcribed text"

        provider = GitHubCopilotProvider(api_key="test", model="gpt-5-mini")
        result = provider.transcribe_handwriting([Path("/fake/image.png")])

        mock_responses.assert_called_once()
        assert result == "transcribed text"
