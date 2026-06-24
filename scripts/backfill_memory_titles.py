#!/usr/bin/env python3
"""One-off: fill `metadata.title` for memories distilled before titles existed.

New memories get an LLM noun-phrase title at distill time (extraction.py), but
~40% of older rows have none, so they render blank in the web UI and lack a
label in search/graph. Re-running the LLM over 1781 rows would burn the local
model against the Pi budget gate, so we derive a cheap title from the memory's
own content (first clause, <=60 chars). New rows keep their proper LLM titles.

Dry-run by default; pass --execute to write.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import orjson

LANCE = Path.home() / "app/piloci/data/piloci/lancedb"


def derive_title(content: str) -> str:
    """First clause of the content, trimmed to a <=60-char noun-ish phrase."""
    text = (content or "").strip().replace("\n", " ")
    # Cut at the first sentence boundary (Korean/English), else hard cap.
    m = re.search(r"[.!?。](?:\s|$)", text)
    head = text[: m.start()] if m else text
    head = head.strip().strip("-•*# ").strip()
    if len(head) > 60:
        head = head[:60].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return head or "(untitled)"


def main() -> int:
    execute = "--execute" in sys.argv
    import lancedb

    db = lancedb.connect(str(LANCE))
    tbl = db.open_table("piloci_memories")
    arr = tbl.to_arrow()
    mids = arr.column("memory_id").to_pylist()
    metas = arr.column("metadata").to_pylist()
    contents = arr.column("content").to_pylist()

    new_meta: dict[str, str] = {}
    for mid, meta, content in zip(mids, metas, contents, strict=True):
        try:
            d = orjson.loads(meta) if meta else {}
        except Exception:
            d = {}
        if d.get("title"):
            continue
        d["title"] = derive_title(content)
        new_meta[mid] = orjson.dumps(d).decode()

    print(f"memories={len(mids)}  missing title={len(new_meta)}")
    for mid in list(new_meta)[:8]:
        print(f"  {mid[:8]}  →  {orjson.loads(new_meta[mid])['title']!r}")
    if not execute:
        print("(dry-run — pass --execute to write)")
        return 0

    # Rebuild the changed rows with patched metadata and upsert them in one
    # pass (merge_insert on memory_id) so we don't spawn 1781 table versions.
    import pyarrow.compute as pc

    mask = pc.is_in(arr.column("memory_id"), value_set=__import__("pyarrow").array(list(new_meta)))
    changed = arr.filter(mask)
    patched_meta = [new_meta[m] for m in changed.column("memory_id").to_pylist()]
    idx = changed.schema.get_field_index("metadata")
    changed = changed.set_column(idx, "metadata", __import__("pyarrow").array(patched_meta))
    (tbl.merge_insert("memory_id").when_matched_update_all().execute(changed))
    print(f">>> filled {len(new_meta)} titles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
