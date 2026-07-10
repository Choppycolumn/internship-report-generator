from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from .coordinate_mapper import CoordinateMapper
from .models import RegionMM, WritingLine
from .paths import ProjectPaths
from .storage import utc_now_iso
from .template_editor import template_background_path
from .template_importer import load_template, save_template


@dataclass(frozen=True)
class LineDetectionOptions:
    darkness_threshold: int = 210
    minimum_dark_fraction: float = 0.55
    merge_distance_mm: float = 0.8


def _candidate_regions(config) -> list[RegionMM]:
    if config.content_regions:
        return config.content_regions
    width, height = config.require_confirmed_size()
    return [
        RegionMM(
            id="full_page_detection",
            label="full page detection",
            x_mm=0,
            y_mm=0,
            width_mm=width,
            height_mm=height,
        )
    ]


def detect_horizontal_lines(
    paths: ProjectPaths,
    template_id: str,
    options: LineDetectionOptions | None = None,
) -> list[WritingLine]:
    options = options or LineDetectionOptions()
    if not 0 < options.minimum_dark_fraction <= 1:
        raise ValueError("minimum_dark_fraction must be in (0, 1]")
    if not 0 <= options.darkness_threshold <= 255:
        raise ValueError("darkness_threshold must be between 0 and 255")

    config = load_template(paths, template_id)
    config.require_confirmed_size()
    background = template_background_path(paths, config)
    with Image.open(background) as opened:
        grayscale = np.asarray(opened.convert("L"))
    mapper = CoordinateMapper(
        physical_width_mm=float(config.physical_width_mm),
        physical_height_mm=float(config.physical_height_mm),
        pixel_width=grayscale.shape[1],
        pixel_height=grayscale.shape[0],
    )
    detected: list[WritingLine] = []
    for region_index, region in enumerate(_candidate_regions(config), 1):
        x0, y0 = mapper.mm_to_px(region.x_mm, region.y_mm)
        x1, y1 = mapper.mm_to_px(region.right_mm, region.bottom_mm)
        left = max(0, int(round(x0)))
        right = min(grayscale.shape[1], int(round(x1)))
        top = max(0, int(round(y0)))
        bottom = min(grayscale.shape[0], int(round(y1)))
        if right - left < 2 or bottom - top < 2:
            continue
        crop = grayscale[top:bottom, left:right]
        dark = crop <= options.darkness_threshold
        row_scores = dark.mean(axis=1)
        candidate_rows = np.flatnonzero(row_scores >= options.minimum_dark_fraction)
        if not len(candidate_rows):
            continue
        groups: list[list[int]] = [[int(candidate_rows[0])]]
        for row in candidate_rows[1:]:
            row = int(row)
            if row <= groups[-1][-1] + 1:
                groups[-1].append(row)
            else:
                groups.append([row])

        for group_index, group in enumerate(groups, 1):
            local_y = max(group, key=lambda row: float(row_scores[row]))
            row_mask = dark[local_y]
            columns = np.flatnonzero(row_mask)
            if not len(columns):
                continue
            span_fraction = (int(columns[-1]) - int(columns[0]) + 1) / crop.shape[1]
            if span_fraction < options.minimum_dark_fraction:
                continue
            x_start_mm, y_mm = mapper.px_to_mm(left + int(columns[0]), top + local_y)
            x_end_mm, _ = mapper.px_to_mm(left + int(columns[-1]), top + local_y)
            detected.append(
                WritingLine(
                    id=f"detected_r{region_index:02d}_{group_index:02d}",
                    x_start_mm=round(x_start_mm, 3),
                    x_end_mm=round(x_end_mm, 3),
                    y_mm=round(y_mm, 3),
                    confidence=round(min(1.0, float(row_scores[local_y])), 3),
                    source="detected",
                )
            )

    detected.sort(key=lambda line: line.y_mm)
    merged: list[WritingLine] = []
    for line in detected:
        if merged and abs(line.y_mm - merged[-1].y_mm) <= options.merge_distance_mm:
            if (line.confidence or 0) > (merged[-1].confidence or 0):
                merged[-1] = line
            continue
        merged.append(line)
    for index, line in enumerate(merged, 1):
        line.id = f"detected_line_{index:02d}"

    config.detected_writing_lines = merged
    config.confidence["horizontal_line_detection"] = (
        round(sum(line.confidence or 0 for line in merged) / len(merged), 3)
        if merged
        else 0.0
    )
    config.updated_at = utc_now_iso()
    save_template(paths, config)
    return merged


def apply_detected_lines(paths: ProjectPaths, template_id: str) -> list[WritingLine]:
    config = load_template(paths, template_id)
    if not config.detected_writing_lines:
        raise ValueError("No detected line suggestions are available")
    config.writing_lines = [line.model_copy(deep=True) for line in config.detected_writing_lines]
    config.updated_at = utc_now_iso()
    save_template(paths, config)
    return config.writing_lines

