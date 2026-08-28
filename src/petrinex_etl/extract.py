"""Unwrap Petrinex's nested zips and read their CSVs safely.

Format facts that cost real debugging time (learned in well-spacing-playbook):

- Monthly volumetric downloads are a zip INSIDE a zip: outer zip holds
  `Vol_YYYY-MM-XX.csv.zip`, which holds the CSV.
- DuckDB's CSV sniffer auto-detects NO quoting on these files, so a quoted
  facility name containing commas ("Joffre 8-25,12-20,...") shifts every
  later column. `ignore_errors=true` hides this by silently dropping such
  rows -- month-dependent, invisible data loss. Always pass `quote='"'`
  explicitly and never use ignore_errors.
- `***` marks confidential values; read all_varchar and TRY_CAST so they
  become NULL instead of a parse failure.
"""
import zipfile
from pathlib import Path

# Interpolate into read_csv('...', {READ_CSV_OPTS}).
READ_CSV_OPTS = "all_varchar=true, quote='\"'"


def extract_csv(zip_path: Path, work: Path) -> Path:
    """Extract the CSV from a (possibly nested) Petrinex zip into work/."""
    work.mkdir(parents=True, exist_ok=True)
    cur = zip_path
    for _ in range(3):
        with zipfile.ZipFile(cur) as z:
            name = z.namelist()[0]
            target = work / Path(name).name
            with z.open(name) as src, open(target, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
        if cur != zip_path:
            cur.unlink()
        if not target.name.lower().endswith(".zip"):
            return target
        cur = target
    raise RuntimeError(f"zip nesting deeper than expected: {zip_path}")
