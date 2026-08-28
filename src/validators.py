from __future__ import annotations

import unicodedata

from .coordinate_mapper import points_to_mm
from .models import (
    LayoutDocument,
    PaginatedDocument,
    RegionMM,
    Severity,
    TemplateConfig,
    ValidationIssue,
    ValidationReport,
)


def estimate_text_width_mm(text: str, font_size_pt: float) -> float:
    units = 0.0
    for character in text:
        units += 1.0 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else 0.55
    return points_to_mm(units * font_size_pt)


def text_item_region(item) -> RegionMM:
    width = item.width_mm or estimate_text_width_mm(item.text, item.font_size_pt)
    font_height_mm = item.height_mm or points_to_mm(item.font_size_pt * 1.15)
    top = max(0.0, item.baseline_y_mm - font_height_mm * 0.82)
    return RegionMM(
        id=item.id,
        label=item.text[:24],
        x_mm=item.x_mm,
        y_mm=top,
        width_mm=max(0.01, width),
        height_mm=max(0.01, font_height_mm),
    )


def validate_template(config: TemplateConfig) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        page_width, page_height = config.require_confirmed_size()
    except ValueError as exc:
        return [
            ValidationIssue(
                code="PHYSICAL_SIZE_MISSING", severity=Severity.ERROR, message=str(exc)
            )
        ]
    if not config.has_exact_size:
        issues.append(
            ValidationIssue(
                code="PHYSICAL_SIZE_PROVISIONAL",
                severity=Severity.ERROR,
                message=(
                    "Physical page size is a user-confirmed estimate. Preview and calibration "
                    "are allowed, but formal print output remains blocked until exact width and "
                    "height are measured."
                ),
            )
        )
    region_groups = [
        "content_regions",
        "header_regions",
        "fixed_text_regions",
        "forbidden_regions",
        "image_regions",
        "table_regions",
        "signature_regions",
        "page_number_regions",
    ]
    for group_name in region_groups:
        for region in getattr(config, group_name):
            if region.right_mm > page_width + 1e-6 or region.bottom_mm > page_height + 1e-6:
                issues.append(
                    ValidationIssue(
                        code="REGION_OUT_OF_BOUNDS",
                        severity=Severity.ERROR,
                        message=f"{group_name} region exceeds physical page",
                        object_id=region.id,
                    )
                )
    for line in config.writing_lines:
        if line.x_end_mm > page_width + 1e-6 or line.y_mm > page_height + 1e-6:
            issues.append(
                ValidationIssue(
                    code="WRITING_LINE_OUT_OF_BOUNDS",
                    severity=Severity.ERROR,
                    message="Writing line exceeds physical page",
                    object_id=line.id,
                )
            )
    # v2 content regions carry the ordering and column model used by the
    # paginator. Check the configuration explicitly so a bad template fails
    # before a PDF is generated.
    for region in config.content_regions:
        if not 1 <= region.columns <= 4:
            issues.append(
                ValidationIssue(
                    code="CONTENT_REGION_INVALID_COLUMNS",
                    severity=Severity.ERROR,
                    message="Content region columns must be between 1 and 4",
                    object_id=region.id,
                    )
                )
        usable_width = region.width_mm - region.column_gap_mm * (region.columns - 1)
        if usable_width <= 0 or usable_width / region.columns < 5.0:
            issues.append(
                ValidationIssue(
                    code="CONTENT_REGION_COLUMN_TOO_NARROW",
                    severity=Severity.ERROR,
                    message="Each content column must be at least 5 mm wide",
                    object_id=region.id,
                )
            )
        if region.layout_mode == "free":
            if region.baseline_start_mm is not None and not (
                region.y_mm - 1e-6 <= region.baseline_start_mm <= region.bottom_mm + 1e-6
            ):
                issues.append(
                    ValidationIssue(
                        code="CONTENT_REGION_BASELINE_OUT_OF_BOUNDS",
                        severity=Severity.ERROR,
                        message="Free content baseline_start_mm must lie within its region",
                        object_id=region.id,
                    )
                )
            if region.line_spacing_mm is None or region.line_spacing_mm <= 0:
                issues.append(
                    ValidationIssue(
                        code="CONTENT_REGION_FREE_SPACING_MISSING",
                        severity=Severity.ERROR,
                        message="Free content regions require a positive line_spacing_mm",
                        object_id=region.id,
                    )
                )

    for index, region in enumerate(config.content_regions):
        for other in config.content_regions[index + 1 :]:
            if region.intersects(other, tolerance_mm=0.1):
                issues.append(
                    ValidationIssue(
                        code="CONTENT_REGION_OVERLAP",
                        severity=Severity.ERROR,
                        message="Content regions overlap",
                        object_id=region.id,
                        details={"other_region_id": other.id},
                    )
                )

    def _check_target(target: RegionMM, code: str, label: str) -> None:
        if target.right_mm > page_width + 1e-6 or target.bottom_mm > page_height + 1e-6:
            issues.append(
                ValidationIssue(
                    code=code,
                    severity=Severity.ERROR,
                    message=f"{label} target exceeds physical page",
                    object_id=target.id,
                )
            )

    field_targets = list(config.fields.items())
    for name, target in field_targets:
        _check_target(target, "FIELD_TARGET_OUT_OF_BOUNDS", f"Field '{name}'")
        for protected in config.forbidden_regions:
            if target.intersects(protected, tolerance_mm=0.1):
                issues.append(
                    ValidationIssue(
                        code="FIELD_TARGET_IN_FORBIDDEN_REGION",
                        severity=Severity.ERROR,
                        message=f"Field '{name}' target intersects a forbidden region",
                        object_id=name,
                    )
                )
    for index, (name, target) in enumerate(field_targets):
        for other_name, other in field_targets[index + 1 :]:
            if target.intersects(other, tolerance_mm=0.1):
                issues.append(
                    ValidationIssue(
                        code="FIELD_TARGET_OVERLAP",
                        severity=Severity.ERROR,
                        message=f"Field targets '{name}' and '{other_name}' overlap",
                        object_id=name,
                        details={"other_field": other_name},
                    )
                )

    for table_id, table in config.tables.items():
        if table.region is not None:
            _check_target(table.region, "TABLE_REGION_OUT_OF_BOUNDS", f"Table '{table_id}'")
        cells = table.cells
        for cell in cells:
            _check_target(cell, "TABLE_CELL_OUT_OF_BOUNDS", f"Table '{table_id}' cell")
            if table.region is not None and not (
                cell.x_mm >= table.region.x_mm - 1e-6
                and cell.right_mm <= table.region.right_mm + 1e-6
                and cell.y_mm >= table.region.y_mm - 1e-6
                and cell.bottom_mm <= table.region.bottom_mm + 1e-6
            ):
                issues.append(
                    ValidationIssue(
                        code="TABLE_CELL_OUT_OF_BOUNDS",
                        severity=Severity.ERROR,
                        message=f"Table cell '{cell.id}' lies outside table '{table_id}'",
                        object_id=cell.id,
                    )
                )
        for index, cell in enumerate(cells):
            for other in cells[index + 1 :]:
                if cell.intersects(other, tolerance_mm=0.1):
                    issues.append(
                        ValidationIssue(
                            code="TABLE_CELL_OVERLAP",
                            severity=Severity.ERROR,
                            message=f"Cells in table '{table_id}' overlap",
                            object_id=cell.id,
                            details={"other_cell_id": other.id},
                        )
                    )
    return issues


