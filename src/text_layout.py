from __future__ import annotations

import re
from dataclasses import dataclass

from .fonts import text_width_mm


PROHIBITED_LINE_START = set("，。！？；：、）》」』】〕〉％‰,.!?;:%)]}”’…")
PROHIBITED_LINE_END = set("（《「『【〔〈([{“‘")


@dataclass(frozen=True)
class WrappedLine:
    text: str
    indent_mm: float
    width_mm: float


def normalize_paragraph(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_ascii_word_character(character: str) -> bool:
    return character.isascii() and (character.isalnum() or character in {"_", "/"})


def take_line(
    text: str,
    available_width_mm: float,
    font_name: str,
    font_size_pt: float,
) -> tuple[str, str]:
    text = text.lstrip()
    if not text:
        return "", ""
    if available_width_mm <= 0:
        raise ValueError("available_width_mm must be positive")

    end = 0
    for index in range(1, len(text) + 1):
        if text_width_mm(text[:index], font_name, font_size_pt) <= available_width_mm + 1e-6:
            end = index
        else:
            break
    if end == 0:
        end = 1

    if end < len(text):
        if _is_ascii_word_character(text[end - 1]) and _is_ascii_word_character(text[end]):
            break_positions = [
                position
                for position in range(1, end)
                if text[position - 1].isspace() or text[position - 1] == "-"
            ]
            if break_positions and break_positions[-1] >= max(1, end // 2):
                end = break_positions[-1]

        while end > 1 and text[end] in PROHIBITED_LINE_START:
            end -= 1
        while end > 1 and text[end - 1] in PROHIBITED_LINE_END:
            end -= 1

    line = text[:end].rstrip()
    remaining = text[end:].lstrip()
    if not line:
        line = text[0]
        remaining = text[1:].lstrip()
    return line, remaining


def wrap_across_widths(
    text: str,
    available_widths_mm: list[float],
    font_name: str,
    font_size_pt: float,
    first_line_indent_mm: float = 0.0,
    is_paragraph_start: bool = True,
) -> tuple[list[WrappedLine], str]:
    remaining = normalize_paragraph(text)
    wrapped: list[WrappedLine] = []
    for line_index, width_mm in enumerate(available_widths_mm):
        if not remaining:
            break
        indent = first_line_indent_mm if is_paragraph_start and line_index == 0 else 0.0
        usable_width = width_mm - indent
        if usable_width <= 0:
            raise ValueError("First-line indent leaves no usable line width")
        line, remaining = take_line(remaining, usable_width, font_name, font_size_pt)
        wrapped.append(
            WrappedLine(
                text=line,
                indent_mm=indent,
                width_mm=text_width_mm(line, font_name, font_size_pt),
            )
        )
    return wrapped, remaining

