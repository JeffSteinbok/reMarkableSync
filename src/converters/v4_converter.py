"""Converter for legacy reMarkable v4 stroke files."""

from .legacy_converter import LegacyConverter


class V4Converter(LegacyConverter):
    def __init__(self):
        super().__init__("v4")

    def get_conversion_info(self) -> dict:
        return {"format": "v4", "support_level": "supported", "renderer": "reportlab"}
