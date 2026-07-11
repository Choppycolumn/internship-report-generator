from pathlib import Path


def test_daily_review_launcher_is_ascii_with_windows_line_endings() -> None:
    launcher = Path(__file__).resolve().parents[1] / "start_daily_review.cmd"
    data = launcher.read_bytes()

    data.decode("ascii")
    assert b"\r\n" in data
    assert data.count(b"\n") == data.count(b"\r\n")
    assert b".venv\\Scripts\\python.exe" in data
    assert b"launch_daily_review.py" in data
