from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from src.models import RegionMM, TemplateConfig, TemplateStatus, WritingLine
from src.paths import ProjectPaths
from src.storage import utc_now_iso


@pytest.fixture
def project_paths(tmp_path: Path) -> ProjectPaths:
    paths = ProjectPaths(tmp_path)
    paths.ensure()
    fonts = {
        "candidate_paths": [],
        "fallback_pdf_font": "STSong-Light",
    }
    (tmp_path / "config" / "fonts.json").write_text(
        json.dumps(fonts), encoding="utf-8"
    )
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "config" / "style.json",
        tmp_path / "config" / "style.json",
    )
    return paths


@pytest.fixture
def ready_template(project_paths: ProjectPaths) -> TemplateConfig:
    background = project_paths.templates_preview / "test_background.png"
    Image.new("RGB", (1200, 1800), "white").save(background)
    now = utc_now_iso()
    return TemplateConfig(
        template_id="test_template",
        display_name="test",
        status=TemplateStatus.CALIBRATED,
        physical_width_mm=120.0,
        physical_height_mm=180.0,
        physical_size_source="user_measurement",
        source_media="templates/raw/test.png",
        source_sha256="0" * 64,
        source_kind="raster",
        source_preview_image="templates/preview/test_background.png",
        source_pixel_width=1200,
        source_pixel_height=1800,
        orientation="portrait",
        binding_side="left",
        content_regions=[
            RegionMM(id="content", x_mm=12, y_mm=30, width_mm=98, height_mm=130)
        ],
        forbidden_regions=[
            RegionMM(id="binding", x_mm=0, y_mm=0, width_mm=8, height_mm=180)
        ],
        page_number_regions=[
            RegionMM(id="page_number", x_mm=50, y_mm=165, width_mm=20, height_mm=10)
        ],
        writing_lines=[
            WritingLine(
                id=f"line_{index}",
                x_start_mm=12,
                x_end_mm=110,
                y_mm=y,
            )
            for index, y in enumerate([40, 48.2, 56.1, 64.3, 72.2, 80.4], 1)
        ],
        imported_at=now,
        updated_at=now,
    )
