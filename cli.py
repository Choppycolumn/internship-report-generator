from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.export_manager import ExportManager
from src.models import LayoutDocument, PrinterCalibration, TextItem
from src.line_detector import LineDetectionOptions, apply_detected_lines, detect_horizontal_lines
from src.daily_material_reader import load_daily_review, save_daily_review
from src.paths import get_paths
from src.pdf_renderer import PdfRenderer
from src.perspective_corrector import correct_template
from src.printer_calibration import (
    calibration_path,
    generate_calibration_page,
    save_calibration,
)
from src.requirement_parser import RequirementImporter
from src.template_calibrator import mark_calibrated
from src.template_importer import TemplateImporter, load_template, set_physical_size


def _json_print(value) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="internship-report-generator",
        description="生产（专业）实习报告智能生成与精确套打系统",
    )
    groups = parser.add_subparsers(dest="group", required=True)

    project = groups.add_parser("project")
    project_commands = project.add_subparsers(dest="command", required=True)
    project_commands.add_parser("init")

    requirements = groups.add_parser("requirements")
    requirement_commands = requirements.add_subparsers(dest="command", required=True)
    requirement_import = requirement_commands.add_parser("import")
    requirement_import.add_argument("file", type=Path)
    requirement_import.add_argument(
        "--category",
        choices=["school_rules", "internship_outline", "scoring_rules"],
        default="school_rules",
    )

    template = groups.add_parser("template")
    template_commands = template.add_subparsers(dest="command", required=True)
    template_add = template_commands.add_parser("add")
    template_add.add_argument("scan_file", type=Path)
    template_add.add_argument("--template-id")
    template_add.add_argument("--display-name")
    template_add.add_argument("--notes", default="")

    template_size = template_commands.add_parser("set-size")
    template_size.add_argument("template_id")
    template_size.add_argument("--width-mm", type=float, required=True)
    template_size.add_argument("--height-mm", type=float, required=True)
    template_size.add_argument(
        "--orientation", choices=["unknown", "portrait", "landscape"], default="unknown"
    )
    template_size.add_argument(
        "--binding-side",
        choices=["unknown", "left", "right", "top", "none"],
        default="unknown",
    )
    template_size.add_argument("--notes")
    template_size.add_argument(
        "--provisional",
        action="store_true",
        help="Use a user-accepted estimate for preview/calibration while keeping formal print blocked",
    )

    template_correct = template_commands.add_parser("correct")
    template_correct.add_argument("template_id")
    template_correct.add_argument("--use-full-frame", action="store_true")
    template_correct.add_argument("--force", action="store_true")
    template_correct.add_argument("--deskew-degree", type=float, default=0.0)
    template_correct.add_argument(
        "--corners-px",
        help="Manual TLx,TLy,TRx,TRy,BRx,BRy,BLx,BLy source pixel coordinates",
    )

    template_detect = template_commands.add_parser("detect-lines")
    template_detect.add_argument("template_id")
    template_detect.add_argument("--darkness-threshold", type=int, default=210)
    template_detect.add_argument("--minimum-dark-fraction", type=float, default=0.55)
    template_detect.add_argument("--merge-distance-mm", type=float, default=0.8)
    template_detect.add_argument("--apply", action="store_true")

    template_calibrate = template_commands.add_parser("calibrate")
    template_calibrate.add_argument("template_id")
    template_calibrate.add_argument("--mark-complete", action="store_true")

    template_preview = template_commands.add_parser("preview")
    template_preview.add_argument("template_id")

    printer = groups.add_parser("printer")
    printer_commands = printer.add_subparsers(dest="command", required=True)
    calibration_page = printer_commands.add_parser("calibration-page")
    calibration_page.add_argument("template_id")

    printer_set = printer_commands.add_parser("set-calibration")
    printer_set.add_argument("printer_name")
    printer_set.add_argument("--template-id", required=True)
    printer_set.add_argument("--x-offset-mm", type=float, default=0.0)
    printer_set.add_argument("--y-offset-mm", type=float, default=0.0)
    printer_set.add_argument("--scale-x", type=float, default=1.0)
    printer_set.add_argument("--scale-y", type=float, default=1.0)
    printer_set.add_argument("--rotation-degree", type=float, default=0.0)

    test_print = printer_commands.add_parser("test-print")
    test_print.add_argument("template_id")
    test_print.add_argument("--printer-name")

    day = groups.add_parser("day")
    day_commands = day.add_subparsers(dest="command", required=True)
    day_import = day_commands.add_parser("import")
    day_import.add_argument("date")
    day_analyze = day_commands.add_parser("analyze")
    day_analyze.add_argument("date")
    day_review = day_commands.add_parser("review-app")
    day_review.add_argument("--host", default="127.0.0.1")
    day_review.add_argument("--port", type=int, default=8765)
    return parser


