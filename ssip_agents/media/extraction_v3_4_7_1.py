from __future__ import annotations

"""OCR, visual preparation, QR and link extraction for SSIP media.

The extraction stage is deliberately dependency-tolerant.  Optional OCR and
QR engines are used when installed; otherwise the output records an explicit
``UNAVAILABLE`` status and a warning instead of fabricating text or URLs.
Raw assets are never modified.  Derived images, text and field-level evidence
are written below the dated media run directory.
"""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .intake_v3_4_7_0 import MediaIntakePaths, parse_ingest_date


MEDIA_EXTRACTION_SCHEMA_VERSION = "3.4.7.1"
EXTRACTION_REVISION = "media-extractor-qr-barcode-v1"
_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
_TRAILING_URL_CHARS = ".,;:!?)]}>'\""
_AMOUNT_RE = re.compile(
    r"(?P<currency>₹|rs\.?|inr|usd|\$)?\s*"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>crore|cr|lakh|lac|million|mn|thousand|k)?",
    re.IGNORECASE,
)
_UNIT_MULTIPLIER = {
    "crore": 10_000_000,
    "cr": 10_000_000,
    "lakh": 100_000,
    "lac": 100_000,
    "million": 1_000_000,
    "mn": 1_000_000,
    "thousand": 1_000,
    "k": 1_000,
}


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    """One field-level observation and its provenance."""

    evidence_id: str
    asset_id: str
    field_name: str
    value: str
    source_kind: str
    confidence: float
    locator: str
    excerpt: str = ""
    extraction_status: str = "EXTRACTED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8", newline="")
    temporary.replace(path)


