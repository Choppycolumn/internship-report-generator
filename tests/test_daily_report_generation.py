from __future__ import annotations

import pytest

from src.content_planner import analyze_daily_material
from src.daily_material_reader import load_day_metadata, save_daily_review
from src.daily_report_generator import (
    approve_daily_draft,
    build_codex_context,
    generate_daily_draft,
    import_codex_daily_draft,
    save_daily_draft,
)
from src.models import DailyReview
from src.storage import save_json_atomic, utc_now_iso
from src.writing_rules import BANNED_META_TALK_TERMS


def _save_review(project_paths, date: str, topic: str, notes: str) -> None:
    save_daily_review(
        project_paths,
        DailyReview(
            date=date,
            topic=topic,
            notes=notes,
            updated_at=utc_now_iso(),
        ),
    )


def _resolve_placeholders(draft):
    draft.facts.pending_confirmation = []
    for section in draft.sections:
        if section.requires_confirmation:
            section.requires_confirmation = False
            if section.id == "paragraph_analysis":
                section.text = "结合当天记录，对现场流程的基本目的和观察重点进行了整理。"
            elif section.id == "paragraph_reflection":
                section.text = "当天的主要收获是进一步明确了现场观察与课堂知识之间的联系。"
    return draft


def test_daily_review_save_preserves_extended_metadata(project_paths) -> None:
    date = "2026-07-01"
    day_dir = project_paths.root / "days" / date
    save_json_atomic(
        day_dir / "metadata.json",
        {
            "date": date,
            "location": "测试车间",
            "confirmed_operations": ["观察装配流程"],
            "prohibited_claims": ["独立完成调试"],
            "word_count_target": 600,
        },
    )
    _save_review(project_paths, date, "装配流程学习", "观察了装配区域。")

    metadata = load_day_metadata(project_paths, date)

    assert metadata["location"] == "测试车间"
    assert metadata["confirmed_operations"] == ["观察装配流程"]
    assert metadata["prohibited_claims"] == ["独立完成调试"]
    assert metadata["word_count_target"] == 600


def test_inference_is_classified_but_not_written_into_body(project_paths) -> None:
    date = "2026-07-02"
    _save_review(project_paths, date, "检测流程学习", "")

    facts = analyze_daily_material(project_paths, date)
    draft = generate_daily_draft(project_paths, date)
    body = "\n".join(section.text for section in draft.sections)

    assert facts.inferred_facts
    assert "可能围绕" not in body
    assert any(section.requires_confirmation for section in draft.sections)


def test_approval_blocks_pending_then_locks_resolved_draft(project_paths) -> None:
    date = "2026-07-03"
    _save_review(
        project_paths,
        date,
        "质量控制学习",
        "观察了质量检查流程。认识到规范记录对质量追溯很重要。",
    )
    draft = generate_daily_draft(project_paths, date, 500)

    with pytest.raises(ValueError, match="Formal approval blocked"):
        approve_daily_draft(project_paths, date)

    saved = save_daily_draft(project_paths, _resolve_placeholders(draft))
    approved = approve_daily_draft(project_paths, date)

    assert saved.status == "draft"
    assert approved.status == "approved"
    assert approved.approved_at
    assert (project_paths.root / "reports" / "approved" / f"{date}.json").exists()


def test_duplicate_checker_compares_previous_approved_days(project_paths) -> None:
    first_date = "2026-07-04"
    second_date = "2026-07-05"
    topic = "生产流程观察"
    notes = "观察了生产流程中的物料传递和工序衔接。"
    _save_review(project_paths, first_date, topic, notes)
    first = generate_daily_draft(project_paths, first_date)
    save_daily_draft(project_paths, _resolve_placeholders(first))
    approve_daily_draft(project_paths, first_date)

    _save_review(project_paths, second_date, topic, notes)
    second = generate_daily_draft(project_paths, second_date)

    assert second.metrics.max_similarity == 1.0
    assert second.metrics.duplicate_findings
    assert second.metrics.duplicate_findings[0].other_date == first_date


def test_codex_context_is_local_and_contains_recent_material(project_paths) -> None:
    date = "2026-07-07"
    _save_review(project_paths, date, "现场参观", "观察了现场设备布局。")

    context = build_codex_context(project_paths, date)

    assert context["generation_mode"] == "codex_conversation_local_files"
    assert context["external_model_api_required"] is False
    assert context["notes"] == "观察了现场设备布局。"
    assert context["facts"]["confirmed_facts"]
    assert context["writing_rules"]["voice"].startswith("普通本科生第一人称")
    assert "现有记录" in context["writing_rules"]["banned_meta_talk_terms"]


def test_codex_authored_payload_is_wrapped_and_measured(project_paths) -> None:
    date = "2026-07-08"
    _save_review(project_paths, date, "安全规范学习", "学习了现场安全要求。")
    payload = {
        "date": date,
        "title": "现场安全规范学习",
        "confirmed_facts": ["学习了现场安全要求。"],
        "inferred_facts": [],
        "pending_confirmation": [],
        "prohibited_claims": ["发生安全事故"],
        "word_count_target": 500,
        "sections": [
            {"id": "heading", "type": "heading", "level": 1, "text": "一、当日实习内容"},
            {
                "id": "body",
                "type": "paragraph",
                "text": "当天根据现场要求学习了安全规范，并对记录中明确提到的内容进行了整理。",
                "basis": ["note:学习了现场安全要求。"],
                "requires_confirmation": False,
            },
        ],
    }

    draft = import_codex_daily_draft(project_paths, payload)

    assert draft.title == payload["title"]
    assert draft.metrics.body_characters > 0
    assert draft.metrics.remaining_characters < 500
    assert draft.content_hash


def test_generated_scaffold_uses_first_person_without_meta_talk(project_paths) -> None:
    date = "2026-07-09"
    _save_review(project_paths, date, "产品资料学习", "学习医疗器械产品的基本用途。")

    draft = generate_daily_draft(project_paths, date)
    body = "\n".join(section.text for section in draft.sections if section.type == "paragraph")

    assert "我" in body
    assert not any(term in body for term in BANNED_META_TALK_TERMS)
    assert draft.word_count_target == 650


def test_meta_talk_is_warned_and_blocks_formal_approval(project_paths) -> None:
    date = "2026-07-10"
    _save_review(project_paths, date, "入职报到", "完成入职报到。")
    payload = {
        "date": date,
        "title": "入职报到",
        "confirmed_facts": ["完成入职报到。"],
        "pending_confirmation": [],
        "sections": [
            {
                "id": "body",
                "type": "paragraph",
                "text": "今天我完成了入职报到。现有记录没有写明具体部门，因此本日内容不补写这些细节。",
            }
        ],
    }

    draft = import_codex_daily_draft(project_paths, payload)

    assert any("元话语" in warning for warning in draft.content_warnings)
    with pytest.raises(ValueError, match="meta-language"):
        approve_daily_draft(project_paths, date)
