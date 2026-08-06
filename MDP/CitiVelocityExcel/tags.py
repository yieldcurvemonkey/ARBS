r"""Typed tag builders, derived from the harvested catalog rather than hand-written.

Every builder validates its tokens against the recorded grammar, so it cannot
drift from what the add-in accepts. Where a branch was recorded, an unknown token
raises :class:`~MDP.CitiVelocityExcel.errors.UnknownTagError` with the accepted
set and the closest matches; where the walk stopped short of a branch (the
Function Builder walk was depth-capped), the builder still constructs the tag
from the documented shape but marks it ``verified=False`` - see
:func:`describe`.

Why builders are derived and not guessed
----------------------------------------
Generate-and-test over plausible token spellings found 14 OIS currencies but got
the two biggest ones wrong and missed six curves outright:

===========================================  =======================
guessed                                      actual
===========================================  =======================
``EUR_ESTR`` / ``EUR_ESTER``                 ``EUR_EUROSTR``
``USD_FEDFUNDS`` / ``USD_FF``                ``USD_FEDFUND``
--                                           ``JPY_TONAR_JSCC`` / ``JPY_TONAR_LCH`` (CCP-split)
--                                           ``DKK_TNDKK``, ``MXN_T_FONDEO``
sub-types PAR/FWD/SWAP_SPREAD                + ``ROLL_CARRY``, ``BFLY``, ``CURVES``
===========================================  =======================

``EUR_EONIA`` exists but is stale (~1y). A builder that silently emits wrong tags
is worse than no builder, which is why nothing here is spelled from memory.

Vol branches default to ``_RFR``
--------------------------------
All four ``_RFR`` branches (``ATM_RFR``, ``OTM_RFR``, ``REALIZED_RFR``,
``VOL_RATIO_RFR``) are 100% shape-correct with zero failures; their legacy twins
``ATM``, ``OTM``, ``REALIZED``, ``VOL_RATIO`` account for every VOL shape failure
and return no data. ``rfr=False`` is available and warns.

A per-branch spelling difference worth knowing
----------------------------------------------
The negative strike offsets are spelled differently per measure:
``OTM_RFR.NORMALABSOLUTE`` uses ``OTM_M25``, while ``OTM_RFR.PREMIUM`` uses
``OTM_N25``. :func:`vol_otm` picks the right one from the catalog rather than
assuming either.
"""

from __future__ import annotations

import datetime
import difflib
import warnings
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from MDP.CitiVelocityExcel.catalog import (
    DEPRECATED_VOL_BRANCHES,
    CitiVeloCatalog,
    sort_tenors,
)
from MDP.CitiVelocityExcel.errors import UnknownTagError

__all__ = [
    "TagInfo",
    "describe",
    "ois",
    "ois_par",
    "ois_fwd",
    "ois_swap_spread",
    "ois_par_grid",
    "ois_meeting",
    "swap_libor",
    "swap_libor_par_grid",
    "invoice_spread",
    "ois_invoice_spread",
    "tsy",
    "tsy_otr",
    "sov",
    "vol_atm",
    "vol_otm",
    "vol_realized",
    "vol_ratio",
    "vol_atm_grid",
    "vol_otm_grid",
    "bond",
    "bond_curve",
    "BOND_VALUES",
    "CVCURVEBOND_MEASURES",
    "inflation_swap",
    "inflation_index",
    "inflation_carry",
    "inflation_swaption",
    "xccy_basis",
    "xccy_basis_grid",
    "spread_option",
    "midcurve",
    "futures",
    "basis_swap",
    "fra",
    "money_market",
    "OIS_INDICES",
    "STALE_OIS_INDICES",
    "SWAP_SPREAD_LIQUID_TENORS",
]

DateLike = Union[datetime.date, datetime.datetime, str]


# ------------------------------------------------------------------ #
#                          known vocabularies                        #
# ------------------------------------------------------------------ #

#: The 20 real OIS index identifiers, from the add-in itself. Not guessable.
OIS_INDICES: Tuple[str, ...] = (
    "AUD_AONIA",
    "CAD_CORRA",
    "CHF_SARON",
    "DKK_TNDKK",
    "EUR_EONIA",
    "EUR_EUROSTR",
    "GBP_SONIA",
    "ILS_SHIR",
    "JPY_TONAR",
    "JPY_TONAR_JSCC",
    "JPY_TONAR_LCH",
    "MXN_T_FONDEO",
    "NOK_NOWA",
    "NZD_NZIONA",
    "SEK_STINA",
    "SGD_SORA",
    "THB_THOR",
    "USD_FEDFUND",
    "USD_SOFR",
    "ZAR_ZARONIA",
)

#: Present in the catalog but not maintained. ``EUR_EONIA`` stops around a year
#: back; ``JPY_TONAR`` is superseded by the two CCP-qualified curves.
STALE_OIS_INDICES: Tuple[str, ...] = ("EUR_EONIA",)

#: ``SWAP_SPREAD`` serves exactly these eleven through ``CVTSHIST``. Note
#: ``CVMETADATA`` reports ZERO valid tenors for this family - it is unsound as a
#: validator and would have silently dropped the whole thing.
SWAP_SPREAD_LIQUID_TENORS: Tuple[str, ...] = (
    "1M",
    "3M",
    "6M",
    "1Y",
    "2Y",
    "3Y",
    "5Y",
    "7Y",
    "10Y",
    "20Y",
    "30Y",
)

