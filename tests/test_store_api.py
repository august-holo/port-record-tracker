"""Invariants the post relies on: append-only custody, hashes that round-trip, parsers that
never block a capture, mock rows that are always flagged, gaps that read as unknown, and
Pacific day boundaries. Runs against a temporary data directory.
"""
import hashlib
import importlib
import os
import sqlite3
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Fresh store + app modules pointed at tmp_path."""
    monkeypatch.setenv("TSA_DATA_DIR", str(tmp_path))
    import src.store as store

    importlib.reload(store)
    import src.parse as parse
    import src.api as api
    import src.web as web

    importlib.reload(parse)
    importlib.reload(api)
    importlib.reload(web)
    from fastapi.testclient import TestClient

    return {"store": store, "parse": parse, "web": web, "client": TestClient(web.app), "dir": tmp_path}


def add_capture(env, source_id: str, fixture: str, fetched_at: str, is_mock: bool = False) -> int:
    """Insert a capture with an explicit UTC time (record_capture stamps 'now', so we set it after)."""
    store = env["store"]
    body = (FIX / fixture).read_bytes()
    ext = "json" if fixture.endswith(".json") else "html"
    h = store.store_raw(body, ext)
    conn = store.connect()
    from src.capture import SOURCES

    cid = store.record_capture(conn, source_id, SOURCES[source_id]["url"], 200, h, is_mock=is_mock)
    conn.execute("UPDATE captures SET fetched_at = ? WHERE id = ?", (fetched_at, cid))  # test-only time travel
    conn.commit()
    conn.close()
    return cid


# ---------- custody ----------

def test_raw_body_round_trips_by_hash(env):
    store = env["store"]
    body = b"<html>hello</html>"
    h = store.store_raw(body)
    assert h == hashlib.sha256(body).hexdigest()
    assert store.find_raw(h).read_bytes() == body


def test_captures_are_only_ever_added(env):
    store = env["store"]
    conn = store.connect()
    a = store.record_capture(conn, "t18_update", "u", 200, "a" * 64)
    b = store.record_capture(conn, "t18_update", "u", 200, "a" * 64)  # same hash, new row
    rows = conn.execute("SELECT id, content_hash FROM captures ORDER BY id").fetchall()
    conn.close()
    assert [r[0] for r in rows] == [a, b]
    assert b > a


def test_failed_fetch_is_recorded(env):
    store = env["store"]
    conn = store.connect()
    cid = store.record_capture(conn, "t18_update", "u", None, None, error="boom")
    row = conn.execute("SELECT http_status, content_hash, error FROM captures WHERE id = ?", (cid,)).fetchone()
    conn.close()
    assert row == (None, None, "boom")


def test_migration_is_idempotent(env):
    store = env["store"]
    store.connect().close()
    store.connect().close()
    conn = store.connect()
    versions = [r[0] for r in conn.execute("SELECT version FROM schema_version")]
    conn.close()
    assert versions == sorted(set(versions))


# ---------- parsing ----------

def test_parse_is_deterministic(env):
    parse = env["parse"]
    cid = add_capture(env, "t18_update", "t18_update.html", "2026-09-20T18:44:28+00:00")
    parse.parse_capture(cid)
    conn = env["store"].connect()
    first = sorted(r[0] for r in conn.execute("SELECT row_hash FROM parsed_rows WHERE capture_id = ?", (cid,)))
    conn.close()
    parse.parse_capture(cid, force=True)
    conn = env["store"].connect()
    second = sorted(r[0] for r in conn.execute("SELECT row_hash FROM parsed_rows WHERE capture_id = ?", (cid,)))
    conn.close()
    assert first == second and len(first) > 50


def test_parser_failure_is_logged_and_capture_survives(env, monkeypatch):
    parse = env["parse"]
    cid = add_capture(env, "t18_update", "t18_update.html", "2026-09-20T18:44:28+00:00")

    def boom(*a, **k):
        raise RuntimeError("page redesigned")

    monkeypatch.setattr(parse, "parse_terminal_page", boom)
    with pytest.raises(RuntimeError):
        parse.parse_capture(cid)
    conn = env["store"].connect()
    assert conn.execute("SELECT COUNT(*) FROM captures WHERE id = ?", (cid,)).fetchone()[0] == 1
    err = conn.execute("SELECT error FROM parse_errors WHERE capture_id = ?", (cid,)).fetchone()[0]
    conn.close()
    assert "page redesigned" in err


def test_mock_rows_are_flagged_everywhere(env):
    parse = env["parse"]
    cid = add_capture(env, "emodal_slots_mock", "emodal_slots_mock.json", "2026-09-20T18:44:52+00:00", is_mock=True)
    parse.parse_capture(cid)
    r = env["client"].get("/api/captures?source=emodal_slots_mock").json()["captures"]
    assert r and all(c["is_mock"] == 1 for c in r)
    rows = env["client"].get(f"/api/parsed?capture_id={cid}").json()["rows"]
    assert rows and all(row["row"]["mock"] is True for row in rows)


def test_daily_manifest_lists_each_capture_with_its_hash(env):
    import csv
    import src.manifest as manifest
    from datetime import date

    importlib.reload(manifest)
    a = add_capture(env, "wut_erd", "wut_erd.html", "2026-09-20T18:44:00+00:00")
    add_capture(env, "wut_erd", "wut_erd.html", "2026-09-21T00:10:00+00:00")  # next UTC day
    assert manifest.write_day(date(2026, 9, 20)) == 1
    rows = list(csv.DictReader((env["dir"] / "manifests" / "captures-2026-09-20.csv").open()))
    assert [r["id"] for r in rows] == [str(a)]
    assert rows[0]["content_hash"] == hashlib.sha256((FIX / "wut_erd.html").read_bytes()).hexdigest()
    assert manifest.write_day(date(2026, 9, 19)) == 0  # no captures, no file


# ---------- exhibit semantics ----------

def test_day_without_captures_is_unknown_not_fine(env):
    x = env["client"].get("/api/exhibit?terminal=T18&start=2026-09-18&end=2026-09-18").json()
    d = x["days"][0]
    assert d["gate"] is None and d["empties"] is None and d["notices"] == [] and d["slots"] is None
    a = d["answers"]
    assert a["gate_scheduled_open"] is None
    assert a["empties_accepted"] is None
    assert a["appointments_available"] is None


def test_exhibit_reads_gate_and_empties_with_evidence(env):
    parse = env["parse"]
    cid = add_capture(env, "t18_update", "t18_update.html", "2026-09-20T18:44:28+00:00")
    parse.parse_capture(cid)
    x = env["client"].get("/api/exhibit?terminal=T18&start=2026-09-18&end=2026-09-22&line=HLC&equipment=40HC").json()
    by = {d["date"]: d for d in x["days"]}
    assert by["2026-09-18"]["answers"]["gate_scheduled_open"] is False
    assert by["2026-09-22"]["answers"]["gate_scheduled_open"] is True
    e = by["2026-09-22"]["empties"]
    assert e["from_capture"] == cid and e["same_day"] is False and e["capture_pt_date"] == "2026-09-20"
    assert {(r["action"], r["accepted"]) for r in e["rules"]} == {("drop", False), ("pick", True)}
    assert by["2026-09-22"]["answers"]["empties_accepted"] is False
    assert [c["capture_id"] for c in x["captures"]] == [cid]


def test_empties_answer_follows_the_drop_rule_not_the_pick_rule(env):
    parse = env["parse"]
    cid = add_capture(env, "t18_update", "t18_update.html", "2026-09-20T18:44:28+00:00")
    parse.parse_capture(cid)

    def answer(equipment):
        x = env["client"].get(
            f"/api/exhibit?terminal=T18&start=2026-09-20&end=2026-09-20&line=HLC&equipment={equipment}"
        ).json()
        d = x["days"][0]
        return {(r["action"], r["accepted"]) for r in d["empties"]["rules"]}, d["answers"]["empties_accepted"]

    # 45': drop refused and pick refused -> not accepted. 20': both accepted -> accepted.
    assert answer("45HC") == ({("drop", False), ("pick", False)}, False)
    assert answer("20") == ({("drop", True), ("pick", True)}, True)
    # Reefers are listed for pick-up only: no return rule, so the record does not answer.
    assert answer("REEFER") == ({("pick", True)}, None)


def test_mock_channel_is_hidden_unless_switched_on(env, monkeypatch):
    import src.capture as capture

    parse = env["parse"]
    cid = add_capture(env, "emodal_slots_mock", "emodal_slots_mock.json", "2026-09-20T18:44:52+00:00", is_mock=True)
    parse.parse_capture(cid)
    url = "/api/exhibit?terminal=T18&start=2026-09-20&end=2026-09-20"

    monkeypatch.setattr(capture, "MOCK_ENABLED", False)
    x = env["client"].get(url).json()
    assert x["days"][0]["slots"] is None and "MOCK" not in x["caveat"]
    assert not any(c["channel"] == "slots" for c in x["channels"])
    assert not any(s["mock"] for s in env["client"].get("/api/sources").json()["sources"])

    monkeypatch.setattr(capture, "MOCK_ENABLED", True)
    x = env["client"].get(url).json()
    assert x["days"][0]["slots"]["mock"] is True and "MOCK" in x["caveat"]
    assert any(s["mock"] for s in env["client"].get("/api/sources").json()["sources"])


def test_evening_capture_files_under_pacific_day(env):
    parse = env["parse"]
    # 02:00 UTC on the 21st is 19:00 PT on the 20th.
    cid = add_capture(env, "wut_empties", "wut_empties.html", "2026-09-21T02:00:00+00:00")
    parse.parse_capture(cid)
    x = env["client"].get("/api/exhibit?terminal=WUT&start=2026-09-20&end=2026-09-21&line=HLC").json()
    by = {d["date"]: d for d in x["days"]}
    assert by["2026-09-20"]["empties"]["same_day"] is True
    assert by["2026-09-21"]["empties"]["same_day"] is False
    assert x["captures"][0]["fetched_at_pt"].startswith("2026-09-20T19:00")


def test_exhibit_rejects_bad_input(env):
    c = env["client"]
    assert c.get("/api/exhibit?terminal=T99&start=2026-09-01&end=2026-09-02").status_code == 400
    assert c.get("/api/exhibit?terminal=T18&start=2026-09-02&end=2026-09-01").status_code == 400
    assert c.get("/api/exhibit?terminal=T18&start=2026-01-01&end=2026-09-01").status_code == 400


def test_options_come_from_the_terminals_own_grid(env):
    parse = env["parse"]
    cid = add_capture(env, "t18_update", "t18_update.html", "2026-09-20T18:44:28+00:00")
    parse.parse_capture(cid)
    o = env["client"].get("/api/options?terminal=T18").json()
    assert "HLC" in o["lines"] and "ANL" in o["lines"] and "ANLYES" not in o["lines"]
    assert "40HC" in o["equipment"] and "OT" not in o["equipment"]
    assert env["client"].get("/api/options?terminal=Husky").json()["lines"] == []


# ---------- raw viewer ----------

def test_raw_download_matches_hash_and_view_is_sandboxed(env):
    cid = add_capture(env, "t18_update", "t18_update.html", "2026-09-20T18:44:28+00:00")
    h = env["client"].get(f"/api/capture/{cid}").json()["content_hash"]
    dl = env["client"].get(f"/raw/{h}?download=1")
    assert dl.status_code == 200
    assert hashlib.sha256(dl.content).hexdigest() == h
    assert "attachment" in dl.headers["content-disposition"] and h[:12] in dl.headers["content-disposition"]
    view = env["client"].get(f"/raw/{h}")
    assert "sandbox" in view.headers["content-security-policy"]
    assert env["client"].get("/raw/" + "0" * 64).status_code == 404
    assert env["client"].get("/raw/nothex").status_code == 400
