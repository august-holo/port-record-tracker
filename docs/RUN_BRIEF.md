# Run Brief: the 14-day capture

**For:** the coding session on `terminal-state-archive`
**Goal:** leave the archive running unattended for 14 days (target: start Sat 19 Sep, run through Sat 3 Oct 2026) and come back to data that answers the five questions in §6, queryable from the laptop without opening the code.
**Companion:** `docs/BUILD_BRIEF.md` is the original design. This brief is only what has to change before the run starts. Nothing here alters the chain-of-custody rules in the build brief (append-only captures, content-addressed raw bodies, raw stored even when unchanged).

---

## 1. Where the repo is right now (verified 19 Sep, 18:30 PT)

- `src/capture.py`, `src/store.py`, `src/scheduler.py`, `src/web.py` exist and work. Four captures in `data/archive.db`, all from 18:28 PT on the 18th: `nwsa_erd` ×2, `wut_erd` ×1, `nwsa_turn_times` ×1. `nwsa_bulletins` is registered but has never been captured.
- The scheduler has never been left running. There is no process supervision.
- `USER_AGENT` still says `CONTACT_EMAIL_HERE`.
- No parsers. Change detection is on the raw page hash only.
- Pages are server-rendered and parseable without a browser:
  - NWSA ERD page: 11 `<table>` elements. The five terminal ERD tables are the ones with ≥4 rows (row counts seen: 4, 11, 4, 6, 12). The WUT section is the table whose header is `Vessel Name | SVC | 1st/ERD | CUT-OFF | ETB | ETD`. Other terminals' headers differ; identify each table by the nearest preceding heading, not by position.
  - WUT page: one 8-column table: `SSCO | Vessel Voyage No | Vessel Name | SVC | 1st/ERD | CUT-OFF | ETB | ETD`. Dates are `MM-DD-YYYY HHMM`; ETB can be the literal `WORKING`.
  - Turn times page: 5 tables; cells are `N/A` when fewer than 20 trucks passed in the hour (12 `N/A` cells in the 18:28 capture).
- The single snapshot already shows the P25 post's claim. Same-minute capture, vessel CHARLOTTE SCHULTE: WUT's own page says ERD 09-23 0700 / cutoff 09-28 1600; NWSA's compiled page says ERD 09-25 0700 / cutoff 09-25 1600. Keep those two raw files; they are the Monday post's evidence.

## 2. Work items, in order

### A. Contact email (5 min)
Put a real address in `USER_AGENT`. Do this first; nothing else should run sustained without it.

### B. Parsers (the main work)
Add `src/parse.py` with one parser per source. A parser takes raw bytes and returns a list of row dicts. Parsers may raise; a failed parse must never prevent the raw capture from being recorded (parse after `record_capture`, catch everything, log it, store the error).

Row shapes:

| source | one row per | fields |
|---|---|---|
| `wut_erd` | vessel/voyage | `terminal='WUT'`, `ssco`, `voyage`, `vessel`, `svc`, `erd`, `cutoff`, `etb`, `etd` |
| `nwsa_erd` | (terminal, vessel[, voyage]) | `terminal` (T5 / T18 / Husky / PCT / WUT, from the heading), then whatever date columns that terminal's table has, normalised to the names above where the meaning matches; keep any extra columns under their original header |
| `nwsa_turn_times` | (terminal, metric) | `terminal`, `queue_min`, `in_terminal_min`, each nullable (`N/A` → NULL, and keep a boolean `na` so "gate effectively closed" is queryable) |
| `nwsa_bulletins` | notice | `posted_date`, `title`, `body_text`, `url` if linked |

Store them in a new table, never by rewriting `captures`:

```sql
CREATE TABLE parsed_rows (
  id INTEGER PRIMARY KEY,
  capture_id INTEGER NOT NULL REFERENCES captures(id),
  source_id TEXT NOT NULL,
  terminal TEXT,
  entity_key TEXT NOT NULL,     -- e.g. 'WUT|CHARLOTTE SCHULTE|ARET/0614/2026' or 'T5|<vessel>'
  row_json TEXT NOT NULL,       -- canonical JSON, sorted keys
  row_hash TEXT NOT NULL        -- sha256 of row_json
);
CREATE INDEX idx_parsed_entity ON parsed_rows(source_id, entity_key, capture_id);
CREATE TABLE parse_errors (capture_id INTEGER, source_id TEXT, error TEXT, at TEXT);
```

