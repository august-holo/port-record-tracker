"""Parsers: raw capture -> parsed_rows.

Usage:
    python -m src.parse --all            # parse every capture that has no parsed rows
    python -m src.parse --all --force    # re-parse everything (rewrites derived rows only)
    python -m src.parse 42               # parse capture id 42

Rules:
  * parsed_rows / parse_errors are DERIVED tables. They may be regenerated from raw.
    captures and data/raw are never touched here.
  * a parser returns a list of row dicts; each must have `kind` and `entity_key`.
  * parsers are allowed to fail; the failure is recorded in parse_errors.
  * dates are kept as captured strings AND normalised to ISO (America/Los_Angeles)
    where the meaning is clear. Both, not one.
"""
import hashlib
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import store

PT = ZoneInfo("America/Los_Angeles")
PARSER_VERSION = 5

MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
STATUS_WORDS = {"open", "closed", "yes", "no", "n/a"}
NOTICE_KEYWORDS = [
    "closed", "closure", "not accept", "will not", "no longer", "not be", "until further notice",
    "appointment", "restrict", "suspend", "turned", "dual transaction", "empty", "empties",
    "holiday", "hoot", "reefer", "cutoff", "cut-off",
]
# On their own these make a paragraph a notice. The rest of NOTICE_KEYWORDS also turn up in the
# standing appointment rules every terminal page repeats, so they count only beside a date.
STRONG_NOTICE_KEYWORDS = {
    "closed", "closure", "not accept", "no longer", "until further notice", "restrict", "suspend", "holiday",
}


# ---------- helpers ----------

def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _canon(row: dict) -> tuple[str, str]:
    js = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return js, hashlib.sha256(js.encode()).hexdigest()


def _infer_year(month: int, day: int, ref: date) -> date | None:
    """Pick the year that puts (month, day) nearest the reference date."""
    candidates = []
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            candidates.append(date(y, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda d: abs((d - ref).days))


def parse_date_token(tok: str, ref: date) -> date | None:
    """'SEPT 14', 'Sept. 14th', '9/8', '09/21/2026', '09-21-2026', 'Monday, September 14th'."""
    t = tok.strip().lower()
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", t)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", t)
    if m:
        return _infer_year(int(m.group(1)), int(m.group(2)), ref)
    m = re.search(r"\b([a-z]{3,9})\.?\s+(\d{1,2})\b", t)
    if m and m.group(1) in MONTHS:
        return _infer_year(MONTHS[m.group(1)], int(m.group(2)), ref)
    m = re.search(r"\b(\d{1,2})\s+([a-z]{3,9})\b", t)
    if m and m.group(2) in MONTHS:
        return _infer_year(MONTHS[m.group(2)], int(m.group(1)), ref)
    return None


def parse_datetime_token(tok: str, ref: date) -> str | None:
    """'09-23-2026 0700' / '09/10/2026 08:00' -> ISO in PT. Returns None if no time."""
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})\s+(\d{2}):?(\d{2})", tok)
    if not m:
        return None
    mo, d, y, hh, mm = map(int, m.groups())
    try:
        return datetime(y, mo, d, hh, mm, tzinfo=PT).isoformat(timespec="minutes")
    except ValueError:
        return None


