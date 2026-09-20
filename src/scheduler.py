"""Long-running scheduler: captures each source on its cadence, and self-checks hourly.

Usage:
    python -m src.scheduler
"""
import json
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from . import health, store
from .capture import SOURCES, capture_source

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def write_health() -> None:
    """Hourly self-check into data/health.json; failures are logged at WARNING so they stand out."""
    report = health.run()
    (store.DATA_DIR / "health.json").write_text(json.dumps(report, indent=1))
    for c in report["checks"]:
        if not c["ok"]:
            logging.warning("HEALTH %s %s: %s", c.get("source") or "-", c["name"], c["detail"])
    logging.info("health: %s", "ok" if report["ok"] else f"{report['failed']} failed")


def main() -> None:
    # Capture everything once at startup, then intervals take over.
    for source_id in SOURCES:
        capture_source(source_id)

    sched = BlockingScheduler(timezone="UTC")
    for source_id, src in SOURCES.items():
        sched.add_job(
            capture_source,
            "interval",
            minutes=src["cadence_minutes"],
            args=[source_id],
            id=source_id,
        )
    sched.add_job(write_health, "interval", minutes=60, id="health")
    logging.info(
        "scheduler running: %s",
        {k: f"{v['cadence_minutes']}min" for k, v in SOURCES.items()},
    )
    sched.start()


if __name__ == "__main__":
    main()
