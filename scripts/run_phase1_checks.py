from __future__ import annotations

import json
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.coordinate_mapper import CoordinateMapper, points_to_mm
from src.models import LayoutDocument, TextItem
from src.paths import get_paths
from src.template_importer import load_template
from src.validators import validate_layout


def image_xobjects(pdf_path: Path) -> int:
    page = PdfReader(str(pdf_path)).pages[0]
    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") or {}
    return sum(
        1
        for reference in xobjects.values()
        if reference.get_object().get("/Subtype") == "/Image"
    )


def main() -> None:
    paths = get_paths()
    results: dict[str, object] = {}

    candidate = load_template(paths, "lined_content_page_candidate")
    results["candidate_size_is_unset"] = (
        candidate.physical_width_mm is None
        and candidate.physical_height_mm is None
        and candidate.physical_size_source is None
    )
    try:
        candidate.require_confirmed_size()
        results["candidate_layout_gate"] = False
    except ValueError:
        results["candidate_layout_gate"] = True

    mapper = CoordinateMapper(185.0, 260.0, 3700, 5200)
    px = mapper.mm_to_px(37.25, 149.75)
    mm = mapper.px_to_mm(*px)
    results["coordinate_round_trip_under_0_01_mm"] = (
        abs(mm[0] - 37.25) < 0.01 and abs(mm[1] - 149.75) < 0.01
    )

    synthetic = load_template(paths, "phase1_synthetic_demo")
    collision = LayoutDocument(
        template_id=synthetic.template_id,
        output_stem="collision_check",
        text_items=[TextItem(id="collision", text="禁打区碰撞", x_mm=2, baseline_y_mm=50)],
    )
    collision_report = validate_layout(synthetic, collision)
    results["forbidden_region_collision_is_blocked"] = not collision_report.valid_for_print

    pdfs = {
        "preview": paths.output_previews / "phase1_synthetic_preview.pdf",
        "print": paths.output_print / "phase1_synthetic_print.pdf",
        "debug": paths.output_debug / "phase1_synthetic_layout_debug.pdf",
    }
    size_checks = {}
    for name, path in pdfs.items():
        page = PdfReader(str(path)).pages[0]
        width = points_to_mm(float(page.mediabox.width))
        height = points_to_mm(float(page.mediabox.height))
        size_checks[name] = abs(width - 120.0) < 0.01 and abs(height - 180.0) < 0.01
    results["pdf_sizes_match_non_a4_fixture"] = size_checks
    results["preview_has_background"] = image_xobjects(pdfs["preview"]) > 0
    results["print_has_no_background"] = image_xobjects(pdfs["print"]) == 0
    results["all_passed"] = all(
        bool(value) if not isinstance(value, dict) else all(value.values())
        for key, value in results.items()
        if key != "all_passed"
    )
    output = paths.output_reports / "phase1_automated_checks.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if not results["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
