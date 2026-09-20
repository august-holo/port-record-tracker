"""Fetch sources and record captures. Usable one-shot (cron/manual) or via scheduler.

Usage:
    python -m src.capture              # capture all sources once
    python -m src.capture t18_update   # capture one source
    python -m src.capture --public     # only public sources (skip mocks)

Every capture stores the raw body (changed or not), then tries to parse it.
A parse failure never prevents the capture from being recorded.
"""
import logging
import os
import random
import sys
import time

import requests

from . import store

log = logging.getLogger(__name__)

# Contact email for the User-Agent. Set CONTACT_EMAIL in the environment (or .env)
# before any sustained run; the placeholder is only for smoke tests.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "CONTACT_EMAIL_HERE")
USER_AGENT = f"terminal-state-archive/0.2 (public-page archival; contact: {CONTACT_EMAIL})"

NWSA = "https://www.nwseaportalliance.com"

# Source registry. `terminal` is the NWSA short name the exhibit groups by.
# `channel` says which stop-the-clock fact the source speaks to:
#   gate      - scheduled gate hours / closures
#   empties   - empty-return acceptance by line and size
#   bulletin  - port-wide notices (unscheduled closures, blanket restrictions)
#   turn_time - queue / in-terminal minutes (congestion)
#   erd       - export receiving windows
#   slots     - appointment availability (mock until we have eModal access)
SOURCES: dict[str, dict] = {
    # --- export receiving (P25) ---
    "nwsa_erd": {
        "url": f"{NWSA}/cargo-operations/vessel-schedules-and-calendar/export-receiving-dates",
        "cadence_minutes": 60,
        "terminal": None,
        "channel": "erd",
        "parser": "nwsa_erd",
    },
    "wut_erd": {
        "url": "https://www.uswut.com/schedule/vessel-export-receiving/",
        "cadence_minutes": 120,
        "terminal": "WUT",
        "channel": "erd",
        "parser": "wut_erd",
    },
    # --- port-wide ---
    "nwsa_turn_times": {
        "url": f"{NWSA}/cargo-operations/cameras-truck-turn-times",
        "cadence_minutes": 15,
        "terminal": None,
        "channel": "turn_time",
        "parser": "nwsa_turn_times",
    },
    "nwsa_bulletins": {
        "url": f"{NWSA}/cargo-operations/trucker-resources/trucker-news-updates",
        "cadence_minutes": 60,
        "terminal": None,
        "channel": "bulletin",
        "parser": "nwsa_bulletins",
    },
    # --- terminal update pages (gate hours, closures, empty matrices, notices) ---
    "t18_update": {
        "url": f"{NWSA}/cargo-operations/terminals/terminal-18/terminal-18-update",
        "cadence_minutes": 120,
        "terminal": "T18",
        "channel": "gate",
        "parser": "terminal_page",
    },
    "t5_update": {
        "url": f"{NWSA}/cargo-operations/terminals/terminal-5/terminal-5",
        "cadence_minutes": 120,
        "terminal": "T5",
        "channel": "gate",
        "parser": "terminal_page",
    },
    "husky_update": {
        "url": f"{NWSA}/cargo-operations/terminals/husky-terminal-husky/husky-terminal-husky-update",
        "cadence_minutes": 120,
        "terminal": "Husky",
        "channel": "gate",
        "parser": "terminal_page",
    },
    "pct_update": {
        "url": f"{NWSA}/cargo-operations/terminals/pierce-county-terminal-pct/pierce-county-terminal-pct-update",
        "cadence_minutes": 120,
        "terminal": "PCT",
        "channel": "gate",
        "parser": "terminal_page",
    },
    "wut_update": {
        "url": f"{NWSA}/cargo-operations/terminals/washington-united-terminals-wut/washington-united-terminals-wut-update",
        "cadence_minutes": 120,
        "terminal": "WUT",
        "channel": "gate",
        "parser": "terminal_page",
    },
    # --- terminal operators' own pages ---
    "wut_empties": {
        "url": "https://www.uswut.com/schedule/empty-receiving/",
        "cadence_minutes": 120,
        "terminal": "WUT",
        "channel": "empties",
        "parser": "wut_empties",
    },
    # --- appointment availability: MOCK until eModal access exists ---
    "emodal_slots_mock": {
        "url": "mock://emodal/api/appointments/move/slots",
        "cadence_minutes": 15,
        "terminal": None,
        "channel": "slots",
        "parser": "emodal_slots",
        "mock": True,
    },
}

TIMEOUT = 30
RETRY_AFTER_SECONDS = 20
MIN_SECONDS_BETWEEN_REQUESTS = 3.0  # per process; far under one request a minute per host across sources


def _fetch(url: str) -> requests.Response:
    """GET with one retry on connection error / 5xx."""
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        if resp.status_code >= 500:
            raise requests.HTTPError(f"{resp.status_code} from {url}", response=resp)
        return resp
    except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as first:
        log.warning("retrying %s after %s: %s", url, RETRY_AFTER_SECONDS, first)
        time.sleep(RETRY_AFTER_SECONDS)
        return requests.get(url, headers=headers, timeout=TIMEOUT)


def capture_source(source_id: str) -> int | None:
    """Capture one source. Returns the capture id (or None on hard failure)."""
    src = SOURCES[source_id]
    if src.get("mock"):
        from . import mock_emodal

        return mock_emodal.capture(source_id, src)

    conn = store.connect()
    capture_id = None
    try:
        time.sleep(random.uniform(0, 1.0))
        started = time.monotonic()
        resp = _fetch(src["url"])
        ext = "json" if "json" in (resp.headers.get("Content-Type") or "") else "html"
        content_hash = store.store_raw(resp.content, ext)
        capture_id = store.record_capture(
            conn,
            source_id,
            src["url"],
            resp.status_code,
            content_hash,
            content_type=resp.headers.get("Content-Type"),
        )
        ms = int((time.monotonic() - started) * 1000)
        print(f"[{source_id}] {resp.status_code} hash={content_hash[:12]} {ms}ms")
    except requests.RequestException as exc:
        store.record_capture(conn, source_id, src["url"], None, None, error=str(exc))
        print(f"[{source_id}] FAILED: {exc}", file=sys.stderr)
    finally:
        conn.close()

    if capture_id is not None:
        # Parse after the capture is safely recorded; never let a parser block a capture.
        try:
            from . import parse

            n = parse.parse_capture(capture_id)
            print(f"[{source_id}] parsed {n} rows")
        except Exception as exc:  # noqa: BLE001 - parsers are allowed to fail
            print(f"[{source_id}] parse error: {exc}", file=sys.stderr)
    return capture_id


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    public_only = "--public" in sys.argv
    targets = args or [s for s, v in SOURCES.items() if not (public_only and v.get("mock"))]
    for source_id in targets:
        if source_id not in SOURCES:
            sys.exit(f"unknown source: {source_id} (known: {', '.join(SOURCES)})")
        capture_source(source_id)
        time.sleep(MIN_SECONDS_BETWEEN_REQUESTS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
