"""Normalize the business-entity infrastructure snapshots to parquet.

Three small current-state files tie business entities to facilities:

- Facility Infrastructure: facility -> current OperatorBAID (+ start
  date) and LicenseeBAID, plus subtype, status, location, licence,
  orphan flag and the Directive 060 TierAggregateID.
- Facility Operator History: the full operatorship time series
  (StartDate/EndDate, open interval = '9999-12') — attribute any
  historical month to the right operator across transfers.
- Business Associate: the BA registry — legal name, address, corporate
  status, amalgamation chain (roll defunct BAIDs into successors).

Columns are kept exactly as Petrinex names them: these are reference
tables, not the analytical core, and 40-odd renames would just invite
transcription bugs. The Well Infrastructure file is NOT handled here —
its per-event rows need real modeling (see roadmap).
"""
import duckdb

from . import config
from .extract import READ_CSV_OPTS, extract_csv

FILES = (
    "Facility Infrastructure",
    "Facility Operator History",
    "Business Associate",
)


def build(province: str = "AB") -> None:
    out_dir = config.OUT / "infra"
    work = config.OUT / "work"
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    for name in FILES:
        zp = config.infra_zip(province, name)
        if not zp.exists():
            raise SystemExit(f"missing {zp}; run fetch-infra first")
        out_path = config.infra_parquet(province, name)
        csv_path = extract_csv(zp, work)
        try:
            con.execute(f"""
                copy (select * from read_csv('{csv_path}', {READ_CSV_OPTS}))
                to '{out_path}' (format parquet, compression zstd)
            """)
        finally:
            csv_path.unlink()
        n = con.execute(f"select count(*) from '{out_path}'").fetchone()[0]
        print(f"  {name}: {n:,} rows -> {out_path.name}")
