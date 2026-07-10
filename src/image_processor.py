from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from .image_analyzer import analyze_image
from .models import DailyImageReview
from .paths import ProjectPaths


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SUPPORTED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "TIFF": ".tiff", "WEBP": ".webp"}


def process_uploaded_image(
    paths: ProjectPaths,
    date: str,
    index: int,
    original_name: str,
    data: bytes,
    caption: str = "",
    generated_text: str = "",
) -> DailyImageReview:
    if not data:
        raise ValueError("Uploaded image is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("A single uploaded image cannot exceed 25 MB")
    try:
        opened = Image.open(io.BytesIO(data))
        opened.load()
    except Exception as exc:
        raise ValueError(f"Unsupported or damaged image: {original_name}") from exc
    if opened.format not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported image format: {opened.format}")
    exif = opened.getexif()
    exif_gps_present = bool(exif.get_ifd(0x8825)) if 0x8825 in exif else False
    corrected = ImageOps.exif_transpose(opened).convert("RGB")
    initial_gray = corrected.convert("L")
    mean = int(initial_gray.resize((1, 1)).getpixel((0, 0)))
    extrema = initial_gray.getextrema()
    contrast_range = extrema[1] - extrema[0]
    if mean < 55:
        corrected = ImageEnhance.Brightness(corrected).enhance(1.12)
    if contrast_range < 90:
        corrected = ImageEnhance.Contrast(corrected).enhance(1.08)
    if max(corrected.size) > 3200:
        scale = 3200 / max(corrected.size)
        corrected = corrected.resize(
            (
                max(1, round(corrected.width * scale)),
                max(1, round(corrected.height * scale)),
            ),
            Image.Resampling.LANCZOS,
        )

    day_dir = paths.root / "days" / date
    originals_dir = day_dir / "attachments" / "originals"
    originals_dir.mkdir(parents=True, exist_ok=True)
    original_suffix = SUPPORTED_FORMATS[opened.format]
    original_path = originals_dir / f"original_{index:02d}{original_suffix}"
    processed_path = day_dir / f"photo_{index:02d}.jpg"
    if original_path.exists() or processed_path.exists():
        raise FileExistsError(f"Image slot {index:02d} already exists for {date}")
    original_path.write_bytes(data)
    corrected.save(processed_path, format="JPEG", quality=92, optimize=True)
    quality = analyze_image(corrected, data, exif_gps_present)
    return DailyImageReview(
        id=f"image_{index:02d}",
        original_name=original_name,
        original_path=original_path.relative_to(paths.root).as_posix(),
        processed_path=processed_path.relative_to(paths.root).as_posix(),
        caption=caption,
        generated_text=generated_text,
        quality=quality,
    )
