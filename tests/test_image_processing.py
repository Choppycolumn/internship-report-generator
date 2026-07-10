from __future__ import annotations

import base64
import io

from PIL import Image, ImageDraw

from daily_review_app import _save_payload
from src.daily_material_reader import load_daily_review
from src.image_analyzer import hash_distance
from src.image_processor import process_uploaded_image


def make_image_bytes(size=(1400, 1000), color=(235, 240, 250)) -> bytes:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    for x in range(80, size[0] - 80, 45):
        draw.line((x, 60, size[0] - x // 3, size[1] - 60), fill=(20, 55, 120), width=5)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=94)
    return buffer.getvalue()


def test_uploaded_image_is_preserved_and_processed(project_paths) -> None:
    data = make_image_bytes()
    review = process_uploaded_image(
        project_paths,
        "2026-07-10",
        1,
        "camera.jpg",
        data,
        caption="图1 合成测试照片",
        generated_text="这是一段与图片对应的测试文字。",
    )
    assert (project_paths.root / review.original_path).read_bytes() == data
    assert (project_paths.root / review.processed_path).exists()
    assert review.quality.width_px == 1400
    assert review.quality.height_px == 1000
    assert review.quality.sha256


def test_duplicate_upload_is_flagged_in_daily_review(project_paths) -> None:
    data = make_image_bytes()
    data_url = "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
    payload = {
        "date": "2026-07-11",
        "topic": "合成审核测试",
        "notes": "仅用于测试。",
        "status": "draft",
        "images": [
            {"original_name": "first.jpg", "data_url": data_url, "caption": "图1", "generated_text": "文字1"},
            {"original_name": "second.jpg", "data_url": data_url, "caption": "图2", "generated_text": "文字2"},
        ],
    }
    review = _save_payload(project_paths, payload)
    assert len(review.images) == 2
    assert review.images[1].duplicate_of == review.images[0].id
    assert "POSSIBLE_DUPLICATE" in review.images[1].quality.warnings
    reloaded = load_daily_review(project_paths, "2026-07-11")
    assert reloaded.images[0].generated_text == "文字1"


def test_perceptual_hash_distance_is_zero_for_same_image() -> None:
    assert hash_distance("00ff", "00ff") == 0

