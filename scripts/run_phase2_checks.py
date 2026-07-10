from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import PaginatedDocument
from src.paths import get_paths
from src.template_importer import load_template
from src.text_layout import PROHIBITED_LINE_END, PROHIBITED_LINE_START
from src.validators import validate_paginated_layout


def main() -> None:
    paths = get_paths()
    document = PaginatedDocument.model_validate_json(
        (paths.root / "reports" / "structured" / "phase2_paginated.json").read_text(
            encoding="utf-8"
        )
    )
    template_ids = {page.template_id for page in document.pages}
    configs = {template_id: load_template(paths, template_id) for template_id in template_ids}
    continuation = configs["phase2_synthetic_continuation"]
    results: dict[str, object] = {
        "page_count_is_3": len(document.pages) == 3,
        "template_sequence_is_correct": [page.template_id for page in document.pages]
        == [
            "phase1_synthetic_demo",
            "phase2_synthetic_continuation",
            "phase2_synthetic_continuation",
        ],
        "detected_line_count_is_16": len(continuation.detected_writing_lines) == 16,
        "detected_lines_match_manual_under_0_2_mm": all(
            abs(detected.y_mm - manual.y_mm) < 0.2
            for detected, manual in zip(
                continuation.detected_writing_lines, continuation.writing_lines
            )
        ),
    }

    content_by_page = []
    paragraph_lines: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    bad_start: list[str] = []
    bad_end: list[str] = []
    baselines_match = True
    for page in document.pages:
        config = configs[page.template_id]
        content = [item for item in page.text_items if item.role != "page_number"]
        content_by_page.append(content)
        for item in content:
            if item.text and item.text[0] in PROHIBITED_LINE_START:
                bad_start.append(item.id)
            if item.text and item.text[-1] in PROHIBITED_LINE_END:
                bad_end.append(item.id)
            if "_segment_" in item.id:
                paragraph_id = re.sub(r"_segment_.*", "", item.id)
                paragraph_lines[paragraph_id][page.page_number] += 1
            expected_offset = -0.5 if item.role == "heading" else -0.6
            target_y = item.baseline_y_mm - expected_offset
            if min(abs(target_y - line.y_mm) for line in config.writing_lines) > 0.01:
                baselines_match = False

    multi_page_paragraphs = {
        paragraph: counts
        for paragraph, counts in paragraph_lines.items()
        if len(counts) > 1
    }
    results.update(
        {
            "no_heading_at_page_bottom": all(
                not content or content[-1].role != "heading" for content in content_by_page
            ),
            "no_bad_line_start_punctuation": not bad_start,
            "no_bad_line_end_punctuation": not bad_end,
            "all_text_uses_real_line_y": baselines_match,
            "multi_page_paragraph_has_at_least_2_lines_per_page": all(
                count >= 2
                for counts in multi_page_paragraphs.values()
                for count in counts.values()
            ),
            "page_numbers_present": all(
                any(item.role == "page_number" for item in page.text_items)
                for page in document.pages
            ),
            "layout_validation_passes": validate_paginated_layout(
                configs, document
            ).valid_for_print,
        }
    )
    results["all_passed"] = all(bool(value) for value in results.values())
    output = paths.output_reports / "phase2_automated_checks.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if not results["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

