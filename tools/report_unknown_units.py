# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = []
# ///
# ─── How to run ───
# uv run tools/report_unknown_units.py .g2b/g2b.sqlite3

"""Report numeric-adjacent unit tokens not covered by normalization v2."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Final

from g2b_compare.db.connection import connect_read_only
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.normalize.units import ALIASES

_SUFFIX_PATTERN: Final = r"(?:(?<=\d)|(?<=\.))\s*(?P<token>[A-Za-z°℃㎡]+)"
_PREFIX_PATTERN: Final = r"(?P<prefix>[A-Za-z°℃㎡]+)\s*(?=\d)"
_TOKEN: Final = re.compile(f"{_SUFFIX_PATTERN}|{_PREFIX_PATTERN}")


def main() -> int:
    """Scan the latest complete materialization and emit deterministic JSON."""
    database = Path(sys.argv[1] if len(sys.argv) > 1 else ".g2b/g2b.sqlite3")
    known = frozenset(unicodedata.normalize("NFKC", item) for item in ALIASES)
    counts: dict[str, int] = defaultdict(int)
    categories: dict[str, set[str]] = defaultdict(set)
    with connect_read_only(database) as connection:
        materialization = query(
            connection,
            "SELECT MAX(id) FROM materialization_snapshots WHERE status='complete'",
        ).fetchone()
        if materialization is None or materialization[0] is None:
            _ = sys.stdout.write('{"items":[],"materialization_id":null}\n')
            return 0
        materialization_id = as_int(materialization[0])
        rows = query(
            connection,
            """SELECT p.category_no||'/'||p.detail_category_no,
                      p.spec_name,p.detail,p.characteristic,a.raw_value
               FROM products p
               LEFT JOIN product_attributes a
                 ON a.materialization_id=p.materialization_id
                AND a.product_id=p.product_id
               WHERE p.materialization_id=?
               ORDER BY p.product_id,a.ordinal""",
            (materialization_id,),
        ).fetchall()
        for row in rows:
            category = as_text(row[0])
            values = row[1:]
            for raw in values:
                text = unicodedata.normalize("NFKC", as_text(raw))
                for match in _TOKEN.finditer(text):
                    token = match.group("token") or match.group("prefix") or ""
                    if token in known:
                        continue
                    counts[token] += 1
                    categories[token].add(category)
    items = [
        {
            "token": token,
            "frequency": counts[token],
            "detail_category_count": len(categories[token]),
        }
        for token in sorted(
            counts,
            key=lambda item: (-counts[item], -len(categories[item]), item.encode()),
        )
    ]
    _ = sys.stdout.write(
        json.dumps(
            {"materialization_id": materialization_id, "items": items},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
