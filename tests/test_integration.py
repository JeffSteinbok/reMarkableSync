"""Integration tests with .rm binary fixture files.

Tests the full pipeline: .rm fixture → version detection → can_convert()
→ convert_to_pdf() (mocked external tool) → valid PDF output.

Also tests the notebook discovery → organization → conversion orchestration
with real fixture file paths.
"""

import json
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.converters.v4_converter import V4Converter
from src.converters.v5_converter import V5Converter
from src.converters.v6_converter import V6Converter

# ---------------------------------------------------------------------------
# Fixture helpers (creates real .rm binary fixture files)
# ---------------------------------------------------------------------------

RM_HEADER_V4 = b"reMarkable .lines file, version=4          "
RM_HEADER_V5 = b"reMarkable .lines file, version=5          "
RM_HEADER_V6 = b"reMarkable .lines file, version=6          "

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "rm_files"


def _minimal_rm(header: bytes) -> bytes:
    """Build a minimal .rm binary: header + 0-layer count."""
    return header + struct.pack("<I", 0)


@pytest.fixture
def v4_rm(tmp_path):
    p = tmp_path / "page_v4.rm"
    p.write_bytes(_minimal_rm(RM_HEADER_V4))
    return p


@pytest.fixture
def v5_rm(tmp_path):
    p = tmp_path / "page_v5.rm"
    p.write_bytes(_minimal_rm(RM_HEADER_V5))
    return p


@pytest.fixture
def v6_rm(tmp_path):
    p = tmp_path / "page_v6.rm"
    p.write_bytes(_minimal_rm(RM_HEADER_V6))
    return p


# ---------------------------------------------------------------------------
# Integration: version detection → can_convert
# ---------------------------------------------------------------------------


class TestVersionDetectionIntegration:
    """Version detection drives the correct converter selection."""

    def test_v4_file_routed_to_v4_converter_only(self, v4_rm):
        assert V4Converter().can_convert(v4_rm)
        assert not V5Converter().can_convert(v4_rm)
        assert not V6Converter().can_convert(v4_rm)

    def test_v5_file_routed_to_v5_converter_only(self, v5_rm):
        assert not V4Converter().can_convert(v5_rm)
        assert V5Converter().can_convert(v5_rm)
        assert not V6Converter().can_convert(v5_rm)

    def test_v6_file_routed_to_v6_converter_only(self, v6_rm):
        assert not V4Converter().can_convert(v6_rm)
        assert not V5Converter().can_convert(v6_rm)
        assert V6Converter().can_convert(v6_rm)

    def test_pre_committed_v4_fixture_routable(self):
        p = FIXTURES_DIR / "minimal_v4.rm"
        if not p.exists():
            pytest.skip("minimal_v4.rm fixture not found")
        assert V4Converter().can_convert(p)

    def test_pre_committed_v5_fixture_routable(self):
        p = FIXTURES_DIR / "minimal_v5.rm"
        if not p.exists():
            pytest.skip("minimal_v5.rm fixture not found")
        assert V5Converter().can_convert(p)

    def test_pre_committed_v6_fixture_routable(self):
        p = FIXTURES_DIR / "minimal_v6.rm"
        if not p.exists():
            pytest.skip("minimal_v6.rm fixture not found")
        assert V6Converter().can_convert(p)


# ---------------------------------------------------------------------------
# Integration: convert_to_pdf with mocked AI/OCR → valid PDF header
# ---------------------------------------------------------------------------


