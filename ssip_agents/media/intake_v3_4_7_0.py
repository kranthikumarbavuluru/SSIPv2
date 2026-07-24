from __future__ import annotations

"""Non-destructive media intake foundation for SSIP v3.4.7.0.

This module deliberately stops at asset registration. OCR, QR decoding,
entity extraction, department mapping and publication are later stages. The
input files are never modified and no operational database is opened.
"""

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


MEDIA_SCHEMA_VERSION = "3.4.7.0"
SUPPORTED_SUFFIXES = frozenset(
    {
        ".bmp",
        ".gif",
        ".heic",
        ".heif",
        ".jpeg",
        ".jpg",
        ".pdf",
        ".png",
        ".tif",
        ".tiff",
        ".webp",
    }
)
_MIME_OVERRIDES = {
    ".heic": "image/heic",
    ".heif": "image/heif",
}


def parse_ingest_date(value: str | date | None) -> date:
    """Return a strict ISO ingest date, defaulting to the local run date."""

    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Ingest date must be YYYY-MM-DD: {value!r}") from exc


def _utc_iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _mime_type(path: Path) -> str:
    return _MIME_OVERRIDES.get(path.suffix.casefold()) or mimetypes.guess_type(
        path.name
    )[0] or "application/octet-stream"


def _relative_path(path: Path, project_root: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


@dataclass(frozen=True, slots=True)
class MediaIntakePaths:
    """Date-based paths used by the media intake foundation."""

    project_root: Path

    @property
    def media_root(self) -> Path:
        return self.project_root / "media"

    @property
    def inbox_root(self) -> Path:
        return self.media_root / "inbox"

    @property
    def processed_root(self) -> Path:
        return self.media_root / "processed"

    @property
    def quarantine_root(self) -> Path:
        return self.media_root / "quarantine"

    @property
    def runs_root(self) -> Path:
        return self.project_root / "data" / "media_runs"

    def batch_inbox(self, ingest_date: str | date | None = None) -> Path:
        return self.inbox_root / parse_ingest_date(ingest_date).isoformat()

    def batch_processed(self, ingest_date: str | date | None = None) -> Path:
        return self.processed_root / parse_ingest_date(ingest_date).isoformat()

    def batch_quarantine(self, ingest_date: str | date | None = None) -> Path:
        return self.quarantine_root / parse_ingest_date(ingest_date).isoformat()

    def batch_run(self, ingest_date: str | date | None = None) -> Path:
        return self.runs_root / parse_ingest_date(ingest_date).isoformat()

    def ensure_batch_layout(self, ingest_date: str | date | None = None) -> None:
        for path in (
            self.batch_inbox(ingest_date),
            self.batch_processed(ingest_date),
            self.batch_quarantine(ingest_date),
            self.batch_run(ingest_date),
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class MediaAsset:
    """Stable, portable description of one input file."""

    asset_id: str
    ingest_date: str
    relative_path: str
    file_name: str
    extension: str
    mime_type: str
    size_bytes: int
    sha256: str
    modified_at: str
    status: str
    duplicate_of: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _manifest_paths(paths: MediaIntakePaths, ingest_date: date) -> tuple[Path, Path]:
    batch_dir = paths.batch_run(ingest_date)
    return batch_dir / "asset_manifest.jsonl", batch_dir / "run_report.json"


def _historical_hashes(
    paths: MediaIntakePaths,
    current_batch: Path,
) -> dict[str, str]:
    """Load prior hashes without treating a same-day rerun as a duplicate."""

    output: dict[str, str] = {}
    if not paths.runs_root.exists():
        return output
    for manifest in sorted(paths.runs_root.glob("*/asset_manifest.jsonl")):
        if manifest.parent.resolve() == current_batch.resolve():
            continue
        try:
            lines = manifest.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            digest = str(payload.get("sha256", "")).strip()
            asset_id = str(payload.get("asset_id", "")).strip()
            if digest and asset_id:
                output.setdefault(digest, asset_id)
    return output


def _iter_input_files(inbox: Path) -> Iterable[Path]:
    if not inbox.exists():
        return ()
    inbox_root = inbox.resolve()
    output: list[Path] = []
    for path in sorted(inbox.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            if path.resolve().is_relative_to(inbox_root):
                output.append(path)
        except (OSError, ValueError):
            continue
    return output


def _asset_for_file(
    path: Path,
    *,
    project_root: Path,
    ingest_date: date,
    seen_hashes: dict[str, str],
    historical_hashes: dict[str, str],
) -> MediaAsset:
    relative_path = _relative_path(path, project_root)
    extension = path.suffix.casefold()
    try:
        stat = path.stat()
        digest = _sha256_file(path)
        size_bytes = stat.st_size
        modified_at = _utc_iso_from_timestamp(stat.st_mtime)
        duplicate_of = seen_hashes.get(digest) or historical_hashes.get(digest) or ""
        if extension not in SUPPORTED_SUFFIXES:
            status = "UNSUPPORTED_MEDIA"
        elif duplicate_of:
            status = "DUPLICATE"
        else:
            status = "READY_FOR_EXTRACTION"
        identity_seed = f"{ingest_date.isoformat()}:{relative_path}".encode("utf-8")
        asset_id = f"asset-{hashlib.sha256(identity_seed).hexdigest()[:20]}"
        seen_hashes.setdefault(digest, asset_id)
        return MediaAsset(
            asset_id=asset_id,
            ingest_date=ingest_date.isoformat(),
            relative_path=relative_path,
            file_name=path.name,
            extension=extension,
            mime_type=_mime_type(path),
            size_bytes=size_bytes,
            sha256=digest,
            modified_at=modified_at,
            status=status,
            duplicate_of=duplicate_of,
        )
    except (OSError, ValueError) as exc:
        fallback = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()
        return MediaAsset(
            asset_id=f"asset-{fallback[:20]}",
            ingest_date=ingest_date.isoformat(),
            relative_path=relative_path,
            file_name=path.name,
            extension=extension,
            mime_type=_mime_type(path),
            size_bytes=0,
            sha256="",
            modified_at="",
            status="READ_ERROR",
            error=str(exc),
        )


def scan_media_batch(
    project_root: Path,
    ingest_date: str | date | None = None,
) -> dict[str, Any]:
    """Register one dated inbox and write an idempotent manifest/report.

    The scan only reads files from ``media/inbox/YYYY-MM-DD`` and writes
    generated metadata under ``data/media_runs/YYYY-MM-DD``. It never moves,
    edits or deletes the input assets and never opens the SSIP database.
    """

    root = project_root.resolve()
    parsed_date = parse_ingest_date(ingest_date)
    paths = MediaIntakePaths(root)
    paths.ensure_batch_layout(parsed_date)
    inbox = paths.batch_inbox(parsed_date)
    batch_dir = paths.batch_run(parsed_date)
    manifest_path, report_path = _manifest_paths(paths, parsed_date)
    historical_hashes = _historical_hashes(paths, batch_dir)
    seen_hashes: dict[str, str] = {}
    assets = [
        _asset_for_file(
            path,
            project_root=root,
            ingest_date=parsed_date,
            seen_hashes=seen_hashes,
            historical_hashes=historical_hashes,
        )
        for path in _iter_input_files(inbox)
    ]
    assets.sort(key=lambda item: item.relative_path.casefold())
    manifest = "".join(
        json.dumps(asset.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        for asset in assets
    )
    _atomic_write_text(manifest_path, manifest)

    status_counts = Counter(asset.status for asset in assets)
    supported = [
        asset
        for asset in assets
        if asset.extension in SUPPORTED_SUFFIXES and asset.status != "READ_ERROR"
    ]
    report: dict[str, Any] = {
        "schema_version": MEDIA_SCHEMA_VERSION,
        "run_id": f"media-{parsed_date.strftime('%Y%m%d')}",
        "ingest_date": parsed_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_directory": _relative_path(inbox, root),
        "manifest_path": _relative_path(manifest_path, root),
        "asset_count": len(assets),
        "supported_asset_count": len(supported),
        "unique_supported_asset_count": sum(
            1 for asset in supported if asset.status == "READY_FOR_EXTRACTION"
        ),
        "duplicate_count": status_counts.get("DUPLICATE", 0),
        "unsupported_count": status_counts.get("UNSUPPORTED_MEDIA", 0),
        "read_error_count": status_counts.get("READ_ERROR", 0),
        "status_counts": dict(sorted(status_counts.items())),
        "hash_algorithm": "sha256",
        "next_stage": "OCR, QR and visual extraction",
        "database_modified": False,
    }
    _atomic_write_text(
        report_path,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return report
