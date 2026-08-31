"""Command line interface: petrinex <command> [--province AB|SK]."""
import argparse

from . import facilities, fetch, infra, wells


def main() -> None:
    p = argparse.ArgumentParser(prog="petrinex", description=__doc__)
    p.add_argument("--province", default="AB", choices=("AB", "SK"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="report the live public volumetric window")
    fv = sub.add_parser("fetch-vol", help="download monthly volumetric zips")
    fv.add_argument("--first", help="YYYY-MM (default: probe the window)")
    fv.add_argument("--last", help="YYYY-MM (default: probe the window)")
    sub.add_parser("fetch-infra",
                   help="download the infrastructure snapshot CSVs")
    sub.add_parser("build-wells", help="build well_months parquet from raw zips")
    sub.add_parser("build-facilities",
                   help="build facility_months parquet from raw zips")
    sub.add_parser("build-infra",
                   help="normalize facility/operator/BA snapshots to parquet")
    a = p.parse_args()
    if a.cmd == "probe":
        w = fetch.probe_window(a.province)
        print(f"{a.province}: {w[0]} .. {w[1]}" if w else f"{a.province}: none found")
    elif a.cmd == "fetch-vol":
        fetch.fetch_vol(a.province, a.first, a.last)
    elif a.cmd == "fetch-infra":
        fetch.fetch_infra(a.province)
    elif a.cmd == "build-wells":
        wells.build(a.province)
    elif a.cmd == "build-facilities":
        facilities.build(a.province)
    elif a.cmd == "build-infra":
        infra.build(a.province)


if __name__ == "__main__":
    main()
