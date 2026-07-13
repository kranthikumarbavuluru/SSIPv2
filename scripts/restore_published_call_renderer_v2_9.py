# -*- coding: utf-8 -*-

from pathlib import Path
import shutil

root = Path(
    r"D:\WebSite\DASHBOARD\Code\SSIP"
)

path = (
    root
    / "apps"
    / "public_dashboard_app_v2_9.py"
)

backup = (
    root
    / "apps"
    / "public_dashboard_app_v2_9_before_call_renderer_restore.py"
)

text = path.read_text(
    encoding="utf-8-sig"
)

start_marker = "def _published_call_card("
end_marker = "\ndef _historical_relevance_label"

start = text.find(start_marker)

if start < 0:
    raise RuntimeError(
        "_published_call_card was not found."
    )

end = text.find(
    end_marker,
    start,
)

if end < 0:
    raise RuntimeError(
        "_historical_relevance_label boundary was not found."
    )

current_block = text[start:end]

if (
    "Render a governed published call"
    in current_block
):
    print(
        "Published-call renderer is already restored."
    )
    raise SystemExit(0)

replacement = '''def _published_call_card(
    item: CatalogueRecord,
    *,
    parent_names: dict[str, str],
    ecosystem: bool = False,
) -> str:
    """Render a governed published call using the standard scheme card."""
    parent = (
        item.parent_scheme_name
        or parent_names.get(
            item.parent_master_id,
            "",
        )
        or "Parent scheme requires curation"
    )

    card_html = scheme_card(
        item,
        compact=False,
    )

    if (
        not isinstance(card_html, str)
        or not card_html.strip()
    ):
        identifier = (
            item.master_id
            or item.scheme_name
            or "unknown call"
        )

        raise TypeError(
            "scheme_card returned no HTML for "
            + str(identifier)
        )

    audience = (
        "Institutional or ecosystem opportunity"
        if ecosystem
        else "Startup application opportunity"
    )

    call_context = (
        '<div class="agency-line">'
        '<b>Parent programme:</b> '
        + esc(parent)
        + " - "
        + esc(audience)
        + "</div>"
    )

    closing_tag = "</article>"

    if closing_tag in card_html:
        return card_html.replace(
            closing_tag,
            call_context + closing_tag,
            1,
        )

    return card_html + call_context


'''

shutil.copy2(
    path,
    backup,
)

updated = (
    text[:start]
    + replacement
    + text[end:]
)

path.write_text(
    updated,
    encoding="utf-8",
    newline="\n",
)

print(
    "SSIP published-call renderer restore: COMPLETE"
)
print(
    "Backup:",
    backup,
)
print(
    "Original function characters replaced:",
    len(current_block),
)
