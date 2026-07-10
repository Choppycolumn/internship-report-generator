from src.models import LayoutDocument, TextItem
from src.fonts import register_chinese_font, text_width_mm
from src.text_layout import PROHIBITED_LINE_END, PROHIBITED_LINE_START, wrap_across_widths
from src.validators import estimate_text_width_mm, validate_layout


def test_chinese_text_uses_full_width_estimate() -> None:
    chinese = estimate_text_width_mm("生产实习", 10.5)
    ascii_width = estimate_text_width_mm("abcde", 10.5)
    assert chinese > ascii_width


def test_text_in_binding_region_is_blocked(ready_template) -> None:
    document = LayoutDocument(
        template_id=ready_template.template_id,
        output_stem="collision",
        text_items=[TextItem(id="bad", text="越界", x_mm=2, baseline_y_mm=50)],
    )
    report = validate_layout(ready_template, document)
    assert not report.valid_for_print
    assert any(issue.code == "TEXT_IN_FORBIDDEN_REGION" for issue in report.issues)


def test_chinese_wrapping_avoids_bad_boundary_punctuation(project_paths) -> None:
    font = register_chinese_font(project_paths)
    font_size = 10.5
    width = text_width_mm("这是一个用于测试", font, font_size)
    wrapped, remaining = wrap_across_widths(
        "这是一个用于测试（标点换行）的句子，后面还有内容。",
        [width] * 10,
        font,
        font_size,
    )
    assert not remaining
    assert len(wrapped) >= 2
    assert all(not line.text.startswith(tuple(PROHIBITED_LINE_START)) for line in wrapped)
    assert all(not line.text.endswith(tuple(PROHIBITED_LINE_END)) for line in wrapped)


def test_first_line_indent_reduces_only_first_available_width(project_paths) -> None:
    font = register_chinese_font(project_paths)
    wrapped, remaining = wrap_across_widths(
        "第一行需要缩进，第二行回到左边界。",
        [35.0, 35.0, 35.0],
        font,
        10.5,
        first_line_indent_mm=7.0,
        is_paragraph_start=True,
    )
    assert not remaining
    assert wrapped[0].indent_mm == 7.0
    assert all(line.indent_mm == 0 for line in wrapped[1:])