def validate_layout(
    config: TemplateConfig,
    document: LayoutDocument,
    minimum_font_size_pt: float = 8.0,
) -> ValidationReport:
    issues = validate_template(config)
    if any(issue.severity == Severity.ERROR for issue in issues):
        return ValidationReport(valid_for_print=False, issues=issues)
    page_width, page_height = config.require_confirmed_size()
    image_regions: list[RegionMM] = []
    for item in document.image_items:
        region = RegionMM(
            id=item.id,
            label=item.path,
            x_mm=item.x_mm,
            y_mm=item.y_mm,
            width_mm=item.width_mm,
            height_mm=item.height_mm,
        )
        image_regions.append(region)
        if region.right_mm > page_width + 1e-6 or region.bottom_mm > page_height + 1e-6:
            issues.append(
                ValidationIssue(
                    code="IMAGE_OUT_OF_BOUNDS",
                    severity=Severity.ERROR,
                    message="Image frame extends beyond the physical page",
                    object_id=item.id,
                )
            )
        protected = (
            config.forbidden_regions
            + config.header_regions
            + config.fixed_text_regions
            + config.table_regions
            + config.signature_regions
            + config.page_number_regions
            + list(config.fields.values())
            + [table.region for table in config.tables.values() if table.region is not None]
            + [cell for table in config.tables.values() for cell in table.cells]
        )
        for protected_region in protected:
            if region.intersects(protected_region, tolerance_mm=0.1):
                issues.append(
                    ValidationIssue(
                        code="IMAGE_IN_PROTECTED_REGION",
                        severity=Severity.ERROR,
                        message=f"Image intersects protected region '{protected_region.label or protected_region.id}'",
                        object_id=item.id,
                    )
                )
        if config.content_regions and not any(
            region.x_mm >= content.x_mm - 1e-6
            and region.right_mm <= content.right_mm + 1e-6
            and region.y_mm >= content.y_mm - 1e-6
            and region.bottom_mm <= content.bottom_mm + 1e-6
            for content in config.content_regions
        ):
            issues.append(
                ValidationIssue(
                    code="IMAGE_OUTSIDE_CONTENT_REGION",
                    severity=Severity.ERROR,
                    message="Image is outside every calibrated content region",
                    object_id=item.id,
                )
            )
        effective_dpi = min(
            item.source_pixel_width / (item.width_mm / 25.4),
            item.source_pixel_height / (item.height_mm / 25.4),
        )
        if effective_dpi < 72:
            severity = Severity.ERROR
        elif effective_dpi < 150:
            severity = Severity.WARNING
        else:
            severity = None
        if severity:
            issues.append(
                ValidationIssue(
                    code="IMAGE_RESOLUTION_LOW",
                    severity=severity,
                    message=f"Effective image resolution is only {effective_dpi:.1f} dpi",
                    object_id=item.id,
                    details={"effective_dpi": round(effective_dpi, 1)},
                )
            )
    for index, region in enumerate(image_regions):
        for other in image_regions[index + 1 :]:
            if region.intersects(other, tolerance_mm=0.1):
                issues.append(
                    ValidationIssue(
                        code="IMAGE_OVERLAP",
                        severity=Severity.ERROR,
                        message="Two image frames overlap",
                        object_id=region.id,
                        details={"other_image_id": other.id},
                    )
                )
    for item in document.text_items:
        if item.font_size_pt < minimum_font_size_pt:
            issues.append(
                ValidationIssue(
                    code="FONT_TOO_SMALL",
                    severity=Severity.ERROR,
                    message=f"Font size {item.font_size_pt:g} pt is below {minimum_font_size_pt:g} pt",
                    object_id=item.id,
                )
            )
        region = text_item_region(item)
        if region.right_mm > page_width + 1e-6 or region.bottom_mm > page_height + 1e-6:
            issues.append(
                ValidationIssue(
                    code="TEXT_OUT_OF_BOUNDS",
                    severity=Severity.ERROR,
                    message="Text extends beyond the physical page",
                    object_id=item.id,
                )
            )
        protected_regions = (
            config.forbidden_regions
            + config.header_regions
            + config.fixed_text_regions
            + config.image_regions
            + config.signature_regions
        )
        if item.role != "field":
            protected_regions += config.table_regions
            protected_regions += list(config.fields.values())
            protected_regions += [
                table.region for table in config.tables.values() if table.region is not None
            ]
            protected_regions += [
                cell for table in config.tables.values() for cell in table.cells
            ]
        if item.role != "page_number":
            protected_regions += config.page_number_regions
        for forbidden in protected_regions:
            if region.intersects(forbidden, tolerance_mm=0.1):
                issues.append(
                    ValidationIssue(
                        code="TEXT_IN_FORBIDDEN_REGION",
                        severity=Severity.ERROR,
                        message=f"Text intersects protected region '{forbidden.label or forbidden.id}'",
                        object_id=item.id,
                    )
                )
        for image_region in image_regions:
            if region.intersects(image_region, tolerance_mm=0.1):
                issues.append(
                    ValidationIssue(
                        code="TEXT_IMAGE_OVERLAP",
                        severity=Severity.ERROR,
                        message="Text overlaps an image frame",
                        object_id=item.id,
                        details={"image_id": image_region.id},
                    )
                )
        if item.role in {"body", "heading", "caption"} and config.content_regions:
            contained = any(
                region.x_mm >= content.x_mm - 1e-6
                and region.right_mm <= content.right_mm + 1e-6
                and region.y_mm >= content.y_mm - 2.0
                and region.bottom_mm <= content.bottom_mm + 2.0
                for content in config.content_regions
            )
            if not contained:
                issues.append(
                    ValidationIssue(
                        code="TEXT_OUTSIDE_CONTENT_REGION",
                        severity=Severity.ERROR,
                        message="Body text is outside every calibrated content region",
                        object_id=item.id,
                    )
                )
    # Catch text frames that collide after all block types have been resolved.
    text_regions = [(item, text_item_region(item)) for item in document.text_items]
    for index, (item, region) in enumerate(text_regions):
        for other_item, other_region in text_regions[index + 1 :]:
            if region.intersects(other_region, tolerance_mm=0.05):
                issues.append(
                    ValidationIssue(
                        code="TEXT_OVERLAP",
                        severity=Severity.ERROR,
                        message="Two text frames overlap",
                        object_id=item.id,
                        details={"other_text_id": other_item.id},
                    )
                )
    return ValidationReport(
        valid_for_print=not any(issue.severity == Severity.ERROR for issue in issues),
        issues=issues,
    )


