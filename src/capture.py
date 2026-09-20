"""Fetch sources and record captures. Usable one-shot (cron/manual) or via scheduler.

Usage:
    python -m src.capture              # capture all sources once
    python -m src.capture t18_update   # capture one source
    python -m src.capture --public     # only public sources (skip mocks)

Every capture stores the raw body (changed or not), then tries to parse it.
A parse failure never prevents the capture from being recorded.
"""
import json
import logging
import os
import random
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import certifi
import requests

from . import store

log = logging.getLogger(__name__)

# Contact email for the User-Agent. Set CONTACT_EMAIL in the environment (or .env)
# before any sustained run; the placeholder is only for smoke tests.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "CONTACT_EMAIL_HERE")
USER_AGENT = f"terminal-state-archive/0.2 (public-page archival; contact: {CONTACT_EMAIL})"

NWSA = "https://www.nwseaportalliance.com"

# (terminal, camera name, still-image URL), as linked from NWSA's cameras page.
CAMERAS = [
    ("T5", "ingate", "https://terminalcamera.tideworks.com/T5Sgate.jpg"),
    ("T18", "southgate", "https://terminalcamera.tideworks.com/T18southgate2.jpg"),
    ("T18", "northgate_out", "https://terminalcamera.tideworks.com/T18northgateout.jpg"),
    ("Husky", "cam2", "https://livecams.portsamerica.com/livecamImages/HuskyCam2.jpg"),
    ("Husky", "cam3", "https://livecams.portsamerica.com/livecamImages/HuskyCam3.jpg"),
    ("Husky", "cam4", "https://livecams.portsamerica.com/livecamImages/HuskyCam4.jpg"),
    ("PCT", "ingate", "https://gate.etstcm.com/gateimages/ingate.jpg"),
    ("PCT", "outgate", "https://gate.etstcm.com/gateimages/outgate.jpg"),
    ("PCT", "lot", "https://gate.etstcm.com/gateimages/lot.jpg"),
    ("WUT", "ingate", "https://camera2.uswut.com:1027/snapshot-ingate.jpg"),
    ("WUT", "lot", "https://camera2.uswut.com:1027/snapshot-flot.jpg"),
]
# Stills are ~100 KB each, so they are taken only while a gate could be open (Pacific time).
CAMERA_HOURS = {"hours": "5-18", "timezone": "America/Los_Angeles"}

