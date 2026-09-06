"""Download Petrinex public data files.

The public volumetric archive is a ROLLING window (~5 years for Alberta).
Months slide off the front, so probe_window() discovers the live bounds
instead of trusting constants. Verified 2026-08: AB serves 2022-01 onward;
the SK endpoint answers on the same URL scheme.
"""
import time
from datetime import date
from pathlib import Path

import requests

from . import config

VOL_URL = "https://www.petrinex.gov.ab.ca/publicdata/API/Files/{province}/Vol/{month}/CSV"
INFRA_URL = (
    "https://www.petrinex.gov.ab.ca/publicdata/API/Files/{province}"
    "/Infra/{file}/CSV"
)

# Current-state snapshot files under Infra/. The last three tie business
# entities to facilities: facility -> operator + licensee BAIDs (current),
# the full operatorship time series, and the BA registry itself (legal
# name, corporate status, amalgamation chain).
INFRA_FILES = (
    "Well Infrastructure",
    "Facility Infrastructure",
    "Facility Operator History",
    "Business Associate",
)


# Petrinex is flaky right after its weekend regeneration: files that
# exist answer 404 for a while, and a 404 for a missing month looks the
# same. So a 404 is retryable everywhere, with backoff, and the callers
# decide how many attempts a given request deserves.
RETRY_STATUS = (404, 429, 500, 502, 503, 504)
_TRANSIENT = (requests.ConnectionError, requests.Timeout,
              requests.exceptions.ChunkedEncodingError)


def _backoff(attempt: int, base: float) -> float:
    return base * 2 ** attempt


def _download(url: str, dest: Path, quiet: bool = False,
              attempts: int = 5, base_delay: float = 10.0) -> None:
    """Stream url to dest. Retries transient errors and RETRY_STATUS with
    exponential backoff (10, 20, 40, 80 s by default); the last failure
    is raised as-is."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not quiet:
        print(f"  {url}\n    -> {dest}")
    for attempt in range(attempts):
        try:
            with requests.get(url, stream=True, timeout=300) as r:
                if r.status_code in RETRY_STATUS and attempt < attempts - 1:
                    raise requests.HTTPError(
                        f"{r.status_code} for {url}", response=r)
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            break
        except (requests.HTTPError, *_TRANSIENT) as e:
            dest.unlink(missing_ok=True)
            retryable = (not isinstance(e, requests.HTTPError)
                         or e.response.status_code in RETRY_STATUS)
            if not retryable or attempt == attempts - 1:
                raise
            delay = _backoff(attempt, base_delay)
            print(f"    retry {attempt + 1}/{attempts - 1} in {delay:.0f}s: {e}")
            time.sleep(delay)
    if not quiet:
        print(f"    done ({dest.stat().st_size / 1e6:.1f} MB)")


def _month_str(idx: int) -> str:
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def _has_data(province: str, month: str,
              attempts: int = 1, base_delay: float = 5.0) -> bool:
    """True if the month's zip is served. With attempts > 1 a miss is
    retried with backoff, so a flaky 404 is not mistaken for the edge
    of the public window."""
    url = VOL_URL.format(province=province, month=month)
    for attempt in range(attempts):
        try:
            with requests.get(url, stream=True, timeout=90) as r:
                if r.status_code == 200:
                    return next(r.iter_content(8), b"")[:2] == b"PK"  # zip magic
        except _TRANSIENT:
            pass
        if attempt < attempts - 1:
            time.sleep(_backoff(attempt, base_delay))
    return False


# How hard to confirm a window edge: 3 retries at 5, 10, 20 s.
EDGE_ATTEMPTS = 4


def probe_window(province: str = "AB") -> tuple[str, str] | None:
    """Discover the live public window as ('YYYY-MM', 'YYYY-MM').

    Both edges are confirmed with retries: the month just past `latest`
    and the first miss below `earliest` must stay missing across
    EDGE_ATTEMPTS, otherwise the walk continues."""
    today = date.today()
    tidx = today.year * 12 + today.month - 1
    latest = None
    for back in range(12):
        month = _month_str(tidx - back)
        if _has_data(province, month):
            latest = month
            break
    if latest is None:
        return None
    lidx = _month_idx(latest)
    # Confirm the top edge: the month after `latest` may have 404'd
    # transiently. Walk forward while a retried check says it exists.
    while lidx < tidx and _has_data(province, _month_str(lidx + 1),
                                    attempts=EDGE_ATTEMPTS):
        lidx += 1
    latest = _month_str(lidx)
    # Walk back from the LATEST month present -- the current calendar month
    # is never published yet, so walking back from today stalls immediately.
    earliest = latest
    for back in range(1, 96):
        month = _month_str(lidx - back)
        if not _has_data(province, month, attempts=EDGE_ATTEMPTS):
            break
        earliest = month
    return earliest, latest


def _month_idx(month: str) -> int:
    y, m = (int(v) for v in month.split("-"))
    return y * 12 + m - 1


def fetch_vol(province: str = "AB",
              first: str | None = None, last: str | None = None) -> None:
    """Fetch monthly volumetric zips. Resumable: existing files are skipped."""
    if first is None or last is None:
        window = probe_window(province)
        if window is None:
            raise SystemExit(f"no public volumetric months found for {province}")
        first, last = window
        print(f"  live public window for {province}: {first} .. {last}")
    out = config.vol_dir(province)
    on_disk = sorted(p.name[4:11] for p in out.glob(f"Vol_*-{province}.csv.zip"))
    if on_disk and (first > on_disk[0] or last < on_disk[-1]):
        print(f"  WARNING: probed window {first}..{last} is narrower than "
              f"the archive on disk {on_disk[0]}..{on_disk[-1]}; "
              f"Petrinex is probably flaky right now")
    months = [_month_str(i)
              for i in range(_month_idx(first), _month_idx(last) + 1)]
    got = skipped = 0
    for i, month in enumerate(months, 1):
        dest = out / f"Vol_{month}-{province}.csv.zip"
        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            continue
        try:
            _download(VOL_URL.format(province=province, month=month), dest,
                      quiet=True)
            got += 1
        except requests.HTTPError as e:
            print(f"    {month}: unavailable ({e.response.status_code}) -- skipping")
            dest.unlink(missing_ok=True)
            continue
        if i % 10 == 0 or i == len(months):
            print(f"    {i}/{len(months)} ({got} fetched, {skipped} present)")
    total = sum(p.stat().st_size for p in out.glob("*.zip"))
    print(f"  done: {got} fetched, {skipped} already present, "
          f"{total / 1e6:.0f} MB in {out}")


def fetch_infra(province: str = "AB",
                names: tuple[str, ...] = INFRA_FILES) -> None:
    """Fetch the infrastructure snapshot CSVs. Unlike volumetrics these
    are current-state files, so re-running always overwrites them."""
    for name in names:
        url = INFRA_URL.format(province=province, file=name.replace(" ", "%20"))
        _download(url, config.infra_zip(province, name))
