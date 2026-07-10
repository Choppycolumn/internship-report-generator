from __future__ import annotations

from pathlib import Path

from .models import LayoutDocument, PaginatedDocument, PrinterCalibration, TemplateConfig
from .paths import ProjectPaths
from .pdf_renderer import PdfRenderer
from .storage import save_json_atomic
from .validators import validate_layout, validate_paginated_layout


class ExportManager:
    def __init__(self, paths: ProjectPaths):
        self.paths = paths
        self.renderer = PdfRenderer(paths)

    def export_three_pdfs(
        self,
        config: TemplateConfig,
        document: LayoutDocument,
        calibration: PrinterCalibration | None = None,
    ) -> dict[str, Path | None]:
        validation = validate_layout(config, document)
        report_path = self.paths.output_reports / f"{document.output_stem}_validation.json"
        save_json_atomic(report_path, validation)

        preview = self.paths.output_previews / f"{document.output_stem}_preview.pdf"
        debug = self.paths.output_debug / f"{document.output_stem}_layout_debug.pdf"
        self.renderer.render(config, document, preview, "preview", calibration)
        self.renderer.render(config, document, debug, "debug", calibration)

        formal: Path | None = None
        if validation.valid_for_print:
            formal = self.paths.output_print / f"{document.output_stem}_print.pdf"
            self.renderer.render(config, document, formal, "print", calibration)
        return {
            "preview": preview,
            "print": formal,
            "debug": debug,
            "validation_report": report_path,
        }

    def export_paginated_three_pdfs(
        self,
        configs: dict[str, TemplateConfig],
        document: PaginatedDocument,
        calibrations: dict[str, PrinterCalibration] | None = None,
    ) -> dict[str, Path | None]:
        validation = validate_paginated_layout(configs, document)
        report_path = self.paths.output_reports / f"{document.output_stem}_validation.json"
        save_json_atomic(report_path, validation)
        preview = self.paths.output_previews / f"{document.output_stem}_preview.pdf"
        debug = self.paths.output_debug / f"{document.output_stem}_layout_debug.pdf"
        self.renderer.render_paginated(
            configs, document, preview, "preview", calibrations
        )
        self.renderer.render_paginated(configs, document, debug, "debug", calibrations)
        formal: Path | None = None
        if validation.valid_for_print:
            formal = self.paths.output_print / f"{document.output_stem}_print.pdf"
            self.renderer.render_paginated(
                configs, document, formal, "print", calibrations
            )
        return {
            "preview": preview,
            "print": formal,
            "debug": debug,
            "validation_report": report_path,
        }
