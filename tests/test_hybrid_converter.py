"""Tests for the hybrid_converter module (notebook discovery and organization)."""

import json
from pathlib import Path

import pytest

from src.hybrid_converter import (
    _hash_file,
    copy_existing_pdf,
    find_notebooks,
    get_folder_hierarchy,
    get_page_templates,
    merge_pdfs,
    organize_notebooks_by_structure,
)


def _write_metadata(files_dir: Path, uuid: str, name: str, ntype: str, parent: str = ""):
    """Helper to write a .metadata file."""
    meta = {
        "visibleName": name,
        "type": ntype,
        "parent": parent,
    }
    (files_dir / f"{uuid}.metadata").write_text(json.dumps(meta), encoding="utf-8")


def _write_rm_file(files_dir: Path, uuid: str, page: str, version: int):
    """Helper to write a fake .rm file with a version header."""
    page_dir = files_dir / uuid
    page_dir.mkdir(exist_ok=True)
    header = f"reMarkable .lines file, version={version}          "
    (page_dir / f"{page}.rm").write_bytes(header.encode("ascii"))


@pytest.fixture
def backup_dir(tmp_path):
    """Create a backup directory with fake notebook structure."""
    bd = tmp_path / "backup"
    files_dir = bd / "Notebooks"
    files_dir.mkdir(parents=True)

    # Folder
    _write_metadata(files_dir, "folder-1", "Work", "CollectionType")

    # Notebook with v6 pages
    _write_metadata(files_dir, "nb-001", "Meeting Notes", "DocumentType", parent="folder-1")
    _write_rm_file(files_dir, "nb-001", "page1", 6)
    _write_rm_file(files_dir, "nb-001", "page2", 6)

    # Notebook with v5 pages
    _write_metadata(files_dir, "nb-002", "Old Notebook", "DocumentType", parent="")
    _write_rm_file(files_dir, "nb-002", "page1", 5)

    # Notebook with mixed versions
    _write_metadata(files_dir, "nb-003", "Mixed", "DocumentType", parent="folder-1")
    _write_rm_file(files_dir, "nb-003", "page1", 5)
    _write_rm_file(files_dir, "nb-003", "page2", 6)

    # Empty document (no .rm files, no pdf) — should NOT be included
    _write_metadata(files_dir, "nb-empty", "Empty Doc", "DocumentType")

    return bd


class TestFindNotebooks:
    """Tests for discovering notebooks from backup directory."""

    def test_finds_all_notebooks(self, backup_dir):
        results = find_notebooks(backup_dir)
        names = [n["name"] for n in results]
        assert "Work" in names  # folder included
        assert "Meeting Notes" in names
        assert "Old Notebook" in names
        assert "Mixed" in names

    def test_classifies_v6_files(self, backup_dir):
        results = find_notebooks(backup_dir)
        meeting = next(n for n in results if n["name"] == "Meeting Notes")
        assert len(meeting["v6_files"]) == 2
        assert len(meeting["v5_files"]) == 0

    def test_classifies_v5_files(self, backup_dir):
        results = find_notebooks(backup_dir)
        old = next(n for n in results if n["name"] == "Old Notebook")
        assert len(old["v5_files"]) == 1
        assert len(old["v6_files"]) == 0

    def test_classifies_mixed_versions(self, backup_dir):
        results = find_notebooks(backup_dir)
        mixed = next(n for n in results if n["name"] == "Mixed")
        assert len(mixed["v5_files"]) == 1
        assert len(mixed["v6_files"]) == 1

    def test_excludes_empty_documents(self, backup_dir):
        results = find_notebooks(backup_dir)
        names = [n["name"] for n in results]
        assert "Empty Doc" not in names

    def test_returns_empty_for_missing_dir(self, tmp_path):
        results = find_notebooks(tmp_path / "nonexistent")
        assert results == []

    def test_handles_corrupt_metadata(self, backup_dir):
        files_dir = backup_dir / "Notebooks"
        (files_dir / "bad-uuid.metadata").write_text("not json!!!", encoding="utf-8")
        # Should not crash
        results = find_notebooks(backup_dir)
        assert len(results) >= 3  # originals still found

    def test_preserves_parent_uuid(self, backup_dir):
        results = find_notebooks(backup_dir)
        meeting = next(n for n in results if n["name"] == "Meeting Notes")
        assert meeting["parent"] == "folder-1"

    def test_includes_collection_type(self, backup_dir):
        results = find_notebooks(backup_dir)
        work = next(n for n in results if n["name"] == "Work")
        assert work["type"] == "CollectionType"