#: The per-bond timeseries value vocabulary, established by probing rather than
#: taken from the desk's 43-entry measure catalogue. Every ``REFERENCE_DATA``
#: field in that catalogue is rejected as a tag, and ``DOLLAR_DURATION`` is
#: really ``DV01``.
BOND_VALUES: Tuple[str, ...] = (
    "PRICE",
    "YIELD",
    "SPREAD_TSY",
    "OAS",
    "DURATION",
    "DV01",
    "CAS",
    "ASW_4_USD",
    "ASW_4_EUR",
    "ASW_4_GBP",
    "ASW_4_CHF",
    "ASW_4_JPY",
    "ASW_4_AUD",
)

#: What ``CVCURVEBOND`` accepts as the ``<MEASURE>`` segment. This is a DIFFERENT
#: surface from :data:`BOND_VALUES`: ``CVCURVEBOND`` accepts ``OAS`` but not
#: ``DV01``, while ``DV01`` *is* a valid per-bond timeseries value.
CVCURVEBOND_MEASURES: Tuple[str, ...] = (
    "YIELD",
    "PRICE",
    "SPREAD_TSY",
    "ASW_4_USD",
    "OAS",
    "DURATION",
)

#: Asset types that ``CVCURVEBOND`` actually populates. ``CORP``, ``MUNI``,
#: ``SUPRA``, ``SSA``, ``TIPS``, ``INFL``, ``ILB``, ``SOVEREIGN`` and ``QUASI``
#: all return nothing, as do the ``CAN`` and ``AUS`` countries entirely.
BOND_ASSET_TYPES: Tuple[str, ...] = ("GOVT", "AGENCY", "COVERED")

#: Documented but never harvested (the Function Builder walk was depth-capped
#: above them). Builders for these construct from the documented shape and mark
#: the result unverified.
_DOCUMENTED_ONLY_FAMILIES = frozenset({"SPREAD_OPTIONS", "MIDCURVES"})


# ------------------------------------------------------------------ #
#                              plumbing                              #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class TagInfo:
    """What is known about a tag before it is ever sent to the add-in."""

    tag: str
    family: str
    on_recorded_path: bool
    verification: str
    note: str = ""

    @property
    def verified(self) -> bool:
        """True only when this exact tag was probed and served data."""
        return self.verification in {"valid", "shape_ok"}


def _catalog(catalog: Optional[CitiVeloCatalog] = None) -> CitiVeloCatalog:
    return catalog if catalog is not None else CitiVeloCatalog.default()


def _pick(
    cat: CitiVeloCatalog,
    node: str,
    segment: Any,
    *,
    what: str,
    allow_unrecorded: bool = False,
) -> str:
    """Validate one segment against the recorded options of ``node``.

    When ``node`` was never expanded, the segment is accepted as-is (with
    ``allow_unrecorded``), because the walk's depth cap is a limit on OUR
    knowledge, not on the add-in's vocabulary.
    """
    token = str(segment).strip()
    if not token:
        raise UnknownTagError(f"Empty {what} for {node!r}.")
    options = cat.options(node)
    if not options:
        if allow_unrecorded:
            return token
        raise UnknownTagError(
            f"{node!r} has no recorded children, so {what}={token!r} cannot be validated. "
            "Pass the full tag straight through if you know it is right - the client "
            "accepts any RATES.* string."
        )
    if token in options:
        return token
    upper = {o.upper(): o for o in options}
    if token.upper() in upper:
        return upper[token.upper()]
    close = difflib.get_close_matches(token.upper(), list(upper), n=4, cutoff=0.5)
    suggestion = f" Did you mean {', '.join(upper[c] for c in close)}?" if close else ""
    shown = ", ".join(options[:24]) + (f", ... (+{len(options) - 24})" if len(options) > 24 else "")
    raise UnknownTagError(f"Unknown {what} {token!r} under {node}. Accepted: {shown}.{suggestion}")


def describe(tag: str, *, catalog: Optional[CitiVeloCatalog] = None) -> TagInfo:
    """What the catalog knows about ``tag`` without asking the add-in."""
    cat = _catalog(catalog)
    parts = str(tag).split(".")
    family = parts[1] if len(parts) > 1 else ""
    on_path = _on_recorded_path(cat, tag)
    note = ""
    if family in _DOCUMENTED_ONLY_FAMILIES:
        note = (
            f"RATES.{family} was recorded only to the measure level; the expiry and "
            "underlying levels come from the desk's documented shape and are unverified."
        )
    elif family == "SWAP_LIBOR":
        note = (
            "RATES.SWAP_LIBOR's grammar is confirmed (EUR/AUD/INR served on 2026-08-05; "
            "GBP/JPY empty, consistent with their RFR migration). Coverage is per currency, "
            "and there is no local repricing path: the legs are IBOR-indexed."
        )
    return TagInfo(
        tag=str(tag),
        family=family,
        on_recorded_path=on_path,
        verification=cat.verification(str(tag)),
        note=note,
    )


def _on_recorded_path(cat: CitiVeloCatalog, tag: str) -> bool:
    """True when every segment of ``tag`` lies on a path the walk recorded."""
    parts = str(tag).split(".")
    node = parts[0]
    for seg in parts[1:]:
        options = cat.options(node)
        if not options:
            return True  # ran past the walk's depth cap; nothing contradicts it
        if seg not in options:
            return False
        node = f"{node}.{seg}"
    return True


