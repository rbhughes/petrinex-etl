"""Fixtures are AER ST37 surveyed surface locations (NAD83 -> WGS84);
the model is fitted centroids, so assert within a tolerance that
reflects its measured accuracy (p50 266 m, p90 1.6 km)."""
import math

import pytest

from petrinex_etl.dls import latlon_from_dls


def dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = (a[0] - b[0]) * 111_320.0
    dlon = (a[1] - b[1]) * 111_320.0 * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)


# label -> (lsd, sec, twp, rge, mer), surveyed (lat, lon)
ST37_FIXTURES = [
    ("00/07-19-010-15W4/0", (7, 19, 10, 15, 4), (49.835896, -112.024044)),
    ("00/01-01-001-15W4/0", (1, 1, 1, 15, 4), (49.000218, -111.878654)),
    ("00/01-01-001-17W4/0", (1, 1, 1, 17, 4), (49.002158, -112.145169)),
    ("00/01-01-017-03W5/0", (1, 1, 17, 3, 5), (50.398956, -114.279870)),
    ("00/01-01-020-03W5/0", (1, 1, 20, 3, 5), (50.662783, -114.281943)),
    ("00/01-01-059-02W6/0", (1, 1, 59, 2, 6), (54.065689, -118.152467)),
    ("00/01-01-062-05W6/0", (1, 1, 62, 5, 6), (54.323299, -118.613390)),
]


@pytest.mark.parametrize("label,dls,truth", ST37_FIXTURES,
                         ids=[f[0] for f in ST37_FIXTURES])
def test_against_st37_surveyed_locations(label, dls, truth):
    lsd, sec, twp, rge, mer = dls
    pred = latlon_from_dls(twp, rge, mer, sec=sec, lsd=lsd)
    assert dist_m(pred, truth) < 1_000


def test_coarser_granularity_stays_inside_cell():
    lsd_pt = latlon_from_dls(10, 15, 4, sec=19, lsd=7)
    sec_pt = latlon_from_dls(10, 15, 4, sec=19)
    twp_pt = latlon_from_dls(10, 15, 4)
    assert dist_m(lsd_pt, sec_pt) < 1_200   # within the section
    assert dist_m(lsd_pt, twp_pt) < 7_000   # within the township


def test_serpentine_corners():
    # Section 1 is the SE corner of a township, 36 the NE, 6 the SW.
    se = latlon_from_dls(50, 10, 5, sec=1)
    sw = latlon_from_dls(50, 10, 5, sec=6)
    ne = latlon_from_dls(50, 10, 5, sec=36)
    assert sw[1] < se[1] and abs(sw[0] - se[0]) < 1e-6
    assert ne[0] > se[0] and abs(ne[1] - se[1]) < 1e-9


def test_rejects_bad_parts():
    for kwargs in ({"twp": 0}, {"rge": 40}, {"mer": 7},
                   {"sec": 37}, {"lsd": 17}):
        args = {"twp": 50, "rge": 10, "mer": 5, "sec": 1, "lsd": 1}
        args.update(kwargs)
        with pytest.raises(ValueError):
            latlon_from_dls(**args)
    with pytest.raises(ValueError):
        latlon_from_dls(50, 10, 5, lsd=1)  # LSD without section
