"""Sync command implementation - backup and convert in one go."""

import logging
from pathlib import Path
from typing import Optional

from ..backup import ReMarkableBackup
from ..backup.connection import USB_HOST
from ..utils.logging import setup_logging


def run_sync_command(
    backup_dir: Path,
    password: Optional[str] = None,
    log_level: str = "WRN",
    skip_templates: bool = False,
    force_backup: bool = False,
    force_convert: bool = False,
    host: str = USB_HOST,
    use_wifi: bool = False,
    wifi_host: str = "",
) -> int:
    """Execute the sync command (backup + convert).

    This is the most common workflow: backup the tablet and then convert
    any notebooks that were updated during the backup.

    Args:
        backup_dir: Directory to store backup files
        password: SSH password for tablet
        log_level: Log verbosity (DBG/INF/WRN/ERR)
        skip_templates: Skip backing up template files
        force_backup: Force backup all files
        force_convert: Force convert all notebooks
        host: Tablet IP/hostname for USB connections
        use_wifi: Use Wi-Fi instead of USB
        wifi_host: Wi-Fi IP/hostname of the tablet

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    import time as _time

    from ..config import load_config

    log_dir = backup_dir.parent
    setup_logging(log_level, log_dir=log_dir)
    _start_time = _time.monotonic()

    config = load_config()

    print("reMarkable Sync (Backup + Convert)")
    print("=" * 70)
    print(f"Backup directory: {backup_dir.absolute()}")

    if use_wifi:
        print(f"Connection mode: Wi-Fi ({wifi_host or 'auto-discover'})")
    else:
        print(f"Connection mode: USB ({host})")
    if not skip_templates:
        print("Template backup: Enabled")
    if force_backup:
        print("Force backup: All files will be backed up")
    if force_convert:
        print("Force convert: All notebooks will be converted")

    # ------------------------------------------------------------------
    # Backup + convert
    # ------------------------------------------------------------------
    backup_tool = ReMarkableBackup(
        backup_dir,
        password=password,
        host=host,
        use_wifi=use_wifi,
        wifi_host=wifi_host,
        pre_sync_command=config.get("pre_sync_command", "").strip(),
        post_sync_command=config.get("post_sync_command", "").strip(),
    )

    try:
        # Run backup with PDF conversion enabled
        success, _, _ = backup_tool.run_backup(
            force_convert_all=force_convert,
            convert_to_pdf=True,
            backup_templates=not skip_templates,
        )

        elapsed = _time.monotonic() - _start_time
        mins, secs = divmod(int(elapsed), 60)

        if success:
            print()
            print("=" * 70)
            print("  Sync Summary")
            print("=" * 70)
            print(f"  Backup     : {backup_tool.files_dir}")
            if not skip_templates:
                print(f"  Templates  : {backup_tool.templates_dir}")
            _pdf_dir = config.get("pdf_dir", "")
            if _pdf_dir and Path(_pdf_dir).exists():
                print(f"  PDFs       : {_pdf_dir}")
            print(f"  Duration   : {mins}m {secs}s")
            print("=" * 70)

            # ------------------------------------------------------------------
            # Post-sync command
            # ------------------------------------------------------------------
            return 0
        else:
            print("\n[ERROR] Sync failed. Check logs for details.")
            return 1

    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Sync interrupted by user")
        return 130
    except Exception as e:
        logging.error("Unexpected error: %s", e)
        print(f"\n[ERROR] Unexpected error: {e}")
        return 1
