from __future__ import annotations

import math
import re
from pathlib import Path

from reportlab.pdfgen import canvas

from .coordinate_mapper import mm_to_points
from .models import PrinterCalibration, TemplateConfig
from .paths import ProjectPaths
from .storage import save_json_atomic, utc_now_iso


def safe_printer_key(printer_name: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9_-]+", "_", printer_name).strip("_").lower()
    return key or "printer"


def calibration_path(paths: ProjectPaths, printer_name: str, template_id: str) -> Path:
    return paths.printers / f"{safe_printer_key(printer_name)}__{template_id}.json"


def save_calibration(
    paths: ProjectPaths,
    printer_name: str,
    template_id: str,
    x_offset_mm: float = 0.0,
    y_offset_mm: float = 0.0,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    rotation_degree: float = 0.0,
) -> PrinterCalibration:
    calibration = PrinterCalibration(
        printer_name=printer_name,
        template_id=template_id,
        x_offset_mm=x_offset_mm,
        y_offset_mm=y_offset_mm,
        scale_x=scale_x,
        scale_y=scale_y,
        rotation_degree=rotation_degree,
        updated_at=utc_now_iso(),
    )
    save_json_atomic(calibration_path(paths, printer_name, template_id), calibration)
    return calibration


def apply_calibration_to_point_mm(
    x_mm: float,
    y_mm: float,
    page_width_mm: float,
    page_height_mm: float,
    calibration: PrinterCalibration,
) -> tuple[float, float]:
    center_x, center_y = page_width_mm / 2.0, page_height_mm / 2.0
    x = (x_mm - center_x) * calibration.scale_x
    y = (y_mm - center_y) * calibration.scale_y
    angle = math.radians(calibration.rotation_degree)
    rotated_x = x * math.cos(angle) - y * math.sin(angle)
    rotated_y = x * math.sin(angle) + y * math.cos(angle)
    return (
        rotated_x + center_x + calibration.x_offset_mm,
        rotated_y + center_y + calibration.y_offset_mm,
    )


def _cross(pdf: canvas.Canvas, x_mm: float, y_mm: float, size_mm: float = 4.0) -> None:
    x = mm_to_points(x_mm)
    y = pdf._pagesize[1] - mm_to_points(y_mm)
    size = mm_to_points(size_mm)
    pdf.line(x - size, y, x + size, y)
    pdf.line(x, y - size, x, y + size)


def generate_calibration_page(
    paths: ProjectPaths,
    config: TemplateConfig,
    output: Path | None = None,
) -> Path:
    width_mm, height_mm = config.require_confirmed_size()
    output = output or paths.output_calibration / f"{config.template_id}_calibration.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    page_size = (mm_to_points(width_mm), mm_to_points(height_mm))
    pdf = canvas.Canvas(str(output), pagesize=page_size, pageCompression=1)
    pdf.setTitle(f"Printer calibration - {config.template_id}")
    pdf.setLineWidth(0.4)
    pdf.setStrokeColorRGB(0.65, 0.65, 0.65)
    position = 0.0
    while position <= width_mm + 1e-6:
        x = mm_to_points(position)
        pdf.line(x, 0, x, page_size[1])
        position += 10.0
    position = 0.0
    while position <= height_mm + 1e-6:
        y = page_size[1] - mm_to_points(position)
        pdf.line(0, y, page_size[0], y)
        position += 10.0

    pdf.setStrokeColorRGB(0, 0, 0)
    pdf.setLineWidth(0.8)
    inset = min(8.0, width_mm / 8.0, height_mm / 8.0)
    for x, y in [
        (inset, inset),
        (width_mm - inset, inset),
        (inset, height_mm - inset),
        (width_mm - inset, height_mm - inset),
        (width_mm / 2.0, height_mm / 2.0),
    ]:
        _cross(pdf, x, y)
    for line in config.writing_lines:
        y = page_size[1] - mm_to_points(line.y_mm)
        pdf.setStrokeColorRGB(0.75, 0.1, 0.1)
        pdf.line(mm_to_points(line.x_start_mm), y, mm_to_points(line.x_end_mm), y)
    pdf.setStrokeColorRGB(0, 0, 0)
    pdf.setFont("Helvetica", 7)
    pdf.drawString(mm_to_points(5), page_size[1] - mm_to_points(5), config.template_id)
    if not config.has_exact_size:
        pdf.setFillColorRGB(0.8, 0.0, 0.0)
        pdf.drawRightString(
            page_size[0] - mm_to_points(5),
            page_size[1] - mm_to_points(5),
            "PROVISIONAL SIZE - VERIFY ON PLAIN PAPER",
        )
        pdf.setFillColorRGB(0, 0, 0)
    pdf.drawString(mm_to_points(5), mm_to_points(5), "Print at Actual size / 100%; disable Fit and auto-center")
    pdf.rect(0.5, 0.5, page_size[0] - 1, page_size[1] - 1)
    pdf.showPage()
    pdf.save()
    return output
