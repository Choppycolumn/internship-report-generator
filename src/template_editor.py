from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import RegionMM, TemplateConfig
from .paths import ProjectPaths


REGION_COLORS = {
    "content_regions": (0, 150, 0, 210),
    "header_regions": (45, 95, 220, 210),
    "fixed_text_regions": (150, 80, 190, 210),
    "forbidden_regions": (220, 35, 35, 220),
    "image_regions": (255, 135, 0, 220),
    "table_regions": (0, 155, 170, 220),
    "signature_regions": (160, 95, 30, 220),
    "page_number_regions": (90, 90, 90, 220),
}


def template_background_path(paths: ProjectPaths, config: TemplateConfig) -> Path:
    relative = config.corrected_image or config.source_preview_image
    if not relative:
        raise ValueError("Template has no viewable background image")
    path = paths.root / relative
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def create_editor_overlay(
    paths: ProjectPaths,
    config: TemplateConfig,
    display_width_px: int = 900,
    include_grid: bool = True,
) -> Image.Image:
    physical_width, physical_height = config.require_confirmed_size()
    background_path = template_background_path(paths, config)
    with Image.open(background_path) as opened:
        base = opened.convert("RGBA")
    scale = display_width_px / base.width
    display_height = max(1, round(base.height * scale))
    base = base.resize((display_width_px, display_height), Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    px_per_mm_x = display_width_px / physical_width
    px_per_mm_y = display_height / physical_height

    if include_grid:
        x = 0.0
        while x <= physical_width + 1e-6:
            px = round(x * px_per_mm_x)
            draw.line((px, 0, px, display_height), fill=(30, 100, 230, 55), width=1)
            if x > 0:
                draw.text((px + 2, 2), f"{x:g}", fill=(20, 70, 160, 180))
            x += 10.0
        y = 0.0
        while y <= physical_height + 1e-6:
            py = round(y * px_per_mm_y)
            draw.line((0, py, display_width_px, py), fill=(30, 100, 230, 55), width=1)
            if y > 0:
                draw.text((2, py + 2), f"{y:g}", fill=(20, 70, 160, 180))
            y += 10.0

    for kind, color in REGION_COLORS.items():
        regions: list[RegionMM] = getattr(config, kind)
        for region in regions:
            box = (
                region.x_mm * px_per_mm_x,
                region.y_mm * px_per_mm_y,
                region.right_mm * px_per_mm_x,
                region.bottom_mm * px_per_mm_y,
            )
            draw.rectangle(box, outline=color, fill=(*color[:3], 35), width=3)
            draw.text((box[0] + 3, box[1] + 3), region.label or kind, fill=color)

    for line in config.writing_lines:
        draw.line(
            (
                line.x_start_mm * px_per_mm_x,
                line.y_mm * px_per_mm_y,
                line.x_end_mm * px_per_mm_x,
                line.y_mm * px_per_mm_y,
            ),
            fill=(235, 0, 190, 230),
            width=2,
        )
    return Image.alpha_composite(base, overlay).convert("RGB")

