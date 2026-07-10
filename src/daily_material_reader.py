from __future__ import annotations

from datetime import date as date_type
from pathlib import Path

from .models import DailyReview
from .paths import ProjectPaths
from .storage import save_json_atomic, utc_now_iso


def validate_date(value: str) -> str:
    parsed = date_type.fromisoformat(value)
    return parsed.isoformat()


def day_directory(paths: ProjectPaths, date: str) -> Path:
    return paths.root / "days" / validate_date(date)


def load_daily_review(paths: ProjectPaths, date: str) -> DailyReview:
    normalized = validate_date(date)
    path = day_directory(paths, normalized) / "review.json"
    if path.exists():
        return DailyReview.model_validate_json(path.read_text(encoding="utf-8"))
    return DailyReview(date=normalized, updated_at=utc_now_iso())


def save_daily_review(paths: ProjectPaths, review: DailyReview) -> None:
    day_dir = day_directory(paths, review.date)
    day_dir.mkdir(parents=True, exist_ok=True)
    review.updated_at = utc_now_iso()
    save_json_atomic(day_dir / "review.json", review)
    (day_dir / "notes.txt").write_text(review.notes.strip() + "\n", encoding="utf-8")
    metadata = {
        "date": review.date,
        "topic": review.topic,
        "template_id": "lined_content_page_candidate",
        "allow_inference": True,
        "include_images": bool(review.images),
        "target_pages": None,
        "keywords": [],
        "confirmed_operations": [],
        "prohibited_claims": [],
        "review_status": review.status,
        "image_count": len(review.images),
    }
    save_json_atomic(day_dir / "metadata.json", metadata)


def list_review_dates(paths: ProjectPaths) -> list[str]:
    days_root = paths.root / "days"
    if not days_root.exists():
        return []
    dates = []
    for child in days_root.iterdir():
        if child.is_dir():
            try:
                dates.append(validate_date(child.name))
            except ValueError:
                continue
    return sorted(dates, reverse=True)

