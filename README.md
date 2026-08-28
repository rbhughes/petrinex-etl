# petrinex-etl

Fetch and normalize [Petrinex](https://www.petrinex.ca) public volumetric
data — the monthly, well-level production/injection/disposition reporting
for Alberta (and Saskatchewan) — into clean parquet you can query with
DuckDB, pandas, or anything else.

Petrinex's public files are genuinely rich (every volumetric row for every
well and facility, monthly) and genuinely hostile (nested zips, unquoted-
looking CSVs that are actually quoted, confidentiality masks, a rolling
archive window). This repo is the accumulated fix for all of that,
extracted from a production-scale ML project so others don't have to
rediscover it.

## Quickstart

```sh
pip install -e .
petrinex probe                 # discover the live public window (it slides)
petrinex fetch-vol             # download all monthly zips (resumable, ~25 GB for AB)
petrinex fetch-infra           # well headers (licence, status, location)
petrinex build-wells           # -> data/well_months/AB/YYYY-MM.parquet (~100 MB total)
```

All commands take `--province AB|SK` (AB default; AB verified end-to-end,
the SK endpoint answers on the same URL scheme).

## Output: `well_months`

One parquet per production month; every volumetric row reported against a
well (`FromToIDType='WI'`), **all** activities kept:

| column | meaning |
|---|---|
| `month`, `well_id` | production month, Petrinex WellID (`ABWI...`) |
| `facility_id`, `facility_type`, `facility_subtype` | reporting facility (usually the battery) |
| `operator_baid`, `operator_name` | operator of record that month |
| `activity` | `PROD`, `SHUTIN`, `INJ`, `VENT`, `FLARE`, `FUEL`, `DISP`, ... |
| `product` | `OIL`, `GAS`, `WATER`, `COND`, `STEAM`, ... |
| `volume`, `hours`, `energy` | m³ (gas: e3m³), hours on production, GJ |

Scale (Alberta): ~137,000 producing wells and ~350,000 well rows per
month; 55 months currently public.

## The traps this repo already stepped in

- **Nested zips.** Each monthly download is a zip containing a `.csv.zip`
  containing the CSV. `extract.py` unwraps any depth.
- **The quoting trap.** DuckDB's sniffer detects *no* quoting on these
  files, so a facility name like `"Joffre 8-25,12-20,13-30"` shifts every
  later column. `ignore_errors=true` hides the damage by silently dropping
  those rows — month-dependent, invisible loss. Always `quote='"'`,
  always `all_varchar=true` + `TRY_CAST`, never `ignore_errors`.
- **`***` means confidential**, not zero. TRY_CAST maps it to NULL.
- **Gas is e3m³**; oil/water/condensate are m³. Mixing them corrupts BOE.
- **Negative volumes are amendments**, not errors. Keep them; they net out.
- **The archive is a rolling window** (~5 years for AB). Months fall off
  the front: `petrinex probe` discovers the live bounds; `fetch-vol` is
  resumable so a cron-ish refresh just picks up new months.
- **Production is reported at the battery**, with `FromToIDType='WI'`
  naming the well. Wells are not rows; they are `FromToID`s.
- **`SHUTIN` rows exist** (~15,000 wells/month in AB): the explicitly
  reported inactive inventory most consumers never notice.
- **`Hours` (hours-on-production)** is populated on >99.9% of AB well PROD
  rows — it separates "declining" from "curtailed".

## UWI conversion (`petrinex_etl.uwi`)

The join key between AER ST37 geometry (`UWI_Label`, DLS display format)
and Petrinex (`WellIdentifier`):

```python
>>> well_id_from_label("00/07-19-010-15W4/0")
'100071901015W400'
>>> label_from_well_id("1AA120406220W500")
'AA/12-04-062-20W5/0'
```

Two documented traps: the location exception is **leading** and the event
sequence **trailing** (swapping them still parses and silently ruins the
join), and the location exception is **alphanumeric** (`AA`, `F1`, `W0` —
a digits-only pattern drops 11.7% of Alberta). Match rate on all of
Alberta ST37: 99.99% (532,553/532,623).

## Data licence — read this

Petrinex data is owned by the **Government of Alberta** (Crown copyright;
terms at <https://petrinex.ca/terms>). Commercial use requires prior
consent. **Do not re-host the raw files** — `data/` is gitignored for
that reason; this repo ships code, and everyone pulls the data from the
source. Multiple local projects should share one raw archive via the
`PETRINEX_RAW` env var (or a symlink at `data/raw/`) instead of
re-downloading 25 GB.

## Used by

- [shut-in-prediction](../shut-in-prediction) — early-warning hazard model
  for Alberta well inactivity.
- [methane-outliers](../methane-outliers) — vent/flare/fuel peer-expectation
  models (planned; will add a facility-level table here).
- [well-spacing-playbook](../well-spacing-playbook) — the well-interference
  project this layer was extracted from.

## Roadmap

- `build-facilities`: facility-month table (all activities at facility
  grain) for methane work.
- Verified SK end-to-end build.
- Well Infrastructure CSV -> parquet normalizer.
