from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .content_planner import analyze_daily_material, split_note_facts
from .daily_material_reader import (
    load_day_metadata,
    load_daily_review,
    save_daily_review,
    validate_date,
)
from .duplication_checker import calculate_draft_metrics
from .models import (
    CodexDailyDraftInput,
    DailyDraft,
    DailyDraftMetrics,
    DailyDraftSection,
    DailyFactBundle,
)
from .paths import ProjectPaths
from .storage import save_json_atomic, utc_now_iso
from .writing_rules import (
    DEFAULT_DAILY_TARGET,
    RECOMMENDED_DAILY_MAX,
    codex_daily_writing_rules,
    find_meta_talk_terms,
    paragraph_text,
    uses_first_person,
)


REFLECTION_MARKERS = ("收获", "体会", "认识", "理解", "意识", "思考", "问题")


def draft_path(paths: ProjectPaths, date: str) -> Path:
    return paths.root / "reports" / "drafts" / f"{validate_date(date)}.json"


def approved_path(paths: ProjectPaths, date: str) -> Path:
    return paths.root / "reports" / "approved" / f"{validate_date(date)}.json"


def structured_path(paths: ProjectPaths, date: str) -> Path:
    return paths.root / "reports" / "structured" / f"{validate_date(date)}_daily.json"


def _placeholder(section_id: str, text: str) -> DailyDraftSection:
    return DailyDraftSection(
        id=section_id,
        type="paragraph",
        text=f"【待确认】{text}",
        requires_confirmation=True,
    )


