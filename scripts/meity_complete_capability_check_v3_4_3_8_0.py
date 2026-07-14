from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_complete_intelligence_v3_4_3_8_0 import (
    BrowserRenderer,
)


def main() -> int:
    modules = {
        "pypdf": bool(
            importlib.util.find_spec("pypdf")
        ),
        "PyPDF2": bool(
            importlib.util.find_spec("PyPDF2")
        ),
        "pymupdf": bool(
            importlib.util.find_spec("fitz")
        ),
        "pytesseract": bool(
            importlib.util.find_spec(
                "pytesseract"
            )
        ),
        "pillow": bool(
            importlib.util.find_spec("PIL")
        ),
    }
    renderer = BrowserRenderer(10)
    tesseract = (
        shutil.which("tesseract")
        or shutil.which("tesseract.exe")
        or ""
    )
    payload = {
        "version": "3.4.3.8.0",
        "browser_available": bool(
            renderer.executable
        ),
        "browser_executable": (
            renderer.executable
        ),
        "native_pdf_text_available": any(
            modules[name]
            for name in (
                "pypdf",
                "PyPDF2",
                "pymupdf",
            )
        ),
        "image_pdf_ocr_available": (
            modules["pymupdf"]
            and modules["pytesseract"]
            and modules["pillow"]
            and bool(tesseract)
        ),
        "tesseract_executable": tesseract,
        "modules": modules,
        "api_and_javascript_scan": True,
        "database_write_capability": False,
        "publication_capability": False,
    }
    print(
        json.dumps(
            payload,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
