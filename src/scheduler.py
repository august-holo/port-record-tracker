"""Long-running scheduler: captures each source on its cadence.

Usage:
    python -m src.scheduler
"""
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from .capture import SOURCES, capture_source

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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
    logging.info(
        "scheduler running: %s",
        {k: f"{v['cadence_minutes']}min" for k, v in SOURCES.items()},
    )
    sched.start()


if __name__ == "__main__":
    main()
