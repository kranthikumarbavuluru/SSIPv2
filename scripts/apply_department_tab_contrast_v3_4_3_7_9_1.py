from __future__ import annotations

import argparse
from pathlib import Path


MARKER = (
    "v3.4.3.7.9.1 — readable Streamlit department tabs "
    "in both colour modes"
)

CSS_BLOCK = r"""
/* ==========================================================================
   v3.4.3.7.9.1 — readable Streamlit department tabs in both colour modes
   ========================================================================== */

/*
Streamlit may retain the host/browser tab text colour after SSIP switches its
own presentation layer between light and dark mode. These selectors target
only st.tabs controls and restore explicit, accessible contrast.
*/
html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] [data-baseweb="tab-list"] {
  border-bottom-color: #d7e3f1 !important;
}

html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[role="tab"],
html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[data-baseweb="tab"],
html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[role="tab"] *,
html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[data-baseweb="tab"] * {
  color: #405873 !important;
  -webkit-text-fill-color: #405873 !important;
  opacity: 1 !important;
  visibility: visible !important;
}

html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[role="tab"][aria-selected="false"],
html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="false"] {
  background: transparent !important;
  opacity: 1 !important;
}

html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[role="tab"]:hover,
html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[data-baseweb="tab"]:hover {
  background: #f1f6fc !important;
}

html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[role="tab"][aria-selected="true"],
html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"],
html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] *,
html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] * {
  color: #0b4da5 !important;
  -webkit-text-fill-color: #0b4da5 !important;
  font-weight: 800 !important;
  opacity: 1 !important;
}

html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
  background-color: #1261c9 !important;
}

/* Explicit dark-mode equivalents keep the already-good dark view unchanged. */
html:has(#ssip-dark-mode) div[data-testid="stTabs"] [data-baseweb="tab-list"] {
  border-bottom-color: #2c4669 !important;
}

html:has(#ssip-dark-mode) div[data-testid="stTabs"] button[role="tab"],
html:has(#ssip-dark-mode) div[data-testid="stTabs"] button[data-baseweb="tab"],
html:has(#ssip-dark-mode) div[data-testid="stTabs"] button[role="tab"] *,
html:has(#ssip-dark-mode) div[data-testid="stTabs"] button[data-baseweb="tab"] * {
  color: #c7d8ec !important;
  -webkit-text-fill-color: #c7d8ec !important;
  opacity: 1 !important;
  visibility: visible !important;
}

html:has(#ssip-dark-mode) div[data-testid="stTabs"] button[role="tab"]:hover,
html:has(#ssip-dark-mode) div[data-testid="stTabs"] button[data-baseweb="tab"]:hover {
  background: #132a47 !important;
}

html:has(#ssip-dark-mode) div[data-testid="stTabs"] button[role="tab"][aria-selected="true"],
html:has(#ssip-dark-mode) div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"],
html:has(#ssip-dark-mode) div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] *,
html:has(#ssip-dark-mode) div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] * {
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
  font-weight: 800 !important;
  opacity: 1 !important;
}

html:has(#ssip-dark-mode) div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
  background-color: #4da3ff !important;
}
"""


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8-sig")
    if MARKER in text:
        return False

    separator = "" if text.endswith("\n") else "\n"
    path.write_text(
        text
        + separator
        + "\n"
        + CSS_BLOCK.strip()
        + "\n",
        encoding="utf-8",
    )
    return True


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")
    required = (
        MARKER,
        'html:not(:has(#ssip-dark-mode)) div[data-testid="stTabs"]',
        'html:has(#ssip-dark-mode) div[data-testid="stTabs"]',
        'button[role="tab"][aria-selected="false"]',
        'button[role="tab"][aria-selected="true"]',
        '[data-baseweb="tab-highlight"]',
        '-webkit-text-fill-color: #405873 !important;',
        '-webkit-text-fill-color: #ffffff !important;',
        'opacity: 1 !important;',
    )
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError(
            "Department-tab contrast validation failed: "
            + repr(missing)
        )

    if text.count(MARKER) != 1:
        raise RuntimeError(
            "Department-tab contrast block must occur exactly once."
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    path = (
        Path(args.project_root).resolve()
        / "assets/styles/ssip_public_dashboard.css"
    )
    if not path.exists():
        raise FileNotFoundError(
            f"Public dashboard stylesheet not found: {path}"
        )

    if not args.check:
        changed = patch(path)
        print(
            "Department tab contrast patch: "
            + ("APPLIED" if changed else "ALREADY_APPLIED")
        )

    validate(path)
    print(
        "SSIP v3.4.3.7.9.1 department tab contrast: PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
