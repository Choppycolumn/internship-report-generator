from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image

from src.models import ContentRegion, FieldTarget, RegionMM, WritingLine
from src.line_detector import apply_detected_lines, detect_horizontal_lines
from src.paths import get_paths
from src.template_calibrator import (
    REGION_KINDS,
    mark_calibrated,
    replace_fields,
    replace_regions,
    replace_writing_lines,
)
from src.template_editor import create_editor_overlay
from src.template_importer import load_template, set_physical_size


REGION_LABELS = {
    "content_regions": "正文区域",
    "header_regions": "页眉区域",
    "fixed_text_regions": "固定文字区域",
    "forbidden_regions": "禁止打印区域",
    "image_regions": "图片区域",
    "table_regions": "表格区域",
    "signature_regions": "签字区域",
    "page_number_regions": "页码区域",
}


def _regions_as_rows(regions: list[RegionMM]) -> list[dict]:
    return [region.model_dump() for region in regions]


def _lines_as_rows(lines: list[WritingLine]) -> list[dict]:
    return [line.model_dump() for line in lines]


def _editor_rows(value) -> list[dict]:
    """Normalize Streamlit's list/DataFrame editor return value."""
    if hasattr(value, "to_dict"):
        return value.to_dict("records")
    return [dict(row) for row in value]


