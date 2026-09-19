"""Minimal read-only UI over the capture store.

Usage:
    .venv/bin/uvicorn src.web:app --reload --port 8100

Pages:
    /                    dashboard: per-source capture stats
    /captures/{source}   capture history with change markers (hash transitions)
    /raw/{hash}          the raw captured page body
"""
import html
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from . import store
from .capture import SOURCES

app = FastAPI(title="Terminal State Archive")

STYLE = """
<style>
  body { font-family: ui-monospace, Menlo, monospace; margin: 2rem; color: #222; }
  h1 { font-size: 1.2rem; } h2 { font-size: 1rem; }
  table { border-collapse: collapse; margin-top: 1rem; }
  th, td { border: 1px solid #ccc; padding: 4px 10px; text-align: left; font-size: 0.85rem; }
  th { background: #f4f4f4; }
  .changed { background: #fff3c4; font-weight: bold; }
  .error { background: #ffd7d7; }
  a { color: #0b62a4; }
  .muted { color: #888; }
</style>
"""


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>{STYLE}</head>"
        f"<body><h1><a href='/'>terminal-state-archive</a> / {html.escape(title)}</h1>"
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
    conn.close()
    by_id = {r["source_id"]: r for r in rows}

    trs = ""
    for source_id, src in SOURCES.items():
        r = by_id.get(source_id)
        if r:
            trs += (
                f"<tr><td><a href='/captures/{source_id}'>{source_id}</a></td>"
                f"<td>{src['cadence_minutes']}m</td><td>{r['captures']}</td>"
                f"<td>{r['versions']}</td><td>{r['errors'] or 0}</td>"
                f"<td>{r['first']}</td><td>{r['last']}</td></tr>"
            )
        else:
            trs += (
                f"<tr><td>{source_id}</td><td>{src['cadence_minutes']}m</td>"
                f"<td colspan='5' class='muted'>no captures yet</td></tr>"
            )
    body = (
        "<table><tr><th>source</th><th>cadence</th><th>captures</th>"
        "<th>distinct versions</th><th>errors</th><th>first</th><th>last</th></tr>"
        f"{trs}</table>"
        "<p class='muted'>distinct versions &gt; 1 means the page changed between captures.</p>"
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
    conn.close()

    # chronological pass to mark hash transitions, then render newest-first
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
            f"<tr class='{cls}'><td>{r['fetched_at']}</td><td>{r['http_status'] or ''}</td>"
            f"<td>{hash_cell}</td><td>{html.escape(str(note))}</td></tr>"
        )
    body = (
        f"<p class='muted'>{SOURCES[source_id]['url']}</p>"
        "<table><tr><th>fetched_at (UTC)</th><th>status</th><th>hash</th><th>note</th></tr>"
        f"{trs}</table>"
    )
    return page(source_id, body)


@app.get("/raw/{content_hash}", response_class=HTMLResponse)
def raw(content_hash: str):
    if not all(c in "0123456789abcdef" for c in content_hash) or len(content_hash) != 64:
        raise HTTPException(400, "bad hash")
    path = store.RAW_DIR / content_hash[:2] / f"{content_hash}.html"
    if not path.exists():
        raise HTTPException(404, "no such capture")
    return HTMLResponse(path.read_text(errors="replace"))