def execute(args: argparse.Namespace) -> int:
    paths = get_paths()
    if args.group == "project" and args.command == "init":
        paths.ensure()
        _json_print({"status": "initialized", "root": paths.root})
        return 0

    if args.group == "requirements" and args.command == "import":
        record = RequirementImporter(paths).import_file(args.file, args.category)
        _json_print(record)
        return 0

    if args.group == "template" and args.command == "add":
        config = TemplateImporter(paths).add(
            args.scan_file, args.template_id, args.display_name, args.notes
        )
        _json_print(config)
        return 0
    if args.group == "template" and args.command == "set-size":
        config = set_physical_size(
            paths,
            args.template_id,
            args.width_mm,
            args.height_mm,
            args.orientation,
            args.binding_side,
            args.notes,
            args.provisional,
        )
        _json_print(config)
        return 0
    if args.group == "template" and args.command == "correct":
        corners = None
        if args.corners_px:
            values = [float(value.strip()) for value in args.corners_px.split(",")]
            if len(values) != 8:
                raise ValueError("--corners-px requires exactly eight comma-separated numbers")
            corners = [(values[index], values[index + 1]) for index in range(0, 8, 2)]
        output = correct_template(
            paths,
            args.template_id,
            args.use_full_frame,
            args.force,
            corners,
            args.deskew_degree,
        )
        _json_print({"corrected_image": output})
        return 0
    if args.group == "template" and args.command == "detect-lines":
        lines = detect_horizontal_lines(
            paths,
            args.template_id,
            LineDetectionOptions(
                darkness_threshold=args.darkness_threshold,
                minimum_dark_fraction=args.minimum_dark_fraction,
                merge_distance_mm=args.merge_distance_mm,
            ),
        )
        applied = False
        if args.apply:
            lines = apply_detected_lines(paths, args.template_id)
            applied = True
        _json_print(
            {
                "template_id": args.template_id,
                "detected_count": len(lines),
                "applied": applied,
                "lines": lines,
            }
        )
        return 0
    if args.group == "template" and args.command == "calibrate":
        config = load_template(paths, args.template_id)
        config.require_confirmed_size()
        if args.mark_complete:
            config = mark_calibrated(paths, args.template_id)
            _json_print(config)
        else:
            _json_print(
                {
                    "status": "ready_for_manual_calibration",
                    "template_id": args.template_id,
                    "command": "streamlit run app.py",
                }
            )
        return 0
    if args.group == "template" and args.command == "preview":
        config = load_template(paths, args.template_id)
        document = LayoutDocument(
            template_id=config.template_id,
            output_stem=f"{config.template_id}_template",
            text_items=[],
        )
        renderer = PdfRenderer(paths)
        preview = paths.output_previews / f"{document.output_stem}_preview.pdf"
        debug = paths.output_debug / f"{document.output_stem}_layout_debug.pdf"
        renderer.render(config, document, preview, "preview")
        renderer.render(config, document, debug, "debug")
        _json_print({"preview": preview, "debug": debug})
        return 0

    if args.group == "printer" and args.command == "calibration-page":
        config = load_template(paths, args.template_id)
        output = generate_calibration_page(paths, config)
        _json_print({"calibration_page": output})
        return 0
    if args.group == "printer" and args.command == "set-calibration":
        load_template(paths, args.template_id).require_confirmed_size()
        calibration = save_calibration(
            paths,
            args.printer_name,
            args.template_id,
            args.x_offset_mm,
            args.y_offset_mm,
            args.scale_x,
            args.scale_y,
            args.rotation_degree,
        )
        _json_print(calibration)
        return 0
    if args.group == "printer" and args.command == "test-print":
        config = load_template(paths, args.template_id)
        width_mm, height_mm = config.require_confirmed_size()
        calibration = None
        if args.printer_name:
            path = calibration_path(paths, args.printer_name, args.template_id)
            calibration = PrinterCalibration.model_validate_json(path.read_text(encoding="utf-8"))
        document = LayoutDocument(
            template_id=config.template_id,
            output_stem=f"{config.template_id}_test_print",
            text_items=[
                TextItem(
                    id="test_print_label",
                    text="打印位置测试：请使用实际大小 100%",
                    x_mm=max(5.0, width_mm * 0.1),
                    baseline_y_mm=max(15.0, height_mm * 0.15),
                    font_size_pt=10.5,
                )
            ],
        )
        exported = ExportManager(paths).export_three_pdfs(config, document, calibration)
        _json_print(exported)
        return 0
    if args.group == "day" and args.command == "import":
        review = load_daily_review(paths, args.date)
        save_daily_review(paths, review)
        _json_print(review)
        return 0
    if args.group == "day" and args.command == "analyze":
        review = load_daily_review(paths, args.date)
        _json_print(
            {
                "date": review.date,
                "topic": review.topic,
                "status": review.status,
                "image_count": len(review.images),
                "approved_images": sum(1 for image in review.images if image.approved),
                "warnings": {
                    image.id: image.quality.warnings
                    for image in review.images
                    if image.quality.warnings
                },
                "images_missing_caption": [
                    image.id for image in review.images if not image.caption.strip()
                ],
                "images_missing_text": [
                    image.id for image in review.images if not image.generated_text.strip()
                ],
            }
        )
        return 0
    if args.group == "day" and args.command == "review-app":
        from daily_review_app import serve

        serve(paths, args.host, args.port)
        return 0
    raise ValueError("Unsupported command")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return execute(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
