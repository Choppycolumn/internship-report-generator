from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export_manager import ExportManager
from src.models import LayoutDocument, RegionMM, TextItem, WritingLine
from src.paths import get_paths
from src.printer_calibration import generate_calibration_page
from src.storage import utc_now_iso
from src.template_calibrator import mark_calibrated
from src.template_importer import (
    TemplateImporter,
    load_template,
    save_template,
    set_physical_size,
)


TEMPLATE_ID = "phase1_synthetic_demo"
WIDTH_MM = 120.0
HEIGHT_MM = 180.0


def create_synthetic_source(path: Path) -> None:
    width_px, height_px = 1200, 1800
    image = Image.new("RGB", (width_px, height_px), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, width_px - 3, height_px - 3), outline=(50, 50, 50), width=3)
    draw.rectangle((80, 90, width_px - 80, 240), outline=(80, 80, 80), width=3)
    draw.line((80, 260, width_px - 80, 260), fill=(50, 50, 50), width=3)
    for y in range(430, 1580, 80):
        draw.line((120, y, width_px - 100, y), fill=(165, 165, 165), width=2)
    draw.text((420, 140), "SYNTHETIC TEMPLATE", fill=(50, 50, 50))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


def main() -> None:
    paths = get_paths()
    source = paths.root / "tmp" / "synthetic_phase1_source.png"
    if not source.exists():
        create_synthetic_source(source)
    config_path = paths.template_config(TEMPLATE_ID)
    if not config_path.exists():
        TemplateImporter(paths).add(
            source,
            template_id=TEMPLATE_ID,
            display_name="第一阶段非 A4 合成测试模板",
            notes="仅用于软件验收，不代表任何真实报告纸。",
        )
    config = load_template(paths, TEMPLATE_ID)
    if not config.has_confirmed_size:
        config = set_physical_size(
            paths,
            TEMPLATE_ID,
            WIDTH_MM,
            HEIGHT_MM,
            orientation="portrait",
            binding_side="left",
            notes="尺寸来自合成测试定义，不应用于用户模板。",
        )
    config.content_regions = [
        RegionMM(
            id="demo_content",
            label="合成正文区",
            x_mm=12,
            y_mm=35,
            width_mm=98,
            height_mm=125,
        )
    ]
    config.header_regions = [
        RegionMM(id="demo_header", label="合成页眉", x_mm=8, y_mm=9, width_mm=104, height_mm=17)
    ]
    config.forbidden_regions = [
        RegionMM(id="binding", label="合成装订区", x_mm=0, y_mm=0, width_mm=8, height_mm=180)
    ]
    config.writing_lines = [
        WritingLine(
            id=f"line_{index:02d}",
            x_start_mm=12,
            x_end_mm=110,
            y_mm=y,
            source="manual",
        )
        for index, y in enumerate([43, 51, 59, 67, 75, 83, 91, 99, 107, 115, 123, 131, 139, 147, 155], 1)
    ]
    config.updated_at = utc_now_iso()
    save_template(paths, config)
    config = mark_calibrated(paths, TEMPLATE_ID)

    document = LayoutDocument(
        template_id=TEMPLATE_ID,
        output_stem="phase1_synthetic",
        text_items=[
            TextItem(
                id="demo_text_1",
                text="第一阶段坐标测试：文字基线位于 51.0 mm。",
                x_mm=14,
                baseline_y_mm=51,
                font_size_pt=10.5,
            ),
            TextItem(
                id="demo_text_2",
                text="非 A4 合成页：120 × 180 mm，仅用于验收。",
                x_mm=14,
                baseline_y_mm=67,
                font_size_pt=10.5,
            ),
        ],
    )
    exported = ExportManager(paths).export_three_pdfs(config, document)
    calibration = generate_calibration_page(paths, config)
    for name, path in exported.items():
        print(f"{name}: {path}")
    print(f"calibration: {calibration}")


if __name__ == "__main__":
    main()
