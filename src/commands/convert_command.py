"""Convert command implementation."""

import logging
from pathlib import Path
from typing import Optional

from ..rm_pdf_converter import run_conversion
from ..utils.logging import setup_logging


def _resolve_backup_dir(backup_dir: Path) -> Path:
    """Resolve backup directory using config when CLI default path is missing."""
    if backup_dir.exists():
        return backup_dir

    default_cli_backup_dir = Path("./remarkable_backup").absolute()
    if backup_dir.expanduser().absolute() != default_cli_backup_dir:
        return backup_dir

    from ..config import load_config

    configured_backup_dir = str(load_config().get("backup_dir", "")).strip()
    if configured_backup_dir:
        candidate = Path(configured_backup_dir).expanduser()
        candidate.mkdir(parents=True, exist_ok=True)
        print(f"Using configured backup directory: {candidate}")
        return candidate

    return backup_dir


def run_convert_command(
    backup_dir: Path,
    output_dir: Optional[Path],
    log_level: str,
    force_all: bool,
    sample: Optional[int],
    notebook: Optional[str],
) -> int:
    """Execute the convert command.

    Args:
        backup_dir: Directory containing reMarkable backup files
        output_dir: Directory to save PDF files
        log_level: Log verbosity (DBG/INF/WRN/ERR)
        force_all: Convert all notebooks (ignore sync status)
        sample: Convert only first N notebooks
        notebook: Convert only this notebook (by UUID or name)

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    from ..config import get_config_dir

    log_dir = get_config_dir()
    setup_logging(log_level, log_dir=log_dir)
    backup_dir = _resolve_backup_dir(backup_dir)

    if not backup_dir.exists():
        print(f"[ERROR] Backup directory not found: {backup_dir}")
        return 1

    # Set default output directory from config
    if not output_dir:
        from ..config import load_config

        config = load_config()
        pdf_dir = config.get("pdf_dir", "")
        if pdf_dir:
            output_dir = Path(pdf_dir)
        else:
            print("[ERROR] No PDF directory configured. Run 'remarkablesync config' first.")
            return 1

    print("reMarkable PDF Converter")
    print("=" * 70)
    print(f"Backup directory: {backup_dir}")
    print(f"Output directory: {output_dir}")

    if force_all:
        print("Force mode: Converting all notebooks")
    if sample:
        print(f"Sample mode: Converting first {sample} notebooks")
    if notebook:
        print(f"Single notebook mode: Converting {notebook}")

    try:
        # Determine updated notebooks list
        updated_only_file = None
        if not force_all and not notebook and not sample:
            # Check if there's an updated_notebooks.txt from recent backup
            updated_list = backup_dir / "updated_notebooks.txt"
            if updated_list.exists():
                updated_only_file = updated_list
                print("Converting recently updated notebooks only")

        updated_uuids: set | None = None
        if updated_only_file and updated_only_file.exists():
            lines = updated_only_file.read_text(encoding="utf-8").splitlines()
            updated_uuids = {ln.strip() for ln in lines if ln.strip()}

        success, _converted, _merged = run_conversion(
            backup_dir=backup_dir,
            output_dir=output_dir,
            verbose=log_level,
            sample=sample,
            notebook_filter=notebook,
            updated_uuids=updated_uuids,
        )

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Conversion interrupted by user")
        return 130
    except Exception as e:
        logging.error("Unexpected error: %s", e)
        print(f"\n[ERROR] Unexpected error: {e}")
        return 1
