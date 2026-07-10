from __future__ import annotations

from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from src.export_manager import ExportManager
from src.layout_engine import LayoutEngine
from src.models import FlowBlock, FlowDocument
from src.template_importer import save_template


def image_count_by_page(path: Path) -> list[int]:
    counts = []
    for page in PdfReader(str(path)).pages:
        resources = page.get("/Resources") or {}
        xobjects = resources.get("/XObject") or {}
        counts.append(
            sum(
                1
                for reference in xobjects.values()
                if reference.get_object().get("/Subtype") == "/Image"
            )
        )
    return counts


def test_image_block_keeps_caption_and_advances_text(project_paths, ready_template) -> None:
    save_template(project_paths, ready_template)
    image_path = project_paths.root / "days" / "2026-07-10" / "photo_01.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1600, 1000), (80, 130, 190)).save(image_path)
    flow = FlowDocument(
        output_stem="image_layout",
        template_sequence=[ready_template.template_id],
        blocks=[
            FlowBlock(
                id="photo",
                type="image",
                image_paths=[image_path.relative_to(project_paths.root).as_posix()],
                captions=["图1 合成设备照片"],
                target_height_mm=25,
            ),
        ],
        show_page_numbers=False,
    )
    document = LayoutEngine(project_paths).layout(flow)
    assert len(document.pages[0].image_items) == 1
    assert any(item.role == "caption" for item in document.pages[0].text_items)
    image = document.pages[0].image_items[0]
    caption = next(item for item in document.pages[0].text_items if item.role == "caption")
    assert caption.baseline_y_mm > image.y_mm + image.height_mm

    exported = ExportManager(project_paths).export_paginated_three_pdfs(
        {ready_template.template_id: ready_template}, document
    )
    assert image_count_by_page(exported["print"]) == [1]
    assert image_count_by_page(exported["preview"]) == [2]