class TestGetFolderHierarchy:
    """Tests for resolving folder paths via parent UUIDs."""

    def test_single_level_parent(self, backup_dir):
        notebook = {"parent": "folder-1"}
        hierarchy = get_folder_hierarchy(notebook, backup_dir)
        assert hierarchy == [("Work", "folder-1")]

    def test_no_parent(self, backup_dir):
        notebook = {"parent": ""}
        hierarchy = get_folder_hierarchy(notebook, backup_dir)
        assert hierarchy == []

    def test_missing_parent_metadata(self, backup_dir):
        notebook = {"parent": "nonexistent-uuid"}
        hierarchy = get_folder_hierarchy(notebook, backup_dir)
        assert hierarchy == []

    def test_nested_folders(self, tmp_path):
        """Multi-level folder hierarchy."""
        bd = tmp_path / "backup"
        files_dir = bd / "Notebooks"
        files_dir.mkdir(parents=True)

        _write_metadata(files_dir, "root-folder", "Projects", "CollectionType", parent="")
        _write_metadata(files_dir, "sub-folder", "2024", "CollectionType", parent="root-folder")

        notebook = {"parent": "sub-folder"}
        hierarchy = get_folder_hierarchy(notebook, bd)
        assert hierarchy == [("Projects", "root-folder"), ("2024", "sub-folder")]


class TestOrganizeNotebooksByStructure:
    """Tests for organizing notebooks into folder structure."""

    def test_documents_separated_from_folders(self, backup_dir):
        notebooks = find_notebooks(backup_dir)
        result = organize_notebooks_by_structure(notebooks, backup_dir)
        docs = result["documents_to_convert"]
        # Only DocumentType items should be in documents_to_convert
        for doc in docs:
            assert doc["type"] == "DocumentType"

    def test_folder_path_assigned(self, backup_dir):
        notebooks = find_notebooks(backup_dir)
        result = organize_notebooks_by_structure(notebooks, backup_dir)
        docs = result["documents_to_convert"]
        meeting = next(d for d in docs if d["name"] == "Meeting Notes")
        assert meeting["folder_path"] == "Work"

    def test_root_level_has_empty_path(self, backup_dir):
        notebooks = find_notebooks(backup_dir)
        result = organize_notebooks_by_structure(notebooks, backup_dir)
        docs = result["documents_to_convert"]
        old = next(d for d in docs if d["name"] == "Old Notebook")
        assert old["folder_path"] == ""

    def test_folder_structure_dict(self, backup_dir):
        notebooks = find_notebooks(backup_dir)
        result = organize_notebooks_by_structure(notebooks, backup_dir)
        structure = result["folder_structure"]
        assert "Work" in structure
        assert "" in structure  # root-level docs


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


class TestHashFile:
    """Tests for _hash_file utility."""

    def test_hash_existing_file(self, tmp_path):
        """_hash_file returns MD5 hash of file contents."""
        f = tmp_path / "test.txt"
        f.write_text("hello world")

        result = _hash_file(f)

        assert len(result) == 32  # MD5 hex digest
        assert result == "5eb63bbbe01eeed093cb22bb8f5acdc3"  # known MD5

    def test_hash_nonexistent_file(self, tmp_path):
        """_hash_file returns empty string for missing file."""
        result = _hash_file(tmp_path / "nonexistent.txt")
        assert result == ""

    def test_hash_empty_file(self, tmp_path):
        """_hash_file handles empty files."""
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")

        result = _hash_file(f)

        assert len(result) == 32
        assert result == "d41d8cd98f00b204e9800998ecf8427e"  # MD5 of empty

    def test_hash_binary_file(self, tmp_path):
        """_hash_file handles binary content."""
        f = tmp_path / "binary.bin"
        f.write_bytes(bytes(range(256)))

        result = _hash_file(f)

        assert len(result) == 32


