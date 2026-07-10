from pathlib import Path

from PIL import Image, ImageDraw

from src.line_detector import LineDetectionOptions, apply_detected_lines, detect_horizontal_lines
from src.models import RegionMM
from src.template_importer import TemplateImporter, load_template, save_template, set_physical_size


def test_detected_lines_are_suggestions_until_applied(project_paths, tmp_path: Path) -> None:
    source = tmp_path / "lined.png"
    image = Image.new("RGB", (1000, 1500), "white")
    draw = ImageDraw.Draw(image)
    expected_y = [40.0, 51.3, 62.1, 74.0]
    for y_mm in expected_y:
        y_px = round(y_mm * 10)
        draw.line((100, y_px, 900, y_px), fill=(145, 145, 145), width=2)
    image.save(source)
    TemplateImporter(project_paths).add(source, template_id="detector")
    config = set_physical_size(project_paths, "detector", 100.0, 150.0)
    config.content_regions = [
        RegionMM(id="content", x_mm=10, y_mm=30, width_mm=80, height_mm=60)
    ]
    save_template(project_paths, config)

    lines = detect_horizontal_lines(
        project_paths,
        "detector",
        LineDetectionOptions(darkness_threshold=200, minimum_dark_fraction=0.8),
    )
    assert len(lines) == len(expected_y)
    assert all(abs(line.y_mm - expected) < 0.2 for line, expected in zip(lines, expected_y))
    config = load_template(project_paths, "detector")
    assert not config.writing_lines
    assert len(config.detected_writing_lines) == 4

    applied = apply_detected_lines(project_paths, "detector")
    assert len(applied) == 4
    assert all(line.source == "detected" for line in applied)

