"""Tests for the TemplateRenderer module."""

import json

import pytest
from reportlab.pdfgen.canvas import Canvas as RLCanvas

from src.template_renderer import TemplateRenderer


@pytest.fixture
def templates_dir(tmp_path):
    """Create a fake templates directory with metadata."""
    tdir = tmp_path / "templates"
    tdir.mkdir()

    templates_json = {
        "templates": [
            {"name": "P Grid small", "filename": "P Grid small"},
            {"name": "P Lines medium", "filename": "P Lines medium"},
            {"name": "P Dots S", "filename": "P Dots S"},
            {"name": "Blank", "filename": "Blank"},
        ]
    }
    (tdir / "templates.json").write_text(json.dumps(templates_json), encoding="utf-8")

    # Create fake template files
    grid_data = {"constants": [{"gridSize": 52}]}
    (tdir / "P Grid small.template").write_text(json.dumps(grid_data), encoding="utf-8")

    lines_data = {"constants": [{"lineHeight": 40}]}
    (tdir / "P Lines medium.template").write_text(json.dumps(lines_data), encoding="utf-8")

    dots_data = {"constants": [{"dotSpacing": 35}]}
    (tdir / "P Dots S.template").write_text(json.dumps(dots_data), encoding="utf-8")

    return tdir


