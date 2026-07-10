from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export_manager import ExportManager
from src.layout_engine import LayoutEngine
from src.line_detector import detect_horizontal_lines
from src.models import FlowBlock, FlowDocument, RegionMM, WritingLine
from src.paths import get_paths
from src.storage import save_json_atomic, utc_now_iso
from src.template_calibrator import mark_calibrated
from src.template_importer import (
    TemplateImporter,
    load_template,
    save_template,
    set_physical_size,
)


FIRST_TEMPLATE = "phase1_synthetic_demo"
CONTINUATION_TEMPLATE = "phase2_synthetic_continuation"
WIDTH_MM = 120.0
HEIGHT_MM = 180.0
CONTINUATION_LINES_MM = [
    38.0,
    46.1,
    54.0,
    62.2,
    70.1,
    78.3,
    86.2,
    94.4,
    102.3,
    110.5,
    118.4,
    126.6,
    134.5,
    142.7,
    150.6,
    158.0,
]


def create_continuation_source(path: Path) -> None:
    image = Image.new("RGB", (1200, 1800), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 1197, 1797), outline=(45, 45, 45), width=3)
    draw.line((90, 255, 1120, 255), fill=(55, 55, 55), width=3)
    draw.text((455, 155), "SYNTHETIC CONTINUATION", fill=(45, 45, 45))
    for y_mm in CONTINUATION_LINES_MM:
        y = round(y_mm * 10)
        draw.line((120, y, 1100, y), fill=(155, 155, 155), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


def prepare_templates(paths) -> dict:
    first = load_template(paths, FIRST_TEMPLATE)
    first.page_number_regions = [
        RegionMM(id="first_page_number", label="合成页码区", x_mm=50, y_mm=165, width_mm=20, height_mm=10)
    ]
    first.updated_at = utc_now_iso()
    save_template(paths, first)
    first = mark_calibrated(paths, FIRST_TEMPLATE)

    source = paths.root / "tmp" / "phase2_continuation_source.png"
    if not source.exists():
        create_continuation_source(source)
    if not paths.template_config(CONTINUATION_TEMPLATE).exists():
        TemplateImporter(paths).add(
            source,
            template_id=CONTINUATION_TEMPLATE,
            display_name="第二阶段非等距横线续页合成模板",
            notes="仅用于第二阶段分页与多模板验收。",
        )
    continuation = load_template(paths, CONTINUATION_TEMPLATE)
    if not continuation.has_confirmed_size:
        continuation = set_physical_size(
            paths,
            CONTINUATION_TEMPLATE,
            WIDTH_MM,
            HEIGHT_MM,
            orientation="portrait",
            binding_side="left",
            notes="合成测试尺寸，不应用于用户模板。",
        )
    continuation.content_regions = [
        RegionMM(id="continuation_content", label="合成续页正文区", x_mm=12, y_mm=32, width_mm=98, height_mm=128)
    ]
    continuation.header_regions = [
        RegionMM(id="continuation_header", label="合成续页页眉", x_mm=9, y_mm=10, width_mm=103, height_mm=16)
    ]
    continuation.forbidden_regions = [
        RegionMM(id="continuation_binding", label="合成续页装订区", x_mm=0, y_mm=0, width_mm=8, height_mm=180)
    ]
    continuation.page_number_regions = [
        RegionMM(id="continuation_page_number", label="合成续页页码区", x_mm=50, y_mm=165, width_mm=20, height_mm=10)
    ]
    continuation.writing_lines = [
        WritingLine(
            id=f"continuation_line_{index:02d}",
            x_start_mm=12,
            x_end_mm=110,
            y_mm=y_mm,
            source="manual",
        )
        for index, y_mm in enumerate(CONTINUATION_LINES_MM, 1)
    ]
    continuation.updated_at = utc_now_iso()
    save_template(paths, continuation)
    continuation = mark_calibrated(paths, CONTINUATION_TEMPLATE)
    detected = detect_horizontal_lines(paths, CONTINUATION_TEMPLATE)
    print(f"detected_line_suggestions: {len(detected)}")
    return {FIRST_TEMPLATE: first, CONTINUATION_TEMPLATE: continuation}


def build_flow() -> FlowDocument:
    blocks = [
        FlowBlock(
            id="stage2_heading",
            type="heading",
            level=1,
            text="一、第二阶段合成排版验证",
            keep_with_next=True,
        ),
        FlowBlock(
            id="baseline_paragraph",
            type="paragraph",
            text=(
                "本页为软件排版能力的合成验证材料，不代表任何真实实习经历。引擎按照模板配置中逐条记录的横线坐标放置文字，"
                "逻辑行与扫描纸面一一对应。正文第一行保留两个汉字宽度的缩进，后续行回到正文左边界。中文逗号、句号、分号、"
                "右括号等符号不得单独出现在行首，左括号和书名号也不应孤立在上一行末尾。"
            ),
        ),
        FlowBlock(
            id="line_heading",
            type="heading",
            level=2,
            text="1. 横线坐标与文字基线",
            keep_with_next=True,
        ),
        FlowBlock(
            id="line_paragraph",
            type="paragraph",
            text=(
                "续页模板中的横线间距被有意设置为轻微不等距。排版程序不会用一个固定行距推算全部行，而是读取三十八毫米、"
                "四十六点一毫米、五十四毫米等实际坐标。每个文本项还保存自身的边界框、字体大小和目标基线，调试文件能够同时显示"
                "扫描横线、检测建议、文字边框以及最终基线，从而为人工微调提供依据。"
            ),
        ),
        FlowBlock(
            id="pagination_heading",
            type="heading",
            level=2,
            text="2. 自动分页与多模板选择",
            keep_with_next=True,
        ),
        FlowBlock(
            id="pagination_paragraph",
            type="paragraph",
            text=(
                "当当前页面剩余横线不足时，引擎把后续内容移动到下一页，并根据模板序列选择续页。标题启用与下一段保持功能，"
                "页面底部只剩一条横线时不会孤立放置标题。段落跨页前会预演当前页和下一页的换行结果，尽量避免下一页只剩一行的"
                "情况。页码来自模板中人工标定的页码区域，因此系统不会擅自猜测页脚位置。"
            ),
        ),
        FlowBlock(
            id="validation_heading",
            type="heading",
            level=1,
            text="二、版面校验与输出隔离",
            keep_with_next=True,
        ),
        FlowBlock(
            id="validation_paragraph",
            type="paragraph",
            text=(
                "正式套打文件只保留新增文字和页码，不包含合成背景、页眉或横线。预览文件叠加扫描背景，便于核对文字是否贴近目标横线；"
                "调试文件额外显示十毫米网格、正文区、禁打区、文字边界和模板编号。若文字进入装订区域、固定页眉、图片区、签字区或"
                "页面外部，验证器会阻止正式套打文件生成，并把错误对象和页码写入结构化报告。"
            ),
        ),
        FlowBlock(
            id="continuity_paragraph",
            type="paragraph",
            text=(
                "这一流程为后续图片混排和每日实习内容审核提供稳定基础。后续阶段只需要产生经过人工确认的结构化内容块，分页器即可"
                "在不改变事实层级的前提下完成逐页排版。当前所有示例文字都明确标记为合成验证内容，不会写入真实生产实习报告。"
            ),
        ),
        FlowBlock(
            id="result_heading",
            type="heading",
            level=2,
            text="3. 第二阶段校验结果记录",
            keep_with_next=True,
        ),
        FlowBlock(
            id="result_paragraph",
            type="paragraph",
            text=(
                "自动检查将记录每页采用的模板编号、物理尺寸、可用横线数量和文本项数量，并核对预览版与正式版的页数是否一致。"
                "对于合成续页，检测器应识别十六条横线，排版后的正文基线应保持相同顺序且允许原始间距轻微变化。最终视觉检查还要确认"
                "行首没有错误标点、标题没有落在页底、页码位于人工标定区域，并且正式套打文件中不存在任何背景图像对象。"
            ),
        ),
    ]
    return FlowDocument(
        output_stem="phase2_synthetic_paginated",
        template_sequence=[FIRST_TEMPLATE, CONTINUATION_TEMPLATE],
        blocks=blocks,
        page_number_start=1,
        show_page_numbers=True,
    )


def main() -> None:
    paths = get_paths()
    configs = prepare_templates(paths)
    flow = build_flow()
    paginated = LayoutEngine(paths).layout(flow)
    save_json_atomic(paths.root / "reports" / "structured" / "phase2_flow.json", flow)
    save_json_atomic(
        paths.root / "reports" / "structured" / "phase2_paginated.json", paginated
    )
    exported = ExportManager(paths).export_paginated_three_pdfs(
        configs, paginated
    )
    print(f"pages: {len(paginated.pages)}")
    print("templates:", [page.template_id for page in paginated.pages])
    for name, path in exported.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
