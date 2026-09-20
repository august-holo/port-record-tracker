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
