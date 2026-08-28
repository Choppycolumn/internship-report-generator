from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TemplateStatus(str, Enum):
    AWAITING_PHYSICAL_SIZE = "awaiting_physical_size"
    SIZE_CONFIRMED = "size_confirmed"
    CORRECTED = "corrected"
    CALIBRATED = "calibrated"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class RegionMM(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    label: str = ""
    x_mm: float = Field(ge=0)
    y_mm: float = Field(ge=0)
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)

    @property
    def right_mm(self) -> float:
        return self.x_mm + self.width_mm

    @property
    def bottom_mm(self) -> float:
        return self.y_mm + self.height_mm

    def intersects(self, other: "RegionMM", tolerance_mm: float = 0.0) -> bool:
        return not (
            self.right_mm <= other.x_mm + tolerance_mm
            or other.right_mm <= self.x_mm + tolerance_mm
            or self.bottom_mm <= other.y_mm + tolerance_mm
            or other.bottom_mm <= self.y_mm + tolerance_mm
        )


class ContentRegion(RegionMM):
    """A flowable content area with explicit ordering and column semantics."""

    flow_order: int = Field(default=0, ge=0)
    layout_mode: Literal["lined", "free"] = "lined"
    columns: int = Field(default=1, ge=1, le=4)
    column_gap_mm: float = Field(default=0.0, ge=0)
    baseline_start_mm: float | None = Field(default=None, ge=0)
    line_spacing_mm: float | None = Field(default=None, gt=0)
    baseline_offset_mm: float | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_region_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "flow_order" not in data and "order" in data:
            data["flow_order"] = data.pop("order")
        if "layout_mode" not in data and "mode" in data:
            data["layout_mode"] = data.pop("mode")
        if "line_spacing_mm" not in data and "baseline_spacing_mm" in data:
            data["line_spacing_mm"] = data.pop("baseline_spacing_mm")
        return data


class WritingLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    x_start_mm: float = Field(ge=0)
    x_end_mm: float = Field(gt=0)
    y_mm: float = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: Literal["manual", "detected"] = "manual"

    @model_validator(mode="after")
    def validate_x_order(self) -> "WritingLine":
        if self.x_end_mm <= self.x_start_mm:
            raise ValueError("x_end_mm must be greater than x_start_mm")
        return self


class TemplateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 2
    template_id: str
    display_name: str = ""
    status: TemplateStatus = TemplateStatus.AWAITING_PHYSICAL_SIZE
    physical_width_mm: float | None = Field(default=None, gt=0)
    physical_height_mm: float | None = Field(default=None, gt=0)
    physical_size_source: Literal["user_measurement", "user_confirmed_estimate"] | None = None
    source_media: str
    source_sha256: str
    source_kind: Literal["raster", "pdf"]
    source_preview_image: str | None = None
    corrected_image: str | None = None
    source_pixel_width: int | None = Field(default=None, gt=0)
    source_pixel_height: int | None = Field(default=None, gt=0)
    source_dpi: float | None = Field(default=None, gt=0)
    diagnostic_pdf_media_box_mm: list[float] | None = None
    orientation: Literal["portrait", "landscape", "unknown"] = "unknown"
    binding_side: Literal["left", "right", "top", "none", "unknown"] = "unknown"
    notes: str = ""
    content_regions: list[ContentRegion] = Field(default_factory=list)
    header_regions: list[RegionMM] = Field(default_factory=list)
    fixed_text_regions: list[RegionMM] = Field(default_factory=list)
    forbidden_regions: list[RegionMM] = Field(default_factory=list)
    image_regions: list[RegionMM] = Field(default_factory=list)
    table_regions: list[RegionMM] = Field(default_factory=list)
    signature_regions: list[RegionMM] = Field(default_factory=list)
    page_number_regions: list[RegionMM] = Field(default_factory=list)
    writing_lines: list[WritingLine] = Field(default_factory=list)
    detected_writing_lines: list[WritingLine] = Field(default_factory=list)
    fields: dict[str, "FieldTarget"] = Field(default_factory=dict)
    tables: dict[str, "TableDefinition"] = Field(default_factory=dict)
    manual_measurements: dict[str, float | str | bool | None] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    imported_at: str
    updated_at: str

    @model_validator(mode="before")
    @classmethod
    def migrate_schema(cls, value: Any) -> Any:
        """Normalize v1 JSON in memory; persistence is opt-in via template migrate."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        version = int(data.get("schema_version", 1) or 1)
        if version > 2:
            raise ValueError(
                f"Template schema_version {version} is newer than the supported version 2"
            )
        regions = []
        for index, raw_region in enumerate(data.get("content_regions", []) or []):
            region = dict(raw_region)
            region.setdefault("flow_order", index)
            region.setdefault("layout_mode", "lined")
            region.setdefault("columns", 1)
            regions.append(region)
        data["content_regions"] = regions

        # v1 field values were plain RegionMM records. Accept both those and the
        # v2 nested {region: ..., alignment: ...} shape.
        normalized_fields = {}
        for name, raw_field in (data.get("fields", {}) or {}).items():
            if isinstance(raw_field, BaseModel):
                raw_field = raw_field.model_dump()
            if isinstance(raw_field, dict):
                field = dict(raw_field)
                nested = field.pop("region", None)
                if isinstance(nested, dict):
                    nested = dict(nested)
                    nested.update(field)
                    field = nested
                if "alignment" not in field and "align" in field:
                    field["alignment"] = field.pop("align")
                normalized_fields[str(name)] = field
            else:
                normalized_fields[str(name)] = raw_field
        data["fields"] = normalized_fields
        # Unknown historical versions are still loaded through the v2 shape so
        # callers can validate and decide whether to persist the migration.
        data["schema_version"] = 2 if version < 2 else version
        return data

    @model_validator(mode="after")
    def validate_physical_size_pair(self) -> "TemplateConfig":
        width_set = self.physical_width_mm is not None
        height_set = self.physical_height_mm is not None
        if width_set != height_set:
            raise ValueError("physical width and height must be set together")
        if width_set and self.physical_size_source not in {
            "user_measurement",
            "user_confirmed_estimate",
        }:
            raise ValueError("physical dimensions require an explicit user size source")
        if not width_set and self.physical_size_source is not None:
            raise ValueError("physical_size_source requires dimensions")
        return self

    @property
    def has_confirmed_size(self) -> bool:
        return (
            self.physical_width_mm is not None
            and self.physical_height_mm is not None
            and self.physical_size_source
            in {"user_measurement", "user_confirmed_estimate"}
        )

    @property
    def has_exact_size(self) -> bool:
        return self.has_confirmed_size and self.physical_size_source == "user_measurement"

    def require_confirmed_size(self) -> tuple[float, float]:
        if not self.has_confirmed_size:
            raise ValueError(
                f"Template '{self.template_id}' has no user-confirmed physical size. "
                "Run template set-size with measured width and height first."
            )
        return float(self.physical_width_mm), float(self.physical_height_mm)

    def resolve_path(self, project_root: Path, relative_path: str | None) -> Path | None:
        return project_root / relative_path if relative_path else None


class TextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    text: str
    x_mm: float = Field(ge=0)
    baseline_y_mm: float = Field(ge=0)
    font_size_pt: float = Field(default=10.5, gt=0)
    width_mm: float | None = Field(default=None, gt=0)
    height_mm: float | None = Field(default=None, gt=0)
    role: Literal["body", "heading", "field", "caption", "page_number"] = "body"


class FieldTarget(RegionMM):
    alignment: Literal["left", "center", "right"] = "left"
    font_size_pt: float = Field(default=10.5, gt=0)
    baseline_offset_mm: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def normalize_field_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "alignment" not in data and "align" in data:
            data["alignment"] = data.pop("align")
        nested = data.pop("region", None)
        if isinstance(nested, dict):
            nested = dict(nested)
            nested.update(data)
            data = nested
        return data


class TableCell(RegionMM):
    row: int = Field(default=0, ge=0)
    column: int = Field(default=0, ge=0)
    text: str = ""
    alignment: Literal["left", "center", "right"] = "left"

    @model_validator(mode="before")
    @classmethod
    def normalize_cell_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "row" not in data and "row_index" in data:
            data["row"] = data.pop("row_index")
        if "column" not in data and "column_index" in data:
            data["column"] = data.pop("column_index")
        return data


class TableDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    region: RegionMM | None = None
    rows: int | None = Field(default=None, ge=1)
    columns: int | None = Field(default=None, ge=1)
    cells: list[TableCell] = Field(default_factory=list)
    font_size_pt: float = Field(default=9.0, gt=0)
    cell_padding_mm: float = Field(default=1.0, ge=0)
    border: bool = False

    @model_validator(mode="after")
    def validate_table_geometry(self) -> "TableDefinition":
        if not self.cells and self.region is None:
            raise ValueError("Table definitions require a region or explicit cells")
        if self.cells and (self.rows is not None or self.columns is not None):
            max_row = max(cell.row for cell in self.cells)
            max_col = max(cell.column for cell in self.cells)
            if self.rows is not None and max_row >= self.rows:
                raise ValueError("table cell row exceeds table rows")
            if self.columns is not None and max_col >= self.columns:
                raise ValueError("table cell column exceeds table columns")
        return self


class ImageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    path: str
    x_mm: float = Field(ge=0)
    y_mm: float = Field(ge=0)
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    crop_mode: Literal["contain", "cover"] = "contain"
    border: bool = True
    source_pixel_width: int = Field(gt=0)
    source_pixel_height: int = Field(gt=0)


class LayoutDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    output_stem: str
    text_items: list[TextItem] = Field(default_factory=list)
    image_items: list[ImageItem] = Field(default_factory=list)


class FlowBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal[
        "heading",
        "paragraph",
        "image",
        "image_grid",
        "spacer",
        "page_break",
        "field",
        "table",
    ]
    text: str = ""
    level: int = Field(default=1, ge=1, le=3)
    lines: int = Field(default=1, ge=1)
    keep_with_next: bool = False
    image_paths: list[str] = Field(default_factory=list, max_length=3)
    captions: list[str] = Field(default_factory=list, max_length=3)
    crop_mode: Literal["contain", "cover"] = "contain"
    target_height_mm: float | None = Field(default=None, ge=25.0, le=100.0)
    field_name: str | None = None
    value: str | None = None
    alignment: Literal["left", "center", "right"] | None = None
    table_id: str | None = None
    table_values: list[list[str]] = Field(default_factory=list)
    table_cells: list[TableCell] = Field(default_factory=list)
    table_rows: int | None = Field(default=None, ge=1)
    table_columns: int | None = Field(default=None, ge=1)
    draw_border: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_block_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "field_name" not in data and "field" in data:
            data["field_name"] = data.pop("field")
        if "alignment" not in data and "align" in data:
            data["alignment"] = data.pop("align")
        if "value" in data and not data.get("text"):
            data["text"] = str(data["value"])
        if "table_values" not in data:
            if "values" in data:
                data["table_values"] = data.pop("values")
            elif "table" in data and isinstance(data["table"], list):
                data["table_values"] = data.pop("table")
        if "table_cells" not in data and "cells" in data:
            data["table_cells"] = data.pop("cells")
        return data

    @model_validator(mode="after")
    def validate_image_block(self) -> "FlowBlock":
        if self.type in {"image", "image_grid"}:
            if not self.image_paths:
                raise ValueError("Image blocks require at least one image path")
            if self.type == "image" and len(self.image_paths) != 1:
                raise ValueError("type=image requires exactly one image path")
            if self.captions and len(self.captions) != len(self.image_paths):
                raise ValueError("captions must be empty or match image_paths length")
        elif self.image_paths or self.captions:
            raise ValueError("image_paths and captions are only valid for image blocks")
        if self.type == "field" and not self.field_name:
            raise ValueError("field blocks require field_name")
        if self.type == "table" and not (self.table_id or self.table_values or self.table_cells):
            raise ValueError("table blocks require table_id, table_values, or table_cells")
        return self


class FlowDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_stem: str
    template_sequence: list[str] = Field(min_length=1)
    blocks: list[FlowBlock] = Field(default_factory=list)
    page_number_start: int = Field(default=1, ge=1)
    show_page_numbers: bool = True


class LayoutPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    page_number: int = Field(ge=1)
    text_items: list[TextItem] = Field(default_factory=list)
    image_items: list[ImageItem] = Field(default_factory=list)


class ImageQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: str
    perceptual_hash: str
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    blur_score: float = Field(ge=0)
    brightness_mean: float = Field(ge=0, le=255)
    contrast_std: float = Field(ge=0)
    is_blurry: bool
    is_low_resolution: bool
    warnings: list[str] = Field(default_factory=list)


class DailyImageReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    original_name: str
    original_path: str
    processed_path: str
    caption: str = ""
    generated_text: str = ""
    approved: bool = False
    quality: ImageQualityReport
    duplicate_of: str | None = None


class DailyReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    topic: str = ""
    notes: str = ""
    status: Literal["draft", "reviewed", "approved"] = "draft"
    images: list[DailyImageReview] = Field(default_factory=list)
    updated_at: str


class DailyFactBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_facts: list[str] = Field(default_factory=list)
    inferred_facts: list[str] = Field(default_factory=list)
    pending_confirmation: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)


class DailyDraftSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["heading", "paragraph", "image"]
    text: str = ""
    level: int | None = Field(default=None, ge=1, le=3)
    path: str | None = None
    caption: str = ""
    basis: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False

    @model_validator(mode="after")
    def validate_section(self) -> "DailyDraftSection":
        if self.type == "heading" and self.level is None:
            raise ValueError("heading sections require a level")
        if self.type == "image" and not self.path:
            raise ValueError("image sections require a path")
        return self


class DuplicateFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_section_id: str
    other_date: str
    other_section_id: str
    score: float = Field(ge=0, le=1)
    excerpt: str


class DailyDraftMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body_characters: int = Field(ge=0)
    target_characters: int = Field(ge=1)
    remaining_characters: int = Field(ge=0)
    section_characters: dict[str, int] = Field(default_factory=dict)
    max_similarity: float = Field(default=0.0, ge=0, le=1)
    duplicate_findings: list[DuplicateFinding] = Field(default_factory=list)


class DailyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    version: int = Field(default=1, ge=1)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    title: str
    status: Literal["draft", "approved"] = "draft"
    source_review_updated_at: str
    facts: DailyFactBundle
    word_count_target: int = Field(default=650, ge=100)
    sections: list[DailyDraftSection] = Field(default_factory=list)
    metrics: DailyDraftMetrics
    content_warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    content_hash: str = ""
    created_at: str
    updated_at: str
    approved_at: str | None = None


class CodexDailyDraftInput(BaseModel):
    """Human/Codex-authored content before deterministic metrics and locking."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    title: str
    confirmed_facts: list[str] = Field(default_factory=list)
    inferred_facts: list[str] = Field(default_factory=list)
    pending_confirmation: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    word_count_target: int = Field(default=650, ge=100)
    sections: list[DailyDraftSection] = Field(default_factory=list)


class PaginatedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_stem: str
    pages: list[LayoutPage] = Field(min_length=1)


class PrinterCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    printer_name: str
    template_id: str
    x_offset_mm: float = 0.0
    y_offset_mm: float = 0.0
    scale_x: float = Field(default=1.0, gt=0)
    scale_y: float = Field(default=1.0, gt=0)
    rotation_degree: float = Field(default=0.0, ge=-5.0, le=5.0)
    updated_at: str


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Severity
    message: str
    object_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid_for_print: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == Severity.ERROR]


# TemplateConfig is declared before FieldTarget/TableDefinition so the public
# model layout remains close to the historical schema. Resolve those forward
# references once all model classes are available.
TemplateConfig.model_rebuild()
