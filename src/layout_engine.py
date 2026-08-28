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
    RegionMM,
    TableCell,
    TableDefinition,
    TemplateConfig,
    TextItem,
)
from .pagination import (
    LineSlot,
    content_region_columns,
    template_for_page,
    usable_line_slots,
)
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
            elif block.type == "field":
                self._place_field(block, block_index)
            elif block.type == "table":
                self._place_table(block, block_index)
            else:
                raise ValueError(f"Unsupported block type: {block.type}")

        while len(self._states) > 1 and not self._page_has_content(self._states[-1]):
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

    @staticmethod
    def _page_has_content(state: _PageState) -> bool:
        return bool(state.page.text_items or state.page.image_items or state.cursor)

    def _new_page(self) -> _PageState:
        assert self._flow is not None
        page_index = len(self._states)
        template_id = template_for_page(self._flow.template_sequence, page_index)
        config = load_template(self.paths, template_id)
        config.require_confirmed_size()
        try:
            slots = usable_line_slots(config)
        except ValueError as exc:
            # Cover, signature, and other field/table-only pages legitimately
            # have no flowing body area. Text/image flow blocks still fail with
            # a clear error below instead of looping while looking for slots.
            if "no calibrated content region" in str(exc) or "no usable content slots" in str(exc):
                slots = []
            else:
                raise
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
        if not self._page_has_content(self.state):
            return
        self._new_page()

    def _place_spacer(self, line_count: int) -> None:
        remaining = line_count
        while remaining:
            available = len(self.state.remaining_slots)
            if available == 0:
                if not self.state.slots:
                    raise ValueError(
                        f"Template '{self.state.config.template_id}' has no usable content slots for a spacer"
                    )
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
                if not self.state.slots:
                    raise ValueError(
                        f"Template '{self.state.config.template_id}' has no usable content slots for a heading"
                    )
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
                if not self.state.slots:
                    raise ValueError(
                        f"Template '{self.state.config.template_id}' has no usable content slots for a paragraph"
                    )
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
            if slot.baseline_offset_mm is not None:
                baseline_offset = slot.baseline_offset_mm
            elif slot.layout_mode == "free":
                baseline_offset = 0.0
            else:
                baseline_offset = baseline_offset_mm
            self.state.page.text_items.append(
                TextItem(
                    id=f"{id_prefix}_line_{line_index}",
                    text=wrapped_line.text,
                    x_mm=slot.x_start_mm + wrapped_line.indent_mm,
                    baseline_y_mm=slot.y_mm + baseline_offset,
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
                if not self.state.slots:
                    raise ValueError(
                        f"Template '{self.state.config.template_id}' has no usable content slots for an image"
                    )
                self._new_page()
                continue
            slot = self.state.remaining_slots[0]
            candidate_regions = [
                region
                for region in self.state.config.content_regions
                if region.id == slot.region_id
            ]
            if not candidate_regions:
                self._new_page()
                continue
            region = candidate_regions[0]
            region_columns = content_region_columns(region)
            if slot.column_index >= len(region_columns):
                raise ValueError("Image slot references an invalid content column")
            column_start, column_end = region_columns[slot.column_index]
            available_width = column_end - column_start
            gap_mm = 4.0 if image_count > 1 else 0.0
            frame_width = (available_width - gap_mm * (image_count - 1)) / image_count
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
                    if candidate.region_id == slot.region_id
                    and candidate.column_index == slot.column_index
                    and candidate.y_mm >= bottom_y + 5.0
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
                x_mm = column_start + image_index * (frame_width + gap_mm)
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

    def _place_field(self, block: FlowBlock, block_index: int) -> None:
        """Place a value in a named pre-printed field without consuming flow slots."""
        assert block.field_name is not None
        target = self.state.config.fields.get(block.field_name)
        if target is None:
            raise ValueError(
                f"Field '{block.field_name}' is not configured on template "
                f"'{self.state.config.template_id}'"
            )
        text = block.text if block.text else (block.value or "")
        font_size = target.font_size_pt
        width = text_width_mm(text, self.font_name, font_size)
        if width > target.width_mm + 1e-6:
            raise ValueError(
                f"Field '{block.field_name}' value exceeds target width "
                f"({width:.2f}mm > {target.width_mm:.2f}mm)"
            )
        alignment = block.alignment or target.alignment
        if alignment == "center":
            x_mm = target.x_mm + (target.width_mm - width) / 2.0
        elif alignment == "right":
            x_mm = target.right_mm - width
        else:
            x_mm = target.x_mm
        baseline = target.y_mm + target.height_mm * 0.72 + target.baseline_offset_mm
        self.state.page.text_items.append(
            TextItem(
                id=f"block_{block_index}_{block.id}_field_{block.field_name}",
                text=text,
                x_mm=max(target.x_mm, x_mm),
                baseline_y_mm=baseline,
                font_size_pt=font_size,
                width_mm=max(0.01, width),
                height_mm=points_to_mm(font_size * 1.15),
                role="field",
            )
        )

    def _resolve_table(self, block: FlowBlock) -> TableDefinition:
        assert self.state.config is not None
        if block.table_id and block.table_id in self.state.config.tables:
            return self.state.config.tables[block.table_id]
        if block.table_id:
            region = next(
                (item for item in self.state.config.table_regions if item.id == block.table_id),
                None,
            )
            if region is not None:
                return TableDefinition(
                    id=block.table_id,
                    region=region,
                    rows=block.table_rows or 1,
                    columns=block.table_columns or 1,
                )
        if self.state.config.table_regions:
            region = self.state.config.table_regions[0]
            return TableDefinition(
                id=block.table_id or region.id or "table_1",
                region=region,
                rows=block.table_rows or max(1, len(block.table_values)),
                columns=block.table_columns or max(
                    1, max((len(row) for row in block.table_values), default=1)
                ),
            )
        if block.table_cells:
            return TableDefinition(id=block.table_id or "inline_table", cells=block.table_cells)
        raise ValueError(
            f"Table '{block.table_id or block.id}' has no configured table region or cells"
        )

    def _table_cells(self, definition: TableDefinition) -> list[TableCell]:
        if definition.cells:
            return definition.cells
        assert definition.region is not None
        rows = definition.rows or 1
        columns = definition.columns or 1
        cell_width = definition.region.width_mm / columns
        cell_height = definition.region.height_mm / rows
        return [
            TableCell(
                id=f"{definition.id}_{row}_{column}",
                row=row,
                column=column,
                x_mm=definition.region.x_mm + column * cell_width,
                y_mm=definition.region.y_mm + row * cell_height,
                width_mm=cell_width,
                height_mm=cell_height,
            )
            for row in range(rows)
            for column in range(columns)
        ]

    def _place_table(self, block: FlowBlock, block_index: int) -> None:
        definition = self._resolve_table(block)
        values = block.table_values
        explicit_values = {(cell.row, cell.column): cell for cell in block.table_cells}
        for cell in self._table_cells(definition):
            value_cell = explicit_values.get((cell.row, cell.column))
            text = (
                value_cell.text
                if value_cell is not None
                else values[cell.row][cell.column]
                if cell.row < len(values) and cell.column < len(values[cell.row])
                else cell.text
            )
            if not text:
                continue
            alignment = value_cell.alignment if value_cell is not None else cell.alignment
            font_size = definition.font_size_pt
            inner_x = cell.x_mm + definition.cell_padding_mm
            inner_width = max(1.0, cell.width_mm - definition.cell_padding_mm * 2.0)
            wrapped, remaining = wrap_across_widths(
                text,
                [inner_width] * max(1, int(cell.height_mm / max(1.0, points_to_mm(font_size * 1.15)))),
                self.font_name,
                font_size,
            )
            max_lines = max(1, int(cell.height_mm / max(1.0, points_to_mm(font_size * 1.15))))
            if remaining:
                raise ValueError(
                    f"Table '{definition.id}' cell ({cell.row}, {cell.column}) text does not fit"
                )
            for line_index, wrapped_line in enumerate(wrapped[:max_lines]):
                if alignment == "center":
                    x_mm = inner_x + (inner_width - wrapped_line.width_mm) / 2.0
                elif alignment == "right":
                    x_mm = inner_x + inner_width - wrapped_line.width_mm
                else:
                    x_mm = inner_x
                baseline = cell.y_mm + definition.cell_padding_mm + points_to_mm(font_size * 0.9) + line_index * points_to_mm(font_size * 1.15)
                self.state.page.text_items.append(
                    TextItem(
                        id=f"block_{block_index}_{block.id}_table_{cell.row}_{cell.column}_{line_index + 1}",
                        text=wrapped_line.text,
                        x_mm=max(cell.x_mm, x_mm),
                        baseline_y_mm=baseline,
                        font_size_pt=font_size,
                        width_mm=max(0.01, wrapped_line.width_mm),
                        height_mm=points_to_mm(font_size * 1.15),
                        role="field",
                    )
                )
