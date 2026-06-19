"""
Backup package for ReMarkable tablet backup functionality.

This package provides modular components for backing up ReMarkable tablets,
including SSH connection management, file metadata handling, and backup orchestration.
"""

from .backup_manager import ReMarkableBackup
from .connection import ReMarkableConnection
from .credential_store import (
    InMemoryCredentialStore,
    KeyringCredentialStore,
    create_credential_store,
)
from .metadata import FileMetadata
from .protocols import (
    DEFAULT_TABLET_CONFIG,
    ConnectionProtocol,
    CredentialStoreProtocol,
    TabletConfig,
)

__all__ = [
    "ReMarkableConnection",
    "FileMetadata",
    "ReMarkableBackup",
    "ConnectionProtocol",
    "CredentialStoreProtocol",
    "TabletConfig",
    "DEFAULT_TABLET_CONFIG",
    "KeyringCredentialStore",
    "InMemoryCredentialStore",
    "create_credential_store",
]
