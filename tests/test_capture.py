"""Politeness: requests to one host are spaced out even when the scheduler fires sources together."""
import threading
import time

import src.capture as capture


def test_same_host_requests_are_spaced(monkeypatch):
    calls: list[tuple[str, float]] = []
    monkeypatch.setattr(capture, "MIN_SECONDS_BETWEEN_REQUESTS", 0.2)
    monkeypatch.setattr(capture.requests, "get", lambda url, **kw: calls.append((url, time.monotonic())))

    urls = ["https://a.example/1", "https://a.example/2", "https://a.example/3", "https://b.example/1"]
    threads = [threading.Thread(target=capture._get, args=(u,)) for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    a = sorted(at for url, at in calls if "a.example" in url)
    assert len(calls) == 4
    assert all(later - earlier >= 0.19 for earlier, later in zip(a, a[1:]))


def test_windowed_sources_are_not_stale_overnight():
    from datetime import datetime, timezone

    from src import health

    cam = capture.SOURCES["cam_t5_ingate"]
    at = lambda h, m=0: datetime(2026, 9, 21, h, m, tzinfo=timezone.utc)  # noqa: E731  (PDT = UTC-7)
    assert health._expected_now(cam, at(10)) is False      # 03:00 PT, cameras are off
    assert health._expected_now(cam, at(12, 10)) is False  # 05:10 PT, window only just opened
    assert health._expected_now(cam, at(19)) is True       # noon PT
    assert health._expected_now(capture.SOURCES["nwsa_turn_feed"], at(10)) is True  # no window: always expected


def test_every_camera_is_a_windowed_image_source():
    cams = {k: v for k, v in capture.SOURCES.items() if v["channel"] == "camera"}
    assert len(cams) == len(capture.CAMERAS) == 11
    assert all(v["parser"] == "camera" and v["active_hours"] and v["terminal"] for v in cams.values())
    assert capture._extension("image/jpeg") == "jpg" and capture._extension("text/html; charset=utf-8") == "html"
