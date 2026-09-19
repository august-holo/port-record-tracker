"""Fetch sources and record captures. Usable one-shot (cron/manual) or via scheduler.

Usage:
    python -m src.capture              # capture all sources once
    python -m src.capture nwsa_erd     # capture one source
"""
import sys

import requests

from . import store

# TODO: put a real contact email here before any sustained run.
USER_AGENT = (
    "terminal-state-archive/0.1 (public-page archival; contact: CONTACT_EMAIL_HERE)"
)

SOURCES = {
    "nwsa_erd": {
        "url": "https://www.nwseaportalliance.com/cargo-operations/vessel-schedules-and-calendar/export-receiving-dates",
        "cadence_minutes": 60,
    },
    "wut_erd": {
        "url": "https://www.uswut.com/schedule/vessel-export-receiving/",
        "cadence_minutes": 120,
    },
    "nwsa_turn_times": {
        "url": "https://www.nwseaportalliance.com/cargo-operations/cameras-truck-turn-times",
        "cadence_minutes": 15,
    },
    "nwsa_bulletins": {
        "url": "https://www.nwseaportalliance.com/cargo-operations/trucker-resources/trucker-news-updates",
        "cadence_minutes": 60,
    },
}

TIMEOUT = 30


def capture_source(source_id: str) -> None:
    src = SOURCES[source_id]
    conn = store.connect()
    try:
        resp = requests.get(
            src["url"], headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT
        )
        content_hash = store.store_raw(resp.content)
        store.record_capture(conn, source_id, src["url"], resp.status_code, content_hash)
        print(f"[{source_id}] {resp.status_code} hash={content_hash[:12]}")
    except requests.RequestException as exc:
        store.record_capture(conn, source_id, src["url"], None, None, error=str(exc))
        print(f"[{source_id}] FAILED: {exc}", file=sys.stderr)
    finally:
        conn.close()


def main() -> None:
    targets = sys.argv[1:] or list(SOURCES)
    for source_id in targets:
        if source_id not in SOURCES:
            sys.exit(f"unknown source: {source_id} (known: {', '.join(SOURCES)})")
        capture_source(source_id)


if __name__ == "__main__":
    main()
