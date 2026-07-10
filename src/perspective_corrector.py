from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

from .models import TemplateStatus
from .paths import ProjectPaths
from .storage import utc_now_iso
from .template_importer import load_template, save_template


def _order_points(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(differences)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def detect_page_quad(image: np.ndarray) -> np.ndarray | None:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required for automatic page-corner detection") from exc
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 140)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = image.shape[0] * image.shape[1]
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:20]:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(polygon) == 4 and cv2.contourArea(polygon) >= image_area * 0.45:
            return _order_points(polygon.reshape(4, 2).astype(np.float32))
    return None


def correct_template(
    paths: ProjectPaths,
    template_id: str,
    use_full_frame: bool = False,
    force: bool = False,
    corners_px: list[tuple[float, float]] | None = None,
    deskew_degree: float = 0.0,
) -> Path:
    config = load_template(paths, template_id)
    physical_width_mm, physical_height_mm = config.require_confirmed_size()
    if corners_px is not None and deskew_degree:
        raise ValueError("Use either manual perspective corners or deskew_degree, not both")
    if config.corrected_image and not force:
        raise FileExistsError(
            "Corrected image already exists. Use --force only after checking the existing result."
        )
    input_relative = config.source_preview_image or config.source_media
    input_path = paths.root / input_relative
    if corners_px is not None:
        if len(corners_px) != 4:
            raise ValueError("corners_px must contain TL, TR, BR and BL points")
        with Image.open(input_path) as opened:
            source = opened.convert("RGB")
        if deskew_degree:
            source = source.rotate(
                deskew_degree,
                resample=Image.Resampling.BICUBIC,
                expand=False,
                fillcolor="white",
            )
        for x, y in corners_px:
            if x < 0 or y < 0 or x > source.width or y > source.height:
                raise ValueError("A manual corner lies outside the source image")
        source_area = max(1, source.width * source.height)
        target_ratio = physical_width_mm / physical_height_mm
        target_width = max(1, int(round(math.sqrt(source_area * target_ratio))))
        target_height = max(1, int(round(target_width / target_ratio)))
        top_left, top_right, bottom_right, bottom_left = corners_px
        quad = (
            top_left[0],
            top_left[1],
            bottom_left[0],
            bottom_left[1],
            bottom_right[0],
            bottom_right[1],
            top_right[0],
            top_right[1],
        )
        corrected_pil = source.transform(
            (target_width, target_height),
            Image.Transform.QUAD,
            quad,
            resample=Image.Resampling.BICUBIC,
        )
        output = paths.templates_corrected / f"{config.template_id}.png"
        if output.exists() and not force:
            raise FileExistsError(output)
        corrected_pil.save(output, format="PNG", optimize=True)
        config.corrected_image = output.relative_to(paths.root).as_posix()
        config.source_pixel_width = target_width
        config.source_pixel_height = target_height
        config.status = TemplateStatus.CORRECTED
        config.confidence["page_boundary"] = 1.0
        config.manual_measurements["perspective_corners_px"] = ";".join(
            f"{x:g},{y:g}" for x, y in corners_px
        )
        config.manual_measurements["deskew_degree"] = deskew_degree
        config.updated_at = utc_now_iso()
        save_template(paths, config)
        return output

    try:
        import cv2
    except ImportError as exc:
        if not use_full_frame:
            raise RuntimeError(
                "OpenCV is required for automatic page-corner detection. Install project "
                "dependencies, or use --use-full-frame only when the image boundary is the "
                "verified paper boundary."
            ) from exc
        with Image.open(input_path) as opened:
            source = opened.convert("RGB")
        if deskew_degree:
            source = source.rotate(
                deskew_degree,
                resample=Image.Resampling.BICUBIC,
                expand=False,
                fillcolor="white",
            )
        source_area = max(1, source.width * source.height)
        target_ratio = physical_width_mm / physical_height_mm
        target_width = max(1, int(round(math.sqrt(source_area * target_ratio))))
        target_height = max(1, int(round(target_width / target_ratio)))
        corrected_pil = source.resize(
            (target_width, target_height), Image.Resampling.LANCZOS
        )
        output = paths.templates_corrected / f"{config.template_id}.png"
        if output.exists() and not force:
            raise FileExistsError(output)
        corrected_pil.save(output, format="PNG", optimize=True)
        config.corrected_image = output.relative_to(paths.root).as_posix()
        config.source_pixel_width = target_width
        config.source_pixel_height = target_height
        config.status = TemplateStatus.CORRECTED
        config.confidence["page_boundary"] = 1.0
        config.manual_measurements["deskew_degree"] = deskew_degree
        config.updated_at = utc_now_iso()
        save_template(paths, config)
        return output

    image = None
    if deskew_degree:
        pil_image = Image.open(input_path).convert("RGB")
        pil_image = pil_image.rotate(
            deskew_degree,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor="white",
        )
        image = cv2.cvtColor(np.asarray(pil_image), cv2.COLOR_RGB2BGR)
    else:
        image = cv2.imread(str(input_path))
        if image is None:
            pil_image = Image.open(input_path).convert("RGB")
            image = cv2.cvtColor(np.asarray(pil_image), cv2.COLOR_RGB2BGR)
    height, width = image.shape[:2]
    points = detect_page_quad(image)
    if points is None:
        if not use_full_frame:
            raise ValueError(
                "No reliable four-corner page boundary was detected. Review the scan or rerun "
                "with --use-full-frame only if the image boundary is the true paper boundary."
            )
        points = np.array(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
            dtype=np.float32,
        )

    source_area = max(1, width * height)
    target_ratio = physical_width_mm / physical_height_mm
    target_width = max(1, int(round(math.sqrt(source_area * target_ratio))))
    target_height = max(1, int(round(target_width / target_ratio)))
    destination = np.array(
        [
            [0, 0],
            [target_width - 1, 0],
            [target_width - 1, target_height - 1],
            [0, target_height - 1],
        ],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(points, destination)
    corrected = cv2.warpPerspective(
        image,
        matrix,
        (target_width, target_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    output = paths.templates_corrected / f"{config.template_id}.png"
    if output.exists() and not force:
        raise FileExistsError(output)
    if not cv2.imwrite(str(output), corrected):
        raise OSError(f"Failed to write corrected image: {output}")

    config.corrected_image = output.relative_to(paths.root).as_posix()
    config.source_pixel_width = target_width
    config.source_pixel_height = target_height
    config.status = TemplateStatus.CORRECTED
    config.confidence["page_boundary"] = 1.0 if use_full_frame else 0.8
    config.manual_measurements["deskew_degree"] = deskew_degree
    config.updated_at = utc_now_iso()
    save_template(paths, config)
    return output