def validate_paginated_layout(
    configs: dict[str, TemplateConfig],
    document: PaginatedDocument,
    minimum_font_size_pt: float = 8.0,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    page_sizes: dict[tuple[float, float], list[int]] = {}
    for page_index, page in enumerate(document.pages, 1):
        config = configs.get(page.template_id)
        if config is None:
            issues.append(
                ValidationIssue(
                    code="TEMPLATE_NOT_FOUND",
                    severity=Severity.ERROR,
                    message=f"Template '{page.template_id}' is missing for page {page_index}",
                )
            )
            continue
        page_document = LayoutDocument(
            template_id=page.template_id,
            output_stem=f"{document.output_stem}_page_{page_index}",
            text_items=page.text_items,
            image_items=page.image_items,
        )
        page_report = validate_layout(config, page_document, minimum_font_size_pt)
        try:
            width_mm, height_mm = config.require_confirmed_size()
        except ValueError:
            width_mm = height_mm = None
        if width_mm is not None and height_mm is not None:
            page_sizes.setdefault((round(width_mm, 3), round(height_mm, 3)), []).append(page_index)
        for issue in page_report.issues:
            issue.details = {**issue.details, "page_index": page_index}
            issues.append(issue)
    if len(page_sizes) > 1:
        issues.append(
            ValidationIssue(
                code="MIXED_PAGE_SIZES",
                severity=Severity.WARNING,
                message="Paginated document contains multiple physical page sizes",
                details={"page_sizes_mm": {f"{width}x{height}": pages for (width, height), pages in page_sizes.items()}},
            )
        )
    return ValidationReport(
        valid_for_print=not any(issue.severity == Severity.ERROR for issue in issues),
        issues=issues,
    )
