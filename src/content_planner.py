from __future__ import annotations

import re
from typing import Iterable

from .daily_material_reader import load_day_metadata, load_daily_review
from .models import DailyFactBundle
from .paths import ProjectPaths


FIELD_LABELS = {
    "location": "实习地点",
    "department": "实习部门",
    "instructor": "现场指导人员",
}


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = re.sub(r"\s+", " ", str(value)).strip(" \t\r\n，,；;")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def split_note_facts(notes: str) -> list[str]:
    parts = re.split(r"(?:\r?\n)+|(?<=[。！？!?；;])", notes)
    return _unique(part.strip() for part in parts)


def analyze_daily_material(paths: ProjectPaths, date: str) -> DailyFactBundle:
    review = load_daily_review(paths, date)
    metadata = load_day_metadata(paths, date)
    confirmed: list[str] = []
    inferred: list[str] = []
    pending: list[str] = []

    if review.topic.strip():
        confirmed.append(f"当日实习主题：{review.topic.strip()}")
    else:
        pending.append("请确认当天的实习主题。")

    note_facts = split_note_facts(review.notes)
    confirmed.extend(note_facts)
    if not note_facts:
        pending.append("请补充当天实际观察、学习或参与的内容。")

    for field, label in FIELD_LABELS.items():
        value = str(metadata.get(field, "")).strip()
        if value:
            confirmed.append(f"{label}：{value}")

    for operation in metadata.get("confirmed_operations", []) or []:
        confirmed.append(f"已确认参与内容：{operation}")

    if review.images:
        confirmed.append(f"当日共提供 {len(review.images)} 张照片。")
    for image in review.images:
        if image.approved:
            if image.caption.strip():
                confirmed.append(f"已审核图片说明：{image.caption.strip()}")
            if image.generated_text.strip():
                confirmed.append(image.generated_text.strip())
        else:
            pending.append(f"图片 {image.id} 的图题和对应文字尚未人工确认。")

    if metadata.get("allow_inference", True) and review.topic.strip() and not note_facts:
        inferred.append(
            f"当天内容可能围绕“{review.topic.strip()}”展开，具体参观、观察和参与内容仍需确认。"
        )

    pending.extend(metadata.get("pending_confirmation", []) or [])
    prohibited = metadata.get("prohibited_claims", []) or []
    return DailyFactBundle(
        confirmed_facts=_unique(confirmed),
        inferred_facts=_unique(inferred),
        pending_confirmation=_unique(pending),
        prohibited_claims=_unique(prohibited),
    )
