"""
Base Converter - Internal Helper Module

This is a helper module providing the base converter interface.
Do not run directly - use RemarkableSync.py as the entry point.

Entry Point:
    RemarkableSync.py convert [OPTIONS]

This module provides:
- Abstract base class for all ReMarkable file converters
- Common functionality for version detection and file operations
- Shared utilities for SVG/PDF conversion
"""

import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class BaseConverter(ABC):
    """Abstract base class for all ReMarkable file converters.

    This class defines the common interface and utility methods
    that all specific converter implementations should provide.
    """

    def __init__(self, name: str):
        """Initialize the base converter.

        Args:
            name: Human-readable name for this converter (e.g., "v5", "v6")
        """
        self.name = name
        self.logger = logging.getLogger(f"converter.{name}")

    @abstractmethod
    def can_convert(self, rm_file: Path) -> bool:
        """Check if this converter can handle the given .rm file.

        Args:
            rm_file: Path to the .rm file to check

        Returns:
            bool: True if this converter can handle the file format
        """
        raise NotImplementedError("Subclasses must implement can_convert method")

    @abstractmethod
    def convert_to_pdf(self, rm_file: Path, output_file: Path) -> bool:
        """Convert a .rm file to PDF.

        Args:
            rm_file: Path to the source .rm file
            output_file: Path where the PDF should be created

        Returns:
            bool: True if conversion was successful, False otherwise
        """
        raise NotImplementedError("Subclasses must implement convert_to_pdf method")

    def svg_to_pdf(self, svg_file: Path, pdf_file: Path) -> bool:
        """Convert SVG file to PDF using svglib and reportlab.

        This is a common utility function used by multiple converters
        that work through SVG intermediate format.

        Args:
            svg_file: Path to the source SVG file
            pdf_file: Path where the PDF should be created

        Returns:
            bool: True if conversion was successful, False otherwise
        """
        try:
            # Import conversion libraries at runtime to avoid hard dependencies
            from reportlab.graphics import renderPDF  # pylint: disable=import-outside-toplevel
            from svglib.svglib import svg2rlg  # pylint: disable=import-outside-toplevel
        except ImportError:
            self.logger.debug("svglib/reportlab not available for SVG to PDF conversion")
            return False

        try:
            # Convert SVG to reportlab drawing
            drawing = svg2rlg(str(svg_file))
            if drawing is None:
                self.logger.debug("Failed to parse SVG file: %s", svg_file.name)
                return False

            # Log drawing dimensions for debugging
            self.logger.debug(
                "SVG drawing dimensions: width=%s, height=%s", drawing.width, drawing.height
            )

            # ReMarkable 2 dimensions in PDF points (72 points per inch at 226 DPI)
            REMARKABLE_WIDTH = 447.5  # 1404 pixels / 226 DPI * 72

            # Scale uniformly so the width matches ReMarkable width,
            # but preserve the actual height (which may be taller than
            # standard for extended/infinite-scroll pages).
            if drawing.width > 0 and drawing.height > 0:
                scale = REMARKABLE_WIDTH / drawing.width

                if abs(scale - 1.0) > 0.01:  # Only scale if significantly different
                    self.logger.debug("Scaling drawing by factor: %s", scale)
                    drawing.height = drawing.height * scale
                    drawing.width = REMARKABLE_WIDTH
                    drawing.scale(scale, scale)

            # Render drawing to PDF
            # autoSize=1 makes the PDF match the drawing dimensions
            renderPDF.drawToFile(
                drawing,
                str(pdf_file),
                autoSize=1,
            )

            # Verify PDF was created and has reasonable size
            if pdf_file.exists() and pdf_file.stat().st_size > 500:
                self.logger.debug("SVG to PDF conversion successful: %s", pdf_file.name)
                return True

            self.logger.debug("PDF creation failed or file too small: %s", pdf_file.name)
            return False

        except Exception as e:  # noqa: BLE001
            self.logger.debug("SVG to PDF conversion error for %s: %s", svg_file.name, e)
            return False

    def copy_existing_pdf(self, source_pdf: Path, target_pdf: Path) -> bool:
        """Copy an existing PDF file to the target location.

        Args:
            source_pdf: Path to the source PDF file
            target_pdf: Path where the PDF should be copied

        Returns:
            bool: True if copy was successful, False otherwise
        """
        try:
            # Ensure target directory exists
            target_pdf.parent.mkdir(parents=True, exist_ok=True)

            # Copy the PDF file
            shutil.copy2(source_pdf, target_pdf)

            # Verify the copy was successful
            if target_pdf.exists() and target_pdf.stat().st_size > 0:
                self.logger.debug("PDF copy successful: %s -> %s", source_pdf.name, target_pdf.name)
                return True

            self.logger.debug("PDF copy failed: %s", source_pdf.name)
            return False

        except Exception as e:  # noqa: BLE001
            self.logger.debug("PDF copy error for %s: %s", source_pdf.name, e)
            return False

    def detect_version(self, rm_file: Path) -> Optional[str]:
        """Detect the version of a ReMarkable file by examining its header.

        ReMarkable files have version information in the first few bytes.
        This method reads the header to determine the file format version.

        Args:
            rm_file: Path to the .rm file to analyze

        Returns:
            Optional[str]: Version string (e.g., "5", "6") or None if undetectable
        """
        try:
            with open(rm_file, "rb") as f:
                header = f.read(50).decode("utf-8", errors="ignore")

                # Check for known version patterns
                if "version=6" in header:
                    return "6"
                if "version=5" in header:
                    return "5"
                if "version=4" in header:
                    return "4"
                if "version=3" in header:
                    return "3"

                # Try to detect by file size and content patterns
                f.seek(0)
                content = f.read(32)
                if len(content) > 8:
                    # Additional heuristics could go here
                    pass
                return None

        except Exception as e:  # noqa: BLE001
            self.logger.debug("Version detection failed for %s: %s", rm_file.name, e)
            return None

    def __str__(self) -> str:
        """Return string representation of the converter."""
        return f"ReMarkable {self.name} Converter"

    def __repr__(self) -> str:
        """Return detailed string representation of the converter."""
        return f"BaseConverter(name='{self.name}')"
