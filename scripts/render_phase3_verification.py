from __future__ import annotations

import json
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def image_xobjects(page) -> int:
    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") or {}
    return sum(
        1
        for reference in xobjects.values()
        if reference.get_object().get("/Subtype") == "/Image"
    )


def contact_sheet(images: list[Image.Image], output: Path, label: str) -> None:
    width = 430
    margin = 24
    label_height = 32
    thumbs = [
        image.resize((width, round(image.height * width / image.width)), Image.Resampling.LANCZOS)
        for image in images
    ]
    columns = 2
    rows = (len(thumbs) + 1) // 2
    cell_height = max(image.height for image in thumbs) + label_height
    sheet = Image.new(
        "RGB",
        (columns * width + (columns + 1) * margin, rows * cell_height + (rows + 1) * margin),
        "#d7d9df",
    )
    draw = ImageDraw.Draw(sheet)
    for index, image in enumerate(thumbs):
        row, column = divmod(index, columns)
        x = margin + column * (width + margin)
        y = margin + row * (cell_height + margin)
        draw.text((x, y), f"{label} page {index + 1}", fill="black")
        sheet.paste(image, (x, y + label_height))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="PNG")


def main() -> None:
    paginated = json.loads(
        (ROOT / "reports" / "structured" / "phase3_paginated.json").read_text(
            encoding="utf-8"
        )
    )
    expected_content_images = [len(page["image_items"]) for page in paginated["pages"]]
    pdfs = {
        "preview": ROOT / "outputs" / "previews" / "phase3_synthetic_image_layout_preview.pdf",
        "print": ROOT / "outputs" / "print" / "phase3_synthetic_image_layout_print.pdf",
        "debug": ROOT / "outputs" / "debug" / "phase3_synthetic_image_layout_layout_debug.pdf",
    }
    output_dir = ROOT / "outputs" / "reports" / "phase3_visual_check"
    report = {}
    for name, path in pdfs.items():
        reader = PdfReader(str(path))
        document = pdfium.PdfDocument(str(path))
        rendered = [document[index].render(scale=2.0).to_pil().convert("RGB") for index in range(len(reader.pages))]
        sheet = output_dir / f"{name}_contact_sheet.png"
        contact_sheet(rendered, sheet, name)
        report[name] = {
            "pages": len(reader.pages),
            "image_xobjects_by_page": [image_xobjects(page) for page in reader.pages],
            "page_sizes_mm": [
                [
                    round(float(page.mediabox.width) * 25.4 / 72.0, 3),
                    round(float(page.mediabox.height) * 25.4 / 72.0, 3),
                ]
                for page in reader.pages
            ],
            "contact_sheet": str(sheet.relative_to(ROOT)),
        }
    report["assertions"] = {
        "page_counts_match": len({report[name]["pages"] for name in pdfs}) == 1,
        "print_contains_only_content_images": report["print"]["image_xobjects_by_page"]
        == expected_content_images,
        "preview_contains_background_plus_content": report["preview"]["image_xobjects_by_page"]
        == [count + 1 for count in expected_content_images],
        "all_page_sizes_match": all(
            size == [120.0, 180.0]
            for name in pdfs
            for size in report[name]["page_sizes_mm"]
        ),
    }
    output = ROOT / "outputs" / "reports" / "phase3_pdf_verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not all(report["assertions"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

