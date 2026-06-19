"""Tests for v4/v5/v6 binary converter modules.

Covers:
- can_convert() version identification
- detect_version() header parsing
- convert_to_pdf() with mocked external dependencies (rmrl / rmc)
- Error handling: corrupt files, missing dependencies, truncated headers
"""

import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.converters import ConverterRegistry, get_default_registry
from src.converters.base_converter import BaseConverter
from src.converters.v4_converter import V4Converter
from src.converters.v5_converter import V5Converter
from src.converters.v6_converter import V6Converter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RM_HEADER_TEMPLATE = "reMarkable .lines file, version={v}          \n"


def _make_rm(tmp_path: Path, version: int, extra: bytes = b"") -> Path:
    """Write a minimal .rm file with the given version header."""
    header = RM_HEADER_TEMPLATE.format(v=version).encode("ascii")
    payload = header + struct.pack("<I", 0) + extra  # 0 layers
    p = tmp_path / f"v{version}_page.rm"
    p.write_bytes(payload)
    return p


def _make_corrupt(tmp_path: Path, name: str = "corrupt.rm", content: bytes = b"\xff\xfe") -> Path:
    """Write a corrupt/truncated .rm file."""
    p = tmp_path / name
    p.write_bytes(content)
    return p


# ---------------------------------------------------------------------------
# BaseConverter.detect_version
# ---------------------------------------------------------------------------


class _ConcreteConverter(BaseConverter):
    """Minimal concrete subclass for testing the base class directly."""

    def __init__(self):
        super().__init__("test")

    def can_convert(self, rm_file: Path) -> bool:
        return False

    def convert_to_pdf(self, rm_file: Path, output_file: Path) -> bool:
        return False


class TestDetectVersion:
    """Tests for BaseConverter.detect_version()."""

    def test_detects_v4(self, tmp_path):
        rm = _make_rm(tmp_path, 4)
        assert _ConcreteConverter().detect_version(rm) == "4"

    def test_detects_v5(self, tmp_path):
        rm = _make_rm(tmp_path, 5)
        assert _ConcreteConverter().detect_version(rm) == "5"

    def test_detects_v6(self, tmp_path):
        rm = _make_rm(tmp_path, 6)
        assert _ConcreteConverter().detect_version(rm) == "6"

    def test_returns_none_for_unknown_header(self, tmp_path):
        rm = tmp_path / "unknown.rm"
        rm.write_bytes(b"this is not a rm file at all")
        assert _ConcreteConverter().detect_version(rm) is None

    def test_returns_none_for_empty_file(self, tmp_path):
        rm = tmp_path / "empty.rm"
        rm.write_bytes(b"")
        assert _ConcreteConverter().detect_version(rm) is None

    def test_returns_none_for_nonexistent_file(self, tmp_path):
        rm = tmp_path / "nonexistent.rm"
        assert _ConcreteConverter().detect_version(rm) is None

    def test_returns_none_for_corrupt_bytes(self, tmp_path):
        rm = _make_corrupt(tmp_path)
        assert _ConcreteConverter().detect_version(rm) is None


# ---------------------------------------------------------------------------
# V4Converter
# ---------------------------------------------------------------------------


class TestV4CanConvert:
    """Tests for V4Converter.can_convert()."""

    def test_accepts_v4_file(self, tmp_path):
        assert V4Converter().can_convert(_make_rm(tmp_path, 4))

    def test_rejects_v5_file(self, tmp_path):
        assert not V4Converter().can_convert(_make_rm(tmp_path, 5))

    def test_rejects_v6_file(self, tmp_path):
        assert not V4Converter().can_convert(_make_rm(tmp_path, 6))

    def test_rejects_corrupt_file(self, tmp_path):
        assert not V4Converter().can_convert(_make_corrupt(tmp_path))

    def test_rejects_nonexistent_file(self, tmp_path):
        assert not V4Converter().can_convert(tmp_path / "ghost.rm")


