"""Thin wrapper around the system keyring for storing API tokens.

All secrets (SSH password, GitHub token, Claude API key) are stored under
the same service name with different usernames.
"""

import logging

try:
    import keyring  # type: ignore

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

SERVICE = "remarkablesync"

# Keyring usernames for each secret
KEY_GITHUB_TOKEN = "github_token"
KEY_CLAUDE_API_KEY = "claude_api_key"
KEY_GOOGLE_API_KEY = "google_api_key"


def get_secret(key: str) -> str:
    """Retrieve a secret from the system keyring.

    Returns:
        The stored value, or empty string if not found or keyring unavailable.
    """
    if not KEYRING_AVAILABLE:
        return ""
    try:
        value = keyring.get_password(SERVICE, key)
        return value or ""
    except Exception as e:
        logging.debug("keyring get failed for %s: %s", key, e)
        return ""


def set_secret(key: str, value: str) -> bool:
    """Store a secret in the system keyring.

    Returns:
        True on success, False otherwise.
    """
    if not KEYRING_AVAILABLE:
        return False
    try:
        keyring.set_password(SERVICE, key, value)
        return True
    except Exception as e:
        logging.warning("keyring set failed for %s: %s", key, e)
        return False


def delete_secret(key: str) -> bool:
    """Remove a secret from the system keyring.

    Returns:
        True on success, False otherwise.
    """
    if not KEYRING_AVAILABLE:
        return False
    try:
        keyring.delete_password(SERVICE, key)
        return True
    except Exception as e:
        logging.debug("keyring delete failed for %s: %s", key, e)
        return False
