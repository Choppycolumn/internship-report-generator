from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli import _json_print
from src.layout_engine import LayoutEngine
from src.export_manager import ExportManager
from src.models import (
    ContentRegion,
    FieldTarget,
    FlowBlock,
    FlowDocument,
    LayoutPage,
    PaginatedDocument,
    RegionMM,
    TableDefinition,
    TemplateConfig,
    TextItem,
    LayoutDocument,
    Severity,
    ValidationIssue,
    WritingLine,
)
from src.pagination import usable_line_slots
from src.template_importer import save_template
from src.template_calibrator import mark_calibrated
from src.validators import validate_layout, validate_paginated_layout, validate_template


def test_v1_template_is_migrated_in_memory() -> None:
    old = {
        "schema_version": 1,
        "template_id": "old",
        "physical_width_mm": 100,
        "physical_height_mm": 150,
        "physical_size_source": "user_measurement",
        "source_media": "templates/raw/old.png",
        "source_sha256": "0" * 64,
        "source_kind": "raster",
        "content_regions": [
            {"id": "body", "x_mm": 10, "y_mm": 20, "width_mm": 80, "height_mm": 100}
        ],
        "writing_lines": [],
        "imported_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    migrated = TemplateConfig.model_validate(old)
    assert migrated.schema_version == 2
    assert migrated.content_regions[0].layout_mode == "lined"
    assert migrated.content_regions[0].columns == 1
    assert migrated.content_regions[0].flow_order == 0


def test_future_template_schema_is_rejected() -> None:
    with pytest.raises(ValueError, match="newer than the supported version"):
        TemplateConfig.model_validate(
            {
                "schema_version": 99,
                "template_id": "future",
                "source_media": "templates/raw/future.png",
                "source_sha256": "0" * 64,
                "source_kind": "raster",
                "imported_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        )


def test_two_columns_are_consumed_top_to_bottom(project_paths, ready_template) -> None:
    config = ready_template.model_copy(deep=True)
    config.content_regions = [
        ContentRegion(
            id="body",
            x_mm=12,
            y_mm=30,
            width_mm=98,
            height_mm=60,
            columns=2,
            column_gap_mm=4,
        )
    ]
    save_template(project_paths, config)
    slots = usable_line_slots(config)
    assert [slot.column_index for slot in slots] == [0] * 6 + [1] * 6
    assert [slot.y_mm for slot in slots[:6]] == [40, 48.2, 56.1, 64.3, 72.2, 80.4]
    assert slots[0].x_start_mm < slots[6].x_start_mm
    assert slots[0].x_end_mm + 4 == slots[6].x_start_mm


def test_lined_region_can_override_baseline_offset(project_paths, ready_template) -> None:
    config = ready_template.model_copy(deep=True)
    config.content_regions = [
        ContentRegion(
            id="body",
            x_mm=12,
            y_mm=30,
            width_mm=98,
            height_mm=60,
            baseline_offset_mm=-1.25,
        )
    ]
    save_template(project_paths, config)
    document = LayoutEngine(project_paths).layout(
        FlowDocument(
            output_stem="baseline",
            template_sequence=[config.template_id],
            blocks=[FlowBlock(id="body", type="paragraph", text="今天我学习了模板标定。")],
            show_page_numbers=False,
        )
    )
    assert document.pages[0].text_items[0].baseline_y_mm == 38.75


def test_free_region_generates_configured_baselines(project_paths, ready_template) -> None:
    config = ready_template.model_copy(deep=True)
    config.content_regions = [
        ContentRegion(
            id="free",
            x_mm=12,
            y_mm=30,
            width_mm=98,
            height_mm=25,
            layout_mode="free",
            baseline_start_mm=34,
            line_spacing_mm=6.5,
        )
    ]
    config.writing_lines = []
    slots = usable_line_slots(config)
    assert [slot.y_mm for slot in slots] == [34, 40.5, 47, 53.5]
    assert all(slot.layout_mode == "free" for slot in slots)


def test_configured_table_region_is_removed_from_free_flow_slots(ready_template) -> None:
    config = ready_template.model_copy(deep=True)
    config.content_regions = [
        ContentRegion(
            id="free",
            x_mm=12,
            y_mm=30,
            width_mm=98,
            height_mm=40,
            layout_mode="free",
            baseline_start_mm=35,
            line_spacing_mm=7,
        )
    ]
    config.writing_lines = []
    config.tables = {
        "embedded": TableDefinition(
            id="embedded",
            region=RegionMM(id="embedded", x_mm=12, y_mm=40, width_mm=98, height_mm=15),
            rows=1,
            columns=1,
        )
    }
    assert [slot.y_mm for slot in usable_line_slots(config)] == [35, 56, 63, 70]


def test_field_only_template_can_be_marked_calibrated(project_paths, ready_template) -> None:
    config = ready_template.model_copy(deep=True)
    config.template_id = "field_only"
    config.content_regions = []
    config.writing_lines = []
    config.fields = {
        "name": FieldTarget(id="name", x_mm=20, y_mm=20, width_mm=50, height_mm=8)
    }
    save_template(project_paths, config)
    calibrated = mark_calibrated(project_paths, config.template_id)
    assert calibrated.status.value == "calibrated"


def test_field_block_uses_target_alignment(project_paths, ready_template) -> None:
    config = ready_template.model_copy(deep=True)
    config.fields = {
        "student_name": FieldTarget(
            id="student_name",
            x_mm=20,
            y_mm=20,
            width_mm=60,
            height_mm=8,
            alignment="center",
        )
    }
    save_template(project_paths, config)
    document = LayoutEngine(project_paths).layout(
        FlowDocument(
            output_stem="field",
            template_sequence=[config.template_id],
            blocks=[FlowBlock(id="name", type="field", field="student_name", text="张三")],
            show_page_numbers=False,
        )
    )
    item = document.pages[0].text_items[0]
    assert item.role == "field"
    assert item.x_mm > 20


def test_table_block_fills_cells_without_repainting_borders(project_paths, ready_template) -> None:
    config = ready_template.model_copy(deep=True)
    config.table_regions = [RegionMM(id="score", x_mm=12, y_mm=30, width_mm=80, height_mm=20)]
    config.tables = {
        "score": TableDefinition(
            id="score",
            region=config.table_regions[0],
            rows=2,
            columns=2,
            border=False,
        )
    }
    save_template(project_paths, config)
    document = LayoutEngine(project_paths).layout(
        FlowDocument(
            output_stem="table",
            template_sequence=[config.template_id],
            blocks=[
                FlowBlock(
                    id="values",
                    type="table",
                    table_id="score",
                    table_values=[["项目", "得分"], ["内容", "30"]],
                )
            ],
            show_page_numbers=False,
        )
    )
    items = document.pages[0].text_items
    assert len(items) == 4
    assert all(item.role == "field" for item in items)
    assert not validate_template(config)


def test_table_cell_overflow_is_not_silently_truncated(project_paths, ready_template) -> None:
    config = ready_template.model_copy(deep=True)
    config.table_regions = [RegionMM(id="tiny", x_mm=12, y_mm=30, width_mm=20, height_mm=5)]
    config.tables = {
        "tiny": TableDefinition(
            id="tiny",
            region=config.table_regions[0],
            rows=1,
            columns=1,
            font_size_pt=9,
        )
    }
    save_template(project_paths, config)
    with pytest.raises(ValueError, match="text does not fit"):
        LayoutEngine(project_paths).layout(
            FlowDocument(
                output_stem="overflow",
                template_sequence=[config.template_id],
                blocks=[
                    FlowBlock(
                        id="table",
                        type="table",
                        table_id="tiny",
                        table_values=[["这是一段明显无法放入狭小单元格的长文本"]],
                    )
                ],
                show_page_numbers=False,
            )
        )


def test_body_text_cannot_enter_named_field_target(ready_template) -> None:
    config = ready_template.model_copy(deep=True)
    config.fields = {
        "name": FieldTarget(id="name", x_mm=12, y_mm=35, width_mm=40, height_mm=10)
    }
    report = validate_layout(
        config,
        LayoutDocument(
            template_id=config.template_id,
            output_stem="field_collision",
            text_items=[
                TextItem(
                    id="body",
                    text="正文不得压住姓名栏",
                    x_mm=12,
                    baseline_y_mm=40,
                    font_size_pt=10.5,
                    width_mm=35,
                    height_mm=4,
                    role="body",
                )
            ],
        ),
    )
    assert any(issue.code == "TEXT_IN_FORBIDDEN_REGION" for issue in report.issues)


def test_cli_json_output_keeps_validation_issues_structured(capsys) -> None:
    _json_print(
        {
            "issues": [
                ValidationIssue(
                    code="EXAMPLE",
                    severity=Severity.WARNING,
                    message="example warning",
                )
            ]
        }
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["issues"][0]["code"] == "EXAMPLE"


def test_mixed_page_sizes_are_reported_without_blocking(project_paths, ready_template) -> None:
    other = ready_template.model_copy(deep=True)
    other.template_id = "other"
    other.physical_width_mm = 100
    other.physical_height_mm = 150
    other.content_regions = [
        ContentRegion(id="body", x_mm=8, y_mm=20, width_mm=80, height_mm=100)
    ]
    other.forbidden_regions = [RegionMM(id="binding", x_mm=0, y_mm=0, width_mm=5, height_mm=150)]
    other.page_number_regions = [RegionMM(id="page_number", x_mm=40, y_mm=135, width_mm=20, height_mm=8)]
    other.writing_lines = [
        WritingLine(id=f"line_{index}", x_start_mm=8, x_end_mm=88, y_mm=y)
        for index, y in enumerate([30, 38, 46, 54], 1)
    ]
    configs = {ready_template.template_id: ready_template, other.template_id: other}
    document = PaginatedDocument(
        output_stem="mixed",
        pages=[
            LayoutPage(template_id=ready_template.template_id, page_number=1),
            LayoutPage(template_id=other.template_id, page_number=2),
        ],
    )
    report = validate_paginated_layout(configs, document)
    assert report.valid_for_print
    issue = next(issue for issue in report.issues if issue.code == "MIXED_PAGE_SIZES")
    assert issue.severity.value == "warning"


def test_mixed_page_sizes_render_with_per_page_media_boxes(project_paths, ready_template) -> None:
    other = ready_template.model_copy(deep=True)
    other.template_id = "other_render"
    other.physical_width_mm = 100
    other.physical_height_mm = 150
    other.content_regions = [
        ContentRegion(id="body", x_mm=8, y_mm=20, width_mm=80, height_mm=100)
    ]
    other.forbidden_regions = [RegionMM(id="binding", x_mm=0, y_mm=0, width_mm=5, height_mm=150)]
    other.page_number_regions = [RegionMM(id="page_number", x_mm=40, y_mm=135, width_mm=20, height_mm=8)]
    other.writing_lines = [
        WritingLine(id=f"line_{index}", x_start_mm=8, x_end_mm=88, y_mm=y)
        for index, y in enumerate([30, 38, 46, 54], 1)
    ]
    save_template(project_paths, ready_template)
    save_template(project_paths, other)
    document = PaginatedDocument(
        output_stem="mixed_render",
        pages=[
            LayoutPage(template_id=ready_template.template_id, page_number=1),
            LayoutPage(template_id=other.template_id, page_number=2),
        ],
    )
    paths = ExportManager(project_paths).export_paginated_three_pdfs(
        {ready_template.template_id: ready_template, other.template_id: other}, document
    )
    from pypdf import PdfReader
    reader = PdfReader(str(paths["print"]))
    assert [
        (round(float(page.mediabox.width) * 25.4 / 72.0, 2), round(float(page.mediabox.height) * 25.4 / 72.0, 2))
        for page in reader.pages
    ] == [(120.0, 180.0), (100.0, 150.0)]
