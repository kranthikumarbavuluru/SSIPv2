from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil


SOURCE_DIRECTORIES = (
    ".codex/skills",
    "agents",
    "apps",
    "assets",
    "config",
    "database",
    "docs",
    "models",
    "prompts",
    "scripts",
    "services",
    "ssip_agents",
    "ssip_dashboard",
    "tests",
    "tools",
    "ui",
    "utils",
)

ROOT_FILES = {
    ".gitignore",
    "AGENTS.md",
    "CODEX.md",
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-admin-review.txt",
    "requirements-extractor.txt",
    "requirements-public-dashboard.txt",
    "INSTALL_NIGHTLY_GOVERNANCE_TASK_v3_4_2_1.ps1",
    "REMOVE_NIGHTLY_AGENT_PREVIEW_TASK_v1.ps1",
    "RUN_AGENTS_NOW_v3_4_1_0.ps1",
    "RUN_GOVERNANCE_AGENTS_v3_4_2_1.ps1",
    "RUN_GOVERNED_AGENTS_PREVIEW_v1.ps1",
    "PUBLISH_APPROVED_AGENT_RUN_v1.ps1",
    "ROLLBACK_LAST_PUBLICATION_v1.ps1",
    "VALIDATE_GOVERNED_AGENT_RUN_v1.ps1",
}

DATA_FILES = {
    "data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv",
    "data/catalogue_preview/v3_3_2/catalogue_summary_v3_3_2.json",
    "data/audit/v2_8_1_catalogue_normalization/catalogue_normalization_plan_v2_8_1.csv",
    "data/audit/v2_8_1_catalogue_normalization/catalogue_normalization_summary_v2_8_1.json",
    "data/departments/dst/pilot_v1/dst_evidence_pilot_v1.db",
    "data/departments/dst/pilot_v1/dst_programme_hierarchy_v1.csv",
    "data/departments/dst/pilot_v1/dst_individual_calls_v1.csv",
    "data/departments/dst/pilot_v1/dst_startup_call_candidates_v1.csv",
    "data/departments/dst/pilot_v1/dst_curation_queue_v1.csv",
    "data/departments/dst/pilot_v1/dst_pilot_summary_v1.json",
    "data/departments/dst/pilot_v1/archive_v1/dst_historical_archive_manifest_v1.json",
    "data/departments/dst/pilot_v1/archive_v1/dst_historical_archive_qualified_v1.csv",
    "data/departments/dst/pilot_v1/archive_v1/dst_historical_archive_sample_v1.csv",
    "data/departments/dst/pilot_v1/archive_v1/dst_historical_archive_exceptions_v1.csv",
}

EXCLUDED_NAMES = {
    "__pycache__",
    ".pytest_cache",
    "public_dashboard_app_v2_9_before_v3_4_0_4a_20260710_173149.py",
    "public_dashboard_app_v2_9_before_v3_4_0_5_20260710_190834.py",
    "master_backlog_executor_v2_7_1.py.backup",
    "developer_console.py",
    "test_xml_warning_hotfix_v3_4_0_6a.py",  # duplicate lives under tests/
}

EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pyd", ".bak", ".backup", ".log"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_source_file(path: Path, root: Path) -> bool:
    rel = relative(path, root)
    if path.name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if any(part in EXCLUDED_NAMES for part in path.parts):
        return False
    if "backups" in path.parts:
        return False
    if rel.startswith("database/") and path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm"}:
        return False
    if rel.startswith("data/") and rel not in DATA_FILES:
        return False
    if rel in ROOT_FILES or rel in DATA_FILES:
        return True
    return any(rel == prefix or rel.startswith(prefix + "/") for prefix in SOURCE_DIRECTORIES)


def quarantine_reason(rel: str) -> str:
    parts = set(Path(rel).parts)
    name = Path(rel).name
    suffix = Path(rel).suffix.lower()
    if ".venv" in parts or "venv" in parts:
        return "VIRTUAL_ENVIRONMENT"
    if "__pycache__" in parts or suffix in {".pyc", ".pyo", ".pyd"}:
        return "COMPILED_CACHE"
    if ".pytest_cache" in parts or name.startswith(".test_tmp"):
        return "TEST_CACHE"
    if "backups" in parts or suffix in {".bak", ".backup"}:
        return "BACKUP"
    if "logs" in parts or suffix == ".log":
        return "LOG"
    if "outputs" in parts:
        return "GENERATED_OUTPUT"
    if rel.startswith("database/") and suffix in {".db", ".sqlite", ".sqlite3"}:
        return "OPERATIONAL_DATABASE"
    if suffix in {".db-wal", ".db-shm"}:
        return "DATABASE_RUNTIME_FILE"
    if rel.startswith("data/"):
        return "UNSELECTED_GENERATED_OR_RAW_DATA"
    if name.startswith("README_v") or name.startswith("requirements-v"):
        return "LEGACY_VERSION_DOCUMENT"
    if name.startswith(("PACKAGE_VALIDATION", "PACKAGE_MANIFEST", "SHA256", "CHECKSUM")):
        return "LEGACY_PACKAGE_ARTIFACT"
    if "_before_" in name:
        return "EMBEDDED_SOURCE_BACKUP"
    return "NOT_IN_GITHUB_ALLOWLIST"


def build_export(root: Path, target: Path, manifest_path: Path) -> dict:
    root = root.resolve()
    target = target.resolve()
    manifest_path = manifest_path.resolve()
    if root == target or root not in target.parents:
        raise ValueError("Export target must be a new folder inside the project root.")
    if target.exists():
        raise FileExistsError(f"Export target already exists: {target}")

    all_files = [
        path for path in root.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and "github_export" not in path.parts
    ]
    selected = sorted((path for path in all_files if is_source_file(path, root)), key=lambda p: relative(p, root))
    target.mkdir(parents=True)
    exported = []
    for source in selected:
        rel = relative(source, root)
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        exported.append({"path": rel, "size": source.stat().st_size, "sha256": sha256(source)})

    manifest = {
        "export_version": "1.0.0",
        "source_root": ".",
        "target_purpose": "clean GitHub repository export",
        "file_count": len(exported),
        "total_bytes": sum(item["size"] for item in exported),
        "files": exported,
    }
    (target / "GITHUB_EXPORT_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    selected_paths = {item["path"] for item in exported}
    quarantine = []
    for path in sorted(all_files, key=lambda p: relative(p, root)):
        rel = relative(path, root)
        if rel in selected_paths:
            continue
        try:
            size = path.stat().st_size
            digest = sha256(path)
        except OSError:
            size = -1
            digest = "UNREADABLE"
        quarantine.append({
            "path": rel,
            "size": size,
            "sha256": digest,
            "reason": quarantine_reason(rel),
        })
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("path", "size", "sha256", "reason"))
        writer.writeheader()
        writer.writerows(quarantine)

    return {
        "target": str(target),
        "exported_files": len(exported),
        "exported_bytes": manifest["total_bytes"],
        "quarantine_candidates": len(quarantine),
        "quarantine_manifest": str(manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic clean SSIP GitHub export.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--target", type=Path, default=Path("github_export/SSIP"))
    parser.add_argument("--quarantine-manifest", type=Path, default=Path("github_export/SSIP_quarantine_manifest.csv"))
    args = parser.parse_args()
    root = args.project_root.resolve()
    target = args.target if args.target.is_absolute() else root / args.target
    quarantine_manifest = (
        args.quarantine_manifest
        if args.quarantine_manifest.is_absolute()
        else root / args.quarantine_manifest
    )
    print(json.dumps(build_export(root, target, quarantine_manifest), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