def _status(cell: str) -> str | None:
    c = cell.strip().lower()
    if c in ("open", "yes", "y"):
        return "open"
    if c in ("closed", "no", "n", "close"):
        return "closed"
    if re.fullmatch(r"\d{4}\s*-\s*\d{4}", c) or re.fullmatch(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", c):
        return "open"
    if c in ("n/a", "na", "-", "—", ""):
        return None
    if c.startswith("open") or " open" in c:
        return "open"
    if c.startswith("closed") or c.startswith("no ") or "not accept" in c:
        return "closed"
    return None


def _tables_with_context(soup: BeautifulSoup) -> list[tuple[str, list[list[str]]]]:
    """Every table as a matrix of cell strings, with the nearest preceding heading."""
    out = []
    for table in soup.find_all("table"):
        if table.find("table"):
            continue  # layout wrapper; its inner tables are handled on their own
        heading = ""
        for prev in table.find_all_previous(["h1", "h2", "h3", "h4", "h5", "strong", "p"], limit=8):
            t = _text(prev)
            if t and len(t) < 80:
                heading = t
                break
        rows = []
        for tr in table.find_all("tr"):
            cells: list[str] = []
            for c in tr.find_all(["th", "td"]):
                try:
                    span = max(1, int(c.get("colspan", 1)))
                except ValueError:
                    span = 1
                cells.extend([_text(c)] * span)
            if cells:
                rows.append(cells)
        if rows:
            out.append((heading, rows))
    return out


def _main_content(soup: BeautifulSoup):
    for sel in ("main", "article", "#main-content", ".region-content", ".node__content", "body"):
        el = soup.select_one(sel)
        if el:
            return el
    return soup


# ---------- terminal update pages ----------

def _equipment_from_header(h: str) -> tuple[str, str | None]:
    """'40DH Drop' -> ('40DH', 'drop'); '20\\' Pick Up' -> ('20', 'pick'); 'Reefer Drop' -> ('Reefer','drop')."""
    hl = h.lower()
    action = "drop" if "drop" in hl else ("pick" if "pick" in hl else None)
    eq = re.sub(r"(?i)\b(drop|pick\s*up|pick|off|status)\b", "", h)
    eq = eq.replace("'", "").replace("’", "").replace("”", "").strip(" -:")
    eq = re.sub(r"\s+", "", eq).upper() or "ANY"
    return eq, action


EQUIPMENT_RE = re.compile(r"(?i)\d{2}|reefer|rfr|special|hc|dh|dr|sd")


def _is_equipment_header(h: str) -> bool:
    eq, _ = _equipment_from_header(h)
    return bool(EQUIPMENT_RE.search(eq)) and eq not in ("OT", "FR")


def _clean_line(line: str) -> tuple[str, str]:
    """The T18 page once published 'CMA/APL/ANLYES' (a status typed into the line cell). Keep the raw, fix the code."""
    raw = line.strip()
    m = re.match(r"^(.*?[A-Z])(YES|NO)$", raw)
    return (m.group(1) if m else raw), raw


def parse_terminal_page(raw: bytes, terminal: str, ref: date) -> list[dict]:
    soup = BeautifulSoup(raw, "lxml")
    content = _main_content(soup)
    rows: list[dict] = []

    # 1. tables
    for heading, matrix in _tables_with_context(content):
        header = matrix[0]
        body = matrix[1:]
        header_dates = [parse_date_token(h, ref) for h in header]
        n_header_dates = sum(1 for d in header_dates if d)
        first_col_dates = [parse_date_token(r[0], ref) if r else None for r in body]
        n_first_col_dates = sum(1 for d in first_col_dates if d)
        status_cells = sum(1 for r in body for c in r[1:] if _status(c) is not None)
        drop_pick_cols = sum(1 for h in header if re.search(r"(?i)drop|pick", h))
        equipment_cols = sum(1 for h in header[1:] if _is_equipment_header(h))

        # gate hours: dates across the header, one row per shift
        if n_header_dates >= 2 and (status_cells or header_dates[0]):
            for r in body:
                # A leading label column ("0800-1600", "Shift") is optional; PCT's table is dates-only.
                has_label = not header_dates[0]
                shift = r[0] if has_label else "day"
                start = 1 if has_label else 0
                for i, cell in enumerate(r[start:], start=start):
                    if i >= len(header_dates) or not header_dates[i]:
                        continue
                    st = _status(cell)
                    if st is None:
                        continue
                    d = header_dates[i]
                    if shift == "day" and re.search(r"\d{4}\s*-\s*\d{4}", cell):
                        shift = cell  # dates-only header: the hours live in the cell itself
                    rows.append(
                        {
                            "kind": "gate_day",
                            "entity_key": f"{terminal}|gate|{d.isoformat()}|{shift}",
                            "terminal": terminal,
                            "date_iso": d.isoformat(),
                            "date_raw": header[i],
                            "shift": shift,
                            "status": st,
                            "cell_raw": cell,
                            "heading": heading,
                        }
                    )
            continue

        # gate hours: one row per date. The date may sit in the first or second cell (a day name may
        # precede it), and the cell after it must be a status word or an hours range. If the "header"
        # row itself carries a date, the table has no header and every row is data.
        hours_re = re.compile(r"\d{4}\s*-\s*\d{4}|\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}")
        all_rows = matrix if any(header_dates[:2]) else body
        gate_rows = []
        for r in all_rows:
            date_idx = next((i for i, c in enumerate(r[:2]) if parse_date_token(c, ref)), None)
            if date_idx is None:
                continue
            rest = [c for c in r[date_idx + 1 :] if c.strip()]
            if not rest or _status(rest[0]) is None:
                continue
            gate_rows.append((r, parse_date_token(r[date_idx], ref), date_idx, rest[0]))
        if len(gate_rows) >= 2 and len(gate_rows) >= 0.6 * len(all_rows):
            for r, d, date_idx, cell in gate_rows:
                st = _status(cell)
                shift = cell if hours_re.search(cell) else "day"
                rows.append(
                    {
                        "kind": "gate_day",
                        "entity_key": f"{terminal}|gate|{d.isoformat()}|{shift}",
                        "terminal": terminal,
                        "date_iso": d.isoformat(),
                        "date_raw": r[date_idx],
                        "shift": shift,
                        "status": st,
                        "cell_raw": cell,
                        "heading": heading,
                    }
                )
            continue

        # empty-return matrix: line per row, equipment x drop/pick per column
        if (drop_pick_cols >= 2 or (equipment_cols >= 2 and status_cells)) and body and not re.search(r"(?i)chassis|trac|dcli", heading) and not any(re.search(r"(?i)chassis|trac|dcli", r[0]) for r in body):
            hl = heading.lower()
            table_action = "pick" if "pick" in hl else ("drop" if ("receiv" in hl or "drop" in hl or "return" in hl) else None)
            for r in body:
                line, line_raw = _clean_line(r[0])
                if not line:
                    continue
                seen_cols: set[tuple[str, str]] = set()
                for i, cell in enumerate(r[1:], start=1):
                    if i >= len(header) or not _is_equipment_header(header[i]):
                        continue
                    st = _status(cell)
                    if st is None:
                        continue
                    eq, action = _equipment_from_header(header[i])
                    action = action or table_action or "any"
                    if (eq, action) in seen_cols:
                        continue  # a colspan-expanded duplicate of the previous column
                    seen_cols.add((eq, action))
                    rows.append(
                        {
                            "kind": "empty_rule",
                            "entity_key": f"{terminal}|empty|{line}|{eq}|{action}",
                            "terminal": terminal,
                            "line": line,
                            "line_raw": line_raw,
                            "equipment": eq,
                            "action": action,
                            "accepted": st == "open",
                            "cell_raw": cell,
                            "heading": heading,
                        }
                    )
            continue

        # empty status list: 'Container Type | <LINE> Status' with OPEN/CLOSED rows
        if len(header) >= 2 and re.search(r"(?i)status", " ".join(header)) and status_cells:
            line = re.sub(r"(?i)status", "", header[1]).strip() or "ANY"
            for r in body:
                if len(r) < 2:
                    continue
                st = _status(r[1])
                if st is None:
                    continue
                eq = re.sub(r"\s+", "", r[0]).upper()
                rows.append(
                    {
                        "kind": "empty_rule",
                        "entity_key": f"{terminal}|empty|{line}|{eq}|any",
                        "terminal": terminal,
                        "line": line,
                        "equipment": eq,
                        "action": "any",
                        "accepted": st == "open",
                        "cell_raw": r[1],
                        "heading": heading,
                    }
                )
            continue

        # anything else: keep the table as generic rows so nothing is lost
        for idx, r in enumerate(body):
            rows.append(
                {
                    "kind": "table_row",
                    "entity_key": f"{terminal}|table|{heading[:40]}|{idx}",
                    "terminal": terminal,
                    "heading": heading,
                    "cells": dict(zip(header, r)) if len(header) == len(r) else {"cells": r},
                }
            )

    # 2. notices: paragraphs and list items with operational keywords
    seen = set()
    for el in content.find_all(["p", "li", "h3", "h4", "strong", "div"]):
        if el.name == "div" and el.find(["p", "li", "div", "table", "h3", "h4"]):
            continue  # only leaf divs; block containers are covered by their children
        t = _text(el)
        if len(t) < 12 or len(t) > 600 or t in seen:
            continue
        tl = t.lower()
        hits = [k for k in NOTICE_KEYWORDS if k in tl]
        if not hits:
            continue
        seen.add(t)
        dates = []
        for m in re.finditer(r"(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?([a-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?|\d{1,2}/\d{1,2}(?:/\d{2,4})?)", tl):
            d = parse_date_token(m.group(1), ref)
            if d:
                dates.append(d.isoformat())
        if not dates and not STRONG_NOTICE_KEYWORDS.intersection(hits):
            continue  # standing boilerplate, not news
        rows.append(
            {
                "kind": "notice",
                "entity_key": f"{terminal}|notice|{hashlib.sha1(t.encode()).hexdigest()[:12]}",
                "terminal": terminal,
                "text": t,
                "keywords": hits,
                "dates_mentioned": sorted(set(dates)),
            }
        )

    # 3. an explicit "as of" stamp anywhere on the page
    m = re.search(r"(?i)(as of|last update)\s*[–:-]?\s*(?:on\s+)?(\d{1,2}/\d{1,2}/\d{2,4})", _text(content))
    if m:
        d = parse_date_token(m.group(2), ref)
        if d:
            rows.append(
                {
                    "kind": "as_of",
                    "entity_key": f"{terminal}|as_of",
                    "terminal": terminal,
                    "as_of_iso": d.isoformat(),
                    "as_of_raw": m.group(0),
                }
            )
    return rows


# ---------- WUT empty receiving ----------

def parse_wut_empties(raw: bytes, ref: date) -> list[dict]:
    soup = BeautifulSoup(raw, "lxml")
    content = _main_content(soup)
    rows: list[dict] = []
    as_of = None
    m = re.search(r"(?i)(?:last update|matrix|as of)\s*[–:-]?\s*(?:on\s+|for\s+)?(\d{1,2}/\d{1,2}/\d{4})", _text(content))
    if m:
        d = parse_date_token(m.group(1), ref)
        as_of = d.isoformat() if d else None
        rows.append({"kind": "as_of", "entity_key": "WUT|empties|as_of", "terminal": "WUT",
                     "as_of_iso": as_of, "as_of_raw": m.group(0)})
    for heading, matrix in _tables_with_context(content):
        header = matrix[0]
        if not re.search(r"(?i)ssco|line", header[0]) and not any(re.search(r"(?i)drop|pick", h) for h in header):
            continue
        for r in matrix[1:]:
            line = r[0].strip()
            if not line or len(r) < 2:
                continue
            seen_cols: set[tuple[str, str | None]] = set()
            for i, cell in enumerate(r[1:], start=1):
                if i >= len(header) or not _is_equipment_header(header[i]):
                    continue
                st = _status(cell)
                if st is None:
                    continue
                eq, action = _equipment_from_header(header[i])
                if (eq, action) in seen_cols:
                    continue
                seen_cols.add((eq, action))
                rows.append(
                    {
                        "kind": "empty_rule",
                        "entity_key": f"WUT|empty|{line}|{eq}|{action or 'any'}",
                        "terminal": "WUT",
                        "line": line,
                        "equipment": eq,
                        "action": action or "any",
                        "accepted": st == "open",
                        "cell_raw": cell,
                        "as_of_iso": as_of,
                        "heading": heading,
                    }
                )
    return rows


# ---------- NWSA bulletins ----------

def parse_nwsa_bulletins(raw: bytes, ref: date) -> list[dict]:
    soup = BeautifulSoup(raw, "lxml")
    content = _main_content(soup)
    rows: list[dict] = []
    seen = set()
    # Drupal-style listing: each item has a link and, usually, a date nearby.
    for a in content.find_all("a", href=True):
        href = a["href"]
        if "trucker-news-updates/" not in href:
            continue
        title = _text(a)
        if not title or href in seen:
            continue
        seen.add(href)
        container = a.find_parent(["article", "li", "div"]) or a
        ctx = _text(container)[:400]
        d = None
        m = re.search(r"([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})", ctx)
        if m:
            d = parse_date_token(m.group(1), ref)
        rows.append(
            {
                "kind": "notice",
                "entity_key": f"NWSA|bulletin|{href}",
                "terminal": None,
                "title": title,
                "url": href if href.startswith("http") else f"https://www.nwseaportalliance.com{href}",
                "posted_iso": d.isoformat() if d else None,
                "context": ctx,
                "keywords": [k for k in NOTICE_KEYWORDS if k in ctx.lower()],
            }
        )
    return rows


# ---------- NWSA turn times ----------

def parse_nwsa_turn_times(raw: bytes, ref: date) -> list[dict]:
    soup = BeautifulSoup(raw, "lxml")
    text = _text(_main_content(soup))
    rows = []
    for name, key in (("T5", "T5"), ("T18", "T18"), ("Husky", "Husky"),
                      ("Pierce County Terminal", "PCT"), ("Washington United Terminals", "WUT")):
        m = re.search(rf"{re.escape(name)}\s+Queue\s+(\S+)\s+In Terminal\s+(\S+)", text)
        if not m:
            continue
        q, it = m.group(1), m.group(2)
        def num(v):
            return int(v) if v.isdigit() else None
        rows.append(
            {
                "kind": "turn_time",
                "entity_key": f"{key}|turn_time",
                "terminal": key,
                "queue_min": num(q),
                "in_terminal_min": num(it),
                "na": not (q.isdigit() or it.isdigit()),
                "placeholder": "Connecting" in text,   # page is JS-rendered; numbers not in HTML
                "raw": f"{q}/{it}",
            }
        )
    return rows


def _minutes(v) -> int | None:
    """'0hr 32m' -> 32, '1hr 05m' -> 65, '47' -> 47, 'N/A' -> None."""
    t = str(v or "").strip().lower()
    m = re.fullmatch(r"(?:(\d+)\s*hr)?\s*(?:(\d+)\s*m(?:in)?)?", t)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    return int(t) if t.isdigit() else None


def parse_nwsa_turn_feed(raw: bytes, ref: date) -> list[dict]:
    """The socket.io polling payload behind NWSA's turn-times page: one `42["data", {...}]` packet.

    NWSA's page defines N/A as fewer than 20 trucks through the gate in the last 60 minutes,
    "which may be attributed to terminal closures and lunch breaks".
    """
    packet = next((pk for pk in raw.split(b"\x1e") if pk.startswith(b'42["data"')), None)
    if packet is None:
        raise ValueError("no data packet in turn-time feed payload")
    rows = []
    for terminal, v in json.loads(packet[2:])[1].items():
        q, it, total = _minutes(v.get("Queue")), _minutes(v.get("In-Terminal")), _minutes(v.get("Total Experience"))
        rows.append(
            {
                "kind": "turn_time",
                "entity_key": f"{terminal}|turn_time",
                "terminal": terminal,
                "queue_min": q,
                "in_terminal_min": it,
                "total_min": total,
                "na": q is None and it is None,
                "feed_updated_utc": v.get("updated"),
                "raw": {k: v.get(k) for k in ("Queue", "In-Terminal", "Total Experience")},
            }
        )
    return rows


# ---------- gate cameras ----------

def parse_camera(raw: bytes, terminal: str | None, camera: str | None) -> list[dict]:
    """A still has no facts to read out; the row records that a real image was captured."""
    kind = "jpeg" if raw[:3] == b"\xff\xd8\xff" else ("png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else None)
    if kind is None:
        raise ValueError(f"camera returned {len(raw)} bytes that are not an image")
    return [
        {
            "kind": "camera_frame",
            "entity_key": f"{terminal}|camera|{camera}",
            "terminal": terminal,
            "camera": camera,
            "image": kind,
            "bytes": len(raw),
        }
    ]


# ---------- ERD pages ----------

WUT_ERD_HEADER = ["ssco", "voyage", "vessel", "svc", "erd", "cutoff", "etb", "etd"]


def parse_wut_erd(raw: bytes, ref: date) -> list[dict]:
    soup = BeautifulSoup(raw, "lxml")
    rows = []
    for heading, matrix in _tables_with_context(_main_content(soup)):
        if len(matrix[0]) != 8:
            continue
        for r in matrix[1:]:
            if len(r) != 8:
                continue
            rec = dict(zip(WUT_ERD_HEADER, r))
            row = {
                "kind": "erd",
                "entity_key": f"WUT|erd|{rec['vessel']}|{rec['voyage']}",
                "terminal": "WUT",
                **rec,
            }
            for f in ("erd", "cutoff", "etb", "etd"):
                row[f + "_iso"] = parse_datetime_token(rec[f], ref)
            rows.append(row)
    return rows


NWSA_ANCHORS = (("T5", "terminal-5"), ("T18", "terminal-18"), ("Husky", "husky"),
                ("PCT", "pierce"), ("WUT", "washington-united"))


def _nwsa_terminal_for(table) -> str | None:
    """The NWSA ERD page marks each terminal section with an anchored div id."""
    for prev in table.find_all_previous(id=True, limit=6):
        pid = (prev.get("id") or "").lower()
        for name, pat in NWSA_ANCHORS:
            if pid.startswith(pat):
                return name
    return None


def parse_nwsa_erd(raw: bytes, ref: date) -> list[dict]:
    soup = BeautifulSoup(raw, "lxml")
    rows = []
    content = _main_content(soup)
    tables = [t for t in content.find_all("table") if not t.find("table")]
    for table, (heading, matrix) in zip(tables, _tables_with_context(content)):
        header = [h.strip() for h in matrix[0]]
        if len(matrix) < 2:
            continue
        terminal = _nwsa_terminal_for(table)
        if terminal is None:
            continue
        for idx, r in enumerate(matrix[1:]):
            if not any(c.strip() for c in r) or [c.strip().upper() for c in r] == [h.upper() for h in header]:
                continue  # blank spacer row or repeated header row
            rec = dict(zip(header, r))
            vessel = rec.get("Vessel Name") or rec.get("Vessel") or r[0]
            voyage = rec.get("Voyage") or rec.get("Vessel Voyage No") or ""
            row = {
                "kind": "erd",
                "entity_key": f"{terminal}|erd|{vessel}|{voyage}" if voyage else f"{terminal}|erd|{vessel}|#{idx}",
                "terminal": terminal,
                "vessel": vessel,
                "voyage": voyage,
                "cells": rec,
            }
            for k, v in rec.items():
                kl = k.lower()
                if "cut" in kl:
                    row["cutoff"] = v
                    row["cutoff_iso"] = parse_datetime_token(v, ref)
                elif "erd" in kl or "receiv" in kl or "start" in kl:
                    row.setdefault("erd", v)
                    row.setdefault("erd_iso", parse_datetime_token(v, ref))
            rows.append(row)
    return rows


# ---------- eModal slots (mock or real) ----------

def parse_emodal_slots(raw: bytes, ref: date) -> list[dict]:
    doc = json.loads(raw)
    is_mock = bool(doc.get("mock"))
    rows = []
    for q in doc.get("queries", []):
        req, resp = q["request"], q["response"]
        eq = req.get("equipment", {})
        slots = resp.get("result") or []
        by_day: dict[str, int] = {}
        for s in slots:
            by_day[s["startTime"][:10]] = by_day.get(s["startTime"][:10], 0) + 1
        key = f"{q['terminal']}|slots|{req.get('tradeType')}|{req.get('pickDrop')}|{eq.get('size')}{eq.get('type')}|{eq.get('line') or 'ANY'}"
        rows.append(
            {
                "kind": "slot_window",
                "entity_key": key,
                "terminal": q["terminal"],
                "mock": is_mock,
                "trade_type": req.get("tradeType"),
                "pick_drop": req.get("pickDrop"),
                "equipment": f"{eq.get('size')}{eq.get('type')}",
                "line": eq.get("line"),
                "facility_code": (req.get("facility") or {}).get("facilityCode"),
                "slot_count": len(slots),
                "first_slot": slots[0]["startTime"] if slots else None,
                "last_slot": slots[-1]["startTime"] if slots else None,
                "by_day": by_day,
                "generated_at": doc.get("generated_at"),
            }
        )
    return rows


# ---------- dispatch ----------

def run_parser(parser: str, raw: bytes, terminal: str | None, ref: date, src: dict | None = None) -> list[dict]:
    if parser == "nwsa_turn_feed":
        return parse_nwsa_turn_feed(raw, ref)
    if parser == "camera":
        return parse_camera(raw, terminal, (src or {}).get("camera"))
    if parser == "terminal_page":
        return parse_terminal_page(raw, terminal or "?", ref)
    if parser == "wut_empties":
        return parse_wut_empties(raw, ref)
    if parser == "nwsa_bulletins":
        return parse_nwsa_bulletins(raw, ref)
    if parser == "nwsa_turn_times":
        return parse_nwsa_turn_times(raw, ref)
    if parser == "wut_erd":
        return parse_wut_erd(raw, ref)
    if parser == "nwsa_erd":
        return parse_nwsa_erd(raw, ref)
    if parser == "emodal_slots":
        return parse_emodal_slots(raw, ref)
    raise ValueError(f"no parser named {parser}")


def parse_capture(capture_id: int, force: bool = False, conn: sqlite3.Connection | None = None) -> int:
    from .capture import SOURCES

    own = conn is None
    conn = conn or store.connect()
    try:
        cap = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
        if cap is None:
            raise ValueError(f"no capture {capture_id}")
        (cid, source_id, fetched_at, url, status, content_hash, error, *rest) = cap
        if content_hash is None:
            return 0
        existing = conn.execute("SELECT COUNT(*) FROM parsed_rows WHERE capture_id = ?", (cid,)).fetchone()[0]
        if existing and not force:
            return existing
        if existing and force:
            conn.execute("DELETE FROM parsed_rows WHERE capture_id = ?", (cid,))
        src = SOURCES.get(source_id)
        if not src or not src.get("parser"):
            return 0
        path = store.find_raw(content_hash)
        if path is None:
            raise FileNotFoundError(f"raw body {content_hash} missing")
        ref = datetime.fromisoformat(fetched_at).astimezone(PT).date()
        try:
            rows = run_parser(src["parser"], path.read_bytes(), src.get("terminal"), ref, src)
        except Exception as exc:  # noqa: BLE001
            conn.execute(
                "INSERT INTO parse_errors (capture_id, source_id, error, at) VALUES (?, ?, ?, ?)",
                (cid, source_id, f"{type(exc).__name__}: {exc}", datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            conn.commit()
            raise
        for row in rows:
            row.setdefault("parser_version", PARSER_VERSION)
            js, h = _canon(row)
            conn.execute(
                "INSERT INTO parsed_rows (capture_id, source_id, terminal, kind, entity_key, row_json, row_hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, source_id, row.get("terminal"), row["kind"], row["entity_key"], js, h),
            )
        conn.commit()
        return len(rows)
    finally:
        if own:
            conn.close()


def main() -> None:
    force = "--force" in sys.argv
    conn = store.connect()
    if "--all" in sys.argv:
        if force:
            ids = [r[0] for r in conn.execute("SELECT id FROM captures WHERE content_hash IS NOT NULL ORDER BY id")]
        else:
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT c.id FROM captures c LEFT JOIN parsed_rows p ON p.capture_id = c.id"
                    " WHERE c.content_hash IS NOT NULL GROUP BY c.id HAVING COUNT(p.id) = 0 ORDER BY c.id"
                )
            ]
    else:
        ids = [int(a) for a in sys.argv[1:] if a.isdigit()]
    total = 0
    for cid in ids:
        try:
            n = parse_capture(cid, force=force, conn=conn)
            total += n
            print(f"capture {cid}: {n} rows")
        except Exception as exc:  # noqa: BLE001
            print(f"capture {cid}: ERROR {exc}", file=sys.stderr)
    conn.close()
    print(f"{len(ids)} captures, {total} rows")


if __name__ == "__main__":
    main()
