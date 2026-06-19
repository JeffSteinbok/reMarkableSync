"""
Credential storage implementations.

Provides abstractions for credential storage backends, enabling
dependency injection for testing without system keyring access.
"""

import logging
from typing import Optional

from .protocols import CredentialStoreProtocol


class KeyringCredentialStore:
    """Credential store backed by the system keyring.

    Wraps the keyring library and implements CredentialStoreProtocol
    for use in production environments.
    """

    def __init__(self):
        """Initialize keyring credential store."""
        self._available = False
        try:
            import keyring  # type: ignore

            self._keyring = keyring
            self._available = True
        except ImportError:
            logging.warning("keyring library not available - password saving disabled")
            self._keyring = None

    @property
    def available(self) -> bool:
        """Check if keyring is available on this system."""
        return self._available

    def get_password(self, service: str, username: str) -> Optional[str]:
        """Retrieve a stored password from the system keyring."""
        if not self._available:
            return None

        try:
            return self._keyring.get_password(service, username)
        except Exception as e:
            # Log at warning on first occurrence since this affects user experience
            logging.warning("Failed to retrieve password from keyring: %s", e)
            logging.debug("Keyring retrieval error details:", exc_info=True)
            return None

    def set_password(self, service: str, username: str, password: str) -> bool:
        """Store a password in the system keyring."""
        if not self._available:
            return False

        try:
            self._keyring.set_password(service, username, password)
            return True
        except Exception as e:
            logging.warning("Failed to save password to keyring: %s", e)
            logging.debug("Keyring save error details:", exc_info=True)
            return False

    def delete_password(self, service: str, username: str) -> bool:
        """Delete a stored password from the system keyring."""
        if not self._available:
            return False

        try:
            self._keyring.delete_password(service, username)
            return True
        except Exception as e:
            logging.debug("Failed to delete password from keyring: %s", e, exc_info=True)
            return False


class InMemoryCredentialStore:
    """In-memory credential store for testing.

    Stores credentials in a dictionary instead of the system keyring.
    Useful for unit tests that don't need persistent credential storage.
    """

    def __init__(self):
        """Initialize in-memory credential store."""
        self._store: dict[tuple[str, str], str] = {}

    @property
    def available(self) -> bool:
        """In-memory store is always available."""
        return True

    def get_password(self, service: str, username: str) -> Optional[str]:
        """Retrieve a stored password from memory."""
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> bool:
        """Store a password in memory."""
        self._store[(service, username)] = password
        return True

    def delete_password(self, service: str, username: str) -> bool:
        """Delete a stored password from memory."""
        if (service, username) in self._store:
            del self._store[(service, username)]
            return True
        return False


# Type alias for credential store implementations
CredentialStore = KeyringCredentialStore | InMemoryCredentialStore


def create_credential_store(use_keyring: bool = True) -> CredentialStoreProtocol:
    """Factory function to create the appropriate credential store.

    Args:
        use_keyring: If True (default), use system keyring. If False, use in-memory store.

    Returns:
        A credential store implementation.
    """
    if use_keyring:
        return KeyringCredentialStore()
    return InMemoryCredentialStore()