class TestConvertToPdfIntegration:
    """Tests the convert_to_pdf path with mocked external tools."""

    def _make_fake_pdf(self, path: Path) -> None:
        """Write a minimal valid PDF to *path*."""
        path.write_bytes(
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>\nendobj\n"
            b"xref\n0 4\n0000000000 65535 f \n"
            b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n200\n%%EOF\n"
        )

    def test_v5_convert_produces_pdf(self, v5_rm, tmp_path):
        out = tmp_path / "output.pdf"
        svg_content = b"<svg>" + b"x" * 200 + b"</svg>"

        fake_rmrl = MagicMock()
        fake_rmrl.render.return_value = svg_content

        converter = V5Converter()
        with patch.dict("sys.modules", {"rmrl": fake_rmrl}):
            with patch.object(converter, "svg_to_pdf") as mock_svg:

                def _write_pdf(svg_path, pdf_path):
                    self._make_fake_pdf(pdf_path)
                    return True

                mock_svg.side_effect = _write_pdf
                result = converter.convert_to_pdf(v5_rm, out)

        assert result is True
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"

    def test_v6_convert_produces_pdf(self, v6_rm, tmp_path):
        out = tmp_path / "output.pdf"

        converter = V6Converter()

        def _fake_rm_to_svg(rm_path, svg_path):
            Path(svg_path).write_bytes(b"<svg>" + b"x" * 200 + b"</svg>")

        with patch("rmc.exporters.svg.rm_to_svg", side_effect=_fake_rm_to_svg):
            with patch.object(converter, "svg_to_pdf") as mock_svg:

                def _write_pdf(svg_path, pdf_path):
                    self._make_fake_pdf(pdf_path)
                    return True

                mock_svg.side_effect = _write_pdf
                result = converter.convert_to_pdf(v6_rm, out)

        assert result is True
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"

    def test_v4_convert_produces_pdf(self, v4_rm, tmp_path):
        out = tmp_path / "output.pdf"
        svg_content = b"<svg>" + b"x" * 200 + b"</svg>"

        fake_rmrl = MagicMock()
        fake_rmrl.render.return_value = svg_content

        converter = V4Converter()
        with patch.dict("sys.modules", {"rmrl": fake_rmrl}):
            with patch.object(converter, "svg_to_pdf") as mock_svg:

                def _write_pdf(svg_path, pdf_path):
                    self._make_fake_pdf(pdf_path)
                    return True

                mock_svg.side_effect = _write_pdf
                result = converter.convert_to_pdf(v4_rm, out)

        assert result is True
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Integration: notebook discovery with real .rm fixture files
# ---------------------------------------------------------------------------


class TestNotebookDiscoveryIntegration:
    """find_notebooks correctly classifies real .rm fixture files."""

    def _make_backup(self, tmp_path: Path, notebooks: list) -> Path:
        bd = tmp_path / "backup"
        files_dir = bd / "Notebooks"
        files_dir.mkdir(parents=True)

        for nb in notebooks:
            uuid = nb["uuid"]
            meta = {
                "visibleName": nb["name"],
                "type": "DocumentType",
                "parent": "",
            }
            (files_dir / f"{uuid}.metadata").write_text(json.dumps(meta), encoding="utf-8")

            nb_dir = files_dir / uuid
            nb_dir.mkdir(exist_ok=True)
            for page_file, content in nb.get("pages", []):
                (nb_dir / page_file).write_bytes(content)

        return bd

    def test_v5_pages_classified_correctly(self, tmp_path):
        from src.hybrid_converter import find_notebooks

        bd = self._make_backup(
            tmp_path,
            [
                {
                    "uuid": "nb-v5",
                    "name": "V5 Notebook",
                    "pages": [
                        ("page1.rm", _minimal_rm(RM_HEADER_V5)),
                        ("page2.rm", _minimal_rm(RM_HEADER_V5)),
                    ],
                }
            ],
        )
        results = find_notebooks(bd)
        nb = next((n for n in results if n["name"] == "V5 Notebook"), None)
        assert nb is not None
        assert len(nb["v5_files"]) == 2
        assert len(nb["v6_files"]) == 0

    def test_v6_pages_classified_correctly(self, tmp_path):
        from src.hybrid_converter import find_notebooks

        bd = self._make_backup(
            tmp_path,
            [
                {
                    "uuid": "nb-v6",
                    "name": "V6 Notebook",
                    "pages": [("page1.rm", _minimal_rm(RM_HEADER_V6))],
                }
            ],
        )
        results = find_notebooks(bd)
        nb = next((n for n in results if n["name"] == "V6 Notebook"), None)
        assert nb is not None
        assert len(nb["v6_files"]) == 1
        assert len(nb["v5_files"]) == 0

    def test_mixed_version_pages_classified(self, tmp_path):
        from src.hybrid_converter import find_notebooks

        bd = self._make_backup(
            tmp_path,
            [
                {
                    "uuid": "nb-mixed",
                    "name": "Mixed Notebook",
                    "pages": [
                        ("page1.rm", _minimal_rm(RM_HEADER_V5)),
                        ("page2.rm", _minimal_rm(RM_HEADER_V6)),
                    ],
                }
            ],
        )
        results = find_notebooks(bd)
        nb = next((n for n in results if n["name"] == "Mixed Notebook"), None)
        assert nb is not None
        assert len(nb["v5_files"]) == 1
        assert len(nb["v6_files"]) == 1

    def test_v4_pages_classified_correctly(self, tmp_path):
        from src.hybrid_converter import find_notebooks

        bd = self._make_backup(
            tmp_path,
            [
                {
                    "uuid": "nb-v4",
                    "name": "V4 Notebook",
                    "pages": [("page1.rm", _minimal_rm(RM_HEADER_V4))],
                }
            ],
        )
        results = find_notebooks(bd)
        nb = next((n for n in results if n["name"] == "V4 Notebook"), None)
        assert nb is not None
        assert len(nb["v4_files"]) == 1


