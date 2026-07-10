from src.models import LayoutDocument, TextItem
from src.validators import validate_layout


def test_too_small_font_blocks_formal_print(ready_template) -> None:
    document = LayoutDocument(
        template_id=ready_template.template_id,
        output_stem="small_font",
        text_items=[TextItem(id="tiny", text="过小字号", x_mm=15, baseline_y_mm=50, font_size_pt=6)],
    )
    report = validate_layout(ready_template, document)
    assert not report.valid_for_print
    assert any(issue.code == "FONT_TOO_SMALL" for issue in report.issues)


def test_out_of_bounds_text_blocks_formal_print(ready_template) -> None:
    document = LayoutDocument(
        template_id=ready_template.template_id,
        output_stem="outside",
        text_items=[TextItem(id="outside", text="超出页面", x_mm=116, baseline_y_mm=50)],
    )
    report = validate_layout(ready_template, document)
    assert not report.valid_for_print
    assert any(issue.code == "TEXT_OUT_OF_BOUNDS" for issue in report.issues)


def test_provisional_physical_size_blocks_formal_print(ready_template) -> None:
    provisional = ready_template.model_copy(deep=True)
    provisional.physical_size_source = "user_confirmed_estimate"
    document = LayoutDocument(
        template_id=provisional.template_id,
        output_stem="provisional",
        text_items=[TextItem(id="text", text="预览文字", x_mm=15, baseline_y_mm=50)],
    )
    report = validate_layout(provisional, document)
    assert not report.valid_for_print
    assert any(issue.code == "PHYSICAL_SIZE_PROVISIONAL" for issue in report.issues)
