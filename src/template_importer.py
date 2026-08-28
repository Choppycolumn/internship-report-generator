from __future__ import annotations

import io
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageOps
from pypdf import PdfReader

from .models import TemplateConfig, TemplateStatus
from .paths import ProjectPaths
from .storage import copy_without_overwrite, save_json_atomic, sha256_file, utc_now_iso


SUPPORTED_RASTER_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
SUPPORTED_SUFFIXES = SUPPORTED_RASTER_SUFFIXES | {".pdf"}


def sanitize_template_id(value: str, digest: str = "") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_").lower()
    if not normalized:
        normalized = f"template_{digest[:12]}" if digest else "template"
    if normalized[0].isdigit():
        normalized = f"template_{normalized}"
    return normalized


class TemplateImporter:
    def __init__(self, paths: ProjectPaths):
        self.paths = paths

    def add(
        self,
        scan_file: Path,
        template_id: str | None = None,
        display_name: str | None = None,
        notes: str = "",
    ) -> TemplateConfig:
        scan_file = scan_file.resolve()
        if not scan_file.is_file():
            raise FileNotFoundError(scan_file)
        suffix = scan_file.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported template format: {suffix}")
        digest = sha256_file(scan_file)
        resolved_id = sanitize_template_id(template_id or scan_file.stem, digest)
        config_path = self.paths.template_config(resolved_id)
        if config_path.exists():
            raise FileExistsError(
                f"Template id '{resolved_id}' already exists; existing config was not overwritten."
            )

        stored = copy_without_overwrite(scan_file, self.paths.templates_raw)
        now = utc_now_iso()
        common = {
            "template_id": resolved_id,
            "display_name": display_name or scan_file.stem,
            "status": TemplateStatus.AWAITING_PHYSICAL_SIZE,
            "source_media": stored.relative_to(self.paths.root).as_posix(),
            "source_sha256": digest,
            "notes": notes,
            "imported_at": now,
            "updated_at": now,
        }

        if suffix == ".pdf":
            metadata = self._inspect_pdf(stored, resolved_id)
            config = TemplateConfig(source_kind="pdf", **common, **metadata)
        else:
            metadata = self._inspect_raster(stored, resolved_id)
            config = TemplateConfig(source_kind="raster", **common, **metadata)

        save_json_atomic(config_path, config)
        return config

    def _inspect_raster(self, stored: Path, template_id: str) -> dict:
        with Image.open(stored) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            width, height = image.size
            dpi_info = opened.info.get("dpi")
            dpi = None
            if isinstance(dpi_info, tuple) and dpi_info and all(float(v) > 0 for v in dpi_info):
                dpi = float(sum(dpi_info) / len(dpi_info))
            preview = self.paths.templates_preview / f"{template_id}_source.png"
            image.save(preview, format="PNG", optimize=True)
        return {
            "source_preview_image": preview.relative_to(self.paths.root).as_posix(),
            "source_pixel_width": width,
            "source_pixel_height": height,
            "source_dpi": dpi,
        }

    def _inspect_pdf(self, stored: Path, template_id: str) -> dict:
        reader = PdfReader(str(stored))
        if not reader.pages:
            raise ValueError("PDF contains no pages")
        page = reader.pages[0]
        media_width_mm = float(page.mediabox.width) * 25.4 / 72.0
        media_height_mm = float(page.mediabox.height) * 25.4 / 72.0
        preview = self.paths.templates_preview / f"{template_id}_source.png"
        width = height = None

        images = list(page.images)
        if images:
            embedded = max(images, key=lambda item: len(item.data))
            with Image.open(io.BytesIO(embedded.data)) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                width, height = image.size
                image.save(preview, format="PNG", optimize=True)
        else:
            try:
                import fitz
            except ImportError as exc:
                raise RuntimeError(
                    "This PDF has no directly extractable page image. Install PyMuPDF to render it."
                ) from exc
            document = fitz.open(str(stored))
            pixmap = document[0].get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            pixmap.save(str(preview))
            width, height = pixmap.width, pixmap.height

        return {
            "source_preview_image": preview.relative_to(self.paths.root).as_posix(),
            "source_pixel_width": width,
            "source_pixel_height": height,
            "diagnostic_pdf_media_box_mm": [
                round(media_width_mm, 3),
                round(media_height_mm, 3),
            ],
        }


def load_template(paths: ProjectPaths, template_id: str) -> TemplateConfig:
    config_path = paths.template_config(sanitize_template_id(template_id))
    if not config_path.exists():
        raise FileNotFoundError(f"Template config not found: {config_path}")
    return TemplateConfig.model_validate_json(config_path.read_text(encoding="utf-8"))


def migrate_template(
    paths: ProjectPaths, template_id: str, apply: bool = False
) -> tuple[TemplateConfig, bool]:
    """Load and normalize a template, optionally persisting the v2 document.

    The default is deliberately read-only so users can inspect a migration
    before changing an existing template configuration.
    """
    config_path = paths.template_config(sanitize_template_id(template_id))
    if not config_path.exists():
        raise FileNotFoundError(f"Template config not found: {config_path}")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    config = TemplateConfig.model_validate(raw)
    normalized = config.model_dump(mode="json")
    changed = raw != normalized
    if apply and changed:
        save_template(paths, config)
    return config, changed


def save_template(paths: ProjectPaths, config: TemplateConfig) -> None:
    save_json_atomic(paths.template_config(config.template_id), config)


def set_physical_size(
    paths: ProjectPaths,
    template_id: str,
    width_mm: float,
    height_mm: float,
    orientation: str = "portrait",
    binding_side: str = "unknown",
    notes: str | None = None,
    provisional: bool = False,
) -> TemplateConfig:
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError("Measured width and height must be positive")
    config = load_template(paths, template_id)
    config.physical_width_mm = float(width_mm)
    config.physical_height_mm = float(height_mm)
    config.physical_size_source = (
        "user_confirmed_estimate" if provisional else "user_measurement"
    )
    config.orientation = orientation  # type: ignore[assignment]
    config.binding_side = binding_side  # type: ignore[assignment]
    config.status = TemplateStatus.SIZE_CONFIRMED
    if notes:
        config.notes = f"{config.notes}\n{notes}".strip()
    config.updated_at = utc_now_iso()
    save_template(paths, config)
    return config
