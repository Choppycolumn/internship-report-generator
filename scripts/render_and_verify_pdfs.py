from __future__ import annotations

import json
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.coordinate_mapper import points_to_mm


def count_image_xobjects(pdf_path: Path) -> int:
    page = PdfReader(str(pdf_path)).pages[0]
    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") or {}
    return sum(
        1
        for reference in xobjects.values()
        if reference.get_object().get("/Subtype") == "/Image"
    )


def main() -> None:
    try:
        import fitz

        renderer_name = "PyMuPDF"

        def render_first_page(pdf_path: Path, png_path: Path) -> tuple[int, int]:
            document = fitz.open(str(pdf_path))
            pixmap = document[0].get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            pixmap.save(str(png_path))
            return pixmap.width, pixmap.height

    except ImportError:
        import pypdfium2 as pdfium

        renderer_name = "PDFium"

        def render_first_page(pdf_path: Path, png_path: Path) -> tuple[int, int]:
            document = pdfium.PdfDocument(str(pdf_path))
            bitmap = document[0].render(scale=2.0)
            image = bitmap.to_pil().convert("RGB")
            image.save(png_path, format="PNG")
            return image.width, image.height

    inputs = {
        "preview": ROOT / "outputs" / "previews" / "phase1_synthetic_preview.pdf",
        "print": ROOT / "outputs" / "print" / "phase1_synthetic_print.pdf",
        "debug": ROOT / "outputs" / "debug" / "phase1_synthetic_layout_debug.pdf",
        "calibration": ROOT
        / "outputs"
        / "calibration"
        / "phase1_synthetic_demo_calibration.pdf",
    }
    output_dir = ROOT / "outputs" / "reports" / "phase1_visual_check"
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict] = {}
    for name, pdf_path in inputs.items():
        if not pdf_path.exists():
            raise FileNotFoundError(pdf_path)
        reader = PdfReader(str(pdf_path))
        page = reader.pages[0]
        width_mm = points_to_mm(float(page.mediabox.width))
        height_mm = points_to_mm(float(page.mediabox.height))
        png_path = output_dir / f"{name}.png"
        rendered_width, rendered_height = render_first_page(pdf_path, png_path)
        report[name] = {
            "pdf": str(pdf_path.relative_to(ROOT)),
            "rendered_png": str(png_path.relative_to(ROOT)),
            "page_width_mm": round(width_mm, 4),
            "page_height_mm": round(height_mm, 4),
            "size_matches_120x180_mm": abs(width_mm - 120.0) < 0.01
            and abs(height_mm - 180.0) < 0.01,
            "image_xobjects": count_image_xobjects(pdf_path),
            "rendered_pixels": [rendered_width, rendered_height],
            "renderer": renderer_name,
        }
    report["assertions"] = {
        "all_sizes_match": all(
            item["size_matches_120x180_mm"]
            for key, item in report.items()
            if key != "assertions"
        ),
        "preview_has_background": report["preview"]["image_xobjects"] > 0,
        "print_has_no_background": report["print"]["image_xobjects"] == 0,
    }
    report_path = ROOT / "outputs" / "reports" / "phase1_pdf_verification.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
