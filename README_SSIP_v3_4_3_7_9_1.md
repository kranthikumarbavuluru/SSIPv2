# SSIP v3.4.3.7.9.1 — Department Tab Contrast Fix

This presentation-only hotfix restores readable Streamlit tab labels in
SSIP light mode.

## Scope

The fix applies to all `st.tabs` components, including:

- DST Schemes
- Current DST Calls
- DST Historical Archive
- MeitY Schemes
- Current MeitY Calls
- MeitY Historical Archive

It defines explicit colours for inactive, hover and selected tab states.
Dark-mode tab contrast is preserved with separate selectors.

## Governance

- No catalogue changes.
- No database changes.
- No publication changes.
- No DST or MeitY records are modified.
- No navigation, filter or status logic changes.
