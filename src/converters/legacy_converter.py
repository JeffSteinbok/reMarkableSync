"""Rendering for the v4/v5 binary stroke formats."""

import math
import struct
from pathlib import Path

from .base_converter import BaseConverter


class LegacyConverter(BaseConverter):
    def can_convert(self, rm_file: Path) -> bool:
        return self.detect_version(rm_file) == self.name.removeprefix("v")

    def convert_to_pdf(self, rm_file: Path, output_file: Path) -> bool:
        try:
            from reportlab.pdfgen.canvas import Canvas

            data = rm_file.read_bytes()
            if not self.can_convert(rm_file):
                raise ValueError(f"Expected a {self.name} .rm header")
            offset = 43

            def read(fmt):
                nonlocal offset
                size = struct.calcsize(fmt)
                result = struct.unpack_from(fmt, data, offset)
                offset += size
                return result

            strokes = []
            height = 1872.0
            (layers,) = read("<I")
            if layers > len(data) // 4:
                raise ValueError("Invalid layer count")
            for _ in range(layers):
                (count,) = read("<I")
                if count > (len(data) - offset) // 20:
                    raise ValueError("Invalid stroke count")
                for _ in range(count):
                    if self.name == "v5":
                        pen, color, _, width, _, point_count = read("<IIIfII")
                    else:
                        pen, color, _, width, point_count = read("<IIIfI")
                    size = point_count * 24
                    if size > len(data) - offset:
                        raise ValueError("Truncated stroke points")
                    points = list(struct.iter_unpack("<ffffff", data[offset : offset + size]))
                    offset += size
                    if not math.isfinite(width) or width < 0:
                        raise ValueError("Invalid stroke width")
                    for x, y, _, _, point_width, _ in points:
                        if not all(math.isfinite(v) for v in (x, y, point_width)):
                            raise ValueError("Invalid stroke coordinates")
                        height = max(height, y + max(width, point_width, 1))
                    strokes.append((pen, color, width, points))
            if offset != len(data):
                raise ValueError("Unexpected trailing stroke data")

            scale = 72 / 226
            output_file.parent.mkdir(parents=True, exist_ok=True)
            canvas = Canvas(str(output_file), pagesize=(1404 * scale, height * scale))
            canvas.scale(scale, scale)
            canvas.setLineCap(1)
            canvas.setLineJoin(1)
            colors = {0: (0, 0, 0), 1: (0.5, 0.5, 0.5), 2: (1, 1, 1)}
            for pen, color, width, points in strokes:
                if not points or pen in (6, 8):
                    continue
                rgb = colors.get(color, (0, 0, 0))
                canvas.setStrokeColorRGB(*rgb)
                canvas.setFillColorRGB(*rgb)
                canvas.setStrokeAlpha(0.25 if pen in (5, 18) else 1)
                if len(points) == 1:
                    x, y, _, _, point_width, _ = points[0]
                    canvas.circle(x, height - y, max(point_width, width, 0.1) / 2, fill=1)
                else:
                    for first, second in zip(points, points[1:], strict=False):
                        canvas.setLineWidth(max((first[4] + second[4]) / 2, width, 0.1))
                        canvas.line(first[0], height - first[1], second[0], height - second[1])
            canvas.showPage()
            canvas.save()
            return True
        except (ImportError, OSError, ValueError, struct.error):
            self.logger.exception("Could not render %s page %s", self.name, rm_file.name)
            return False

    def get_requirements(self) -> list[str]:
        return ["reportlab Python library"]
