r"""Keep the bond universe current, because the universe MOVES.

``catalog/bond_isins.json`` is a harvest: it holds whatever ``CVCURVEBOND``
returned on the day someone ran the probe. The US Treasury universe does not sit
still — Treasury auctions weekly and 24 of the 349 nominal coupon bonds Citi
carries mature during 2026 alone — so a static catalog is wrong within weeks in
two different directions:

**New issues are missing.** Measured 2026-08-08 against the repo's own
``fiscaldata`` reference table: 352 live nominal coupon USTs, of which Citi
carried 349. Six were absent — three announced for settlement on 2026-08-17
(when-issued, correctly not quoted yet) and **three issued 2026-07-31, eight days
earlier, that Citi had still not picked up**. Those three are the on-the-run 2Y,
5Y and 7Y, so ``UnifiedQuery(cusip="CT2")`` resolves to a bond this source cannot
quote. That is a real operational limit of the source, not a bug here, and it is
why resolution raises a coverage error naming it rather than returning nothing.

**Matured bonds vanish.** ``CVCURVEBOND`` is date-stamped, so it looks like you
can ask for a historical universe — but measured across five as-of dates
(2021-08-09 through 2026-08-07) it returns 115, 150, 235, 296 and 349 ISINs whose
**union is exactly the 349 live today**. Not one bond that has since matured came
back. Citi does not serve a historical constituent list; asking for an old date
returns today's set filtered to what already existed.

That second finding is what shapes this module. If matured bonds cannot be
recovered from Citi, the only way to ever have their history is to have seen them
while they were live — so the catalog is maintained as an **accumulating union**
that never removes anything. A bond seen once stays, with ``first_seen`` and
``last_seen`` recorded, and its already-cached history stays valid after it
matures. Run the refresh regularly and the universe grows into the full picture;
run it never and it decays into a snapshot again.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import pathlib
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog

__all__ = [
    "EmptyUniverseError",
    "REFRESH_TAGS_FILE",
    "RefreshResult",
    "refresh_universe",
    "validate_bond_values",
]

_logger = logging.getLogger(__name__)


def _last_business_day(d: datetime.date) -> datetime.date:
    """Roll a weekend back to Friday.

    The curve is not published on a Saturday, and a refresh that silently sees
    nothing is worse than one that refuses: it logs "0 new" and looks like a
    successful no-op. Holidays are not handled here - the empty-result guard
    catches those with a message naming the day.
    """
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d

#: Where newly validated tags accumulate. A THIRD file on purpose: the two
#: harvest files are the record of a specific exhaustive probe and are left
#: immutable, so "what did the original sweep find" stays answerable.
REFRESH_TAGS_FILE = "bond_tags_validated_refresh.json"

#: The per-bond values worth probing for a newly discovered bond, in the order
#: the original sweep found them useful.
PROBE_VALUES: Tuple[str, ...] = (
    "PRICE", "YIELD", "DURATION", "SPREAD_TSY", "DV01", "OAS",
    "ASW_4_USD", "ASW_4_AUD", "ASW_4_JPY", "ASW_4_EUR", "ASW_4_GBP", "ASW_4_CHF", "CAS",
)


class EmptyUniverseError(RuntimeError):
    """CVCURVEBOND served nothing — a bad as-of date, not an empty universe."""


@dataclasses.dataclass
class RefreshResult:
    """What one refresh changed."""

    universe_key: str
    seen: int = 0
    added: List[str] = dataclasses.field(default_factory=list)
    retained_not_seen: List[str] = dataclasses.field(default_factory=list)
    validated: Dict[str, List[str]] = dataclasses.field(default_factory=dict)

    def describe(self) -> str:
        return (
            f"{self.universe_key}: Citi served {self.seen}, "
            f"{len(self.added)} new, {len(self.retained_not_seen)} retained but no longer served, "
            f"{len(self.validated)} newly value-probed"
        )


def _catalog_dir(catalog: Optional[CitiVeloCatalog] = None) -> pathlib.Path:
    cat = catalog or CitiVeloCatalog.default()
    return pathlib.Path(cat.dir)


def refresh_universe(
    *,
    quotes,
    country: str = "USA",
    currency: str = "USD",
    asset_type: str = "GOVT",
    measure: str = "YIELD",
    as_of: Optional[datetime.date] = None,
    catalog: Optional[CitiVeloCatalog] = None,
    validate_new: bool = True,
) -> RefreshResult:
    """Ask Citi for the universe today and merge it into the catalog.

    The merge is a UNION. Bonds Citi no longer serves are kept, with
    ``last_seen`` left where it was, because their cached history is still real
    and cannot be re-obtained once they mature. Nothing is ever deleted here.

    Parameters
    ----------
    quotes
        A live :class:`~MDP.CitiVelocityExcel.quotes.CitiVeloQuotes`. This is the
        one part that needs Excel.
    validate_new
        Probe which values each newly discovered bond serves and record them, so
        the new bonds are immediately usable. Without this a new bond resolves
        but ``available_values`` returns ``[]`` and nothing is ever requested for
        it.

    Returns
    -------
    RefreshResult
    """
    as_of = _last_business_day(as_of or datetime.date.today())
    key = f"{country.upper()}.{currency.upper()}.{asset_type.upper()}"
    cat_dir = _catalog_dir(catalog)
    path = cat_dir / "bond_isins.json"

    raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    existing = {r["isin"]: dict(r) for r in raw.get(key, [])}

    tag = T.bond_curve(country, currency, asset_type, measure, as_of)
    frame = quotes.curve_bond(tag)
    served = _rows_from_curve_frame(frame)
    _logger.info("refresh %s: Citi served %d bonds as of %s", key, len(served), as_of)

    if not served:
        # Zero is not "Citi dropped every bond"; it is almost always a date with
        # no publication - a weekend, a holiday, or today before the curve lands.
        # Measured: 2026-08-08 (a Saturday) returned nothing while 2026-08-07
        # returned all 349. Recording that as a refresh would leave a log line
        # saying "0 new" and hide the fact that nothing was checked at all.
        raise EmptyUniverseError(
            f"CVCURVEBOND returned no bonds for {key} as of {as_of:%Y-%m-%d} "
            f"({as_of:%A}). That is a publication gap, not an empty universe - the "
            "catalog is unchanged. Retry with --end set to a business day on which "
            "the curve published."
        )

    result = RefreshResult(universe_key=key, seen=len(served))
    stamp = as_of.isoformat()
    for isin, desc, maturity in served:
        row = existing.get(isin)
        if row is None:
            existing[isin] = {
                "isin": isin, "desc": desc, "maturity": maturity,
                "first_seen": stamp, "last_seen": stamp,
            }
            result.added.append(isin)
        else:
            row["last_seen"] = stamp
            row.setdefault("first_seen", stamp)
            # Refresh the description: a bond's coupon never changes, but the
            # committed rows predate the first_seen fields and some carry a
            # blank maturity.
            if desc:
                row["desc"] = desc
            if maturity and not row.get("maturity"):
                row["maturity"] = maturity

    served_isins = {i for i, _, _ in served}
    result.retained_not_seen = sorted(set(existing) - served_isins)

    raw[key] = [existing[i] for i in sorted(existing)]
    path.write_text(json.dumps(raw, indent=1), encoding="utf-8")
    _logger.info(
        "refresh %s: %d new, %d retained but not served today, %d total",
        key, len(result.added), len(result.retained_not_seen), len(existing),
    )

    if validate_new and result.added:
        # A fresh catalog: the one passed in has already cached its bond index,
        # and tags.bond() refuses an ISIN that index has not seen.
        result.validated = validate_bond_values(
            result.added, quotes=quotes, catalog=CitiVeloCatalog.default(), as_of=as_of
        )
    return result


def _rows_from_curve_frame(frame) -> List[Tuple[str, str, str]]:
    """``[(isin, description, maturity)]`` from a ``CVCURVEBOND`` block.

    Column names are matched case-insensitively rather than by position: the
    block's shape is the add-in's business and has changed between probes.
    """
    if frame is None or getattr(frame, "empty", True):
        return []
    cols = {str(c).strip().lower(): c for c in frame.columns}
    isin_col = next((cols[k] for k in ("isin", "id", "security", "identifier") if k in cols), None)
    if isin_col is None:
        isin_col = frame.columns[0]
    desc_col = next((cols[k] for k in ("description", "desc", "name") if k in cols), None)
    mat_col = next((cols[k] for k in ("maturity", "maturitydate", "maturity_date") if k in cols), None)

    out: List[Tuple[str, str, str]] = []
    for _, r in frame.iterrows():
        isin = str(r[isin_col]).strip().upper()
        if len(isin) != 12 or not isin[:2].isalpha():
            continue
        desc = str(r[desc_col]).strip() if desc_col is not None else ""
        mat = str(r[mat_col]).strip() if mat_col is not None else ""
        out.append((isin, desc, mat))
    return out


def validate_bond_values(
    isins: Sequence[str],
    *,
    quotes,
    catalog: Optional[CitiVeloCatalog] = None,
    as_of: Optional[datetime.date] = None,
    years: float = 5.0,
) -> Dict[str, List[str]]:
    """Probe which values Citi serves for each ISIN, and record them.

    Validation is by FETCHING, not by ``CVMETADATA``: metadata under-reports this
    family (it claims zero valid tenors for ``SWAP_SPREAD`` while ``CVTSHIST``
    serves all eleven), and the original bond sweep was built the same way.

    The window is five years by default, and that is load-bearing rather than
    generous: availability is window-dependent. ``OAS`` was measured **empty over
    one week and full over five years** for the same bond. A one-week probe would
    record ``OAS`` as unserved for every new bond, permanently.
    """
    as_of = as_of or datetime.date.today()
    cat = catalog or CitiVeloCatalog.default()
    cat_dir = _catalog_dir(cat)
    wanted = [i for i in dict.fromkeys(str(x).strip().upper() for x in isins) if i]
    if not wanted:
        return {}

    candidates: Dict[str, str] = {}
    for isin in wanted:
        for value in PROBE_VALUES:
            try:
                candidates[f"RATES.BOND.{isin}.{value}"] = isin
            except Exception:  # noqa: BLE001
                continue

    start = as_of - datetime.timedelta(days=int(years * 365.25))
    _logger.info("validating %d candidate tags for %d new bonds", len(candidates), len(wanted))
    frame = quotes.frame(list(candidates), "DAILY", start=start, end=as_of)

    found: Dict[str, List[str]] = {i: [] for i in wanted}
    valid_tags: List[str] = []
    for tag in frame.columns:
        series = frame[tag].dropna()
        if series.empty:
            continue
        isin = candidates.get(str(tag))
        if isin is None:
            continue
        found[isin].append(str(tag).rsplit(".", 1)[-1])
        valid_tags.append(str(tag))

    path = cat_dir / REFRESH_TAGS_FILE
    payload = {"valid_tags": [], "probed": {}}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    merged = sorted(set(payload.get("valid_tags", [])) | set(valid_tags))
    probed = dict(payload.get("probed", {}))
    for isin in wanted:
        probed[isin] = {"at": as_of.isoformat(), "values": sorted(found[isin])}
    path.write_text(
        json.dumps({"valid_tags": merged, "probed": probed,
                    "note": "Accumulated by bonds/refresh.py. The two bond_tags_validated*.json "
                            "files are the original exhaustive sweep and are left immutable."},
                   indent=1),
        encoding="utf-8",
    )
    for isin in wanted:
        _logger.info("  %s serves %d value(s): %s", isin, len(found[isin]), ", ".join(found[isin]) or "(none)")
    return found
