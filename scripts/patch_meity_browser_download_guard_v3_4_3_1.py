from pathlib import Path

project_root = Path(__file__).resolve().parents[1]

target = (
    project_root
    / "scripts"
    / "meity_discovery_expansion_agent_v3_4_3_1.py"
)

text = target.read_text(
    encoding="utf-8-sig"
)

old_render_condition = '''                browser.available
                and not page.error
                and (
'''

new_render_condition = '''                browser.available
                and not page.error
                and not is_evidence_document(
                    page.canonical_url
                )
                and page.content_type not in {
                    "application/pdf",
                    "application/msword",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/vnd.ms-excel",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/zip",
                    "application/octet-stream",
                }
                and (
'''

condition_count = text.count(
    old_render_condition
)

if condition_count != 1:
    raise RuntimeError(
        "Expected one browser-render condition; "
        f"found {condition_count}."
    )

text = text.replace(
    old_render_condition,
    new_render_condition,
    1,
)

old_browser_block = '''            if should_render:
                rendered_meta, rendered_links, network_endpoints = browser.discover(
                    page.canonical_url
                )
                if rendered_meta:
                    page.rendered_used = True
                    for key in ("title", "heading", "text_excerpt"):
                        value = normalize_space(rendered_meta.get(key, ""))
                        if value and (
                            key != "text_excerpt"
                            or len(value) > len(page.text_excerpt)
                        ):
                            setattr(page, key, value)
                page.rendered_link_count = len(rendered_links)
                if any(
                    signal in page.canonical_url.casefold()
                    for signal in DISCOVERY_INDEX_PATH_SIGNALS
                ):
                    rendered_index_count += 1
'''

new_browser_block = '''            if should_render:
                try:
                    (
                        rendered_meta,
                        rendered_links,
                        network_endpoints,
                    ) = browser.discover(
                        page.canonical_url
                    )

                    if rendered_meta:
                        page.rendered_used = True

                        for key in (
                            "title",
                            "heading",
                            "text_excerpt",
                        ):
                            value = normalize_space(
                                rendered_meta.get(
                                    key,
                                    "",
                                )
                            )

                            if value and (
                                key != "text_excerpt"
                                or len(value)
                                > len(page.text_excerpt)
                            ):
                                setattr(
                                    page,
                                    key,
                                    value,
                                )

                    page.rendered_link_count = len(
                        rendered_links
                    )

                    if any(
                        signal
                        in page.canonical_url.casefold()
                        for signal
                        in DISCOVERY_INDEX_PATH_SIGNALS
                    ):
                        rendered_index_count += 1

                except Exception as exc:
                    rendered_links = []
                    network_endpoints = []

                    page.reasons.append(
                        "BROWSER_RENDER_SKIPPED_"
                        + type(exc).__name__.upper()
                    )

                    print(
                        "  Browser rendering skipped: "
                        f"{page.canonical_url} | "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
'''

block_count = text.count(
    old_browser_block
)

if block_count != 1:
    raise RuntimeError(
        "Expected one browser-discovery block; "
        f"found {block_count}."
    )

text = text.replace(
    old_browser_block,
    new_browser_block,
    1,
)

target.write_text(
    text,
    encoding="utf-8",
    newline="\n",
)

print(
    "MeitY browser download guard: COMPLETE"
)
