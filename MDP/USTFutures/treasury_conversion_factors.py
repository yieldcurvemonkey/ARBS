import datetime
import hashlib
import math
from calendar import monthrange
from dataclasses import dataclass
from typing import Dict, Optional, Sequence

import pandas as pd

from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data


@dataclass(frozen=True)
class TreasuryFutureConversionSpec:
    root: str
    aliases: tuple[str, ...]
    rounding_months: int
    min_remaining_months_from_first: Optional[int] = None
    max_remaining_months_from_first: Optional[int] = None
    max_remaining_months_from_last: Optional[int] = None
    max_remaining_months_from_first_exclusive: bool = False
    # First delivery period (YYYYMM) from which ``max_remaining_months_from_first`` applies.
    # None means "always". A deliverable grade is not a constant: see the TY entry below.
    max_remaining_effective_period: Optional[int] = None
    min_original_term_months: Optional[int] = None
    max_original_term_months: Optional[int] = None
    exact_original_term_months: frozenset[int] = frozenset()
    calc_mode: str = "ust_short"


# Deliverable-grade specifications, audited 2026-08-14 against the CBOT rulebook and CME's
# "Understanding Treasury Futures" (Table 2, Treasury Futures Contracts Summary).
#
#   root  contract              original term      remaining term (from 1st day of delivery month)
#   ----  --------------------  -----------------  ----------------------------------------------
#   TU    2-Year T-Note         <= 5y 3m           >= 1y 9m, <= 2y from the LAST day of the month
#   Z3N   3-Year T-Note         <= 7y              >= 2y 9m, <= 3y from the LAST day of the month
#   FV    5-Year T-Note         <= 5y 3m           >= 4y 2m
#   TY    10-Year T-Note        <= 10y             >= 6y 6m and < 8y
#   UXY   Ultra 10-Year T-Note  original-issue 10y >= 9y 5m, <= 10y
#   TWE   20-Year T-Bond        --                 >= 19y 2m, <= 19y 11m
#   US    Classic T-Bond        --                 >= 15y and < 25y
#   WN    Ultra T-Bond          --                 >= 25y
#
# Only TY was wrong: it used 72 months (6y 0m) and set no original-term limit, so the basket
# admitted both notes 6 months too short AND old 30-year BONDS with 6.5-8y left to run. The old
# bonds carry 5.5-7.625% coupons, which makes them cheapest-to-deliver in a sub-6% world, and they
# were named CTD on 1,103 of 1,886 ZN panel days with a median implied repo of 14.6% against
# funding of 0.05-5.3%. An implied repo that far above funding is not a market; it is a bond that
# cannot actually be delivered. See CBOT Rulebook Chapter 19 (U.S. Treasury Note Futures, 6 1/2 to
# 8-Year), https://www.cmegroup.com/content/dam/cmegroup/rulebook/CBOT/II/19.pdf :
#
#   "The contract grade for delivery on futures made under these Rules shall be U.S. Treasury
#    fixed-principal notes which have fixed semi-annual coupon payments, and which have: (a) an
#    original term to maturity (i.e., term to maturity at issue) of not more than 10 years; and
#    (b) a remaining term to maturity of not less than 6 years 6 months and less than 8 years."
#
# That rule also restricts the grade to FIXED-PRINCIPAL securities, which excludes TIPS and FRNs.
#
# THIS IS ENFORCED, AND THE ENFORCEMENT IS LOAD-BEARING ON EVERY ROOT. It happens at FETCH time,
# not here: `fiscaldata._fetch_auctions_raw_fiscaldata` sends `inflation_index_security:eq:No` to
# the Treasury auctions API and drops rows whose `frn_index_determination_rate` is populated.
# Measured 2026-08-15 by re-fetching with that one filter removed: 106 TIPS CUSIPs enter the frame
# and contaminate the December-2026 basket of all six roots -- TYZ26 3, TUZ26 1, FVZ26 1, USZ26 10,
# WNZ26 5, TNZ26 1. Nothing in this module would stop them: a 10-year TIPS is `security_type='Note'`
# with a fixed `int_rate` and semi-annual payments, so `oi` says "10-Year" and every filter below
# passes it, after which a conversion factor is computed off its real coupon -- meaningless.
#
# (An earlier version of this note said the frame "carries no security-type column ... so that leg
# of the rule is NOT enforced here ... latent rather than active". That was wrong in the direction
# that invites damage: a reader could delete the fetch filter as redundant. `security_type` really
# is redundant -- measured, the API returns the identical 2,375 rows with and without it, because
# TIPS ride as Note/Bond -- but `inflation_index_security` is not.)
#
# `_prepare_reference_data` now also drops flagged rows when the frame carries the markers, so the
# grade is enforced where the basket is built and not only in a query string in another package.
# Frames without the columns -- cached parquet written before they were requested, or a
# treasurydirect-sourced frame, which filters none of this -- are passed through unchanged rather
# than failed closed; see tests/test_ustf_fixed_principal_grade.py for what that does and does not
# catch.