class TestLoadTemplatesMetadata:
    """Tests for loading templates.json."""

    def test_loads_template_definitions(self, templates_dir):
        renderer = TemplateRenderer(templates_dir)
        assert "P Grid small" in renderer.templates_metadata
        assert "P Lines medium" in renderer.templates_metadata
        assert len(renderer.templates_metadata) == 4

    def test_missing_templates_json(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        renderer = TemplateRenderer(empty_dir)
        assert renderer.templates_metadata == {}

    def test_corrupt_templates_json(self, tmp_path):
        tdir = tmp_path / "bad"
        tdir.mkdir()
        (tdir / "templates.json").write_text("not json!", encoding="utf-8")
        renderer = TemplateRenderer(tdir)
        assert renderer.templates_metadata == {}


class TestGetTemplateFile:
    """Tests for resolving template file paths."""

    def test_returns_path_for_existing_template(self, templates_dir):
        renderer = TemplateRenderer(templates_dir)
        result = renderer.get_template_file("P Grid small")
        assert result is not None
        assert result.exists()
        assert result.name == "P Grid small.template"

    def test_returns_none_for_blank(self, templates_dir):
        renderer = TemplateRenderer(templates_dir)
        assert renderer.get_template_file("Blank") is None

    def test_returns_none_for_empty_name(self, templates_dir):
        renderer = TemplateRenderer(templates_dir)
        assert renderer.get_template_file("") is None

    def test_returns_none_for_missing_template(self, templates_dir):
        renderer = TemplateRenderer(templates_dir)
        assert renderer.get_template_file("Nonexistent Template") is None


class TestLoadTemplate:
    """Tests for loading and caching template data."""

    def test_loads_template_data(self, templates_dir):
        renderer = TemplateRenderer(templates_dir)
        data = renderer.load_template("P Grid small")
        assert data is not None
        assert "constants" in data

    def test_caches_loaded_template(self, templates_dir):
        renderer = TemplateRenderer(templates_dir)
        data1 = renderer.load_template("P Grid small")
        data2 = renderer.load_template("P Grid small")
        assert data1 is data2  # same object from cache

    def test_returns_none_for_missing(self, templates_dir):
        renderer = TemplateRenderer(templates_dir)
        assert renderer.load_template("Does Not Exist") is None


class TestRenderTemplateToPdf:
    """Tests for PDF rendering (no sample .rm files needed)."""

    def test_blank_template_creates_pdf(self, templates_dir, tmp_path):
        renderer = TemplateRenderer(templates_dir)
        output = tmp_path / "blank.pdf"
        result = renderer.render_template_to_pdf("Blank", output)
        assert result is True
        assert output.exists()
        assert output.stat().st_size > 0
        # Check PDF header
        assert output.read_bytes()[:4] == b"%PDF"

    def test_empty_name_creates_blank_pdf(self, templates_dir, tmp_path):
        renderer = TemplateRenderer(templates_dir)
        output = tmp_path / "empty.pdf"
        result = renderer.render_template_to_pdf("", output)
        assert result is True
        assert output.exists()

    def test_grid_template_creates_pdf(self, templates_dir, tmp_path):
        renderer = TemplateRenderer(templates_dir)
        output = tmp_path / "grid.pdf"
        result = renderer.render_template_to_pdf("P Grid small", output)
        assert result is True
        assert output.exists()
        # Grid PDF should be larger than blank (has line content)
        blank = tmp_path / "blank.pdf"
        renderer.render_template_to_pdf("Blank", blank)
        assert output.stat().st_size > blank.stat().st_size

    def test_lines_template_creates_pdf(self, templates_dir, tmp_path):
        renderer = TemplateRenderer(templates_dir)
        output = tmp_path / "lines.pdf"
        result = renderer.render_template_to_pdf("P Lines medium", output)
        assert result is True
        assert output.exists()

    def test_dots_template_creates_pdf(self, templates_dir, tmp_path):
        renderer = TemplateRenderer(templates_dir)
        output = tmp_path / "dots.pdf"
        result = renderer.render_template_to_pdf("P Dots S", output)
        assert result is True
        assert output.exists()

    def test_unknown_template_falls_back_to_blank(self, templates_dir, tmp_path):
        renderer = TemplateRenderer(templates_dir)
        output = tmp_path / "fallback.pdf"
        result = renderer.render_template_to_pdf("Unknown Template XYZ", output)
        assert result is True
        assert output.exists()


def _pdf_page_size(pdf_path):
    """Return (width, height) in PDF points for the first page of a PDF."""
    from PyPDF2 import PdfReader

    reader = PdfReader(str(pdf_path))
    page = reader.pages[0]
    return float(page.mediabox.width), float(page.mediabox.height)


class TestRenderTemplateToPdfLongPage:
    """Tests for long/extended page support in template rendering."""

    def test_blank_template_respects_custom_height(self, templates_dir, tmp_path):
        """Blank template rendered at double height should produce a taller PDF."""
        renderer = TemplateRenderer(templates_dir)
        output = tmp_path / "blank_long.pdf"
        long_height = renderer.REMARKABLE_HEIGHT * 2
        result = renderer.render_template_to_pdf("Blank", output, page_height=long_height)
        assert result is True
        _, height = _pdf_page_size(output)
        assert abs(height - long_height) < 1.0

    def test_grid_template_respects_custom_height(self, templates_dir, tmp_path):
        """Grid template rendered with a custom height should produce a taller PDF."""
        renderer = TemplateRenderer(templates_dir)
        output = tmp_path / "grid_long.pdf"
        long_height = renderer.REMARKABLE_HEIGHT * 2
        result = renderer.render_template_to_pdf("P Grid small", output, page_height=long_height)
        assert result is True
        _, height = _pdf_page_size(output)
        assert abs(height - long_height) < 1.0

    def test_lines_template_respects_custom_height(self, templates_dir, tmp_path):
        """Lines template rendered with a custom height should produce a taller PDF."""
        renderer = TemplateRenderer(templates_dir)
        output = tmp_path / "lines_long.pdf"
        long_height = renderer.REMARKABLE_HEIGHT * 2
        result = renderer.render_template_to_pdf("P Lines medium", output, page_height=long_height)
        assert result is True
        _, height = _pdf_page_size(output)
        assert abs(height - long_height) < 1.0

    def test_dots_template_respects_custom_height(self, templates_dir, tmp_path):
        """Dots template rendered with a custom height should produce a taller PDF."""
        renderer = TemplateRenderer(templates_dir)
        output = tmp_path / "dots_long.pdf"
        long_height = renderer.REMARKABLE_HEIGHT * 2
        result = renderer.render_template_to_pdf("P Dots S", output, page_height=long_height)
        assert result is True
        _, height = _pdf_page_size(output)
        assert abs(height - long_height) < 1.0

    def test_standard_height_unchanged_when_no_override(self, templates_dir, tmp_path):
        """Without a custom height, template should use the standard ReMarkable height."""
        renderer = TemplateRenderer(templates_dir)
        output = tmp_path / "grid_std.pdf"
        result = renderer.render_template_to_pdf("P Grid small", output)
        assert result is True
        _, height = _pdf_page_size(output)
        assert abs(height - renderer.REMARKABLE_HEIGHT) < 1.0


class TestMergePdfWithTemplateLongPage:
    """Tests for merge_pdf_with_template when content is taller than template."""

    def _make_pdf(self, path, width, height):
        """Create a minimal single-page PDF at the given dimensions."""
        c = RLCanvas(str(path), pagesize=(width, height))
        c.showPage()
        c.save()

    def test_long_content_page_not_clipped(self, tmp_path):
        """When content is taller than template, output must preserve content height."""
        from PyPDF2 import PdfReader

        from src.hybrid_converter import merge_pdf_with_template
        from src.template_renderer import TemplateRenderer

        std_w = TemplateRenderer.REMARKABLE_WIDTH
        std_h = TemplateRenderer.REMARKABLE_HEIGHT
        long_h = std_h * 2

        content_pdf = tmp_path / "content.pdf"
        template_pdf = tmp_path / "template.pdf"
        output_pdf = tmp_path / "merged.pdf"

        self._make_pdf(content_pdf, std_w, long_h)
        self._make_pdf(template_pdf, std_w, std_h)

        result = merge_pdf_with_template(content_pdf, template_pdf, output_pdf)

        assert result is True
        reader = PdfReader(str(output_pdf))
        out_height = float(reader.pages[0].mediabox.height)
        # The merged page must be at least as tall as the content page.
        assert out_height >= long_h - 1.0, (
            f"Output page height {out_height} is shorter than content height {long_h}; "
            "long page was clipped by the template."
        )
