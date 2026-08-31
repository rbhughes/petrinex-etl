"""DLS/ATS surface location -> approximate lat/lon (WGS84).

Petrinex facility and well locations are Alberta Township System
coordinates (LSD-SEC-TWP-RGE-MER). This converts them to centroid
lat/lon good enough for mapping, with no lookup tables or deps.

Model: latitude is linear in township number and miles north within
the township; longitude offsets west of the meridian are scaled by
cos(baseline latitude) — ranges are surveyed from baselines every 4
townships, so using the band's baseline beats cos(well latitude)
(measured: p50 374 m -> 266 m). The five constants are least-squares
fits against 532,623 AER ST37 well surface locations (every AB well
with both a DLS label and surveyed coordinates).

Measured accuracy on that population: p50 266 m, p90 1.6 km, p99
3.2 km. The tail is real survey irregularity (correction-line jogs,
road-allowance patterns) that no closed-form model captures — treat
results as LSD/section centroids, not survey coordinates.

Section and LSD grids are serpentine, starting at the SOUTHEAST
corner: sections 1-6 run east->west along the south edge, 7-12 back
west->east, up to 36 in the northeast; LSDs 1-16 snake the same way
within a section (4x4, quarter-mile cells).
"""
import math

# Least-squares fits vs ST37 (see module docstring).
_LAT0 = 49.001620372146974   # south edge of township 1, effective
_TWP_DEG = 0.08729099414344944  # township height, degrees latitude
_MILE_LAT_DEG = 0.0144168    # one mile north, degrees latitude
_RGE_DEG = 0.0877342         # range width, degrees lon at baseline
_MILE_LON_DEG = 0.0149086    # one mile west, degrees lon at baseline

_MERIDIAN_LON = {4: -110.0, 5: -114.0, 6: -118.0}


def _serpentine(idx: int, width: int) -> tuple[int, int]:
    """(row, col-from-start-corner) for a 1-based serpentine grid."""
    row, pos = divmod(idx - 1, width)
    col = pos if row % 2 == 0 else width - 1 - pos
    return row, col


def latlon_from_dls(twp: int, rge: int, mer: int,
                    sec: int | None = None,
                    lsd: int | None = None) -> tuple[float, float]:
    """Centroid lat/lon for a DLS location, at the finest granularity
    given: LSD (~400 m cell), section (~1.6 km), or township (~10 km).
    Raises ValueError on out-of-range parts."""
    if mer not in _MERIDIAN_LON:
        raise ValueError(f"meridian must be 4, 5 or 6, got {mer}")
    if not 1 <= twp <= 126:
        raise ValueError(f"township must be 1..126, got {twp}")
    if not 1 <= rge <= 34:
        raise ValueError(f"range must be 1..34, got {rge}")
    if sec is None and lsd is not None:
        raise ValueError("LSD given without a section")

    if sec is None:
        north = west = 3.0          # township centre, miles
    else:
        if not 1 <= sec <= 36:
            raise ValueError(f"section must be 1..36, got {sec}")
        sec_row, sec_col = _serpentine(sec, 6)
        if lsd is None:
            north = sec_row + 0.5   # section centre
            west = sec_col + 0.5
        else:
            if not 1 <= lsd <= 16:
                raise ValueError(f"LSD must be 1..16, got {lsd}")
            lsd_row, lsd_col = _serpentine(lsd, 4)
            north = sec_row + (lsd_row + 0.5) * 0.25
            west = sec_col + (lsd_col + 0.5) * 0.25

    lat = _LAT0 + _TWP_DEG * (twp - 1) + _MILE_LAT_DEG * north
    # Baseline of the 4-township survey band this township belongs to.
    baseline_lat = 49.0 + 4 * _TWP_DEG * ((twp + 1) // 4)
    lon = _MERIDIAN_LON[mer] - (
        _RGE_DEG * (rge - 1) + _MILE_LON_DEG * west
    ) / math.cos(math.radians(baseline_lat))
    return lat, lon
