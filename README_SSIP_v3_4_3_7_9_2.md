# SSIP v3.4.3.7.9.2 — Definitive Department Tab Contrast

The previous tab hotfix was too dependent on one Streamlit DOM shape. This
continuation uses accessibility roles and BaseWeb attributes instead of
requiring a `button` element.

## Fix

The final CSS block targets:

- `[data-baseweb="tab-list"] [role="tab"]`
- `[data-testid="stTabs"] [role="tab"]`
- all descendants of each tab
- Markdown paragraph label fallbacks
- inactive, hover and selected states
- the active-tab highlight

Colours use the existing SSIP variables, so the same selectors work in both
light and dark mode without a separate light-mode detection condition.

## Governance

- Presentation-only change.
- No database modification.
- No publication action.
- No DST or MeitY data change.
- No page, filter, status or navigation logic change.
