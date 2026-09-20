"""Parser tests against frozen pages in tests/fixtures.

Every assertion here is a fact a human verified against the live page on 2026-09-20,
or a bug that was fixed that day. If a parser change breaks one of these, the change
is wrong or the page changed; either way, look before updating the expectation.
"""
from datetime import date
from pathlib import Path

import pytest

from src import parse

FIX = Path(__file__).parent / "fixtures"
REF = date(2026, 9, 20)  # the PT date the fixtures were captured


def load(name: str) -> bytes:
    return (FIX / name).read_bytes()


def rows_of(kind: str, rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["kind"] == kind]


# ---------- T18 (SSA, Seattle) ----------

@pytest.fixture(scope="module")
def t18():
    return parse.parse_terminal_page(load("t18_update.html"), "T18", REF)


def test_t18_gate_days_cover_two_weeks(t18):
    gate = rows_of("gate_day", t18)
    dates = sorted({r["date_iso"] for r in gate})
    assert "2026-09-14" in dates and "2026-09-25" in dates
    assert len(dates) == 10  # Mon–Fri, two weeks


def test_t18_friday_closed_weekday_open(t18):
    by_date = {r["date_iso"]: r for r in rows_of("gate_day", t18)}
    assert by_date["2026-09-18"]["status"] == "closed"
    assert by_date["2026-09-25"]["status"] == "closed"
    assert by_date["2026-09-14"]["status"] == "open"
    assert by_date["2026-09-14"]["shift"] == "0800-1600"


def test_t18_hlc_40dh_drop_refused_pick_accepted(t18):
    rules = {(r["line"], r["equipment"], r["action"]): r for r in rows_of("empty_rule", t18)}
    assert rules[("HLC", "40DH", "drop")]["accepted"] is False
    assert rules[("HLC", "40DH", "pick")]["accepted"] is True


def test_t18_line_typo_cleaned_but_raw_kept(t18):
    cma = [r for r in rows_of("empty_rule", t18) if r["line"].startswith("CMA")]
    assert cma, "CMA/APL/ANL row missing"
    assert all(r["line"] == "CMA/APL/ANL" for r in cma)
    assert all(r["line_raw"] == "CMA/APL/ANLYES" for r in cma)


def test_t18_no_duplicate_rules_from_colspan(t18):
    keys = [(r["line"], r["equipment"], r["action"]) for r in rows_of("empty_rule", t18)]
    assert len(keys) == len(set(keys))


def test_t18_chassis_table_is_not_empty_rules(t18):
    lines = {r["line"] for r in rows_of("empty_rule", t18)}
    assert not any("DCLI" in l or "TRAC" in l for l in lines)
    equipment = {r["equipment"] for r in rows_of("empty_rule", t18)}
    assert equipment == {"20", "40DR", "40DH", "45DH", "REEFER", "SPECIAL"}


def test_t18_friday_closure_notice_found(t18):
    notices = rows_of("notice", t18)
    assert any("closed on fridays" in r["text"].lower() for r in notices)


# ---------- T5 (SSA, Seattle): per-line OPEN/CLOSED tables ----------

@pytest.fixture(scope="module")
def t5():
    return parse.parse_terminal_page(load("t5_update.html"), "T5", REF)


def test_t5_monday_closed(t5):
    by_date = {r["date_iso"]: r for r in rows_of("gate_day", t5)}
    assert by_date["2026-09-14"]["status"] == "closed"
    assert by_date["2026-09-15"]["status"] == "open"


def test_t5_msc_empties_parsed_with_action_from_heading(t5):
    rules = rows_of("empty_rule", t5)
    assert rules and all(r["line"] == "MSC" for r in rules)
    actions = {r["action"] for r in rules}
    assert actions == {"drop", "pick"}
    drop = {r["equipment"]: r for r in rules if r["action"] == "drop"}
    assert drop["20DR"]["accepted"] is True
    assert "Fridays" in drop["40RH"]["cell_raw"]  # "Open on Fridays Only" still reads as open


# ---------- WUT (HMM, Tacoma) ----------

@pytest.fixture(scope="module")
def wut_empties():
    return parse.parse_wut_empties(load("wut_empties.html"), REF)


def test_wut_matrix_lines_and_sizes(wut_empties):
    rules = rows_of("empty_rule", wut_empties)
    assert {r["line"] for r in rules} == {"HLC", "HMM", "ONE", "YML"}
    assert {r["equipment"] for r in rules} == {"20", "40SD", "40HC", "45HC", "REEFER"}
    assert not any(r["equipment"] in ("OT", "FR") for r in rules)  # overtime/Friday columns are not sizes


def test_wut_hlc_refused_across_the_board(wut_empties):
    hlc = [r for r in rows_of("empty_rule", wut_empties) if r["line"] == "HLC"]
    assert hlc and all(r["accepted"] is False for r in hlc)


