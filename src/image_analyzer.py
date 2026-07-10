from __future__ import annotations

import hashlib

import numpy as np
from PIL import Image

from .models import ImageQualityReport


def perceptual_hash(image: Image.Image, size: int = 16) -> str:
    grayscale = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    values = np.asarray(grayscale, dtype=np.float32)
    bits = values >= values.mean()
    bit_string = "".join("1" if value else "0" for value in bits.flat)
    return f"{int(bit_string, 2):0{size * size // 4}x}"


def hash_distance(first: str, second: str) -> int:
    if len(first) != len(second):
        raise ValueError("Perceptual hashes must have the same length")
    return (int(first, 16) ^ int(second, 16)).bit_count()


def analyze_image(
    image: Image.Image,
    original_bytes: bytes,
    exif_gps_present: bool = False,
) -> ImageQualityReport:
    working = image.convert("RGB")
    grayscale = working.convert("L")
    if max(grayscale.size) > 1400:
        scale = 1400 / max(grayscale.size)
        grayscale = grayscale.resize(
            (max(1, round(grayscale.width * scale)), max(1, round(grayscale.height * scale))),
            Image.Resampling.LANCZOS,
        )
    values = np.asarray(grayscale, dtype=np.float32)
    if values.shape[0] >= 3 and values.shape[1] >= 3:
        laplacian = (
            -4 * values[1:-1, 1:-1]
            + values[:-2, 1:-1]
            + values[2:, 1:-1]
            + values[1:-1, :-2]
            + values[1:-1, 2:]
        )
        blur_score = float(laplacian.var())
    else:
        blur_score = 0.0
    brightness = float(values.mean())
    contrast = float(values.std())
    low_resolution = min(working.size) < 800 or working.width * working.height < 1_000_000
    blurry = blur_score < 55.0
    warnings: list[str] = []
    if low_resolution:
        warnings.append("LOW_RESOLUTION")
    if blurry:
        warnings.append("POSSIBLY_BLURRY")
    if brightness < 45:
        warnings.append("TOO_DARK")
    elif brightness > 235:
        warnings.append("TOO_BRIGHT")
    if contrast < 25:
        warnings.append("LOW_CONTRAST")
    if exif_gps_present:
        warnings.append("EXIF_GPS_PRESENT_IN_ORIGINAL")
    return ImageQualityReport(
        sha256=hashlib.sha256(original_bytes).hexdigest(),
        perceptual_hash=perceptual_hash(working),
        width_px=working.width,
        height_px=working.height,
        blur_score=round(blur_score, 3),
        brightness_mean=round(brightness, 3),
        contrast_std=round(contrast, 3),
        is_blurry=blurry,
        is_low_resolution=low_resolution,
        warnings=warnings,
    )

