"""JSON API for the exhibit UI. Read-only.

    GET /api/sources                         registry + capture stats per source
    GET /api/captures?source=&limit=         capture rows, newest first
    GET /api/parsed?capture_id=              parsed rows for one capture
    GET /api/exhibit?terminal=T18&start=YYYY-MM-DD&end=YYYY-MM-DD[&line=HLC&equipment=40HC]
                                             the per-day exhibit

Every fact in the exhibit carries `evidence`: the capture ids (with UTC fetch time
and raw-body hash) from which it was read. Gaps are reported as gaps: a day with no
capture for a channel says `unknown`, never `no problem`.
"""
import json
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from . import store
from .capture import SOURCES, active_sources

router = APIRouter(prefix="/api")
PT = ZoneInfo("America/Los_Angeles")
TERMINALS = ["T18", "T5", "Husky", "PCT", "WUT"]

PUBLISHERS = {
    "nwseaportalliance.com": "Northwest Seaport Alliance (the port authority), compiling terminal operators' postings; updated weekdays by 9 a.m.",
    "uswut.com": "Washington United Terminals (HMM's Tacoma terminal), on its own site",
    "mock": "Nobody. Synthetic data in the shape of eModal's appointments API, until access exists.",
}


def _publisher(url: str) -> str:
    for host, who in PUBLISHERS.items():
        if host in url:
            return who
    return "unknown"


def db() -> sqlite3.Connection:
    conn = store.connect()
    conn.row_factory = sqlite3.Row
    return conn


def _pt_date(fetched_at_utc: str) -> str:
    return datetime.fromisoformat(fetched_at_utc).astimezone(PT).date().isoformat()


def _norm_equipment(e: str | None) -> str:
    if not e:
        return ""
    e = e.upper().replace("'", "").replace(" ", "")
    e = e.replace("DH", "HC").replace("SD", "DR").replace("DRY", "DR")
    return e


def _equipment_matches(rule_eq: str, want: str) -> bool:
    if not want:
        return True
    r, w = _norm_equipment(rule_eq), _norm_equipment(want)
    if r in ("ANY", ""):
        return True
    return r == w or r.startswith(w) or w.startswith(r)


def _line_matches(rule_line: str, want: str) -> bool:
    if not want:
        return True
    parts = re.split(r"[\s/,]+", rule_line.upper())
    return want.upper() in parts or want.upper() == rule_line.upper()


# ---------- registry ----------

@router.get("/sources")
def sources():
    conn = db()
    stats = {
        r["source_id"]: dict(r)
        for r in conn.execute(
            """SELECT source_id, COUNT(*) AS captures, COUNT(DISTINCT content_hash) AS versions,
                      SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors,
                      MIN(fetched_at) AS first, MAX(fetched_at) AS last
               FROM captures GROUP BY source_id"""
        )
    }
    parsed = {
        r["source_id"]: r["n"]
        for r in conn.execute("SELECT source_id, COUNT(*) AS n FROM parsed_rows GROUP BY source_id")
    }
    conn.close()
    out = []
    for sid, src in active_sources().items():
        s = stats.get(sid, {})
        status = "mock" if src.get("mock") else ("working" if s.get("captures") else "no captures yet")
        if s.get("captures") and not parsed.get(sid) and not src.get("mock"):
            status = "captured, nothing parsed"
        out.append(
            {
                "source_id": sid,
                "url": src["url"],
                "publisher": _publisher(src["url"]),
                "terminal": src.get("terminal"),
                "channel": src["channel"],
                "cadence_minutes": src["cadence_minutes"],
                "mock": bool(src.get("mock")),
                "status": status,
                "captures": s.get("captures", 0),
                "versions": s.get("versions", 0),
                "errors": s.get("errors", 0) or 0,
                "parsed_rows": parsed.get(sid, 0),
                "first": s.get("first"),
                "last": s.get("last"),
            }
        )
    return {"sources": out, "terminals": TERMINALS}