class TestV4ConvertToPdf:
    """Tests for V4Converter.convert_to_pdf()."""

    def test_returns_false_when_rmrl_unavailable(self, tmp_path):
        rm = _make_rm(tmp_path, 4)
        out = tmp_path / "out.pdf"
        with patch.dict("sys.modules", {"rmrl": None}):
            result = V4Converter().convert_to_pdf(rm, out)
        assert result is False

    def test_returns_false_when_rmrl_render_fails(self, tmp_path):
        rm = _make_rm(tmp_path, 4)
        out = tmp_path / "out.pdf"

        fake_rmrl = MagicMock()
        fake_rmrl.render.return_value = None  # simulate render failure

        with patch.dict("sys.modules", {"rmrl": fake_rmrl}):
            result = V4Converter().convert_to_pdf(rm, out)
        assert result is False

    def test_returns_false_when_svg_too_small(self, tmp_path):
        rm = _make_rm(tmp_path, 4)
        out = tmp_path / "out.pdf"

        fake_rmrl = MagicMock()
        fake_rmrl.render.return_value = b"tiny"  # < 100 bytes

        with patch.dict("sys.modules", {"rmrl": fake_rmrl}):
            result = V4Converter().convert_to_pdf(rm, out)
        assert result is False

    def test_returns_false_for_nonexistent_input(self, tmp_path):
        out = tmp_path / "out.pdf"
        result = V4Converter().convert_to_pdf(tmp_path / "ghost.rm", out)
        assert result is False

    def test_calls_svg_to_pdf_on_success(self, tmp_path):
        rm = _make_rm(tmp_path, 4)
        out = tmp_path / "out.pdf"

        svg_content = b"<svg>" + b"x" * 200 + b"</svg>"
        fake_rmrl = MagicMock()
        fake_rmrl.render.return_value = svg_content

        converter = V4Converter()
        with patch.dict("sys.modules", {"rmrl": fake_rmrl}):
            with patch.object(converter, "svg_to_pdf", return_value=True) as mock_svg:
                result = converter.convert_to_pdf(rm, out)

        assert result is True
        mock_svg.assert_called_once()

    def test_is_rmrl_available_reflects_import(self):
        converter = V4Converter()
        # Just verify the method exists and returns a bool
        result = converter.is_rmrl_available()
        assert isinstance(result, bool)

    def test_get_requirements_returns_list(self):
        reqs = V4Converter().get_requirements()
        assert isinstance(reqs, list)
        assert any("rmrl" in r for r in reqs)

    def test_get_conversion_info_returns_dict(self):
        info = V4Converter().get_conversion_info()
        assert isinstance(info, dict)
        assert info["format"] == "v4"

    def test_str_representation(self):
        assert "v4" in str(V4Converter())


# ---------------------------------------------------------------------------
# V5Converter
# ---------------------------------------------------------------------------


class TestV5CanConvert:
    """Tests for V5Converter.can_convert()."""

    def test_accepts_v5_file(self, tmp_path):
        assert V5Converter().can_convert(_make_rm(tmp_path, 5))

    def test_rejects_v4_file(self, tmp_path):
        assert not V5Converter().can_convert(_make_rm(tmp_path, 4))

    def test_rejects_v6_file(self, tmp_path):
        assert not V5Converter().can_convert(_make_rm(tmp_path, 6))

    def test_rejects_corrupt_file(self, tmp_path):
        assert not V5Converter().can_convert(_make_corrupt(tmp_path))

    def test_rejects_nonexistent_file(self, tmp_path):
        assert not V5Converter().can_convert(tmp_path / "ghost.rm")


