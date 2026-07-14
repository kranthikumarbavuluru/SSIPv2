from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.apply_meity_source_parser_fix_v3_4_3_8_0_1 import (
    NEW_BLOCK,
    OLD_BLOCK,
    patch,
    validate,
)


class MeitYSourceParserFixTests(unittest.TestCase):
    def test_patch_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "service.py"
            path.write_text(
                "prefix\n" + OLD_BLOCK + "suffix\n",
                encoding="utf-8",
            )
            self.assertTrue(patch(path))
            validate(path)
            self.assertFalse(patch(path))
            validate(path)

    def test_safe_parser_allows_meta_without_name(self) -> None:
        namespace: dict[str, object] = {}
        source = """
def clean(value):
    return str(value or "").strip()

def extract(attr):
    key = clean(
        attr.get("property")
        or attr.get("name")
        or attr.get("itemprop")
        or ""
    ).casefold()
    return key
"""
        exec(source, namespace)
        extract = namespace["extract"]
        self.assertEqual(extract({}), "")
        self.assertEqual(extract({"name": "Description"}), "description")


if __name__ == "__main__":
    unittest.main()
