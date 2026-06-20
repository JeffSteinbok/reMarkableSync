"""
Hybrid ReMarkable PDF Converter - Internal Module

This is a helper module providing core conversion functionality.
Do not run directly - use the main RemarkableSync entry point instead.

Entry Point:
    RemarkableSync.py convert [OPTIONS]

This module provides:
- Automatic file version detection by reading .rm file headers
- Batch conversion with progress tracking
- Folder structure preservation matching ReMarkable organization
- PDF merging to create single documents from multi-page notebooks
- Support for v5 format files (rmrl) and v6 format files (rmc)
- Detection and reporting for v4/v3 files (limited support)
"""

import hashlib
import json
import logging
import shutil
import tempfile
import warnings
from pathlib import Path
from typing import Dict, List, Optional

# Import modular converter classes and registry
from .converters import ConverterRegistry, get_default_registry
from .template_renderer import TemplateRenderer
from .utils import sanitize_name

# Suppress warnings from third-party libraries to reduce output noise
warnings.filterwarnings("ignore")


def _hash_file(path: Path) -> str:
    """Return MD5 hex-digest of *path*, or empty string if it doesn't exist."""
    if not path.exists():
        return ""
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def setup_logging(verbose: bool = False):
    """Configure logging with appropriate levels and formatting.

    Sets up logging with timestamp formatting and suppresses verbose
    output from third-party libraries (svglib, reportlab) that can
    clutter the console during PDF conversion.

    Args:
        verbose: Enable DEBUG level logging if True, INFO level if False
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Suppress verbose debug messages from svglib that clutter the output
    logging.getLogger("svglib.svglib").setLevel(logging.WARNING)
    logging.getLogger("reportlab").setLevel(logging.WARNING)


def find_notebooks(backup_dir: Path) -> List[Dict]:
    """Find and parse notebook metadata from backup directory.

    Scans the backup directory for .metadata files and analyzes associated
    .rm files to classify them by version for appropriate conversion tools.

    File Version Detection:
    - Reads the first 8 bytes of each .rm file to detect format version
    - version=5: Uses rmrl library (legacy format)
    - version=6: Uses rmc library (current format)
    - version=4: Detected but limited support (attempts rmrl fallback)
    - version=3: Detected but no conversion support

    Args:
        backup_dir: Path to the ReMarkable backup directory

    Returns:
        List of dictionaries containing notebook information:
        - uuid: Unique identifier for the notebook
        - name: Display name of the notebook
        - type: DocumentType or CollectionType (folder)
        - parent: UUID of parent folder (empty if root level)
        - metadata_file: Path to the .metadata file
        - rm_files: List of all .rm files for this notebook
        - v5_files, v6_files, v4_files, v3_files: Files categorized by version
        - pdf_files: Any existing PDF files in the notebook directory
    """
    notebooks: List[Dict] = []
    files_dir = backup_dir / "Notebooks"

    if not files_dir.exists():
        logging.error(f"Backup files directory not found: {files_dir}")
        return []

    for metadata_file in files_dir.glob("*.metadata"):
        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            uuid = metadata_file.stem
            notebook_type = metadata.get("type", "unknown")

            if notebook_type in ["CollectionType", "DocumentType"]:
                notebook_info: Dict = {
                    "uuid": uuid,
                    "name": metadata.get("visibleName", "Untitled"),
                    "type": notebook_type,
                    "parent": metadata.get("parent", ""),
                    "metadata_file": metadata_file,
                    "rm_files": list(files_dir.glob(f"{uuid}/*.rm")),
                    "pdf_files": list(files_dir.glob(f"{uuid}/*.pdf")),
                }

                # Analyze file versions
                notebook_info["v5_files"] = []
                notebook_info["v6_files"] = []
                notebook_info["v4_files"] = []
                notebook_info["v3_files"] = []

                for rm_file in notebook_info["rm_files"]:
                    try:
                        # Read file header to determine version format
                        # Each .rm file starts with a version identifier in ASCII
                        with open(rm_file, "rb") as f:
                            header = f.read(50).decode("ascii", errors="ignore")
                            # Classify files by version for appropriate conversion tool
                            if "version=6" in header:
                                notebook_info["v6_files"].append(rm_file)
                            elif "version=5" in header:
                                notebook_info["v5_files"].append(rm_file)
                            elif "version=4" in header:
                                notebook_info["v4_files"].append(rm_file)
                            elif "version=3" in header:
                                notebook_info["v3_files"].append(rm_file)
                    except Exception:
                        # Ignore files that can't be read or don't have valid headers
                        pass

                # Include in conversion list if it's a folder or has convertible content
                # - CollectionType: Folders (included for directory structure)
                # - Documents with any version of .rm files or existing PDFs
                if (
                    notebook_type == "CollectionType"
                    or notebook_info["v5_files"]
                    or notebook_info["v6_files"]
                    or notebook_info["v4_files"]
                    or notebook_info["v3_files"]
                    or notebook_info["pdf_files"]
                ):
                    notebooks.append(notebook_info)

        except Exception as e:  # noqa: BLE001
            logging.warning(f"Failed to parse {metadata_file}: {e}")

    return notebooks


def svg_to_pdf(
    svg_file: Path,
    pdf_file: Path,
    registry: Optional[ConverterRegistry] = None,
) -> bool:
    """Convert SVG to PDF using modular converter utilities.

    This is a wrapper function that maintains backward compatibility
    while using the new modular converter architecture.

    Args:
        svg_file: Path to input SVG file
        pdf_file: Path to output PDF file
        registry: Optional converter registry (uses default if not provided)

    Returns:
        bool: True if conversion successful, False otherwise
    """
    reg = registry or get_default_registry()
    # Use the v6 converter for utility methods (they're in the base class)
    converter = reg.get_for_version(6)
    if converter is None:
        return False
    return converter.svg_to_pdf(svg_file, pdf_file)


def merge_pdf_with_template(
    content_pdf: Path, template_pdf: Optional[Path], output_pdf: Path
) -> bool:
    """Merge a content PDF with a template background PDF.

    Args:
        content_pdf: Path to PDF with notebook content
        template_pdf: Path to PDF with template background (None for no template)
        output_pdf: Path where merged PDF should be saved

    Returns:
        bool: True if merge successful, False otherwise
    """
    try:
        from PyPDF2 import PdfReader, PdfWriter
        from PyPDF2.generic import DecodedStreamObject, NameObject

        if not content_pdf.exists():
            return False

        content_reader = PdfReader(str(content_pdf))
        writer = PdfWriter()

        # If we have a template, merge it with the content
        if template_pdf and template_pdf.exists():
            template_reader = PdfReader(str(template_pdf))
            if len(template_reader.pages) > 0:
                # Get template content stream once
                template_page = template_reader.pages[0]
                template_stream = template_page["/Contents"].get_object().get_data()

                for content_page in content_reader.pages:
                    # Prepend template drawing (wrapped in q/Q to isolate
                    # graphics state) before the content stream. This avoids
                    # PyPDF2's merge_page which can produce corrupt PDFs
                    # when combining pages with conflicting font resources.
                    content_stream = content_page["/Contents"].get_object().get_data()
                    combined = b"q\n" + template_stream + b"\nQ\n" + content_stream
                    new_stream = DecodedStreamObject()
                    new_stream.set_data(combined)
                    content_page[NameObject("/Contents")] = new_stream
                    writer.add_page(content_page)
            else:
                # No template pages, just copy content
                for page in content_reader.pages:
                    writer.add_page(page)
        else:
            # No template, just copy content
            for page in content_reader.pages:
                writer.add_page(page)

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        with open(output_pdf, "wb") as f:
            writer.write(f)

        return output_pdf.exists() and output_pdf.stat().st_size > 0

    except Exception as e:
        logging.debug(f"PDF template merge failed: {e}")
        return False


def merge_pdfs(pdf_files: List[Path], output_file: Path) -> bool:
    """Merge multiple PDF files into a single PDF document.

    Takes a list of individual page PDFs and combines them into
    a single multi-page PDF document, maintaining page order.

    Args:
        pdf_files: List of PDF file paths to merge (in order)
        output_file: Path where merged PDF should be saved

    Returns:
        bool: True if merge successful, False otherwise

    Note:
        Uses PyPDF2 for PDF manipulation. Creates parent directories
        if they don't exist.
    """
    try:
        from PyPDF2 import PdfReader, PdfWriter

        writer = PdfWriter()

        for pdf_file in pdf_files:
            if pdf_file.exists():
                reader = PdfReader(str(pdf_file))
                for page in reader.pages:
                    writer.add_page(page)

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "wb") as f:
            writer.write(f)

        return output_file.exists() and output_file.stat().st_size > 0

    except Exception as e:
        logging.debug(f"PDF merge failed: {e}")
        return False


def organize_notebooks_by_structure(notebooks: List[Dict], backup_dir: Path) -> Dict:
    """Organize notebooks into their folder structure for conversion.

    Analyzes the parent-child relationships between notebooks and folders
    to recreate the ReMarkable folder structure in the output directory.
    This ensures PDFs are organized the same way as on the device.

    Args:
        notebooks: List of notebook dictionaries from find_notebooks()
        backup_dir: Path to backup directory (used for hierarchy resolution)

    Returns:
        Dictionary with:
        - 'documents': List of document notebooks to convert
        - 'structure': Dict mapping folder paths to lists of notebooks

    Note:
        Folder hierarchy is determined by following parent UUIDs up
        to the root level, creating folder paths like "Work/Projects/Notes"
    """
    # Build folder structure
    folder_structure = {}
    documents_to_convert = []

    for item in notebooks:
        if item["type"] == "DocumentType":
            hierarchy = get_folder_hierarchy(item, backup_dir)
            item["folder_path"] = "/".join(name for name, _ in hierarchy)
            item["folder_hierarchy"] = hierarchy
            documents_to_convert.append(item)

            folder_path = item["folder_path"]
            if folder_path not in folder_structure:
                folder_structure[folder_path] = []
            folder_structure[folder_path].append(item)

    return {"folder_structure": folder_structure, "documents_to_convert": documents_to_convert}


def get_folder_hierarchy(notebook: Dict, backup_dir: Path) -> List[tuple]:
    """Get the folder hierarchy for a notebook by following parent UUIDs.

    Returns a list of ``(raw_name, uuid)`` tuples ordered from root to
    immediate parent, e.g. ``[("1:1", "abc..."), ("L65+", "def...")]``.
    """
    hierarchy = []
    current_uuid = notebook.get("parent")
    files_dir = backup_dir / "Notebooks"

    while current_uuid and current_uuid != "":
        try:
            metadata_file = files_dir / f"{current_uuid}.metadata"
            if metadata_file.exists():
                with open(metadata_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                folder_name = metadata.get("visibleName", "Unknown")
                if folder_name:
                    hierarchy.insert(0, (folder_name, current_uuid))
                current_uuid = metadata.get("parent")
            else:
                break
        except Exception as e:
            logging.debug(f"Failed to read parent metadata for {current_uuid}: {e}")
            break

    return hierarchy


def convert_v6_file_with_rmc(
    rm_file: Path,
    output_file: Path,
    registry: Optional[ConverterRegistry] = None,
) -> bool:
    """Convert v6 format .rm file to PDF using modular V6Converter.

    This is a wrapper function that maintains backward compatibility
    while using the new modular converter architecture.

    Args:
        rm_file: Path to the v6 format .rm file
        output_file: Path where PDF should be saved
        registry: Optional converter registry (uses default if not provided)

    Returns:
        bool: True if conversion successful, False otherwise
    """
    reg = registry or get_default_registry()
    converter = reg.get_for_version(6)
    if converter is None:
        return False
    return converter.convert_to_pdf(rm_file, output_file)


def convert_v5_file_with_rmrl(
    rm_file: Path,
    output_file: Path,
    registry: Optional[ConverterRegistry] = None,
) -> bool:
    """Convert v5 format .rm file to PDF using modular V5Converter.

    This is a wrapper function that maintains backward compatibility
    while using the new modular converter architecture.

    Args:
        rm_file: Path to the v5 format .rm file
        output_file: Path where PDF should be saved
        registry: Optional converter registry (uses default if not provided)

    Returns:
        bool: True if conversion successful, False otherwise
    """
    reg = registry or get_default_registry()
    converter = reg.get_for_version(5)
    if converter is None:
        return False
    return converter.convert_to_pdf(rm_file, output_file)


def convert_v4_file_with_rmrl(
    rm_file: Path,
    output_file: Path,
    registry: Optional[ConverterRegistry] = None,
) -> bool:
    """Convert v4 format .rm file to PDF using modular V4Converter.

    This is a wrapper function that maintains backward compatibility
    while using the new modular converter architecture.

    Args:
        rm_file: Path to the v4 format .rm file
        output_file: Path where PDF should be saved
        registry: Optional converter registry (uses default if not provided)

    Returns:
        bool: True if conversion successful, False otherwise

    Note:
        v4 format support is limited and may fail for many files.
    """
    reg = registry or get_default_registry()
    converter = reg.get_for_version(4)
    if converter is None:
        return False
    return converter.convert_to_pdf(rm_file, output_file)


def copy_existing_pdf(
    pdf_file: Path,
    output_file: Path,
    registry: Optional[ConverterRegistry] = None,
) -> bool:
    """Copy existing PDF file using base converter utility.

    This is a wrapper function that maintains backward compatibility
    while using the modular converter architecture.

    Args:
        pdf_file: Path to the source PDF file
        output_file: Path where PDF should be copied
        registry: Optional converter registry (uses default if not provided)

    Returns:
        bool: True if copy successful, False otherwise
    """
    reg = registry or get_default_registry()
    # Use the v6 converter for utility methods (they're in the base class)
    converter = reg.get_for_version(6)
    if converter is None:
        return False
    return converter.copy_existing_pdf(pdf_file, output_file)


def get_page_templates(content_file: Path) -> Dict[str, str]:
    """Extract template names for each page from .content file.

    Args:
        content_file: Path to the .content JSON file

    Returns:
        Dictionary mapping page IDs to template names
    """
    page_templates = {}

    if not content_file or not content_file.exists():
        return page_templates

    try:
        with open(content_file, "r", encoding="utf-8") as f:
            content_data = json.load(f)

        # Extract pages from cPages structure
        c_pages = content_data.get("cPages", {})
        pages = c_pages.get("pages", [])

        for page in pages:
            page_id = page.get("id")
            template_info = page.get("template", {})
            template_name = template_info.get("value", "Blank")

            if page_id:
                page_templates[page_id] = template_name

    except Exception as e:
        logging.debug(f"Failed to extract page templates from {content_file}: {e}")

    return page_templates


def convert_notebook(
    notebook: Dict,
    output_dir: Path,
    backup_dir: Path,
    template_renderer: Optional[TemplateRenderer] = None,
    changed_page_ids: Optional[set] = None,
    on_page_done: Optional[callable] = None,
    on_page_start: Optional[callable] = None,
    registry=None,
) -> Dict:
    """Convert a notebook using appropriate tools for each file type.

    Creates a single PDF per notebook with all pages merged together.
    Per-page PDFs are cached in ``backup_dir/PagePDFs/<uuid>/`` so that
    only pages whose ``.rm`` source changed need to be re-converted.
    The cached page PDFs are also available for downstream consumers
    like the OCR engine.

    Args:
        notebook: Notebook metadata dict from :func:`find_notebooks`.
        output_dir: Root directory for final merged PDFs.
        backup_dir: RemarkableSync backup root directory.
        template_renderer: Optional template renderer for backgrounds.
        changed_page_ids: Set of page IDs whose ``.rm`` files changed.
            When *None* all pages are (re-)converted.
        on_page_done: Callback ``(cached: bool)`` called after each page.
            *cached* is True when the page was served from cache.
        registry: Optional :class:`~src.utils.name_registry.NameRegistry`
            for stable, deduplicated output path names.
    """
    # Build output directory using registry if available, else plain sanitize
    hierarchy = notebook.get("folder_hierarchy", [])
    output_notebook_dir = output_dir
    if registry:
        for i, (folder_name, folder_uuid) in enumerate(hierarchy):
            parent_uuid = hierarchy[i - 1][1] if i > 0 else ""
            output_notebook_dir = output_notebook_dir / registry.get_or_assign(
                folder_uuid, folder_name, parent_uuid
            )
        parent_uuid = hierarchy[-1][1] if hierarchy else ""
        safe_name = registry.get_or_assign(notebook["uuid"], notebook["name"], parent_uuid)
    else:
        for folder_name, _ in hierarchy:
            output_notebook_dir = output_notebook_dir / sanitize_name(folder_name)
        safe_name = sanitize_name(notebook["name"]) or f"notebook_{notebook['uuid'][:8]}"

    output_notebook_dir.mkdir(parents=True, exist_ok=True)

    # Persistent page PDF cache directory
    page_cache_dir = backup_dir / "PagePDFs" / notebook["uuid"]
    page_cache_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "name": notebook["name"],
        "folder_path": str(output_notebook_dir.relative_to(output_dir)) if hierarchy else "",
        "page_cache_dir": page_cache_dir,
        "v5_converted": 0,
        "v6_converted": 0,
        "v4_converted": 0,
        "pdfs_copied": 0,
        "v4_detected": len(notebook.get("v4_files", [])),
        "v3_detected": len(notebook.get("v3_files", [])),
        "total_files": 0,
        "output_files": [],
    }

    # Collect all PDF pages to merge (in order)
    page_pdfs = []

    # Template temp dir (still ephemeral — templates are cheap to render)
    template_temp_dir = None
    if template_renderer:
        template_temp_dir = Path(tempfile.mkdtemp(prefix="remarkable_templates_"))

    try:
        # Resolve ordered pages using .content file if present
        metadata_file = notebook.get("metadata_file")
        content_path = metadata_file.with_suffix(".content") if metadata_file else None

        # Extract page templates from content file
        page_templates = {}
        if template_renderer and content_path:
            page_templates = get_page_templates(content_path)

        # Build a set of all known .rm files by page ID for fast lookup
        all_rm_by_id: Dict[str, Path] = {}
        for rm_file in (
            notebook.get("v5_files", [])
            + notebook.get("v6_files", [])
            + notebook.get("v4_files", [])
        ):
            all_rm_by_id[rm_file.stem] = rm_file

        # Determine version for each page
        v6_ids = {f.stem for f in notebook.get("v6_files", [])}
        v4_ids = {f.stem for f in notebook.get("v4_files", [])}

        # Order pages using .content file (applies to all versions)
        ordered_pages: List[Path] = []
        if content_path and content_path.exists():
            try:
                with open(content_path, "r", encoding="utf-8") as cf:
                    content_json = json.load(cf)
                page_ids = content_json.get("pages", [])
                # v6 notebooks use cPages.pages with {id, idx, ...} dicts
                if not page_ids:
                    cpages = content_json.get("cPages", {}).get("pages", [])
                    page_ids = [p["id"] for p in cpages if "id" in p]
                base_dir = content_path.parent / content_path.stem
                for pid in page_ids:
                    if pid in all_rm_by_id:
                        ordered_pages.append(all_rm_by_id[pid])
                    else:
                        candidate = base_dir / f"{pid}.rm"
                        if candidate.exists():
                            ordered_pages.append(candidate)
                        else:
                            alt = list((content_path.parent).glob(f"{pid}.rm"))
                            if alt:
                                ordered_pages.append(alt[0])
            except Exception as e:
                logging.debug("Failed reading content ordering for %s: %s", notebook["name"], e)

        # Fallback to unsorted list if ordering extraction failed
        if not ordered_pages:
            ordered_pages = (
                notebook.get("v5_files", [])
                + notebook.get("v6_files", [])
                + notebook.get("v4_files", [])
            )

        def _needs_conversion(page_id: str) -> bool:
            """Check if a page needs (re-)conversion."""
            if changed_page_ids is None:
                return True  # No change info → convert all
            return page_id in changed_page_ids

        def _convert_page(rm_file: Path, version_tag: str, convert_fn, result_key: str) -> tuple:
            """Convert a single page, using cache when possible.

            Returns ``(path, cached)`` where *cached* is True when the
            page was served from the persistent cache without conversion.
            Returns ``(None, False)`` on failure.
            """
            page_id = rm_file.stem
            cached_pdf = page_cache_dir / f"{page_id}.pdf"

            # Use cached PDF if page hasn't changed
            if not _needs_conversion(page_id) and cached_pdf.exists():
                return cached_pdf, True

            # Convert the .rm file to a content PDF
            content_pdf = page_cache_dir / f"{page_id}_content.pdf"
            if not convert_fn(rm_file, content_pdf):
                return None, False

            # Apply template if available
            if template_renderer and template_temp_dir:
                template_name = page_templates.get(page_id, "Blank")
                if template_name and template_name != "Blank":
                    temp_template_pdf = template_temp_dir / f"template_{page_id}.pdf"

                    # Read the actual content page dimensions so the template
                    # pattern covers the full page — including extended/long pages
                    # where the content height exceeds the standard ReMarkable size.
                    page_height = None
                    page_width = None
                    try:
                        from PyPDF2 import PdfReader

                        content_reader = PdfReader(str(content_pdf))
                        if content_reader.pages:
                            content_page = content_reader.pages[0]
                            page_height = float(content_page.mediabox.height)
                            page_width = float(content_page.mediabox.width)
                    except Exception:
                        pass

                    if template_renderer.render_template_to_pdf(
                        template_name,
                        temp_template_pdf,
                        page_height=page_height,
                        page_width=page_width,
                    ):
                        if merge_pdf_with_template(content_pdf, temp_template_pdf, cached_pdf):
                            # Clean up intermediate content PDF
                            try:
                                content_pdf.unlink(missing_ok=True)
                            except OSError:
                                pass
                            results[result_key] += 1
                            return cached_pdf, False

            # No template or template merge failed — content PDF is the final
            if content_pdf != cached_pdf:
                try:
                    shutil.copy2(content_pdf, cached_pdf)
                    content_pdf.unlink(missing_ok=True)
                except OSError:
                    cached_pdf = content_pdf
            results[result_key] += 1
            return cached_pdf, False

        # Convert all pages in content-file order
        for rm_file in ordered_pages:
            page_id = rm_file.stem
            if on_page_start:
                on_page_start()
            if page_id in v6_ids:
                pdf, cached = _convert_page(rm_file, "v6", convert_v6_file_with_rmc, "v6_converted")
            elif page_id in v4_ids:
                pdf, cached = _convert_page(
                    rm_file, "v4", convert_v4_file_with_rmrl, "v4_converted"
                )
            else:
                pdf, cached = _convert_page(
                    rm_file, "v5", convert_v5_file_with_rmrl, "v5_converted"
                )
            if pdf:
                page_pdfs.append(pdf)
            if on_page_done:
                on_page_done(cached=cached)

        # Copy existing PDFs
        for i, pdf_file in enumerate(notebook["pdf_files"]):
            if on_page_start:
                on_page_start()
            cached_pdf = page_cache_dir / f"existing_{i+1:03d}.pdf"
            was_cached = False
            if not cached_pdf.exists() or changed_page_ids is None:
                if copy_existing_pdf(pdf_file, cached_pdf):
                    page_pdfs.append(cached_pdf)
                    results["pdfs_copied"] += 1
            else:
                page_pdfs.append(cached_pdf)
                results["pdfs_copied"] += 1
                was_cached = True
            if on_page_done:
                on_page_done(cached=was_cached)

        # Store ordered page PDFs in results for downstream consumers
        results["page_pdfs"] = list(page_pdfs)

        # Create merged PDF if we have any pages
        if page_pdfs:
            final_pdf = output_notebook_dir / f"{safe_name}.pdf"
            pre_merge_hash = _hash_file(final_pdf)

            if merge_pdfs(page_pdfs, final_pdf):
                results["output_files"].append(final_pdf)
                results["pdf_changed"] = _hash_file(final_pdf) != pre_merge_hash
                logging.info(
                    f"OK - {notebook['name']}: Merged {len(page_pdfs)} pages into {final_pdf.name}"
                )
            else:
                logging.warning(
                    f"[FAIL] {notebook['name']}: Failed to merge {len(page_pdfs)} pages"
                )

        results["total_files"] = (
            len(notebook["v5_files"])
            + len(notebook["v6_files"])
            + len(notebook.get("v4_files", []))
            + len(notebook.get("v3_files", []))
            + len(notebook["pdf_files"])
        )

        # Unsupported versions note
        if results["v4_detected"] or results["v3_detected"]:
            unsupported_info = output_notebook_dir / f"{safe_name}_unsupported.txt"
            try:
                with open(unsupported_info, "w", encoding="utf-8") as f:
                    f.write(f"Notebook: {notebook['name']}\n")
                    f.write(f"UUID: {notebook['uuid']}\n\n")
                    f.write("Detected unsupported .rm versions:\n")
                    if results["v4_detected"]:
                        f.write(
                            f"  - v4 pages: {results['v4_detected']} (no converter implemented yet)\n"
                        )
                    if results["v3_detected"]:
                        f.write(f"  - v3 pages: {results['v3_detected']} (legacy format)\n")
                    f.write(
                        "\nSuggestion: Keep these files; future tooling or an older firmware converter may be needed.\n"
                    )
                results["output_files"].append(unsupported_info)
            except Exception as e:
                logging.debug("Could not write unsupported info for %s: %s", notebook["name"], e)

    finally:
        # Clean up template temp dir only (page PDFs are persistent cache)
        try:
            if template_temp_dir and template_temp_dir.exists():
                shutil.rmtree(template_temp_dir, ignore_errors=True)
        except Exception as e:
            logging.debug(f"Cleanup error: {e}")

    return results
