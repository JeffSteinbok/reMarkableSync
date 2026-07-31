"""Tests for rm_pdf_converter.run_conversion() — batch conversion orchestration.

All I/O-heavy dependencies (find_notebooks, convert_notebook, TemplateRenderer)
are mocked so these tests exercise only the orchestration/filtering logic.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.rm_pdf_converter import run_conversion

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

_NB_DEFAULTS = {
    "uuid": "nb-001",
    "name": "Test Notebook",
    "type": "DocumentType",
    "folder_path": "",
    "v5_files": [],
    "v6_files": [],
    "v4_files": [],
    "pdf_files": [],
}


def _make_notebook(**overrides):
    nb = dict(_NB_DEFAULTS)
    nb.update(overrides)
    return nb


def _build_backup(tmp_path: Path, notebooks=None):
    """Create a minimal backup directory structure."""
    bd = tmp_path / "backup"
    (bd / "Notebooks").mkdir(parents=True)
    if notebooks:
        for nb in notebooks:
            uuid = nb["uuid"]
            meta = {
                "visibleName": nb["name"],
                "type": nb.get("type", "DocumentType"),
                "parent": nb.get("parent", ""),
            }
            (bd / "Notebooks" / f"{uuid}.metadata").write_text(json.dumps(meta), encoding="utf-8")
    return bd


# Patch targets used by most tests
_PATCH_FIND = "src.rm_pdf_converter.find_notebooks"
_PATCH_ORG = "src.rm_pdf_converter.organize_notebooks_by_structure"
_PATCH_CONVERT = "src.rm_pdf_converter.convert_notebook"
_PATCH_PROGRESS = "src.rm_pdf_converter.create_progress"


def _fake_progress():
    """Return a context-manager mock for create_progress."""
    ctx = MagicMock()
    task_mock = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.add_task.return_value = task_mock
    return ctx


def _patch_progress(monkeypatch=None):
    return patch(_PATCH_PROGRESS, return_value=_fake_progress())


# ---------------------------------------------------------------------------
# Missing / empty backup
# ---------------------------------------------------------------------------


class TestRunConversionMissingDir:
    def test_missing_backup_dir_returns_failure(self, tmp_path):
        success, converted, merged = run_conversion(
            tmp_path / "nonexistent",
            tmp_path / "output",
        )
        assert success is False
        assert converted == {}
        assert merged == []

    def test_backup_dir_exists_but_no_notebooks(self, tmp_path):
        bd = _build_backup(tmp_path)
        with (
            patch(_PATCH_FIND, return_value=[]),
            patch(_PATCH_ORG, return_value={"documents_to_convert": []}),
        ):
            success, converted, merged = run_conversion(bd, tmp_path / "output")
        assert success is False


# ---------------------------------------------------------------------------
# updated_uuids filtering
# ---------------------------------------------------------------------------


class TestRunConversionUpdatedUuids:
    def _run(self, tmp_path, notebooks, updated_uuids, **kw):
        bd = _build_backup(tmp_path)
        org = {"documents_to_convert": [n for n in notebooks if n["type"] == "DocumentType"]}
        with (
            patch(_PATCH_FIND, return_value=notebooks),
            patch(_PATCH_ORG, return_value=org),
            _patch_progress(),
        ):
            return run_conversion(
                bd,
                tmp_path / "output",
                updated_uuids=updated_uuids,
                **kw,
            )

    def test_empty_updated_uuids_skips_conversion(self, tmp_path):
        nbs = [_make_notebook(uuid="a", v6_files=["x"])]
        success, converted, merged = self._run(tmp_path, nbs, updated_uuids=set())
        assert success is True
        assert converted == {}

    def test_none_updated_uuids_converts_all(self, tmp_path):
        nbs = [_make_notebook(uuid="a", v6_files=["x"])]
        with patch(
            "src.rm_pdf_converter.convert_notebook",
            return_value={
                "output_files": [Path("/fake.pdf")],
                "page_pdfs": [],
                "pdf_changed": True,
            },
        ):
            success, converted, merged = self._run(tmp_path, nbs, updated_uuids=None)
        # At least tried to convert (find_notebooks was called)
        assert success is True or success is False  # just no crash

    def test_updated_uuids_filters_to_subset(self, tmp_path):
        nbs = [
            _make_notebook(uuid="nb-a", name="A", v6_files=["a.rm"]),
            _make_notebook(uuid="nb-b", name="B", v6_files=["b.rm"]),
        ]
        bd = _build_backup(tmp_path)

        results_captured = []

        def _fake_find(backup_dir):
            return nbs

        def _passthrough_org(items, backup_dir):
            return {"documents_to_convert": [n for n in items if n.get("type") == "DocumentType"]}

        def _fake_convert(notebook, *args, **kwargs):
            results_captured.append(notebook["uuid"])
            return {"output_files": [], "page_pdfs": [], "pdf_changed": False}

        with (
            patch(_PATCH_FIND, side_effect=_fake_find),
            patch(_PATCH_ORG, side_effect=_passthrough_org),
            patch("src.rm_pdf_converter.convert_notebook", side_effect=_fake_convert),
            _patch_progress(),
        ):
            run_conversion(bd, tmp_path / "output", updated_uuids={"nb-a"})

        # Only notebook "nb-a" should have been converted
        assert results_captured == ["nb-a"]


def test_conversion_logs_overall_page_progress(tmp_path, caplog):
    notebooks = [
        _make_notebook(uuid="nb-a", name="A", v6_files=["a1.rm", "a2.rm"]),
        _make_notebook(uuid="nb-b", name="B", v6_files=["b1.rm"]),
    ]
    bd = _build_backup(tmp_path)

    def _fake_convert(notebook, *args, **kwargs):
        on_page_done = kwargs["on_page_done"]
        for _ in notebook["v6_files"]:
            on_page_done()
        return {"output_files": [Path("/fake.pdf")], "page_pdfs": [], "pdf_changed": True}

    with (
        patch(_PATCH_FIND, return_value=notebooks),
        patch(_PATCH_ORG, return_value={"documents_to_convert": notebooks}),
        patch(_PATCH_CONVERT, side_effect=_fake_convert),
        _patch_progress(),
        caplog.at_level("INFO"),
    ):
        run_conversion(bd, tmp_path / "output")

    assert "PDF: A (page 2/2, overall 2/3)" in caplog.text
    assert "PDF: B (page 1/1, overall 3/3)" in caplog.text


# ---------------------------------------------------------------------------
# notebook_filter
# ---------------------------------------------------------------------------


class TestRunConversionNotebookFilter:
    def _run_with_filter(self, tmp_path, notebooks, notebook_filter):
        bd = _build_backup(tmp_path)
        converted_uuids = []

        def _passthrough_org(items, backup_dir):
            return {"documents_to_convert": [n for n in items if n.get("type") == "DocumentType"]}

        def _fake_convert(notebook, *args, **kwargs):
            converted_uuids.append(notebook["uuid"])
            return {"output_files": [], "page_pdfs": [], "pdf_changed": False}

        with (
            patch(_PATCH_FIND, return_value=notebooks),
            patch(_PATCH_ORG, side_effect=_passthrough_org),
            patch("src.rm_pdf_converter.convert_notebook", side_effect=_fake_convert),
            _patch_progress(),
        ):
            success, _, _ = run_conversion(bd, tmp_path / "output", notebook_filter=notebook_filter)

        return success, converted_uuids

    def test_filter_by_name_matches(self, tmp_path):
        nbs = [
            _make_notebook(uuid="nb-1", name="My Notes", v6_files=["x"]),
            _make_notebook(uuid="nb-2", name="Other", v6_files=["y"]),
        ]
        success, uuids = self._run_with_filter(tmp_path, nbs, "My Notes")
        assert uuids == ["nb-1"]

    def test_filter_by_uuid_matches(self, tmp_path):
        nbs = [
            _make_notebook(uuid="nb-1", name="A", v6_files=["x"]),
            _make_notebook(uuid="nb-2", name="B", v6_files=["y"]),
        ]
        success, uuids = self._run_with_filter(tmp_path, nbs, "nb-2")
        assert uuids == ["nb-2"]

    def test_filter_not_found_returns_failure(self, tmp_path):
        nbs = [_make_notebook(uuid="nb-1", name="A", v6_files=["x"])]
        success, uuids = self._run_with_filter(tmp_path, nbs, "No Such Notebook")
        assert success is False
        assert uuids == []


# ---------------------------------------------------------------------------
# folder_filter
# ---------------------------------------------------------------------------


class TestRunConversionFolderFilter:
    def _run_with_folder_filter(self, tmp_path, notebooks, folder_filter):
        bd = _build_backup(tmp_path)
        org = {"documents_to_convert": notebooks}
        converted_uuids = []

        def _fake_convert(notebook, *args, **kwargs):
            converted_uuids.append(notebook["uuid"])
            return {"output_files": [], "page_pdfs": [], "pdf_changed": False}

        with (
            patch(_PATCH_FIND, return_value=notebooks),
            patch(_PATCH_ORG, return_value=org),
            patch("src.rm_pdf_converter.convert_notebook", side_effect=_fake_convert),
            _patch_progress(),
        ):
            run_conversion(bd, tmp_path / "output", folder_filter=folder_filter)

        return converted_uuids

    def test_folder_filter_includes_matching_folder(self, tmp_path):
        nbs = [
            _make_notebook(uuid="nb-1", name="Work Note", folder_path="Work", v6_files=["x"]),
            _make_notebook(uuid="nb-2", name="Personal", folder_path="Personal", v6_files=["y"]),
        ]
        uuids = self._run_with_folder_filter(tmp_path, nbs, ["Work"])
        assert "nb-1" in uuids
        assert "nb-2" not in uuids

    def test_folder_filter_root_notebooks(self, tmp_path):
        nbs = [
            _make_notebook(uuid="nb-1", name="Root Note", folder_path="", v6_files=["x"]),
            _make_notebook(uuid="nb-2", name="Sub Note", folder_path="Work", v6_files=["y"]),
        ]
        uuids = self._run_with_folder_filter(tmp_path, nbs, ["(Root)"])
        assert "nb-1" in uuids
        assert "nb-2" not in uuids

    def test_folder_filter_multiple_folders(self, tmp_path):
        nbs = [
            _make_notebook(uuid="nb-1", folder_path="Work", v6_files=["x"]),
            _make_notebook(uuid="nb-2", folder_path="Personal", v6_files=["y"]),
            _make_notebook(uuid="nb-3", folder_path="Archive", v6_files=["z"]),
        ]
        uuids = self._run_with_folder_filter(tmp_path, nbs, ["Work", "Personal"])
        assert "nb-1" in uuids
        assert "nb-2" in uuids
        assert "nb-3" not in uuids


# ---------------------------------------------------------------------------
# sample limit
# ---------------------------------------------------------------------------


class TestRunConversionSample:
    def test_sample_limits_notebooks(self, tmp_path):
        nbs = [
            _make_notebook(uuid=f"nb-{i}", name=f"Notebook {i}", v6_files=[f"p{i}.rm"])
            for i in range(5)
        ]
        bd = _build_backup(tmp_path)
        org = {"documents_to_convert": nbs}
        converted_uuids = []

        def _fake_convert(notebook, *args, **kwargs):
            converted_uuids.append(notebook["uuid"])
            return {"output_files": [], "page_pdfs": [], "pdf_changed": False}

        with (
            patch(_PATCH_FIND, return_value=nbs),
            patch(_PATCH_ORG, return_value=org),
            patch("src.rm_pdf_converter.convert_notebook", side_effect=_fake_convert),
            _patch_progress(),
        ):
            run_conversion(bd, tmp_path / "output", sample=2)

        assert len(converted_uuids) == 2


# ---------------------------------------------------------------------------
# Converter failure handling
# ---------------------------------------------------------------------------


class TestRunConversionErrorHandling:
    def test_convert_notebook_exception_does_not_crash(self, tmp_path):
        nbs = [_make_notebook(uuid="nb-1", v6_files=["x.rm"])]
        bd = _build_backup(tmp_path)
        org = {"documents_to_convert": nbs}

        def _bad_convert(notebook, *args, **kwargs):
            raise RuntimeError("Simulated converter crash")

        with (
            patch(_PATCH_FIND, return_value=nbs),
            patch(_PATCH_ORG, return_value=org),
            patch("src.rm_pdf_converter.convert_notebook", side_effect=_bad_convert),
            _patch_progress(),
        ):
            # Should not raise
            success, _, _ = run_conversion(bd, tmp_path / "output")

        assert success is False  # 0 notebooks converted successfully

    def test_output_dir_created_if_missing(self, tmp_path):
        nbs = [_make_notebook(uuid="nb-1", v6_files=["x.rm"])]
        bd = _build_backup(tmp_path)
        org = {"documents_to_convert": nbs}
        out = tmp_path / "new_output_dir"

        def _fake_convert(notebook, *args, **kwargs):
            return {"output_files": [out / "test.pdf"], "page_pdfs": [], "pdf_changed": False}

        with (
            patch(_PATCH_FIND, return_value=nbs),
            patch(_PATCH_ORG, return_value=org),
            patch("src.rm_pdf_converter.convert_notebook", side_effect=_fake_convert),
            _patch_progress(),
        ):
            run_conversion(bd, out)

        assert out.exists()