class TestMergePdfs:
    """Tests for merge_pdfs function."""

    def test_merge_creates_output(self, tmp_path):
        """merge_pdfs creates output file from valid PDFs."""
        # Create minimal valid PDFs
        from PyPDF2 import PdfWriter

        pdf1 = tmp_path / "page1.pdf"
        pdf2 = tmp_path / "page2.pdf"
        output = tmp_path / "merged.pdf"

        for pdf_path in [pdf1, pdf2]:
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            with open(pdf_path, "wb") as f:
                writer.write(f)

        result = merge_pdfs([pdf1, pdf2], output)

        assert result is True
        assert output.exists()
        assert output.stat().st_size > 0

    def test_merge_skips_missing_files(self, tmp_path):
        """merge_pdfs skips non-existent files."""
        from PyPDF2 import PdfWriter

        pdf1 = tmp_path / "exists.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with open(pdf1, "wb") as f:
            writer.write(f)

        missing = tmp_path / "missing.pdf"
        output = tmp_path / "merged.pdf"

        result = merge_pdfs([pdf1, missing], output)

        assert result is True
        assert output.exists()

    def test_merge_empty_list(self, tmp_path):
        """merge_pdfs handles empty input list."""
        output = tmp_path / "merged.pdf"

        result = merge_pdfs([], output)

        # Empty merge creates empty file or fails
        assert isinstance(result, bool)

    def test_merge_creates_parent_dirs(self, tmp_path):
        """merge_pdfs creates parent directories."""
        from PyPDF2 import PdfWriter

        pdf1 = tmp_path / "page1.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with open(pdf1, "wb") as f:
            writer.write(f)

        output = tmp_path / "nested" / "dir" / "merged.pdf"

        result = merge_pdfs([pdf1], output)

        assert result is True
        assert output.exists()


class TestCopyExistingPdf:
    """Tests for copy_existing_pdf function."""

    def test_copy_creates_destination(self, tmp_path):
        """copy_existing_pdf copies file to destination."""
        src = tmp_path / "source.pdf"
        src.write_bytes(b"%PDF-1.4 fake pdf content")
        dst = tmp_path / "dest.pdf"

        result = copy_existing_pdf(src, dst)

        assert result is True
        assert dst.exists()
        assert dst.read_bytes() == src.read_bytes()

    def test_copy_missing_source(self, tmp_path):
        """copy_existing_pdf returns False for missing source."""
        result = copy_existing_pdf(tmp_path / "missing.pdf", tmp_path / "dest.pdf")
        assert result is False

    def test_copy_creates_parent_dirs(self, tmp_path):
        """copy_existing_pdf creates parent directories."""
        src = tmp_path / "source.pdf"
        src.write_bytes(b"%PDF-1.4 content")
        dst = tmp_path / "nested" / "dir" / "dest.pdf"

        result = copy_existing_pdf(src, dst)

        assert result is True
        assert dst.exists()


class TestGetPageTemplates:
    """Tests for get_page_templates function."""

    def test_parses_content_file(self, tmp_path):
        """get_page_templates extracts page template mappings."""
        content = {
            "pages": ["page1-uuid", "page2-uuid"],
            "cPages": {
                "pages": [
                    {"id": "page1-uuid", "template": {"value": "Blank"}},
                    {"id": "page2-uuid", "template": {"value": "Lined"}},
                ]
            },
        }
        content_file = tmp_path / "notebook.content"
        content_file.write_text(json.dumps(content))

        result = get_page_templates(content_file)

        assert result.get("page1-uuid") == "Blank"
        assert result.get("page2-uuid") == "Lined"

    def test_handles_missing_file(self, tmp_path):
        """get_page_templates returns empty dict for missing file."""
        result = get_page_templates(tmp_path / "missing.content")
        assert result == {}

    def test_handles_malformed_content(self, tmp_path):
        """get_page_templates handles invalid JSON."""
        content_file = tmp_path / "bad.content"
        content_file.write_text("not valid json")

        result = get_page_templates(content_file)

        assert result == {}

    def test_handles_missing_cpages(self, tmp_path):
        """get_page_templates handles content without cPages."""
        content = {"pages": ["page1"]}
        content_file = tmp_path / "simple.content"
        content_file.write_text(json.dumps(content))

        result = get_page_templates(content_file)

        assert result == {}
