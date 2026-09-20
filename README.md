# Terminal State Archive

Captures the public, mutable pages describing Seattle-Tacoma container terminal
state (gate hours, empty-return matrices, bulletins, ERDs, turn times), stores every
capture immutably with timestamp + hash, parses it into per-day facts, and renders a
dated exhibit for demurrage / detention disputes. See `docs/BUILD_BRIEF.md`.

## Run everything: Docker

```bash
cp .env.example .env          # set CONTACT_EMAIL (goes in the scraper's User-Agent)
docker compose up --build
```

- http://localhost:3000 — the exhibit UI (Next.js)
- http://localhost:8100 — the archive API and the plain capture dashboard
- the `scheduler` service captures every source on its cadence into `./data/`

`./data/` is bind-mounted, so captures persist across restarts and the SQLite file
(`data/archive.db`) can be opened read-only from the host at any time. Nothing in
`data/` is ever rewritten.

Settings live in `.env` (see `.env.example`): `CONTACT_EMAIL`, `HEALTHCHECK_PING_URL` (hourly
health ping to a healthchecks.io-style monitor, so a broken or stopped archive sends an email), and
`TSA_ENABLE_MOCK`. The mock eModal appointments channel is **off by default**: not captured, not
listed, and its column is left out of the exhibit. `TSA_ENABLE_MOCK=1` switches it on for UI work;
its rows are flagged `is_mock=1` everywhere.

## Run for development (no Docker)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
CONTACT_EMAIL=you@example.com .venv/bin/python -m src.capture     # one-shot, all sources
.venv/bin/python -m src.parse --all                                # (re)parse existing captures
.venv/bin/uvicorn src.web:app --reload --port 8100                 # API + dashboard
cd web && npm install && npm run dev                               # UI at http://localhost:3000
```

Use `localhost`, not `127.0.0.1`, for the Next dev server.

## Tests and health

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q          # parsers against frozen pages + store/API invariants
.venv/bin/python -m src.health               # live checks on the running archive; exit 1 on any failure
docker compose run --rm api pytest -q        # same, inside the image
```

- `tests/test_parsers.py`: every fact a human verified on the live pages on 2026-09-20, and every
  parser bug fixed that day, as assertions against `tests/fixtures/` (real captures, byte for byte).
- `tests/test_store_api.py`: append-only custody, hash round-trip, parser failure never blocks a
  capture, mock rows always flagged, gaps read as unknown, Pacific day boundaries, sandboxed raw view.
- `src/health.py`: the daily manual check automated — freshness per source, error counts, latest
  capture parsed to rows, gate table still covers today, empty-rule counts stable, mock flags, raw
  files present, disk. Runs hourly in the scheduler (writes `data/health.json`), and at `/api/health`.
  Alerts, when added, wrap this.

## Layout

- `src/store.py` — append-only SQLite captures + content-addressed raw bodies; additive migrations
- `src/capture.py` — source registry (11 sources, one mock) and fetchers; requests to one host are spaced 5 s apart
- `src/parse.py` — per-source parsers → `parsed_rows` (gate days, empty rules, notices, ERDs, turn times, slots)
- `src/mock_emodal.py` — the labeled MOCK appointments channel
- `src/api.py` — JSON: `/api/sources`, `/api/captures`, `/api/parsed`, `/api/exhibit`
- `src/web.py` — FastAPI app: dashboard pages, raw viewer, mounts the API
- `src/scheduler.py` — APScheduler loop per source cadence, plus the hourly health report
- `src/health.py` — live checks; `python -m src.health`
- `tests/` — parser and invariant tests; `tests/fixtures/` are frozen real captures
- `web/` — Next.js exhibit UI (see `web/README.md`)
- `docs/DAILY_CHECK.md` — the ten-minute manual check to run each day while it collects
- `ui/index.html` — earlier single-file UI, superseded by `web/`
- `data/` — gitignored; `archive.db` + raw bodies

## Channels and what they settle

| channel | source(s) | settles | status |
|---|---|---|---|
| gate | five terminal update pages | was the gate scheduled open that day | working |
| empties | terminal pages, WUT matrix | were this line's empties (by size, drop/pick) accepted | working |
| bulletin | NWSA trucker notices | unscheduled closures, blanket restrictions | working |
| erd | NWSA + WUT export receiving | did the export window move | working |
| turn_time | NWSA turn times | congestion | page is JS-rendered; numbers not yet captured |
| slots | eModal `move/slots` | was an appointment available | MOCK, off unless `TSA_ENABLE_MOCK=1` |
