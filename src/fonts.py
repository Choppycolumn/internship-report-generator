from __future__ import annotations

import json
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont

from .coordinate_mapper import points_to_mm
from .paths import ProjectPaths


def register_chinese_font(paths: ProjectPaths) -> str:
    font_config_path = paths.root / "config" / "fonts.json"
    font_config = json.loads(font_config_path.read_text(encoding="utf-8"))
    registered_name = "IRGChinese"
    if registered_name in pdfmetrics.getRegisteredFontNames():
        return registered_name
    for candidate in font_config.get("candidate_paths", []):
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            kwargs = {"subfontIndex": 0} if path.suffix.lower() in {".ttc", ".otc"} else {}
            pdfmetrics.registerFont(TTFont(registered_name, str(path), **kwargs))
            return registered_name
        except Exception:
            continue
    fallback = font_config.get("fallback_pdf_font", "STSong-Light")
    if fallback not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(fallback))
    return fallback


def text_width_mm(text: str, font_name: str, font_size_pt: float) -> float:
    return points_to_mm(pdfmetrics.stringWidth(text, font_name, font_size_pt))