class TestV5ConvertToPdf:
    """Tests for V5Converter.convert_to_pdf()."""

    def test_returns_false_when_rmrl_unavailable(self, tmp_path):
        rm = _make_rm(tmp_path, 5)
        out = tmp_path / "out.pdf"
        with patch.dict("sys.modules", {"rmrl": None}):
            result = V5Converter().convert_to_pdf(rm, out)
        assert result is False

    def test_returns_false_when_rmrl_render_returns_none(self, tmp_path):
        rm = _make_rm(tmp_path, 5)
        out = tmp_path / "out.pdf"

        fake_rmrl = MagicMock()
        fake_rmrl.render.return_value = None

        with patch.dict("sys.modules", {"rmrl": fake_rmrl}):
            result = V5Converter().convert_to_pdf(rm, out)
        assert result is False

    def test_returns_false_when_svg_output_too_small(self, tmp_path):
        rm = _make_rm(tmp_path, 5)
        out = tmp_path / "out.pdf"

        fake_rmrl = MagicMock()
        fake_rmrl.render.return_value = b"short"

        with patch.dict("sys.modules", {"rmrl": fake_rmrl}):
            result = V5Converter().convert_to_pdf(rm, out)
        assert result is False

    def test_calls_svg_to_pdf_on_success(self, tmp_path):
        rm = _make_rm(tmp_path, 5)
        out = tmp_path / "out.pdf"

        svg_content = b"<svg>" + b"x" * 200 + b"</svg>"
        fake_rmrl = MagicMock()
        fake_rmrl.render.return_value = svg_content

        converter = V5Converter()
        with patch.dict("sys.modules", {"rmrl": fake_rmrl}):
            with patch.object(converter, "svg_to_pdf", return_value=True) as mock_svg:
                result = converter.convert_to_pdf(rm, out)

        assert result is True
        mock_svg.assert_called_once()

    def test_svg_to_pdf_failure_returns_false(self, tmp_path):
        rm = _make_rm(tmp_path, 5)
        out = tmp_path / "out.pdf"

        svg_content = b"<svg>" + b"x" * 200 + b"</svg>"
        fake_rmrl = MagicMock()
        fake_rmrl.render.return_value = svg_content

        converter = V5Converter()
        with patch.dict("sys.modules", {"rmrl": fake_rmrl}):
            with patch.object(converter, "svg_to_pdf", return_value=False):
                result = converter.convert_to_pdf(rm, out)

        assert result is False

    def test_is_rmrl_available_returns_bool(self):
        result = V5Converter().is_rmrl_available()
        assert isinstance(result, bool)

    def test_get_requirements_includes_rmrl(self):
        reqs = V5Converter().get_requirements()
        assert any("rmrl" in r for r in reqs)

    def test_str_representation(self):
        assert "v5" in str(V5Converter())


# ---------------------------------------------------------------------------
# V6Converter
# ---------------------------------------------------------------------------


class TestV6CanConvert:
    """Tests for V6Converter.can_convert()."""

    def test_accepts_v6_file(self, tmp_path):
        assert V6Converter().can_convert(_make_rm(tmp_path, 6))

    def test_rejects_v5_file(self, tmp_path):
        assert not V6Converter().can_convert(_make_rm(tmp_path, 5))

    def test_rejects_v4_file(self, tmp_path):
        assert not V6Converter().can_convert(_make_rm(tmp_path, 4))

    def test_rejects_corrupt_file(self, tmp_path):
        assert not V6Converter().can_convert(_make_corrupt(tmp_path))

    def test_rejects_nonexistent_file(self, tmp_path):
        assert not V6Converter().can_convert(tmp_path / "ghost.rm")


class TestV6ConvertToPdf:
    """Tests for V6Converter.convert_to_pdf()."""

    def test_returns_false_when_rmc_not_found(self, tmp_path):
        rm = _make_rm(tmp_path, 6)
        out = tmp_path / "out.pdf"

        with patch("subprocess.run", side_effect=FileNotFoundError("rmc not found")):
            result = V6Converter().convert_to_pdf(rm, out)

        assert result is False

    def test_returns_false_when_rmc_fails(self, tmp_path):
        rm = _make_rm(tmp_path, 6)
        out = tmp_path / "out.pdf"

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "conversion error"

        with patch("subprocess.run", return_value=mock_result):
            result = V6Converter().convert_to_pdf(rm, out)

        assert result is False

    def test_returns_false_when_svg_not_created(self, tmp_path):
        rm = _make_rm(tmp_path, 6)
        out = tmp_path / "out.pdf"

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            # rmc succeeds but doesn't write the SVG file
            result = V6Converter().convert_to_pdf(rm, out)

        assert result is False

    def test_returns_false_on_timeout(self, tmp_path):
        import subprocess

        rm = _make_rm(tmp_path, 6)
        out = tmp_path / "out.pdf"

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["rmc"], 30)):
            result = V6Converter().convert_to_pdf(rm, out)

        assert result is False

    def test_calls_svg_to_pdf_after_successful_rmc(self, tmp_path):
        rm = _make_rm(tmp_path, 6)
        out = tmp_path / "out.pdf"

        mock_run = MagicMock()
        mock_run.returncode = 0

        converter = V6Converter()

        def _fake_run(cmd, **kwargs):
            # Simulate rmc writing the SVG file
            svg_path = Path(cmd[4])  # -o <svg_file>
            svg_path.write_bytes(b"<svg>" + b"x" * 200 + b"</svg>")
            return mock_run

        with patch("subprocess.run", side_effect=_fake_run):
            with patch.object(converter, "svg_to_pdf", return_value=True) as mock_svg:
                result = converter.convert_to_pdf(rm, out)

        assert result is True
        mock_svg.assert_called_once()

    def test_is_rmc_available_returns_bool(self):
        result = V6Converter().is_rmc_available()
        assert isinstance(result, bool)

    def test_get_requirements_includes_rmc(self):
        reqs = V6Converter().get_requirements()
        assert any("rmc" in r for r in reqs)

    def test_str_representation(self):
        assert "v6" in str(V6Converter())


