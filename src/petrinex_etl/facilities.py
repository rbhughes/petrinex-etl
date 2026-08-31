"""Build the facility_months table: EVERY volumetric row at reporting-
facility grain, counterparty preserved, one parquet per month.

well_months keeps only rows attributed to wells (FromToIDType='WI').
That is the wrong cut for methane accounting: measured on 2025-06 AB,
well-attributed rows carry only ~1% of FUEL volume, ~3% of FLARE and
~48% of VENT — the rest is reported against the facility itself
(FromToID = the reporting facility) or other facilities. This table
keeps every row and preserves the counterparty columns so consumers
can make their own cut.

Double-counting, verified on 2025-06 AB: where a facility reports both
per-well (WI) and self-referencing VENT/FLARE/FUEL rows for the same
product, the sums differ — the self rows are ADDITIVE equipment-level
volumes, not duplicated totals of the well allocation (near-equal cases
are confined to <5 m3 volumes where rounding makes any two sums match).
Summing all rows per facility is therefore the correct facility total.
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
                ReportingFacilityID          as facility_id,
                ReportingFacilityType        as facility_type,
                ReportingFacilitySubTypeDesc as facility_subtype,
                OperatorBAID                 as operator_baid,
                OperatorName                 as operator_name,
                ActivityID                   as activity,
                ProductID                    as product,
                FromToID                     as from_to_id,
                FromToIDType                 as from_to_type,
                try_cast(Volume as double)   as volume,
                try_cast(Hours as double)    as hours,
                try_cast(Energy as double)   as energy
            from read_csv('{csv_path}', {READ_CSV_OPTS})
        ) to '{out_path}' (format parquet, compression zstd)
    """)
    return con.execute(f"select count(*) from '{out_path}'").fetchone()[0]


def build(province: str = "AB") -> None:
    raw = config.vol_dir(province)
    out = config.facility_months_dir(province)
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
        print(f"  {month}: {n:,} facility rows", flush=True)
    print(f"  built {done} months, skipped {skipped} existing -> {out}")
