from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.daily_material_reader import load_daily_review, save_daily_review
from src.export_manager import ExportManager
from src.image_processor import process_uploaded_image
from src.layout_engine import LayoutEngine
from src.models import DailyReview, FlowBlock, FlowDocument
from src.paths import get_paths
from src.storage import save_json_atomic, utc_now_iso
from src.template_importer import load_template


DEMO_DATE = "2099-01-03"


def synthetic_photo(size: tuple[int, int], palette: tuple[str, str, str], label: str) -> bytes:
    image = Image.new("RGB", size, palette[0])
    draw = ImageDraw.Draw(image)
    width, height = size
    draw.rounded_rectangle(
        (width * 0.08, height * 0.12, width * 0.92, height * 0.82),
        radius=max(12, width // 40),
        fill=palette[1],
        outline="white",
        width=max(4, width // 250),
    )
    for index in range(5):
        x0 = width * (0.14 + index * 0.14)
        draw.rectangle(
            (x0, height * 0.24, x0 + width * 0.08, height * 0.68),
            fill=palette[2],
            outline="white",
            width=3,
        )
        draw.ellipse(
            (x0 + width * 0.015, height * 0.3, x0 + width * 0.065, height * 0.36),
            fill="white",
        )
    draw.text((width * 0.1, height * 0.88), f"SYNTHETIC DEMO - {label}", fill="white")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=94)
    return buffer.getvalue()


def prepare_daily_review(paths) -> DailyReview:
    existing = load_daily_review(paths, DEMO_DATE)
    if existing.images:
        return existing
    specs = [
        ((1800, 1100), ("#183b66", "#2f6aa1", "#e4a84f"), "EQUIPMENT"),
        ((1200, 1700), ("#31443d", "#547c68", "#d9c58c"), "ASSEMBLY"),
        ((1800, 1100), ("#4f294f", "#825483", "#7ed0c6"), "INSPECTION"),
    ]
    captions = ["设备结构与功能区域示意", "装配工位与操作区域示意", "检测环节与质量控制示意"]
    texts = [
        "从合成图片可以确认设备外观由多个功能区域构成；正式报告中应结合真实照片说明观察到的部件，不能据此虚构具体型号。",
        "该图用于演示竖幅照片的等比例缩放。生成文字应区分现场观察、工作人员介绍和个人分析，避免把参观写成亲自操作。",
        "检测主题图片可与质量控制段落对应。若用户没有提供测试参数或结果，系统只描述流程和一般性原理，不写入具体数据。",
    ]
    images = []
    for index, (spec, caption, text) in enumerate(zip(specs, captions, texts), 1):
        size, palette, label = spec
        images.append(
            process_uploaded_image(
                paths,
                DEMO_DATE,
                index,
                f"synthetic_{index:02d}.jpg",
                synthetic_photo(size, palette, label),
                caption=caption,
                generated_text=text,
            )
        )
    review = DailyReview(
        date=DEMO_DATE,
        topic="第三阶段图片与文字审核合成示例",
        notes="该日期和全部图片均为软件验收材料，不代表真实实习经历。",
        status="reviewed",
        images=images,
        updated_at=utc_now_iso(),
    )
    save_daily_review(paths, review)
    return load_daily_review(paths, DEMO_DATE)


def build_flow(review: DailyReview) -> FlowDocument:
    paths = [image.processed_path for image in review.images]
    return FlowDocument(
        output_stem="phase3_synthetic_image_layout",
        template_sequence=["phase1_synthetic_demo", "phase2_synthetic_continuation"],
        blocks=[
            FlowBlock(
                id="heading",
                type="heading",
                text="三、图片处理与图文混排验证",
                keep_with_next=True,
            ),
            FlowBlock(
                id="intro",
                type="paragraph",
                text="本节全部图片均为合成验收素材，用于检查横幅、竖幅照片的等比例缩放、图题绑定和图片后正文接续。",
            ),
            FlowBlock(
                id="two_photos",
                type="image_grid",
                image_paths=paths[:2],
                captions=["设备结构示意", "装配工位示意"],
                target_height_mm=43,
            ),
            FlowBlock(
                id="between_text",
                type="paragraph",
                text="两张图片在同一行内保持各自宽高比，图题随图片移动；当前页空间不足时，图片和图题整体进入下一页。",
            ),
            FlowBlock(
                id="single_photo",
                type="image",
                image_paths=[paths[2]],
                captions=["检测环节与质量控制示意"],
                target_height_mm=50,
            ),
            FlowBlock(
                id="after_text",
                type="paragraph",
                text="单图排版完成后，后续正文从图题之后的下一条可用横线继续。正式套打文件保留照片、图题和正文，但不会重复打印模板背景。",
            ),
        ],
        show_page_numbers=True,
    )


def main() -> None:
    paths = get_paths()
    review = prepare_daily_review(paths)
    flow = build_flow(review)
    document = LayoutEngine(paths).layout(flow)
    configs = {
        template_id: load_template(paths, template_id)
        for template_id in {page.template_id for page in document.pages}
    }
    save_json_atomic(paths.root / "reports" / "structured" / "phase3_flow.json", flow)
    save_json_atomic(
        paths.root / "reports" / "structured" / "phase3_paginated.json", document
    )
    exported = ExportManager(paths).export_paginated_three_pdfs(configs, document)
    print(
        json.dumps(
            {
                "date": review.date,
                "images": len(review.images),
                "pages": len(document.pages),
                "images_by_page": [len(page.image_items) for page in document.pages],
                "outputs": {key: str(value) if value else None for key, value in exported.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

