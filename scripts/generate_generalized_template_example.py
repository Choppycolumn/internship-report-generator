from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export_manager import ExportManager
from src.layout_engine import LayoutEngine
from src.models import (
    ContentRegion,
    FieldTarget,
    FlowBlock,
    FlowDocument,
    RegionMM,
    TableDefinition,
    TemplateConfig,
    TemplateStatus,
    WritingLine,
)
from src.paths import get_paths
from src.storage import sha256_file, utc_now_iso
from src.template_importer import save_template


def _font(size: int) -> ImageFont.ImageFont:
    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simsun.ttc"):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _background(path: Path, size_mm: tuple[float, float], kind: str) -> tuple[int, int]:
    scale = 8
    width = round(size_mm[0] * scale)
    height = round(size_mm[1] * scale)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _font(34)
    body_font = _font(22)
    draw.rectangle((2, 2, width - 3, height - 3), outline="#7b8794", width=2)
    draw.text((width // 2, 22), "通用套打格式验收页", fill="#1f2937", font=title_font, anchor="ma")

    if kind == "form":
        draw.text((120, 125), "姓名：", fill="#374151", font=body_font)
        draw.line((190, 154, 520, 154), fill="#64748b", width=2)
        draw.text((620, 125), "日期：", fill="#374151", font=body_font)
        draw.line((690, 154, 1010, 154), fill="#64748b", width=2)
        left, top, right, bottom = 120, 310, 1080, 670
        for row in range(4):
            y = top + (bottom - top) * row // 3
            draw.line((left, y, right, y), fill="#64748b", width=2)
        for column in range(4):
            x = left + (right - left) * column // 3
            draw.line((x, top, x, bottom), fill="#64748b", width=2)
        draw.text((120, 740), "自由填写区", fill="#374151", font=body_font)
    elif kind == "lined":
        for y in range(340, height - 250, 64):
            draw.line((160, y, width - 160, y), fill="#a8b1bd", width=1)
        draw.line((width // 2, 320, width // 2, height - 220), fill="#d1d5db", width=2)
    else:
        draw.rectangle((95, 250, width - 95, 520), outline="#94a3b8", width=2)
        draw.text((120, 275), "摘要区", fill="#374151", font=body_font)
        draw.rectangle((95, 590, width - 95, height - 150), outline="#94a3b8", width=2)
        draw.text((120, 615), "正文区", fill="#374151", font=body_font)

    image.save(path)
    return width, height


def _config(paths, template_id: str, size_mm: tuple[float, float], kind: str) -> TemplateConfig:
    source = paths.templates_raw / f"{template_id}.png"
    pixel_width, pixel_height = _background(source, size_mm, kind)
    now = utc_now_iso()
    base = dict(
        schema_version=2,
        template_id=template_id,
        display_name=f"通用格式验收-{kind}",
        status=TemplateStatus.CALIBRATED,
        physical_width_mm=size_mm[0],
        physical_height_mm=size_mm[1],
        physical_size_source="user_measurement",
        source_media=source.relative_to(paths.root).as_posix(),
        source_sha256=sha256_file(source),
        source_kind="raster",
        source_preview_image=source.relative_to(paths.root).as_posix(),
        source_pixel_width=pixel_width,
        source_pixel_height=pixel_height,
        orientation="portrait",
        binding_side="left",
        notes="合成通用格式验收模板，不代表真实学校报告纸。",
        imported_at=now,
        updated_at=now,
    )
    if kind == "form":
        table_region = RegionMM(id="training_table", x_mm=15, y_mm=38.75, width_mm=120, height_mm=45)
        return TemplateConfig(
            **base,
            content_regions=[
                ContentRegion(
                    id="free_body",
                    x_mm=15,
                    y_mm=95,
                    width_mm=120,
                    height_mm=85,
                    flow_order=0,
                    layout_mode="free",
                    baseline_start_mm=102,
                    line_spacing_mm=7,
                )
            ],
            fields={
                "student_name": FieldTarget(id="student_name", x_mm=24, y_mm=15, width_mm=41, height_mm=8, alignment="center", baseline_offset_mm=-1.5),
                "report_date": FieldTarget(id="report_date", x_mm=86, y_mm=15, width_mm=40, height_mm=8, alignment="center", baseline_offset_mm=-1.5),
            },
            table_regions=[table_region],
            tables={
                "training_table": TableDefinition(
                    id="training_table", region=table_region, rows=3, columns=3, font_size_pt=8.5
                )
            },
        )
    if kind == "lined":
        line_values = [42 + index * 8 for index in range(21)]
        return TemplateConfig(
            **base,
            content_regions=[
                ContentRegion(
                    id="two_columns",
                    x_mm=20,
                    y_mm=38,
                    width_mm=140,
                    height_mm=170,
                    flow_order=0,
                    layout_mode="lined",
                    columns=2,
                    column_gap_mm=8,
                    baseline_offset_mm=-0.6,
                )
            ],
            writing_lines=[
                WritingLine(id=f"line_{index:02d}", x_start_mm=20, x_end_mm=160, y_mm=y)
                for index, y in enumerate(line_values, 1)
            ],
        )
    return TemplateConfig(
        **base,
        content_regions=[
            ContentRegion(
                id="summary",
                x_mm=12,
                y_mm=44,
                width_mm=size_mm[0] - 24,
                height_mm=14,
                flow_order=0,
                layout_mode="free",
                baseline_start_mm=50,
                line_spacing_mm=7,
            ),
            ContentRegion(
                id="body",
                x_mm=12,
                y_mm=90,
                width_mm=size_mm[0] - 24,
                height_mm=size_mm[1] - 104,
                flow_order=1,
                layout_mode="free",
                baseline_start_mm=98,
                line_spacing_mm=7,
            ),
        ],
        fixed_text_regions=[
            RegionMM(id="summary_label", x_mm=12, y_mm=32, width_mm=24, height_mm=8),
            RegionMM(id="body_label", x_mm=12, y_mm=74, width_mm=24, height_mm=8),
        ],
    )


def main() -> None:
    paths = get_paths()
    paths.ensure()
    configs = {
        "format_form": _config(paths, "format_form", (150.0, 210.0), "form"),
        "format_lined_columns": _config(paths, "format_lined_columns", (180.0, 250.0), "lined"),
        "format_free_regions": _config(paths, "format_free_regions", (130.0, 180.0), "free"),
    }
    for config in configs.values():
        save_template(paths, config)

    long_text = (
        "本页用于验证双栏横线排版。文字应先填满左栏，再进入右栏；每一行都按扫描模板记录的真实横线坐标放置，"
        "栏间留白不会被正文侵入。不同页面可以使用不同的物理尺寸、正文宽度和行距，排版引擎会在换页时切换对应模板。"
        "对于以后新增的封面、目录、日记、分析、总结或签字页，只需要导入扫描件、填写实测尺寸并标定区域，不需要修改排版核心。"
    ) * 4
    flow = FlowDocument(
        output_stem="generalized_format_showcase",
        template_sequence=["format_form", "format_lined_columns", "format_free_regions"],
        show_page_numbers=False,
        blocks=[
            FlowBlock(id="name", type="field", field="student_name", text="示例学生"),
            FlowBlock(id="date", type="field", field="report_date", text="2026-08-28"),
            FlowBlock(
                id="table",
                type="table",
                table_id="training_table",
                table_values=[["项目", "内容", "状态"], ["模板", "字段与表格", "通过"], ["输出", "三类 PDF", "通过"]],
            ),
            FlowBlock(id="form_note", type="paragraph", text="本页验证固定字段、预印表格填充和无横线自由区域。正式套打版只包含新增文字，不会重复打印背景中的边框与标题。"),
            FlowBlock(id="next", type="page_break"),
            FlowBlock(id="two_column_title", type="heading", level=1, text="双栏横线正文"),
            FlowBlock(id="two_column_body", type="paragraph", text=long_text),
            FlowBlock(id="third", type="page_break"),
            FlowBlock(id="summary_title", type="heading", level=2, text="多内容区摘要"),
            FlowBlock(id="summary_text", type="paragraph", text="上方摘要区和下方正文区拥有独立流转顺序。"),
            FlowBlock(id="body_text", type="paragraph", text="最后一页验证不同纸张尺寸和多个无横线内容区。页面坐标仍以毫米保存，输出 PDF 的 MediaBox 会随模板精确切换。"),
        ],
    )
    document = LayoutEngine(paths).layout(flow)
    exported = ExportManager(paths).export_paginated_three_pdfs(configs, document)
    for name, output in exported.items():
        print(f"{name}: {output}")


if __name__ == "__main__":
    main()