def main() -> None:
    import pandas as pd
    import streamlit as st
    from streamlit_drawable_canvas import st_canvas

    paths = get_paths()
    st.set_page_config(page_title="实习报告模板标定", layout="wide")
    st.title("实习报告模板毫米标定")
    st.caption("左上角为原点；x 向右、y 向下；所有保存值均为毫米。")

    configs = sorted(paths.templates_config.glob("*.json"))
    if not configs:
        st.info("尚未导入模板。请先运行 python cli.py template add <scan_file>。")
        return
    template_ids = [path.stem for path in configs]
    template_id = st.sidebar.selectbox("模板", template_ids)
    config = load_template(paths, template_id)
    st.sidebar.json(
        {
            "status": config.status.value,
            "physical_width_mm": config.physical_width_mm,
            "physical_height_mm": config.physical_height_mm,
            "size_source": config.physical_size_source,
        }
    )

    if not config.has_confirmed_size:
        st.error("此模板没有用户实测物理尺寸，标定功能已锁定。PDF 介质框和图片比例不会被采用。")
        with st.form("set-size"):
            width = st.number_input("实测宽度 (mm)", min_value=1.0, value=None)
            height = st.number_input("实测高度 (mm)", min_value=1.0, value=None)
            orientation = st.selectbox("方向", ["unknown", "portrait", "landscape"])
            binding = st.selectbox("装订侧", ["unknown", "left", "right", "top", "none"])
            submitted = st.form_submit_button("保存用户实测尺寸")
            if submitted:
                if width is None or height is None:
                    st.error("必须同时输入实测宽度和高度。")
                else:
                    set_physical_size(paths, template_id, width, height, orientation, binding)
                    st.success("尺寸已保存。请刷新页面继续标定。")
        return

    left, right = st.columns([3, 2])
    with left:
        zoom = st.slider("显示缩放", 60, 140, 100, 10)
        display_width = int(900 * zoom / 100)
        overlay = create_editor_overlay(paths, config, display_width_px=display_width)
        region_kind = st.selectbox(
            "当前矩形类型",
            list(REGION_KINDS),
            format_func=lambda value: REGION_LABELS[value],
        )
        drawing_mode = st.radio("画布模式", ["rect", "transform"], horizontal=True)
        canvas = st_canvas(
            fill_color="rgba(255, 0, 0, 0.10)",
            stroke_width=2,
            stroke_color="#e21d1d",
            background_image=overlay,
            update_streamlit=True,
            height=overlay.height,
            width=overlay.width,
            drawing_mode=drawing_mode,
            key=f"canvas-{template_id}-{zoom}",
        )

        preview_rows: list[dict] = []
        if canvas.json_data:
            width_mm, height_mm = config.require_confirmed_size()
            for index, obj in enumerate(canvas.json_data.get("objects", []), 1):
                if obj.get("type") != "rect":
                    continue
                left_px = float(obj.get("left", 0))
                top_px = float(obj.get("top", 0))
                width_px = float(obj.get("width", 0)) * float(obj.get("scaleX", 1))
                height_px = float(obj.get("height", 0)) * float(obj.get("scaleY", 1))
                preview_rows.append(
                    {
                        "id": f"{region_kind}_{index}",
                        "label": REGION_LABELS[region_kind],
                        "x_mm": round(left_px * width_mm / overlay.width, 3),
                        "y_mm": round(top_px * height_mm / overlay.height, 3),
                        "width_mm": round(width_px * width_mm / overlay.width, 3),
                        "height_mm": round(height_px * height_mm / overlay.height, 3),
                    }
                )
        if preview_rows:
            st.write("画布矩形的实时毫米坐标")
            st.dataframe(preview_rows, use_container_width=True)
            if st.button(f"以画布矩形替换{REGION_LABELS[region_kind]}"):
                replace_regions(
                    paths,
                    template_id,
                    region_kind,
                    [RegionMM.model_validate(row) for row in preview_rows],
                )
                st.success("区域已按毫米保存。")

    with right:
        st.subheader("精确数值编辑")
        selected_kind = st.selectbox(
            "编辑区域组",
            list(REGION_KINDS),
            format_func=lambda value: REGION_LABELS[value],
            key="table-region-kind",
        )
        region_rows = _regions_as_rows(getattr(config, selected_kind))
        region_table = st.data_editor(
            region_rows,
            num_rows="dynamic",
            use_container_width=True,
            key=f"regions-{selected_kind}",
        )
        if st.button("保存区域表"):
            try:
                region_rows = _editor_rows(region_table)
                if selected_kind == "content_regions":
                    regions = [
                        ContentRegion.model_validate(row) for row in region_rows
                    ]
                else:
                    regions = [RegionMM.model_validate(row) for row in region_rows]
                replace_regions(paths, template_id, selected_kind, regions)
                st.success("区域表已保存。")
            except ValueError as exc:
                st.error(str(exc))

        st.subheader("字段目标")
        st.caption("按字段名称保存套打区域；对齐方式支持 left、center、right。")
        field_rows = [
            {"name": name, **target.model_dump()}
            for name, target in config.fields.items()
        ]
        field_table = st.data_editor(
            field_rows,
            num_rows="dynamic",
            use_container_width=True,
            key=f"fields-{template_id}",
        )
        if st.button("保存字段目标"):
            try:
                fields = {}
                for row in _editor_rows(field_table):
                    row = dict(row)
                    name = str(row.pop("name", "")).strip()
                    if name:
                        fields[name] = FieldTarget.model_validate(row)
                replace_fields(paths, template_id, fields)
                st.success("字段目标已保存。")
            except ValueError as exc:
                st.error(str(exc))

        st.subheader("真实横线")
        st.caption("可逐条新增、删除和修改；不假设横线等距。")
        if st.button("自动检测横线建议"):
            suggestions = detect_horizontal_lines(paths, template_id)
            st.success(f"已生成 {len(suggestions)} 条建议；不会自动覆盖人工横线。")
        if config.detected_writing_lines:
            st.write("自动检测建议")
            st.dataframe(_lines_as_rows(config.detected_writing_lines), use_container_width=True)
            if st.button("采用检测建议并替换当前横线"):
                apply_detected_lines(paths, template_id)
                st.success("已采用检测建议。")
        line_rows = _lines_as_rows(config.writing_lines)
        line_table = st.data_editor(
            line_rows,
            num_rows="dynamic",
            use_container_width=True,
            key="writing-lines",
        )
        if st.button("保存横线表"):
            try:
                lines = [WritingLine.model_validate(row) for row in _editor_rows(line_table)]
                replace_writing_lines(paths, template_id, lines)
                st.success("横线已保存。")
            except ValueError as exc:
                st.error(str(exc))

        if st.button("完成本模板标定"):
            mark_calibrated(paths, template_id)
            st.success("模板状态已更新为 calibrated。")


if __name__ == "__main__":
    main()
