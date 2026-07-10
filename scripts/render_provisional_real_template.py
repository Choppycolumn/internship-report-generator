from __future__ import annotations

import json
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def render(pdf_path: Path, png_path: Path) -> list[int]:
    document = pdfium.PdfDocument(str(pdf_path))
    image = document[0].render(scale=2.0).to_pil().convert("RGB")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(png_path, format="PNG")
    return [image.width, image.height]


def main() -> None:
    files = {
        "preview": ROOT / "outputs" / "previews" / "lined_content_page_candidate_provisional_preview.pdf",
        "debug": ROOT / "outputs" / "debug" / "lined_content_page_candidate_provisional_layout_debug.pdf",
        "calibration": ROOT / "outputs" / "calibration" / "lined_content_page_candidate_provisional_calibration.pdf",
    }
    output_dir = ROOT / "outputs" / "reports" / "real_template_provisional_visual_check"
    report = {}
    for name, pdf_path in files.items():
        page = PdfReader(str(pdf_path)).pages[0]
        width_mm = float(page.mediabox.width) * 25.4 / 72.0
        height_mm = float(page.mediabox.height) * 25.4 / 72.0
        png = output_dir / f"{name}.png"
        pixels = render(pdf_path, png)
        report[name] = {
            "pdf": str(pdf_path.relative_to(ROOT)),
            "png": str(png.relative_to(ROOT)),
            "page_size_mm": [round(width_mm, 3), round(height_mm, 3)],
            "rendered_pixels": pixels,
        }
    formal = ROOT / "outputs" / "print" / "lined_content_page_candidate_provisional_print.pdf"
    report["assertions"] = {
        "all_sizes_match_provisional": all(
            item["page_size_mm"] == [180.876, 258.484]
            for item in report.values()
            if isinstance(item, dict) and "page_size_mm" in item
        ),
        "formal_print_absent": not formal.exists(),
    }
    output = ROOT / "outputs" / "reports" / "real_template_provisional_pdf_verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not all(report["assertions"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

