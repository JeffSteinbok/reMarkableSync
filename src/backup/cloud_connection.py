"""Read-only connection adapter for the undocumented reMarkable Cloud API."""

import json
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
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
        missing_policy: str = "keep",
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
        if missing_policy not in {"keep", "archive"}:
            raise ValueError(f"Unsupported cloud missing-file policy: {missing_policy}")
        self.missing_policy = missing_policy
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
                    "[ERROR] Cloud sync requires the 'remarkapy' package.",
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
                            "  Cloud access uses reMarkable's desktop-app API.\n"
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
                "lastModified": str(self._mtime_for(item) * 1000),
                "parent": item.parent,
                "type": item.type,
                "visibleName": item.visibleName,
            }
            blocks.append(f"FILE:{item.id}")
            blocks.append(json.dumps(metadata))
        return "\n".join(blocks), "", 0

    def list_top_level_folders(self) -> List[str]:
        """Return cloud folders without building the full backup file index."""
        if not self.authenticate():
            return []
        return sorted(
            item.visibleName
            for item in self._client.list_items(refresh=True)
            if item.type == "CollectionType" and not item.parent
        )

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

    def reconcile_missing_files(
        self,
        local_root: Path,
        remote_root: str,
        remote_files: List[Dict],
    ) -> List[Path]:
        """Keep or archive files absent from the latest successful cloud listing."""
        inventory_path = local_root.parent / "cloud_inventory.json"
        previous = self._load_inventory(inventory_path)
        current = {
            str(Path(file["path"]).relative_to(remote_root))
            for file in remote_files
            if file["path"].startswith(remote_root.rstrip("/") + "/")
        }

        archived: List[Path] = []
        archive_root: Optional[Path] = None
        if self.missing_policy == "archive" and previous:
            for relative_text in sorted(previous - current):
                relative = Path(relative_text)
                if relative.is_absolute() or ".." in relative.parts:
                    logging.warning("Ignoring unsafe cloud inventory path: %s", relative_text)
                    continue
                source = local_root / relative
                if not source.is_file():
                    continue
                if archive_root is None:
                    archive_root = self._new_archive_root(local_root.parent)
                destination = archive_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.replace(destination)
                archived.append(destination)

            if archived:
                print_warn(
                    f"  WRN - Treated {len(archived)} missing cloud files as deleted; "
                    f"moved them to {archive_root}"
                )

        self._save_inventory(inventory_path, current)
        return archived

    def _build_file_index(self) -> None:
        self._files.clear()
        self._items.clear()
        xochitl = self._tablet_config.xochitl_dir.rstrip("/")

        items = [
            item for item in self._client.list_items(refresh=True) if item.type != "TemplateType"
        ]
        worker_count = min(16, len(items))
        with ThreadPoolExecutor(max_workers=worker_count or 1) as executor:
            manifests = executor.map(
                lambda item: self._client.get_entries(item.hash, manifest_id=item.id),
                items,
            )

        for item, manifest in zip(items, manifests, strict=True):
            self._items[item.id] = item
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
    def _load_inventory(path: Path) -> set[str]:
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logging.warning("Could not read cloud inventory: %s", path)
            return set()
        files = data.get("files", [])
        if not isinstance(files, list):
            return set()
        return {value for value in files if isinstance(value, str)}

    @staticmethod
    def _save_inventory(path: Path, files: set[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "files": sorted(files)}, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _new_archive_root(backup_root: Path) -> Path:
        base = backup_root / "Cloud Archive" / datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = base
        suffix = 2
        while candidate.exists():
            candidate = Path(f"{base}-{suffix}")
            suffix += 1
        return candidate

    @staticmethod
    def _mtime_for(item: Any) -> int:
        try:
            return int(item.lastModified) // 1000
        except (AttributeError, TypeError, ValueError):
            return int(item.hash[:16], 16)
