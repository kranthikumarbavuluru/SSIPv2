from __future__ import annotations

import argparse
from pathlib import Path


MARKER = (
    "v3.4.3.7.9.2 — definitive version-tolerant "
    "department tab contrast"
)

CSS_BLOCK = r"""
/* ==========================================================================
   v3.4.3.7.9.2 — definitive version-tolerant department tab contrast
   ========================================================================== */

/*
Do not depend on the exact HTML tag used by a particular Streamlit release.
Target the accessibility role and BaseWeb tab list directly. SSIP colour
variables already change with the application's light/dark mode.
*/
[data-baseweb="tab-list"],
[data-testid="stTabs"] [role="tablist"] {
  opacity: 1 !important;
  color: var(--public-ink, #10213f) !important;
  border-bottom-color: var(--public-border, #d7e3f1) !important;
}

[data-baseweb="tab-list"] [role="tab"],
[data-baseweb="tab-list"] [data-baseweb="tab"],
[data-testid="stTabs"] [role="tab"],
[data-testid="stTabs"] [data-baseweb="tab"] {
  color: var(--public-ink, #10213f) !important;
  -webkit-text-fill-color: var(--public-ink, #10213f) !important;
  opacity: 1 !important;
  visibility: visible !important;
  filter: none !important;
  mix-blend-mode: normal !important;
}

[data-baseweb="tab-list"] [role="tab"] *,
[data-baseweb="tab-list"] [data-baseweb="tab"] *,
[data-testid="stTabs"] [role="tab"] *,
[data-testid="stTabs"] [data-baseweb="tab"] * {
  color: var(--public-ink, #10213f) !important;
  -webkit-text-fill-color: var(--public-ink, #10213f) !important;
  opacity: 1 !important;
  visibility: visible !important;
  filter: none !important;
  mix-blend-mode: normal !important;
  text-shadow: none !important;
}

[data-baseweb="tab-list"] [role="tab"][aria-selected="false"],
[data-baseweb="tab-list"] [data-baseweb="tab"][aria-selected="false"],
[data-testid="stTabs"] [role="tab"][aria-selected="false"],
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="false"] {
  color: var(--public-ink, #10213f) !important;
  -webkit-text-fill-color: var(--public-ink, #10213f) !important;
  opacity: 1 !important;
}

[data-baseweb="tab-list"] [role="tab"][aria-selected="true"],
[data-baseweb="tab-list"] [data-baseweb="tab"][aria-selected="true"],
[data-testid="stTabs"] [role="tab"][aria-selected="true"],
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
  color: var(--public-blue-dark, #0b3a82) !important;
  -webkit-text-fill-color: var(--public-blue-dark, #0b3a82) !important;
  border-bottom-color: var(--public-blue, #1261c9) !important;
  box-shadow: inset 0 -2px 0 var(--public-blue, #1261c9) !important;
  opacity: 1 !important;
  font-weight: 800 !important;
}

[data-baseweb="tab-list"] [role="tab"][aria-selected="true"] *,
[data-baseweb="tab-list"] [data-baseweb="tab"][aria-selected="true"] *,
[data-testid="stTabs"] [role="tab"][aria-selected="true"] *,
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] * {
  color: var(--public-blue-dark, #0b3a82) !important;
  -webkit-text-fill-color: var(--public-blue-dark, #0b3a82) !important;
  opacity: 1 !important;
  font-weight: 800 !important;
}

[data-baseweb="tab-list"] [role="tab"]:hover,
[data-baseweb="tab-list"] [data-baseweb="tab"]:hover,
[data-testid="stTabs"] [role="tab"]:hover,
[data-testid="stTabs"] [data-baseweb="tab"]:hover {
  background: var(--public-blue-soft, #eaf3ff) !important;
  color: var(--public-blue-dark, #0b3a82) !important;
  -webkit-text-fill-color: var(--public-blue-dark, #0b3a82) !important;
  opacity: 1 !important;
}

[data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
  background: var(--public-blue, #1261c9) !important;
  background-color: var(--public-blue, #1261c9) !important;
  opacity: 1 !important;
}

/* Cover older Streamlit builds that render the label as a Markdown paragraph. */
[data-baseweb="tab-list"] [data-testid="stMarkdownContainer"],
[data-baseweb="tab-list"] [data-testid="stMarkdownContainer"] p,
[data-testid="stTabs"] [data-testid="stMarkdownContainer"],
[data-testid="stTabs"] [data-testid="stMarkdownContainer"] p {
  color: var(--public-ink, #10213f) !important;
  -webkit-text-fill-color: var(--public-ink, #10213f) !important;
  opacity: 1 !important;
  visibility: visible !important;
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
        '[data-baseweb="tab-list"] [role="tab"]',
        '[data-testid="stTabs"] [role="tab"]',
        '[data-baseweb="tab-list"] [role="tab"] *',
        '[data-testid="stTabs"] [role="tab"] *',
        '[aria-selected="false"]',
        '[aria-selected="true"]',
        'var(--public-ink, #10213f)',
        'var(--public-blue-dark, #0b3a82)',
        'var(--public-blue, #1261c9)',
        'opacity: 1 !important;',
        'visibility: visible !important;',
        'filter: none !important;',
        '[data-testid="stMarkdownContainer"] p',
    )
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError(
            "Definitive tab contrast validation failed: "
            + repr(missing)
        )
    if text.count(MARKER) != 1:
        raise RuntimeError(
            "Definitive tab contrast block must occur exactly once."
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
            "Definitive department tab contrast patch: "
            + ("APPLIED" if changed else "ALREADY_APPLIED")
        )

    validate(path)
    print(
        "SSIP v3.4.3.7.9.2 definitive tab contrast: PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
