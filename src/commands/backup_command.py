"""Backup command implementation."""

import logging
from pathlib import Path
from typing import Optional

from ..backup import ReMarkableBackup
from ..backup.connection import USB_HOST
from ..utils.logging import setup_logging


def run_backup_command(
    backup_dir: Path,
    password: Optional[str],
    log_level: str,
    skip_templates: bool,
    force: bool,
    host: str = USB_HOST,
    use_wifi: bool = False,
    wifi_host: str = "",
) -> int:
    """Execute the backup command.

    Args:
        backup_dir: Directory to store backup files
        password: SSH password for tablet
        log_level: Log verbosity (DBG/INF/WRN/ERR)
        skip_templates: Skip backing up template files
        force: Force backup all files (ignore sync status)
        host: Tablet IP/hostname for USB connections
        use_wifi: Use Wi-Fi instead of USB
        wifi_host: Wi-Fi IP/hostname of the tablet

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    log_dir = backup_dir.parent
    setup_logging(log_level, log_dir=log_dir)

    from ..utils.console import print_section

    print_section("Backup")
    print(f"Backup directory: {backup_dir.absolute()}")

    if use_wifi:
        print(f"Connection mode: Wi-Fi ({wifi_host or 'auto-discover'})")
    else:
        print(f"Connection mode: USB ({host})")
    if not skip_templates:
        print("Template backup: Enabled")
    if force:
        print("Force mode: All files will be backed up")

    backup_tool = ReMarkableBackup(
        backup_dir,
        password=password,
        host=host,
        use_wifi=use_wifi,
        wifi_host=wifi_host,
    )

    try:
        success, _, _ = backup_tool.run_backup(
            force_convert_all=False, convert_to_pdf=False, backup_templates=not skip_templates
        )

        if success:
            print("\n[SUCCESS] Backup completed successfully!")
            print(f"Files backed up to: {backup_tool.files_dir}")
            if not skip_templates:
                print(f"Templates backed up to: {backup_tool.templates_dir}")
            return 0
        else:
            print("\n[ERROR] Backup failed. Check logs for details.")
            return 1

    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Backup interrupted by user")
        return 130
    except Exception as e:
        logging.error("Unexpected error: %s", e)
        print(f"\n[ERROR] Unexpected error: {e}")
        return 1
