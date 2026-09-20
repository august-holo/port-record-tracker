"""Daily custody manifests: the captures table as one CSV per UTC day, in data/manifests/.

    python -m src.manifest              # (re)write today's and yesterday's
    python -m src.manifest 2026-09-20   # one day

The production stack syncs data/manifests/ and data/raw/ to a write-once (Object Lock) bucket,
so the link between a page hash and the time it was fetched is held by a third party within
the hour, and no longer rests on this archive's own database. A day's file grows until the
day ends; the bucket keeps every version.
"""
import csv
import sys
from datetime import date, datetime, timedelta, timezone

from . import store

MANIFEST_DIR = store.DATA_DIR / "manifests"
COLUMNS = ["id", "source_id", "fetched_at", "url", "http_status", "content_hash", "error", "is_mock"]


def write_day(day: date) -> int:
    """Write the manifest for one UTC day. Returns the number of captures in it."""
    conn = store.connect()
    rows = conn.execute(
        f"SELECT {', '.join(COLUMNS)} FROM captures WHERE fetched_at >= ? AND fetched_at < ? ORDER BY id",
        (day.isoformat(), (day + timedelta(days=1)).isoformat()),
    ).fetchall()
    conn.close()
    if not rows:
        return 0
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_DIR / f".{day.isoformat()}.csv.tmp"
    with tmp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(rows)
    tmp.replace(MANIFEST_DIR / f"captures-{day.isoformat()}.csv")
    return len(rows)


def write_recent() -> None:
    today = datetime.now(timezone.utc).date()
    for day in (today - timedelta(days=1), today):
        write_day(day)


if __name__ == "__main__":
    days = [date.fromisoformat(a) for a in sys.argv[1:]]
    if days:
        for d in days:
            print(f"{d}: {write_day(d)} captures")
    else:
        write_recent()
