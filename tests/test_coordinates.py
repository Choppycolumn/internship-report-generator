from src.coordinate_mapper import CoordinateMapper, mm_to_points, points_to_mm


def test_mm_pixel_round_trip() -> None:
    mapper = CoordinateMapper(185.0, 260.0, 3700, 5200)
    x_px, y_px = mapper.mm_to_px(37.25, 149.75)
    x_mm, y_mm = mapper.px_to_mm(x_px, y_px)
    assert abs(x_mm - 37.25) < 0.01
    assert abs(y_mm - 149.75) < 0.01


def test_mm_points_round_trip() -> None:
    assert abs(points_to_mm(mm_to_points(123.456)) - 123.456) < 1e-9


def test_top_left_y_is_flipped_for_pdf() -> None:
    mapper = CoordinateMapper(120.0, 180.0, 1200, 1800)
    x_pt, y_pt = mapper.top_left_mm_to_pdf_points(10.0, 30.0)
    assert abs(points_to_mm(x_pt) - 10.0) < 1e-9
    assert abs(points_to_mm(y_pt) - 150.0) < 1e-9

