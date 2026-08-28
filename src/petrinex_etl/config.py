"""Path resolution. Raw Petrinex files are Crown data: kept out of git,
shared between projects via PETRINEX_RAW rather than duplicated."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = Path(os.environ.get("PETRINEX_RAW", ROOT / "data" / "raw"))
OUT = Path(os.environ.get("PETRINEX_OUT", ROOT / "data"))

PROVINCES = ("AB", "SK")


def vol_dir(province: str) -> Path:
    return RAW / "vol" / province


def infra_zip(province: str) -> Path:
    return RAW / "infra" / f"{province}_Well_Infrastructure_CSV.zip"


def well_months_dir(province: str) -> Path:
    return OUT / "well_months" / province
