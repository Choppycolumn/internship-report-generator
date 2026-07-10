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
            + config.table_regions
            + config.signature_regions
        )
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
        for issue in page_report.issues:
            issue.details = {**issue.details, "page_index": page_index}
            issues.append(issue)
    return ValidationReport(
        valid_for_print=not any(issue.severity == Severity.ERROR for issue in issues),
        issues=issues,
    )
