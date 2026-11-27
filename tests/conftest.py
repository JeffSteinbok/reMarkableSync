"""
Test configuration and fixtures for ReMarkable PDF conversion tests.

Provides common fixtures and utilities for testing PDF conversion functionality
across different ReMarkable file format versions.
"""

import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest

# Add the project root to the Python path so imports work
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def runtime_dir(monkeypatch, tmp_path) -> Path:
    directory = tmp_path / "runtime"
    monkeypatch.setattr("src.config.get_runtime_dir", lambda: directory)
    return directory


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test outputs.

    Yields:
        Path: Temporary directory that gets cleaned up after test
    """
    with tempfile.TemporaryDirectory() as temp_dir_str:
        yield Path(temp_dir_str)


@pytest.fixture
def test_assets_dir() -> Path:
    """Get the test assets directory path.

    Returns:
        Path: Path to the test assets directory
    """
    return Path(__file__).parent / "assets"


@pytest.fixture
def test_output_dir() -> Path:
    """Get the test output directory path.

    Returns:
        Path: Path to the test output directory
    """
    return Path(__file__).parent / "output"


@pytest.fixture
def v3_assets_dir(test_assets_dir: Path) -> Path:
    """Get the v3 test assets directory.

    Args:
        test_assets_dir: Base test assets directory

    Returns:
        Path: Path to v3 test assets
    """
    return test_assets_dir / "v3"


@pytest.fixture
def v4_assets_dir(test_assets_dir: Path) -> Path:
    """Get the v4 test assets directory.

    Args:
        test_assets_dir: Base test assets directory

    Returns:
        Path: Path to v4 test assets
    """
    return test_assets_dir / "v4"


@pytest.fixture
def v5_assets_dir(test_assets_dir: Path) -> Path:
    """Get the v5 test assets directory.

    Args:
        test_assets_dir: Base test assets directory

    Returns:
        Path: Path to v5 test assets
    """
    return test_assets_dir / "v5"


@pytest.fixture
def v6_assets_dir(test_assets_dir: Path) -> Path:
    """Get the v6 test assets directory.

    Args:
        test_assets_dir: Base test assets directory

    Returns:
        Path: Path to v6 test assets
    """
    return test_assets_dir / "v6"


@pytest.fixture(autouse=True)
def setup_test_output_dir(test_output_dir: Path):
    """Ensure test output directory exists before each test.

    Args:
        test_output_dir: Test output directory path
    """
    test_output_dir.mkdir(parents=True, exist_ok=True)


# Test helper functions
def is_valid_pdf(pdf_path: Path) -> bool:
    """Check if a file is a valid PDF by checking its header.

    Args:
        pdf_path: Path to the PDF file to check

    Returns:
        bool: True if file appears to be a valid PDF
    """
    if not pdf_path.exists():
        return False

    try:
        with open(pdf_path, "rb") as f:
            header = f.read(4)
            return header == b"%PDF"
    except (OSError, IOError):
        return False


def get_file_size(file_path: Path) -> int:
    """Get the size of a file in bytes.

    Args:
        file_path: Path to the file

    Returns:
        int: File size in bytes, 0 if file doesn't exist
    """
    if not file_path.exists():
        return 0

    try:
        return file_path.stat().st_size
    except (OSError, IOError):
        return 0


# Constants for test validation
MIN_PDF_SIZE = 100  # Minimum size for a valid PDF file in bytes
MIN_CONVERTED_PDF_SIZE = 1000  # Minimum size for a converted PDF with content
