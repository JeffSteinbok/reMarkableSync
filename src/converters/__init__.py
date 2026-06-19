"""
ReMarkable File Converters Package

This package contains converter classes for different ReMarkable file formats.
Each converter handles a specific version of the ReMarkable file format.
"""

from typing import Dict, Optional, Type

from .base_converter import BaseConverter
from .v4_converter import V4Converter
from .v5_converter import V5Converter
from .v6_converter import V6Converter

__all__ = ["BaseConverter", "V5Converter", "V6Converter", "V4Converter", "ConverterRegistry"]


class ConverterRegistry:
    """Registry for ReMarkable file format converters.

    Provides a centralized way to manage and access converters for different
    file format versions. Supports dependency injection for testing.

    Example:
        registry = ConverterRegistry()
        converter = registry.get_for_version(6)
        if converter:
            converter.convert_to_pdf(rm_file, output_file)
    """

    # Default converter classes by version
    _DEFAULT_CONVERTERS: Dict[int, Type[BaseConverter]] = {
        4: V4Converter,
        5: V5Converter,
        6: V6Converter,
    }

    def __init__(self, converters: Optional[Dict[int, BaseConverter]] = None):
        """Initialize the converter registry.

        Args:
            converters: Optional dict mapping version numbers to converter instances.
                       If not provided, creates default converters.
        """
        if converters is not None:
            self._converters = converters
        else:
            self._converters = {version: cls() for version, cls in self._DEFAULT_CONVERTERS.items()}

    def get_for_version(self, version: int) -> Optional[BaseConverter]:
        """Get converter for a specific file format version.

        Args:
            version: The ReMarkable file format version (3, 4, 5, or 6)

        Returns:
            The converter instance for that version, or None if unsupported.
        """
        return self._converters.get(version)

    def register(self, version: int, converter: BaseConverter) -> None:
        """Register a converter for a specific version.

        Args:
            version: The file format version this converter handles.
            converter: The converter instance to register.
        """
        self._converters[version] = converter

    @property
    def supported_versions(self) -> list[int]:
        """Get list of supported version numbers."""
        return sorted(self._converters.keys())

    def __contains__(self, version: int) -> bool:
        """Check if a version is supported."""
        return version in self._converters


# Default registry instance for convenience
_default_registry: Optional[ConverterRegistry] = None


def get_default_registry() -> ConverterRegistry:
    """Get or create the default converter registry.

    Returns:
        The default ConverterRegistry instance.
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = ConverterRegistry()
    return _default_registry
