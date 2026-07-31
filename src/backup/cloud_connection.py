"""Read-only connection adapter for the undocumented reMarkable Cloud API."""

import json
import logging
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import click

from ..utils.console import print_warn
from .credential_store import create_credential_store
from .protocols import DEFAULT_TABLET_CONFIG, CredentialStoreProtocol, TabletConfig


class ReMarkableCloudConnection:
    """Expose reMarkable Cloud documents through the backup connection protocol."""

    KEYRING_SERVICE = "reMarkableSync"
    KEYRING_USERNAME = "reMarkable_cloud_device_token"

    def __init__(
        self,
        credential_store: Optional[CredentialStoreProtocol] = None,
        tablet_config: Optional[TabletConfig] = None,
        client: Any = None,
    ):
        self.host = "cloud.remarkable.com"
        self.username = "cloud"
        self.port = 443
        self.password = None
        self.password_saved = False
        self._credential_store = credential_store or create_credential_store()
        self._tablet_config = tablet_config or DEFAULT_TABLET_CONFIG
        self._client = client
        self._owns_client = client is None
        self._files: Dict[str, Tuple[Any, Any]] = {}
        self._items: Dict[str, Any] = {}
        self._bundles: Dict[str, Dict[str, bytes]] = {}

    @property
    def scp_client(self):
        """Compatibility shim for callers that still expect an SCP-like client."""
        return self if self._client is not None else None

    def get_saved_password(self) -> Optional[str]:
        """Return the saved cloud device token."""
        return self._credential_store.get_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)

    def save_password(self, password: str) -> bool:
        """Save the cloud device token."""
        success = self._credential_store.set_password(
            self.KEYRING_SERVICE, self.KEYRING_USERNAME, password
        )
        self.password_saved = success
        return success

    def delete_saved_password(self) -> bool:
        """Delete the saved cloud device token."""
        return self._credential_store.delete_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)

    def get_password(self) -> str:
        """Return the saved cloud device token, if present."""
        return self.get_saved_password() or ""

    def authenticate(self, pairing_code: Optional[str] = None) -> bool:
        """Authenticate without downloading the cloud document index."""
        if self._client is None:
            try:
                from httpx import HTTPError
                from remarkapy import Client
                from remarkapy.exceptions import RemarkableAPIError
            except ImportError:
                click.echo(
                    "[ERROR] Cloud sync requires Python 3.12+ and the 'remarkapy' package.",
                    err=True,
                )
                return False

            device_token = self.get_saved_password()
            try:
                self._client = Client(
                    device_token=device_token or None,
                    interactive=False,
                    refresh_on_init=bool(device_token),
                    persist_config=False,
                )
                if not device_token:
                    if pairing_code is None:
                        click.echo(
                            "  Cloud access uses reMarkable's unofficial desktop-app API.\n"
                            "  Create a one-time code at: "
                            "https://my.remarkable.com/device/desktop/connect"
                        )
                        pairing_code = click.prompt("Enter the 8-character reMarkable code").strip()
                    device_token = self._client.register_device(pairing_code)
                    self._client.refresh_user_token()
                    if not self.save_password(device_token):
                        raise RuntimeError(
                            "Could not save the reMarkable cloud device token "
                            "in the system keyring"
                        )
            except (HTTPError, RemarkableAPIError) as exc:
                raise RuntimeError(f"reMarkable Cloud authentication failed: {exc}") from exc
        return True

    def connect(self) -> bool:
        """Authenticate and load the current cloud document index."""
        if not self.authenticate():
            return False

        self._build_file_index()
        print_warn(
            "  WRN - Cloud sync is update-only. Missing cloud items are kept in the local backup."
        )
        return True

    def disconnect(self) -> None:
        """Close the cloud HTTP session."""
        if self._client is not None:
            self._client.close()
            if self._owns_client:
                self._client = None
        self._files.clear()
        self._items.clear()
        self._bundles.clear()

    def execute_command(self, command: str) -> Tuple[str, str, int]:
        """Support the metadata batch-read used by folder filtering."""
        if not self._files:
            raise ConnectionError("Not connected to reMarkable Cloud")
        if ".metadata" not in command or "cat" not in command:
            return "", "Cloud mode does not support remote shell commands", 1

        blocks = []
        for item in sorted(self._items.values(), key=lambda value: value.id):
            metadata = {
                "lastModified": item.lastModified,
                "parent": item.parent,
                "type": item.type,
                "visibleName": item.visibleName,
            }
            blocks.append(f"FILE:{item.id}")
            blocks.append(json.dumps(metadata))
        return "\n".join(blocks), "", 0

    def list_files(self, remote_path: str) -> List[Dict]:
        """List raw cloud document files using tablet-compatible virtual paths."""
        if not self._files:
            raise ConnectionError("Not connected to reMarkable Cloud")
        if remote_path == self._tablet_config.templates_dir:
            logging.info("System templates are not available through reMarkable Cloud")
            return []
        prefix = remote_path.rstrip("/") + "/"
        return [
            {
                "path": path,
                "mtime": self._mtime_for(item),
                "size": file_ref.size,
            }
            for path, (item, file_ref) in self._files.items()
            if path.startswith(prefix)
        ]

    def get(self, remote_path: str, local_path: str, recursive: bool = False) -> None:
        """Download one raw notebook file from the cloud."""
        if recursive:
            raise ValueError("Recursive cloud downloads are not supported")
        try:
            item, file_ref = self._files[remote_path]
        except KeyError as exc:
            raise FileNotFoundError(f"Cloud file not found: {remote_path}") from exc

        bundle = self._bundle_for(item.id)
        try:
            data = bundle[file_ref.id]
        except KeyError as exc:
            raise FileNotFoundError(f"Cloud content unavailable: {remote_path}") from exc

        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    def _build_file_index(self) -> None:
        self._files.clear()
        self._items.clear()
        xochitl = self._tablet_config.xochitl_dir.rstrip("/")

        for item in self._client.list_hydrated_items(refresh=True):
            if item.type == "TemplateType":
                continue
            self._items[item.id] = item
            manifest = self._client.get_entries(item.hash, manifest_id=item.id)
            for file_ref in manifest.entries:
                self._files[f"{xochitl}/{file_ref.id}"] = (item, file_ref)

    def _bundle_for(self, item_id: str) -> Dict[str, bytes]:
        cached = self._bundles.get(item_id)
        if cached is not None:
            return cached

        raw_bundle = self._client.get_document(item_id)
        with zipfile.ZipFile(BytesIO(raw_bundle)) as archive:
            bundle = {name: archive.read(name) for name in archive.namelist()}
        self._bundles[item_id] = bundle
        return bundle

    @staticmethod
    def _mtime_for(item: Any) -> int:
        try:
            return int(item.lastModified) // 1000
        except (TypeError, ValueError):
            return 0
