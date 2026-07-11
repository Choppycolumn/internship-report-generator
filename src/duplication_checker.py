from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import DailyDraft, DailyDraftMetrics, DailyDraftSection, DuplicateFinding
from .paths import ProjectPaths


def count_report_characters(text: str) -> int:
    chinese = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text)
    latin_or_numbers = re.findall(r"[A-Za-z0-9]+", text)
    return len(chinese) + len(latin_or_numbers)


def _normalized(text: str) -> str:
    return re.sub(r"[^\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9]", "", text).lower()


def _ngrams(text: str, size: int = 3) -> set[str]:
    if len(text) < size:
        return {text} if text else set()
    return {text[index : index + size] for index in range(len(text) - size + 1)}


def text_similarity(left: str, right: str) -> float:
    left_normalized = _normalized(left)
    right_normalized = _normalized(right)
    if not left_normalized or not right_normalized:
        return 0.0
    sequence = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    left_ngrams = _ngrams(left_normalized)
    right_ngrams = _ngrams(right_normalized)
    union = left_ngrams | right_ngrams
    jaccard = len(left_ngrams & right_ngrams) / len(union) if union else 0.0
    return round(max(sequence, jaccard), 4)


def _paragraphs(sections: list[DailyDraftSection]) -> list[DailyDraftSection]:
    return [
        section
        for section in sections
        if section.type == "paragraph"
        and not section.requires_confirmation
        and not section.text.lstrip().startswith("【待确认】")
        and len(_normalized(section.text)) >= 20
    ]


def find_duplicate_content(
    paths: ProjectPaths,
    date: str,
    sections: list[DailyDraftSection],
    threshold: float = 0.72,
) -> list[DuplicateFinding]:
    current = _paragraphs(sections)
    comparisons: list[tuple[str, DailyDraftSection]] = []
    approved_root = paths.root / "reports" / "approved"
    if approved_root.exists():
        for path in sorted(approved_root.glob("*.json")):
            try:
                draft = DailyDraft.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if draft.date != date:
                comparisons.extend((draft.date, section) for section in _paragraphs(draft.sections))

    findings: list[DuplicateFinding] = []
    for index, section in enumerate(current):
        candidates = comparisons + [(date, other) for other in current[:index]]
        for other_date, other in candidates:
            score = text_similarity(section.text, other.text)
            if score >= threshold:
                findings.append(
                    DuplicateFinding(
                        current_section_id=section.id,
                        other_date=other_date,
                        other_section_id=other.id,
                        score=score,
                        excerpt=other.text[:80],
                    )
                )
    return sorted(findings, key=lambda item: item.score, reverse=True)[:30]


def calculate_draft_metrics(paths: ProjectPaths, draft: DailyDraft) -> DailyDraftMetrics:
    section_counts = {
        section.id: count_report_characters(section.text)
        for section in draft.sections
        if section.type == "paragraph"
    }
    body_count = sum(section_counts.values())
    findings = find_duplicate_content(paths, draft.date, draft.sections)
    return DailyDraftMetrics(
        body_characters=body_count,
        target_characters=draft.word_count_target,
        remaining_characters=max(0, draft.word_count_target - body_count),
        section_characters=section_counts,
        max_similarity=max((item.score for item in findings), default=0.0),
        duplicate_findings=findings,
    )
