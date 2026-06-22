"""Tests for the keyring_store module."""

from unittest.mock import patch

from src import keyring_store


class TestKeyringUnavailable:
    """Behaviour when the keyring package is not installed."""

    def test_get_secret_returns_empty(self):
        with patch.object(keyring_store, "KEYRING_AVAILABLE", False):
            assert keyring_store.get_secret("github_token") == ""

    def test_set_secret_returns_false(self):
        with patch.object(keyring_store, "KEYRING_AVAILABLE", False):
            assert keyring_store.set_secret("github_token", "val") is False

    def test_delete_secret_returns_false(self):
        with patch.object(keyring_store, "KEYRING_AVAILABLE", False):
            assert keyring_store.delete_secret("github_token") is False


class TestKeyringAvailable:
    """Behaviour when keyring is available (mocked)."""

    def test_get_secret_success(self):
        with patch.object(keyring_store, "KEYRING_AVAILABLE", True):
            with patch.object(keyring_store, "keyring") as mock_kr:
                mock_kr.get_password.return_value = "my-token"
                result = keyring_store.get_secret("github_token")
        assert result == "my-token"
        mock_kr.get_password.assert_called_once_with("remarkablesync", "github_token")

    def test_get_secret_returns_empty_on_none(self):
        with patch.object(keyring_store, "KEYRING_AVAILABLE", True):
            with patch.object(keyring_store, "keyring") as mock_kr:
                mock_kr.get_password.return_value = None
                result = keyring_store.get_secret("github_token")
        assert result == ""

    def test_get_secret_handles_exception(self):
        with patch.object(keyring_store, "KEYRING_AVAILABLE", True):
            with patch.object(keyring_store, "keyring") as mock_kr:
                mock_kr.get_password.side_effect = RuntimeError("locked")
                result = keyring_store.get_secret("github_token")
        assert result == ""

    def test_set_secret_success(self):
        with patch.object(keyring_store, "KEYRING_AVAILABLE", True):
            with patch.object(keyring_store, "keyring") as mock_kr:
                result = keyring_store.set_secret("github_token", "tok123")
        assert result is True
        mock_kr.set_password.assert_called_once_with("remarkablesync", "github_token", "tok123")

    def test_set_secret_handles_exception(self):
        with patch.object(keyring_store, "KEYRING_AVAILABLE", True):
            with patch.object(keyring_store, "keyring") as mock_kr:
                mock_kr.set_password.side_effect = RuntimeError("fail")
                result = keyring_store.set_secret("github_token", "tok")
        assert result is False

    def test_delete_secret_success(self):
        with patch.object(keyring_store, "KEYRING_AVAILABLE", True):
            with patch.object(keyring_store, "keyring") as mock_kr:
                result = keyring_store.delete_secret("github_token")
        assert result is True
        mock_kr.delete_password.assert_called_once_with("remarkablesync", "github_token")

    def test_delete_secret_handles_exception(self):
        with patch.object(keyring_store, "KEYRING_AVAILABLE", True):
            with patch.object(keyring_store, "keyring") as mock_kr:
                mock_kr.delete_password.side_effect = RuntimeError("not found")
                result = keyring_store.delete_secret("github_token")
        assert result is False


class TestConstants:
    """Verify module-level constants."""

    def test_service_name(self):
        assert keyring_store.SERVICE == "remarkablesync"

    def test_key_constants(self):
        assert keyring_store.KEY_GITHUB_TOKEN == "github_token"
        assert keyring_store.KEY_CLAUDE_API_KEY == "claude_api_key"
