"""
Backup Manager - Internal Helper Module

This is a helper module providing backup orchestration functionality.
Do not run directly - use RemarkableSync.py as the entry point.

Entry Point:
    RemarkableSync.py backup [OPTIONS]
    RemarkableSync.py sync [OPTIONS]

This module provides:
- SSH connection management to reMarkable tablet
- File synchronization with incremental updates
- Metadata management and tracking
- Optional automatic PDF conversion after backup
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import paramiko
from scp import SCPException

from .connection import ReMarkableConnection
from .metadata import FileMetadata
from .protocols import DEFAULT_TABLET_CONFIG, ConnectionProtocol, TabletConfig


class ReMarkableBackup:  # pylint: disable=too-many-instance-attributes
    """Main backup orchestrator for reMarkable tablet.

    Coordinates SSH connection, file synchronization, metadata management,
    and optional PDF conversion to provide a complete backup solution.

    Key features:
    - Incremental sync based on file modification times
    - Integrity verification using MD5 checksums
    - Automatic PDF conversion integration
    - Progress tracking and detailed logging
    """

    def __init__(
        self,
        backup_dir: Path,
        password: Optional[str] = None,
        host: str = "10.11.99.1",
        use_wifi: bool = False,
        wifi_host: str = "",
        pre_sync_command: str = "",
        post_sync_command: str = "",
        connection: Optional[ConnectionProtocol] = None,
        tablet_config: Optional[TabletConfig] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize backup orchestrator.

        Args:
            backup_dir: Local directory to store backup files
            password: SSH password for tablet (prompted if not provided)
            host: Tablet IP/hostname (USB default: 10.11.99.1)
            use_wifi: Connect via Wi-Fi instead of USB
            wifi_host: Wi-Fi IP/hostname (auto-discovered if empty)
            pre_sync_command: Shell command to run before SSH connects.
            post_sync_command: Shell command to run after SSH disconnects.
            connection: Optional connection instance for dependency injection.
            tablet_config: Tablet-specific configuration (paths, etc.).
            config: Application configuration dict (injected instead of loading globally).
        """
        self.backup_dir = backup_dir
        self.files_dir = backup_dir / "Notebooks"
        self.templates_dir = backup_dir / "Templates"
        self.metadata_file = backup_dir / "sync_metadata.json"

        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)

        # Store injected config or None (will load on demand if needed)
        self._config = config

        # Use injected connection or create default
        if connection is not None:
            self.connection = connection
        else:
            self.connection = ReMarkableConnection(
                password=password,
                host=host,
                use_wifi=use_wifi,
                wifi_host=wifi_host,
                pre_sync_command=pre_sync_command,
                post_sync_command=post_sync_command,
            )
        self.metadata = FileMetadata(self.metadata_file)

        # Use injected tablet config or default
        self._tablet_config = tablet_config or DEFAULT_TABLET_CONFIG

        # ReMarkable paths (from tablet config)
        self.remote_xochitl_dir = self._tablet_config.xochitl_dir
        self.remote_templates_dir = self._tablet_config.templates_dir

    def _get_config(self) -> Dict[str, Any]:
        """Get configuration, loading from disk if not injected."""
        if self._config is not None:
            return self._config
        from ..config import load_config

        return load_config()

    def _resolve_allowed_uuids(self) -> Optional[Set[str]]:
        """Resolve which notebook UUIDs belong to the configured folder filter.

        Reads .metadata files from the tablet over SSH (already connected)
        to determine folder hierarchy, then returns UUIDs that belong to
        selected folders. Returns None if no filter is configured.
        """
        config = self._get_config()
        folder_names = config.get("folders", [])
        if not folder_names:
            print("  Syncing: all folders")
            return None

        print(f"  Syncing folders: {', '.join(folder_names)}")

        # Read all metadata files from the tablet in one command
        stdout, stderr, exit_code = self.connection.execute_command(
            f"for f in {self.remote_xochitl_dir}/*.metadata; do "
            f'[ -f "$f" ] && echo "FILE:$(basename $f .metadata)" && cat "$f"; '
            f"done"
        )
        if exit_code != 0:
            logging.warning("Could not read metadata for folder filtering")
            return None

        # Parse all metadata
        metadata_cache: Dict[str, dict] = {}
        current_uuid = None
        current_lines = []
        for line in stdout.split("\n"):
            if line.startswith("FILE:"):
                if current_uuid and current_lines:
                    try:
                        metadata_cache[current_uuid] = json.loads("\n".join(current_lines))
                    except (json.JSONDecodeError, ValueError):
                        pass
                current_uuid = line[5:].strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_uuid and current_lines:
            try:
                metadata_cache[current_uuid] = json.loads("\n".join(current_lines))
            except (json.JSONDecodeError, ValueError):
                pass

        # Walk parent chain to find top-level folder for each UUID
        include_root = "(Root)" in folder_names
        real_folder_names = [f for f in folder_names if f != "(Root)"]

        def _get_top_folder(uuid: str) -> str:
            visited = set()
            current = uuid
            while current and current not in visited:
                visited.add(current)
                meta = metadata_cache.get(current)
                if not meta:
                    return ""
                parent = meta.get("parent", "")
                if not parent:
                    if meta.get("type") == "CollectionType":
                        return meta.get("visibleName", "")
                    return ""
                parent_meta = metadata_cache.get(parent)
                if parent_meta and not parent_meta.get("parent", ""):
                    return parent_meta.get("visibleName", "")
                current = parent
            return ""

        allowed = set()
        for uuid, meta in metadata_cache.items():
            parent = meta.get("parent", "")
            # Root-level items (no parent)
            if include_root and not parent:
                allowed.add(uuid)
                continue
            # Items inside selected folders
            top = _get_top_folder(uuid)
            if top and top in real_folder_names:
                allowed.add(uuid)

        logging.info(
            "Folder filter: %d/%d items in selected folders",
            len(allowed),
            len(metadata_cache),
        )
        print(f"  Found {len(allowed)} notebooks in selected folders")
        return allowed

    def _do_backup_files(
        self,
    ) -> Tuple[bool, Set[str], Dict[str, Set[str]]]:  # pylint: disable=too-many-branches
        """Backup files from reMarkable tablet. Assumes connection is already open."""
        logging.info("Starting file backup...")

        try:
            allowed_uuids = self._resolve_allowed_uuids()

            # Get list of remote files
            from src.utils.console import console

            with console.status("[bold blue]Scanning tablet files..."):
                remote_files = self.connection.list_files(self.remote_xochitl_dir)
            print(f"  Scanned {len(remote_files)} files on tablet")

            if not remote_files:
                logging.warning("No files found on reMarkable tablet")
                return True, set(), {}

            # Apply folder filter — only sync files belonging to allowed UUIDs
            if allowed_uuids is not None:

                def _file_in_allowed(rf):
                    rel = os.path.relpath(rf["path"], self.remote_xochitl_dir)
                    parts = rel.split(os.sep)
                    # Extract UUID from path (e.g. "uuid.metadata" or "uuid/page.rm")
                    first = parts[0].split(".")[0]
                    if len(first) == 36:
                        return first in allowed_uuids
                    return True  # Non-UUID files (e.g. version) always synced

                before = len(remote_files)
                remote_files = [rf for rf in remote_files if _file_in_allowed(rf)]
                print(f"  Filtered to {len(remote_files)} files (from {before} total)")

            if not remote_files:
                logging.warning("No files found on reMarkable tablet")
                return True, set(), {}

            # Filter files that need syncing
            files_to_sync = []
            for remote_file in remote_files:
                relative_path = os.path.relpath(remote_file["path"], self.remote_xochitl_dir)
                local_path = self.files_dir / relative_path

                if self.metadata.should_sync_file(remote_file, local_path):
                    files_to_sync.append((remote_file, local_path))

            if not files_to_sync:
                print("  All files are up to date")
                logging.info("All files are up to date")
                return True, set(), {}

            print(f"  Downloading {len(files_to_sync)} changed files...")

            # Track which notebooks have been updated
            updated_notebooks = set()
            # Track which specific pages changed per notebook
            updated_pages: Dict[str, Set[str]] = {}

            # Download files with Rich progress bar (pinned to bottom)
            from src.utils.console import create_progress, print_error

            with create_progress("Downloading") as progress:
                task = progress.add_task("Downloading", total=len(files_to_sync))

                for remote_file, local_path in files_to_sync:
                    try:
                        # Create local directory if needed
                        local_path.parent.mkdir(parents=True, exist_ok=True)

                        # Download file
                        if self.connection.scp_client is None:
                            logging.error("SCP client not initialized")
                            return False, set(), {}
                        self.connection.scp_client.get(remote_file["path"], str(local_path))

                        # Update metadata
                        self.metadata.update_file_metadata(remote_file, local_path)

                        # Track notebook UUID if this file belongs to a notebook
                        relative_path = os.path.relpath(
                            remote_file["path"], self.remote_xochitl_dir
                        )
                        path_parts = relative_path.split(os.sep)

                        notebook_uuid = None
                        if len(path_parts) >= 1:
                            first_part = path_parts[0].split(".")[0]
                            if len(first_part) == 36 and first_part not in [
                                "templates",
                                "version",
                            ]:
                                notebook_uuid = first_part

                        if len(path_parts) >= 2:
                            if len(path_parts[0]) == 36 and path_parts[0] not in [
                                "templates",
                                "version",
                            ]:
                                notebook_uuid = path_parts[0]

                        if notebook_uuid:
                            updated_notebooks.add(notebook_uuid)

                            if len(path_parts) >= 2 and path_parts[-1].endswith(".rm"):
                                page_id = path_parts[-1].rsplit(".", 1)[0]
                                if notebook_uuid not in updated_pages:
                                    updated_pages[notebook_uuid] = set()
                                updated_pages[notebook_uuid].add(page_id)

                        progress.update(task, advance=1, description=local_path.name[:40])

                    except (OSError, SCPException) as e:
                        print_error(f"  ERR - Failed to download {remote_file['path']}: {e}")
                        progress.update(task, advance=1)

            # Save metadata
            self.metadata.save()

            if updated_notebooks:
                logging.debug("Updated notebook UUIDs: %s", sorted(updated_notebooks))

            logging.info(
                "File backup completed successfully. Updated %d notebooks.", len(updated_notebooks)
            )
            return True, updated_notebooks, updated_pages

        except (paramiko.SSHException, OSError) as e:
            logging.error("Backup failed: %s", e)
            return False, set(), {}

    def _do_backup_templates(self) -> bool:
        """Backup template files from reMarkable tablet. Assumes connection is already open."""
        logging.info("Starting template backup...")

        try:
            # Get list of template files
            remote_files = self.connection.list_files(self.remote_templates_dir)

            if not remote_files:
                logging.warning("No template files found on reMarkable tablet")
                return True

            # Filter templates that need syncing
            files_to_sync = []
            for remote_file in remote_files:
                relative_path = os.path.relpath(remote_file["path"], self.remote_templates_dir)
                local_path = self.templates_dir / relative_path

                if self.metadata.should_sync_file(remote_file, local_path):
                    files_to_sync.append((remote_file, local_path))

            if not files_to_sync:
                logging.info("All template files are up to date")
                return True

            logging.info("Syncing %d template files...", len(files_to_sync))

            # Download template files with progress bar
            from src.utils.console import create_progress, print_error

            with create_progress("Templates") as progress:
                task = progress.add_task("Templates", total=len(files_to_sync))
                for remote_file, local_path in files_to_sync:
                    try:
                        local_path.parent.mkdir(parents=True, exist_ok=True)

                        if self.connection.scp_client is None:
                            logging.error("SCP client not initialized")
                            return False
                        self.connection.scp_client.get(remote_file["path"], str(local_path))

                        self.metadata.update_file_metadata(remote_file, local_path)

                    except (OSError, SCPException) as e:
                        print_error(f"  ERR - Failed to download {remote_file['path']}: {e}")

                    progress.update(task, advance=1, description=local_path.name[:40])

            # Save metadata
            self.metadata.save()

            logging.info("Template backup completed successfully")
            return True

        except (paramiko.SSHException, OSError) as e:
            logging.error("Template backup failed: %s", e)
            return False

    def find_notebooks(self) -> List[Dict]:
        """Find and parse notebook metadata.

        Scans the backup directory for .metadata files and extracts
        notebook information including name, type, and associated files.

        Returns:
            List of dictionaries containing notebook information
        """
        notebooks = []

        # Look for .metadata files which indicate notebooks/documents
        for metadata_file in self.files_dir.glob("*.metadata"):
            try:
                with open(metadata_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)

                uuid = metadata_file.stem
                notebook_info = {
                    "uuid": uuid,
                    "name": metadata.get("visibleName", "Untitled"),
                    "type": metadata.get("type", "unknown"),
                    "parent": metadata.get("parent", ""),
                    "metadata_file": metadata_file,
                    "content_file": self.files_dir / f"{uuid}.content",
                    "rm_files": list(self.files_dir.glob(f"{uuid}/*.rm")),
                    "pagedata_files": list(self.files_dir.glob(f"{uuid}/*.json")),
                }

                if notebook_info["content_file"].exists():
                    notebooks.append(notebook_info)

            except (OSError, json.JSONDecodeError) as e:
                logging.warning("Failed to parse %s: %s", metadata_file, e)

        return notebooks

    def convert_to_pdf(self, notebook: Dict) -> Optional[Path]:
        """Convert notebook to PDF using available tools.

        Creates a placeholder metadata file for the notebook.
        In a full implementation, this would integrate with PDF conversion tools.

        Args:
            notebook: Dictionary containing notebook information

        Returns:
            Optional[Path]: Path to created file, None on error
        """
        output_path = self.backup_dir / "PDF" / f"{notebook['name']}.pdf"

        # For now, create a placeholder PDF indicating conversion is needed
        # In a real implementation, you would integrate with rm2pdf or rmc
        try:
            with open(output_path.with_suffix(".txt"), "w", encoding="utf-8") as f:
                f.write(f"Notebook: {notebook['name']}\n")
                f.write(f"UUID: {notebook['uuid']}\n")
                f.write(f"Type: {notebook['type']}\n")
                f.write(f"RM Files: {len(notebook['rm_files'])}\n")
                f.write(f"Pages: {len(notebook['pagedata_files'])}\n")
                f.write("\nTo convert to PDF, you'll need to install rmc or rm2pdf tools\n")
                f.write("See: https://github.com/ricklupton/rmc\n")

            logging.info("Created metadata for %s", notebook["name"])
            return output_path.with_suffix(".txt")

        except OSError as e:
            logging.error("Failed to create PDF metadata for %s: %s", notebook["name"], e)
            return None

    def run_backup(
        self,
        force_convert_all: bool = False,
        convert_to_pdf: bool = False,
        backup_templates: bool = True,
    ) -> Tuple[bool, Set[str], Dict[str, Set[str]]]:
        """Run complete backup process with optional PDF conversion.

        Args:
            force_convert_all: If True, convert all notebooks to PDF regardless of sync status
            convert_to_pdf: If True, automatically convert notebooks to PDF using hybrid converter
            backup_templates: If True, backup template files from the tablet (default: True)

        Returns:
            Tuple of (success, updated_notebook_uuids, updated_pages)
        """
        logging.info("Starting reMarkable backup process")

        if not self.connection.connect():
            return False, set(), {}

        updated_notebook_uuids: Set[str] = set()
        updated_pages: Dict[str, Set[str]] = {}

        try:
            success, updated_notebook_uuids, updated_pages = self._do_backup_files()
            if not success:
                return False, set(), {}

            if backup_templates:
                templates_success = self._do_backup_templates()
                if not templates_success:
                    logging.warning("Template backup failed, but continuing with main backup")
        finally:
            self.connection.disconnect()

        if convert_to_pdf:
            ok = self.run_pdf_conversion(updated_notebook_uuids, force_convert_all, updated_pages)
            return ok, updated_notebook_uuids, updated_pages

        logging.info("Backup process completed successfully")
        return True, updated_notebook_uuids, updated_pages

    def run_pdf_conversion(
        self,
        updated_notebook_uuids: Set[str],
        force_convert_all: bool = False,
        updated_pages: Optional[Dict[str, Set[str]]] = None,
    ) -> bool:
        """Run PDF conversion using the converter module.

        Args:
            updated_notebook_uuids: Set of notebook UUIDs that were updated during sync
            force_convert_all: If True, convert all notebooks regardless of sync status
            updated_pages: Dict mapping notebook UUID to set of changed page IDs

        Returns:
            bool: True if conversion successful, False otherwise
        """
        from ..rm_pdf_converter import run_conversion

        logging.info("Starting PDF conversion...")

        # Get config (injected or loaded)
        config = self._get_config()

        pdf_dir = config.get("pdf_dir", "")
        if pdf_dir:
            output_dir = Path(pdf_dir)
        else:
            output_dir = self.backup_dir / "PDF"
            logging.warning("No pdf_dir configured, falling back to %s", output_dir)

        if not updated_notebook_uuids and not force_convert_all:
            logging.info("No notebooks were updated - skipping PDF conversion")
            return True

        folder_filter = config.get("folders", []) or None

        try:
            success, _converted, _merged = run_conversion(
                backup_dir=self.backup_dir,
                output_dir=output_dir,
                verbose="INF",
                sample=None,
                notebook_filter=None,
                updated_uuids=updated_notebook_uuids if not force_convert_all else None,
                updated_pages=updated_pages,
                folder_filter=folder_filter,
            )

            if success:
                logging.info("PDF conversion completed successfully")
            else:
                logging.error("PDF conversion failed")

            return success

        except Exception as e:  # pylint: disable=broad-except
            logging.error("Failed to execute PDF conversion: %s", e)
            return False
