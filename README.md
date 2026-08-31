# petrinex-etl

[![Petrinex logo][logo]](https://www.petrinex.ca)

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
petrinex fetch-infra           # well/facility/operator/BA snapshots
petrinex build-wells           # -> data/well_months/AB/      (~100 MB)
petrinex build-facilities      # -> data/facility_months/AB/  (~160 MB)
petrinex build-infra           # -> data/infra/AB_*.parquet   (~8 MB)
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

Downloads the four infrastructure snapshot CSVs to
`$PETRINEX_RAW/infra/<province>_<Name>_CSV.zip`:

- **Well Infrastructure** (~63 MB) — per-event well headers:
  identifiers, licence, status, location, linked facility. The bridge
  between well IDs and everything else (see the UWI section).
- **Facility Infrastructure** (~8 MB) — one row per facility: current
  operator and licensee BAIDs, subtype, operational status, location,
  licence, orphan flag, Directive 060 tier aggregate.
- **Facility Operator History** (~7 MB) — full operatorship time
  series per facility (start/end month; open interval = `9999-12`).
- **Business Associate** (~1 MB) — the BA registry: legal name,
  address, corporate status, amalgamation chain.

Unlike volumetrics these are single current-state snapshots, so
re-running always overwrites them.

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

### `petrinex build-facilities`

Transforms the same raw monthly zips into
`$PETRINEX_OUT/facility_months/<province>/<YYYY-MM>.parquet` — EVERY
volumetric row at reporting-facility grain, counterparty preserved
(no `FromToIDType` filter). Same mechanics as `build-wells`: nested-zip
unwrap, safe CSV options, resumable per month. The full Alberta window
is ~160 MB (~550,000 rows/month).

This is the table for methane work: well-attributed rows carry only
~1% of FUEL volume, ~3% of FLARE and ~48% of VENT (measured, 2025-06
AB) — the rest is reported against facilities and never reaches
`well_months`.

### `petrinex build-infra`

Normalizes the three business-entity snapshots (Facility
Infrastructure, Facility Operator History, Business Associate) to
`$PETRINEX_OUT/infra/<province>_<name>.parquet`, column names kept
exactly as Petrinex publishes them. Requires a prior `fetch-infra`.
The Well Infrastructure file is not handled yet (see roadmap) — its
per-event rows need real modeling, not a straight copy.

### Typical workflows

First-time setup:

```sh
petrinex probe          # see what's available
petrinex fetch-vol      # ~420 MB
petrinex fetch-infra
petrinex build-wells
petrinex build-facilities
petrinex build-infra
```

Monthly refresh (safe to run blindly — every step is incremental;
re-fetching infra refreshes the current-state snapshots):

```sh
petrinex fetch-vol && petrinex build-wells && petrinex build-facilities
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

## Output: `facility_months`

One parquet per production month; **every** volumetric row, keyed on
the reporting facility, counterparty preserved:

| column | meaning |
|---|---|
| `month`, `facility_id` | production month, Petrinex FacilityID (`ABBT...`) |
| `facility_type`, `facility_subtype` | `BT`/`GS`/`GP`/`IF` + subtype desc |
| `operator_baid`, `operator_name` | operator of record that month |
| `activity`, `product` | as in `well_months`, plus facility-only rows |
| `from_to_id`, `from_to_type` | counterparty: well (`WI`), facility, or self |
| `volume`, `hours`, `energy` | m³ (gas: e3m³), hours, GJ |

The `from_to_type='WI'` cut of this table is exactly `well_months`
(row-for-row; verified). Facility self-referencing VENT/FLARE/FUEL
rows are additive equipment-level volumes, not duplicated totals of
the per-well allocations (verified on 2025-06: where both exist their
sums differ; near-equal cases are confined to <5 m³ noise) — so
summing all rows per facility is the correct facility total.

## Output: business-entity tables (`data/infra/`)

Three snapshot parquets tying business associates to facilities, from
`build-infra` (columns exactly as Petrinex names them):

| table | rows (AB) | keys |
|---|---|---|
| `facility_infrastructure` | 125k | `FacilityID` -> operator + licensee BAIDs |
| `facility_operator_history` | 375k | `FacilityID` + month range -> operator |
| `business_associate` | 19k | `BAIdentifier`; `AmalgamatedIntoBAID` chain |

Three ways to tie an operator to a facility, in order of preference:
the monthly `operator_baid` already on every `facility_months` row
(operator of record for that month); the operator-history table for
attributing arbitrary months across transfers (covers 100% of current
facilities; ~6,600 facilities changed operator between 2022-03 and
today); and the BA registry for entity metadata and rolling
amalgamated BAs into their successors.

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

## DLS location -> lat/lon (`petrinex_etl.dls`)

Petrinex facility (and well) surface locations are Alberta Township
System coordinates. `latlon_from_dls(twp, rge, mer, sec=, lsd=)`
converts them to centroid lat/lon with no lookup tables:

```python
>>> latlon_from_dls(10, 15, 4, sec=19, lsd=7)
(49.8351..., -112.0271...)   # ST37 surveyed: 49.8359, -112.0240
```

The five model constants are least-squares fits against 532,623 AER
ST37 surveyed well locations. Measured accuracy on that population:
**p50 267 m, p90 1.6 km, p99 3.2 km** — LSD-centroid quality, fine
for mapping, not for survey work. One non-obvious modeling fact:
ranges are surveyed from baselines every 4 townships, so scaling
longitude by cos(baseline latitude) instead of cos(well latitude)
cuts median error from 374 m to 266 m. Covers 100.0% of AB
facilities (124,912/124,919 have usable DLS parts).

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
  models, built on `facility_months` + the business-entity tables.
- [well-spacing-playbook](../well-spacing-playbook) — the well-interference
  project this layer was extracted from.

## Roadmap

- Verified SK end-to-end build.
- Well Infrastructure CSV -> parquet normalizer (per-event rows; needs
  modeling, unlike the straight-copy snapshots in `build-infra`).

[logo]: https://www.petrinex.ca/media/l1paitxk/petrinexlogo.jpg?width=280&height=120&v=1dac7d2bcab8d70
