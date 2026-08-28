from __future__ import annotations

from dataclasses import dataclass

from .models import ContentRegion, RegionMM, TemplateConfig, WritingLine


@dataclass(frozen=True)
class LineSlot:
    line_id: str
    x_start_mm: float
    x_end_mm: float
    y_mm: float
    region_id: str = ""
    flow_order: int = 0
    column_index: int = 0
    baseline_offset_mm: float | None = None
    layout_mode: str = "lined"

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


def content_region_columns(region: ContentRegion) -> list[tuple[float, float]]:
    usable_width = region.width_mm - region.column_gap_mm * (region.columns - 1)
    if usable_width <= 0:
        return []
    column_width = usable_width / region.columns
    return [
        (
            region.x_mm + column_index * (column_width + region.column_gap_mm),
            region.x_mm
            + column_index * (column_width + region.column_gap_mm)
            + column_width,
        )
        for column_index in range(region.columns)
    ]


def usable_line_slots(config: TemplateConfig) -> list[LineSlot]:
    config.require_confirmed_size()
    if not config.content_regions:
        raise ValueError(f"Template '{config.template_id}' has no calibrated content region")

    protected = (
        config.forbidden_regions
        + config.header_regions
        + config.fixed_text_regions
        + config.image_regions
        + config.table_regions
        + config.signature_regions
        + config.page_number_regions
        + list(config.fields.values())
        + [table.region for table in config.tables.values() if table.region is not None]
        + [cell for table in config.tables.values() for cell in table.cells]
    )
    slots: list[LineSlot] = []
    ordered_regions = sorted(
        enumerate(config.content_regions),
        key=lambda pair: (pair[1].flow_order, pair[0]),
    )
    for region_position, region in ordered_regions:
        columns = content_region_columns(region)
        if not columns:
            continue
        if region.layout_mode == "free":
            spacing = region.line_spacing_mm or 5.0
            baseline = region.baseline_start_mm
            if baseline is None:
                baseline = region.y_mm + min(spacing, max(0.0, region.height_mm - 0.1))
            if baseline > region.bottom_mm + 1e-6:
                continue
            baselines: list[float] = []
            while baseline <= region.bottom_mm + 1e-6:
                baselines.append(baseline)
                baseline += spacing
            for column_index, (column_start, column_end) in enumerate(columns):
                for line_index, y_mm in enumerate(baselines, 1):
                    segments = [(column_start, column_end)]
                    for blocked in protected:
                        if _region_contains_y(blocked, y_mm):
                            segments = _subtract_interval(segments, blocked.x_mm, blocked.right_mm)
                    if not segments:
                        continue
                    start, end = max(segments, key=lambda segment: segment[1] - segment[0])
                    slots.append(
                        LineSlot(
                            line_id=f"{region.id or region_position}_free_{column_index + 1}_{line_index}",
                            x_start_mm=round(start, 3),
                            x_end_mm=round(end, 3),
                            y_mm=round(y_mm, 3),
                            region_id=region.id,
                            flow_order=region.flow_order,
                            column_index=column_index,
                            baseline_offset_mm=region.baseline_offset_mm,
                            layout_mode="free",
                        )
                    )
            continue

        # A lined region uses the actual measured line coordinates. Each line is
        # clipped to each configured column, then columns are consumed fully
        # top-to-bottom before the next column.
        for column_index, (column_start, column_end) in enumerate(columns):
            for line in sorted(config.writing_lines, key=lambda item: item.y_mm):
                if not _region_contains_y(region, line.y_mm):
                    continue
                segments = [(max(line.x_start_mm, column_start), min(line.x_end_mm, column_end))]
                segments = [segment for segment in segments if segment[1] - segment[0] >= 5.0]
                for blocked in protected:
                    if _region_contains_y(blocked, line.y_mm):
                        segments = _subtract_interval(segments, blocked.x_mm, blocked.right_mm)
                if not segments:
                    continue
                start, end = max(segments, key=lambda segment: segment[1] - segment[0])
                slots.append(
                    LineSlot(
                        line_id=f"{line.id}_{region.id or region_position}_{column_index + 1}",
                        x_start_mm=round(start, 3),
                        x_end_mm=round(end, 3),
                        y_mm=line.y_mm,
                        region_id=region.id,
                        flow_order=region.flow_order,
                        column_index=column_index,
                        baseline_offset_mm=region.baseline_offset_mm,
                        layout_mode="lined",
                    )
                )
    if not slots:
        raise ValueError(f"Template '{config.template_id}' has no usable content slots")
    return slots


def template_for_page(template_sequence: list[str], zero_based_page_index: int) -> str:
    if not template_sequence:
        raise ValueError("template_sequence cannot be empty")
    return template_sequence[min(zero_based_page_index, len(template_sequence) - 1)]
