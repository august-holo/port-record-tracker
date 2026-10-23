# Build Brief: Terminal State Archive

A handoff for a coding session. Everything a fresh session needs to start building without re-deriving the why. Written 2026-09-17. Context docs: `../Terminal State Archive.md` (the case for it), `../ERD Feed Opportunity.md` (the first customer), `Research Pack.md` and `Validation Card.md` in this folder (the facts it has to be able to prove).

## What it is, in one paragraph

A scraper that captures the public, mutable pages describing the state of the Seattle-Tacoma container terminals (gate hours, empty-return rules by line, export receiving windows, appointment availability, queue times, chassis inventory), stores every capture immutably with a timestamp and a hash, diffs consecutive captures, and lets a user ask "what was terminal X's state on date Y" and get back a dated exhibit. Two customers, same data: a dispatcher who wants an alert when an export window moves (forward-looking), and a broker disputing a demurrage invoice who needs to prove the box couldn't have moved (backward-looking). Build the capture layer once; the two products are views on it.

## Why it's shaped this way

The demurrage dispute turns on five facts the FMC's 2020 incentive principle names: was the box available, was the gate open, were empties being accepted, could an appointment be had, was there a government hold. Four of the five are published daily by the port or the terminals and then overwritten. Nobody keeps history. The value is the *history and the diff*, not the current value, which anyone can read. So: never overwrite, always timestamp, and make the diff a first-class object.

## Sources

All public HTML unless noted. Capture the raw page every time; parse into fields where the structure allows; keep the raw regardless.

| Source | URL | What to capture | Cadence | Notes |
|---|---|---|---|---|
| NWSA export receiving dates | https://www.nwseaportalliance.com/cargo-operations/vessel-schedules-and-calendar/export-receiving-dates | Per-terminal tables: vessel/voyage, receiving open, reefer open, cutoff, ETA/ETB, "authorized" vs "estimated" status | Hourly (page updates weekdays by 9 a.m.; hourly catches the update and proves the cadence) | Five terminals on one page; table shapes differ per terminal |
| WUT export receiving | https://www.uswut.com/schedule/vessel-export-receiving/ | SSCO, voyage, vessel, SVC, 1st/ERD, cutoff, ETB, ETD; prose reefer rules | Every 2 hours | Cleanest single-terminal table; good first parser |
| Terminal update pages (T5, T18, Husky, PCT, WUT) | Linked from https://www.nwseaportalliance.com/cargo-operations/terminals | Gate hours, closures, empty-return rules by line, appointment requirements, holiday schedules; mostly prose | Every 2 hours | Prose; store raw, extract with a small rules layer, expect to hand-tune |
| NWSA gate schedules | https://www.nwseaportalliance.com/cargo-operations/terminals/gate-schedules | Gate hours by terminal by day | Every 2 hours | |
| NWSA trucker bulletins | https://www.nwseaportalliance.com/cargo-operations/trucker-resources/trucker-news-updates | Dated notices: empties accepted/refused, appointment changes, closures | Hourly; also subscribe the GovDelivery feed to an inbox and archive the emails | Bulletins are the best "what changed and when" source; they're dated by the port itself |
| NWSA queue / turn times | https://www.nwseaportalliance.com/cargo-operations/cameras-truck-turn-times | Queue time and in-terminal time per terminal (rolling 60-min average, refreshes every 15 min; "N/A" when <20 trucks) | Every 15 min | The one numeric time series; captures gate congestion and effective closures |
| eModal appointment capacity dashboard | Linked from NWSA trucker resources | Available appointment slots by terminal/time, if rendered publicly | Every 15 min if public; else skip and note | May require login; test first. If login-gated, it's out of scope for v1 |
| DCLI chassis inventory | https://dcli.com/region/pacific-northwest/ | Chassis count by size class per facility | Every 2 hours (page updates up to 3x/day) | "No chassis" is a common unavoidable-dwell cause |
| TRAC pool notices | https://www.nwseaportalliance.com/cargo-operations/trucker-resources/trucker-news-updates/trac-pacific-northwest-pool-operations and TRAC's site | Pool status notices | Daily | Low volume |

Start with the first two rows and the turn-time feed. Add the rest once capture and diff are stable.

## Architecture (keep it boring)