Keep raw dates as captured strings in `row_json`, and add normalised ISO fields alongside (`erd_iso`, `cutoff_iso`, …) in America/Los_Angeles. Both, not one.

Add a backfill: `python -m src.parse --all` parses every capture without parsed rows. Run it on the four existing captures; the WUT-vs-NWSA CHARLOTTE SCHULTE difference must show up in `parsed_rows` before you go further.

### C. Change detection on parsed content, not page hash
The NWSA page carries site chrome (the bulletins sidebar, at minimum) that will churn, so raw-hash transitions on `nwsa_erd` will be mostly noise. Add:

- `captures.parsed_hash` (nullable column, `ALTER TABLE ... ADD COLUMN`): sha256 over the sorted list of `row_hash`es for that capture. For `nwsa_erd`, also compute one per terminal and store as JSON in `captures.parsed_hash_by_terminal`.
- A `changes` table filled at parse time by comparing each capture's rows with the previous *successfully parsed* capture of the same source:

```sql
CREATE TABLE changes (
  id INTEGER PRIMARY KEY,
  source_id TEXT, terminal TEXT, entity_key TEXT,
  field TEXT, old_value TEXT, new_value TEXT,
  kind TEXT,                    -- 'added' | 'removed' | 'changed'
  prev_capture_id INTEGER,      -- last capture where old_value held
  capture_id INTEGER,           -- first capture where new_value appeared
  prev_fetched_at TEXT, fetched_at TEXT
);
```

The interval `(prev_fetched_at, fetched_at]` is the uncertainty window for when the page actually changed. That is why cadence matters (D).

Keep the raw-hash change markers in the web UI too; they are still the proof that the page bytes changed.

### D. Cadence
Current cadences (NWSA ERD 60 min, WUT 120, turn times 15, bulletins 60) cannot answer "what minute does the NWSA page change" or measure WUT→NWSA lag to better than an hour or two. Change to:

| source | cadence |
|---|---|
| `nwsa_erd` | every 10 min 06:00–11:00 PT Mon–Fri; every 30 min otherwise |
| `wut_erd` | every 30 min, always (this is the leading indicator; the lag is measured against it) |
| `nwsa_turn_times` | every 15 min (unchanged) |
| `nwsa_bulletins` | every 60 min (unchanged) |

Load on `nwseaportalliance.com` at peak: 6 + 4 + 1 requests/hour ≈ one every 5–6 min. Fine. APScheduler supports this with two cron jobs for `nwsa_erd` (weekday-morning, and everything else) instead of one interval job; give them distinct ids. Add a small jitter (0–60 s) so requests don't land on the exact minute.

Add a retry: one retry after 20 s on connection error / 5xx, then record the failure. Timeout stays 30 s.

### E. Running unattended
This is where 14-day runs die on a laptop. Do all of these:

1. **Supervision.** macOS: a `launchd` user agent (`~/Library/LaunchAgents/io.holotekt.terminal-state-archive.plist`) with `RunAtLoad` and `KeepAlive` true, `WorkingDirectory` set to the repo, stdout/stderr to `data/logs/scheduler.log`. Linux: a systemd user unit with `Restart=always`. Put the plist/unit file in `ops/` in the repo with an `ops/install.sh` that copies and loads it, and `ops/uninstall.sh`.
2. **Sleep.** A closed-lid laptop stops the scheduler. Either run it on a machine that stays awake, or set the launchd job to run under `caffeinate -i` and disable sleep on power in Energy settings. Verify, don't assume: close the lid for 20 minutes and check the capture log.
3. **SQLite concurrency.** `PRAGMA journal_mode=WAL` in `store.connect()`, plus `busy_timeout=5000`. The web UI, the CLI and a Cowork session will read the DB while the scheduler writes.
4. **Logs.** One line per capture (source, status, raw hash prefix, parsed hash prefix, changed yes/no, ms). Rotate at 10 MB. A daily line at 00:05 UTC summarising captures/errors/changes per source for the last 24 h.
5. **Disk.** ~65 KB per capture × ~300 captures/day ≈ 20 MB/day, ~300 MB for the run. Fine; no dedupe. Check `data/` is on the local disk, not a synced folder that could stall.
6. **Clock.** DB stays UTC. Everything user-facing renders America/Los_Angeles, and says so.

### F. Querying from the laptop
Three ways, all read-only. Build the CLI first; it is the one that gets used.