# ------------------------------------------------------------------ #
#                                 OIS                                #
# ------------------------------------------------------------------ #


def ois(
    index: str,
    sub_type: str,
    *segments: Any,
    catalog: Optional[CitiVeloCatalog] = None,
) -> str:
    """``RATES.OIS.<index>.<sub_type>.<...>`` with every segment validated.

    ``sub_type`` is one of ``PAR FWD SWAP_SPREAD ROLL_CARRY BFLY CURVES``.
    """
    cat = _catalog(catalog)
    idx = _pick(cat, "RATES.OIS", index, what="OIS index")
    if idx in STALE_OIS_INDICES:
        warnings.warn(
            f"{idx} exists but is stale (~1 year behind). Prefer the live curve for that "
            "currency, e.g. EUR_EUROSTR.",
            stacklevel=2,
        )
    node = f"RATES.OIS.{idx}"
    sub = _pick(cat, node, sub_type, what="OIS sub-type")
    node = f"{node}.{sub}"
    for seg in segments:
        token = _pick(cat, node, seg, what="segment", allow_unrecorded=True)
        node = f"{node}.{token}"
    return node


def ois_par(index: str, tenor: str, *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.OIS.<index>.PAR.<tenor>`` - the par swap rate, in percent."""
    return ois(index, "PAR", tenor, catalog=catalog)


def ois_fwd(index: str, forward: str, tenor: str, *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.OIS.<index>.FWD.<forward>.<tenor>`` - a forward-starting par rate."""
    return ois(index, "FWD", forward, tenor, catalog=catalog)


def ois_swap_spread(index: str, tenor: str, *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.OIS.<index>.SWAP_SPREAD.<tenor>``.

    Only :data:`SWAP_SPREAD_LIQUID_TENORS` are known to serve; the catalog carries
    the full 44-tenor axis because it is shared with ``PAR``.
    """
    return ois(index, "SWAP_SPREAD", tenor, catalog=catalog)


def ois_par_grid(
    index: str,
    *,
    tenors: Optional[Sequence[str]] = None,
    catalog: Optional[CitiVeloCatalog] = None,
) -> List[str]:
    """Every ``PAR`` tag for one OIS curve, in tenor order.

    This is the par grid the rateslib and QuantLib curve builders consume, and it
    is one ``CVTSHIST`` call: the add-in's own 44-tenor curve export is a single
    call, which is where the default chunk size comes from.
    """
    cat = _catalog(catalog)
    idx = _pick(cat, "RATES.OIS", index, what="OIS index")
    axis = list(tenors) if tenors else cat.tenors(f"RATES.OIS.{idx}.PAR")
    return [f"RATES.OIS.{idx}.PAR.{t}" for t in sort_tenors(axis)]


def ois_meeting(
    ccy: str,
    meeting_date: DateLike,
    *,
    catalog: Optional[CitiVeloCatalog] = None,
) -> str:
    """``RATES.OIS_MEETING.<ccy>.<yyyy>.<yyyymmdd>`` - the meeting-priced OIS rate."""
    cat = _catalog(catalog)
    cur = _pick(cat, "RATES.OIS_MEETING", ccy, what="OIS_MEETING currency")
    if isinstance(meeting_date, str):
        token = meeting_date.strip().replace("-", "")
    else:
        token = meeting_date.strftime("%Y%m%d")
    if len(token) != 8 or not token.isdigit():
        raise UnknownTagError(f"Meeting date must be yyyymmdd, got {meeting_date!r}.")
    year = token[:4]
    node = f"RATES.OIS_MEETING.{cur}"
    year = _pick(cat, node, year, what="meeting year")
    return f"{node}.{year}.{token}"


def invoice_spread(ccy: str, tenor: str, *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.INVOICESPREAD.<ccy>.<tenor>``."""
    cat = _catalog(catalog)
    cur = _pick(cat, "RATES.INVOICESPREAD", ccy, what="INVOICESPREAD currency")
    tok = _pick(cat, f"RATES.INVOICESPREAD.{cur}", tenor, what="invoice tenor")
    return f"RATES.INVOICESPREAD.{cur}.{tok}"


def ois_invoice_spread(curve: str, contract: str, *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.OIS_INVOICESPREAD.<curve>.<contract>``."""
    cat = _catalog(catalog)
    cur = _pick(cat, "RATES.OIS_INVOICESPREAD", curve, what="OIS_INVOICESPREAD curve")
    tok = _pick(cat, f"RATES.OIS_INVOICESPREAD.{cur}", contract, what="contract", allow_unrecorded=True)
    return f"RATES.OIS_INVOICESPREAD.{cur}.{tok}"


# ------------------------------------------------------------------ #
#                             SWAP_LIBOR                             #
# ------------------------------------------------------------------ #


def swap_libor(
    ccy: str,
    sub_type: str,
    *segments: Any,
    catalog: Optional[CitiVeloCatalog] = None,
    warn: bool = True,
) -> str:
    """``RATES.SWAP_LIBOR.<ccy>.<sub_type>.<...>`` - 46 currencies.

    The shape mirrors ``RATES.OIS``: ``PAR FWD SWAP_SPREAD ROLL_CARRY BFLY
    CURVES`` over a tenor axis. **Confirmed live 2026-08-05**: of a five-currency
    probe at ``PAR.10Y``, EUR, AUD and INR served data while GBP and JPY came back
    empty - which is the expected shape of an IBOR family after those two
    currencies migrated to RFR, not a shape failure. So the grammar is right and
    the coverage is per currency.

    What is still true is that there is **no local repricing path** for this
    family: its legs are IBOR-indexed, so the OIS conventions in
    ``curves/conventions.py`` would be the wrong ones. Use the published quote.
    """
    cat = _catalog(catalog)
    cur = _pick(cat, "RATES.SWAP_LIBOR", ccy, what="SWAP_LIBOR currency")
    node = f"RATES.SWAP_LIBOR.{cur}"
    sub = _pick(cat, node, sub_type, what="SWAP_LIBOR sub-type")
    node = f"{node}.{sub}"
    for seg in segments:
        token = _pick(cat, node, seg, what="segment", allow_unrecorded=True)
        node = f"{node}.{token}"
    if warn:
        warnings.warn(
            "RATES.SWAP_LIBOR coverage is PER CURRENCY: a 2026-08-05 probe found EUR, AUD "
            "and INR serving at PAR.10Y while GBP and JPY returned empty. Validate the "
            "currencies you need (client.validate_with_controls([...])), and note there is no "
            "local repricing path - the legs are IBOR-indexed.",
            stacklevel=2,
        )
    return node


def swap_libor_par_grid(
    ccy: str,
    *,
    tenors: Optional[Sequence[str]] = None,
    catalog: Optional[CitiVeloCatalog] = None,
) -> List[str]:
    """Every ``PAR`` tag for one ``SWAP_LIBOR`` currency. Coverage is per currency."""
    cat = _catalog(catalog)
    cur = _pick(cat, "RATES.SWAP_LIBOR", ccy, what="SWAP_LIBOR currency")
    axis = list(tenors) if tenors else cat.tenors(f"RATES.SWAP_LIBOR.{cur}.PAR")
    warnings.warn(
        "RATES.SWAP_LIBOR coverage is per currency (EUR/AUD/INR served on 2026-08-05; "
        "GBP/JPY were empty). Validate before relying on a given currency.",
        stacklevel=2,
    )
    return [f"RATES.SWAP_LIBOR.{cur}.PAR.{t}" for t in sort_tenors(axis)]


# ------------------------------------------------------------------ #
#                          treasuries / sovereigns                   #
# ------------------------------------------------------------------ #


def tsy(*segments: Any, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.TSY.<...>`` with every segment validated where recorded."""
    cat = _catalog(catalog)
    node = "RATES.TSY"
    for seg in segments:
        token = _pick(cat, node, seg, what="TSY segment", allow_unrecorded=True)
        node = f"{node}.{token}"
    return node


def tsy_otr(tenor: str, value: str = "YIELD", *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.TSY.TSY.OTR.<tenor>.<YIELD|PRICE>``.

    The series description carries the on-the-run ISIN, so this is also how you
    discover which bond the OTR point refers to on a given date.
    """
    return tsy("TSY", "OTR", tenor, str(value).upper(), catalog=catalog)


def sov(*segments: Any, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.SOV.<...>`` - sovereign curves (CMT / FWD / SOV sub-trees)."""
    cat = _catalog(catalog)
    node = "RATES.SOV"
    for seg in segments:
        token = _pick(cat, node, seg, what="SOV segment", allow_unrecorded=True)
        node = f"{node}.{token}"
    return node


# ------------------------------------------------------------------ #
#                                 VOL                                #
# ------------------------------------------------------------------ #


def _vol_branch(cat: CitiVeloCatalog, ccy: str, stem: str, rfr: bool) -> str:
    cur = _pick(cat, "RATES.VOL", ccy, what="VOL currency")
    branch = f"{stem}_RFR" if rfr else stem
    if not rfr and stem in DEPRECATED_VOL_BRANCHES:
        warnings.warn(
            f"RATES.VOL.{cur}.{stem} is a deprecated non-RFR branch: it accounts for every "
            "VOL shape failure in the harvest and returns no data. Use rfr=True.",
            stacklevel=3,
        )
    node = f"RATES.VOL.{cur}"
    branch = _pick(cat, node, branch, what="VOL branch")
    return f"{node}.{branch}"


def vol_atm(
    ccy: str,
    expiry: str,
    tenor: str,
    *,
    measure: str = "NORMAL",
    rfr: bool = True,
    catalog: Optional[CitiVeloCatalog] = None,
) -> str:
    """An ATM swaption vol point.

    ``RATES.VOL.<ccy>.ATM_RFR.<measure>[.ANNUAL].<expiry>.<tenor>`` where
    ``measure`` is one of ``NORMAL BLACK PREMIUM FWDPREMIUM``.

    The optional ``ANNUAL`` level is NOT optional per-call - it is branch-local.
    ``NORMAL`` carries it; ``BLACK``, ``PREMIUM`` and ``FWDPREMIUM`` go straight
    to expiry. This function reads which from the catalog instead of assuming, and
    that difference is exactly what made a level-pooled generator produce 2,163
    VOL tags of which zero were valid.
    """
    cat = _catalog(catalog)
    node = _vol_branch(cat, ccy, "ATM", rfr)
    meas = _pick(cat, node, measure, what="ATM vol measure")
    node = f"{node}.{meas}"
    options = cat.options(node)
    if "ANNUAL" in options or "DAILY" in options:
        basis = "ANNUAL" if "ANNUAL" in options else "DAILY"
        node = f"{node}.{basis}"
    exp = _pick(cat, node, expiry, what="expiry", allow_unrecorded=True)
    node = f"{node}.{exp}"
    ten = _pick(cat, node, tenor, what="swap tenor", allow_unrecorded=True)
    return f"{node}.{ten}"


def vol_otm(
    ccy: str,
    expiry: str,
    tenor: str,
    offset_bp: Union[int, float, str],
    *,
    measure: str = "NORMALABSOLUTE",
    rfr: bool = True,
    catalog: Optional[CitiVeloCatalog] = None,
) -> str:
    """An out-of-the-money swaption vol point at a strike offset in basis points.

    ``offset_bp`` may be signed (``-25``) or an explicit token (``'OTM_M25'``).
    The negative-offset spelling is **per measure**: ``NORMALABSOLUTE`` uses
    ``OTM_M25`` and ``PREMIUM`` uses ``OTM_N25``. The right one is read from the
    catalog, never assumed.

    ``measure`` is one of ``PREMIUM NORMALABSOLUTE NORMALSKEW RISK_REVERSAL``.
    """
    cat = _catalog(catalog)
    node = _vol_branch(cat, ccy, "OTM", rfr)
    meas = _pick(cat, node, measure, what="OTM vol measure")
    node = f"{node}.{meas}"
    options = cat.options(node)
    if "ANNUAL" in options or "DAILY" in options:
        node = f"{node}.{'ANNUAL' if 'ANNUAL' in options else 'DAILY'}"

    token = _offset_token(cat, node, offset_bp)
    node = f"{node}.{token}"
    exp = _pick(cat, node, expiry, what="expiry", allow_unrecorded=True)
    node = f"{node}.{exp}"
    ten = _pick(cat, node, tenor, what="swap tenor", allow_unrecorded=True)
    return f"{node}.{ten}"


def _offset_token(cat: CitiVeloCatalog, node: str, offset_bp: Union[int, float, str]) -> str:
    """Map a signed basis-point offset to this branch's own OTM token spelling."""
    if isinstance(offset_bp, str) and offset_bp.upper().startswith("OTM_"):
        return _pick(cat, node, offset_bp.upper(), what="strike offset")
    value = float(offset_bp)
    magnitude = int(abs(value))
    options = cat.options(node)
    if value >= 0:
        return _pick(cat, node, f"OTM_{magnitude}", what="strike offset")
    for prefix in ("OTM_M", "OTM_N"):
        candidate = f"{prefix}{magnitude}"
        if candidate in options:
            return candidate
    negatives = sorted(o for o in options if o.startswith("OTM_M") or o.startswith("OTM_N"))
    raise UnknownTagError(
        f"No {magnitude}bp negative strike offset under {node}. "
        f"Accepted negative offsets: {', '.join(negatives) or '(none recorded)'}."
    )


def vol_realized(
    ccy: str, *segments: Any, rfr: bool = True, catalog: Optional[CitiVeloCatalog] = None
) -> str:
    """``RATES.VOL.<ccy>.REALIZED_RFR.<...>``."""
    cat = _catalog(catalog)
    node = _vol_branch(cat, ccy, "REALIZED", rfr)
    for seg in segments:
        node = f"{node}.{_pick(cat, node, seg, what='REALIZED segment', allow_unrecorded=True)}"
    return node


def vol_ratio(
    ccy: str,
    window: str,
    expiry: str,
    tenor: str,
    *,
    rfr: bool = True,
    catalog: Optional[CitiVeloCatalog] = None,
) -> str:
    """``RATES.VOL.<ccy>.VOL_RATIO_RFR.<window>.<expiry>.<tenor>``.

    One level shallower than the other VOL branches: there is no measure level,
    the first level is the realized window (``1M 3M 6M 1Y``).
    """
    cat = _catalog(catalog)
    node = _vol_branch(cat, ccy, "VOL_RATIO", rfr)
    win = _pick(cat, node, window, what="realized window")
    node = f"{node}.{win}"
    exp = _pick(cat, node, expiry, what="expiry", allow_unrecorded=True)
    node = f"{node}.{exp}"
    ten = _pick(cat, node, tenor, what="swap tenor", allow_unrecorded=True)
    return f"{node}.{ten}"


def vol_atm_grid(
    ccy: str,
    *,
    expiries: Optional[Sequence[str]] = None,
    tenors: Optional[Sequence[str]] = None,
    measure: str = "NORMAL",
    rfr: bool = True,
    catalog: Optional[CitiVeloCatalog] = None,
) -> Dict[Tuple[str, str], str]:
    """The full ATM expiry x tenor grid as ``{(expiry, tenor): tag}``.

    Already expiry x tenor, i.e. a ready-made surface - no interpolation is needed
    to populate it, only to read between its nodes.
    """
    cat = _catalog(catalog)
    node = _vol_branch(cat, ccy, "ATM", rfr)
    meas = _pick(cat, node, measure, what="ATM vol measure")
    node = f"{node}.{meas}"
    options = cat.options(node)
    if "ANNUAL" in options or "DAILY" in options:
        node = f"{node}.{'ANNUAL' if 'ANNUAL' in options else 'DAILY'}"
    exp_axis = list(expiries) if expiries else sort_tenors(cat.options(node))
    out: Dict[Tuple[str, str], str] = {}
    for exp in exp_axis:
        exp_node = f"{node}.{exp}"
        ten_axis = list(tenors) if tenors else sort_tenors(cat.options(exp_node))
        for ten in ten_axis:
            out[(exp, ten)] = f"{exp_node}.{ten}"
    return out


def vol_otm_grid(
    ccy: str,
    offsets_bp: Sequence[Union[int, float, str]],
    *,
    expiries: Optional[Sequence[str]] = None,
    tenors: Optional[Sequence[str]] = None,
    measure: str = "NORMALABSOLUTE",
    rfr: bool = True,
    catalog: Optional[CitiVeloCatalog] = None,
) -> Dict[Tuple[str, str, float], str]:
    """The OTM cube slice as ``{(expiry, tenor, offset_bp): tag}``."""
    cat = _catalog(catalog)
    node = _vol_branch(cat, ccy, "OTM", rfr)
    meas = _pick(cat, node, measure, what="OTM vol measure")
    node = f"{node}.{meas}"
    options = cat.options(node)
    if "ANNUAL" in options or "DAILY" in options:
        node = f"{node}.{'ANNUAL' if 'ANNUAL' in options else 'DAILY'}"

    out: Dict[Tuple[str, str, float], str] = {}
    for offset in offsets_bp:
        token = _offset_token(cat, node, offset)
        off_node = f"{node}.{token}"
        signed = _token_to_bp(token)
        exp_axis = list(expiries) if expiries else sort_tenors(cat.options(off_node))
        for exp in exp_axis:
            exp_node = f"{off_node}.{exp}"
            ten_axis = list(tenors) if tenors else sort_tenors(cat.options(exp_node))
            for ten in ten_axis:
                out[(exp, ten, signed)] = f"{exp_node}.{ten}"
    return out


def _token_to_bp(token: str) -> float:
    """``OTM_M25`` -> ``-25.0``; ``OTM_25`` -> ``25.0``."""
    body = token[len("OTM_") :]
    if body[:1] in {"M", "N"}:
        return -float(body[1:])
    return float(body)


# ------------------------------------------------------------------ #
#                                bonds                               #
# ------------------------------------------------------------------ #


def bond(isin: str, value: str = "YIELD", *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.BOND.<ISIN>.<value>`` - the per-bond timeseries.

    ``RATES.BOND`` has ZERO children in the DAG: the ISIN universe is far too
    large for a browse tree, so bonds are a two-step mechanism. Use
    :func:`bond_curve` (``CVCURVEBOND``) to get the universe, then this to get one
    bond's history.

    ``ASW_4_<CCY>`` is a **sparse cross-currency matrix, not the bond's own
    currency**: a bund carries ``ASW_4_USD/GBP/CHF/AUD`` but not ``ASW_4_EUR``, a
    gilt carries ``ASW_4_EUR/GBP/AUD``, a Treasury carries ``ASW_4_USD/JPY``.
    There is no derivable rule - which legs are populated must be discovered per
    bond.
    """
    cat = _catalog(catalog)
    code = str(isin).strip().upper()
    if not code:
        raise UnknownTagError("Empty ISIN.")
    token = str(value).strip().upper()
    if token not in BOND_VALUES:
        close = difflib.get_close_matches(token, BOND_VALUES, n=3, cutoff=0.4)
        hint = ""
        if token == "DOLLAR_DURATION":
            hint = " (the desk's catalogue calls it DOLLAR_DURATION; the tag is DV01)"
        elif token in {"SEDOL", "RIC", "ISSUERNAME", "MATURITYDATEYYYYMMDD"}:
            hint = " (REFERENCE_DATA fields are static and are not served as timeseries)"
        raise UnknownTagError(
            f"Unknown bond value {value!r}{hint}. Accepted: {', '.join(BOND_VALUES)}."
            + (f" Did you mean {', '.join(close)}?" if close else "")
        )
    tag = f"RATES.BOND.{code}.{token}"
    if cat.bond_isin_lookup(code) is None:
        warnings.warn(
            f"{code} is not in the harvested 2,162-ISIN CVCURVEBOND universe. The tag grammar is "
            "confirmed (zero ISIN x value combinations were ever rejected), so this may still "
            "serve - but it was not seen in any curve.",
            stacklevel=2,
        )
    return tag


def bond_curve(
    country: str,
    currency: str,
    asset_type: str,
    measure: str = "YIELD",
    when: Optional[DateLike] = None,
) -> str:
    """A ``CVCURVEBOND`` tag: the bond UNIVERSE for one country/currency/type.

    ``RATES.BONDS.BY_COUNTRY.<CTRY>.<CCY>.ASSET_TYPE_<TYPE>.<MEASURE>.<yyyymmdd>``
    returns ``Date | ISIN | Description | <measure>``.

    Note ``RATES.BONDS`` (plural) is a **separate curve namespace** - it is not one
    of the 33 timeseries families, and it is reached through ``CVCURVEBOND``, not
    ``CVTSHIST``.
    """
    ctry = str(country).strip().upper()
    ccy = str(currency).strip().upper()
    atype = str(asset_type).strip().upper().removeprefix("ASSET_TYPE_")
    meas = str(measure).strip().upper()
    if atype not in BOND_ASSET_TYPES:
        raise UnknownTagError(
            f"Unknown bond asset type {asset_type!r}. Accepted: {', '.join(BOND_ASSET_TYPES)}. "
            "CORP, MUNI, SUPRA, SSA, TIPS, INFL, ILB, SOVEREIGN and QUASI all return nothing."
        )
    if meas not in CVCURVEBOND_MEASURES:
        raise UnknownTagError(
            f"CVCURVEBOND does not accept measure {measure!r}. Accepted: "
            f"{', '.join(CVCURVEBOND_MEASURES)}. Note this differs from the per-bond value "
            "vocabulary: CVCURVEBOND accepts OAS but not DV01, while DV01 is a valid per-bond value."
        )
    if when is None:
        when = datetime.date.today()
    stamp = when if isinstance(when, str) else when.strftime("%Y%m%d")
    return f"RATES.BONDS.BY_COUNTRY.{ctry}.{ccy}.ASSET_TYPE_{atype}.{meas}.{stamp}"


# ------------------------------------------------------------------ #
#                             inflation                              #
# ------------------------------------------------------------------ #


def inflation_swap(index: str, tenor: str, *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.INFLATION.SWAP.<index>.<tenor>`` - the zero-coupon inflation swap rate."""
    cat = _catalog(catalog)
    idx = _pick(cat, "RATES.INFLATION.SWAP", index, what="inflation index")
    node = f"RATES.INFLATION.SWAP.{idx}"
    return f"{node}.{_pick(cat, node, tenor, what='tenor', allow_unrecorded=True)}"


def inflation_index(name: str, *segments: Any, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.INFLATION.INDEX.<name>[.<...>]`` - the published index level."""
    cat = _catalog(catalog)
    idx = _pick(cat, "RATES.INFLATION.INDEX", name, what="inflation index")
    node = f"RATES.INFLATION.INDEX.{idx}"
    for seg in segments:
        node = f"{node}.{_pick(cat, node, seg, what='segment', allow_unrecorded=True)}"
    return node


def inflation_carry(name: str, *segments: Any, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.INFLATION.INF_CARRY.<name>.<...>``.

    Sub-measures include ``IOTA``, ``CARRYADJIOTA``, ``NETBEICARRY``,
    ``NOMINALYIELDCARRY`` and ``REALYIELDCARRY``.
    """
    cat = _catalog(catalog)
    idx = _pick(cat, "RATES.INFLATION.INF_CARRY", name, what="carry curve")
    node = f"RATES.INFLATION.INF_CARRY.{idx}"
    for seg in segments:
        node = f"{node}.{_pick(cat, node, seg, what='segment', allow_unrecorded=True)}"
    return node


def inflation_swaption(
    index: str, *segments: Any, catalog: Optional[CitiVeloCatalog] = None
) -> str:
    """``RATES.INFLATION.SWAPTION.<index>.<...>``."""
    cat = _catalog(catalog)
    idx = _pick(cat, "RATES.INFLATION.SWAPTION", index, what="inflation swaption index")
    node = f"RATES.INFLATION.SWAPTION.{idx}"
    for seg in segments:
        node = f"{node}.{_pick(cat, node, seg, what='segment', allow_unrecorded=True)}"
    return node


# ------------------------------------------------------------------ #
#                          cross-currency                            #
# ------------------------------------------------------------------ #


def xccy_basis(
    ccy1: str,
    ccy2: str,
    tenor: str,
    *,
    forward: str = "SPOT",
    leg: str = "SPREAD_LEG",
    catalog: Optional[CitiVeloCatalog] = None,
) -> str:
    """``RATES.XCCY_OIS_SWAP.<ccy1>.<ccy2>.<fwd>.<tenor>.<leg>.BASIS_SPREAD``.

    Seven segments, validated 1,097/1,097 in the harvest - the one family that is
    100% shape-correct end to end. ``leg`` is ``SPREAD_LEG`` (the quoted basis) or
    ``BASE_LEG``.
    """
    cat = _catalog(catalog)
    a = _pick(cat, "RATES.XCCY_OIS_SWAP", ccy1, what="XCCY base currency")
    node = f"RATES.XCCY_OIS_SWAP.{a}"
    b = _pick(cat, node, ccy2, what="XCCY quote currency")
    node = f"{node}.{b}"
    fwd = _pick(cat, node, forward, what="forward start")
    node = f"{node}.{fwd}"
    ten = _pick(cat, node, tenor, what="tenor", allow_unrecorded=True)
    node = f"{node}.{ten}"
    leg_token = _pick(cat, node, leg, what="leg", allow_unrecorded=True)
    return f"{node}.{leg_token}.BASIS_SPREAD"


def xccy_basis_grid(
    ccy1: str,
    ccy2: str,
    *,
    tenors: Optional[Sequence[str]] = None,
    forward: str = "SPOT",
    leg: str = "SPREAD_LEG",
    catalog: Optional[CitiVeloCatalog] = None,
) -> Dict[str, str]:
    """``{tenor: tag}`` across the whole basis curve for one currency pair."""
    cat = _catalog(catalog)
    a = _pick(cat, "RATES.XCCY_OIS_SWAP", ccy1, what="XCCY base currency")
    b = _pick(cat, f"RATES.XCCY_OIS_SWAP.{a}", ccy2, what="XCCY quote currency")
    node = f"RATES.XCCY_OIS_SWAP.{a}.{b}.{forward}"
    axis = list(tenors) if tenors else sort_tenors(cat.options(node))
    return {
        t: xccy_basis(a, b, t, forward=forward, leg=leg, catalog=cat) for t in axis
    }


# ------------------------------------------------------------------ #
#                    options on spreads / midcurves                  #
# ------------------------------------------------------------------ #


def spread_option(
    ccy: str,
    expiry: str,
    pair: str,
    *,
    kind: str = "OPT_CAP",
    value: str = "VOL",
    catalog: Optional[CitiVeloCatalog] = None,
    warn: bool = True,
) -> str:
    """``RATES.SPREAD_OPTIONS.<ccy>.<kind>.<value>.<expiry>.<pair>``.

    A **single-look** CMS spread option: an option on the difference of two
    forward CMS rates at ONE expiry - not a strip, unlike a CMS spread cap/floor.
    ``pair`` is a concatenated tenor pair such as ``2Y5Y``, ``5Y10Y``, ``10Y30Y``.

    The expiry and pair levels were NOT harvested (the Function Builder walk was
    depth-capped above them), so they come from the desk's documented shape and
    are unverified.
    """
    cat = _catalog(catalog)
    cur = _pick(cat, "RATES.SPREAD_OPTIONS", ccy, what="SPREAD_OPTIONS currency")
    node = f"RATES.SPREAD_OPTIONS.{cur}"
    k = _pick(cat, node, kind, what="option kind")
    node = f"{node}.{k}"
    v = _pick(cat, node, value, what="PRICE or VOL")
    tag = f"{node}.{v}.{str(expiry).strip().upper()}.{str(pair).strip().upper()}"
    if warn:
        warnings.warn(
            "RATES.SPREAD_OPTIONS was harvested only to the PRICE/VOL level; the expiry and "
            "pair levels are the desk's documented shape and are unverified. Validate first.",
            stacklevel=2,
        )
    return tag


def midcurve(
    ccy: str,
    expiry: str,
    underlying: str,
    *,
    kind: str = "OPT_STR",
    value: str = "VOL",
    catalog: Optional[CitiVeloCatalog] = None,
    warn: bool = True,
) -> str:
    """``RATES.MIDCURVES.<ccy>.<kind>.<value>.<expiry>.<underlying>``.

    ``kind`` is ``OPT_PAY``/``OPT_REC``/``OPT_STR``; ``underlying`` is a
    forward-swap token such as ``1Y1Y``. Unverified below the currency level for
    the same reason as :func:`spread_option`.
    """
    cat = _catalog(catalog)
    cur = _pick(cat, "RATES.MIDCURVES", ccy, what="MIDCURVES currency")
    tag = (
        f"RATES.MIDCURVES.{cur}.{str(kind).strip().upper()}.{str(value).strip().upper()}"
        f".{str(expiry).strip().upper()}.{str(underlying).strip().upper()}"
    )
    if warn:
        warnings.warn(
            "RATES.MIDCURVES was harvested only to the currency level; everything below is the "
            "desk's documented shape and is unverified. Validate first.",
            stacklevel=2,
        )
    return tag


# ------------------------------------------------------------------ #
#                    futures / basis / FRA / money                   #
# ------------------------------------------------------------------ #


def futures(contract: str, nth: Union[int, str], value: str = "PRICE", *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.FUTURES.<XCBT_TY|XCME_ED|...>.NEXT_<n>.<PRICE|VOLUME>``.

    ``RATES.FUTURES`` is the one rates family that carries OHLC, at both intraday
    and EOD frequencies.
    """
    cat = _catalog(catalog)
    con = _pick(cat, "RATES.FUTURES", contract, what="futures contract")
    token = nth if isinstance(nth, str) else f"NEXT_{int(nth)}"
    node = f"RATES.FUTURES.{con}"
    tok = _pick(cat, node, token, what="contract slot", allow_unrecorded=True)
    return f"{node}.{tok}.{str(value).strip().upper()}"


def basis_swap(basis: str, ccy: str, tenor: str, *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.BASIS_SWAPS.<basis>.<ccy>.<tenor>``.

    ``basis`` is one of the six named bases, e.g. ``SOFR_FEDFUND_BASIS``,
    ``EUROSTR_EURIBOR_BASIS``, ``3S1S_BASIS``.
    """
    cat = _catalog(catalog)
    b = _pick(cat, "RATES.BASIS_SWAPS", basis, what="basis")
    node = f"RATES.BASIS_SWAPS.{b}"
    c = _pick(cat, node, ccy, what="currency")
    node = f"{node}.{c}"
    return f"{node}.{_pick(cat, node, tenor, what='tenor', allow_unrecorded=True)}"


def fra(ccy: str, start: str, tenor: str, *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.FRA.<ccy>.<start>.<tenor>``."""
    cat = _catalog(catalog)
    c = _pick(cat, "RATES.FRA", ccy, what="FRA currency")
    node = f"RATES.FRA.{c}"
    s = _pick(cat, node, start, what="FRA start", allow_unrecorded=True)
    node = f"{node}.{s}"
    return f"{node}.{_pick(cat, node, tenor, what='FRA tenor', allow_unrecorded=True)}"


def money_market(ccy: str, index: str, tenor: str, *, catalog: Optional[CitiVeloCatalog] = None) -> str:
    """``RATES.MONEY_MARKETS.<ccy>.<index>.<tenor>``."""
    cat = _catalog(catalog)
    c = _pick(cat, "RATES.MONEY_MARKETS", ccy, what="money-market currency")
    node = f"RATES.MONEY_MARKETS.{c}"
    i = _pick(cat, node, index, what="money-market index")
    node = f"{node}.{i}"
    return f"{node}.{_pick(cat, node, tenor, what='tenor', allow_unrecorded=True)}"
