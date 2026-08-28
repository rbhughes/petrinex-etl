"""Canadian DLS UWI display label <-> Petrinex WellIdentifier.

Display format: LE/LSD-SEC-TWP-RGEWM/ES, e.g. '00/07-19-010-15W4/0'.
Petrinex WellIdentifier: '1' + LE + LSD + SEC + TWP + RGE + WM + ES(2),
e.g. '100071901015W400'. This is the join key between AER ST37 geometry
(UWI_Label) and Petrinex volumetric/infrastructure data (WellIdentifier /
FromToID after stripping the jurisdiction prefix).

Two traps, both proven expensive:

- LE (location exception) is LEADING and ES (event sequence) is TRAILING.
  Swapping them still parses -- and silently drops the ST37<->Petrinex
  join from 100% to 68% (and mis-links wells that happen to match).
- LE is ALPHANUMERIC: F1, AA, W0, S0 are common (31,626 Alberta wells sit
  at exception AA alone). A digits-only pattern silently discards 11.7%
  of the province.

Match rate when applied to all of Alberta ST37: 99.99% (532,553/532,623).
"""
import re

_LABEL = re.compile(r"^([A-Z0-9]{2})/(\d{2})-(\d{2})-(\d{3})-(\d{2})(W\d)/(\d+)$")
_WELL_ID = re.compile(
    r"^1([A-Z0-9]{2})(\d{2})(\d{2})(\d{3})(\d{2})(W\d)(\d{2})$"
)


def well_id_from_label(label: str) -> str | None:
    """'00/07-19-010-15W4/0' -> '100071901015W400' (None if unparseable)."""
    m = _LABEL.match(label.strip())
    if not m:
        return None
    le, lsd, sec, twp, rge, mer, es = m.groups()
    if len(es) > 2:
        return None
    return f"1{le}{lsd}{sec}{twp}{rge}{mer}{es:0>2}"


def label_from_well_id(well_id: str) -> str | None:
    """'100071901015W400' -> '00/07-19-010-15W4/0' (None if unparseable)."""
    m = _WELL_ID.match(well_id.strip())
    if not m:
        return None
    le, lsd, sec, twp, rge, mer, es = m.groups()
    return f"{le}/{lsd}-{sec}-{twp}-{rge}{mer}/{int(es)}"