# (column, value) pairs that mark a security as NOT fixed-principal. Compared case-insensitively.
# `security_type` is deliberately absent: measured, it discriminates nothing, because TIPS are
# served as security_type='Note'/'Bond' like any other coupon security.
_NOT_FIXED_PRINCIPAL_MARKERS: tuple[tuple[str, str], ...] = (
    ("inflation_index_security", "yes"),
    ("floating_rate", "yes"),
)


_CONTRACT_SPECS: tuple[TreasuryFutureConversionSpec, ...] = (
    TreasuryFutureConversionSpec(
        root="TU",
        aliases=("TU", "ZT", "2Y"),
        rounding_months=1,
        min_remaining_months_from_first=21,
        max_remaining_months_from_last=24,
        max_original_term_months=63,
        calc_mode="ust_short",
    ),
    TreasuryFutureConversionSpec(
        root="Z3N",
        aliases=("Z3N", "3YR", "3Y"),
        rounding_months=1,
        min_remaining_months_from_first=33,
        max_remaining_months_from_last=36,
        max_original_term_months=84,
        calc_mode="ust_short",
    ),
    TreasuryFutureConversionSpec(
        root="FV",
        aliases=("FV", "ZF", "5Y"),
        rounding_months=1,
        min_remaining_months_from_first=50,
        max_original_term_months=63,
        calc_mode="ust_short",
    ),
    TreasuryFutureConversionSpec(
        root="TY",
        aliases=("TY", "ZN", "10Y"),
        rounding_months=3,
        # CBOT Ch.19: "not less than 6 years 6 months" -> 78, not 72.
        min_remaining_months_from_first=78,
        # "and less than 8 years" -- but ONLY from the September 2023 contract month. Before that
        # the grade had no maximum, which is why CME's own published December-2017 ZN basket
        # ("Understanding Treasury Futures", Table 3) runs from 6.50 to 9.67 years and holds 17
        # securities; under an 8-year cap it would hold 4. Per CME SER-9102 (2022-12-06),
        # "Amendments to Rule 19101.A ... Commencing with the September 2023 Contract Month",
        # the prior text read "(b) a remaining term to maturity of not less than 6 years 6 months."
        # Applying today's cap to all history silently drops ~7 genuinely deliverable notes per
        # contract for every ZN month through June 2023.
        max_remaining_months_from_first=96,
        max_remaining_months_from_first_exclusive=True,
        max_remaining_effective_period=202309,
        # CBOT Ch.19: "an original term to maturity ... of not more than 10 years".
        # Keeps 7-year notes (84) in and old 30-year bonds (360) / 20-year bonds (240) out.
        max_original_term_months=120,
        calc_mode="ust_long",
    ),
    TreasuryFutureConversionSpec(
        root="UXY",
        aliases=("UXY", "TN", "ULTRA10Y"),
        rounding_months=3,
        min_remaining_months_from_first=113,
        max_remaining_months_from_first=120,
        exact_original_term_months=frozenset({120}),
        calc_mode="ust_long",
    ),
    TreasuryFutureConversionSpec(
        root="TWE",
        aliases=("TWE",),
        rounding_months=3,
        min_remaining_months_from_first=230,
        max_remaining_months_from_first=239,
        calc_mode="ust_long",
    ),
    TreasuryFutureConversionSpec(
        root="US",
        aliases=("US", "ZB", "30Y"),
        rounding_months=3,
        min_remaining_months_from_first=180,
        max_remaining_months_from_first=300,
        max_remaining_months_from_first_exclusive=True,
        calc_mode="ust_long",
    ),
    TreasuryFutureConversionSpec(
        root="WN",
        aliases=("WN", "UB", "ULTRA"),
        rounding_months=3,
        min_remaining_months_from_first=300,
        calc_mode="ust_long",
    ),
)

