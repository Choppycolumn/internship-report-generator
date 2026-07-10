from pathlib import Path

import pytest
from PIL import Image

from src.models import TemplateStatus
from src.perspective_corrector import correct_template
from src.template_importer import TemplateImporter, set_physical_size


def test_import_does_not_infer_physical_size(project_paths, tmp_path: Path) -> None:
    source = tmp_path / "near_a4_scan.png"
    Image.new("RGB", (2480, 3508), "white").save(source, dpi=(300, 300))
    config = TemplateImporter(project_paths).add(source, template_id="no_guess")
    assert config.physical_width_mm is None
    assert config.physical_height_mm is None
    assert config.physical_size_source is None
    assert config.status == TemplateStatus.AWAITING_PHYSICAL_SIZE
    with pytest.raises(ValueError, match="user-confirmed physical size"):
        config.require_confirmed_size()


def test_only_explicit_set_size_enables_coordinates(project_paths, tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    Image.new("RGB", (1000, 1400), "white").save(source)
    TemplateImporter(project_paths).add(source, template_id="explicit")
    config = set_physical_size(project_paths, "explicit", 173.2, 251.7)
    assert config.require_confirmed_size() == (173.2, 251.7)
    assert config.physical_size_source == "user_measurement"


def test_user_accepted_estimate_enables_preview_but_is_not_exact(project_paths, tmp_path: Path) -> None:
    source = tmp_path / "estimated.png"
    Image.new("RGB", (1000, 1400), "white").save(source)
    TemplateImporter(project_paths).add(source, template_id="estimated")
    config = set_physical_size(
        project_paths,
        "estimated",
        180.9,
        258.5,
        provisional=True,
    )
    assert config.has_confirmed_size
    assert not config.has_exact_size
    assert config.require_confirmed_size() == (180.9, 258.5)


def test_correction_gate_checks_size_before_optional_dependency(project_paths, tmp_path: Path) -> None:
    source = tmp_path / "locked.png"
    Image.new("RGB", (1000, 1400), "white").save(source)
    TemplateImporter(project_paths).add(source, template_id="locked")
    with pytest.raises(ValueError, match="user-confirmed physical size"):
        correct_template(project_paths, "locked", use_full_frame=True)


def test_explicit_full_frame_correction_respects_measured_ratio(project_paths, tmp_path: Path) -> None:
    source = tmp_path / "flatbed.png"
    Image.new("RGB", (1000, 1400), "white").save(source)
    TemplateImporter(project_paths).add(source, template_id="flatbed")
    set_physical_size(project_paths, "flatbed", 100.0, 150.0)
    corrected = correct_template(project_paths, "flatbed", use_full_frame=True)
    with Image.open(corrected) as image:
        assert abs((image.width / image.height) - (100.0 / 150.0)) < 0.002


def test_manual_four_corner_perspective_correction_without_opencv(project_paths, tmp_path: Path) -> None:
    source = tmp_path / "perspective.png"
    image = Image.new("RGB", (1000, 1400), "black")
    from PIL import ImageDraw

    corners = [(140, 90), (900, 150), (950, 1300), (80, 1260)]
    ImageDraw.Draw(image).polygon(corners, fill="white")
    image.save(source)
    TemplateImporter(project_paths).add(source, template_id="perspective")
    set_physical_size(project_paths, "perspective", 100.0, 150.0)
    corrected = correct_template(
        project_paths,
        "perspective",
        corners_px=corners,
    )
    with Image.open(corrected) as result:
        center = result.getpixel((result.width // 2, result.height // 2))
        assert min(center) > 245
        assert abs((result.width / result.height) - (100.0 / 150.0)) < 0.002