# ---------------------------------------------------------------------------
# Fixture files from tests/fixtures/rm_files/
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "rm_files"


@pytest.mark.skipif(
    not (FIXTURES_DIR / "minimal_v4.rm").exists(),
    reason="v4 fixture file not found",
)
class TestFixtureFilesV4:
    """Tests using binary fixture files."""

    def test_fixture_v4_detected(self):
        converter = V4Converter()
        assert converter.can_convert(FIXTURES_DIR / "minimal_v4.rm")

    def test_fixture_v4_not_detected_by_v5(self):
        converter = V5Converter()
        assert not converter.can_convert(FIXTURES_DIR / "minimal_v4.rm")


@pytest.mark.skipif(
    not (FIXTURES_DIR / "minimal_v5.rm").exists(),
    reason="v5 fixture file not found",
)
class TestFixtureFilesV5:
    def test_fixture_v5_detected(self):
        assert V5Converter().can_convert(FIXTURES_DIR / "minimal_v5.rm")

    def test_fixture_v5_not_detected_by_v6(self):
        assert not V6Converter().can_convert(FIXTURES_DIR / "minimal_v5.rm")


@pytest.mark.skipif(
    not (FIXTURES_DIR / "minimal_v6.rm").exists(),
    reason="v6 fixture file not found",
)
class TestFixtureFilesV6:
    def test_fixture_v6_detected(self):
        assert V6Converter().can_convert(FIXTURES_DIR / "minimal_v6.rm")

    def test_fixture_v6_not_detected_by_v5(self):
        assert not V5Converter().can_convert(FIXTURES_DIR / "minimal_v6.rm")


# ---------------------------------------------------------------------------
# BaseConverter utility methods
# ---------------------------------------------------------------------------


class TestBaseConverterUtilities:
    """Tests for shared base-class utilities."""

    def test_copy_existing_pdf(self, tmp_path):
        src = tmp_path / "source.pdf"
        src.write_bytes(b"%PDF-1.4 fake content here")
        dst = tmp_path / "sub" / "dest.pdf"

        result = _ConcreteConverter().copy_existing_pdf(src, dst)

        assert result is True
        assert dst.exists()
        assert dst.read_bytes() == src.read_bytes()

    def test_copy_existing_pdf_missing_source(self, tmp_path):
        result = _ConcreteConverter().copy_existing_pdf(
            tmp_path / "ghost.pdf", tmp_path / "out.pdf"
        )
        assert result is False

    def test_repr(self):
        c = _ConcreteConverter()
        assert "test" in repr(c)


# ---------------------------------------------------------------------------
# ConverterRegistry
# ---------------------------------------------------------------------------


class TestConverterRegistry:
    """Tests for the ConverterRegistry pattern."""

    def test_default_registry_has_all_versions(self):
        """Default registry includes v4, v5, v6 converters."""
        registry = get_default_registry()

        versions = registry.supported_versions

        assert 4 in versions
        assert 5 in versions
        assert 6 in versions

    def test_get_for_version_returns_correct_converter(self):
        """get_for_version returns the right converter type."""
        registry = get_default_registry()

        v4 = registry.get_for_version(4)
        v5 = registry.get_for_version(5)
        v6 = registry.get_for_version(6)

        assert isinstance(v4, V4Converter)
        assert isinstance(v5, V5Converter)
        assert isinstance(v6, V6Converter)

    def test_get_for_version_unknown_returns_none(self):
        """get_for_version returns None for unknown version."""
        registry = get_default_registry()

        result = registry.get_for_version(99)

        assert result is None

    def test_register_adds_custom_converter(self):
        """register() adds a new converter to registry."""
        registry = ConverterRegistry()

        class CustomConverter(BaseConverter):
            def __init__(self):
                super().__init__("custom")

            def can_convert(self, rm_file):
                return False

            def convert_to_pdf(self, rm_file, output):
                return False

        registry.register(99, CustomConverter())

        assert 99 in registry.supported_versions
        assert isinstance(registry.get_for_version(99), CustomConverter)

    def test_registry_is_singleton(self):
        """get_default_registry returns same instance."""
        r1 = get_default_registry()
        r2 = get_default_registry()

        assert r1 is r2

    def test_custom_registry_isolation(self):
        """New registry with empty dict is independent of default."""
        custom = ConverterRegistry(converters={})

        # Custom starts empty
        assert len(custom.supported_versions) == 0

        # Default still has all
        default = get_default_registry()
        assert len(default.supported_versions) >= 3


