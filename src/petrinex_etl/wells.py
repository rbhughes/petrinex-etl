"""Build the well_months table: every volumetric row reported against a
well (FromToIDType='WI'), all activities, one parquet per month.

Keeping ALL activities (PROD, SHUTIN, INJ, VENT, FLARE, FUEL, ...) costs
little and serves very different downstream uses: production modeling,
shut-in detection, methane accounting. ~420 MB of raw zips distill
to ~100 MB of zstd parquet for Alberta.
"""
from pathlib import Path

import duckdb

from . import config
from .extract import READ_CSV_OPTS, extract_csv


def build_month(con, csv_path: Path, out_path: Path) -> int:
    con.execute(f"""
        copy (
            select
                ProductionMonth              as month,
                FromToID                     as well_id,
                ReportingFacilityID          as facility_id,
                ReportingFacilityType        as facility_type,
                ReportingFacilitySubTypeDesc as facility_subtype,
                OperatorBAID                 as operator_baid,
                OperatorName                 as operator_name,
                ActivityID                   as activity,
                ProductID                    as product,
                try_cast(Volume as double)   as volume,
                try_cast(Hours as double)    as hours,
                try_cast(Energy as double)   as energy
            from read_csv('{csv_path}', {READ_CSV_OPTS})
            where FromToIDType = 'WI'
        ) to '{out_path}' (format parquet, compression zstd)
    """)
    return con.execute(f"select count(*) from '{out_path}'").fetchone()[0]


def build(province: str = "AB") -> None:
    raw = config.vol_dir(province)
    out = config.well_months_dir(province)
    work = config.OUT / "work"
    out.mkdir(parents=True, exist_ok=True)
    zips = sorted(raw.glob(f"Vol_*-{province}.csv.zip"))
    if not zips:
        raise SystemExit(f"no volumetric zips under {raw}; run fetch-vol first")
    con = duckdb.connect()
    done = skipped = 0
    for zp in zips:
        month = zp.name.split("_")[1][:7]
        out_path = out / f"{month}.parquet"
        if out_path.exists():
            skipped += 1
            continue
        csv_path = extract_csv(zp, work)
        try:
            n = build_month(con, csv_path, out_path)
        finally:
            csv_path.unlink()
        done += 1
        print(f"  {month}: {n:,} well rows", flush=True)
    print(f"  built {done} months, skipped {skipped} existing -> {out}")