def _jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    _atomic_write(
        path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _asset_path(project_root: Path, relative_path: str) -> Path:
    root = project_root.resolve()
    candidate = (root / relative_path).resolve()
    if root not in candidate.parents:
        raise ValueError("Media asset path escapes the project root.")
    return candidate


def detect_language(text: str) -> tuple[str, float]:
    """Return a conservative language label from available script evidence."""

    text = str(text or "")
    if not text.strip():
        return "und", 0.0
    try:
        from langdetect import detect_langs  # type: ignore

        detected = detect_langs(text)
        if detected:
            top = detected[0]
            return str(top.lang), float(top.prob)
    except (ImportError, ValueError, RuntimeError):
        pass
    scripts = {
        "hi": (0x0900, 0x097F),
        "te": (0x0C00, 0x0C7F),
        "ta": (0x0B80, 0x0BFF),
        "kn": (0x0C80, 0x0CFF),
        "ml": (0x0D00, 0x0D7F),
        "bn": (0x0980, 0x09FF),
    }
    letters = [char for char in text if char.isalpha()]
    for language, (start, end) in scripts.items():
        count = sum(start <= ord(char) <= end for char in letters)
        if count:
            return language, min(0.99, 0.55 + count / max(len(letters), 1))
    return "en", min(0.9, 0.55 + len(letters) / max(len(text), 1) * 0.35)


def _image_preprocess(asset_path: Path, output_path: Path) -> tuple[str, str]:
    try:
        from PIL import Image, ImageOps  # type: ignore
    except ImportError:
        return "", "PILLOW_UNAVAILABLE"
    try:
        with Image.open(asset_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image = ImageOps.autocontrast(ImageOps.grayscale(image))
            if max(image.size) < 1800:
                scale = min(2.0, 1800 / max(image.size))
                image = image.resize(
                    (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path, format="PNG", optimize=True)
        return str(output_path), "PREPROCESSED"
    except (OSError, ValueError) as exc:
        return "", f"PREPROCESS_ERROR:{exc}"


def _pdf_text(asset_path: Path) -> tuple[str, list[str], str]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return "", [], "PYPDF_UNAVAILABLE"
    try:
        reader = PdfReader(str(asset_path))
        pages: list[str] = []
        links: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            pages.append(page.extract_text() or "")
            for annotation in page.get("/Annots", []) or []:
                target = annotation.get_object().get("/A", {})
                uri = str(target.get("/URI", "")).strip()
                if uri:
                    links.append(uri)
        return "\n".join(pages), links, "PDF_TEXT_EXTRACTED"
    except Exception as exc:  # pypdf surfaces malformed PDF errors variably.
        return "", [], f"PDF_TEXT_ERROR:{exc}"


def _ocr_image(image_path: Path) -> tuple[str, str]:
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return "", "OCR_ENGINE_UNAVAILABLE"
    try:
        with Image.open(image_path) as image:
            return str(pytesseract.image_to_string(image) or "").strip(), "OCR_EXTRACTED"
    except Exception as exc:  # OCR engines can fail on missing binaries/configuration.
        return "", f"OCR_ERROR:{exc}"


def _qr_image(image_path: Path) -> tuple[list[str], str]:
    try:
        import cv2  # type: ignore

        image = cv2.imread(str(image_path))
        if image is None:
            return [], "QR_IMAGE_UNREADABLE"
        detector = cv2.QRCodeDetector()
        values, _, _ = detector.detectAndDecodeMulti(image)
        if values:
            return [str(value).strip() for value in values if str(value).strip()], "QR_EXTRACTED"
        value, _, _ = detector.detectAndDecode(image)
        return ([value.strip()] if value and value.strip() else []), "QR_SCAN_COMPLETE"
    except ImportError:
        pass
    try:
        from pyzbar.pyzbar import decode  # type: ignore
        from PIL import Image  # type: ignore

        with Image.open(image_path) as image:
            values = [item.data.decode("utf-8", errors="replace").strip() for item in decode(image)]
        return [value for value in values if value], "QR_EXTRACTED" if values else "QR_SCAN_COMPLETE"
    except ImportError:
        return [], "QR_ENGINE_UNAVAILABLE"
    except Exception as exc:
        return [], f"QR_ERROR:{exc}"


def _barcode_image(image_path: Path) -> tuple[list[dict[str, str]], str]:
    """Decode non-QR barcodes when pyzbar/libzbar is available."""

    try:
        from pyzbar.pyzbar import decode  # type: ignore
        from PIL import Image  # type: ignore

        with Image.open(image_path) as image:
            values = [
                {
                    "value": item.data.decode("utf-8", errors="replace").strip(),
                    "symbology": str(getattr(item, "type", "UNKNOWN")),
                }
                for item in decode(image)
            ]
        values = [item for item in values if item["value"]]
        return values, "BARCODE_EXTRACTED" if values else "BARCODE_SCAN_COMPLETE"
    except ImportError:
        return [], "BARCODE_ENGINE_UNAVAILABLE"
    except Exception as exc:
        return [], f"BARCODE_ERROR:{exc}"


def extract_links(text: str, embedded_links: Iterable[str] = ()) -> list[str]:
    values: list[str] = []
    for candidate in list(_URL_RE.findall(str(text or ""))) + list(embedded_links):
        value = str(candidate).strip().rstrip(_TRAILING_URL_CHARS)
        if value.startswith("https://") or value.startswith("http://"):
            if value not in values:
                values.append(value)
    return values


def parse_funding_amounts(text: str) -> dict[str, Any]:
    """Parse explicit money mentions into nullable min/max fields.

    Values are accepted only when a currency marker or scale unit is present,
    which prevents dates and phone numbers from being mistaken for funding.
    A single unqualified amount is retained as a recorded amount with a
    maximum interpretation only when the surrounding text says ``up to`` or
    ``maximum``.  Missing fields remain ``None``.
    """

    source = " ".join(str(text or "").split())
    matches: list[dict[str, Any]] = []
    for match in _AMOUNT_RE.finditer(source):
        currency = str(match.group("currency") or "").casefold()
        unit = str(match.group("unit") or "").casefold()
        if not currency and not unit:
            continue
        try:
            number = float(match.group("number").replace(",", ""))
        except ValueError:
            continue
        value = int(round(number * _UNIT_MULTIPLIER.get(unit, 1)))
        if value <= 0:
            continue
        start = max(0, match.start() - 32)
        prefix = source[start : match.start()].casefold()
        if any(
            token in prefix
            for token in (
                "turnover",
                "revenue",
                "annual sales",
                "salary",
                "stipend",
                "application fee",
                "registration fee",
                "valuation",
            )
        ):
            continue
        context = source[start : match.end() + 20].casefold()
        matches.append({
            "value": value,
            "currency": "INR" if currency in {"₹", "rs", "rs.", "inr", ""} else currency.upper(),
            "mention": match.group(0).strip(),
            "context": context,
            "start": match.start(),
        })
    if not matches:
        return {
            "funding_minimum": None,
            "funding_maximum": None,
            "funding_currency": "",
            "funding_amount_status": "NOT_STATED",
            "funding_amount_optional": True,
            "funding_mentions": [],
        }
    minimum: int | None = None
    maximum: int | None = None
    range_values: list[int] = []
    for left, right in zip(matches, matches[1:]):
        between = source[left["start"] + len(left["mention"]) : right["start"]].casefold()
        range_tail = between[-32:]
        if re.search(r"(?<!up )\bto\b|[-–—]\s*$", range_tail):
            range_values.extend((left["value"], right["value"]))
    for index, item in enumerate(matches):
        context = item["context"]
        before = source[max(0, item["start"] - 28) : item["start"]].casefold()
        if any(token in context for token in ("up to", "upto", "maximum", "max ")):
            maximum = max(maximum or 0, item["value"])
        elif any(token in before for token in ("from ", "minimum", "min ")):
            minimum = min(minimum or item["value"], item["value"])
        elif index == 0 and len(matches) == 1:
            # A standalone marked amount is a recorded amount, not a made-up
            # lower bound. Treating it as maximum keeps the dashboard useful.
            maximum = item["value"]
    if range_values:
        minimum = min(range_values)
        maximum = max(range_values)
    if minimum is None and maximum is not None and len(matches) > 1:
        lower_values = [item["value"] for item in matches if item["value"] != maximum]
        minimum = min(lower_values) if lower_values else None
    currency = next((item["currency"] for item in matches if item["currency"]), "INR")
    return {
        "funding_minimum": minimum,
        "funding_maximum": maximum,
        "funding_currency": currency,
        "funding_amount_status": "RECORDED",
        "funding_amount_optional": True,
        "funding_mentions": [
            {"mention": item["mention"], "value": item["value"], "currency": item["currency"], "context": item["context"]}
            for item in matches
        ],
    }


def _evidence_id(asset_id: str, field_name: str, value: str, index: int = 0) -> str:
    seed = f"{asset_id}:{field_name}:{index}:{value}".encode("utf-8")
    return f"evidence-{hashlib.sha256(seed).hexdigest()[:20]}"


def extract_media_asset(
    project_root: Path,
    asset: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Extract OCR, QR, links and field evidence for one registered asset."""

    asset_id = str(asset.get("asset_id", "")).strip()
    source_path = _asset_path(project_root, str(asset.get("relative_path", "")))
    suffix = source_path.suffix.casefold()
    preprocessed_path = output_dir / "preprocessed" / f"{asset_id}.png"
    warnings: list[str] = []
    text = ""
    embedded_links: list[str] = []
    preprocess_status = "NOT_APPLICABLE"
    if suffix == ".pdf":
        text, embedded_links, preprocess_status = _pdf_text(source_path)
        if preprocess_status != "PDF_TEXT_EXTRACTED":
            warnings.append(preprocess_status)
    else:
        preprocessed, preprocess_status = _image_preprocess(source_path, preprocessed_path)
        if preprocessed:
            text, ocr_status = _ocr_image(Path(preprocessed))
        else:
            ocr_status = "OCR_INPUT_UNAVAILABLE"
        if not text and ocr_status != "OCR_EXTRACTED":
            warnings.append(ocr_status)

    language, language_confidence = detect_language(text)
    funding = parse_funding_amounts(text)
    links = extract_links(text, embedded_links)
    qr_values: list[str] = []
    qr_status = "QR_NOT_APPLICABLE"
    barcodes: list[dict[str, str]] = []
    barcode_status = "BARCODE_NOT_APPLICABLE"
    if suffix != ".pdf" and preprocessed_path.exists():
        qr_values, qr_status = _qr_image(preprocessed_path)
        if qr_status not in {"QR_EXTRACTED", "QR_SCAN_COMPLETE"}:
            warnings.append(qr_status)
        barcodes, barcode_status = _barcode_image(preprocessed_path)
        if barcode_status not in {"BARCODE_EXTRACTED", "BARCODE_SCAN_COMPLETE"}:
            warnings.append(barcode_status)
    elif suffix != ".pdf":
        qr_status = "QR_INPUT_UNAVAILABLE"
        warnings.append(qr_status)

    evidence: list[dict[str, Any]] = []
    if text:
        evidence.append(
            FieldEvidence(
                evidence_id=_evidence_id(asset_id, "raw_text", text),
                asset_id=asset_id,
                field_name="raw_text",
                value=text,
                source_kind="PDF_TEXT" if suffix == ".pdf" else "OCR",
                confidence=0.72 if suffix == ".pdf" else 0.68,
                locator="document-text",
                excerpt=text[:500],
            ).to_dict()
        )
    for index, link in enumerate(links):
        evidence.append(
            FieldEvidence(
                evidence_id=_evidence_id(asset_id, "official_link", link, index),
                asset_id=asset_id,
                field_name="official_link",
                value=link,
                source_kind="EMBEDDED_LINK" if link in embedded_links else "PRINTED_LINK",
                confidence=0.98 if link in embedded_links else 0.82,
                locator="document-link",
            ).to_dict()
        )
    for index, mention in enumerate(funding["funding_mentions"]):
        evidence.append(
            FieldEvidence(
                evidence_id=_evidence_id(asset_id, "funding_amount", str(mention["mention"]), index),
                asset_id=asset_id,
                field_name="funding_amount",
                value=str(mention["value"]),
                source_kind="OCR" if suffix != ".pdf" else "PDF_TEXT",
                confidence=0.84,
                locator="funding-context",
                excerpt=str(mention["context"]),
            ).to_dict()
        )
    for index, qr_value in enumerate(qr_values):
        evidence.append(
            FieldEvidence(
                evidence_id=_evidence_id(asset_id, "qr_value", qr_value, index),
                asset_id=asset_id,
                field_name="qr_value",
                value=qr_value,
                source_kind="QR",
                confidence=0.99,
                locator="qr-detector",
            ).to_dict()
        )
        if qr_value.startswith("http://") or qr_value.startswith("https://"):
            links.append(qr_value)
    for index, barcode in enumerate(barcodes):
        value = str(barcode.get("value", "")).strip()
        if not value:
            continue
        evidence.append(
            FieldEvidence(
                evidence_id=_evidence_id(asset_id, "barcode_value", value, index),
                asset_id=asset_id,
                field_name="barcode_value",
                value=value,
                source_kind="BARCODE",
                confidence=0.98,
                locator=str(barcode.get("symbology", "UNKNOWN")),
            ).to_dict()
        )

    return {
        "schema_version": MEDIA_EXTRACTION_SCHEMA_VERSION,
        "extractor_revision": EXTRACTION_REVISION,
        "asset_id": asset_id,
        "ingest_date": str(asset.get("ingest_date", "")),
        "relative_path": str(asset.get("relative_path", "")),
        "source_sha256": str(asset.get("sha256", "")),
        "preprocessed_path": str(preprocessed_path.relative_to(project_root)) if preprocessed_path.exists() else "",
        "preprocess_status": preprocess_status,
        "ocr_status": "OCR_EXTRACTED" if text and suffix != ".pdf" else ("PDF_TEXT_EXTRACTED" if text else "NO_TEXT"),
        "raw_text": text,
        "language": language,
        "language_confidence": language_confidence,
        "funding_minimum": funding["funding_minimum"],
        "funding_maximum": funding["funding_maximum"],
        "funding_currency": funding["funding_currency"],
        "funding_amount_status": funding["funding_amount_status"],
        "funding_amount_optional": funding["funding_amount_optional"],
        "funding_mentions": funding["funding_mentions"],
        "qr_status": qr_status,
        "qr_values": list(dict.fromkeys(qr_values)),
        "barcode_status": barcode_status,
        "barcodes": barcodes,
        "links": list(dict.fromkeys(links)),
        "warnings": sorted(set(warnings)),
        "evidence_ids": [row["evidence_id"] for row in evidence],
        "evidence": evidence,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


def extract_media_batch(project_root: Path, ingest_date: str | date | None = None) -> dict[str, Any]:
    """Run extraction for a dated intake manifest incrementally."""

    root = project_root.resolve()
    parsed_date = parse_ingest_date(ingest_date)
    paths = MediaIntakePaths(root)
    paths.ensure_batch_layout(parsed_date)
    batch_dir = paths.batch_run(parsed_date)
    asset_manifest = batch_dir / "asset_manifest.jsonl"
    extraction_manifest = batch_dir / "extraction_manifest.jsonl"
    evidence_path = batch_dir / "field_evidence.jsonl"
    rows = _read_jsonl(asset_manifest)
    previous = {row.get("asset_id"): row for row in _read_jsonl(extraction_manifest)}
    extracted: list[dict[str, Any]] = []
    skipped = 0
    for asset in rows:
        if asset.get("status") != "READY_FOR_EXTRACTION":
            continue
        asset_id = str(asset.get("asset_id", ""))
        if (
            previous.get(asset_id, {}).get("source_sha256") == asset.get("sha256")
            and previous.get(asset_id, {}).get("schema_version") == MEDIA_EXTRACTION_SCHEMA_VERSION
            and previous.get(asset_id, {}).get("extractor_revision") == EXTRACTION_REVISION
        ):
            extracted.append(previous[asset_id])
            skipped += 1
            continue
        extracted.append(extract_media_asset(root, asset, batch_dir))
    extracted.sort(key=lambda row: row.get("asset_id", ""))
    _jsonl(extraction_manifest, extracted)
    evidence = [item for row in extracted for item in row.get("evidence", [])]
    _jsonl(evidence_path, evidence)
    warning_count = sum(len(row.get("warnings", [])) for row in extracted)
    report = {
        "schema_version": MEDIA_EXTRACTION_SCHEMA_VERSION,
        "extractor_revision": EXTRACTION_REVISION,
        "run_id": f"media-extraction-{parsed_date.strftime('%Y%m%d')}",
        "ingest_date": parsed_date.isoformat(),
        "asset_count": len(rows),
        "extracted_count": len(extracted),
        "skipped_unchanged_count": skipped,
        "evidence_count": len(evidence),
        "qr_decoded_count": sum(bool(row.get("qr_values")) for row in extracted),
        "barcode_decoded_count": sum(bool(row.get("barcodes")) for row in extracted),
        "funding_recorded_count": sum(row.get("funding_amount_status") == "RECORDED" for row in extracted),
        "link_count": sum(len(row.get("links", [])) for row in extracted),
        "warning_count": warning_count,
        "ocr_engine": "optional:pytesseract",
        "qr_engine": "optional:opencv-or-pyzbar",
        "manifest_path": extraction_manifest.relative_to(root).as_posix(),
        "evidence_path": evidence_path.relative_to(root).as_posix(),
        "database_modified": False,
    }
    _atomic_write(batch_dir / "extraction_report.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


__all__ = [
    "FieldEvidence",
    "MEDIA_EXTRACTION_SCHEMA_VERSION",
    "detect_language",
    "extract_links",
    "extract_media_asset",
    "extract_media_batch",
]
