from src.models import PrinterCalibration
from src.printer_calibration import apply_calibration_to_point_mm


def test_printer_offset_without_scale_or_rotation() -> None:
    calibration = PrinterCalibration(
        printer_name="test",
        template_id="page",
        x_offset_mm=1.25,
        y_offset_mm=-0.75,
        updated_at="2026-07-10T00:00:00+00:00",
    )
    x, y = apply_calibration_to_point_mm(20, 30, 120, 180, calibration)
    assert abs(x - 21.25) < 1e-9
    assert abs(y - 29.25) < 1e-9


def test_printer_scaling_is_about_page_center() -> None:
    calibration = PrinterCalibration(
        printer_name="test",
        template_id="page",
        scale_x=1.01,
        scale_y=0.99,
        updated_at="2026-07-10T00:00:00+00:00",
    )
    center = apply_calibration_to_point_mm(60, 90, 120, 180, calibration)
    assert center == (60, 90)

