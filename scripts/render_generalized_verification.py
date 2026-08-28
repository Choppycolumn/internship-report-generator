from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz
from PIL import Image
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.coordinate_mapper import points_to_mm


EXPECTED_SIZES = [(150.0, 210.0), (180.0, 250.0), (130.0, 180.0)]


def _image_count(page) -> int:
    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") or {}
    return sum(
        1
        for reference in xobjects.values()
        if reference.get_object().get("/Subtype") == "/Image"
    )


def _ink_ratio(path: Path) -> float:
    with Image.open(path).convert("L") as image:
        histogram = image.histogram()
        non_white = sum(histogram[:245])
        return non_white / (image.width * image.height)


def main() -> None:
    inputs = {
        "preview": ROOT / "outputs" / "previews" / "generalized_format_showcase_preview.pdf",
        "print": ROOT / "outputs" / "print" / "generalized_format_showcase_print.pdf",
        "debug": ROOT / "outputs" / "debug" / "generalized_format_showcase_layout_debug.pdf",
    }
    output_dir = ROOT / "outputs" / "reports" / "generalized_format_visual_check"
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {}
    for mode, pdf_path in inputs.items():
        reader = PdfReader(str(pdf_path))
        rendered = fitz.open(str(pdf_path))
        pages = []
        for index, page in enumerate(reader.pages):
            width_mm = round(points_to_mm(float(page.mediabox.width)), 3)
            height_mm = round(points_to_mm(float(page.mediabox.height)), 3)
            png_path = output_dir / f"{mode}-page-{index + 1}.png"
            pixmap = rendered[index].get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            pixmap.save(str(png_path))
            pages.append(
                {
                    "page": index + 1,
                    "size_mm": [width_mm, height_mm],
                    "size_matches": abs(width_mm - EXPECTED_SIZES[index][0]) < 0.01
                    and abs(height_mm - EXPECTED_SIZES[index][1]) < 0.01,
                    "image_xobjects": _image_count(page),
                    "ink_ratio": round(_ink_ratio(png_path), 6),
                    "rendered_png": png_path.relative_to(ROOT).as_posix(),
                }
            )
        report[mode] = pages

    preview_pages = report["preview"]
    print_pages = report["print"]
    debug_pages = report["debug"]
    assertions = {
        "all_have_three_pages": all(len(report[mode]) == 3 for mode in inputs),
        "all_sizes_match": all(page["size_matches"] for mode in inputs for page in report[mode]),
        "preview_has_backgrounds": all(page["image_xobjects"] > 0 for page in preview_pages),
        "print_has_no_backgrounds": all(page["image_xobjects"] == 0 for page in print_pages),
        "debug_has_backgrounds": all(page["image_xobjects"] > 0 for page in debug_pages),
        "print_pages_are_nonblank": all(page["ink_ratio"] > 0.0001 for page in print_pages),
    }
    report["assertions"] = assertions
    report_path = ROOT / "outputs" / "reports" / "generalized_format_pdf_verification.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(assertions, ensure_ascii=False, indent=2))
    if not all(assertions.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
