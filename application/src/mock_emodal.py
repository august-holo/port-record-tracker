"""MOCK appointment-availability channel.

This is NOT real data. It exists so the exhibit and the API can show the shape of
the sixth channel (eModal `POST /api/appointments/move/slots`) before we have
credentials. Every capture it writes is flagged `is_mock=1`, its URL starts with
`mock://`, and the body says so on the first line. Parsed rows carry `"mock": true`.

Shape follows the public eModal Appointments API (Swagger v1): request is a move
(tradeType I/X/Empty, pickDrop, equipment size/type, facilityCode); response is a
TimeFrameListResultInfo with a list of TimeFrame {startTime, endTime, id}.

The synthetic rules are deliberately boring and documented here so nobody
mistakes a pattern in the mock for a fact about the port:
  * windows are 60 minutes, 08:00-16:00 America/Los_Angeles, next 3 days
  * T18 has no slots on Fridays; T5 has no slots on Mondays (their published closures)
  * the 08:00 and 09:00 windows are "limited": gone once the local clock passes 08:30
  * empty drops for line HLC at T18 return no slots (T18's published restriction)
  * everything else is available
"""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import store

PT = ZoneInfo("America/Los_Angeles")

FACILITIES = {"T18": "SEAT18", "T5": "SEAT5", "Husky": "TACHUS", "PCT": "TACPCT", "WUT": "TACWUT"}
QUERIES = [
    # (terminal, tradeType, pickDrop, size, type, line)
    ("T18", "Empty", "Drop", "40", "HC", "HLC"),
    ("T18", "Empty", "Drop", "40", "HC", "MAE"),
    ("T18", "Import", "Pick", "40", "HC", None),
    ("T5", "Empty", "Drop", "40", "HC", "MSC"),
    ("T5", "Import", "Pick", "40", "HC", None),
    ("Husky", "Empty", "Drop", "40", "HC", "ONE"),
    ("PCT", "Import", "Pick", "40", "HC", None),
    ("WUT", "Empty", "Drop", "40", "HC", "HMM"),
]
WINDOW_HOURS = range(8, 16)


def _slots_for(now_pt: datetime, terminal: str, trade: str, pick_drop: str, line: str | None) -> list[dict]:
    out = []
    slot_id = 1
    for day_offset in range(0, 3):
        day = (now_pt + timedelta(days=day_offset)).date()
        weekday = day.weekday()  # Mon=0
        if terminal == "T18" and weekday == 4:
            continue
        if terminal == "T5" and weekday == 0:
            continue
        if weekday >= 5:
            continue
        if terminal == "T18" and trade == "Empty" and line == "HLC":
            continue
        for hour in WINDOW_HOURS:
            start = datetime.combine(day, datetime.min.time(), tzinfo=PT).replace(hour=hour)
            end = start + timedelta(hours=1)
            if end <= now_pt:
                continue
            if hour in (8, 9) and now_pt.replace(hour=8, minute=30, second=0, microsecond=0) <= now_pt and day_offset == 0:
                continue  # limited morning windows sold out
            out.append(
                {
                    "startTime": start.isoformat(timespec="minutes"),
                    "endTime": end.isoformat(timespec="minutes"),
                    "id": slot_id,
                    "preAdvice": None,
                }
            )
            slot_id += 1
    return out


def build_body(now_utc: datetime | None = None) -> bytes:
    now_utc = now_utc or datetime.now(timezone.utc)
    now_pt = now_utc.astimezone(PT)
    queries = []
    for terminal, trade, pick_drop, size, eq_type, line in QUERIES:
        request = {
            "facility": {"facilityCode": FACILITIES[terminal]},
            "tradeType": trade,
            "pickDrop": pick_drop,
            "equipment": {"size": size, "type": eq_type, "line": line},
        }
        result = _slots_for(now_pt, terminal, trade, pick_drop, line)
        response = {
            "status": 0,
            "message": None,
            "messages": [],
            "attemptedTimeSlot": None,
            "result": result,
        }
        queries.append({"terminal": terminal, "request": request, "response": response})
    doc = {
        "MOCK": "THIS IS SYNTHETIC DATA. It demonstrates the shape of the eModal slots channel; it is not a record of the port.",
        "mock": True,
        "generated_at": now_utc.isoformat(timespec="seconds"),
        "endpoint": "POST /api/appointments/move/slots (mocked)",
        "queries": queries,
    }
    return json.dumps(doc, indent=1, sort_keys=False).encode()


def capture(source_id: str, src: dict) -> int:
    conn = store.connect()
    try:
        body = build_body()
        content_hash = store.store_raw(body, "json")
        capture_id = store.record_capture(
            conn, source_id, src["url"], 200, content_hash, is_mock=True, content_type="application/json"
        )
        print(f"[{source_id}] MOCK hash={content_hash[:12]}")
    finally:
        conn.close()
    try:
        from . import parse

        n = parse.parse_capture(capture_id)
        print(f"[{source_id}] parsed {n} rows (mock)")
    except Exception as exc:  # noqa: BLE001
        print(f"[{source_id}] parse error: {exc}")
    return capture_id
