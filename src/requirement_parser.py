from __future__ import annotations

from pathlib import Path

from .paths import ProjectPaths
from .storage import copy_without_overwrite, load_json, save_json_atomic, sha256_file, utc_now_iso


ALLOWED_CATEGORIES = {"school_rules", "internship_outline", "scoring_rules"}


class RequirementImporter:
    def __init__(self, paths: ProjectPaths):
        self.paths = paths

    def import_file(self, source: Path, category: str = "school_rules") -> dict:
        if category not in ALLOWED_CATEGORIES:
            raise ValueError(f"Unsupported requirement category: {category}")
        target = copy_without_overwrite(source, self.paths.requirements / category)
        manifest_path = self.paths.requirements / "manifest.json"
        manifest = load_json(manifest_path, default={"schema_version": 1, "documents": []})
        digest = sha256_file(target)
        relative = target.relative_to(self.paths.root).as_posix()
        existing = next(
            (item for item in manifest["documents"] if item.get("sha256") == digest), None
        )
        if existing:
            return existing
        record = {
            "id": f"requirement_{digest[:12]}",
            "category": category,
            "classification": "school_requirement_only",
            "may_be_used_as_template": False,
            # Keep manifests portable and safe to share. The absolute source path
            # may contain a Windows account name, cloud folder, or chat cache ID.
            "source_file": source.name,
            "stored_file": relative,
            "sha256": digest,
            "imported_at": utc_now_iso(),
        }
        manifest["documents"].append(record)
        save_json_atomic(manifest_path, manifest)
        return record
