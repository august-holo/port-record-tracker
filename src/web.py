"""Read-only UI over the capture store.

Usage:
    .venv/bin/uvicorn src.web:app --reload --port 8100

Pages:
    /                    dashboard: per-source capture stats
    /captures/{source}   capture history with change markers (hash transitions)
    /raw/{hash}          the raw captured page body
    /ui/                 the exhibit front end (static; talks to /api)
    /api/...             JSON (see src/api.py)
"""
import html
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import capture, store
from .api import router as api_router
from .capture import SOURCES

app = FastAPI(title="Terminal State Archive")
app.include_router(api_router)

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")

MEDIA_TYPES = {".json": "application/json", ".jpg": "image/jpeg", ".png": "image/png", ".txt": "text/plain"}

STYLE = """
<style>
  body { font-family: ui-monospace, Menlo, monospace; margin: 2rem; color: #222; }
  h1 { font-size: 1.2rem; } h2 { font-size: 1rem; }
  table { border-collapse: collapse; margin-top: 1rem; }
  th, td { border: 1px solid #ccc; padding: 4px 10px; text-align: left; font-size: 0.85rem; }
  th { background: #f4f4f4; }
  .changed { background: #fff3c4; font-weight: bold; }
  .error { background: #ffd7d7; }
  .mock { background: #e8e8ff; }
  a { color: #0b62a4; }
  .muted { color: #888; }
</style>
"""


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>{STYLE}</head>"
        f"<body><h1><a href='/'>terminal-state-archive</a> / {html.escape(title)}"
        f" <span class='muted'>· <a href='/ui/'>exhibit UI</a></span></h1>"
        f"{body}</body></html>"
    )


def db() -> sqlite3.Connection:
    conn = store.connect()
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/", response_class=HTMLResponse)
def dashboard():
    conn = db()
    rows = conn.execute(
        """SELECT source_id,
                  COUNT(*) AS captures,
                  COUNT(DISTINCT content_hash) AS versions,
                  SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors,
                  MIN(fetched_at) AS first,
                  MAX(fetched_at) AS last
           FROM captures GROUP BY source_id"""
    ).fetchall()
    parsed = {r["source_id"]: r["n"] for r in conn.execute("SELECT source_id, COUNT(*) AS n FROM parsed_rows GROUP BY source_id")}
    conn.close()
    by_id = {r["source_id"]: r for r in rows}

    trs = ""
    for source_id, src in SOURCES.items():
        r = by_id.get(source_id)
        cls = "mock" if src.get("mock") else ""
        label = f"{source_id}{' (MOCK)' if src.get('mock') else ''}"
        if r:
            trs += (
                f"<tr class='{cls}'><td><a href='/captures/{source_id}'>{label}</a></td>"
                f"<td>{src['channel']}</td><td>{src.get('terminal') or '—'}</td>"
                f"<td>{src['cadence_minutes']}m</td><td>{r['captures']}</td>"
                f"<td>{r['versions']}</td><td>{parsed.get(source_id, 0)}</td><td>{r['errors'] or 0}</td>"
                f"<td>{r['first']}</td><td>{r['last']}</td></tr>"
            )
        else:
            trs += (
                f"<tr class='{cls}'><td>{label}</td><td>{src['channel']}</td><td>{src.get('terminal') or '—'}</td>"
                f"<td>{src['cadence_minutes']}m</td>"
                f"<td colspan='6' class='muted'>no captures yet</td></tr>"
            )
    body = (
        "<table><tr><th>source</th><th>channel</th><th>terminal</th><th>cadence</th><th>captures</th>"
        "<th>distinct versions</th><th>parsed rows</th><th>errors</th><th>first</th><th>last</th></tr>"
        f"{trs}</table>"
        "<p class='muted'>distinct versions &gt; 1 means the page changed between captures. "
        "MOCK rows are synthetic and exist only to show the shape of the appointments channel.</p>"
    )
    return page("dashboard", body)


