# Daily check

Ten minutes, once a day, before the archive is shown to anyone. The point is to catch the
things that would make a reader stop trusting it: a stale capture presented as current, a
parser that silently went to zero after a page redesign, a day landing on the wrong date,
mock data leaking into a real column, or a number that does not match the live page.

Do it at the same time each day, ideally between 9:30 and 11:00 PT, after the port's 9 a.m.
weekday update has landed.

## 1. Is it still collecting? (2 min)

Open the UI and expand **Where the record comes from**. For every row:

- **Last capture is within 2× its cadence.** A 15-min source older than 30 min, a 2-hour source
  older than 4 hours, means the scheduler died or the host blocked us. Check
  `docker compose logs --tail=50 scheduler`.
- **Errors column is not climbing.** One or two is a hiccup; a steady count means a 403/5xx
  and the User-Agent contact email had better be real.
- **Captures count went up since yesterday** for every real source.

Then `http://localhost:8100/` (the plain dashboard): **parsed rows** for each source is non-zero
and **distinct versions** is growing for the sources that change daily (ERD, terminal pages).
A source whose captures climb but whose parsed rows stay flat is a parser that broke silently.

## 2. Does the record match the live page? (5 min)

Pick T18 and today's date, any line, any size, **Check the record**. Then open the live T18
update page in another tab and compare:

- **Gate**: the exhibit's open/closed and hours for today equal the live gate-hours table.
  On a Friday it must say closed (until the terminal changes that rule).
- **Empties**: choose HLC and 40HC; the drop/pick yes/no match the live matrix cell for
  HLC 40DH. Pick one more random cell (e.g. MSC reefer) and check it too. It must never read
  "N of M refused" with M larger than the number of drop/pick columns (that was a colspan bug).
- **Evidence**: click the hash. The captured page shows today's gate table and matrix.
  Click ↓, then `shasum -a 256 <file>`; it must equal the full hash in `/api/capture/<id>`.

Repeat the empties check once for **WUT** against `uswut.com/schedule/empty-receiving/`
(also compare the "LAST UPDATE" date on the page with the `as_of` the archive parsed).

Once a week, do the gate check for **T5**, **Husky** and **PCT** too. Husky and PCT publish
prose, not a grid; the exhibit must say *unknown* for empties there, not *accepted*.

## 3. Days and times (1 min)

- Today's row shows today's weekday. A capture made at 6 p.m. PT (which is the next day in
  UTC) must appear under the PT date. If any evidence time looks 7–8 hours off, the timezone
  handling regressed.
- Check yesterday: the empties cell should say **from <yesterday's date>** only if there was
  no capture yesterday; if the scheduler ran, it should be same-day.

## 4. The 9 a.m. question (1 min, weekdays)

The NWSA ERD page and terminal pages are republished by 9 a.m. In `/captures/nwsa_erd` the
first **CHANGED** row of the day should sit between about 08:00 and 10:00 PT. Note the time.
After a week that is the "what minute does the page change" answer for the P25 post.

## 5. Mock hygiene (30 s)

- The appointment column says **MOCK** on every row that has data. Nowhere else does.
- The channels table shows the mock row shaded and its page as *none*.
- `/api/captures?source=emodal_slots_mock` rows all have `is_mock: 1`.

## 6. What would embarrass you (read once a week)

- A reader clicks a hash and the page is blank or is today's page rather than the day's.
- A terminal redesigns its page: captures continue, parsed rows drop to zero, the exhibit
  turns to *unknown* everywhere without saying why. Section 1 catches this within a day.
- The T18 page's own typos (`CMA/APL/ANLYES`) show up as a line code. The parser keeps the
  raw and cleans the code; if a new one appears, it will show in the line dropdown first.
- The gate table rolls to a new week on Monday: the exhibit for the coming days should show
  it by Monday noon. If Monday's rows are *unknown* on Tuesday, the week-parsing broke.
- Disk: `du -sh data/` grows about 20–30 MB a day. Fine; just know it.

## Log

Keep a one-line note per day in `docs/RUN_LOG.md`: date, all sources fresh y/n, T18 gate
matched y/n, empties matched y/n, hash verified y/n, ERD change time, anything odd.
