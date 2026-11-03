"""Converter for legacy reMarkable v5 stroke files."""

from .legacy_converter import LegacyConverter


class V5Converter(LegacyConverter):
    def __init__(self):
        super().__init__("v5")
