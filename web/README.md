# Terminal State Archive — exhibit UI

Next.js (App Router, TypeScript). Talks to the FastAPI archive at `/api/*`, proxied through a
Next rewrite (`next.config.ts`) so there is no CORS. Override the API location with
`ARCHIVE_API=http://host:port`.

## Run (dev)

```bash
# terminal 1: the archive API, from the repo root
.venv/bin/uvicorn src.web:app --reload --port 8100

# terminal 2: this app
cd web && npm install && npm run dev
# http://localhost:3000/?terminal=T18&start=2026-09-14&end=2026-09-25&line=HLC&equipment=40HC
```

## Layout

- `src/lib/types.ts` — mirrors `src/api.py` response shapes (kept in sync by hand)
- `src/lib/api.ts` — the two fetches (`/api/sources`, `/api/exhibit`)
- `src/components/ExhibitApp.tsx` — the form: terminal, line+size, your failed attempts
- `src/components/Corroboration.tsx` — one row per attempt: what the terminal published that day, with evidence
- `src/components/Info.tsx` / `infoText.ts` — the ⓘ modals: what each thing is and where it came from

The UI does one thing: check whether stored records corroborate your failed attempts.
Anything beyond that (date-range browsing, dispute drafting, printing) is deliberately absent.