def test_wut_as_of_date(wut_empties):
    as_of = rows_of("as_of", wut_empties)
    assert as_of and as_of[0]["as_of_iso"] == "2026-09-21"


def test_wut_update_page_gate_closure_notice():
    rows = parse.parse_terminal_page(load("wut_update.html"), "WUT", REF)
    texts = " ".join(r["text"].lower() for r in rows_of("notice", rows))
    assert "closed on the following dates" in texts


# ---------- Husky and PCT publish prose, not a grid ----------

def test_husky_has_notices_but_no_grid():
    rows = parse.parse_terminal_page(load("husky_update.html"), "Husky", REF)
    assert rows_of("empty_rule", rows) == []
    assert any("no longer accepting chassis" in r["text"].lower() for r in rows_of("notice", rows))


def test_standing_appointment_rules_are_not_notices(t18):
    # The T18 page repeats ~30 paragraphs of appointment rules; only dated or closure text is news.
    texts = [r["text"].lower() for r in rows_of("notice", t18)]
    assert not any("missed appointments are subject to cancellation" in t for t in texts)
    assert len(texts) < 10


def test_pct_gate_days_and_no_grid():
    rows = parse.parse_terminal_page(load("pct_update.html"), "PCT", REF)
    assert rows_of("empty_rule", rows) == []
    by_date = {r["date_iso"]: r for r in rows_of("gate_day", rows)}
    assert len(by_date) == 14  # PCT publishes two full weeks including weekends, dates-only header
    assert by_date["2026-09-07"]["status"] == "closed"  # Labor Day
    assert by_date["2026-09-08"]["status"] == "open" and by_date["2026-09-08"]["shift"] == "0700-1600"
    assert by_date["2026-09-19"]["status"] == "closed"
    assert any("will not accept cma empty" in r["text"].lower() for r in rows_of("notice", rows))


# ---------- port-wide pages ----------

def test_bulletins_have_titles_and_urls():
    rows = parse.parse_nwsa_bulletins(load("nwsa_bulletins.html"), REF)
    assert len(rows) >= 5
    assert all(r["url"].startswith("https://www.nwseaportalliance.com/") for r in rows)
    assert all(r["title"] for r in rows)


def test_turn_times_page_is_recognised_as_placeholder():
    rows = parse.parse_nwsa_turn_times(load("nwsa_turn_times.html"), REF)
    assert {r["terminal"] for r in rows} == {"T5", "T18", "Husky", "PCT", "WUT"}
    assert all(r["placeholder"] and r["na"] for r in rows)


def test_nwsa_erd_attributes_tables_to_terminals():
    rows = parse.parse_nwsa_erd(load("nwsa_erd.html"), REF)
    by_t = {t: [r for r in rows if r["terminal"] == t] for t in ("T5", "T18", "PCT", "WUT")}
    assert all(by_t.values())
    assert any(r["vessel"] == "CHARLOTTE SCHULTE" for r in by_t["WUT"])
    assert not any(r["vessel"].upper() in ("VESSEL", "VESSEL NAME", "CUTOFF") for r in rows)  # no header rows


def test_wut_erd_dates_normalised():
    rows = parse.parse_wut_erd(load("wut_erd.html"), REF)
    cs = next(r for r in rows if r["vessel"] == "CHARLOTTE SCHULTE")
    assert cs["erd"] == "09-23-2026 0700"
    assert cs["erd_iso"].startswith("2026-09-23T07:00")


def test_mock_slots_are_flagged_and_t18_hlc_has_none():
    rows = parse.parse_emodal_slots(load("emodal_slots_mock.json"), REF)
    assert rows and all(r["mock"] is True for r in rows)
    hlc = next(r for r in rows if r["terminal"] == "T18" and r["line"] == "HLC")
    assert hlc["slot_count"] == 0


# ---------- helpers ----------

@pytest.mark.parametrize(
    "tok,expected",
    [
        ("SEPT 14", date(2026, 9, 14)),
        ("Sept. 14th", date(2026, 9, 14)),
        ("9/8", date(2026, 9, 8)),
        ("09/21/2026", date(2026, 9, 21)),
        ("Monday, September 14th", date(2026, 9, 14)),
        ("1/3", date(2027, 1, 3)),  # nearest year to the reference, forward
        ("Cutoff", None),
    ],
)
def test_parse_date_token(tok, expected):
    assert parse.parse_date_token(tok, REF) == expected


@pytest.mark.parametrize(
    "cell,expected",
    [("OPEN", "open"), ("YES", "open"), ("NO", "closed"), ("CLOSED", "closed"),
     ("0800-1600", "open"), ("Open on Fridays Only", "open"), ("N/A", None), ("", None), ("Vessel", None)],
)
def test_status(cell, expected):
    assert parse._status(cell) == expected
