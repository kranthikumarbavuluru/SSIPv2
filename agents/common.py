from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

COLUMN_ALIASES = {
    "master_id": ["master_id", "scheme_master_id", "id", "record_id"],
    "name": ["canonical_name", "scheme_name", "programme_name", "name", "title"],
    "objective": ["objective", "objectives", "description", "summary", "scheme_objective"],
    "eligibility": ["eligibility", "eligible_beneficiaries", "who_can_apply"],
    "benefits": ["benefits", "benefit", "support", "funding_details"],
    "sector": ["primary_sector", "sector", "sectors", "sector_name"],
    "secondary_sectors": ["secondary_sectors", "additional_sectors"],
    "official_url": ["official_url", "official_page", "source_url", "final_url", "best_available_url"],
    "application_url": ["application_url", "apply_url", "application_portal"],
    "department": ["department", "source", "agency"],
    "ministry": ["ministry", "ministry_name"],
    "support_type": ["support_type", "grant_support_type", "scheme_type"],
    "startup_stage": ["startup_stage", "stage"],
    "record_type": ["record_type", "master_type", "programme_type"],
    "publication_status": ["publication_status", "database_status", "status"],
}

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()

def lower(value: Any) -> str:
    return norm(value).casefold()

def find_column(fieldnames: Iterable[str], canonical: str) -> str | None:
    field_map = {f.casefold(): f for f in fieldnames}
    for alias in COLUMN_ALIASES[canonical]:
        if alias.casefold() in field_map:
            return field_map[alias.casefold()]
    return None

def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])

def atomic_write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

def content_hash(*parts: Any) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(norm(part).encode("utf-8", errors="ignore"))
        h.update(b"\x00")
    return h.hexdigest()

def extract_page_text(raw: bytes, content_type: str = "") -> str:
    text = raw.decode("utf-8", errors="replace")
    feature = "xml" if "xml" in content_type.casefold() or text.lstrip().startswith("<?xml") else "html.parser"
    try:
        soup = BeautifulSoup(text, feature)
    except Exception:
        soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return norm(soup.get_text(" ", strip=True))

def allowed_domain(url: str, allowlist: list[str]) -> bool:
    try:
        host = (urlparse(url).hostname or "").casefold()
    except Exception:
        return False
    return any(host == d.casefold() or host.endswith("." + d.casefold()) for d in allowlist)