# Source registry. `terminal` is the NWSA short name the exhibit groups by.
# `channel` says which stop-the-clock fact the source speaks to:
#   gate      - scheduled gate hours / closures
#   empties   - empty-return acceptance by line and size
#   bulletin  - port-wide notices (unscheduled closures, blanket restrictions)
#   turn_time - queue / in-terminal minutes (congestion)
#   camera    - gate camera stills: what the gate and its queue looked like
#   erd       - export receiving windows
#   appointment_system - outages of the appointment platform itself, from its public status page
#   slots     - appointment availability (mock until we have eModal access)
SOURCES: dict[str, dict] = {
    # --- export receiving (P25) ---
    "nwsa_erd": {
        "url": f"{NWSA}/cargo-operations/vessel-schedules-and-calendar/export-receiving-dates",
        "cadence_minutes": 30,
        # NWSA updates this page on weekday mornings; sample faster then to pin down the minute.
        "peak": {"minutes": 10, "hours": "6-10", "days": "mon-fri", "timezone": "America/Los_Angeles"},
        "terminal": None,
        "channel": "erd",
        "parser": "nwsa_erd",
    },
    "wut_erd": {
        "url": "https://www.uswut.com/schedule/vessel-export-receiving/",
        "cadence_minutes": 30,  # the leading indicator; NWSA's lag is measured against it
        "terminal": "WUT",
        "channel": "erd",
        "parser": "wut_erd",
    },
    # --- port-wide ---
    # The page itself: the port's definitions of the numbers, and which cameras it links. Its
    # numbers are filled in by script from the feed below, so the HTML only ever says "Connecting...".
    "nwsa_turn_times": {
        "url": f"{NWSA}/cargo-operations/cameras-truck-turn-times",
        "cadence_minutes": 120,
        "terminal": None,
        "channel": "turn_time",
        "parser": "nwsa_turn_times",
    },
    # The RFID turn-time feed that page connects to (socket.io). One "data" event holds every
    # terminal's queue / in-terminal / total minutes and the feed's own update time.
    "nwsa_turn_feed": {
        "url": "https://truckrfid-experience.azurewebsites.net",
        "cadence_minutes": 15,
        "terminal": None,
        "channel": "turn_time",
        "parser": "nwsa_turn_feed",
        "fetch": "socketio",
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
    # --- the appointment platform's own status page (Statuspage API, published for machine use).
    #     Its incident list carries its own timestamps, so it also covers dates before this
    #     archive started. Linked from NWSA's eModal resources page. ---
    "emodal_status": {
        "url": "https://status.cargosprint.com/api/v2/incidents.json",
        "cadence_minutes": 30,
        "terminal": None,
        "channel": "appointment_system",
        "parser": "statuspage_incidents",
    },
    # --- gate cameras: the stills NWSA embeds on its cameras page "with the permission of our
    #     terminals". Captured while gates can be open; see CAMERAS below. ---
    **{
        f"cam_{terminal.lower()}_{name}": {
            "url": url,
            "cadence_minutes": 15,
            "active_hours": CAMERA_HOURS,
            "terminal": terminal,
            "channel": "camera",
            "parser": "camera",
            "camera": name,
        }
        for terminal, name, url in CAMERAS
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
MIN_SECONDS_BETWEEN_REQUESTS = 5.0  # per host, enforced in _get for the scheduler and the CLI alike

# The mock appointments channel is off unless TSA_ENABLE_MOCK=1: it is not captured, not listed
# and not shown in the exhibit. Synthetic rows have no place on a public evidence page.
MOCK_ENABLED = os.environ.get("TSA_ENABLE_MOCK") == "1"


def active_sources() -> dict[str, dict]:
    return {k: v for k, v in SOURCES.items() if MOCK_ENABLED or not v.get("mock")}


_host_lock = threading.Lock()
_host_locks: dict[str, threading.Lock] = {}
_host_last: dict[str, float] = {}


CERTS_DIR = Path(__file__).resolve().parent / "certs"
# Hosts that serve only their own certificate and leave out the CA's intermediate. Browsers fetch the
# missing link themselves; Python does not. Verification stays on: the intermediate (published by the
# CA, kept in src/certs/) is added to the trusted roots, so the chain is still checked end to end.
MISSING_INTERMEDIATE = {"camera2.uswut.com:1027": "sectigo_public_server_auth_ca_dv_r36.pem"}
_bundles: dict[str, str] = {}


def _verify(host: str) -> bool | str:
    pem = MISSING_INTERMEDIATE.get(host)
    if pem is None:
        return True
    if host not in _bundles:
        bundle = tempfile.NamedTemporaryFile("wb", suffix=".pem", delete=False)
        bundle.write(Path(certifi.where()).read_bytes() + b"\n" + (CERTS_DIR / pem).read_bytes())
        bundle.close()
        _bundles[host] = bundle.name
    return _bundles[host]


def _get(url: str) -> requests.Response:
    """One GET, never closer than MIN_SECONDS_BETWEEN_REQUESTS to the previous one for the same host.

    The scheduler runs sources on a thread pool and several share a cadence, so without this
    they would hit nwseaportalliance.com in the same second.
    """
    host = urlsplit(url).netloc
    with _host_lock:
        lock = _host_locks.setdefault(host, threading.Lock())
    with lock:
        wait = _host_last.get(host, float("-inf")) + MIN_SECONDS_BETWEEN_REQUESTS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, verify=_verify(host))
        finally:
            _host_last[host] = time.monotonic()


class RawResponse:
    """The little of requests.Response that capture_source uses, for fetchers that are not one GET."""

    def __init__(self, content: bytes, status_code: int, content_type: str):
        self.content, self.status_code, self.headers = content, status_code, {"Content-Type": content_type}


def _fetch_socketio(url: str, event: str = "data", max_polls: int = 6) -> RawResponse:
    """Read one event from a socket.io server over HTTP long-polling, as a browser without
    websockets would: open, join the default namespace, poll until the event arrives, leave.

    The body stored is the polling payload exactly as the server sent it.
    """
    base = f"{url.rstrip('/')}/socket.io/"
    with requests.Session() as http:
        http.headers["User-Agent"] = USER_AGENT
        opened = http.get(base, params={"EIO": "4", "transport": "polling"}, timeout=TIMEOUT)
        opened.raise_for_status()
        sid = json.loads(opened.text[1:])["sid"]  # '0{"sid":...}'
        q = {"EIO": "4", "transport": "polling", "sid": sid}
        http.post(base, params=q, data="40", timeout=TIMEOUT).raise_for_status()
        try:
            for _ in range(max_polls):
                polled = http.get(base, params=q, timeout=TIMEOUT)
                polled.raise_for_status()
                packets = polled.content.split(b"\x1e")
                if any(pk.startswith(b'42["' + event.encode() + b'"') for pk in packets):
                    return RawResponse(polled.content, polled.status_code, "application/x-socketio-polling")
                if b"2" in packets:  # server ping; answer or it drops us
                    http.post(base, params=q, data="3", timeout=TIMEOUT)
            raise requests.ConnectionError(f"no '{event}' event from {url} in {max_polls} polls")
        finally:
            try:
                http.post(base, params=q, data="41", timeout=5)
            except requests.RequestException:
                pass


EXTENSIONS = (("json", "json"), ("jpeg", "jpg"), ("png", "png"), ("socketio", "txt"))


def _extension(content_type: str | None) -> str:
    ct = (content_type or "").lower()
    return next((ext for needle, ext in EXTENSIONS if needle in ct), "html")


def _fetch(url: str) -> requests.Response:
    """GET with one retry on connection error / 5xx."""
    try:
        resp = _get(url)
        if resp.status_code >= 500:
            raise requests.HTTPError(f"{resp.status_code} from {url}", response=resp)
        return resp
    except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as first:
        log.warning("retrying %s after %s: %s", url, RETRY_AFTER_SECONDS, first)
        time.sleep(RETRY_AFTER_SECONDS)
        return _get(url)


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
        resp = _fetch_socketio(src["url"]) if src.get("fetch") == "socketio" else _fetch(src["url"])
        ext = _extension(resp.headers.get("Content-Type"))
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
    targets = args or [s for s, v in active_sources().items() if not (public_only and v.get("mock"))]
    for source_id in targets:
        if source_id not in SOURCES:
            sys.exit(f"unknown source: {source_id} (known: {', '.join(SOURCES)})")
        capture_source(source_id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
