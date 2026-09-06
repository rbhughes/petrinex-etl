"""Retry behaviour against a scripted fake of requests.get."""
from datetime import date

import pytest
import requests

from petrinex_etl import fetch


class FakeResp:
    def __init__(self, status, body=b"PK\x03\x04data"):
        self.status_code = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def iter_content(self, n):
        yield self._body


def script(monkeypatch, responses):
    """Serve responses in order (an Exception instance is raised); each
    call records the url. Returns the call log."""
    calls = []
    queue = list(responses)

    def fake_get(url, **kw):
        calls.append(url)
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(fetch.requests, "get", fake_get)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    return calls


def test_download_retries_404_then_succeeds(tmp_path, monkeypatch):
    calls = script(monkeypatch, [FakeResp(404), FakeResp(503),
                                 requests.ConnectionError("reset"),
                                 FakeResp(200, b"zipbytes")])
    dest = tmp_path / "x.zip"
    fetch._download("http://u", dest, quiet=True)
    assert dest.read_bytes() == b"zipbytes"
    assert len(calls) == 4


def test_download_gives_up_and_leaves_no_partial(tmp_path, monkeypatch):
    calls = script(monkeypatch, [FakeResp(404)] * 3)
    dest = tmp_path / "x.zip"
    with pytest.raises(requests.HTTPError):
        fetch._download("http://u", dest, quiet=True, attempts=3)
    assert not dest.exists()
    assert len(calls) == 3


def test_download_does_not_retry_403(tmp_path, monkeypatch):
    calls = script(monkeypatch, [FakeResp(403)])
    with pytest.raises(requests.HTTPError):
        fetch._download("http://u", tmp_path / "x.zip", quiet=True)
    assert len(calls) == 1


def test_has_data_single_attempt_by_default(monkeypatch):
    calls = script(monkeypatch, [FakeResp(404)])
    assert fetch._has_data("AB", "2026-01") is False
    assert len(calls) == 1


def test_has_data_retries_when_asked(monkeypatch):
    calls = script(monkeypatch, [FakeResp(404), requests.Timeout(),
                                 FakeResp(200)])
    assert fetch._has_data("AB", "2026-01", attempts=4) is True
    assert len(calls) == 3


def test_has_data_rejects_non_zip_200(monkeypatch):
    script(monkeypatch, [FakeResp(200, b'{"Message":"nope"}')])
    assert fetch._has_data("AB", "2026-01") is False


def probe_with(monkeypatch, served: dict, flaky: set):
    """served: month -> True/False. Months in `flaky` 404 on their first
    request and then behave. Returns (window, request log)."""
    seen = {}
    calls = []

    def fake_get(url, **kw):
        month = url.split("/Vol/")[1].split("/")[0]
        calls.append(month)
        n = seen.get(month, 0)
        seen[month] = n + 1
        if month in flaky and n == 0:
            return FakeResp(404)
        return FakeResp(200) if served.get(month) else FakeResp(404)

    monkeypatch.setattr(fetch.requests, "get", fake_get)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)

    class D(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 6)

    monkeypatch.setattr(fetch, "date", D)
    return fetch.probe_window("AB"), calls


def months(first, last):
    out = []
    i = fetch._month_idx(first)
    while i <= fetch._month_idx(last):
        out.append(fetch._month_str(i))
        i += 1
    return out


def test_probe_healthy(monkeypatch):
    served = {m: True for m in months("2022-01", "2026-07")}
    win, calls = probe_with(monkeypatch, served, set())
    assert win == ("2022-01", "2026-07")
    # top edge confirmed once with retries, bottom edge once
    assert calls.count("2026-08") == 1 + fetch.EDGE_ATTEMPTS
    assert calls.count("2021-12") == fetch.EDGE_ATTEMPTS


def test_probe_survives_flaky_404s_at_both_edges_and_inside(monkeypatch):
    served = {m: True for m in months("2022-01", "2026-07")}
    flaky = {"2026-07", "2026-05", "2024-03", "2022-01"}
    win, _ = probe_with(monkeypatch, served, flaky)
    assert win == ("2022-01", "2026-07")


def test_probe_none_when_nothing_served(monkeypatch):
    win, _ = probe_with(monkeypatch, {}, set())
    assert win is None
