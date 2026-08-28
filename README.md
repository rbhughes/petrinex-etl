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
petrinex fetch-vol             # all monthly zips (resumable; AB ~420 MB)
petrinex fetch-infra           # well headers (licence, status, location)
petrinex build-wells           # -> data/well_months/AB/  (~100 MB)
```

All commands take `--province AB|SK` (AB default; AB verified end-to-end,
the SK endpoint answers on the same URL scheme).

## CLI reference

Everything runs through one entry point, installed by `pip install -e .`
(or run without installing: `python -m petrinex_etl.cli`).

```text
petrinex [--province {AB,SK}] <command> [options]
```

`--province` is a GLOBAL option and goes BEFORE the command
(`petrinex --province SK probe`, not `petrinex probe --province SK`).
Default is `AB`. Alberta is verified end-to-end; for Saskatchewan the
endpoint answers on the same URL scheme but the downstream build has not
been validated — check the column names before trusting it.

All paths below are controlled by two environment variables:

| variable | default | meaning |
|---|---|---|
| `PETRINEX_RAW` | `<repo>/data/raw` | where raw downloads live |
| `PETRINEX_OUT` | `<repo>/data` | where parquet outputs land |

If several local projects use Petrinex data, point them at ONE raw
archive (env var, or symlink `data/raw` to it) instead of re-downloading.

### `petrinex probe`

Discovers the live public volumetric window and prints it:

```text
$ petrinex probe
AB: 2022-01 .. 2026-07
```

How: requests the current calendar month, walks BACKWARD up to 12 months
until a real zip answers (the current month is never published yet —
Petrinex reports lag ~1-2 months), then keeps walking back up to 96
months until the first 404. Each check downloads only the first 8 bytes
(the zip magic number), so a probe costs a few dozen tiny requests.

Run this first, and re-run it before any scheduled fetch: the window is
ROLLING, so months silently fall off the front as new ones appear.

### `petrinex fetch-vol [--first YYYY-MM] [--last YYYY-MM]`

Downloads one zip per production month into
`$PETRINEX_RAW/vol/<province>/Vol_<YYYY-MM>-<province>.csv.zip`.

- **With no options**, it probes the live window and fetches all of it.
- `--first`/`--last` pin an explicit inclusive range — useful for
  topping up just the newest months in a cron job, or re-fetching a
  month that Petrinex amended. Both must be given together.
- **Resumable:** a month whose file already exists (non-empty) is
  skipped, so re-running after an interruption — or on a schedule —
  only transfers what is missing. To force a re-download, delete the
  month's zip first.
- A 404 on an individual month (the window moved) is reported and
  skipped, never fatal.
- Size: ~8 MB per month; the full 55-month Alberta window is ~420 MB.
- Progress prints every 10 months; the final line totals fetched,
  skipped, and MB on disk.

### `petrinex fetch-infra`

Downloads the Well Infrastructure CSV (one zip, ~63 MB for AB) to
`$PETRINEX_RAW/infra/<province>_Well_Infrastructure_CSV.zip` —
per-event well headers: identifiers, licence, status, location, linked
facility. This is the bridge between well IDs and everything else
(see the UWI section). Unlike volumetrics it is a single
current-state snapshot, so re-running always overwrites it.

### `petrinex build-wells`

Transforms every raw monthly zip into
`$PETRINEX_OUT/well_months/<province>/<YYYY-MM>.parquet`:

- Unwraps the nested zip (outer zip -> inner `.csv.zip` -> CSV) into
  `$PETRINEX_OUT/work/`, one month at a time. The ~120 MB CSV exists
  only transiently and is deleted after each month; peak scratch use is
  one month's CSV.
- Reads with the safe CSV options (`quote='"'`, `all_varchar`,
  `TRY_CAST` — see the traps section), keeps every row reported against
  a well (`FromToIDType='WI'`), all activities, and writes
  zstd-compressed parquet. The full Alberta window is ~100 MB.
- **Resumable:** months whose parquet already exists are skipped. After
  a fresh `fetch-vol` picks up new months, `build-wells` processes just
  those. To rebuild a month (e.g. after re-fetching an amended file),
  delete its parquet.
- Errors out with a hint if no zips are present (run `fetch-vol` first).
- Runtime: a few seconds per month; a full AB build takes minutes.

### Typical workflows

First-time setup:

```sh
petrinex probe          # see what's available
petrinex fetch-vol      # ~420 MB
petrinex fetch-infra
petrinex build-wells
```

Monthly refresh (safe to run blindly — every step is incremental):

```sh
petrinex fetch-vol && petrinex build-wells
```

Then query from anything that reads parquet:

```python
import duckdb
duckdb.sql("""
    select month, count(distinct well_id) wells
    from 'data/well_months/AB/*.parquet'
    where activity = 'PROD' and volume > 0
    group by 1 order by 1
""")
```

## Output: `well_months`

One parquet per production month; every volumetric row reported against a
well (`FromToIDType='WI'`), **all** activities kept:

| column | meaning |
|---|---|
| `month`, `well_id` | production month, Petrinex WellID (`ABWI...`) |
| `facility_*` | reporting facility id/type/subtype (usually the battery) |
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

### PPDM and format lineage

The outputs here are a plain analytical schema, not PPDM — column names
say what the values are and nothing more. The 16-character UWI itself is
the Canadian DLS-based well identifier convention documented in PPDM's
well-identification guidance (<https://ppdm.org>), of which the Petrinex
`WellIdentifier` is the jurisdiction-prefixed form. If you need this
same Petrinex data in a **PPDM 3.9** relational store (WELL, WELL_ALIAS,
PDEN_VOL_SUMMARY, ...), the
[well-spacing-playbook](../well-spacing-playbook) repo's
`scripts/load_ppdm.py` performs that mapping against a PPDM 3.9 schema
subset, and `docs/PPDM_CROSSWALK.md` in this repo documents it column by
column. Note the PPDM schema DDL is PPDM Association IP: obtain it from
PPDM under their terms; neither repo redistributes it.

## Data licence — read this

Petrinex data is owned by the **Government of Alberta** (Crown copyright;
terms at <https://petrinex.ca/terms>). Commercial use requires prior
consent. **Do not re-host the raw files** — `data/` is gitignored for
that reason; this repo ships code, and everyone pulls the data from the
source. Multiple local projects should share one raw archive via the
`PETRINEX_RAW` env var (or a symlink at `data/raw/`) instead of
re-downloading the archive.

## Code licence

MIT — see `LICENSE`. The licence covers the code only, not any data you
fetch with it.

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
