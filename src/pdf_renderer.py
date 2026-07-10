from __future__ import annotations

from pathlib import Path
import io
from typing import Literal

from PIL import Image, ImageOps
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .coordinate_mapper import mm_to_points
from .fonts import register_chinese_font
from .models import (
    LayoutDocument,
    ImageItem,
    PaginatedDocument,
    PrinterCalibration,
    RegionMM,
    TemplateConfig,
)
from .paths import ProjectPaths
from .template_editor import template_background_path
from .validators import text_item_region, validate_layout, validate_paginated_layout


RenderMode = Literal["preview", "print", "debug"]


class LayoutValidationError(RuntimeError):
    pass


def _top_left_rect_to_pdf(
    region: RegionMM, page_height_mm: float
) -> tuple[float, float, float, float]:
    return (
        mm_to_points(region.x_mm),
        mm_to_points(page_height_mm - region.bottom_mm),
        mm_to_points(region.width_mm),
        mm_to_points(region.height_mm),
    )


class PdfRenderer:
    def __init__(self, paths: ProjectPaths):
        self.paths = paths
        self.font_name = register_chinese_font(paths)

    def render(
        self,
        config: TemplateConfig,
        document: LayoutDocument,
        output: Path,
        mode: RenderMode,
        calibration: PrinterCalibration | None = None,
    ) -> Path:
        width_mm, height_mm = config.require_confirmed_size()
        validation = validate_layout(config, document)
        if mode == "print" and not validation.valid_for_print:
            messages = "; ".join(issue.message for issue in validation.errors)
            raise LayoutValidationError(f"Formal print PDF blocked: {messages}")
        output.parent.mkdir(parents=True, exist_ok=True)
        page_size = (mm_to_points(width_mm), mm_to_points(height_mm))
        pdf = canvas.Canvas(str(output), pagesize=page_size, pageCompression=1)
        pdf.setTitle(f"{document.output_stem} - {mode}")

        if mode in {"preview", "debug"}:
            background = template_background_path(self.paths, config)
            pdf.drawImage(
                ImageReader(str(background)),
                0,
                0,
                width=page_size[0],
                height=page_size[1],
                preserveAspectRatio=False,
                mask="auto",
            )

        pdf.saveState()
        self._apply_calibration(pdf, width_mm, height_mm, calibration)
        self._draw_image_items(pdf, config, document)
        self._draw_text_items(pdf, config, document)
        pdf.restoreState()

        if mode == "debug":
            self._draw_debug(pdf, config, document, calibration)
        pdf.showPage()
        pdf.save()
        return output

    def render_paginated(
        self,
        configs: dict[str, TemplateConfig],
        document: PaginatedDocument,
        output: Path,
        mode: RenderMode,
        calibrations: dict[str, PrinterCalibration] | None = None,
    ) -> Path:
        validation = validate_paginated_layout(configs, document)
        if mode == "print" and not validation.valid_for_print:
            messages = "; ".join(issue.message for issue in validation.errors)
            raise LayoutValidationError(f"Formal print PDF blocked: {messages}")
        first_config = configs[document.pages[0].template_id]
        first_width, first_height = first_config.require_confirmed_size()
        output.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(
            str(output),
            pagesize=(mm_to_points(first_width), mm_to_points(first_height)),
            pageCompression=1,
        )
        pdf.setTitle(f"{document.output_stem} - {mode}")
        calibrations = calibrations or {}
        for page_index, page in enumerate(document.pages, 1):
            config = configs[page.template_id]
            width_mm, height_mm = config.require_confirmed_size()
            page_size = (mm_to_points(width_mm), mm_to_points(height_mm))
            pdf.setPageSize(page_size)
            if mode in {"preview", "debug"}:
                background = template_background_path(self.paths, config)
                pdf.drawImage(
                    ImageReader(str(background)),
                    0,
                    0,
                    width=page_size[0],
                    height=page_size[1],
                    preserveAspectRatio=False,
                    mask="auto",
                )
            calibration = calibrations.get(page.template_id)
            pdf.saveState()
            self._apply_calibration(pdf, width_mm, height_mm, calibration)
            page_document = LayoutDocument(
                template_id=page.template_id,
                output_stem=f"{document.output_stem}_page_{page_index}",
                text_items=page.text_items,
                image_items=page.image_items,
            )
            self._draw_image_items(pdf, config, page_document)
            self._draw_text_items(pdf, config, page_document)
            pdf.restoreState()
            if mode == "debug":
                self._draw_debug(pdf, config, page_document, calibration)
            pdf.showPage()
        pdf.save()
        return output

    def _apply_calibration(
        self,
        pdf: canvas.Canvas,
        width_mm: float,
        height_mm: float,
        calibration: PrinterCalibration | None,
    ) -> None:
        if calibration is None:
            return
        center_x = mm_to_points(width_mm / 2.0)
        center_y = mm_to_points(height_mm / 2.0)
        pdf.translate(mm_to_points(calibration.x_offset_mm), -mm_to_points(calibration.y_offset_mm))
        pdf.translate(center_x, center_y)
        pdf.rotate(-calibration.rotation_degree)
        pdf.scale(calibration.scale_x, calibration.scale_y)
        pdf.translate(-center_x, -center_y)

    def _draw_text_items(
        self,
        pdf: canvas.Canvas,
        config: TemplateConfig,
        document: LayoutDocument,
    ) -> None:
        _, height_mm = config.require_confirmed_size()
        pdf.setFillColorRGB(0, 0, 0)
        for item in document.text_items:
            pdf.setFont(self.font_name, item.font_size_pt)
            x = mm_to_points(item.x_mm)
            baseline_y = mm_to_points(height_mm - item.baseline_y_mm)
            pdf.drawString(x, baseline_y, item.text)

    def _draw_image_items(
        self,
        pdf: canvas.Canvas,
        config: TemplateConfig,
        document: LayoutDocument,
    ) -> None:
        _, page_height_mm = config.require_confirmed_size()
        for item in document.image_items:
            source = self.paths.root / item.path
            with Image.open(source) as opened:
                image = opened.convert("RGB")
            frame_ratio = item.width_mm / item.height_mm
            source_ratio = image.width / image.height
            draw_x_mm = item.x_mm
            draw_y_mm = item.y_mm
            draw_width_mm = item.width_mm
            draw_height_mm = item.height_mm
            image_reader: ImageReader
            if item.crop_mode == "cover":
                target_width = max(1, round(image.height * frame_ratio))
                target_height = max(1, round(image.width / frame_ratio))
                if target_width <= image.width:
                    fitted = ImageOps.fit(
                        image,
                        (target_width, image.height),
                        method=Image.Resampling.LANCZOS,
                        centering=(0.5, 0.5),
                    )
                else:
                    fitted = ImageOps.fit(
                        image,
                        (image.width, target_height),
                        method=Image.Resampling.LANCZOS,
                        centering=(0.5, 0.5),
                    )
                buffer = io.BytesIO()
                fitted.save(buffer, format="JPEG", quality=92)
                buffer.seek(0)
                image_reader = ImageReader(buffer)
            else:
                if source_ratio > frame_ratio:
                    draw_height_mm = item.width_mm / source_ratio
                    draw_y_mm += (item.height_mm - draw_height_mm) / 2.0
                else:
                    draw_width_mm = item.height_mm * source_ratio
                    draw_x_mm += (item.width_mm - draw_width_mm) / 2.0
                image_reader = ImageReader(image)
            pdf.drawImage(
                image_reader,
                mm_to_points(draw_x_mm),
                mm_to_points(page_height_mm - draw_y_mm - draw_height_mm),
                width=mm_to_points(draw_width_mm),
                height=mm_to_points(draw_height_mm),
                preserveAspectRatio=False,
                mask="auto",
            )
            if item.border:
                pdf.setStrokeColorRGB(0.25, 0.25, 0.25)
                pdf.setLineWidth(0.45)
                pdf.rect(
                    mm_to_points(item.x_mm),
                    mm_to_points(page_height_mm - item.y_mm - item.height_mm),
                    mm_to_points(item.width_mm),
                    mm_to_points(item.height_mm),
                    stroke=1,
                    fill=0,
                )

    def _draw_debug(
        self,
        pdf: canvas.Canvas,
        config: TemplateConfig,
        document: LayoutDocument,
        calibration: PrinterCalibration | None,
    ) -> None:
        width_mm, height_mm = config.require_confirmed_size()
        page_width, page_height = pdf._pagesize
        pdf.saveState()
        pdf.setFont("Helvetica", 5.5)
        pdf.setStrokeColor(Color(0.1, 0.3, 0.9, alpha=0.35))
        pdf.setFillColor(Color(0.1, 0.3, 0.9, alpha=0.85))
        position = 0.0
        while position <= width_mm + 1e-6:
            x = mm_to_points(position)
            pdf.line(x, 0, x, page_height)
            if position > 0:
                pdf.drawString(x + 1, page_height - 7, f"{position:g}")
            position += 10.0
        position = 0.0
        while position <= height_mm + 1e-6:
            y = page_height - mm_to_points(position)
            pdf.line(0, y, page_width, y)
            if position > 0:
                pdf.drawString(1, y + 1, f"{position:g}")
            position += 10.0

        region_groups = [
            (config.content_regions, (0.0, 0.6, 0.0), "content"),
            (config.forbidden_regions, (0.9, 0.0, 0.0), "forbidden"),
            (config.header_regions, (0.1, 0.3, 0.9), "header"),
            (config.fixed_text_regions, (0.6, 0.2, 0.7), "fixed"),
            (config.image_regions, (1.0, 0.5, 0.0), "image"),
            (config.table_regions, (0.0, 0.6, 0.7), "table"),
            (config.signature_regions, (0.6, 0.3, 0.1), "signature"),
        ]
        for regions, color, label in region_groups:
            pdf.setStrokeColorRGB(*color)
            pdf.setFillColorRGB(*color)
            pdf.setFont(self.font_name, 5.5)
            for region in regions:
                x, y, width, height = _top_left_rect_to_pdf(region, height_mm)
                pdf.rect(x, y, width, height, stroke=1, fill=0)
                pdf.drawString(x + 2, y + height - 7, region.label or label)

        pdf.setStrokeColorRGB(0.9, 0.0, 0.7)
        for line in config.writing_lines:
            y = page_height - mm_to_points(line.y_mm)
            pdf.line(mm_to_points(line.x_start_mm), y, mm_to_points(line.x_end_mm), y)

        pdf.setStrokeColorRGB(0.0, 0.0, 0.0)
        for item in document.text_items:
            region = text_item_region(item)
            x, y, width, height = _top_left_rect_to_pdf(region, height_mm)
            pdf.rect(x, y, width, height, stroke=1, fill=0)
            baseline = page_height - mm_to_points(item.baseline_y_mm)
            pdf.setStrokeColorRGB(0.0, 0.5, 0.0)
            pdf.line(x, baseline, x + width, baseline)
            pdf.setStrokeColorRGB(0.0, 0.0, 0.0)

        pdf.setStrokeColorRGB(1.0, 0.45, 0.0)
        pdf.setFont("Helvetica", 5.5)
        for item in document.image_items:
            x = mm_to_points(item.x_mm)
            y = page_height - mm_to_points(item.y_mm + item.height_mm)
            width = mm_to_points(item.width_mm)
            height = mm_to_points(item.height_mm)
            pdf.rect(x, y, width, height, stroke=1, fill=0)
            pdf.drawString(x + 2, y + height - 7, item.id)

        pdf.setFillColorRGB(0.0, 0.0, 0.0)
        pdf.setFont("Helvetica", 6)
        calibration_text = "none"
        if calibration:
            calibration_text = (
                f"dx={calibration.x_offset_mm:g} dy={calibration.y_offset_mm:g} "
                f"sx={calibration.scale_x:g} sy={calibration.scale_y:g} "
                f"rot={calibration.rotation_degree:g}"
            )
        pdf.drawRightString(
            page_width - 3,
            3,
            f"template={config.template_id} calibration={calibration_text}",
        )
        pdf.rect(0.5, 0.5, page_width - 1, page_height - 1, stroke=1, fill=0)
        pdf.restoreState()
