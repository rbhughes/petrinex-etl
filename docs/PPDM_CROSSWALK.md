# PPDM 3.9 crosswalk for `well_months`

This repo's outputs are deliberately schema-neutral. This page is for
teams who need the same data inside a **PPDM 3.9** relational store: it
maps every `well_months` column to its PPDM home, using the mapping
already proven in production by
[well-spacing-playbook](../../well-spacing-playbook)'s
`scripts/load_ppdm.py` (664,075 wells, 176,216 PDEN entities, 8,165,257
`PDEN_VOL_SUMMARY` rows loaded and reconciled against the raw files by
16/16 independent verification checks).

PPDM schema DDL is PPDM Association IP — obtain it from
<https://ppdm.org> under their terms. Nothing here reproduces the
schema; it only names columns.

## Identity first: three well identifiers

| identifier | example | where it lives |
|---|---|---|
| `well_id` (this repo) | `ABWI100071901015W400` | Petrinex `FromToID` |
| Petrinex `WellIdentifier` | `100071901015W400` | strip the `ABWI` prefix |
| DLS display label | `00/07-19-010-15W4/0` | `petrinex_etl.uwi` converts |

The playbook uses the bare `WellIdentifier` as **`WELL.UWI`** (PPDM does
not mandate a UWI scheme; document your choice). Two `WELL_ALIAS` rows
per well preserve the other identities:

- `ALIAS_TYPE='LICENCE'` — the AER licence number
  (`LicenceNumber` from the Well Infrastructure file).
- `ALIAS_TYPE='PETRINEX'`, `WELL_ALIAS_ID='PETRINEX_WELLID'` — the short
  Petrinex `WellID`.

## Column-by-column

| `well_months` column | PPDM 3.9 destination | notes |
|---|---|---|
| `well_id` | `PDEN.PDEN_ID`, `WELL.UWI` | strip `ABWI`; `PDEN_SUBTYPE='WELL'` |
| — | `PDEN_WELL.PRIMARY_UWI` | = `PDEN_ID` (well-grain PDEN) |
| `month` | `PDEN_VOL_SUMMARY.PERIOD_ID` | with `PERIOD_TYPE='MONTH'` |
| `activity` | `PDEN_VOL_SUMMARY.ACTIVITY_TYPE` | part of the PK: PROD and INJ rows coexist per well-month |
| `product` + `volume` | pivoted into `OIL_VOLUME`, `GAS_VOLUME`, `WATER_VOLUME`, ... | see pivot rules below |
| `hours` | `PDEN_VOL_SUMMARY.PERIOD_ON_PRODUCTION` | max over the month's rows |
| `operator_baid` | `BUSINESS_ASSOCIATE.BUSINESS_ASSOCIATE_ID`; `WELL.OPERATOR` | `BA_TYPE='OPERATOR'` |
| `operator_name` | `BUSINESS_ASSOCIATE.BA_LONG_NAME` | |
| `facility_id/_type/_subtype` | `FACILITY` family | NOT loaded by the playbook (it linked wells only); shown for completeness |
| `energy` | — | GJ; dropped by the playbook — map via your UOM practice if needed |

Constants the playbook stamps: `PDEN_SOURCE='PETRINEX'` (no mandated
value exists; pick one and document it), `VOLUME_METHOD='REPORTED'`,
`AMENDMENT_SEQ_NO=0`, `AMEND_REASON='ORIGINAL'`.

## The product pivot

PPDM keys `PDEN_VOL_SUMMARY` with **no product column** — one row
carries `OIL_VOLUME` / `GAS_VOLUME` / `WATER_VOLUME` side by side — so
Petrinex's one-row-per-product layout pivots on load:

| Petrinex `ProductID` | PPDM column |
|---|---|
| `OIL` | `OIL_VOLUME` |
| `GAS`, `ENTGAS`, `ACGAS` | `GAS_VOLUME` |
| `WATER`, `FSHWTR`, `BRKWTR`, `STEAM` | `WATER_VOLUME` |
| `COND` | `NGL_VOLUME` (playbook choice — use a dedicated condensate column if your schema carries one) |
| `CO2` | `CO2_VOLUME` |

Steam has no PPDM volume column: injected steam folds into
`WATER_VOLUME` (it is water, hot) and the row is flagged
`PRIMARY_PRODUCT='STEAM'` so steam-bearing rows stay identifiable.

## What the playbook did NOT map

- Activities other than `PROD` and `INJ` (`VENT`, `FLARE`, `FUEL`,
  `DISP`, `SHUTIN`, `REC`, inventories, load fluids...). The neutral
  `well_months` table keeps them all verbatim; PPDM models dispositions
  outside `PDEN_VOL_SUMMARY`, and the mapping is yours to design.
- Reporting facilities as first-class `FACILITY` rows.
- Amendment history: Petrinex republishes whole months; the playbook
  loads latest-state with `AMENDMENT_SEQ_NO=0` rather than tracking
  amendment sequences.

## Load-order and engine cautions (paid for, not theoretical)

- Load parents before children: `BUSINESS_ASSOCIATE` -> `WELL` ->
  `WELL_ALIAS` -> `PDEN` -> `PDEN_WELL` -> `PDEN_VOL_SUMMARY`.
- On DuckDB, rows referenced by a FOREIGN KEY cannot be UPDATEd or
  DELETEd — use insert-only staging with `ON CONFLICT DO NOTHING`
  upserts, and resolve cross-links at query time where you must.
- `***` means confidential: read all columns as text and `TRY_CAST`, so
  masked values become NULL instead of load failures (or, worse,
  silently dropped rows under `ignore_errors`).
- Gas is e3m³ while liquids are m³; record units in your UOM columns
  rather than converting silently.
