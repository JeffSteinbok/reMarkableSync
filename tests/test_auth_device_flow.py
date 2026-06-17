"""Tests for the GitHub device flow authentication module."""

from unittest.mock import MagicMock, patch

import pytest

from src.auth.github_device_flow import (
    CLIENT_ID,
    DEVICE_CODE_URL,
    TOKEN_URL,
    device_flow_authenticate,
    poll_for_token,
    request_device_code,
)


class TestRequestDeviceCode:
    """Tests for requesting a device code from GitHub."""

    def test_posts_to_correct_url(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "device_code": "dc-123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "src.auth.github_device_flow.requests.post", return_value=mock_resp
        ) as mock_post:
            result = request_device_code()

        mock_post.assert_called_once_with(
            DEVICE_CODE_URL,
            data={"client_id": CLIENT_ID, "scope": "read:user"},
            headers={"Accept": "application/json"},
        )
        assert result["device_code"] == "dc-123"
        assert result["user_code"] == "ABCD-1234"

    def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("403 Forbidden")

        with patch("src.auth.github_device_flow.requests.post", return_value=mock_resp):
            with pytest.raises(Exception, match="403"):
                request_device_code()


class TestPollForToken:
    """Tests for polling GitHub for the access token."""

    def test_returns_token_on_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "ghu_abc123"}

        with patch("src.auth.github_device_flow.requests.post", return_value=mock_resp):
            with patch("src.auth.github_device_flow.time.sleep"):
                token, err = poll_for_token("dc-123", interval=0, expires_in=10)

        assert token == "ghu_abc123"
        assert err is None

    def test_handles_authorization_pending(self):
        """Keeps polling when authorization is pending, then succeeds."""
        pending_resp = MagicMock()
        pending_resp.json.return_value = {"error": "authorization_pending"}

        success_resp = MagicMock()
        success_resp.json.return_value = {"access_token": "ghu_final"}

        with patch(
            "src.auth.github_device_flow.requests.post",
            side_effect=[pending_resp, success_resp],
        ):
            with patch("src.auth.github_device_flow.time.sleep"):
                token, err = poll_for_token("dc-123", interval=0, expires_in=60)

        assert token == "ghu_final"
        assert err is None

    def test_handles_expired_token(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "expired_token"}

        with patch("src.auth.github_device_flow.requests.post", return_value=mock_resp):
            with patch("src.auth.github_device_flow.time.sleep"):
                token, err = poll_for_token("dc-123", interval=0, expires_in=60)

        assert token is None
        assert "expired" in err.lower()

    def test_handles_access_denied(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "access_denied"}

        with patch("src.auth.github_device_flow.requests.post", return_value=mock_resp):
            with patch("src.auth.github_device_flow.time.sleep"):
                token, err = poll_for_token("dc-123", interval=0, expires_in=60)

        assert token is None
        assert "denied" in err.lower()

    def test_handles_slow_down(self):
        """slow_down error increases the interval."""
        slow_resp = MagicMock()
        slow_resp.json.return_value = {"error": "slow_down"}

        success_resp = MagicMock()
        success_resp.json.return_value = {"access_token": "ghu_slow"}

        with patch(
            "src.auth.github_device_flow.requests.post",
            side_effect=[slow_resp, success_resp],
        ):
            with patch("src.auth.github_device_flow.time.sleep"):
                token, err = poll_for_token("dc-123", interval=0, expires_in=60)

        assert token == "ghu_slow"

    def test_handles_unknown_error(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "error": "something_weird",
            "error_description": "unexpected",
        }

        with patch("src.auth.github_device_flow.requests.post", return_value=mock_resp):
            with patch("src.auth.github_device_flow.time.sleep"):
                token, err = poll_for_token("dc-123", interval=0, expires_in=60)

        assert token is None
        assert "something_weird" in err

    def test_timeout(self):
        """Times out if token never arrives."""
        pending_resp = MagicMock()
        pending_resp.json.return_value = {"error": "authorization_pending"}

        with patch("src.auth.github_device_flow.requests.post", return_value=pending_resp):
            with patch("src.auth.github_device_flow.time.sleep"):
                # Use a very short expires_in and patch time to simulate timeout
                with patch("src.auth.github_device_flow.time.time", side_effect=[0, 0, 1000]):
                    token, err = poll_for_token("dc-123", interval=0, expires_in=5)

        assert token is None
        assert "timed out" in err.lower()


class TestDeviceFlowAuthenticate:
    """Tests for the full device flow."""

    def test_calls_callback_with_code(self):
        device_data = {
            "device_code": "dc-full",
            "user_code": "WXYZ-9999",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
            "expires_in": 900,
        }
        callback = MagicMock()

        with patch("src.auth.github_device_flow.request_device_code", return_value=device_data):
            with patch(
                "src.auth.github_device_flow.poll_for_token",
                return_value=("ghu_full", None),
            ):
                token, err = device_flow_authenticate(on_code_received=callback)

        callback.assert_called_once_with("https://github.com/login/device", "WXYZ-9999")
        assert token == "ghu_full"
        assert err is None

    def test_works_without_callback(self):
        device_data = {
            "device_code": "dc-no-cb",
            "user_code": "AAAA-0000",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
            "expires_in": 900,
        }

        with patch("src.auth.github_device_flow.request_device_code", return_value=device_data):
            with patch(
                "src.auth.github_device_flow.poll_for_token",
                return_value=("ghu_no_cb", None),
            ):
                token, err = device_flow_authenticate()

        assert token == "ghu_no_cb"


class TestConstants:
    """Verify OAuth constants are set."""

    def test_client_id_set(self):
        assert CLIENT_ID and len(CLIENT_ID) > 5

    def test_urls_are_github(self):
        assert "github.com" in DEVICE_CODE_URL
        assert "github.com" in TOKEN_URL
