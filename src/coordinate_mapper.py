from __future__ import annotations

from dataclasses import dataclass

from .models import TemplateConfig


MM_PER_INCH = 25.4
POINTS_PER_INCH = 72.0


def mm_to_points(value_mm: float) -> float:
    return value_mm * POINTS_PER_INCH / MM_PER_INCH


def points_to_mm(points: float) -> float:
    return points * MM_PER_INCH / POINTS_PER_INCH


@dataclass(frozen=True)
class CoordinateMapper:
    physical_width_mm: float
    physical_height_mm: float
    pixel_width: int
    pixel_height: int

    @classmethod
    def from_template(cls, template: TemplateConfig) -> "CoordinateMapper":
        width_mm, height_mm = template.require_confirmed_size()
        if not template.source_pixel_width or not template.source_pixel_height:
            raise ValueError("Template has no pixel dimensions")
        return cls(
            physical_width_mm=width_mm,
            physical_height_mm=height_mm,
            pixel_width=template.source_pixel_width,
            pixel_height=template.source_pixel_height,
        )

    def mm_to_px(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        return (
            x_mm * self.pixel_width / self.physical_width_mm,
            y_mm * self.pixel_height / self.physical_height_mm,
        )

    def px_to_mm(self, x_px: float, y_px: float) -> tuple[float, float]:
        return (
            x_px * self.physical_width_mm / self.pixel_width,
            y_px * self.physical_height_mm / self.pixel_height,
        )

    def top_left_mm_to_pdf_points(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        return mm_to_points(x_mm), mm_to_points(self.physical_height_mm - y_mm)

