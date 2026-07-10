from __future__ import annotations

from typing import Literal

from .models import RegionMM, TemplateConfig, TemplateStatus, WritingLine
from .paths import ProjectPaths
from .storage import utc_now_iso
from .template_importer import load_template, save_template


RegionKind = Literal[
    "content_regions",
    "header_regions",
    "fixed_text_regions",
    "forbidden_regions",
    "image_regions",
    "table_regions",
    "signature_regions",
    "page_number_regions",
]

REGION_KINDS: tuple[str, ...] = (
    "content_regions",
    "header_regions",
    "fixed_text_regions",
    "forbidden_regions",
    "image_regions",
    "table_regions",
    "signature_regions",
    "page_number_regions",
)


def validate_region_on_page(config: TemplateConfig, region: RegionMM) -> None:
    width, height = config.require_confirmed_size()
    if region.right_mm > width + 1e-6 or region.bottom_mm > height + 1e-6:
        raise ValueError(
            f"Region '{region.id or region.label}' exceeds the {width} x {height} mm page"
        )


def replace_regions(
    paths: ProjectPaths,
    template_id: str,
    kind: RegionKind,
    regions: list[RegionMM],
) -> TemplateConfig:
    if kind not in REGION_KINDS:
        raise ValueError(f"Unsupported region kind: {kind}")
    config = load_template(paths, template_id)
    for region in regions:
        validate_region_on_page(config, region)
    setattr(config, kind, regions)
    config.updated_at = utc_now_iso()
    save_template(paths, config)
    return config


def replace_writing_lines(
    paths: ProjectPaths,
    template_id: str,
    lines: list[WritingLine],
) -> TemplateConfig:
    config = load_template(paths, template_id)
    width, height = config.require_confirmed_size()
    for line in lines:
        if line.x_end_mm > width or line.y_mm > height:
            raise ValueError(f"Writing line '{line.id}' exceeds page bounds")
    config.writing_lines = sorted(lines, key=lambda line: line.y_mm)
    config.updated_at = utc_now_iso()
    save_template(paths, config)
    return config


def mark_calibrated(paths: ProjectPaths, template_id: str) -> TemplateConfig:
    config = load_template(paths, template_id)
    config.require_confirmed_size()
    if not config.has_exact_size:
        raise ValueError(
            "A provisional physical size can be previewed but cannot be marked as final calibration"
        )
    if not config.content_regions:
        raise ValueError("At least one content region must be marked before calibration is complete")
    config.status = TemplateStatus.CALIBRATED
    config.updated_at = utc_now_iso()
    save_template(paths, config)
    return config