def _content_hash(draft: DailyDraft) -> str:
    payload = {
        "date": draft.date,
        "title": draft.title,
        "facts": draft.facts.model_dump(mode="json"),
        "sections": [section.model_dump(mode="json") for section in draft.sections],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _refresh(paths: ProjectPaths, draft: DailyDraft) -> DailyDraft:
    draft.updated_at = utc_now_iso()
    draft.content_hash = _content_hash(draft)
    draft.metrics = calculate_draft_metrics(paths, draft)
    warnings: list[str] = []
    if draft.facts.pending_confirmation:
        warnings.append(f"仍有 {len(draft.facts.pending_confirmation)} 项待确认内容。")
    if draft.facts.inferred_facts:
        warnings.append("合理推断仅供审核参考，未自动写入正式正文。")
    if any(section.requires_confirmation for section in draft.sections):
        warnings.append("草稿中仍有需要人工确认的段落。")
    if draft.metrics.max_similarity >= 0.72:
        warnings.append(f"历史内容最高相似度为 {draft.metrics.max_similarity:.0%}。")
    if draft.metrics.remaining_characters:
        warnings.append(f"距离当日建议字数还差 {draft.metrics.remaining_characters} 字。")
    body_text = paragraph_text(draft.sections)
    meta_terms = find_meta_talk_terms(body_text)
    if meta_terms:
        warnings.append(f"正文含有元话语或核验式表达：{'、'.join(meta_terms)}。")
    if body_text and not uses_first_person(body_text):
        warnings.append("正文缺少第一人称本科生视角。")
    if draft.word_count_target <= RECOMMENDED_DAILY_MAX and draft.metrics.body_characters > RECOMMENDED_DAILY_MAX:
        warnings.append(f"正文超过日记建议上限 {RECOMMENDED_DAILY_MAX} 字，请检查是否过度展开。")
    draft.content_warnings = warnings
    total = (
        len(draft.facts.confirmed_facts)
        + len(draft.facts.inferred_facts)
        + len(draft.facts.pending_confirmation)
    )
    draft.confidence = round(len(draft.facts.confirmed_facts) / total, 3) if total else 0.0
    return draft


def save_daily_draft(paths: ProjectPaths, draft: DailyDraft) -> DailyDraft:
    if approved_path(paths, draft.date).exists():
        raise ValueError("This date already has an approved locked draft")
    if draft.status == "approved":
        raise ValueError("Approved drafts are locked and cannot be edited")
    draft.date = validate_date(draft.date)
    refreshed = _refresh(paths, draft)
    save_json_atomic(draft_path(paths, refreshed.date), refreshed)
    save_json_atomic(structured_path(paths, refreshed.date), refreshed)
    return refreshed


def load_daily_draft(paths: ProjectPaths, date: str) -> DailyDraft:
    path = draft_path(paths, date)
    if not path.exists():
        approved = approved_path(paths, date)
        if approved.exists():
            return DailyDraft.model_validate_json(approved.read_text(encoding="utf-8"))
        raise FileNotFoundError(f"Daily draft not found: {validate_date(date)}")
    return DailyDraft.model_validate_json(path.read_text(encoding="utf-8"))


def generate_daily_draft(
    paths: ProjectPaths, date: str, word_count_target: int | None = None
) -> DailyDraft:
    normalized = validate_date(date)
    if approved_path(paths, normalized).exists():
        raise ValueError("This date already has an approved locked draft")
    review = load_daily_review(paths, normalized)
    metadata = load_day_metadata(paths, normalized)
    facts = analyze_daily_material(paths, normalized)
    note_facts = split_note_facts(review.notes)
    now = utc_now_iso()
    existing_path = draft_path(paths, normalized)
    existing = (
        DailyDraft.model_validate_json(existing_path.read_text(encoding="utf-8"))
        if existing_path.exists()
        else None
    )
    target = int(word_count_target or metadata.get("word_count_target") or DEFAULT_DAILY_TARGET)
    if target < 100:
        raise ValueError("word_count_target must be at least 100")

    sections: list[DailyDraftSection] = [
        DailyDraftSection(id="heading_content", type="heading", level=1, text="一、当日实习内容")
    ]
    intro: list[str] = []
    basis: list[str] = []
    if review.topic.strip():
        intro.append(f"今天我的实习主题是“{review.topic.strip()}”。")
        basis.append(f"topic:{review.topic.strip()}")
    if note_facts:
        joined = "；".join(item.rstrip("。！？!?；;") for item in note_facts)
        intro.append(f"按照当天安排，我{joined}。")
        basis.extend(f"note:{item}" for item in note_facts)
    if intro:
        sections.append(
            DailyDraftSection(
                id="paragraph_content",
                type="paragraph",
                text="".join(intro),
                basis=basis,
            )
        )
    else:
        sections.append(_placeholder("paragraph_content", "请补充当天实际实习内容。"))

    sections.append(DailyDraftSection(id="heading_analysis", type="heading", level=1, text="二、技术内容与观察"))
    approved_image_texts: list[str] = []
    for image in review.images:
        sections.append(
            DailyDraftSection(
                id=f"section_{image.id}",
                type="image",
                path=image.processed_path,
                caption=image.caption,
                basis=[f"image:{image.id}"],
                requires_confirmation=not image.approved,
            )
        )
        if image.approved and image.generated_text.strip():
            approved_image_texts.append(image.generated_text.strip())
    if approved_image_texts:
        sections.append(
            DailyDraftSection(
                id="paragraph_analysis",
                type="paragraph",
                text="\n".join(approved_image_texts),
                basis=["approved_image_text"],
            )
        )
    else:
        sections.append(
            _placeholder(
                "paragraph_analysis",
                "请在确认设备、工艺或检测对象后补充技术原理与现场观察。",
            )
        )

    sections.append(DailyDraftSection(id="heading_reflection", type="heading", level=1, text="三、当日收获与思考"))
    reflections = [item for item in note_facts if any(marker in item for marker in REFLECTION_MARKERS)]
    if reflections:
        sections.append(
            DailyDraftSection(
                id="paragraph_reflection",
                type="paragraph",
                text="".join(reflections),
                basis=[f"note:{item}" for item in reflections],
            )
        )
    else:
        sections.append(
            _placeholder(
                "paragraph_reflection",
                "请补充当天最有价值的收获、与课程知识的联系或后续问题。",
            )
        )

    draft = DailyDraft(
        version=(existing.version + 1 if existing else 1),
        date=normalized,
        title=review.topic.strip() or f"{normalized} 实习记录",
        source_review_updated_at=review.updated_at,
        facts=facts,
        word_count_target=target,
        sections=sections,
        metrics=DailyDraftMetrics(
            body_characters=0,
            target_characters=target,
            remaining_characters=target,
        ),
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    return save_daily_draft(paths, draft)


def build_codex_context(paths: ProjectPaths, date: str) -> dict:
    """Build a compact local-only handoff package for this Codex conversation."""
    normalized = validate_date(date)
    review = load_daily_review(paths, normalized)
    metadata = load_day_metadata(paths, normalized)
    facts = analyze_daily_material(paths, normalized)
    history: list[dict] = []
    approved_root = paths.root / "reports" / "approved"
    if approved_root.exists():
        for path in sorted(approved_root.glob("*.json"), reverse=True):
            try:
                previous = DailyDraft.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if previous.date == normalized:
                continue
            paragraphs = [
                section.text[:240]
                for section in previous.sections
                if section.type == "paragraph" and section.text.strip()
            ]
            history.append(
                {
                    "date": previous.date,
                    "title": previous.title,
                    "body_characters": previous.metrics.body_characters,
                    "paragraph_excerpts": paragraphs[:4],
                }
            )
            if len(history) >= 7:
                break
    return {
        "schema_version": 1,
        "generation_mode": "codex_conversation_local_files",
        "external_model_api_required": False,
        "date": normalized,
        "topic": review.topic,
        "notes": review.notes,
        "metadata": metadata,
        "facts": facts.model_dump(mode="json"),
        "images": [
            {
                "id": image.id,
                "processed_path": image.processed_path,
                "caption": image.caption,
                "generated_text": image.generated_text,
                "approved": image.approved,
                "quality_warnings": image.quality.warnings,
            }
            for image in review.images
        ],
        "recent_approved_history": history,
        "writing_rules": codex_daily_writing_rules(),
        "writeback_format": "CodexDailyDraftInput",
    }


def import_codex_daily_draft(
    paths: ProjectPaths, payload: CodexDailyDraftInput | dict
) -> DailyDraft:
    authored = (
        payload
        if isinstance(payload, CodexDailyDraftInput)
        else CodexDailyDraftInput.model_validate(payload)
    )
    normalized = validate_date(authored.date)
    if approved_path(paths, normalized).exists():
        raise ValueError("This date already has an approved locked draft")
    review = load_daily_review(paths, normalized)
    allowed_images = {image.processed_path for image in review.images}
    for section in authored.sections:
        if section.type == "image" and section.path not in allowed_images:
            raise ValueError(f"Draft references an image outside the reviewed day: {section.path}")

    existing_path = draft_path(paths, normalized)
    existing = (
        DailyDraft.model_validate_json(existing_path.read_text(encoding="utf-8"))
        if existing_path.exists()
        else None
    )
    now = utc_now_iso()
    draft = DailyDraft(
        version=(existing.version + 1 if existing else 1),
        date=normalized,
        title=authored.title,
        source_review_updated_at=review.updated_at,
        facts=DailyFactBundle(
            confirmed_facts=authored.confirmed_facts,
            inferred_facts=authored.inferred_facts,
            pending_confirmation=authored.pending_confirmation,
            prohibited_claims=authored.prohibited_claims,
        ),
        word_count_target=authored.word_count_target,
        sections=authored.sections,
        metrics=DailyDraftMetrics(
            body_characters=0,
            target_characters=authored.word_count_target,
            remaining_characters=authored.word_count_target,
        ),
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    return save_daily_draft(paths, draft)


def approve_daily_draft(paths: ProjectPaths, date: str) -> DailyDraft:
    draft = load_daily_draft(paths, date)
    if draft.status == "approved":
        return draft
    draft = _refresh(paths, draft)
    blockers: list[str] = []
    if draft.facts.pending_confirmation:
        blockers.append("pending_confirmation must be empty")
    unresolved = [section.id for section in draft.sections if section.requires_confirmation]
    if unresolved:
        blockers.append(f"sections still require confirmation: {', '.join(unresolved)}")
    body_text = paragraph_text(draft.sections)
    meta_terms = find_meta_talk_terms(body_text)
    if meta_terms:
        blockers.append(f"report prose contains meta-language: {', '.join(meta_terms)}")
    if body_text and not uses_first_person(body_text):
        blockers.append("report prose must use a first-person undergraduate voice")
    for claim in draft.facts.prohibited_claims:
        if claim and claim in body_text:
            blockers.append(f"prohibited claim appears in content: {claim}")
    if "【待确认】" in body_text:
        blockers.append("draft still contains pending placeholders")
    if draft.metrics.max_similarity >= 0.90:
        blockers.append(f"duplicate similarity is too high: {draft.metrics.max_similarity:.0%}")

    review = load_daily_review(paths, draft.date)
    image_by_path = {image.processed_path: image for image in review.images}
    for section in (item for item in draft.sections if item.type == "image"):
        image = image_by_path.get(section.path or "")
        if image is None or not image.approved or not image.caption.strip() or not image.generated_text.strip():
            blockers.append(f"image is not fully approved: {section.id}")
    if blockers:
        raise ValueError("Formal approval blocked: " + "; ".join(blockers))

    destination = approved_path(paths, draft.date)
    if destination.exists():
        locked = DailyDraft.model_validate_json(destination.read_text(encoding="utf-8"))
        if locked.content_hash == draft.content_hash:
            return locked
        raise ValueError("An approved locked version already exists for this date")
    draft.status = "approved"
    draft.approved_at = utc_now_iso()
    draft.updated_at = draft.approved_at
    draft.content_hash = _content_hash(draft)
    save_json_atomic(destination, draft)
    save_json_atomic(draft_path(paths, draft.date), draft)
    save_json_atomic(structured_path(paths, draft.date), draft)
    review.status = "approved"
    save_daily_review(paths, review)
    return draft


def fully_approve_daily_draft(paths: ProjectPaths, date: str) -> DailyDraft:
    """Confirm all review flags for a day, then run the normal approval gates."""
    normalized = validate_date(date)
    draft = load_daily_draft(paths, normalized)
    if draft.status == "approved":
        return draft

    review = load_daily_review(paths, normalized)
    incomplete_images = [
        image.id
        for image in review.images
        if not image.caption.strip() or not image.generated_text.strip()
    ]
    if incomplete_images:
        raise ValueError(
            "Cannot fully approve images without captions and corresponding text: "
            + ", ".join(incomplete_images)
        )

    draft.facts.pending_confirmation = []
    for section in draft.sections:
        section.requires_confirmation = False
    for image in review.images:
        image.approved = True
    review.status = "reviewed"

    save_daily_review(paths, review)
    save_daily_draft(paths, draft)
    return approve_daily_draft(paths, normalized)
