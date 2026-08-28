from __future__ import annotations

from collections.abc import Iterable

from .models import DailyDraftSection


DEFAULT_DAILY_TARGET = 650
RECOMMENDED_DAILY_MIN = 500
RECOMMENDED_DAILY_MAX = 800

# These phrases describe evidence limits or the generation process. They may be
# useful during internal review, but they do not belong in a student's report.
BANNED_META_TALK_TERMS = (
    "现有记录",
    "现有材料",
    "没有写明",
    "未标注",
    "无法确认",
    "可核对",
    "不补写",
    "不解释为",
    "不能解释为",
    "不表示",
    "并不表示",
    "本日记录",
    "图片显示",
    "画面中",
    "根据照片判断",
    "根据现有信息判断",
    "信息不足",
    "避免编造",
    "资料为准",
    "真实材料",
    "照片没有标注",
    "没有可核对的内容说明",
    "由于缺乏相关记录",
    "从图片中只能看出",
    "不能据此判断",
    "照片记录了",
)

FIRST_PERSON_MARKERS = ("我", "我们")


def paragraph_text(sections: Iterable[DailyDraftSection]) -> str:
    return "\n".join(
        section.text.strip()
        for section in sections
        if section.type == "paragraph" and section.text.strip()
    )


def find_meta_talk_terms(text: str) -> list[str]:
    return [term for term in BANNED_META_TALK_TERMS if term in text]


def uses_first_person(text: str) -> bool:
    return any(marker in text for marker in FIRST_PERSON_MARKERS)


def codex_daily_writing_rules() -> dict:
    """Return compact generation rules for the local Codex handoff package."""
    return {
        "voice": "普通本科生第一人称、日记式实习记录，正式但不过度书面化。",
        "recommended_characters": {
            "minimum": RECOMMENDED_DAILY_MIN,
            "maximum": RECOMMENDED_DAILY_MAX,
            "default_target": DEFAULT_DAILY_TARGET,
        },
        "suggested_structure": [
            "当天主要任务",
            "具体学习或观察内容",
            "当天认识和收获",
            "简短的下一步计划",
        ],
        "content_rules": [
            "围绕当天实际发生的事情写，不把未来计划写成当天已完成的工作。",
            "无法确认的部门、人员、地点、产品、型号或细节直接省略或宽泛表达。",
            "事实筛选和风险判断只在内部进行，不向正文读者解释。",
            "每段表达一个中心，避免连续堆砌业务名词和流程环节。",
            "照片只辅助理解活动；普通办公环境用一句自然概括，不逐项描述物品。",
            "图注保持简短自然。",
        ],
        "photo_caption_examples": [
            "图1 公司办公环境",
            "图2 产品资料学习记录",
            "图3 实习现场记录",
        ],
        "banned_meta_talk_terms": list(BANNED_META_TALK_TERMS),
        "final_internal_checks": [
            "删除信息来源说明、免责声明、证据充分性说明和模型自我解释。",
            "删除只为解释为什么没有写某个内容的句子。",
            "检查是否有无依据的具体事实、跨日内容、重复段落和未来任务误写。",
            "检查成稿是否像本科生亲自写的实习日记。",
        ],
    }