1. **Capture.** A scheduler runs fetchers per source on the cadence above. Each fetch stores `{source_id, fetched_at (UTC), url, http_status, content_hash, raw_body}`. Store the raw body even if unchanged (cheap, and it proves the page said the same thing at that time). Identify the user agent honestly; rate-limit to well under one request per minute per host.
2. **Parse.** Per-source parsers turn raw into rows: for ERD tables, one row per (terminal, vessel, voyage) with the date fields; for gate schedules, one row per (terminal, date, open, close); for bulletins, one row per notice with its own date and text; for turn times, one row per (terminal, fetched_at, queue_min, in_terminal_min). Parsers are allowed to fail; a failed parse still leaves the raw capture.
3. **Diff.** For each source, compare the parsed rows of consecutive captures. Emit `change` records: `{source_id, key (e.g., terminal+vessel+voyage), field, old, new, first_seen_at, last_seen_at}`. This is the product for the ERD customer.
4. **Query.** "Terminal X, date range Y–Z" returns: gate hours in force, bulletins dated in range, empty rules in force, ERD rows for vessels in range, turn-time series, chassis series, each with capture timestamps.
5. **Exhibit.** Render a query result as a dated PDF: one page per fact type, capture timestamps on every line, hash of each raw capture in a footer. This is the product for the D&D customer.
6. **Alerts.** Subscribe a user to keys (a vessel/voyage, a terminal, a line's empties). On a `change` record matching, send email/SMS. Later: webhook.

Storage: SQLite or Postgres for rows and changes; object storage (or a directory) for raw bodies keyed by hash. Nothing fancy. The whole dataset is small (a few dozen vessel calls a week; a few hundred captures a day).

## Phases

**Phase 0, an afternoon: prove the cadence.** Capture the NWSA ERD page hourly for three days. Answer two questions the blog needs: when exactly does the page change each day, and does the GovDelivery ERD subscription send a digest or a change alert (subscribe an inbox and archive what arrives). Write both answers to `Research Pack.md` section 2.

**Phase 1, the weekend: capture + diff + change log.** Sources: NWSA ERD, WUT ERD, turn times, bulletins. Output: a change log page ("T18: MSC XXXX v.123 cutoff moved from 9/20 to 9/22, first seen 9/17 09:04") and a per-vessel history view. Run it for two weeks. The count of ERD changes in those two weeks is the number the ERD post is missing.

**Phase 2: alerts.** Email on change for a watched vessel/voyage or terminal. Give it to three dispatchers or brokers free. Ask which alerts they acted on.

**Phase 3: the D&D exhibit.** Add gate schedules, terminal update pages, DCLI. Build the date-range query and the PDF exhibit. Give it to a broker's D&D desk with a real disputed invoice and see whether it changes the outcome. That result is the free-time-clock post's follow-up.

**Not in scope, ever, without a partner:** per-container availability (lives in the terminal operating system and eModal), and anything behind a login.

## Conventions and cautions

- Never overwrite. If storage is a concern, dedupe raw bodies by hash but keep every `(source, fetched_at, hash)` row.
- All timestamps UTC in storage; render in America/Los_Angeles in exhibits, and say so on the exhibit.
- Identify the scraper in the user agent with a contact email. Rate-limit generously. Respect robots.txt; if a terminal blocks, stop and note it rather than routing around.
- Read the terminals' terms of use once before Phase 2. The pages are public and the use is archival; that's likely fine, but know what they say.
- Parsers will break when a page is redesigned. Alert on parse failure; the raw capture still has value.
- Don't claim the archive proves per-container facts. It proves what the terminal *published* about its state. Say so in the exhibit footer.

## Decisions for the building session

1. Language and scheduler (Python + APScheduler or a cron; anything is fine).
2. Storage (SQLite for Phase 1 is enough).
3. Where it runs (a small VM; it needs to be on for two weeks without attention).
4. Whether to capture eModal's dashboard (test whether it's public first).
5. Alert channel for Phase 2 (email is enough).

## Definition of done, per phase

- Phase 0: two answers written into the research pack, with the captures to back them.
- Phase 1: a change log with two weeks of ERD changes and a count; a per-vessel history you can screenshot for the post.
- Phase 2: three external users, one month, a list of alerts they acted on.
- Phase 3: one real dispute with an exhibit attached, and what happened.

## Related

- `../Terminal State Archive.md`: the case, the customers, the trust argument.
- `../ERD Feed Opportunity.md`: the ERD product and its open questions.
- `Research Pack.md`: the five stop-the-clock facts the exhibit must cover.
- `../P25 Export Receiving Dates/`: the ERD post this feeds.

---

## Session log (appended by build sessions)

### 2026-09-18 — repo created, capture layer working

- Decisions taken: Python for Phase 0/1 prototype, port to Rust for the live
  implementation once parsers stabilize. SQLite + content-addressed raw files.
- Smoke test results:
  - NWSA ERD page: server-rendered, 9 HTML tables — directly parseable.
  - WUT ERD: server-rendered tables — parseable.
  - **Turn times: data lives in a Power BI iframe embed; raw page has no
    numbers.** Capturing the series needs the Power BI query API or a headless
    browser. Deferred; does not block Phase 0.
- Open items: real contact email for the User-Agent; where the 3-day Phase 0
  run executes (laptop must stay awake, or a small VM); GovDelivery inbox
  subscription is a manual step.
