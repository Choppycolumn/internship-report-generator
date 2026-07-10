from __future__ import annotations

from pathlib import Path

from src.requirement_parser import RequirementImporter
from src.storage import load_json


def test_requirement_manifest_does_not_store_absolute_source_path(
    project_paths, tmp_path: Path
) -> None:
    source_dir = tmp_path / "private" / "chat-cache"
    source_dir.mkdir(parents=True)
    source = source_dir / "school-rules.jpg"
    source.write_bytes(b"synthetic requirement material")

    record = RequirementImporter(project_paths).import_file(source, "school_rules")
    manifest = load_json(project_paths.requirements / "manifest.json")

    assert record["source_file"] == source.name
    assert str(source_dir) not in str(manifest)
    assert record["stored_file"] == "requirements/school_rules/school-rules.jpg"