@router.get("/captures")
def captures(source: str | None = None, limit: int = Query(200, le=2000)):
    conn = db()
    if source:
        rows = conn.execute(
            "SELECT * FROM captures WHERE source_id = ? ORDER BY fetched_at DESC LIMIT ?", (source, limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM captures ORDER BY fetched_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return {"captures": [dict(r) for r in rows]}


@router.get("/parsed")
def parsed(capture_id: int):
    conn = db()
    rows = conn.execute("SELECT * FROM parsed_rows WHERE capture_id = ? ORDER BY id", (capture_id,)).fetchall()
    conn.close()
    return {"rows": [{**dict(r), "row": json.loads(r["row_json"])} for r in rows]}


@router.get("/capture/{capture_id}")
def capture(capture_id: int):
    """One capture's chain-of-custody record: source, URL, UTC time, hash, and how to verify it."""
    conn = db()
    cap = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
    conn.close()
    if cap is None:
        raise HTTPException(404, "no such capture")
    src = SOURCES.get(cap["source_id"], {})
    return {
        **dict(cap),
        "publisher": _publisher(cap["url"]),
        "channel": src.get("channel"),
        "raw_url": f"/raw/{cap['content_hash']}" if cap["content_hash"] else None,
        "download_url": f"/raw/{cap['content_hash']}?download=1" if cap["content_hash"] else None,
        "verify": "sha256 of the downloaded file must equal content_hash",
    }


@router.get("/health")
def health():
    """Live health checks (see src/health.py). 200 either way; read `ok`."""
    from . import health as h

    return h.run()


@router.get("/options")
def options(terminal: str):
    """Lines and equipment sizes the terminal's own empty-return matrix has ever listed."""
    if terminal not in TERMINALS:
        raise HTTPException(400, f"terminal must be one of {TERMINALS}")
    conn = db()
    rows = conn.execute(
        "SELECT row_json FROM parsed_rows WHERE kind = 'empty_rule' AND terminal = ?", (terminal,)
    ).fetchall()
    conn.close()
    lines: set[str] = set()
    equipment: dict[str, str] = {}
    for r in rows:
        row = json.loads(r["row_json"])
        for part in re.split(r"[\s/,]+", (row.get("line") or "").upper()):
            if part and part != "ANY":
                lines.add(part)
        eq = row.get("equipment") or ""
        n = _norm_equipment(eq)
        if n and n != "ANY":
            equipment.setdefault(n, n)
    return {"terminal": terminal, "lines": sorted(lines), "equipment": sorted(equipment)}


# ---------- exhibit ----------

def _evidence(cap: sqlite3.Row) -> dict:
    return {
        "capture_id": cap["id"],
        "source_id": cap["source_id"],
        "fetched_at_utc": cap["fetched_at"],
        "fetched_at_pt": datetime.fromisoformat(cap["fetched_at"]).astimezone(PT).isoformat(timespec="minutes"),
        "hash": cap["content_hash"],
        "mock": bool(cap["is_mock"]),
    }


@router.get("/exhibit")
def exhibit(
    terminal: str,
    start: str,
    end: str,
    line: str = "",
    equipment: str = "",
):
    if terminal not in TERMINALS:
        raise HTTPException(400, f"terminal must be one of {TERMINALS}")
    try:
        d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(400, f"bad date: {exc}") from exc
    if d1 < d0 or (d1 - d0).days > 60:
        raise HTTPException(400, "range must be 0-60 days")

    conn = db()
    active = list(active_sources())  # leaves out the mock channel unless it is switched on
    # All parsed rows for this terminal or port-wide, joined to their capture.
    rows = conn.execute(
        """SELECT p.id AS pid, p.kind, p.entity_key, p.row_json, p.source_id,
                  c.id, c.fetched_at, c.content_hash, c.is_mock, c.source_id AS csource
           FROM parsed_rows p JOIN captures c ON c.id = p.capture_id
           WHERE (p.terminal = ? OR p.terminal IS NULL) AND c.source_id IN ({})
           ORDER BY c.fetched_at""".format(",".join("?" * len(active))),
        (terminal, *active),
    ).fetchall()
    conn.close()

    # Index by kind, then by the PT date the capture was taken.
    by_kind: dict[str, list] = defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append((json.loads(r["row_json"]), r))

    def captures_on(kind: str, day: str):
        return [(row, cap) for row, cap in by_kind.get(kind, []) if _pt_date(cap["fetched_at"]) == day]

    def latest_before(kind: str, day: str, pred=lambda row: True):
        """Rows from the last capture (of this kind) taken on or before `day` that has matching rows."""
        best_cap_id, best = None, []
        for row, cap in by_kind.get(kind, []):
            if _pt_date(cap["fetched_at"]) > day or not pred(row):
                continue
            if cap["id"] != best_cap_id:
                best_cap_id, best = cap["id"], []
            best.append((row, cap))
        return best

    days = []
    used_captures: dict[int, dict] = {}

    def use(cap):
        used_captures[cap["id"]] = _evidence(cap)
        return cap["id"]

    for i in range((d1 - d0).days + 1):
        d = d0 + timedelta(days=i)
        day = d.isoformat()
        entry: dict = {"date": day, "weekday": d.strftime("%A")}

        # --- gate: scheduled hours for this date, from every capture that asserted them ---
        asserted = [(row, cap) for row, cap in by_kind.get("gate_day", []) if row.get("date_iso") == day]
        if asserted:
            values: dict[str, list] = defaultdict(list)
            for row, cap in asserted:
                values[row["status"]].append(use(cap))
            latest_row, latest_cap = asserted[-1]
            entry["gate"] = {
                "status": latest_row["status"],
                "shift": latest_row.get("shift"),
                "cell_raw": latest_row.get("cell_raw"),
                "asserted_by_captures": {k: sorted(set(v)) for k, v in values.items()},
                "changed_between_captures": len(values) > 1,
                "first_seen_utc": asserted[0][1]["fetched_at"],
                "last_seen_utc": latest_cap["fetched_at"],
            }
        else:
            entry["gate"] = None

        # --- empties: rules in force per the latest capture on/before the day ---
        pred = lambda row: _line_matches(row.get("line", ""), line) and _equipment_matches(row.get("equipment", ""), equipment)  # noqa: E731
        rules = latest_before("empty_rule", day, pred)
        if rules:
            entry["empties"] = {
                "from_capture": use(rules[0][1]),
                "capture_pt_date": _pt_date(rules[0][1]["fetched_at"]),
                "same_day": _pt_date(rules[0][1]["fetched_at"]) == day,
                "rules": [
                    {k: row.get(k) for k in ("line", "equipment", "action", "accepted", "cell_raw", "as_of_iso", "heading")}
                    for row, _ in rules
                ],
            }
        else:
            entry["empties"] = None

        # --- notices: terminal-page notices mentioning the day, plus port bulletins posted that day,
        #     plus any notice first seen that day ---
        notices = []
        seen_keys = set()
        for row, cap in by_kind.get("notice", []):
            hit = day in (row.get("dates_mentioned") or []) or row.get("posted_iso") == day
            if not hit:
                continue
            k = row["entity_key"] if "entity_key" in row else (row.get("url") or row.get("text"))
            if k in seen_keys:
                continue
            seen_keys.add(k)
            notices.append(
                {
                    "text": row.get("text") or row.get("title"),
                    "url": row.get("url"),
                    "posted_iso": row.get("posted_iso"),
                    "keywords": row.get("keywords"),
                    "scope": "port" if row.get("terminal") is None else terminal,
                    "evidence": use(cap),
                }
            )
        entry["notices"] = notices

        # --- turn times: samples taken that day ---
        tt = [(row, cap) for row, cap in captures_on("turn_time", day) if row.get("terminal") == terminal]
        if tt:
            qs = [row["queue_min"] for row, _ in tt if row.get("queue_min") is not None]
            entry["turn_times"] = {
                "samples": len(tt),
                "na_samples": sum(1 for row, _ in tt if row.get("na")),
                "placeholder_only": all(row.get("placeholder") for row, _ in tt),
                "queue_min_max": max(qs) if qs else None,
                "queue_min_min": min(qs) if qs else None,
                "evidence": sorted({use(cap) for _, cap in tt}),
            }
        else:
            entry["turn_times"] = None

        # --- slots (mock until real) ---
        sl = [(row, cap) for row, cap in captures_on("slot_window", day) if row.get("terminal") == terminal]
        if sl:
            queries: dict[str, dict] = {}
            for row, cap in sl:
                if line and row.get("line") and row["line"].upper() != line.upper():
                    continue
                if equipment and not _equipment_matches(row.get("equipment", ""), equipment):
                    continue
                k = row["entity_key"]
                q = queries.setdefault(
                    k,
                    {
                        "query": {kk: row.get(kk) for kk in ("trade_type", "pick_drop", "equipment", "line")},
                        "samples": 0,
                        "samples_with_slot_that_day": 0,
                        "evidence": [],
                    },
                )
                q["samples"] += 1
                if (row.get("by_day") or {}).get(day, 0) > 0:
                    q["samples_with_slot_that_day"] += 1
                q["evidence"].append(use(cap))
            for q in queries.values():
                q["evidence"] = sorted(set(q["evidence"]))
            entry["slots"] = {"mock": any(cap["is_mock"] for _, cap in sl), "queries": list(queries.values())}
        else:
            entry["slots"] = None

        # --- the five questions, answered only from what the record shows ---
        g = entry["gate"]
        e = entry["empties"]
        s = entry["slots"]
        unscheduled = any(
            n for n in notices if any(k in (n.get("keywords") or []) for k in ("closed", "closure", "suspend"))
        )
        # Returning an empty is a drop. Pick-up rules are shown, but they do not decide this answer.
        return_rules = [r for r in e["rules"] if r["action"] in ("drop", "any")] if e else []
        entry["answers"] = {
            "gate_scheduled_open": (None if g is None else g["status"] == "open"),
            "empties_accepted": (all(r["accepted"] for r in return_rules) if return_rules else None),
            "unscheduled_closure_or_restriction_noticed": unscheduled if notices else None,
            "appointments_available": (
                None
                if s is None or not s["queries"]
                else any(q["samples_with_slot_that_day"] > 0 for q in s["queries"])
            ),
            "appointments_source_is_mock": bool(s and s["mock"]),
            "government_hold": None,  # not this archive's fact; the importer's CBP record answers it
        }
        days.append(entry)

    channels = []
    for sid, src in active_sources().items():
        if src.get("terminal") not in (None, terminal):
            continue
        n = sum(
            1
            for r in rows
            if r["csource"] == sid and d0.isoformat() <= _pt_date(r["fetched_at"]) <= d1.isoformat()
        )
        channels.append(
            {
                "source_id": sid,
                "channel": src["channel"],
                "mock": bool(src.get("mock")),
                "parsed_rows_in_range": n,
            }
        )

    shown = {c["channel"] for c in channels}
    return {
        "terminal": terminal,
        "start": start,
        "end": end,
        "filters": {"line": line or None, "equipment": equipment or None},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timezone": "America/Los_Angeles",
        "caveat": (
            "This exhibit shows what the port and terminals PUBLISHED about their state, as captured. "
            "It does not prove per-container facts."
            + (" Appointment availability is MOCK data until eModal access exists." if "slots" in shown else "")
        ),
        "days": days,
        "channels": channels,
        "captures": [used_captures[k] for k in sorted(used_captures)],
    }