_SPEC_BY_ALIAS: Dict[str, TreasuryFutureConversionSpec] = {
    alias: spec for spec in _CONTRACT_SPECS for alias in spec.aliases
}


def contract_specs_fingerprint() -> str:
    """Short stable hash of the whole deliverable-grade table.

    Anything that caches a basket, or a number derived from one, should include this in its key.
    Hand-maintained cache versions do not survive contact with a real change: during this file's
    own repair the basket cache version was bumped BEFORE the last spec edit, so a rebuilt panel
    silently kept the previous baskets -- median 10 deliverables per ZN contract in every year,
    where pre-2023 years should hold 16-17. The spec was already correct; the cache was not, and
    nothing in the cached value recorded which spec had produced it.

    Deriving the version from the specs themselves removes the step that can be forgotten.
    """
    payload = repr(
        [
            (
                s.root,
                s.rounding_months,
                s.min_remaining_months_from_first,
                s.max_remaining_months_from_first,
                s.max_remaining_months_from_last,
                s.max_remaining_months_from_first_exclusive,
                s.max_remaining_effective_period,
                s.min_original_term_months,
                s.max_original_term_months,
                sorted(s.exact_original_term_months),
                s.calc_mode,
            )
            for s in _CONTRACT_SPECS
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _normalize_root(root: str) -> str:
    key = str(root or "").strip().upper()
    if key in _SPEC_BY_ALIAS:
        return _SPEC_BY_ALIAS[key].root
    raise KeyError(f"Unsupported Treasury futures root: {root}")


def get_contract_spec(root: str) -> TreasuryFutureConversionSpec:
    return _SPEC_BY_ALIAS[_normalize_root(root)]


def resolve_delivery_contract(symbol: str, as_of: datetime.date) -> tuple[str, datetime.date, int]:
    import rateslib as rl

    token = str(symbol or "").strip().upper().replace("/", "")
    if not token:
        raise ValueError("symbol must be non-empty")

    explicit = len(token) > 3
    if explicit:
        root = _normalize_root(token[:-3])
        contract_imm_date = rl.get_imm(code=token[-3:])
    else:
        root = _normalize_root(token)
        contract_imm_date = rl.next_imm(start=datetime.datetime(as_of.year, as_of.month, as_of.day))

    if isinstance(contract_imm_date, datetime.datetime):
        imm_date = contract_imm_date.date()
    else:
        imm_date = datetime.date(contract_imm_date.year, contract_imm_date.month, contract_imm_date.day)
    return root, imm_date, int(imm_date.strftime("%Y%m"))


def delivery_business_window(contract_imm_date: datetime.date) -> tuple[datetime.date, datetime.date]:
    from pandas.tseries.offsets import BMonthBegin, BMonthEnd

    start = BMonthBegin().rollback(pd.Timestamp(contract_imm_date)).date()
    end = BMonthEnd().rollforward(pd.Timestamp(contract_imm_date)).date()
    return start, end


def delivery_calendar_window(contract_imm_date: datetime.date) -> tuple[datetime.date, datetime.date]:
    first = datetime.date(contract_imm_date.year, contract_imm_date.month, 1)
    last = datetime.date(contract_imm_date.year, contract_imm_date.month, monthrange(contract_imm_date.year, contract_imm_date.month)[1])
    return first, last


def parse_original_term_months(value: object) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    head = text.split("-", 1)[0].strip()
    try:
        return int(head) * 12
    except ValueError:
        return None


def round_coupon_to_eighth(coupon_pct: float) -> float:
    eighths = math.floor((float(coupon_pct) * 8.0) + 0.5 + 1e-12)
    return eighths / 8.0


def _add_months(value: datetime.date, months: int) -> datetime.date:
    total = (value.year * 12) + (value.month - 1) + int(months)
    year = total // 12
    month = (total % 12) + 1
    day = min(value.day, monthrange(year, month)[1])
    return datetime.date(year, month, day)


def _whole_months_between(start: datetime.date, end: datetime.date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def _resolve_reference_end_date(
    *,
    maturity_date: datetime.date,
    call_date: Optional[datetime.date],
) -> datetime.date:
    if call_date is None or pd.isna(call_date):
        return maturity_date
    return min(maturity_date, call_date)


def calculate_conversion_factor(
    *,
    root: str,
    coupon_pct: float,
    maturity_date: datetime.date,
    delivery_month_first_day: datetime.date,
    call_date: Optional[datetime.date] = None,
) -> float:
    spec = get_contract_spec(root)
    end_date = _resolve_reference_end_date(maturity_date=maturity_date, call_date=call_date)
    whole_months = _whole_months_between(delivery_month_first_day, end_date)
    if whole_months < 0:
        raise ValueError("maturity/call date must be on or after the first day of the delivery month")

    rounded_coupon = round_coupon_to_eighth(float(coupon_pct)) / 100.0
    n, z = divmod(whole_months, 12)
    z = (z // spec.rounding_months) * spec.rounding_months
    v = z if z < 7 else (z - 6 if spec.rounding_months == 1 else 3)

    a = (1.0 / 1.03) ** (v / 6.0)
    b = (rounded_coupon / 2.0) * ((6.0 - v) / 6.0)
    c = (1.0 / 1.03) ** ((2 * n) if z < 7 else ((2 * n) + 1))
    d = (rounded_coupon / 0.06) * (1.0 - c)
    raw = (a * ((rounded_coupon / 2.0) + c + d)) - b
    return math.floor((raw * 10000.0) + 0.5 + 1e-12) / 10000.0


def _coerce_date_columns(df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            continue
        out[col] = pd.to_datetime(out[col], errors="coerce").dt.date
    return out


def _eligible_original_terms(spec: TreasuryFutureConversionSpec, original_term_months: pd.Series) -> pd.Series:
    mask = pd.Series(True, index=original_term_months.index)
    if spec.min_original_term_months is not None:
        mask &= original_term_months >= spec.min_original_term_months
    if spec.max_original_term_months is not None:
        mask &= original_term_months <= spec.max_original_term_months
    if spec.exact_original_term_months:
        mask &= original_term_months.isin(spec.exact_original_term_months)
    return mask


def _eligible_remaining_terms(
    spec: TreasuryFutureConversionSpec,
    *,
    delivery_first: datetime.date,
    delivery_last: datetime.date,
    end_dates: pd.Series,
    period: Optional[int] = None,
) -> pd.Series:
    mask = pd.Series(True, index=end_dates.index)
    if spec.min_remaining_months_from_first is not None:
        mask &= end_dates >= _add_months(delivery_first, spec.min_remaining_months_from_first)
    max_applies = spec.max_remaining_months_from_first is not None and (
        spec.max_remaining_effective_period is None
        or period is None
        or int(period) >= int(spec.max_remaining_effective_period)
    )
    if max_applies:
        upper = _add_months(delivery_first, spec.max_remaining_months_from_first)
        if spec.max_remaining_months_from_first_exclusive:
            mask &= end_dates < upper
        else:
            mask &= end_dates <= upper
    if spec.max_remaining_months_from_last is not None:
        mask &= end_dates <= _add_months(delivery_last, spec.max_remaining_months_from_last)
    return mask


def _prepare_reference_data(
    *,
    as_of: datetime.date,
    reference_data: Optional[pd.DataFrame],
    force_refresh: bool,
) -> pd.DataFrame:
    ref_df = reference_data if reference_data is not None else update_reference_data(source="fiscaldata", force_refresh=force_refresh)
    ref_df = _coerce_date_columns(ref_df, ("auction_date", "issue_date", "maturity_date", "call_date"))
    required = {"cusip", "oi", "issue_date", "maturity_date", "cpn"}
    missing = sorted(required.difference(ref_df.columns))
    if missing:
        raise KeyError(f"UST reference data missing columns required for basket construction: {', '.join(missing)}")

    out = ref_df.copy()
    # Fixed-principal only: no TIPS, no FRNs. See the grade note at the top of this module. The
    # markers are optional because a frame may predate them or come from another source; when they
    # ARE present they are authoritative, and `_NOT_FIXED_PRINCIPAL_MARKERS` is the whole rule.
    for column, flag in _NOT_FIXED_PRINCIPAL_MARKERS:
        if column in out.columns:
            out = out[out[column].astype("string").str.strip().str.casefold() != flag].copy()
    out = out[out["issue_date"].notna() & out["maturity_date"].notna() & out["cpn"].notna()].copy()
    as_of_col = "auction_date" if "auction_date" in out.columns else "issue_date"
    out = out[out[as_of_col].notna() & (out[as_of_col] <= as_of)].copy()
    out["cusip"] = out["cusip"].astype(str)
    out["original_term_months"] = out["oi"].map(parse_original_term_months)
    return out


def build_delivery_basket_frame(
    *,
    as_of: datetime.date,
    symbol: str,
    reference_data: Optional[pd.DataFrame] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    root, contract_imm_date, period = resolve_delivery_contract(symbol, as_of)
    spec = get_contract_spec(root)
    delivery_first, delivery_last = delivery_calendar_window(contract_imm_date)

    ref_df = _prepare_reference_data(as_of=as_of, reference_data=reference_data, force_refresh=force_refresh)
    ref_df = ref_df.sort_values(["issue_date", "cusip"], ascending=[False, True]).drop_duplicates("cusip", keep="first")
    ref_df["end_date"] = ref_df["maturity_date"]
    if "call_date" in ref_df.columns:
        ref_df["end_date"] = [
            _resolve_reference_end_date(maturity_date=maturity, call_date=call_date)
            for maturity, call_date in zip(ref_df["maturity_date"], ref_df["call_date"])
        ]

    eligible = _eligible_original_terms(spec, ref_df["original_term_months"])
    eligible &= _eligible_remaining_terms(
        spec,
        delivery_first=delivery_first,
        delivery_last=delivery_last,
        end_dates=ref_df["end_date"],
        period=int(period),
    )
    basket = ref_df.loc[eligible].copy()
    if basket.empty:
        return pd.DataFrame(
            columns=[
                "as_of",
                "ticker",
                "period",
                "cusip",
                "invoice_conversion_factor",
                "futures_coupon",
                "issue_date",
                "maturity_date",
                "oi",
                "cpn",
            ]
        )

    basket = basket.sort_values(["maturity_date", "issue_date", "cusip"], ascending=[True, False, True]).reset_index(drop=True)
    basket["invoice_conversion_factor"] = [
        calculate_conversion_factor(
            root=root,
            coupon_pct=float(cpn),
            maturity_date=maturity,
            delivery_month_first_day=delivery_first,
            call_date=call_date if "call_date" in basket.columns else None,
        )
        for cpn, maturity, call_date in zip(
            basket["cpn"],
            basket["maturity_date"],
            basket["call_date"] if "call_date" in basket.columns else [None] * len(basket),
        )
    ]
    basket.insert(0, "as_of", pd.Timestamp(as_of))
    basket.insert(1, "ticker", root)
    basket.insert(2, "period", int(period))
    basket["futures_coupon"] = 6.0
    return basket


def delivery_basket_cusips(
    *,
    as_of: datetime.date,
    symbol: str,
    reference_data: Optional[pd.DataFrame] = None,
    force_refresh: bool = False,
) -> list[str]:
    frame = build_delivery_basket_frame(
        as_of=as_of,
        symbol=symbol,
        reference_data=reference_data,
        force_refresh=force_refresh,
    )
    return [str(value) for value in frame["cusip"].tolist()]


def supported_contract_roots() -> tuple[str, ...]:
    return tuple(spec.root for spec in _CONTRACT_SPECS)


__all__ = [
    "TreasuryFutureConversionSpec",
    "build_delivery_basket_frame",
    "calculate_conversion_factor",
    "contract_specs_fingerprint",
    "delivery_basket_cusips",
    "delivery_business_window",
    "delivery_calendar_window",
    "get_contract_spec",
    "parse_original_term_months",
    "resolve_delivery_contract",
    "round_coupon_to_eighth",
    "supported_contract_roots",
]
