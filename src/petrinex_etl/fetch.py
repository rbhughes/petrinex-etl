"""Download Petrinex public data files.

The public volumetric archive is a ROLLING window (~5 years for Alberta).
Months slide off the front, so probe_window() discovers the live bounds
instead of trusting constants. Verified 2026-08: AB serves 2022-01 onward;
the SK endpoint answers on the same URL scheme.
"""
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


def _download(url: str, dest: Path, quiet: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not quiet:
        print(f"  {url}\n    -> {dest}")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    if not quiet:
        print(f"    done ({dest.stat().st_size / 1e6:.1f} MB)")


def _month_str(idx: int) -> str:
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def _has_data(province: str, month: str) -> bool:
    url = VOL_URL.format(province=province, month=month)
    with requests.get(url, stream=True, timeout=90) as r:
        if r.status_code != 200:
            return False
        return next(r.iter_content(8), b"")[:2] == b"PK"  # zip magic


def probe_window(province: str = "AB") -> tuple[str, str] | None:
    """Discover the live public window as ('YYYY-MM', 'YYYY-MM')."""
    today = date.today()
    latest = None
    for back in range(12):
        month = _month_str(today.year * 12 + today.month - 1 - back)
        if _has_data(province, month):
            latest = month
            break
    if latest is None:
        return None
    # Walk back from the LATEST month present -- the current calendar month
    # is never published yet, so walking back from today stalls immediately.
    ly, lm = (int(v) for v in latest.split("-"))
    lidx = ly * 12 + lm - 1
    earliest = latest
    for back in range(1, 96):
        month = _month_str(lidx - back)
        if not _has_data(province, month):
            break
        earliest = month
    return earliest, latest


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
    fy, fm = (int(v) for v in first.split("-"))
    ly, lm = (int(v) for v in last.split("-"))
    months = [_month_str(i) for i in range(fy * 12 + fm - 1, ly * 12 + lm)]
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
