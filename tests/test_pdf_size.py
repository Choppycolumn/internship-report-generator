from pathlib import Path

from pypdf import PdfReader

from src.coordinate_mapper import points_to_mm
from src.export_manager import ExportManager
from src.models import LayoutDocument, LayoutPage, PaginatedDocument, TextItem


def _image_xobjects(pdf_path: Path) -> int:
    page = PdfReader(str(pdf_path)).pages[0]
    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") or {}
    count = 0
    for reference in xobjects.values():
        obj = reference.get_object()
        if obj.get("/Subtype") == "/Image":
            count += 1
    return count


def _image_xobjects_by_page(pdf_path: Path) -> list[int]:
    counts = []
    for page in PdfReader(str(pdf_path)).pages:
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


def test_three_pdf_outputs_use_exact_non_a4_size(project_paths, ready_template) -> None:
    document = LayoutDocument(
        template_id=ready_template.template_id,
        output_stem="size_check",
        text_items=[
            TextItem(id="ok", text="尺寸测试", x_mm=15, baseline_y_mm=50, font_size_pt=10.5)
        ],
    )
    exported = ExportManager(project_paths).export_three_pdfs(ready_template, document)
    for key in ["preview", "print", "debug"]:
        path = exported[key]
        assert path is not None and path.exists()
        page = PdfReader(str(path)).pages[0]
        assert abs(points_to_mm(float(page.mediabox.width)) - 120.0) < 0.01
        assert abs(points_to_mm(float(page.mediabox.height)) - 180.0) < 0.01
    assert _image_xobjects(exported["preview"]) >= 1
    assert _image_xobjects(exported["print"]) == 0


def test_paginated_pdf_keeps_size_and_background_policy(project_paths, ready_template) -> None:
    document = PaginatedDocument(
        output_stem="paged_size_check",
        pages=[
            LayoutPage(
                template_id=ready_template.template_id,
                page_number=index,
                text_items=[
                    TextItem(
                        id=f"page_{index}",
                        text=f"第{index}页",
                        x_mm=15,
                        baseline_y_mm=50,
                    )
                ],
            )
            for index in [1, 2]
        ],
    )
    exported = ExportManager(project_paths).export_paginated_three_pdfs(
        {ready_template.template_id: ready_template}, document
    )
    preview = PdfReader(str(exported["preview"]))
    formal = PdfReader(str(exported["print"]))
    assert len(preview.pages) == len(formal.pages) == 2
    for page in list(preview.pages) + list(formal.pages):
        assert abs(points_to_mm(float(page.mediabox.width)) - 120.0) < 0.01
        assert abs(points_to_mm(float(page.mediabox.height)) - 180.0) < 0.01
    assert all(count == 0 for count in _image_xobjects_by_page(exported["print"]))
    assert all(count > 0 for count in _image_xobjects_by_page(exported["preview"]))
