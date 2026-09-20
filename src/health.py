"""Live health checks: the daily manual check, automated.

    python -m src.health            # print the report; exit 1 if any check fails
    python -m src.health --json     # machine-readable

Also served at GET /api/health and run hourly by the scheduler into data/health.json.
Each check is (name, ok, detail). Alerts, when they come, wrap this: anything that
fails here is worth a message; nothing else is.
"""
import json
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import store
from .capture import active_sources

PT = ZoneInfo("America/Los_Angeles")
DISK_LIMIT_GB = 20
ERROR_LIMIT_24H = 6
RULE_DROP_RATIO = 0.5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expected_now(src: dict, now: datetime) -> bool:
    """False for a source with active_hours when `now` is outside them (or the window has only just opened)."""
    window = src.get("active_hours")
    if not window:
        return True
    first, last = (int(h) for h in window["hours"].split("-"))
    local = now.astimezone(ZoneInfo(window["timezone"]))
    opened = local.replace(hour=first, minute=0, second=0, microsecond=0)
    return first <= local.hour <= last and local - opened >= 2 * timedelta(minutes=src["cadence_minutes"])


def run() -> dict:
    conn = store.connect()
    conn.row_factory = None
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, source: str | None = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "source": source})

    now = _now()
    since_24h = (now - timedelta(hours=24)).isoformat(timespec="seconds")

    for sid, src in active_sources().items():
        cadence = timedelta(minutes=src["cadence_minutes"])
        last = conn.execute(
            "SELECT fetched_at FROM captures WHERE source_id = ? AND content_hash IS NOT NULL ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        if not last:
            add("fresh", False, "no successful capture yet", sid)
            continue
        age = now - datetime.fromisoformat(last[0])
        if _expected_now(src, now):
            add("fresh", age <= 2 * cadence, f"last capture {int(age.total_seconds() // 60)} min ago (cadence {src['cadence_minutes']})", sid)
        else:
            add("fresh", True, f"outside capture hours ({src['active_hours']['hours']} PT); last capture {int(age.total_seconds() // 60)} min ago", sid)

        errs = conn.execute(
            "SELECT COUNT(*) FROM captures WHERE source_id = ? AND error IS NOT NULL AND fetched_at >= ?", (sid, since_24h)
        ).fetchone()[0]
        add("errors_24h", errs <= ERROR_LIMIT_24H, f"{errs} failed fetches in 24h", sid)

        # The latest successful capture must have produced rows (a page redesign shows up here first).
        latest = conn.execute(
            "SELECT id FROM captures WHERE source_id = ? AND content_hash IS NOT NULL ORDER BY id DESC LIMIT 1", (sid,)
        ).fetchone()[0]
        n_rows = conn.execute("SELECT COUNT(*) FROM parsed_rows WHERE capture_id = ?", (latest,)).fetchone()[0]
        if src.get("parser"):
            add("parsed_latest", n_rows > 0, f"{n_rows} parsed rows from capture #{latest}", sid)
        perr = conn.execute(
            "SELECT COUNT(*) FROM parse_errors WHERE source_id = ? AND at >= ?", (sid, since_24h)
        ).fetchone()[0]
        add("parse_errors_24h", perr == 0, f"{perr} parse errors in 24h", sid)

        if src.get("parser") == "terminal_page" and src.get("terminal") in ("T18", "T5", "PCT"):
            # These three publish a gate table; it must still cover today (catches a stale week or a broken parser).
            horizon = date.today().isoformat()
            future = conn.execute(
                "SELECT COUNT(*) FROM parsed_rows WHERE capture_id = ? AND kind = 'gate_day' AND json_extract(row_json, '$.date_iso') >= ?",
                (latest, horizon),
            ).fetchone()[0]
            add("gate_horizon", future > 0, f"{future} gate days on/after {horizon} in latest capture", sid)

        if src["channel"] in ("gate", "empties") and src.get("terminal") in ("T18", "T5", "WUT"):
            # Empty-rule count should not collapse between consecutive captures.
            prev = conn.execute(
                "SELECT id FROM captures WHERE source_id = ? AND content_hash IS NOT NULL AND id < ? ORDER BY id DESC LIMIT 1",
                (sid, latest),
            ).fetchone()
            cur_n = conn.execute(
                "SELECT COUNT(*) FROM parsed_rows WHERE capture_id = ? AND kind = 'empty_rule'", (latest,)
            ).fetchone()[0]
            if prev:
                prev_n = conn.execute(
                    "SELECT COUNT(*) FROM parsed_rows WHERE capture_id = ? AND kind = 'empty_rule'", (prev[0],)
                ).fetchone()[0]
                ok = prev_n == 0 or cur_n >= RULE_DROP_RATIO * prev_n
                add("empty_rules_stable", ok, f"{cur_n} empty rules now vs {prev_n} in previous capture", sid)

    # Mock hygiene: mock URLs are flagged, real ones are not.
    bad = conn.execute(
        "SELECT COUNT(*) FROM captures WHERE (url LIKE 'mock://%' AND is_mock = 0) OR (url NOT LIKE 'mock://%' AND is_mock = 1)"
    ).fetchone()[0]
    add("mock_flags", bad == 0, f"{bad} captures with a wrong is_mock flag")

    # Custody: every capture with a hash has its raw file.
    missing = 0
    for (h,) in conn.execute("SELECT DISTINCT content_hash FROM captures WHERE content_hash IS NOT NULL"):
        if store.find_raw(h) is None:
            missing += 1
    add("raw_files_present", missing == 0, f"{missing} referenced raw bodies missing from disk")

    # Disk.
    usage = shutil.disk_usage(store.DATA_DIR)
    used_gb = sum(p.stat().st_size for p in store.RAW_DIR.rglob("*") if p.is_file()) / 1e9 if store.RAW_DIR.exists() else 0
    add("disk", used_gb < DISK_LIMIT_GB and usage.free > 1e9, f"raw store {used_gb:.2f} GB; {usage.free / 1e9:.1f} GB free")

    conn.close()
    failed = [c for c in checks if not c["ok"]]
    return {
        "ok": not failed,
        "checked_at_utc": now.isoformat(timespec="seconds"),
        "checked_at_pt": now.astimezone(PT).isoformat(timespec="minutes"),
        "failed": len(failed),
        "checks": checks,
    }


def main() -> None:
    report = run()
    if "--json" in sys.argv:
        print(json.dumps(report, indent=1))
    else:
        for c in report["checks"]:
            mark = "ok " if c["ok"] else "FAIL"
            src = f"[{c['source']}] " if c["source"] else ""
            print(f"{mark} {src}{c['name']}: {c['detail']}")
        print(f"\n{'all good' if report['ok'] else str(report['failed']) + ' check(s) failed'} · {report['checked_at_pt']} PT")
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
