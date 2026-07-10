from __future__ import annotations

import json
from dataclasses import dataclass

from PIL import Image

from .coordinate_mapper import points_to_mm
from .fonts import register_chinese_font, text_width_mm
from .models import (
    FlowBlock,
    FlowDocument,
    ImageItem,
    LayoutPage,
    PaginatedDocument,
    TemplateConfig,
    TextItem,
)
from .pagination import LineSlot, template_for_page, usable_line_slots
from .paths import ProjectPaths
from .template_importer import load_template
from .text_layout import WrappedLine, wrap_across_widths


@dataclass
class _PageState:
    config: TemplateConfig
    page: LayoutPage
    slots: list[LineSlot]
    cursor: int = 0

    @property
    def remaining_slots(self) -> list[LineSlot]:
        return self.slots[self.cursor :]


class LayoutEngine:
    def __init__(self, paths: ProjectPaths):
        self.paths = paths
        self.font_name = register_chinese_font(paths)
        self.style = json.loads((paths.root / "config" / "style.json").read_text(encoding="utf-8"))
        self._flow: FlowDocument | None = None
        self._states: list[_PageState] = []
        self._figure_counter = 0

    def layout(self, flow: FlowDocument) -> PaginatedDocument:
        self._flow = flow
        self._states = []
        self._figure_counter = 0
        self._new_page()
        for block_index, block in enumerate(flow.blocks, 1):
            if block.type == "page_break":
                self._page_break()
            elif block.type == "spacer":
                self._place_spacer(block.lines)
            elif block.type == "heading":
                self._place_heading(block, block_index)
            elif block.type == "paragraph":
                self._place_paragraph(block, block_index)
            elif block.type in {"image", "image_grid"}:
                self._place_image_block(block, block_index)
            else:
                raise ValueError(f"Unsupported block type: {block.type}")

        while len(self._states) > 1 and not self._states[-1].page.text_items:
            self._states.pop()
        if flow.show_page_numbers:
            self._add_page_numbers()
        return PaginatedDocument(
            output_stem=flow.output_stem,
            pages=[state.page for state in self._states],
        )

    @property
    def state(self) -> _PageState:
        return self._states[-1]

    def _new_page(self) -> _PageState:
        assert self._flow is not None
        page_index = len(self._states)
        template_id = template_for_page(self._flow.template_sequence, page_index)
        config = load_template(self.paths, template_id)
        config.require_confirmed_size()
        slots = usable_line_slots(config)
        page_number = self._flow.page_number_start + page_index
        state = _PageState(
            config=config,
            page=LayoutPage(
                template_id=template_id,
                page_number=page_number,
                text_items=[],
            ),
            slots=slots,
        )
        self._states.append(state)
        return state

    def _page_break(self) -> None:
        if self.state.cursor == 0 and not self.state.page.text_items:
            return
        self._new_page()

    def _place_spacer(self, line_count: int) -> None:
        remaining = line_count
        while remaining:
            available = len(self.state.remaining_slots)
            if available == 0:
                self._new_page()
                continue
            consumed = min(available, remaining)
            self.state.cursor += consumed
            remaining -= consumed
            if remaining:
                self._new_page()

    def _font_size_for_heading(self, level: int) -> float:
        return float(self.style[f"heading_{level}_size_pt"])

    def _place_heading(self, block: FlowBlock, block_index: int) -> None:
        font_size = self._font_size_for_heading(block.level)
        while True:
            available = self.state.remaining_slots
            if not available:
                self._new_page()
                continue
            wrapped, remaining = wrap_across_widths(
                block.text,
                [slot.width_mm for slot in available],
                self.font_name,
                font_size,
            )
            required = len(wrapped) + (1 if block.keep_with_next else 0)
            if self.state.cursor > 0 and (remaining or required > len(available)):
                self._new_page()
                continue
            self._commit_wrapped_lines(
                wrapped,
                font_size,
                role="heading",
                id_prefix=f"block_{block_index}_{block.id}",
                baseline_offset_mm=float(self.style["heading_baseline_offset_mm"]),
            )
            if not remaining:
                return
            block = block.model_copy(update={"text": remaining, "keep_with_next": False})
            self._new_page()

    def _place_paragraph(self, block: FlowBlock, block_index: int) -> None:
        font_size = float(self.style["font_size_pt"])
        indent = text_width_mm(
            "实" * int(self.style["first_line_indent_em"]),
            self.font_name,
            font_size,
        )
        remaining_text = block.text
        paragraph_start = True
        segment_index = 1
        while remaining_text.strip():
            available = self.state.remaining_slots
            if not available:
                self._new_page()
                continue
            widths = [slot.width_mm for slot in available]
            wrapped, remaining = wrap_across_widths(
                remaining_text,
                widths,
                self.font_name,
                font_size,
                first_line_indent_mm=indent,
                is_paragraph_start=paragraph_start,
            )

            if remaining and len(wrapped) == 1 and self.state.cursor > 0 and paragraph_start:
                self._new_page()
                continue

            if remaining and len(wrapped) >= 2:
                next_template_id = template_for_page(
                    self._flow.template_sequence, len(self._states)
                )
                next_config = load_template(self.paths, next_template_id)
                next_widths = [slot.width_mm for slot in usable_line_slots(next_config)]
                next_wrapped, after_next = wrap_across_widths(
                    remaining,
                    next_widths,
                    self.font_name,
                    font_size,
                    first_line_indent_mm=indent,
                    is_paragraph_start=False,
                )
                if not after_next and len(next_wrapped) == 1 and len(widths) > 1:
                    wrapped, remaining = wrap_across_widths(
                        remaining_text,
                        widths[:-1],
                        self.font_name,
                        font_size,
                        first_line_indent_mm=indent,
                        is_paragraph_start=paragraph_start,
                    )

            self._commit_wrapped_lines(
                wrapped,
                font_size,
                role="body",
                id_prefix=f"block_{block_index}_{block.id}_segment_{segment_index}",
                baseline_offset_mm=float(self.style["baseline_offset_mm"]),
            )
            remaining_text = remaining
            paragraph_start = False
            segment_index += 1
            if remaining_text:
                self._new_page()

    def _commit_wrapped_lines(
        self,
        wrapped: list[WrappedLine],
        font_size_pt: float,
        role: str,
        id_prefix: str,
        baseline_offset_mm: float,
    ) -> None:
        for line_index, wrapped_line in enumerate(wrapped, 1):
            if self.state.cursor >= len(self.state.slots):
                raise RuntimeError("Layout attempted to write past the available line slots")
            slot = self.state.slots[self.state.cursor]
            self.state.page.text_items.append(
                TextItem(
                    id=f"{id_prefix}_line_{line_index}",
                    text=wrapped_line.text,
                    x_mm=slot.x_start_mm + wrapped_line.indent_mm,
                    baseline_y_mm=slot.y_mm + baseline_offset_mm,
                    font_size_pt=font_size_pt,
                    width_mm=max(0.01, wrapped_line.width_mm),
                    height_mm=points_to_mm(font_size_pt * 1.15),
                    role=role,
                )
            )
            self.state.cursor += 1

    def _add_page_numbers(self) -> None:
        assert self._flow is not None
        font_size = float(self.style["page_number_size_pt"])
        for state in self._states:
            if not state.config.page_number_regions:
                continue
            region = state.config.page_number_regions[0]
            text = str(self.style["page_number_format"]).format(page=state.page.page_number)
            width = text_width_mm(text, self.font_name, font_size)
            state.page.text_items.append(
                TextItem(
                    id=f"page_number_{state.page.page_number}",
                    text=text,
                    x_mm=region.x_mm + max(0.0, (region.width_mm - width) / 2.0),
                    baseline_y_mm=region.y_mm + region.height_mm * 0.72,
                    font_size_pt=font_size,
                    width_mm=max(0.01, width),
                    height_mm=points_to_mm(font_size * 1.15),
                    role="page_number",
                )
            )

    def _place_image_block(self, block: FlowBlock, block_index: int) -> None:
        image_count = len(block.image_paths)
        target_height = block.target_height_mm or (52.0 if image_count == 1 else 43.0)
        caption_size = float(self.style["caption_size_pt"])
        while True:
            if not self.state.remaining_slots:
                self._new_page()
                continue
            slot = self.state.remaining_slots[0]
            candidate_regions = [
                region
                for region in self.state.config.content_regions
                if region.y_mm - 1e-6 <= slot.y_mm <= region.bottom_mm + 1e-6
            ]
            if not candidate_regions:
                self._new_page()
                continue
            region = max(candidate_regions, key=lambda item: item.width_mm)
            gap_mm = 4.0 if image_count > 1 else 0.0
            frame_width = (region.width_mm - gap_mm * (image_count - 1)) / image_count
            if frame_width < 25.0:
                raise ValueError("Image columns would be too narrow to remain legible")

            captions = []
            for path_index in range(image_count):
                self._figure_counter += 1
                raw_caption = (
                    block.captions[path_index].strip()
                    if block.captions
                    else "实习现场照片"
                )
                if raw_caption.startswith("图"):
                    captions.append(raw_caption)
                else:
                    captions.append(f"图{self._figure_counter} {raw_caption}")
            wrapped_captions = [
                wrap_across_widths(
                    caption,
                    [frame_width] * 2,
                    self.font_name,
                    caption_size,
                )[0]
                for caption in captions
            ]
            caption_line_count = max(len(lines) for lines in wrapped_captions)
            top_y = max(region.y_mm, slot.y_mm)
            chosen_height = target_height
            caption_slots: list[LineSlot] = []
            while chosen_height >= 25.0:
                bottom_y = top_y + chosen_height
                caption_slots = [
                    candidate
                    for candidate in self.state.remaining_slots
                    if candidate.y_mm >= bottom_y + 5.0
                ][:caption_line_count]
                if (
                    len(caption_slots) == caption_line_count
                    and caption_slots[-1].y_mm <= region.bottom_mm + 1e-6
                ):
                    break
                chosen_height -= 4.0
            if chosen_height < 25.0 or len(caption_slots) < caption_line_count:
                if self.state.cursor > 0:
                    self._new_page()
                    self._figure_counter -= image_count
                    continue
                raise ValueError("Image and caption cannot fit in the calibrated content region")

            for image_index, relative_path in enumerate(block.image_paths):
                source = self.paths.root / relative_path
                if not source.is_file():
                    raise FileNotFoundError(source)
                with Image.open(source) as opened:
                    source_width, source_height = opened.size
                x_mm = region.x_mm + image_index * (frame_width + gap_mm)
                self.state.page.image_items.append(
                    ImageItem(
                        id=f"block_{block_index}_{block.id}_image_{image_index + 1}",
                        path=relative_path,
                        x_mm=x_mm,
                        y_mm=top_y,
                        width_mm=frame_width,
                        height_mm=chosen_height,
                        crop_mode=block.crop_mode,
                        border=True,
                        source_pixel_width=source_width,
                        source_pixel_height=source_height,
                    )
                )
                for caption_index, wrapped_line in enumerate(
                    wrapped_captions[image_index]
                ):
                    caption_slot = caption_slots[caption_index]
                    caption_x = x_mm + max(
                        0.0, (frame_width - wrapped_line.width_mm) / 2.0
                    )
                    self.state.page.text_items.append(
                        TextItem(
                            id=f"block_{block_index}_{block.id}_caption_{image_index + 1}_{caption_index + 1}",
                            text=wrapped_line.text,
                            x_mm=caption_x,
                            baseline_y_mm=caption_slot.y_mm - 0.4,
                            font_size_pt=caption_size,
                            width_mm=max(0.01, wrapped_line.width_mm),
                            height_mm=points_to_mm(caption_size * 1.15),
                            role="caption",
                        )
                    )
            last_caption_slot = caption_slots[-1]
            last_index = self.state.slots.index(last_caption_slot)
            self.state.cursor = last_index + 1
            return