@app.get("/captures/{source_id}", response_class=HTMLResponse)
def captures(source_id: str):
    if source_id not in SOURCES:
        raise HTTPException(404, f"unknown source: {source_id}")
    conn = db()
    rows = conn.execute(
        "SELECT * FROM captures WHERE source_id = ? ORDER BY fetched_at",
        (source_id,),
    ).fetchall()
    parsed = {r["capture_id"]: r["n"] for r in conn.execute(
        "SELECT capture_id, COUNT(*) AS n FROM parsed_rows WHERE source_id = ? GROUP BY capture_id", (source_id,))}
    conn.close()

    trs = ""
    prev_hash = None
    marks = {}
    for r in rows:
        h = r["content_hash"]
        marks[r["id"]] = (prev_hash is not None and h != prev_hash) or False
        if h is not None:
            prev_hash = h
    for r in reversed(rows):
        h = r["content_hash"]
        cls = "error" if r["error"] else ("changed" if marks[r["id"]] else "")
        hash_cell = (
            f"<a href='/raw/{h}'>{h[:12]}</a>" if h else "<span class='muted'>—</span>"
        )
        note = "CHANGED" if marks[r["id"]] and not r["error"] else (r["error"] or "")
        trs += (
            f"<tr class='{cls}'><td>{r['id']}</td><td>{r['fetched_at']}</td><td>{r['http_status'] or ''}</td>"
            f"<td>{hash_cell}</td><td><a href='/api/parsed?capture_id={r['id']}'>{parsed.get(r['id'], 0)}</a></td>"
            f"<td>{html.escape(str(note))}</td></tr>"
        )
    body = (
        f"<p class='muted'>{SOURCES[source_id]['url']}</p>"
        "<table><tr><th>id</th><th>fetched_at (UTC)</th><th>status</th><th>hash</th><th>parsed</th><th>note</th></tr>"
        f"{trs}</table>"
    )
    return page(source_id, body)


@app.get("/raw/{content_hash}")
def raw(content_hash: str, download: int = 0):
    """The captured body, byte for byte.

    Rendered inline under a CSP sandbox (no scripts, no same-origin), because the bytes
    are a third party's page. `?download=1` returns the original file as an attachment,
    named source_time_hash so the filename itself carries the provenance.
    """
    if not all(c in "0123456789abcdef" for c in content_hash) or len(content_hash) != 64:
        raise HTTPException(400, "bad hash")
    path = store.find_raw(content_hash)
    if path is None or (path.suffix in (".jpg", ".png") and not capture.CAMERAS_ENABLED):
        raise HTTPException(404, "no such capture")  # camera stills are not served while the channel is off
    if download:
        conn = store.connect()
        cap = conn.execute(
            "SELECT source_id, fetched_at FROM captures WHERE content_hash = ? ORDER BY id LIMIT 1", (content_hash,)
        ).fetchone()
        conn.close()
        stamp = (cap[1] if cap else "").replace(":", "").replace("+0000", "Z")
        name = f"{cap[0] if cap else 'capture'}_{stamp}_{content_hash[:12]}{path.suffix}"
        return FileResponse(path, media_type=MEDIA_TYPES.get(path.suffix, "text/html"), filename=name)
    headers = {"Content-Security-Policy": "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"}
    if path.suffix in (".jpg", ".png"):
        return FileResponse(path, media_type=MEDIA_TYPES[path.suffix], headers=headers)
    if path.suffix == ".txt":
        return PlainTextResponse(path.read_text(errors="replace"), headers=headers)
    if path.suffix == ".json":
        return PlainTextResponse(path.read_text(errors="replace"), media_type="application/json", headers=headers)
    return HTMLResponse(path.read_text(errors="replace"), headers=headers)


@app.get("/exhibit")
def exhibit_redirect():
    return RedirectResponse("/ui/")
