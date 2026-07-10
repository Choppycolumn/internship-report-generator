from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.coordinate_mapper import CoordinateMapper
from src.export_manager import ExportManager
from src.models import LayoutDocument, RegionMM, TextItem
from src.paths import get_paths
from src.printer_calibration import generate_calibration_page
from src.storage import save_json_atomic, utc_now_iso
from src.template_importer import load_template, save_template


TEMPLATE_ID = "lined_content_page_candidate"


def main() -> None:
    paths = get_paths()
    config = load_template(paths, TEMPLATE_ID)
    if config.physical_size_source != "user_confirmed_estimate":
        raise ValueError("This preview script is only for a user-confirmed provisional size")
    corrected = paths.root / str(config.corrected_image)
    with Image.open(corrected) as image:
        mapper = CoordinateMapper(
            physical_width_mm=float(config.physical_width_mm),
            physical_height_mm=float(config.physical_height_mm),
            pixel_width=image.width,
            pixel_height=image.height,
        )

    rule_x0_mm, rule_y_mm = mapper.px_to_mm(373.0, 660.706)
    rule_x1_mm, _ = mapper.px_to_mm(3726.0, 660.706)
    title_x0_mm, title_y0_mm = mapper.px_to_mm(1145.0, 449.0)
    title_x1_mm, title_y1_mm = mapper.px_to_mm(2971.0, 634.0)

    config.header_regions = [
        RegionMM(
            id="header_provisional",
            label="自动页眉保护区-待确认",
            x_mm=round(max(0.0, rule_x0_mm - 1.0), 3),
            y_mm=round(max(0.0, title_y0_mm - 1.0), 3),
            width_mm=round(min(float(config.physical_width_mm), rule_x1_mm + 1.0) - max(0.0, rule_x0_mm - 1.0), 3),
            height_mm=round(rule_y_mm - max(0.0, title_y0_mm - 1.0) + 1.0, 3),
        )
    ]
    config.fixed_text_regions = [
        RegionMM(
            id="title_provisional",
            label="固定标题-自动识别待确认",
            x_mm=round(title_x0_mm - 1.0, 3),
            y_mm=round(title_y0_mm - 1.0, 3),
            width_mm=round(title_x1_mm - title_x0_mm + 2.0, 3),
            height_mm=round(title_y1_mm - title_y0_mm + 2.0, 3),
        )
    ]
    config.content_regions = [
        RegionMM(
            id="content_provisional",
            label="正文候选区-待人工确认",
            x_mm=round(rule_x0_mm, 3),
            y_mm=38.0,
            width_mm=round(rule_x1_mm - rule_x0_mm, 3),
            height_mm=200.0,
        )
    ]
    config.manual_measurements.update(
        {
            "estimated_size_user_accepted": True,
            "corrected_header_rule_angle_degree": 0.00038,
            "corrected_header_rule_x0_px": 373.0,
            "corrected_header_rule_y_px": 660.706,
            "corrected_header_rule_x1_px": 3726.0,
            "provisional_content_region_requires_confirmation": True,
            "virtual_writing_lines_not_configured": True,
        }
    )
    config.notes = (
        config.notes
        + "\n页眉保护区和正文区为自动候选，仅用于预览；尚未确认正文起止位置和虚拟行距。"
    ).strip()
    config.updated_at = utc_now_iso()
    save_template(paths, config)

    document = LayoutDocument(
        template_id=TEMPLATE_ID,
        output_stem="lined_content_page_candidate_provisional",
        text_items=[
            TextItem(
                id="provisional_heading",
                text="【暂定坐标预览】",
                x_mm=rule_x0_mm + 2.0,
                baseline_y_mm=43.0,
                font_size_pt=11.0,
                role="heading",
            ),
            TextItem(
                id="provisional_body",
                text="此文字仅用于核对暂定页面尺寸、页眉避让和正文起点。",
                x_mm=rule_x0_mm + 2.0,
                baseline_y_mm=52.0,
                font_size_pt=10.5,
                role="body",
            ),
        ],
    )
    exported = ExportManager(paths).export_three_pdfs(config, document)
    calibration = generate_calibration_page(
        paths,
        config,
        paths.output_calibration / "lined_content_page_candidate_provisional_calibration.pdf",
    )
    status = {
        "template_id": TEMPLATE_ID,
        "physical_size_mm": [config.physical_width_mm, config.physical_height_mm],
        "physical_size_source": config.physical_size_source,
        "corrected_header_rule_angle_degree": 0.00038,
        "formal_print_generated": exported["print"] is not None,
        "preview": str(exported["preview"].relative_to(paths.root)),
        "debug": str(exported["debug"].relative_to(paths.root)),
        "calibration": str(calibration.relative_to(paths.root)),
        "regions": {
            "header": [region.model_dump() for region in config.header_regions],
            "fixed_text": [region.model_dump() for region in config.fixed_text_regions],
            "content_provisional": [region.model_dump() for region in config.content_regions],
        },
    }
    save_json_atomic(paths.output_reports / "real_template_provisional_status.json", status)
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