**CLI** — `python -m src.query <cmd>` (add a `bin/tsa` wrapper that activates the venv):

| command | shows |
|---|---|
| `status` | per source: last capture (PT, and "N min ago"), captures today, parsed OK/failed today, distinct parsed versions, errors, and a **STALE** flag if last capture is older than 2× cadence. Exit code 1 if anything is stale, so it can be used as a health check. |
| `changes [--source S] [--since 24h] [--terminal T]` | the `changes` table, newest first, with the uncertainty window |
| `vessel "<name>"` | timeline of every field value for that vessel across *both* WUT and NWSA sources, so the lag is visible by eye |
| `compare` | WUT's own table vs NWSA's WUT section from the latest captures, side by side, differences highlighted (this is the Monday-morning check) |
| `gaps` | any interval between consecutive captures of a source > 2× cadence: when it started, how long, what the log said |
| `cadence --source nwsa_erd` | for each day, the PT time of the first capture whose parsed hash differed from the previous day's last (the "what minute does it update" answer) |
| `export [--csv|--json] [--out data/exports/]` | `captures`, `parsed_rows`, `changes` as flat files for the writing session |

**Web UI** — `src/web.py` already serves `/`, `/captures/{source}`, `/raw/{hash}` on `:8100`. Add `/changes`, `/vessel/{name}`, `/compare`, `/gaps`, and JSON twins under `/api/...` with the same output as the CLI. Run it under launchd too (second plist), bound to `127.0.0.1` only.

**Direct DB** — the connected folder means a Cowork session can open `data/archive.db` read-only from the mounted folder; that is how the 19 Sep numbers in §1 were pulled. Keep it possible: WAL mode (E3), no encryption, no in-memory-only state. Add `docs/QUERIES.md` with five copy-paste SQL queries (latest per source, changes last 24 h, one vessel's history, gaps, N/A turn-time cells by hour).

### G. Acceptance before walking away
Do these in order and paste the results into `docs/RUN_LOG.md` with timestamps:

1. `python -m src.parse --all` on the existing captures; `python -m src.query compare` shows the CHARLOTTE SCHULTE row differing between sources.
2. Install the launchd job. `kill -9` the scheduler process. It is back within 30 s and captures resume.
3. Close the lid (or sleep the machine) for 20 min. `python -m src.query gaps` afterwards shows either no gap or a gap that ended when the machine woke.
4. Let it run for 2 hours. `status` shows all four sources captured, zero STALE, parsed rows for each.
5. Simulate a change: temporarily point a test source at a local file, edit one date, confirm exactly one row lands in `changes` with the right old/new/interval. Remove the test source.
6. Confirm `data/logs/scheduler.log` is being written and rotated config is in place.
7. Commit. Tag `run-2026-09-19`.

Then don't touch it. Monday 09:30 PT: `tsa compare` and `tsa vessel "CHARLOTTE SCHULTE"` — that's the check for the post.

## 3. Rules that don't change
- Never delete or rewrite a row in `captures` or a file in `data/raw/`. New columns and new tables only. If a migration is needed, it is additive and recorded in `src/store.py` with a version number.
- Store raw on every fetch, changed or not.
- Parsers can fail. Captures can't be blocked by a parser.
- One honest user agent, well under one request a minute per host.

## 4. Out of scope for this run
Gate schedules, terminal update pages, DCLI, the D&D exhibit, the Rust port, GovDelivery subscription testing. All of that is after 3 Oct.

## 5. What "done" looks like on 3 Oct
`tsa export` produces files from which someone with no access to the code can answer §6. If any of the five needs a query that doesn't exist yet, that is a bug in this brief, not in the data; fix the query, never the data.

## 6. The five questions the data has to answer
1. **Cadence.** At what PT minute does the NWSA ERD page change each weekday, and does it ever change on weekends or outside 06:00–11:00?
2. **Lag.** For each vessel whose dates changed on WUT's page, how many hours until the same change appeared on NWSA's WUT section (with the uncertainty interval)?
3. **Count and direction.** How many receiving windows (ERD or cutoff) moved during the run, and how many moved earlier (the direction that strands a box)?
4. **Never corrected.** How many windows changed on WUT's page and were still different on NWSA's page when the cutoff passed?
5. **Effective gate closures.** By terminal and hour-of-day, how often the turn-times page showed `N/A` (fewer than 20 trucks/hour), i.e. when the gate was effectively closed. (For the free-time-clock follow-up, not P25.)