def make_logger(project_root: Path, name: str) -> logging.Logger:
    log_dir = project_root / "logs" / "agents"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        fh = logging.FileHandler(log_dir / f"{name}.log", encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger

class AgentState:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(db_path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS evidence_cache(
            url TEXT PRIMARY KEY,
            status_code INTEGER,
            content_type TEXT,
            final_url TEXT,
            fetched_at TEXT,
            body_hash TEXT,
            text TEXT,
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS sector_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id TEXT NOT NULL,
            record_hash TEXT NOT NULL,
            primary_sector TEXT NOT NULL,
            secondary_sectors TEXT,
            confidence REAL NOT NULL,
            method TEXT NOT NULL,
            evidence TEXT NOT NULL,
            evidence_url TEXT,
            review_required INTEGER NOT NULL,
            decided_at TEXT NOT NULL,
            run_id TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sector_history_master
            ON sector_history(master_id, decided_at DESC);
        CREATE TABLE IF NOT EXISTS run_history(
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            input_path TEXT,
            input_rows INTEGER,
            published_rows INTEGER,
            review_rows INTEGER,
            summary_json TEXT
        );
        """)
        self.con.commit()

    def close(self) -> None:
        self.con.close()

    def get_cached_page(self, url: str, max_age_hours: int) -> dict[str, Any] | None:
        row = self.con.execute(
            "SELECT * FROM evidence_cache WHERE url=?", (url,)
        ).fetchone()
        if not row:
            return None
        try:
            fetched = datetime.fromisoformat(row["fetched_at"])
            age = datetime.now(timezone.utc) - fetched
            if age.total_seconds() > max_age_hours * 3600:
                return None
        except Exception:
            return None
        return dict(row)

    def put_cached_page(self, url: str, payload: dict[str, Any]) -> None:
        self.con.execute("""
        INSERT INTO evidence_cache(url,status_code,content_type,final_url,fetched_at,body_hash,text,error)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(url) DO UPDATE SET
          status_code=excluded.status_code,
          content_type=excluded.content_type,
          final_url=excluded.final_url,
          fetched_at=excluded.fetched_at,
          body_hash=excluded.body_hash,
          text=excluded.text,
          error=excluded.error
        """, (
            url, payload.get("status_code"), payload.get("content_type"),
            payload.get("final_url"), payload.get("fetched_at"),
            payload.get("body_hash"), payload.get("text"), payload.get("error")
        ))
        self.con.commit()

    def previous_sector(self, master_id: str) -> dict[str, Any] | None:
        row = self.con.execute("""
        SELECT * FROM sector_history
        WHERE master_id=? AND review_required=0
        ORDER BY id DESC LIMIT 1
        """, (master_id,)).fetchone()
        return dict(row) if row else None

    def add_sector_decision(self, decision: dict[str, Any], run_id: str) -> None:
        self.con.execute("""
        INSERT INTO sector_history(
          master_id,record_hash,primary_sector,secondary_sectors,confidence,
          method,evidence,evidence_url,review_required,decided_at,run_id
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (
            decision["master_id"], decision["record_hash"],
            decision["primary_sector"], decision.get("secondary_sectors",""),
            decision["confidence"], decision["method"], decision["evidence"],
            decision.get("evidence_url",""), int(decision["review_required"]),
            utc_now(), run_id
        ))
        self.con.commit()

@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str
    text: str
    error: str
    fetched_at: str

class OfficialFetcher:
    def __init__(
        self,
        state: AgentState,
        allowlist: list[str],
        timeout_seconds: int = 25,
        cache_hours: int = 24,
        user_agent: str = "SSIP-Agent/3.4.1.0 (+official-source-verification)"
    ):
        self.state = state
        self.allowlist = allowlist
        self.timeout_seconds = timeout_seconds
        self.cache_hours = cache_hours
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def fetch(self, url: str) -> FetchResult:
        url = norm(url)
        if not url:
            return FetchResult("", "", 0, "", "", "EMPTY_URL", utc_now())
        if not allowed_domain(url, self.allowlist):
            return FetchResult(url, "", 0, "", "", "DOMAIN_NOT_ALLOWED", utc_now())
        cached = self.state.get_cached_page(url, self.cache_hours)
        if cached:
            return FetchResult(
                url, cached.get("final_url") or url, cached.get("status_code") or 0,
                cached.get("content_type") or "", cached.get("text") or "",
                cached.get("error") or "", cached.get("fetched_at") or utc_now()
            )
        payload: dict[str, Any]
        try:
            response = self.session.get(url, timeout=self.timeout_seconds, allow_redirects=True)
            raw = response.content[:5_000_000]
            ctype = response.headers.get("content-type", "")
            text = extract_page_text(raw, ctype)
            payload = {
                "status_code": response.status_code,
                "content_type": ctype,
                "final_url": response.url,
                "fetched_at": utc_now(),
                "body_hash": hashlib.sha256(raw).hexdigest(),
                "text": text[:250_000],
                "error": "" if response.ok else f"HTTP_{response.status_code}",
            }
        except Exception as exc:
            payload = {
                "status_code": 0, "content_type": "", "final_url": url,
                "fetched_at": utc_now(), "body_hash": "", "text": "",
                "error": f"{type(exc).__name__}: {exc}"
            }
        self.state.put_cached_page(url, payload)
        return FetchResult(
            url, payload["final_url"], payload["status_code"], payload["content_type"],
            payload["text"], payload["error"], payload["fetched_at"]
        )

class LMStudioClient:
    def __init__(self, base_url: str, model: str, timeout_seconds: int = 90):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def available(self) -> bool:
        try:
            response = self.session.get(self.base_url + "/v1/models", timeout=4)
            return response.ok
        except Exception:
            return False

    def resolve_model(self) -> str:
        if self.model and self.model != "AUTO":
            return self.model
        response = self.session.get(self.base_url + "/v1/models", timeout=8)
        response.raise_for_status()
        data = response.json().get("data") or []
        if not data:
            raise RuntimeError("LM Studio is running but no model is loaded.")
        return data[0]["id"]

    def complete_json(self, system: str, user: str, temperature: float = 0.0) -> dict[str, Any]:
        model = self.resolve_model()
        response = self.session.post(
            self.base_url + "/v1/chat/completions",
            timeout=self.timeout_seconds,
            json={
                "model": model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.S)
            if not match:
                raise
            return json.loads(match.group(0))
