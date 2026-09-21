"""What changed between consecutive captures of each page, read from parsed_rows.

    python -m src.changes                 # every page source, whole record
    python -m src.changes --since 2026-09-19 t18_update wut_empties

For each source: how many captures, how many times the facts on the page changed, and each
change with the window it happened in (after the earlier capture, by the later one). Captures
whose bytes are identical are never compared, so a parser upgrade cannot show up as a change;
after one, run `python -m src.parse --all --force` first so both sides are read the same way. This is
the number to put in front of someone: "T18's empty-return grid changed N times in two weeks,
and the page kept no trace of it."
"""
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from . import store
from .capture import SOURCES

PT = ZoneInfo("America/Los_Angeles")
KINDS = ("gate_day", "empty_rule", "erd", "notice")  # facts; readings and mock slots change by nature
IGNORED = {"parser_version", "heading", "cells", "context", "keywords", "updates", "dates_mentioned", "as_of_iso"}


def _pt(utc: str) -> str:
    return datetime.fromisoformat(utc).astimezone(PT).strftime("%b %d %H:%M")


def _facts(conn, capture_id: int) -> dict[str, dict]:
    rows = conn.execute(
        f"SELECT entity_key, row_json FROM parsed_rows WHERE capture_id = ? AND kind IN ({','.join('?' * len(KINDS))})",
        (capture_id, *KINDS),
    )
    return {k: {f: v for f, v in json.loads(js).items() if f not in IGNORED} for k, js in rows}


def changes_for(conn, source_id: str, since: str = "") -> tuple[int, list[dict]]:
    caps = conn.execute(
        "SELECT id, fetched_at, content_hash FROM captures WHERE source_id = ? AND content_hash IS NOT NULL AND fetched_at >= ?"
        " AND id IN (SELECT capture_id FROM parsed_rows) ORDER BY id",
        (source_id, since),
    ).fetchall()
    out, prev, prev_at, prev_hash = [], None, None, None
    for cid, at, content_hash in caps:
        if content_hash == prev_hash:
            prev_at = at  # same bytes as last time: nothing changed, whatever parser version read them
            continue
        cur = _facts(conn, cid)
        prev_hash = content_hash
        if prev is not None:
            for key in sorted(prev.keys() | cur.keys()):
                a, b = prev.get(key), cur.get(key)
                if a == b:
                    continue
                kind = "added" if a is None else "removed" if b is None else "changed"
                fields = {f: (a.get(f), b.get(f)) for f in (a.keys() | b.keys()) if a.get(f) != b.get(f)} if a and b else {}
                out.append({"key": key, "kind": kind, "fields": fields, "after": prev_at, "by": at, "capture_id": cid})
        prev, prev_at = cur, at
    return len(caps), out


def main() -> None:
    args = sys.argv[1:]
    since = args[args.index("--since") + 1] if "--since" in args else ""
    wanted = [a for a in args if a in SOURCES] or [s for s, v in SOURCES.items() if v["channel"] in ("gate", "empties", "erd", "bulletin")]
    conn = store.connect()
    for sid in wanted:
        n, ch = changes_for(conn, sid, since)
        moments = len({c["capture_id"] for c in ch})
        print(f"\n{sid}: {n} captures, facts changed at {moments} of them ({len(ch)} individual changes)")
        for c in ch[:40]:
            detail = "; ".join(f"{f}: {a!r} -> {b!r}" for f, (a, b) in c["fields"].items()) or c["kind"]
            print(f"  between {_pt(c['after'])} and {_pt(c['by'])} PT  {c['key']}  {detail[:160]}")
        if len(ch) > 40:
            print(f"  ... and {len(ch) - 40} more")
    conn.close()


if __name__ == "__main__":
    main()
