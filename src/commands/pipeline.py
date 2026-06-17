"""Markdown sync command implementation.

Chains the full pipeline:
  1. Backup from tablet (optional)
  2. Convert notebooks to PDF (optional)
  3. OCR / AI handwriting transcription
  4. Export Markdown notes to the output directory
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from ..backup import ReMarkableBackup
from ..backup.connection import USB_HOST
from ..rm_pdf_converter import run_conversion
from ..utils import write_manifest
from ..utils.console import print_error, print_success, print_warn
from ..utils.logging import setup_logging


def run_pipeline(
    backup_dir: Path,
    output_dir: Path,
    password: Optional[str] = None,
    log_level: str = "WRN",
    skip_backup: bool = False,
    skip_convert: bool = False,
    force_backup: bool = False,
    force_convert: bool = False,
    force_export: bool = False,
    ai_provider: str = "",
    ai_model: str = "",
    ai_api_key: str = "",
    use_ai_ocr: bool = True,
    notebook_filter: Optional[str] = None,
    page_filter: Optional[int] = None,
    tags: str = "reMarkable",
    embed_images: bool = True,
    host: str = USB_HOST,
    use_wifi: bool = False,
    wifi_host: str = "",
) -> int:
    """Run the full pipeline: backup → PDF → OCR/AI → Markdown export.

    Args:
        backup_dir: RemarkableSync backup directory.
        output_dir: Root of the Markdown output directory.
        password: SSH password for tablet.
        log_level: Log verbosity (DBG/INF/WRN/ERR).
        skip_backup: Skip the tablet backup stage.
        skip_convert: Skip the PDF conversion stage.
        force_backup: Force full backup (ignore incremental state).
        force_convert: Force convert all notebooks.
        force_export: Re-export all notes even if unchanged.
        ai_provider: AI provider name (``"claude"`` / ``"github"``).
        ai_model: Override the default model for the chosen provider.
        ai_api_key: API key (falls back to env-vars when empty).
        use_ai_ocr: Use AI vision for handwriting recognition.
        tags: Comma-separated tags to add to every note's frontmatter.
        embed_images: Embed page image attachments in notes.
        host: Tablet USB IP/hostname.
        use_wifi: Use Wi-Fi connection.
        wifi_host: Wi-Fi IP/hostname.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    import time as _time

    log_dir = backup_dir.parent
    setup_logging(log_level, log_dir=log_dir)
    _start_time = _time.monotonic()

    from ..config import load_config

    config = load_config()

    pdf_output_dir = Path(config.get("pdf_dir", "")) if config.get("pdf_dir") else None
    if not pdf_output_dir:
        print("[ERROR] No PDF directory configured. Run 'remarkablesync config' first.")
        return 1
    folder_filter = config.get("folders", []) or None

    conn_label = f"Wi-Fi ({wifi_host or 'auto-discover'})" if use_wifi else f"USB ({host})"

    print()
    print("=" * 70)
    print("  reMarkable -> Markdown Export")
    print("=" * 70)
    if not skip_backup:
        print(f"  * Backup via {conn_label} to {backup_dir.absolute()}")
    if not skip_convert:
        print(f"  * Export PDFs to {pdf_output_dir.absolute()}")
    if use_ai_ocr and ai_provider:
        print(f"  * Export Markdown using {ai_provider} to {output_dir.absolute()}")
    else:
        print(f"  * Export Markdown to {output_dir.absolute()}")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Stage 1: Backup
    # ------------------------------------------------------------------
    pre_sync_cmd = config.get("pre_sync_command", "").strip()
    post_sync_cmd = config.get("post_sync_command", "").strip()
    updated_uuids: set = set()
    updated_pages: dict = {}

    if not skip_backup:
        print("\n[1/3] Backing up tablet...")

        backup_tool = ReMarkableBackup(
            backup_dir,
            password=password,
            host=host,
            use_wifi=use_wifi,
            wifi_host=wifi_host,
            pre_sync_command=pre_sync_cmd,
            post_sync_command=post_sync_cmd,
        )
        backup_ok = False
        try:
            success, updated_uuids, updated_pages = backup_tool.run_backup(
                backup_templates=True,
            )
            if not success:
                print_error("  ERR - Backup failed.")
            else:
                print_success(f"  OK - Backed up ({len(updated_uuids)} notebooks updated)")
                write_manifest(
                    backup_dir.parent / "updated_notebooks.txt",
                    sorted(updated_uuids),
                    "updated_notebooks",
                )
                backup_ok = True
        except Exception as exc:  # noqa: BLE001
            logging.error("Backup error: %s", exc)
            print_error(f"  ERR - Backup failed: {exc}")

        if not backup_ok:
            return 1
    else:
        print("\n[1/3] Backup skipped (--skip-backup)")

    # ------------------------------------------------------------------
    # Stage 2: PDF conversion
    # ------------------------------------------------------------------
    converted_pages: Optional[Dict[str, List[Path]]] = None  # None = run on all

    if not skip_convert:
        print("\n[2/3] Converting notebooks to PDF...")

        try:
            _ok, converted_pages, merged_pdfs = run_conversion(
                backup_dir=backup_dir,
                output_dir=pdf_output_dir,
                verbose=log_level,
                updated_uuids=updated_uuids if not force_convert and not skip_backup else None,
                updated_pages=updated_pages,
                folder_filter=folder_filter,
            )
            print_success("  OK - PDF conversion done")
            all_page_pdfs = sorted(p for pages in converted_pages.values() for p in pages)
            write_manifest(
                backup_dir.parent / "updated_pdf_pages.txt", all_page_pdfs, "updated_pdf_pages"
            )
            write_manifest(
                backup_dir.parent / "updated_pdfs.txt", sorted(merged_pdfs), "updated_pdfs"
            )
        except Exception as exc:  # noqa: BLE001
            logging.error("Conversion error: %s", exc)
            print_error(f"  ERR - PDF conversion failed: {exc}")
            return 1
    else:
        print("\n[2/3] PDF conversion skipped (--skip-convert)")

    # ------------------------------------------------------------------
    # Stage 3: OCR + Markdown export
    # ------------------------------------------------------------------
    print("\n[3/3] Exporting to Markdown...")

    # Build OCR engine
    from ..ai import get_provider as get_ai_provider
    from ..hybrid_converter import find_notebooks, organize_notebooks_by_structure
    from ..ocr import OCREngine
    from ..pdf_md_converter import MarkdownExporter

    ocr_engine: Optional[OCREngine] = None
    if use_ai_ocr and ai_provider:
        try:
            kwargs: dict = {}
            if ai_model:
                kwargs["model"] = ai_model
            if ai_api_key:
                kwargs["api_key"] = ai_api_key
            provider = get_ai_provider(ai_provider, **kwargs)
            if provider.is_available():
                ocr_engine = OCREngine(ai_provider=provider, use_ai=True)
                print(f"  AI OCR provider: {ai_provider} ({provider.model})")
            else:
                print_warn(
                    f"  WRN - AI provider '{ai_provider}' not available "
                    "(missing API key or package). OCR skipped."
                )
        except (ValueError, ImportError) as exc:
            logging.warning("Could not initialise AI provider: %s", exc)
    elif use_ai_ocr:
        print_warn("  WRN - --use-ai-ocr set but no --ai-provider given. OCR skipped.")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else ["reMarkable"]

    exporter = MarkdownExporter(
        output_dir=output_dir,
        backup_dir=backup_dir,
        ocr_engine=ocr_engine,
        tags=tag_list,
        embed_images=embed_images,
    )

    # Discover notebooks and their folder paths
    all_items = find_notebooks(backup_dir)
    if not all_items:
        print("      No notebooks found in backup directory. Continuing to post-sync step.")

    org = organize_notebooks_by_structure(all_items, backup_dir)
    notebooks = org["documents_to_convert"]

    # Filter by selected folders from config
    if folder_filter:
        include_root = "(Root)" in folder_filter
        real_folders = [f for f in folder_filter if f != "(Root)"]
        notebooks = [
            nb
            for nb in notebooks
            if (include_root and not nb.get("folder_path", ""))
            or (nb.get("folder_path", "") and nb["folder_path"].split("/")[0] in real_folders)
        ]

    # Filter by notebook name/UUID if specified
    if notebook_filter:
        notebooks = [
            nb for nb in notebooks if nb["uuid"] == notebook_filter or nb["name"] == notebook_filter
        ]
        if not notebooks:
            print(f"  Notebook not found: {notebook_filter}")
            return 1

    # Filter to only notebooks that had PDFs generated in the pipeline
    if not force_export and converted_pages is not None:
        converted_uuids = set(converted_pages.keys())
        notebooks = [n for n in notebooks if n["uuid"] in converted_uuids]
    elif not force_export and updated_uuids is not None and not skip_backup:
        notebooks = [n for n in notebooks if n["uuid"] in updated_uuids]

    if not notebooks:
        print("  No notebooks to export — skipping")
        exported, skipped, exported_dirs = 0, 0, []
    else:
        exported, skipped, exported_dirs = exporter.export_all(
            notebooks=notebooks,
            pdf_output_dir=pdf_output_dir,
            force=force_export,
            converted_pages=converted_pages,
            page_filter=page_filter,
            updated_pages=updated_pages,
        )
        write_manifest(backup_dir.parent / "updated_md.txt", sorted(exported_dirs), "updated_md")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    elapsed = _time.monotonic() - _start_time
    mins, secs = divmod(int(elapsed), 60)

    print()
    print("=" * 70)
    print("  Sync Summary")
    print("=" * 70)
    if not skip_backup:
        print(f"  Backup     : {len(updated_uuids)} notebooks updated -> {backup_dir.absolute()}")
    else:
        print("  Backup     : skipped")
    if not skip_convert:
        print(
            f"  PDF        : {len(converted_pages or {})} notebooks converted -> {pdf_output_dir.absolute()}"
        )
    else:
        print("  PDF        : skipped")
    print(f"  Markdown   : {exported} exported, {skipped} unchanged -> {output_dir.absolute()}")
    print(f"  Duration   : {mins}m {secs}s")
    print("=" * 70)

    return 0
