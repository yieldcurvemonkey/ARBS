r"""Constant-maturity aliases over history, and the bonds they used to be.

A ten-year ``CT2`` series is not one bond. It is 116 of them, and 94 of those
have matured. That single fact is what this module exists for, because every
other part of the Velocity bond stack is built around *today's* universe.

The gap, measured 2026-08-08
----------------------------
``CVCURVEBOND`` does not serve a historical constituent list. Asked at five
as-of dates from 2021 to 2026 it returned 115/150/235/296/349 ISINs whose union
is exactly the 349 it serves today - it filters today's set, it does not
reconstruct the past. So the committed catalog can never contain a bond that
matured before the first harvest, and ``resolve_bond`` - which ends by consulting
that catalog - refuses every one of them.

Counted over ``2016-08-07 .. 2026-08-07`` for the 28 aliases (CT/O/OO/OOO x
2/3/5/7/10/20/30):

========  =====================  ====================
window    distinct constituents  in Citi's catalog
========  =====================  ====================
1 year                       87    84  (97%)
5 years                     325   250  (77%)
10 years                    597   307  (51%)
========  =====================  ====================

Half the ten-year history is bonds the catalog cannot name. The loss is entirely
at the short end - ``CT10``/``CT20``/``CT30`` keep 40/41, 25/25 and 41/41 of
their constituents, while ``CT2`` keeps 22 of 116 - because a 2-year note that
was on the run before 2024 has since redeemed.

Two facts make the gap closable
-------------------------------
**The tag is mechanical.** ``RATES.BOND.<ISIN>.<value>`` needs only an ISIN, and
``US`` + CUSIP + check digit is arithmetic verified against 2,162 real Citi
ISINs. Nothing about building the tag needs the catalog.

**Citi still serves matured bonds, ten years back.** Measured 2026-08-08 by
grouping the tag cache after a ten-year fetch by MATURITY YEAR: **494 of 494**
bonds redeeming in 2016 through 2025 served, every one with a series ending
within a week of its own redemption (23 in 2016, 50 in 2017, 51 in 2018, 52 in
2019, 55 in 2020, 54 in 2021, 51 in 2022, 54 in 2023, 50 in 2024, 54 in 2025).
The universe LISTING excludes a matured bond; the per-bond TAG does not, and the
two are different mechanisms. ``scripts/citivelo_ust_history_depth_probe.py``
re-asks this if Citi's retention is ever suspected of changing.

So :func:`historic_universe` builds a universe that admits the matured bonds,
sourcing their descriptors from the UST reference table (which *does* go back to
1979) instead of from Citi. A synthesised descriptor carries
``source="ust-reference"`` and no ``available_values``, and that emptiness is
load-bearing: :meth:`CitiVeloBondFetcher.plan` reads an empty coverage list as
"never validated" and asks the wire in full, rather than as "serves nothing" and
skipping the bond. Coverage that was never established is not coverage.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from MDP.CitiVelocityExcel.bonds.universe import BondDescriptor, BondUniverse
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog
from utils.identifiers import InvalidIdentifierError, cusip_to_isin

__all__ = [
    "CM_RANK_PREFIXES",
    "CM_TENORS",
    "AliasHistory",
    "alias_rank_and_tenor",
    "constant_maturity_aliases",
    "cusips_to_isins",
    "historic_universe",
    "resolve_alias_history",
]

_logger = logging.getLogger(__name__)

#: The tenors the UST reference table calls ``<n>-Year``. 20 is included and is
#: the one with a start date: Treasury reintroduced the 20-year in May 2020, so
#: ``CT20`` does not resolve before 2020-06-02 and ``OOO20`` not before
#: 2021-03-02. See :attr:`AliasHistory.first_resolvable`.
CM_TENORS: Tuple[int, ...] = (2, 3, 5, 7, 10, 20, 30)

#: Rank 0..3 spelled the way ``FixedRateBondsMDP._resolve_aliases_bulk`` spells
#: them: on-the-run, old, double-old, triple-old.
CM_RANK_PREFIXES: Tuple[str, ...] = ("CT", "O", "OO", "OOO")

_CT_RE = re.compile(r"^CT(\d+)$", re.IGNORECASE)
_O_RE = re.compile(r"^(O{1,3})(\d+)$", re.IGNORECASE)


def constant_maturity_aliases(
    tenors: Sequence[int] = CM_TENORS,
    ranks: Sequence[str] = CM_RANK_PREFIXES,
) -> Tuple[str, ...]:
    """The alias grid, rank-major: ``CT2..CT30, O2..O30, OO2.., OOO2..``.

    Rank-major rather than tenor-major so a ``--limit``ed smoke run gets a whole
    curve at one rank instead of one tenor at four, which is the more useful
    partial answer.
    """
    return tuple(f"{prefix}{tenor}" for prefix in ranks for tenor in tenors)


def alias_rank_and_tenor(alias: str) -> Tuple[int, int]:
    """``('OO5') -> (2, 5)``. Raises for anything that is not a CM alias.

    Mirrors the regexes in ``FixedRateBondsMDP._resolve_aliases_bulk`` rather
    than reimplementing the resolver: this is used to *pre-compute* which alias
    resolves to what on which day, and if the two disagreed the warm would fetch
    one set of bonds and the build would ask for another.
    """
    raw = str(alias).strip()
    m = _CT_RE.match(raw)
    if m:
        return 0, int(m.group(1))
    m = _O_RE.match(raw)
    if m:
        return len(m.group(1)), int(m.group(2))
    raise ValueError(
        f"{alias!r} is not a constant-maturity alias. Expected CT<n>, O<n>, OO<n> or OOO<n>."
    )


@dataclasses.dataclass(frozen=True)
class AliasHistory:
    """Which bond one alias was, on each day of a window.

    Attributes
    ----------
    alias
        The alias as asked for.
    by_date
        ``{date: cusip}``, only for days the alias resolved.
    unresolved
        Days in the window on which it did not resolve at all. For the 20-year
        ranks this is the reintroduction gap and is expected; for anything else
        it is a hole worth looking at.
    """

    alias: str
    by_date: Mapping[datetime.date, str]
    unresolved: Tuple[datetime.date, ...] = ()

    @property
    def cusips(self) -> Tuple[str, ...]:
        """Distinct constituents, in the order they first appear."""
        return tuple(dict.fromkeys(self.by_date[d] for d in sorted(self.by_date)))

    @property
    def first_resolvable(self) -> Optional[datetime.date]:
        """The earliest day in the window the alias resolved to anything.

        This is the honest floor for this alias, and the resume key uses it. Two
        of the 28 aliases have a floor inside a ten-year window (``CT20`` from
        2020-06-02, ``OOO20`` from 2021-03-02), so a "done means the whole
        requested window" rule would leave the 20-year ranks permanently
        incomplete and re-fetching every night forever.
        """
        return min(self.by_date) if self.by_date else None

    def describe(self) -> str:
        first = self.first_resolvable
        return (
            f"{self.alias}: {len(self.cusips)} bond(s) over {len(self.by_date)} day(s)"
            + (f", from {first}" if first else ", never resolved")
            + (f", {len(self.unresolved)} unresolvable day(s)" if self.unresolved else "")
        )


def resolve_alias_history(
    ref_df: pd.DataFrame,
    aliases: Sequence[str],
    days: Sequence[datetime.date],
) -> Dict[str, AliasHistory]:
    """Resolve every alias on every day, using the repo's own ranking rule.

    ``_filter_and_rank_ref_df`` is called once per day and its result indexed by
    ``(oi, rank)``, which is what makes ten years of business days affordable
    offline - measured at 44 s for 2,610 days x 28 aliases with no network and no
    Excel.

    Why the reference table can answer this at all: it is the FULL issuance
    history, not a snapshot of what is outstanding. Measured on the fiscaldata
    cache for 2026-08-07 - 1,785 rows, issue dates from 1979-11-15, and 1,433 of
    them already matured. So the on-the-run ranking is reconstructible at any
    past date, which is the half of the problem that does not need Citi.
    """
    from MDP.FixedRateBonds.FixedRateBondsMDP import _filter_and_rank_ref_df

    wanted = [(a, *alias_rank_and_tenor(a)) for a in aliases]
    hits: Dict[str, Dict[datetime.date, str]] = {a: {} for a in aliases}
    missed: Dict[str, List[datetime.date]] = {a: [] for a in aliases}

    for day in days:
        ranked = _filter_and_rank_ref_df(ref_df, day)
        index = {
            (str(row["oi"]), int(row["rank"])): str(row["cusip"])
            for _, row in ranked.iterrows()
        }
        for alias, rank, tenor in wanted:
            cusip = index.get((f"{tenor}-Year", rank))
            if cusip is None:
                missed[alias].append(day)
            else:
                hits[alias][day] = cusip

    return {
        alias: AliasHistory(alias=alias, by_date=hits[alias], unresolved=tuple(missed[alias]))
        for alias in aliases
    }


def cusips_to_isins(cusips: Iterable[str], *, country: str = "US") -> Dict[str, str]:
    """``{cusip: isin}`` for every CUSIP that completes; the rest are dropped.

    Dropped rather than raised: this runs over the whole issuance history, which
    contains identifiers the arithmetic legitimately refuses, and one of them must
    not lose the other 596.
    """
    out: Dict[str, str] = {}
    for cusip in dict.fromkeys(str(c).strip().upper() for c in cusips if str(c).strip()):
        try:
            out[cusip] = cusip_to_isin(cusip, country)
        except InvalidIdentifierError as exc:
            _logger.info("historic: %s does not complete to an ISIN (%s)", cusip, exc)
    return out


def _descriptor_from_ust_reference(
    isin: str,
    row: Mapping[str, object],
    *,
    country: str,
    currency: str,
    asset_type: str,
) -> BondDescriptor:
    """A descriptor for a bond Citi no longer lists, from Treasury's own record.

    The coupon is Treasury's ``cpn`` in PERCENT, matching
    :attr:`BondDescriptor.coupon`, and the maturity is Treasury's date rather than
    a parse of a description string - which is strictly better information than
    the catalog path has, not a degraded substitute.
    """

    def _as_date(value) -> Optional[datetime.date]:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        ts = pd.Timestamp(value)
        return None if pd.isna(ts) else ts.date()

    coupon = row.get("cpn")
    try:
        coupon = None if coupon is None or pd.isna(coupon) else float(coupon)
    except (TypeError, ValueError):
        coupon = None

    return BondDescriptor(
        isin=isin,
        description=str(row.get("label") or "").strip(),
        ticker="T",
        coupon=coupon,
        maturity=_as_date(row.get("maturity_date")),
        country=country,
        currency=currency,
        asset_type=asset_type,
        # NOT "catalog": this bond is not in Citi's universe listing and a caller
        # inspecting provenance must be able to see that.
        source="ust-reference",
    )


def historic_universe(
    isins: Iterable[str],
    ref_df: pd.DataFrame,
    *,
    base: Optional[BondUniverse] = None,
    catalog: Optional[CitiVeloCatalog] = None,
    country: str = "USA",
    currency: str = "USD",
    asset_type: str = "GOVT",
) -> BondUniverse:
    """Citi's live universe, PLUS the matured USTs named in ``isins``.

    Additive and never subtractive. A bond Citi still lists keeps its catalog
    descriptor - including its validated ``available_values``, which is what stops
    the fetcher spending Excel budget on tags already known unserved. Only ISINs
    the catalog does not hold get a synthesised entry.

    Raises
    ------
    KeyError
        For an ISIN that is neither in the catalog nor in the reference table.
        Deliberately loud: silently dropping it would produce a warm that reports
        success with a hole in the alias series exactly where the interesting
        history is, and the caller can pass a wider ``ref_df`` or drop the bond.
    """
    cat = catalog if catalog is not None else CitiVeloCatalog.default()
    live = base if base is not None else BondUniverse.from_catalog(
        country=country, currency=currency, asset_type=asset_type, catalog=cat
    )

    by_isin: Dict[str, Mapping[str, object]] = {}
    for _, row in ref_df.iterrows():
        try:
            by_isin[cusip_to_isin(str(row["cusip"]), "US")] = row
        except InvalidIdentifierError:
            continue

    rows: List[BondDescriptor] = list(live)
    known = {d.isin for d in rows}
    missing: List[str] = []
    added = 0
    for isin in dict.fromkeys(str(i).strip().upper() for i in isins if str(i).strip()):
        if isin in known:
            continue
        row = by_isin.get(isin)
        if row is None:
            missing.append(isin)
            continue
        rows.append(
            _descriptor_from_ust_reference(
                isin, row, country=country, currency=currency, asset_type=asset_type
            )
        )
        known.add(isin)
        added += 1

    if missing:
        raise KeyError(
            f"{len(missing)} ISIN(s) are in neither Citi's catalog nor the UST reference "
            f"table, so no descriptor can be built for them: {', '.join(sorted(missing)[:8])}"
            + (" ..." if len(missing) > 8 else "")
        )

    _logger.info(
        "historic universe: %d live + %d matured/unlisted = %d bonds", len(live), added, len(rows)
    )
    return BondUniverse(rows, catalog=cat)
