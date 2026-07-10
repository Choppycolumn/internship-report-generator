from __future__ import annotations

from dataclasses import dataclass

from .models import RegionMM, TemplateConfig, WritingLine


@dataclass(frozen=True)
class LineSlot:
    line_id: str
    x_start_mm: float
    x_end_mm: float
    y_mm: float

    @property
    def width_mm(self) -> float:
        return self.x_end_mm - self.x_start_mm


def _subtract_interval(
    segments: list[tuple[float, float]], blocked_start: float, blocked_end: float
) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for start, end in segments:
        if blocked_end <= start or blocked_start >= end:
            result.append((start, end))
            continue
        if blocked_start > start:
            result.append((start, min(blocked_start, end)))
        if blocked_end < end:
            result.append((max(blocked_end, start), end))
    return [(start, end) for start, end in result if end - start >= 5.0]


def _region_contains_y(region: RegionMM, y_mm: float) -> bool:
    return region.y_mm - 1e-6 <= y_mm <= region.bottom_mm + 1e-6


def usable_line_slots(config: TemplateConfig) -> list[LineSlot]:
    config.require_confirmed_size()
    if not config.content_regions:
        raise ValueError(f"Template '{config.template_id}' has no calibrated content region")
    if not config.writing_lines:
        raise ValueError(f"Template '{config.template_id}' has no calibrated writing lines")

    protected = (
        config.forbidden_regions
        + config.header_regions
        + config.fixed_text_regions
        + config.image_regions
        + config.table_regions
        + config.signature_regions
        + config.page_number_regions
    )
    slots: list[LineSlot] = []
    for line in sorted(config.writing_lines, key=lambda item: item.y_mm):
        content_segments: list[tuple[float, float]] = []
        for region in config.content_regions:
            if not _region_contains_y(region, line.y_mm):
                continue
            start = max(line.x_start_mm, region.x_mm)
            end = min(line.x_end_mm, region.right_mm)
            if end - start >= 5.0:
                content_segments.append((start, end))
        if not content_segments:
            continue
        for region in protected:
            if _region_contains_y(region, line.y_mm):
                content_segments = _subtract_interval(
                    content_segments, region.x_mm, region.right_mm
                )
        if not content_segments:
            continue
        start, end = max(content_segments, key=lambda segment: segment[1] - segment[0])
        slots.append(
            LineSlot(
                line_id=line.id,
                x_start_mm=round(start, 3),
                x_end_mm=round(end, 3),
                y_mm=line.y_mm,
            )
        )
    if not slots:
        raise ValueError(f"Template '{config.template_id}' has no usable writing lines")
    return slots


def template_for_page(template_sequence: list[str], zero_based_page_index: int) -> str:
    if not template_sequence:
        raise ValueError("template_sequence cannot be empty")
    return template_sequence[min(zero_based_page_index, len(template_sequence) - 1)]

