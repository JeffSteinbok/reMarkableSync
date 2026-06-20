"""
Template Renderer - Internal Helper Module

This is a helper module for rendering ReMarkable templates.
Do not run directly - use RemarkableSync.py as the entry point.

Entry Point:
    RemarkableSync.py convert [OPTIONS]

This module provides:
- Loading and parsing ReMarkable template metadata
- Rendering templates as PDF backgrounds
- Template compositing with notebook content
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

from reportlab.pdfgen import canvas


class TemplateRenderer:
    """Renders ReMarkable templates as PDF backgrounds."""

    # ReMarkable dimensions
    # reMarkable 2: 1404 x 1872 pixels at 226 DPI
    REMARKABLE_WIDTH_PIXELS = 1404
    REMARKABLE_HEIGHT_PIXELS = 1872
    REMARKABLE_DPI = 226

    # Converted to PDF points (72 points = 1 inch)
    # Width: 1404/226*72 = 447.5 points
    # Height: 1872/226*72 = 596.7 points
    REMARKABLE_WIDTH = 447.5
    REMARKABLE_HEIGHT = 596.7

    # Conversion factor from template pixels to PDF points
    PIXELS_TO_POINTS = 72.0 / REMARKABLE_DPI  # ~0.3186

    def __init__(self, templates_dir: Path):
        """Initialize template renderer.

        Args:
            templates_dir: Path to directory containing template files
        """
        self.templates_dir = templates_dir
        self.templates_json_path = templates_dir / "templates.json"
        self.template_cache: Dict[str, Dict] = {}
        self.templates_metadata: Dict[str, Dict] = {}

        self._load_templates_metadata()

    def _load_templates_metadata(self):
        """Load templates.json metadata."""
        if not self.templates_json_path.exists():
            logging.warning(f"templates.json not found at {self.templates_json_path}")
            return

        try:
            with open(self.templates_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for template in data.get("templates", []):
                    name = template.get("name", "")
                    if name:
                        self.templates_metadata[name] = template
            logging.info(f"Loaded {len(self.templates_metadata)} template definitions")
        except Exception as e:
            logging.warning(f"Failed to load templates.json: {e}")

    def get_template_file(self, template_name: str) -> Optional[Path]:
        """Get the template file path for a given template name.

        Args:
            template_name: Name of the template (e.g., "P Grid small")

        Returns:
            Path to template file, or None if not found
        """
        if not template_name or template_name == "Blank":
            return None

        # Try to get filename from metadata
        template_info = self.templates_metadata.get(template_name)
        if template_info:
            filename = template_info.get("filename", template_name)
        else:
            filename = template_name

        # Look for .template file
        template_file = self.templates_dir / f"{filename}.template"
        if template_file.exists():
            return template_file

        # Try without extension
        template_file = self.templates_dir / filename
        if template_file.exists():
            return template_file

        logging.debug(f"Template file not found for: {template_name}")
        return None

    def load_template(self, template_name: str) -> Optional[Dict]:
        """Load and parse a template JSON file.

        Args:
            template_name: Name of the template

        Returns:
            Template data dictionary, or None if not found
        """
        if template_name in self.template_cache:
            return self.template_cache[template_name]

        template_file = self.get_template_file(template_name)
        if not template_file:
            return None

        try:
            with open(template_file, "r", encoding="utf-8") as f:
                template_data = json.load(f)
                self.template_cache[template_name] = template_data
                return template_data
        except Exception as e:
            logging.debug(f"Failed to load template {template_name}: {e}")
            return None

    def render_template_to_pdf(
        self,
        template_name: str,
        output_pdf: Path,
        page_height: Optional[float] = None,
        page_width: Optional[float] = None,
    ) -> bool:
        """Render a template as a PDF file.

        This creates a simple PDF with basic template rendering.
        For complex templates, this provides a basic grid/line background.

        Args:
            template_name: Name of the template to render
            output_pdf: Path where the PDF should be saved
            page_height: Actual page height in PDF points. When the page is
                taller than the standard ReMarkable height (e.g. a long/extended
                page), passing the real height ensures the template pattern fills
                the entire page rather than stopping at the standard boundary.
                Defaults to REMARKABLE_HEIGHT.
            page_width: Actual page width in PDF points. Defaults to
                REMARKABLE_WIDTH.

        Returns:
            bool: True if successful, False otherwise
        """
        height = page_height if page_height is not None else self.REMARKABLE_HEIGHT
        width = page_width if page_width is not None else self.REMARKABLE_WIDTH

        if not template_name or template_name == "Blank":
            # For blank templates, create a blank PDF
            return self._create_blank_pdf(output_pdf, page_height=height, page_width=width)

        template_data = self.load_template(template_name)
        if not template_data:
            logging.debug(f"Could not load template {template_name}, using blank")
            return self._create_blank_pdf(output_pdf, page_height=height, page_width=width)

        try:
            # Create PDF with actual page dimensions
            c = canvas.Canvas(str(output_pdf), pagesize=(width, height))

            # Basic rendering: draw grid lines if it's a grid template
            if "Grid" in template_name or "grid" in template_name.lower():
                self._render_grid(c, template_data, page_height=height, page_width=width)
            elif "Lines" in template_name or "lines" in template_name.lower():
                self._render_lines(c, template_data, page_height=height, page_width=width)
            elif "Dots" in template_name or "dots" in template_name.lower():
                self._render_dots(c, template_data, page_height=height, page_width=width)

            c.save()
            return output_pdf.exists()

        except Exception as e:
            logging.debug(f"Failed to render template {template_name}: {e}")
            return self._create_blank_pdf(output_pdf, page_height=height, page_width=width)

    def _create_blank_pdf(
        self,
        output_pdf: Path,
        page_height: Optional[float] = None,
        page_width: Optional[float] = None,
    ) -> bool:
        """Create a blank PDF with the given page dimensions.

        Args:
            output_pdf: Path where the PDF should be saved
            page_height: Page height in PDF points (defaults to REMARKABLE_HEIGHT)
            page_width: Page width in PDF points (defaults to REMARKABLE_WIDTH)

        Returns:
            bool: True if successful
        """
        height = page_height if page_height is not None else self.REMARKABLE_HEIGHT
        width = page_width if page_width is not None else self.REMARKABLE_WIDTH
        try:
            c = canvas.Canvas(str(output_pdf), pagesize=(width, height))
            c.showPage()
            c.save()
            return True
        except Exception as e:
            logging.debug(f"Failed to create blank PDF: {e}")
            return False

    def _render_grid(
        self,
        c: canvas.Canvas,
        template_data: Dict,
        page_height: Optional[float] = None,
        page_width: Optional[float] = None,
    ):
        """Render a grid template pattern.

        Args:
            c: ReportLab canvas to draw on
            template_data: Template data dictionary
            page_height: Page height in PDF points (defaults to REMARKABLE_HEIGHT)
            page_width: Page width in PDF points (defaults to REMARKABLE_WIDTH)
        """
        height = page_height if page_height is not None else self.REMARKABLE_HEIGHT
        width = page_width if page_width is not None else self.REMARKABLE_WIDTH
        # Set light gray color for grid
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.3)

        # Try to extract grid size from template (in template pixels)
        grid_size_pixels = 52  # default for small grid
        constants = template_data.get("constants", [])
        for const in constants:
            if "gridSize" in const:
                grid_size_pixels = const["gridSize"]
                break

        # Convert grid size from template pixels to PDF points
        grid_size_points = grid_size_pixels * self.PIXELS_TO_POINTS

        # Draw vertical lines
        x = 0
        while x <= width:
            c.line(x, 0, x, height)
            x += grid_size_points

        # Draw horizontal lines
        y = 0
        while y <= height:
            c.line(0, y, width, y)
            y += grid_size_points

    def _render_lines(
        self,
        c: canvas.Canvas,
        template_data: Dict,
        page_height: Optional[float] = None,
        page_width: Optional[float] = None,
    ):
        """Render a lined template pattern.

        Args:
            c: ReportLab canvas to draw on
            template_data: Template data dictionary
            page_height: Page height in PDF points (defaults to REMARKABLE_HEIGHT)
            page_width: Page width in PDF points (defaults to REMARKABLE_WIDTH)
        """
        height = page_height if page_height is not None else self.REMARKABLE_HEIGHT
        width = page_width if page_width is not None else self.REMARKABLE_WIDTH

        # Set light gray color for lines
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.3)

        # Try to extract line spacing from template (in template pixels)
        # Typical reMarkable line spacing is around 40 pixels
        line_spacing_pixels = 40
        constants = template_data.get("constants", [])
        for const in constants:
            if "lineHeight" in const:
                line_spacing_pixels = const["lineHeight"]
                break

        # Convert line spacing from template pixels to PDF points
        line_spacing_points = line_spacing_pixels * self.PIXELS_TO_POINTS

        # Draw horizontal lines
        y = 0
        while y <= height:
            c.line(0, y, width, y)
            y += line_spacing_points

    def _render_dots(
        self,
        c: canvas.Canvas,
        template_data: Dict,
        page_height: Optional[float] = None,
        page_width: Optional[float] = None,
    ):
        """Render a dot grid template pattern.

        Args:
            c: ReportLab canvas to draw on
            template_data: Template data dictionary
            page_height: Page height in PDF points (defaults to REMARKABLE_HEIGHT)
            page_width: Page width in PDF points (defaults to REMARKABLE_WIDTH)
        """
        height = page_height if page_height is not None else self.REMARKABLE_HEIGHT
        width = page_width if page_width is not None else self.REMARKABLE_WIDTH

        # Set light gray color for dots
        c.setFillColorRGB(0.75, 0.75, 0.75)

        # Try to extract dot spacing from template (in template pixels)
        # Typical reMarkable dot spacing is around 30-40 pixels
        dot_spacing_pixels = 35
        constants = template_data.get("constants", [])
        for const in constants:
            if "dotSpacing" in const or "gridSize" in const:
                key = "dotSpacing" if "dotSpacing" in const else "gridSize"
                dot_spacing_pixels = const[key]
                break

        # Convert dot spacing from template pixels to PDF points
        dot_spacing_points = dot_spacing_pixels * self.PIXELS_TO_POINTS
        dot_radius = 0.5  # Small dots

        # Draw dot grid
        y = 0
        while y <= height:
            x = 0
            while x <= width:
                c.circle(x, y, dot_radius, fill=1, stroke=0)
                x += dot_spacing_points
            y += dot_spacing_points
