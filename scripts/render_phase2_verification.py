from __future__ import annotations

import json
import sys
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.coordinate_mapper import points_to_mm


def image_xobjects(page) -> int:
    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") or {}
    return sum(
        1
        for reference in xobjects.values()
        if reference.get_object().get("/Subtype") == "/Image"
    )


def make_contact_sheet(images: list[Image.Image], output: Path, label: str) -> None:
    thumb_width = 420
    margin = 24
    label_height = 34
    resized: list[Image.Image] = []
    for image in images:
        height = round(image.height * thumb_width / image.width)
        resized.append(image.resize((thumb_width, height), Image.Resampling.LANCZOS))
    columns = 2
    rows = (len(resized) + columns - 1) // columns
    cell_height = max(image.height for image in resized) + label_height
    sheet = Image.new(
        "RGB",
        (columns * thumb_width + (columns + 1) * margin, rows * cell_height + (rows + 1) * margin),
        "#d8d8d8",
    )
    draw = ImageDraw.Draw(sheet)
    for index, image in enumerate(resized):
        row, column = divmod(index, columns)
        x = margin + column * (thumb_width + margin)
        y = margin + row * (cell_height + margin)
        draw.text((x, y), f"{label} page {index + 1}", fill="black")
        sheet.paste(image, (x, y + label_height))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="PNG")


def main() -> None:
    pdfs = {
        "preview": ROOT / "outputs" / "previews" / "phase2_synthetic_paginated_preview.pdf",
        "print": ROOT / "outputs" / "print" / "phase2_synthetic_paginated_print.pdf",
        "debug": ROOT / "outputs" / "debug" / "phase2_synthetic_paginated_layout_debug.pdf",
    }
    output_dir = ROOT / "outputs" / "reports" / "phase2_visual_check"
    report: dict[str, dict] = {}
    for name, pdf_path in pdfs.items():
        reader = PdfReader(str(pdf_path))
        document = pdfium.PdfDocument(str(pdf_path))
        images: list[Image.Image] = []
        sizes = []
        image_counts = []
        for page_index, page in enumerate(reader.pages):
            width_mm = points_to_mm(float(page.mediabox.width))
            height_mm = points_to_mm(float(page.mediabox.height))
            sizes.append([round(width_mm, 4), round(height_mm, 4)])
            image_counts.append(image_xobjects(page))
            images.append(document[page_index].render(scale=2.0).to_pil().convert("RGB"))
        contact = output_dir / f"{name}_contact_sheet.png"
        make_contact_sheet(images, contact, name)
        report[name] = {
            "pdf": str(pdf_path.relative_to(ROOT)),
            "pages": len(reader.pages),
            "page_sizes_mm": sizes,
            "image_xobjects_by_page": image_counts,
            "contact_sheet": str(contact.relative_to(ROOT)),
        }
    report["assertions"] = {
        "same_page_count": len({report[name]["pages"] for name in pdfs}) == 1,
        "all_pages_120x180_mm": all(
            size == [120.0, 180.0]
            for name in pdfs
            for size in report[name]["page_sizes_mm"]
        ),
        "preview_background_each_page": all(
            count > 0 for count in report["preview"]["image_xobjects_by_page"]
        ),
        "print_has_no_background": all(
            count == 0 for count in report["print"]["image_xobjects_by_page"]
        ),
    }
    output = ROOT / "outputs" / "reports" / "phase2_pdf_verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not all(report["assertions"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

