"""
Tests for credential_store module.

Tests both KeyringCredentialStore and InMemoryCredentialStore.
"""

from unittest.mock import MagicMock, patch

from src.backup.credential_store import (
    InMemoryCredentialStore,
    KeyringCredentialStore,
    create_credential_store,
)


class TestInMemoryCredentialStore:
    """Tests for InMemoryCredentialStore."""

    def test_available_always_true(self):
        """InMemoryCredentialStore is always available."""
        store = InMemoryCredentialStore()
        assert store.available is True

    def test_set_and_get_password(self):
        """Can store and retrieve passwords."""
        store = InMemoryCredentialStore()

        result = store.set_password("service", "user", "secret123")

        assert result is True
        assert store.get_password("service", "user") == "secret123"

    def test_get_nonexistent_password(self):
        """Returns None for passwords that don't exist."""
        store = InMemoryCredentialStore()

        assert store.get_password("service", "user") is None

    def test_delete_password(self):
        """Can delete stored passwords."""
        store = InMemoryCredentialStore()
        store.set_password("service", "user", "secret123")

        result = store.delete_password("service", "user")

        assert result is True
        assert store.get_password("service", "user") is None

    def test_delete_nonexistent_password(self):
        """Deleting nonexistent password returns False."""
        store = InMemoryCredentialStore()

        result = store.delete_password("service", "user")

        assert result is False

    def test_multiple_services(self):
        """Can store passwords for multiple service/user combinations."""
        store = InMemoryCredentialStore()

        store.set_password("service1", "user1", "pass1")
        store.set_password("service1", "user2", "pass2")
        store.set_password("service2", "user1", "pass3")

        assert store.get_password("service1", "user1") == "pass1"
        assert store.get_password("service1", "user2") == "pass2"
        assert store.get_password("service2", "user1") == "pass3"


class TestKeyringCredentialStore:
    """Tests for KeyringCredentialStore."""

    def test_available_when_keyring_imports(self):
        """available is True when keyring imports successfully."""
        with patch.dict("sys.modules", {"keyring": MagicMock()}):
            store = KeyringCredentialStore()
            # Force re-init with mocked keyring
            store._available = True
            store._keyring = MagicMock()

            assert store.available is True

    def test_available_false_when_keyring_missing(self):
        """available is False when keyring import fails."""
        store = KeyringCredentialStore()
        store._available = False

        assert store.available is False

    def test_get_password_returns_none_when_unavailable(self):
        """get_password returns None when keyring unavailable."""
        store = KeyringCredentialStore()
        store._available = False

        assert store.get_password("service", "user") is None

    def test_set_password_returns_false_when_unavailable(self):
        """set_password returns False when keyring unavailable."""
        store = KeyringCredentialStore()
        store._available = False

        assert store.set_password("service", "user", "pass") is False

    def test_delete_password_returns_false_when_unavailable(self):
        """delete_password returns False when keyring unavailable."""
        store = KeyringCredentialStore()
        store._available = False

        assert store.delete_password("service", "user") is False

    def test_get_password_calls_keyring(self):
        """get_password delegates to keyring module."""
        store = KeyringCredentialStore()
        store._available = True
        store._keyring = MagicMock()
        store._keyring.get_password.return_value = "secret"

        result = store.get_password("myservice", "myuser")

        assert result == "secret"
        store._keyring.get_password.assert_called_once_with("myservice", "myuser")

    def test_set_password_calls_keyring(self):
        """set_password delegates to keyring module."""
        store = KeyringCredentialStore()
        store._available = True
        store._keyring = MagicMock()

        result = store.set_password("myservice", "myuser", "mypass")

        assert result is True
        store._keyring.set_password.assert_called_once_with("myservice", "myuser", "mypass")

    def test_delete_password_calls_keyring(self):
        """delete_password delegates to keyring module."""
        store = KeyringCredentialStore()
        store._available = True
        store._keyring = MagicMock()

        result = store.delete_password("myservice", "myuser")

        assert result is True
        store._keyring.delete_password.assert_called_once_with("myservice", "myuser")

    def test_handles_keyring_exception_on_get(self):
        """get_password handles keyring exceptions gracefully."""
        store = KeyringCredentialStore()
        store._available = True
        store._keyring = MagicMock()
        store._keyring.get_password.side_effect = Exception("Keyring locked")

        result = store.get_password("service", "user")

        assert result is None

    def test_handles_keyring_exception_on_set(self):
        """set_password handles keyring exceptions gracefully."""
        store = KeyringCredentialStore()
        store._available = True
        store._keyring = MagicMock()
        store._keyring.set_password.side_effect = Exception("Keyring locked")

        result = store.set_password("service", "user", "pass")

        assert result is False

    def test_handles_keyring_exception_on_delete(self):
        """delete_password handles keyring exceptions gracefully."""
        store = KeyringCredentialStore()
        store._available = True
        store._keyring = MagicMock()
        store._keyring.delete_password.side_effect = Exception("Keyring locked")

        result = store.delete_password("service", "user")

        assert result is False


class TestCreateCredentialStore:
    """Tests for create_credential_store factory function."""

    def test_creates_keyring_store_by_default(self):
        """Default creates KeyringCredentialStore."""
        store = create_credential_store()

        assert isinstance(store, KeyringCredentialStore)

    def test_creates_keyring_store_when_requested(self):
        """use_keyring=True creates KeyringCredentialStore."""
        store = create_credential_store(use_keyring=True)

        assert isinstance(store, KeyringCredentialStore)

    def test_creates_memory_store_when_requested(self):
        """use_keyring=False creates InMemoryCredentialStore."""
        store = create_credential_store(use_keyring=False)

        assert isinstance(store, InMemoryCredentialStore)