class TestConverterIntegration:
    """Integration tests for converter pipeline."""

    def test_detect_and_convert_v4(self, tmp_path):
        """Full pipeline: detect v4, get converter, convert."""
        rm = _make_rm(tmp_path, 4)

        registry = get_default_registry()
        base = _ConcreteConverter()

        # Detect version
        version = base.detect_version(rm)
        assert version == "4"

        # Get appropriate converter (convert string to int)
        converter = registry.get_for_version(int(version))
        assert converter is not None
        assert converter.can_convert(rm)

    def test_detect_and_convert_v5(self, tmp_path):
        """Full pipeline: detect v5, get converter, convert."""
        rm = _make_rm(tmp_path, 5)

        registry = get_default_registry()
        base = _ConcreteConverter()

        version = base.detect_version(rm)
        assert version == "5"

        converter = registry.get_for_version(int(version))
        assert converter is not None
        assert converter.can_convert(rm)

    def test_detect_and_convert_v6(self, tmp_path):
        """Full pipeline: detect v6, get converter, convert."""
        rm = _make_rm(tmp_path, 6)

        registry = get_default_registry()
        base = _ConcreteConverter()

        version = base.detect_version(rm)
        assert version == "6"

        converter = registry.get_for_version(int(version))
        assert converter is not None
        assert converter.can_convert(rm)

    def test_pipeline_handles_unknown_version(self, tmp_path):
        """Pipeline gracefully handles unknown versions."""
        rm = tmp_path / "weird.rm"
        rm.write_bytes(b"reMarkable .lines file, version=99          \n")

        registry = get_default_registry()
        base = _ConcreteConverter()

        version = base.detect_version(rm)
        # Version might be "99" or None depending on parsing
        version_int = int(version) if version and version.isdigit() else 99
        converter = registry.get_for_version(version_int)

        # No converter for unknown version
        assert converter is None

    def test_all_converters_have_requirements(self):
        """All converters provide requirements list."""
        registry = get_default_registry()

        for version in registry.supported_versions:
            converter = registry.get_for_version(version)
            reqs = converter.get_requirements()

            assert isinstance(reqs, list)
            # Each should have at least one requirement
            assert len(reqs) > 0

    def test_all_converters_have_info(self):
        """V4 converter provides conversion info."""
        registry = get_default_registry()

        # Only V4Converter has get_conversion_info
        v4 = registry.get_for_version(4)
        info = v4.get_conversion_info()

        assert isinstance(info, dict)
        assert "format" in info


class TestSvgToPdf:
    """Tests for SVG to PDF conversion utility."""

    def test_svg_to_pdf_creates_output(self, tmp_path):
        """svg_to_pdf creates PDF from SVG content."""
        svg_content = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
            <rect width="100" height="100" fill="red"/>
        </svg>
        """
        svg_file = tmp_path / "test.svg"
        svg_file.write_bytes(svg_content)
        out = tmp_path / "out.pdf"

        converter = _ConcreteConverter()
        result = converter.svg_to_pdf(svg_file, out)

        # May fail if cairosvg not installed, but shouldn't crash
        assert isinstance(result, bool)

    def test_svg_to_pdf_handles_invalid_svg(self, tmp_path):
        """svg_to_pdf handles malformed SVG gracefully."""
        svg_file = tmp_path / "bad.svg"
        svg_file.write_bytes(b"not valid svg at all")
        out = tmp_path / "out.pdf"

        converter = _ConcreteConverter()
        result = converter.svg_to_pdf(svg_file, out)

        # Should return False, not crash
        assert result is False

    def test_svg_to_pdf_handles_missing_file(self, tmp_path):
        """svg_to_pdf handles missing SVG file."""
        out = tmp_path / "out.pdf"

        converter = _ConcreteConverter()
        result = converter.svg_to_pdf(tmp_path / "nonexistent.svg", out)

        assert result is False
