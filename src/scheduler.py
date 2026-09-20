"""Long-running scheduler: captures each source on its cadence, and self-checks hourly.

Usage:
    python -m src.scheduler

Set HEALTHCHECK_PING_URL (a healthchecks.io-style check URL) to be told when the archive
is unhealthy or has stopped: the hourly self-check pings it on success and <url>/fail on
failure, and the monitor alerts when the pings stop altogether.
"""
import json
import logging
import os

import requests
from apscheduler.schedulers.blocking import BlockingScheduler

from . import health, manifest, store
from .capture import active_sources, capture_source

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HEALTHCHECK_PING_URL = os.environ.get("HEALTHCHECK_PING_URL", "").rstrip("/")


def ping_monitor(report: dict) -> None:
    if not HEALTHCHECK_PING_URL:
        return
    failed = [f"{c.get('source') or '-'} {c['name']}: {c['detail']}" for c in report["checks"] if not c["ok"]]
    url = HEALTHCHECK_PING_URL if report["ok"] else f"{HEALTHCHECK_PING_URL}/fail"
    try:
        requests.post(url, data="\n".join(failed).encode(), timeout=10)
    except requests.RequestException as exc:
        logging.warning("health ping failed: %s", exc)


def write_health() -> None:
    """Hourly self-check into data/health.json; failures are logged at WARNING so they stand out."""
    report = health.run()
    (store.DATA_DIR / "health.json").write_text(json.dumps(report, indent=1))
    for c in report["checks"]:
        if not c["ok"]:
            logging.warning("HEALTH %s %s: %s", c.get("source") or "-", c["name"], c["detail"])
    logging.info("health: %s", "ok" if report["ok"] else f"{report['failed']} failed")
    ping_monitor(report)


def main() -> None:
    sources = active_sources()
    # Capture everything once at startup, then intervals take over.
    for source_id in sources:
        capture_source(source_id)

    # A late job still runs (the default drops anything more than a second late), and
    # runs missed while the machine slept collapse into one.
    sched = BlockingScheduler(timezone="UTC", job_defaults={"misfire_grace_time": 300, "coalesce": True})
    for source_id, src in sources.items():
        window = src.get("active_hours")
        if window:
            sched.add_job(
                capture_source,
                "cron",
                minute=f"*/{src['cadence_minutes']}",
                hour=window["hours"],
                timezone=window["timezone"],
                jitter=120,  # spreads the cameras out instead of queueing them on the minute
                args=[source_id],
                id=source_id,
            )
            continue
        sched.add_job(
            capture_source,
            "interval",
            minutes=src["cadence_minutes"],
            args=[source_id],
            id=source_id,
        )
        peak = src.get("peak")
        if peak:
            sched.add_job(
                capture_source,
                "cron",
                minute=f"*/{peak['minutes']}",
                hour=peak["hours"],
                day_of_week=peak["days"],
                timezone=peak["timezone"],
                jitter=60,
                args=[source_id],
                id=f"{source_id}_peak",
            )
    sched.add_job(write_health, "interval", minutes=60, id="health")
    sched.add_job(manifest.write_recent, "interval", minutes=60, id="manifest")
    logging.info(
        "scheduler running: %s",
        {k: f"{v['cadence_minutes']}min" for k, v in sources.items()},
    )
    write_health()
    manifest.write_recent()
    sched.start()


if __name__ == "__main__":
    main()
