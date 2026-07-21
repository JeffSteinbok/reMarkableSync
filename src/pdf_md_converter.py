"""Markdown exporter for RemarkableSync.

Converts backed-up ReMarkable notebooks into Markdown files, optionally
enriched with AI-transcribed handwriting text and embedded page-image
attachments.

Output structure (inside the output directory)::

    <output_dir>/
        <folder_path>/
            <notebook_name>.md          ← Markdown note
            <notebook_name>/
                page_001.png            ← page images (attachments)
                page_002.png
                ...
"""

import hashlib
import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .ocr.ocr_engine import OCREngine
from .utils import sanitize_name
from .utils.name_registry import NameRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _file_hash(path: Path) -> str:
    """Return the MD5 hex-digest of *path*."""
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Markdown exporter
# ---------------------------------------------------------------------------


class MarkdownExporter:
    """Export ReMarkable notebooks as Markdown notes."""

    def __init__(
        self,
        output_dir: Path,
        backup_dir: Path,
        ocr_engine: Optional[OCREngine] = None,
        tags: Optional[List[str]] = None,
        embed_images: bool = True,
        attachment_folder: str = "_images",
        registry: Optional[NameRegistry] = None,
    ):
        self.output_dir = output_dir
        self.backup_dir = backup_dir
        self.ocr_engine = ocr_engine
        self.tags = tags or ["remarkable"]
        self.embed_images = embed_images
        self.attachment_folder = attachment_folder or "_images"
        self.registry = registry

        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _get_content_page_order(notebook: Dict) -> Optional[List[str]]:
        """Return ordered page IDs from the notebook's .content file."""
        metadata_file = notebook.get("metadata_file")
        if not metadata_file:
            return None
        content_path = metadata_file.with_suffix(".content")
        if not content_path.exists():
            return None
        try:
            with open(content_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            page_ids = data.get("pages", [])
            if not page_ids:
                cpages = data.get("cPages", {}).get("pages", [])
                page_ids = [p["id"] for p in cpages if "id" in p]
            return page_ids if page_ids else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Page image export
    # ------------------------------------------------------------------

    def _export_page_images(
        self,
        pdf_path: Path,
        images_dir: Path,
    ) -> List[Path]:
        """Rasterise PDF pages and copy them into *images_dir/<attachment_folder>/*.

        Returns a list of paths suitable for embedded image links.
        """
        if not self.embed_images:
            return []
        if not pdf_path.exists():
            return []

        target_dir = images_dir / self.attachment_folder
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            from pdf2image import convert_from_path  # type: ignore

            pages = convert_from_path(str(pdf_path), dpi=150)
            image_paths: List[Path] = []
            for idx, page in enumerate(pages, start=1):
                dest = target_dir / f"page_{idx:03d}.png"
                page.save(str(dest), "PNG")
                image_paths.append(dest)
            return image_paths
        except ImportError:
            logging.debug("pdf2image not available – skipping page image export")
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to export page images from %s: %s", pdf_path.name, exc)

        return []

    # ------------------------------------------------------------------
    # Markdown building
    # ------------------------------------------------------------------

    @staticmethod
    def _build_frontmatter(
        notebook_name: str,
        notebook_uuid: str,
        folder_path: str,
        tags: List[str],
    ) -> str:
        """Return a YAML frontmatter block."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tag_lines = "\n".join(f"  - {t}" for t in tags)
        return (
            "---\n"
            f"title: {notebook_name}\n"
            f"source: reMarkable\n"
            f"remarkable_id: {notebook_uuid}\n"
            f"folder: {folder_path or '/'}\n"
            f"created: {now}\n"
            f"tags:\n"
            f"{tag_lines}\n"
            "---\n\n"
        )

    def _build_page_markdown(
        self,
        title: str,
        notebook_name: str,
        notebook_uuid: str,
        folder_path: str,
        page_num: int,
        page_text: str,
        page_image: Optional[Path] = None,
    ) -> str:
        """Build Markdown content for a single page."""
        lines: List[str] = []

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tag_lines = "\n".join(f"  - {t}" for t in self.tags)

        # Determine AI provider/model from OCR engine
        ai_provider = ""
        ai_model = ""
        if self.ocr_engine and self.ocr_engine.ai_provider:
            provider = self.ocr_engine.ai_provider
            ai_model = getattr(provider, "model", "")
            ai_provider = type(provider).__name__

        props = (
            "---\n"
            f'title: "{title}"\n'
            f"source: reMarkable\n"
            f"remarkable_id: {notebook_uuid}\n"
            f"notebook: {notebook_name}\n"
            f"folder: {folder_path or '/'}\n"
            f"page: {page_num}\n"
            f"created: {now}\n"
        )
        if ai_provider:
            props += f"ai_provider: {ai_provider}\n"
        if ai_model:
            props += f"ai_model: {ai_model}\n"
        props += f"tags:\n{tag_lines}\n---\n\n"
        lines.append(props)

        if page_text.strip():
            # Strip leading H1 if it matches the title (already in frontmatter)
            body = page_text.strip()
            first_line = body.split("\n", 1)[0].strip()
            if first_line.startswith("# ") and first_line[2:].strip().upper() == title.upper():
                body = body.split("\n", 1)[1].strip() if "\n" in body else ""
            if body:
                lines.append(body)
                lines.append("\n\n")

        if page_image and page_image.exists():
            link = f"{self.attachment_folder}/{page_image.name}"
            lines.append(f"![page {page_num}]({link})\n")

        return "".join(lines)

    @staticmethod
    def _extract_title(text: str, page_num: int) -> str:
        """Extract a title and optional date from OCR text.

        Returns format: ``YYYY-MM-DD - Title``, ``YYYY-MM-DD - Page N``,
        or ``Page N`` depending on what's found.
        """
        import re

        title = ""
        date_str = ""

        if text and text.strip():
            # Look for dates in common formats
            # Matches: 8/27/24, 08/27/2024, 2024-08-27, Aug 27, 2024, etc.
            date_patterns = [
                # YYYY-MM-DD
                (
                    r"(\d{4})-(\d{1,2})-(\d{1,2})",
                    lambda m: f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
                ),
                # M/D/YY or MM/DD/YY
                (
                    r"(\d{1,2})/(\d{1,2})/(\d{2})(?!\d)",
                    lambda m: f"20{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}",
                ),
                # M/D/YYYY or MM/DD/YYYY
                (
                    r"(\d{1,2})/(\d{1,2})/(\d{4})",
                    lambda m: f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}",
                ),
            ]
            for pattern, formatter in date_patterns:
                match = re.search(pattern, text)
                if match:
                    try:
                        date_str = formatter(match)
                    except (ValueError, IndexError):
                        pass
                    break

            # Look for title: first heading or first short non-empty line
            for line in text.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Skip lines that are just dates
                if re.match(r"^[_*]*\d{1,2}/\d{1,2}/\d{2,4}[_*]*$", line):
                    continue
                if re.match(r"^[_*]*\d{4}-\d{1,2}-\d{1,2}[_*]*$", line):
                    continue
                if line.startswith("#"):
                    candidate = line.lstrip("#").strip()
                    if candidate:
                        title = candidate
                        break
                elif len(line) < 80:
                    title = line
                    break

        # Build final title
        if date_str and title:
            return f"{date_str} - {title}"
        elif date_str:
            return date_str
        elif title:
            return title
        else:
            return ""

    # ------------------------------------------------------------------
    # Export entry point
    # ------------------------------------------------------------------

    def export_notebook(
        self,
        notebook: Dict,
        pdf_path: Path,
        force: bool = False,
        page_pdfs: Optional[List[Path]] = None,
        on_page_done: Optional[callable] = None,
        changed_page_ids: Optional[set] = None,
    ) -> Optional[Path]:
        """Export a notebook as a folder with one Markdown file per page.

        Args:
            notebook: Notebook metadata dict.
            pdf_path: Path to the converted PDF for this notebook.
            force: Re-export even if the notebook hasn't changed.
            page_pdfs: Optional list of cached per-page PDF paths.
            on_page_done: Callback ``(page_num, total_pages, cached=False)``
                called after each page is processed.  *cached* is True when
                the page was skipped because its PDF hash was unchanged.
            changed_page_ids: Set of page IDs (UUID stems) known to have
                changed in the backup.  When provided, pages in this set
                are always re-exported regardless of hash state.

        Returns:
            Path to the notebook folder, or *None* on failure.
        """
        uuid = notebook["uuid"]
        name = notebook["name"]
        folder_path = notebook.get("folder_path", "")

        safe = sanitize_name(name) or f"notebook_{uuid[:8]}"

        # Notebook becomes a folder
        notebook_dir = self.output_dir
        if folder_path:
            for segment in folder_path.split("/"):
                notebook_dir = notebook_dir / sanitize_name(segment)
        notebook_dir = notebook_dir / safe
        notebook_dir.mkdir(parents=True, exist_ok=True)

        # Determine pages to process
        pages_to_process: List[Path] = []
        if page_pdfs:
            pages_to_process = [p for p in page_pdfs if p.exists()]
        elif pdf_path.exists():
            pages_to_process = [pdf_path]

        if not pages_to_process:
            logging.warning("No PDFs found for notebook '%s'", name)
            return None

        total_pages = len(pages_to_process)

        with tempfile.TemporaryDirectory(prefix="rs_md_") as tmp_str:
            tmp_dir = Path(tmp_str)
            rate_limited = False

            for pg_idx, pg_pdf in enumerate(pages_to_process, start=1):
                # Skip pages that haven't changed
                if (
                    not force
                    and changed_page_ids is not None
                    and pg_pdf.stem not in changed_page_ids
                ):
                    logging.debug("Skipping unchanged page %d of '%s'", pg_idx, name)
                    if on_page_done:
                        on_page_done(pg_idx, total_pages, cached=True)
                    continue

                # Rasterise page to image
                page_image: Optional[Path] = None
                page_images: List[Path] = []  # noqa: F841

                if self.embed_images:
                    images_dir = notebook_dir / self.attachment_folder
                    images_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        import fitz  # PyMuPDF

                        doc = fitz.open(str(pg_pdf))
                        for fitz_page in doc:
                            pix = fitz_page.get_pixmap(dpi=150)
                            dest = images_dir / f"page_{pg_idx:03d}.png"
                            pix.save(str(dest))
                            page_image = dest
                        doc.close()
                    except ImportError:
                        pass
                    except Exception as exc:
                        logging.warning("Image export failed for page %d: %s", pg_idx, exc)

                # OCR this page
                page_text = ""
                ocr_failed = False
                if self.ocr_engine and not rate_limited:
                    from src.ai.base_provider import AIProviderError, AIRateLimitError
                    from src.utils.console import print_error, print_warn

                    raster_images = self.ocr_engine.pdf_to_images(
                        pg_pdf, tmp_dir / f"ocr_page_{pg_idx:03d}"
                    )
                    if raster_images and self.ocr_engine.use_ai and self.ocr_engine.ai_provider:
                        try:
                            raw = self.ocr_engine.ai_provider.transcribe_handwriting(
                                raster_images, context=f"{name} (page {pg_idx})"
                            )
                            if raw:
                                page_text = self.ocr_engine.ai_provider.cleanup_text(
                                    raw, context=f"{name} (page {pg_idx})"
                                )
                        except AIRateLimitError as exc:
                            wait_min = (exc.retry_after + 59) // 60
                            logging.warning("Rate limited for '%s' page %d: %s", name, pg_idx, exc)
                            print_warn(
                                f"  WRN - Rate limited — retry in ~{wait_min} min. "
                                f"Skipping OCR for remaining pages."
                            )
                            rate_limited = True
                            ocr_failed = True
                        except AIProviderError as exc:
                            logging.error("OCR failed for '%s' page %d: %s", name, pg_idx, exc)
                            print_error(f"  ERR - OCR failed for '{name}' page {pg_idx}")
                            ocr_failed = True

                if ocr_failed:
                    if on_page_done:
                        on_page_done(pg_idx, total_pages)
                    continue

                # Derive title from OCR text
                title = self._extract_title(page_text, pg_idx)
                safe_title = sanitize_name(title)

                # Build and write per-page Markdown
                md_content = self._build_page_markdown(
                    title=title or f"Page {pg_idx}",
                    notebook_name=name,
                    notebook_uuid=uuid,
                    folder_path=folder_path,
                    page_num=pg_idx,
                    page_text=page_text,
                    page_image=page_image,
                )

                if safe_title:
                    md_path = notebook_dir / f"{pg_idx:03d} - {safe_title}.md"
                else:
                    md_path = notebook_dir / f"{pg_idx:03d}.md"
                try:
                    with open(md_path, "w", encoding="utf-8") as fh:
                        fh.write(md_content)
                except OSError as exc:
                    logging.error("Failed to write page %d of '%s': %s", pg_idx, name, exc)

                if on_page_done:
                    on_page_done(pg_idx, total_pages)

        logging.info("Exported notebook: %s (%d pages)", name, total_pages)
        return notebook_dir

    def export_all(
        self,
        notebooks: List[Dict],
        pdf_output_dir: Path,
        force: bool = False,
        converted_pages: Optional[Dict[str, List[Path]]] = None,
        page_filter: Optional[int] = None,
        updated_pages: Optional[Dict[str, set]] = None,
    ) -> Tuple[int, int, List[Path]]:
        """Export all notebooks to Markdown.

        Args:
            notebooks: List of notebook metadata dicts.
            pdf_output_dir: Directory containing the converted PDFs (mirrors
                the folder hierarchy).
            force: Re-export all notebooks regardless of change status.
            converted_pages: Dict mapping notebook UUID to list of per-page
                PDF paths produced by the PDF conversion step.  When provided,
                these are used directly instead of scanning the cache dir.
            updated_pages: Dict mapping notebook UUID to set of changed page
                IDs from the backup stage.

        Returns:
            ``(exported_count, skipped_count, exported_dirs)`` tuple where
            *exported_dirs* lists the notebook output directories that were written.
        """
        from .utils.console import create_progress

        exported = 0
        skipped = 0
        exported_dirs: List[Path] = []
        doc_notebooks = [nb for nb in notebooks if nb.get("type") == "DocumentType"]

        # Count total pages for progress bar
        total_pages = 0
        nb_page_counts = []
        # Count total pages that actually need OCR processing
        total_ocr_pages = 0
        for nb in doc_notebooks:
            count = 0
            if converted_pages and nb["uuid"] in converted_pages:
                count = len(converted_pages[nb["uuid"]])
            else:
                cache = self.backup_dir / "PagePDFs" / nb["uuid"]
                if cache.exists():
                    count = len([p for p in cache.glob("*.pdf") if not p.stem.endswith("_content")])
            count = max(count, 1)
            nb_page_counts.append(count)
            total_pages += count

            # Count only pages that will actually be processed
            nb_changed = None
            if updated_pages is not None:
                nb_changed = updated_pages.get(nb["uuid"], set())
            if nb_changed is not None and converted_pages and nb["uuid"] in converted_pages:
                total_ocr_pages += sum(
                    1 for p in converted_pages[nb["uuid"]] if p.stem in nb_changed
                )
            else:
                total_ocr_pages += count

        ocr_counter = [0]

        with create_progress("Exporting") as progress:
            task = progress.add_task("Exporting", total=total_pages)

            for i, notebook in enumerate(doc_notebooks):
                nb_name = notebook["name"][:30]
                nb_pages = nb_page_counts[i]
                progress.update(
                    task,
                    description=f"{nb_name} (page 1 of {nb_pages})",
                )

                safe = sanitize_name(notebook["name"]) or f"notebook_{notebook['uuid'][:8]}"
                folder_path = notebook.get("folder_path", "")

                # Locate the PDF produced by the converter
                pdf_dir = pdf_output_dir
                if folder_path:
                    for seg in folder_path.split("/"):
                        pdf_dir = pdf_dir / sanitize_name(seg)
                pdf_path = pdf_dir / f"{safe}.pdf"

                # Use page PDFs from pipeline if available, else scan cache
                page_pdfs_list: Optional[List[Path]] = None
                if converted_pages and notebook["uuid"] in converted_pages:
                    page_pdfs_list = converted_pages[notebook["uuid"]]
                else:
                    page_cache_dir = self.backup_dir / "PagePDFs" / notebook["uuid"]
                    if page_cache_dir.exists():
                        pdfs_on_disk = {
                            p.stem: p
                            for p in page_cache_dir.glob("*.pdf")
                            if not p.stem.endswith("_content")
                        }
                        if pdfs_on_disk:
                            # Order by .content file if available
                            ordered = self._get_content_page_order(notebook)
                            if ordered:
                                page_pdfs_list = [
                                    pdfs_on_disk[pid] for pid in ordered if pid in pdfs_on_disk
                                ]
                            else:
                                page_pdfs_list = sorted(pdfs_on_disk.values())

                # Filter to specific page if requested
                if page_filter and page_pdfs_list:
                    if page_filter <= len(page_pdfs_list):
                        page_pdfs_list = [page_pdfs_list[page_filter - 1]]
                    else:
                        logging.warning(
                            "Page %d not found (notebook has %d pages)",
                            page_filter,
                            len(page_pdfs_list),
                        )

                def _on_page(
                    pg_num,
                    pg_total,
                    _nb_name=nb_name,
                    _oc=ocr_counter,
                    _total_ocr=total_ocr_pages,
                    cached=False,
                ):
                    if cached:
                        logging.info("MD: %s (page %d/%d) [cached]", _nb_name, pg_num, pg_total)
                    else:
                        _oc[0] += 1
                        desc = f"OCR page {_oc[0]} of {_total_ocr} ({_nb_name} page {pg_num})"
                        progress.update(task, advance=1, description=desc)
                        logging.info(
                            "MD: OCR page %d of %d (%s page %d)",
                            _oc[0],
                            _total_ocr,
                            _nb_name,
                            pg_num,
                        )

                nb_changed_pages = None
                if updated_pages and notebook["uuid"] in updated_pages:
                    nb_changed_pages = updated_pages[notebook["uuid"]]

                result = self.export_notebook(
                    notebook,
                    pdf_path,
                    force=force,
                    page_pdfs=page_pdfs_list,
                    on_page_done=_on_page,
                    changed_page_ids=nb_changed_pages,
                )
                # Ensure we advance the full count even if pages were fewer
                remaining = nb_pages - (nb_pages if result else 0)
                if remaining > 0:
                    progress.update(task, advance=remaining)

                if result:
                    exported += 1
                    exported_dirs.append(result)
                else:
                    skipped += 1

        logging.info("Markdown export complete: %d exported, %d skipped", exported, skipped)
        return exported, skipped, exported_dirs
