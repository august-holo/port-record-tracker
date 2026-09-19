# Terminal State Archive

Captures the public, mutable pages describing Seattle-Tacoma container terminal
state (ERDs, gate hours, bulletins, turn times), stores every capture immutably
with timestamp + hash, and diffs consecutive captures. See `docs/BUILD_BRIEF.md`.

Python prototype (Phase 0/1); port to Rust for the live implementation is planned.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Set a real contact email in `src/capture.py` (`USER_AGENT`) before any sustained run.

## Run

```bash
.venv/bin/python -m src.capture            # one-shot, all sources
.venv/bin/python -m src.capture nwsa_erd   # one-shot, one source
.venv/bin/python -m src.scheduler          # long-running, per-source cadences
.venv/bin/uvicorn src.web:app --port 8100  # read-only UI at http://localhost:8100
```

## Layout

- `src/store.py` — append-only SQLite captures table + content-addressed raw bodies (`data/raw/`)
- `src/capture.py` — source registry and fetchers
- `src/scheduler.py` — APScheduler loop per the cadences in the brief
- `src/web.py` — read-only FastAPI UI: dashboard, capture history with change markers, raw viewer
- `data/` — gitignored; `archive.db` + raw bodies live here

## Phase 0 (current)

Prove the NWSA ERD page's update cadence: capture hourly for three days, then
answer (1) when exactly the page changes each day, (2) whether the GovDelivery
ERD subscription sends a digest or a change alert (manual step: subscribe an
inbox). Answers go to the Research Pack.
