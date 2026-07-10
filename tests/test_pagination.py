import pytest

from src.layout_engine import LayoutEngine
from src.models import FlowBlock, FlowDocument, TemplateConfig, WritingLine
from src.template_importer import save_template


def test_missing_physical_size_stops_page_creation() -> None:
    config = TemplateConfig(
        template_id="locked",
        source_media="templates/raw/locked.png",
        source_sha256="0" * 64,
        source_kind="raster",
        imported_at="2026-07-10T00:00:00+00:00",
        updated_at="2026-07-10T00:00:00+00:00",
    )
    with pytest.raises(ValueError):
        config.require_confirmed_size()


def test_layout_uses_first_and_continuation_templates(project_paths, ready_template) -> None:
    save_template(project_paths, ready_template)
    continuation = ready_template.model_copy(deep=True)
    continuation.template_id = "continuation"
    continuation.writing_lines = [
        WritingLine(
            id=f"continuation_{index}",
            x_start_mm=12,
            x_end_mm=110,
            y_mm=y,
        )
        for index, y in enumerate([38.0, 46.1, 54.0, 62.2, 70.1, 78.3], 1)
    ]
    save_template(project_paths, continuation)
    flow = FlowDocument(
        output_stem="pagination",
        template_sequence=[ready_template.template_id, continuation.template_id],
        blocks=[
            FlowBlock(
                id="heading",
                type="heading",
                text="一、自动分页测试",
                keep_with_next=True,
            ),
            FlowBlock(
                id="paragraph",
                type="paragraph",
                text="这是一段用于验证实际横线坐标和自动分页的合成文字。" * 15,
            ),
        ],
    )
    paginated = LayoutEngine(project_paths).layout(flow)
    assert len(paginated.pages) >= 2
    assert paginated.pages[0].template_id == ready_template.template_id
    assert all(page.template_id == continuation.template_id for page in paginated.pages[1:])
    assert all(any(item.role == "page_number" for item in page.text_items) for page in paginated.pages)
    for page in paginated.pages:
        content_items = [item for item in page.text_items if item.role != "page_number"]
        assert not content_items or content_items[-1].role != "heading"


def test_nonuniform_line_coordinates_are_used_verbatim(project_paths, ready_template) -> None:
    save_template(project_paths, ready_template)
    flow = FlowDocument(
        output_stem="line_positions",
        template_sequence=[ready_template.template_id],
        blocks=[
            FlowBlock(
                id="paragraph",
                type="paragraph",
                text="逐条横线坐标测试内容，需要至少占用三行以验证不等距位置。",
            )
        ],
        show_page_numbers=False,
    )
    page = LayoutEngine(project_paths).layout(flow).pages[0]
    baselines = [item.baseline_y_mm for item in page.text_items]
    expected = [line.y_mm - 0.6 for line in ready_template.writing_lines[: len(baselines)]]
    assert baselines == pytest.approx(expected)
