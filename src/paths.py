from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def requirements(self) -> Path:
        return self.root / "requirements"

    @property
    def templates_raw(self) -> Path:
        return self.root / "templates" / "raw"

    @property
    def templates_corrected(self) -> Path:
        return self.root / "templates" / "corrected"

    @property
    def templates_preview(self) -> Path:
        return self.root / "templates" / "preview"

    @property
    def templates_config(self) -> Path:
        return self.root / "templates" / "config"

    @property
    def printers(self) -> Path:
        return self.root / "config" / "printers"

    @property
    def output_previews(self) -> Path:
        return self.root / "outputs" / "previews"

    @property
    def output_print(self) -> Path:
        return self.root / "outputs" / "print"

    @property
    def output_debug(self) -> Path:
        return self.root / "outputs" / "debug"

    @property
    def output_calibration(self) -> Path:
        return self.root / "outputs" / "calibration"

    @property
    def output_reports(self) -> Path:
        return self.root / "outputs" / "reports"

    def template_config(self, template_id: str) -> Path:
        return self.templates_config / f"{template_id}.json"

    def ensure(self) -> None:
        directories = [
            self.requirements / "school_rules",
            self.requirements / "internship_outline",
            self.requirements / "scoring_rules",
            self.root / "project_data",
            self.root / "config",
            self.printers,
            self.templates_raw,
            self.templates_corrected,
            self.templates_preview,
            self.templates_config,
            self.root / "days",
            self.root / "reports" / "drafts",
            self.root / "reports" / "approved",
            self.root / "reports" / "structured",
            self.output_previews,
            self.output_print,
            self.output_debug,
            self.output_calibration,
            self.output_reports,
            self.root / "tmp" / "pdfs",
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


def project_root() -> Path:
    """Return the repository root without depending on the caller's cwd."""
    return Path(__file__).resolve().parents[1]


def get_paths() -> ProjectPaths:
    paths = ProjectPaths(project_root())
    paths.ensure()
    return paths