# ---------------------------------------------------------------------------
# Integration: full .rm → PDF pipeline (mocked OCR, real file I/O)
# ---------------------------------------------------------------------------


class TestFullPipelineIntegration:
    """End-to-end: .rm files → convert_notebook → PDFs on disk."""

    def _build_notebook_fixture(self, tmp_path: Path, version: int) -> dict:
        """Return a minimal notebook dict with a real .rm file."""
        nb_dir = tmp_path / "Notebooks" / "nb-test"
        nb_dir.mkdir(parents=True)

        header = {4: RM_HEADER_V4, 5: RM_HEADER_V5, 6: RM_HEADER_V6}[version]
        rm_file = nb_dir / "page1.rm"
        rm_file.write_bytes(_minimal_rm(header))

        file_list = [rm_file]
        return {
            "uuid": "nb-test",
            "name": "Test Notebook",
            "type": "DocumentType",
            "folder_path": "",
            "parent": "",
            "v4_files": file_list if version == 4 else [],
            "v5_files": file_list if version == 5 else [],
            "v6_files": file_list if version == 6 else [],
            "v3_files": [],
            "pdf_files": [],
            "metadata_file": tmp_path / "Notebooks" / "nb-test.metadata",
        }

    def test_v5_end_to_end_conversion(self, tmp_path):
        """v5 .rm → convert_notebook → output PDF written to disk."""
        from src.hybrid_converter import convert_notebook

        nb = self._build_notebook_fixture(tmp_path, 5)
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        svg_content = b"<svg>" + b"x" * 200 + b"</svg>"
        fake_rmrl = MagicMock()
        fake_rmrl.render.return_value = svg_content

        def _fake_svg_to_pdf(svg_file, pdf_file):
            pdf_file.parent.mkdir(parents=True, exist_ok=True)
            pdf_file.write_bytes(b"%PDF-1.4\n%%EOF\n")
            return True

        def _fake_merge(pdf_files, output_file):
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_bytes(b"%PDF-1.4\n%%EOF\n")
            return True

        with (
            patch.dict("sys.modules", {"rmrl": fake_rmrl}),
            patch(
                "src.converters.base_converter.BaseConverter.svg_to_pdf",
                side_effect=_fake_svg_to_pdf,
            ),
            patch("src.hybrid_converter.merge_pdfs", side_effect=_fake_merge),
        ):
            results = convert_notebook(nb, out_dir, tmp_path, None)

        assert results["output_files"]

    def test_v6_end_to_end_conversion(self, tmp_path):
        """v6 .rm → convert_notebook → output PDF written to disk."""
        from src.hybrid_converter import convert_notebook

        nb = self._build_notebook_fixture(tmp_path, 6)
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        def _fake_rm_to_svg(rm_path, svg_path):
            Path(svg_path).parent.mkdir(parents=True, exist_ok=True)
            Path(svg_path).write_bytes(b"<svg>" + b"x" * 200 + b"</svg>")

        def _fake_svg_to_pdf(svg_file, pdf_file):
            pdf_file.parent.mkdir(parents=True, exist_ok=True)
            pdf_file.write_bytes(b"%PDF-1.4\n%%EOF\n")
            return True

        def _fake_merge(pdf_files, output_file):
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_bytes(b"%PDF-1.4\n%%EOF\n")
            return True

        with (
            patch("rmc.exporters.svg.rm_to_svg", side_effect=_fake_rm_to_svg),
            patch(
                "src.converters.base_converter.BaseConverter.svg_to_pdf",
                side_effect=_fake_svg_to_pdf,
            ),
            patch("src.hybrid_converter.merge_pdfs", side_effect=_fake_merge),
        ):
            results = convert_notebook(nb, out_dir, tmp_path, None)

        assert results["output_files"]
