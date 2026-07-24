from __future__ import annotations

"""Report optional OCR, QR and PDF extraction engine availability."""

import importlib.util
import json
import shutil


def main() -> int:
    modules = {
        "Pillow": "PIL",
        "pytesseract": "pytesseract",
        "opencv": "cv2",
        "pyzbar": "pyzbar",
        "pypdf": "pypdf",
        "langdetect": "langdetect",
    }
    report = {name: bool(importlib.util.find_spec(module)) for name, module in modules.items()}
    report["tesseract_binary"] = bool(shutil.which("tesseract"))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
