from __future__ import annotations

import datetime as dt
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

import pandas as pd
import QuantLib as ql

from BT.flow_alpha.builder import FlowAlphaStrategySpec
from BT.flow_alpha.models import EventSource, KnownDemandEvent, StateSignalSource, normalize_event_records
from BT.flow_alpha.sources import BusinessPeriodEventSource, DateListEventSource
from BT.flow_alpha.window_rules import AnchorDateWindowRule, NextPeriodBusinessDayWindowRule, SettlementWindowRule, default_rates_calendar
from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from SDRUtils._swappulse_scripts.ingest_usdswaps import LEGS_TABLE
from SDRUtils.analytics.seasonality import get_fomc_dates, get_imm_dates


_YEAR_BUCKETS: tuple[tuple[float, str], ...] = (
    (3.0, "0-3Y"),
    (7.0, "3-7Y"),
    (12.0, "7-12Y"),
    (20.0, "12-20Y"),
    (math.inf, "20Y+"),
)


def _coerce_timestamp(value: Any) -> pd.Timestamp:
    return pd.to_datetime(value, errors="coerce", utc=True)


def _coerce_numeric(value: Any) -> float:
    if value is None or value is pd.NA:
        return float("nan")
    if isinstance(value, str):
        text = value.replace(",", "").replace("$", "").strip().lower()
        try:
            if text.endswith("bn"):
                return float(text[:-2]) * 1_000_000_000.0
            if text.endswith("mm"):
                return float(text[:-2]) * 1_000_000.0
            return float(text)
        except ValueError:
            return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _bucket_maturity(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    years = _coerce_numeric(match.group(1) if match else value)
    if text.endswith("M") and match:
        years /= 12.0
    if not math.isfinite(years):
        return text or "UNKNOWN"
    for threshold, label in _YEAR_BUCKETS:
        if years <= threshold:
            return label
    return "UNKNOWN"


def fomc_event_source(*, family: str = "fomc_event", source_name: str = "FOMC_CALENDAR") -> DateListEventSource:
    return DateListEventSource(
        family=family,
        dates_fn=lambda start, end: [date for date in get_fomc_dates() if start <= date <= end],
        asset_class="RATES",
        source_name=source_name,
        instrument_scope="IRS",
    )


def imm_event_source(*, family: str = "imm_roll", source_name: str = "IMM_CALENDAR") -> DateListEventSource:
    return DateListEventSource(
        family=family,
        dates_fn=get_imm_dates,
        asset_class="RATES",
        source_name=source_name,
        instrument_scope="IRS",
    )


@dataclass
class TreasuryAuctionEventSource(EventSource):
    family: str = "treasury_auction_cycle"
    calendar: ql.Calendar = field(default_factory=default_rates_calendar)
    source_name: str = "UST_REFERENCE_DATA"
    security_terms: Sequence[int | str] = (2, 3, 5, 7, 10, 20, 30)
    families: Optional[Sequence[str]] = None
    refdata_loader: Callable[..., pd.DataFrame] = update_reference_data

    def _load_reference_data(self) -> pd.DataFrame:
        try:
            return self.refdata_loader(source="fiscaldata", source_kwargs={"otrs": self.security_terms}, force_refresh=False)
        except TypeError:
            return self.refdata_loader(source="fiscaldata", force_refresh=False)

    def fetch(self, start: dt.date, end: dt.date, **kwargs: Any) -> list[KnownDemandEvent]:
        ref_df = kwargs.get("ref_df")
        if ref_df is None:
            ref_df = self._load_reference_data()
        if ref_df is None or len(ref_df) == 0:
            return []

        df = ref_df.copy()
        for col in ("auction_date", "issue_date", "record_date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
        if "auction_date" not in df.columns:
            return []
        df = df[df["auction_date"].between(start, end)].copy()

        allowed = set(self.families or [])
        events: list[KnownDemandEvent] = []
        for _, row in df.iterrows():
            auction_date = row.get("auction_date")
            if pd.isna(auction_date):
                continue
            issue_date = row.get("issue_date")
            base_payload = {
                "cusip": row.get("cusip"),
                "security_term": row.get("oi"),
                "auction_date": auction_date,
                "issue_date": issue_date,
                "announcement_date": row.get("announcement_date"),
                "coupon": row.get("cpn"),
            }
            event_key = f"{row.get('cusip') or row.get('oi')}-{auction_date.isoformat()}"
            candidates = [
                ("pre_auction_concession", "PAY_FIXED", "IRS", {"event_kind": "auction"}),
                ("post_auction_squeeze", "RECEIVE_FIXED", "IRS", {"event_kind": "auction"}),
                ("wi_otr_basis", "LONG_WI_SHORT_OTR", "FRB", {"event_kind": "wi_window"}),
            ]
            for family, direction_hint, instrument_scope, extra_payload in candidates:
                if allowed and family not in allowed:
                    continue
                events.append(
                    KnownDemandEvent(
                        event_id=f"{family}-{event_key}",
                        family=family,
                        asset_class="RATES",
                        anchor_date=auction_date,
                        direction_hint=direction_hint,
                        instrument_scope=instrument_scope,
                        source=self.source_name,
                        payload=base_payload | extra_payload,
                    )
                )
        return events


@dataclass
class TreasuryCouponReinvestmentEventSource(EventSource):
    family: str = "coupon_reinvestment"
    source_name: str = "UST_REFERENCE_DATA"
    refdata_loader: Callable[..., pd.DataFrame] = update_reference_data

    def _load_reference_data(self) -> pd.DataFrame:
        try:
            return self.refdata_loader(source="fiscaldata", force_refresh=False)
        except TypeError:
            return self.refdata_loader(source="fiscaldata")

    @staticmethod
    def _semiannual_coupon_dates(maturity_date: dt.date, start: dt.date, end: dt.date) -> list[dt.date]:
        out: list[dt.date] = []
        other_month = maturity_date.month - 6 if maturity_date.month > 6 else maturity_date.month + 6
        for year in range(start.year - 1, end.year + 2):
            for month in sorted({maturity_date.month, other_month}):
                try:
                    candidate = dt.date(year, month, maturity_date.day)
                except ValueError:
                    continue
                if start <= candidate <= end:
                    out.append(candidate)
        return sorted(set(out))

    def fetch(self, start: dt.date, end: dt.date, **kwargs: Any) -> list[KnownDemandEvent]:
        ref_df = kwargs.get("ref_df")
        if ref_df is None:
            ref_df = self._load_reference_data()
        if ref_df is None or len(ref_df) == 0:
            return []

        df = ref_df.copy()
        if "maturity_date" not in df.columns:
            return []
        df["maturity_date"] = pd.to_datetime(df["maturity_date"], errors="coerce").dt.date
        totals: dict[dt.date, dict[str, Any]] = defaultdict(lambda: {"coupon_proxy": 0.0, "cusips": [], "terms": []})

        for _, row in df.iterrows():
            maturity_date = row.get("maturity_date")
            if pd.isna(maturity_date):
                continue
            coupon_proxy = _coerce_numeric(row.get("cpn"))
            coupon_proxy = abs(coupon_proxy) / 2.0 if math.isfinite(coupon_proxy) else 0.0
            for pay_date in self._semiannual_coupon_dates(maturity_date, start, end):
                totals[pay_date]["coupon_proxy"] += coupon_proxy
                totals[pay_date]["cusips"].append(row.get("cusip"))
                totals[pay_date]["terms"].append(row.get("oi"))

        events: list[KnownDemandEvent] = []
        for pay_date, payload in sorted(totals.items()):
            events.append(
                KnownDemandEvent(
                    event_id=f"coupon-{pay_date.isoformat()}",
                    family=self.family,
                    asset_class="RATES",
                    anchor_date=pay_date,
                    direction_hint="RECEIVE_FIXED",
                    instrument_scope="IRS",
                    source=self.source_name,
                    payload={
                        "payment_date": pay_date,
                        "coupon_proxy": payload["coupon_proxy"],
                        "cusips": sorted({cusip for cusip in payload["cusips"] if cusip}),
                        "security_terms": sorted({term for term in payload["terms"] if term}),
                        "size_bucket": "LARGE" if payload["coupon_proxy"] >= 20.0 else "SMALL",
                    },
                )
            )
        return events


@dataclass
class CorporateIssuancePublicSource(EventSource):
    family: str = "corporate_issuance"
    source_name: str = "PUBLIC_FILING"
    records: Optional[pd.DataFrame] = None
    loader: Optional[Callable[[dt.date, dt.date], pd.DataFrame]] = None
    anchor_mode: str = "pricing"
    aliases: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "issuer_name": ("issuer_name", "issuer", "company", "borrower"),
            "issuer_id": ("issuer_id", "cik", "ticker", "company_id"),
            "announcement_date": ("announcement_date", "announce_date", "launch_date"),
            "pricing_date": ("pricing_date", "price_date", "pricing"),
            "settlement_date": ("settlement_date", "close_date", "settlement"),
            "deal_currency": ("deal_currency", "currency", "ccy"),
            "deal_size": ("deal_size", "size", "deal_amount", "amount"),
            "maturity_bucket": ("maturity_bucket", "deal_maturity_bucket", "tenor_bucket", "maturity"),
            "pricing_status": ("pricing_status", "status"),
            "source_evidence": ("source_evidence", "evidence", "headline", "filing_url"),
            "evidence_type": ("evidence_type", "evidence_kind", "source_type"),
        }
    )

    def _normalize_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        for target, aliases in self.aliases.items():
            for alias in aliases:
                if alias in df.columns:
                    out[target] = df[alias]
                    break
            if target not in out.columns:
                out[target] = None
        for col in ("announcement_date", "pricing_date", "settlement_date"):
            out[col] = pd.to_datetime(out[col], errors="coerce").dt.date
        out["deal_size"] = out["deal_size"].map(_coerce_numeric)
        out["maturity_bucket"] = out["maturity_bucket"].map(_bucket_maturity)
        out["evidence_type"] = out["evidence_type"].fillna("PUBLIC_FILING").astype(str).str.upper()
        return out

    def fetch(self, start: dt.date, end: dt.date, **kwargs: Any) -> list[KnownDemandEvent]:
        raw = kwargs.get("records", self.records)
        if raw is None and self.loader is not None:
            raw = self.loader(start, end)
        if raw is None:
            return []
        df = pd.DataFrame(raw)
        if df.empty:
            return []
        df = self._normalize_frame(df)
        anchor_field = {"announcement": "announcement_date", "pricing": "pricing_date", "settlement": "settlement_date"}.get(self.anchor_mode, "pricing_date")
        df = df[df[anchor_field].notna()].copy()
        df = df[df[anchor_field].between(start, end)].copy()

        events: list[KnownDemandEvent] = []
        for idx, row in df.iterrows():
            anchor_date = row[anchor_field]
            source = "PRESS_RELEASE" if row.get("evidence_type") == "PRESS_RELEASE" else self.source_name
            issuer_key = row.get("issuer_id") or row.get("issuer_name") or idx
            events.append(
                KnownDemandEvent(
                    event_id=f"corp-public-{issuer_key}-{anchor_date}",
                    family=self.family,
                    asset_class="RATES",
                    anchor_date=anchor_date,
                    direction_hint="PAY_FIXED",
                    instrument_scope="IRS",
                    source=source,
                    confidence=0.65 if source == "PRESS_RELEASE" else 0.75,
                    payload={
                        "issuer_name": row.get("issuer_name"),
                        "issuer_id": row.get("issuer_id"),
                        "announcement_date": row.get("announcement_date"),
                        "pricing_date": row.get("pricing_date"),
                        "settlement_date": row.get("settlement_date"),
                        "deal_currency": row.get("deal_currency") or "USD",
                        "deal_size": row.get("deal_size"),
                        "maturity_bucket": row.get("maturity_bucket"),
                        "pricing_status": row.get("pricing_status") or "PUBLIC",
                        "hedge_signal_type": "PRIMARY_ISSUANCE",
                        "source_evidence": row.get("source_evidence"),
                        "evidence_type": row.get("evidence_type"),
                    },
                )
            )
        return events


@dataclass
class SDRHedgeInferenceEventSource(EventSource):
    family: str = "corporate_issuance_hedging"
    source_name: str = "SDR_INFERRED"
    swaps: Optional[pd.DataFrame] = None
    loader: Optional[Callable[[dt.date, dt.date], pd.DataFrame]] = None
    min_notional_proxy: float = 100_000_000.0
    min_trades: int = 1
    lookback_days: int = 3
    lookahead_days: int = 1
    aliases: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "execution_timestamp": ("execution_timestamp", "Event timestamp", "event_timestamp"),
            "tenor_years": ("tenor_years", "tenor", "tenor_label"),
            "notional": ("notional", "Notional amount-Leg 1", "notional_amount_leg_1"),
            "risk": ("risk", "estimated_pv01"),
            "package_type": ("package_type", "Package type"),
            "direction": ("direction", "pay_receive_fixed", "fixed_leg_direction", "fixed_rate_direction"),
        }
    )

    def _load_swaps(self, start: dt.date, end: dt.date) -> pd.DataFrame:
        if self.loader is not None:
            return pd.DataFrame(self.loader(start, end))
        if self.swaps is not None:
            return pd.DataFrame(self.swaps)
        return pd.DataFrame()

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        for target, aliases in self.aliases.items():
            for alias in aliases:
                if alias in df.columns:
                    out[target] = df[alias]
                    break
            if target not in out.columns:
                out[target] = None
        out["execution_timestamp"] = out["execution_timestamp"].map(_coerce_timestamp)
        out = out[out["execution_timestamp"].notna()].copy()
        out["trade_date"] = out["execution_timestamp"].dt.date
        out["tenor_years"] = out["tenor_years"].map(_coerce_numeric)
        out["tenor_bucket"] = out["tenor_years"].map(_bucket_maturity)
        out["notional_proxy"] = pd.to_numeric(out["risk"].map(_coerce_numeric), errors="coerce").abs()
        fallback = pd.to_numeric(out["notional"].map(_coerce_numeric), errors="coerce").abs()
        out["notional_proxy"] = out["notional_proxy"].where(out["notional_proxy"].map(math.isfinite), fallback)
        out["direction"] = out["direction"].fillna("").astype(str).str.upper()
        out["package_type"] = out["package_type"].fillna("OUTRIGHT").astype(str).str.upper()
        return out

    def _summarize_cluster(self, df: pd.DataFrame) -> dict[str, Any]:
        notional_proxy = float(df["notional_proxy"].fillna(0.0).sum())
        trade_count = int(len(df))
        directions = df["direction"].tolist()
        pay_votes = sum("PAY" in direction or "PAYER" in direction for direction in directions)
        receive_votes = sum("REC" in direction or "RECEIVE" in direction for direction in directions)
        if pay_votes > receive_votes:
            direction_hint = "PAY_FIXED"
        elif receive_votes > pay_votes:
            direction_hint = "RECEIVE_FIXED"
        else:
            direction_hint = "PAY_FIXED"
        confidence = 0.4
        if trade_count >= self.min_trades:
            confidence += 0.2
        if notional_proxy >= self.min_notional_proxy:
            confidence += 0.2
        return {
            "execution_window": (df["execution_timestamp"].min(), df["execution_timestamp"].max()),
            "notional_proxy": notional_proxy,
            "trade_count": trade_count,
            "direction_hint": direction_hint,
            "confidence": min(confidence, 0.95),
        }

    def fetch(self, start: dt.date, end: dt.date, **kwargs: Any) -> list[KnownDemandEvent]:
        public_events = normalize_event_records(kwargs.get("public_events"))
        swaps_df = kwargs.get("swaps")
        if swaps_df is None:
            swaps_df = self._load_swaps(start, end)
        df = pd.DataFrame(swaps_df)
        if df.empty:
            return []
        df = self._normalize(df)
        if df.empty:
            return []

        events: list[KnownDemandEvent] = []
        for public_event in public_events:
            pricing_date = public_event.payload.get("pricing_date") or public_event.payload.get("announcement_date") or public_event.anchor_date
            if not isinstance(pricing_date, dt.date):
                continue
            maturity_bucket = public_event.payload.get("maturity_bucket") or "UNKNOWN"
            subset = df[(df["trade_date"] >= pricing_date - dt.timedelta(days=self.lookback_days)) & (df["trade_date"] <= pricing_date + dt.timedelta(days=self.lookahead_days))].copy()
            if maturity_bucket != "UNKNOWN":
                subset = subset[subset["tenor_bucket"] == maturity_bucket]
            if subset.empty:
                continue
            summary = self._summarize_cluster(subset)
            if summary["trade_count"] < self.min_trades and summary["notional_proxy"] < self.min_notional_proxy:
                continue
            events.append(
                KnownDemandEvent(
                    event_id=f"{public_event.event_id}-sdr",
                    family=self.family,
                    asset_class="RATES",
                    anchor_date=pricing_date,
                    direction_hint=summary["direction_hint"],
                    instrument_scope="IRS",
                    source="PUBLIC_PLUS_SDR",
                    confidence=max(public_event.confidence, summary["confidence"]),
                    payload={
                        **public_event.payload,
                        "matched_public_event_id": public_event.event_id,
                        "hedge_signal_type": "RATE_LOCK_CLUSTER",
                        "execution_window": summary["execution_window"],
                        "notional_proxy": summary["notional_proxy"],
                        "trade_count": summary["trade_count"],
                        "sdr_table": LEGS_TABLE,
                    },
                )
            )

        if kwargs.get("emit_generic_clusters", True):
            for (trade_date, tenor_bucket), group in df.groupby(["trade_date", "tenor_bucket"], dropna=False):
                summary = self._summarize_cluster(group)
                if summary["trade_count"] < self.min_trades and summary["notional_proxy"] < self.min_notional_proxy:
                    continue
                events.append(
                    KnownDemandEvent(
                        event_id=f"sdr-cluster-{trade_date}-{tenor_bucket}",
                        family=self.family,
                        asset_class="RATES",
                        anchor_date=trade_date,
                        direction_hint=summary["direction_hint"],
                        instrument_scope="IRS",
                        source=self.source_name,
                        confidence=summary["confidence"],
                        payload={
                            "issuer_name": None,
                            "issuer_id": None,
                            "deal_currency": "USD",
                            "deal_size": None,
                            "maturity_bucket": tenor_bucket,
                            "pricing_status": "INFERRED",
                            "hedge_signal_type": "RATE_LOCK_CLUSTER",
                            "source_evidence": "SDR_CLUSTER",
                            "execution_window": summary["execution_window"],
                            "notional_proxy": summary["notional_proxy"],
                            "trade_count": summary["trade_count"],
                            "sdr_table": LEGS_TABLE,
                        },
                    )
                )
        return events


@dataclass
class CorporateIssuanceEventSource(EventSource):
    family: str = "corporate_issuance_hedging"
    public_source: CorporateIssuancePublicSource = field(default_factory=CorporateIssuancePublicSource)
    sdr_source: SDRHedgeInferenceEventSource = field(default_factory=SDRHedgeInferenceEventSource)

    def fetch(self, start: dt.date, end: dt.date, **kwargs: Any) -> list[KnownDemandEvent]:
        public_events = self.public_source.materialize(start, end, **kwargs)
        sdr_events = self.sdr_source.materialize(start, end, public_events=public_events, **kwargs)
        matched_public_ids = {event.payload.get("matched_public_event_id") for event in sdr_events if event.payload.get("matched_public_event_id")}
        combined = list(sdr_events)
        for event in public_events:
            if event.event_id in matched_public_ids:
                continue
            combined.append(event)
        return combined


@dataclass
class RateMoveStateSignalSource(StateSignalSource):
    fetch: Callable[[dt.datetime], Optional[float]]
    entry_threshold: float
    exit_threshold: float
    lookback: int = 2
    family: str = "rate_move_state_signal"

    def signal(self, state: dt.datetime, backtest=None, **kwargs: Any) -> Any:
        if backtest is None:
            return False
        window = backtest.window(self.fetch, state, self.lookback)
        if len(window) < 2 or any(value is None for value in window[-2:]):
            return False
        delta = float(window[-1]) - float(window[-2])
        if abs(delta) < self.entry_threshold:
            return False
        return {
            "triggered": True,
            "flow_signal": {"family": self.family, "delta": delta, "current_value": float(window[-1]), "previous_value": float(window[-2])},
            "flow_alpha_tag": f"{self.family}-{state:%Y%m%d}",
            "flow_alpha_family": self.family,
        }

    def exit_signal(self, state: dt.datetime, backtest=None, **kwargs: Any) -> Any:
        if backtest is None:
            return False
        window = backtest.window(self.fetch, state, self.lookback)
        if len(window) < 2 or any(value is None for value in window[-2:]):
            return False
        delta = float(window[-1]) - float(window[-2])
        return {
            "triggered": abs(delta) <= self.exit_threshold,
            "flow_signal": {"family": self.family, "delta": delta, "current_value": float(window[-1]), "previous_value": float(window[-2])},
            "flow_alpha_family": self.family,
        }


def month_end_duration_extension_spec(
    *,
    cusip: str = "CT10",
    curve: Optional[str] = None,
    value: FixedRateBondValue = FixedRateBondValue.DIRTY_PRICE,
    days_pre_month_end: int = 3,
    days_after_month_end: int = 1,
    calendar: Optional[ql.Calendar] = None,
) -> FlowAlphaStrategySpec:
    source = BusinessPeriodEventSource(
        family="month_end_duration_extension",
        period="month",
        asset_class="RATES",
        direction_hint="LONG_DURATION",
        instrument_scope="FRB",
        calendar=calendar or default_rates_calendar(),
    )
    window_rule = NextPeriodBusinessDayWindowRule(entry_offset_business_days=-abs(days_pre_month_end), next_period="month", exit_business_day=max(days_after_month_end, 1))

    def query_factory(*, event: KnownDemandEvent, **_: Any):
        return FixedRateBondQuery(cusip=cusip, curve=curve, value=value, tags=(event.event_id,))

    return FlowAlphaStrategySpec(name="FRB Month End Seasonality Backtest", source=source, query_factory=query_factory, window_rule=window_rule)


def quarter_end_duration_extension_spec(*, tenor: str = "10Y", curve: str = "USD-SOFR-1D", abs_bpv: float = 100_000.0, calendar: Optional[ql.Calendar] = None) -> FlowAlphaStrategySpec:
    source = BusinessPeriodEventSource(
        family="quarter_end_duration_extension",
        period="quarter",
        asset_class="RATES",
        direction_hint="RECEIVE_FIXED",
        instrument_scope="IRS",
        calendar=calendar or default_rates_calendar(),
    )
    window_rule = NextPeriodBusinessDayWindowRule(entry_offset_business_days=-3, next_period="quarter", exit_business_day=1)

    def query_factory(*, event: KnownDemandEvent, **_: Any):
        sign = abs(abs_bpv) if event.direction_hint == "RECEIVE_FIXED" else -abs(abs_bpv)
        return IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV, tenor=tenor, curve=curve, structure_kwargs={"bpv": sign}, tags=(event.event_id,))

    return FlowAlphaStrategySpec(name="IRS Quarter End Duration Extension", source=source, query_factory=query_factory, window_rule=window_rule)


def pre_auction_concession_spec(*, tenor: str = "10Y", curve: str = "USD-SOFR-1D", abs_bpv: float = 100_000.0) -> FlowAlphaStrategySpec:
    source = TreasuryAuctionEventSource(families=("pre_auction_concession",))
    window_rule = AnchorDateWindowRule(entry_offset_business_days=-2, exit_offset_business_days=1)

    def query_factory(*, event: KnownDemandEvent, **_: Any):
        return IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV, tenor=tenor, curve=curve, structure_kwargs={"bpv": -abs(abs_bpv)}, tags=(event.event_id,))

    return FlowAlphaStrategySpec(name="IRS Pre Auction Concession", source=source, query_factory=query_factory, window_rule=window_rule)


def post_auction_squeeze_spec(*, tenor: str = "10Y", curve: str = "USD-SOFR-1D", abs_bpv: float = 100_000.0) -> FlowAlphaStrategySpec:
    source = TreasuryAuctionEventSource(families=("post_auction_squeeze",))
    window_rule = AnchorDateWindowRule(entry_offset_business_days=0, exit_offset_business_days=1)

    def query_factory(*, event: KnownDemandEvent, **_: Any):
        return IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV, tenor=tenor, curve=curve, structure_kwargs={"bpv": abs(abs_bpv)}, tags=(event.event_id,))

    return FlowAlphaStrategySpec(name="IRS Post Auction Squeeze", source=source, query_factory=query_factory, window_rule=window_rule)


def coupon_reinvestment_spec(*, tenor: str = "5Y", curve: str = "USD-SOFR-1D", abs_bpv: float = 100_000.0) -> FlowAlphaStrategySpec:
    source = TreasuryCouponReinvestmentEventSource()
    window_rule = AnchorDateWindowRule(entry_offset_business_days=-1, exit_offset_business_days=1)

    def query_factory(*, event: KnownDemandEvent, **_: Any):
        return IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV, tenor=tenor, curve=curve, structure_kwargs={"bpv": abs(abs_bpv)}, tags=(event.event_id,))

    return FlowAlphaStrategySpec(name="IRS Coupon Reinvestment", source=source, query_factory=query_factory, window_rule=window_rule)


def repo_balance_sheet_spec(*, period: str = "quarter", tenor: str = "2Y", curve: str = "USD-SOFR-1D", abs_bpv: float = 75_000.0, calendar: Optional[ql.Calendar] = None) -> FlowAlphaStrategySpec:
    source = BusinessPeriodEventSource(
        family=f"{period}_end_repo_window",
        period=period,
        asset_class="RATES",
        direction_hint="LONG_REPO_WINDOW",
        instrument_scope="IRS",
        calendar=calendar or default_rates_calendar(),
    )
    window_rule = AnchorDateWindowRule(entry_offset_business_days=-2, exit_offset_business_days=0)

    def query_factory(*, event: KnownDemandEvent, **_: Any):
        return IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV, tenor=tenor, curve=curve, structure_kwargs={"bpv": abs(abs_bpv)}, tags=(event.event_id,))

    return FlowAlphaStrategySpec(name=f"IRS {period.title()} End Repo Window", source=source, query_factory=query_factory, window_rule=window_rule)


def corporate_issuance_rate_lock_spec(*, curve: str = "USD-SOFR-1D", tenor_bucket_to_tenor: Optional[Mapping[str, str]] = None, abs_bpv: float = 100_000.0, public_records: Optional[pd.DataFrame] = None, sdr_swaps: Optional[pd.DataFrame] = None) -> FlowAlphaStrategySpec:
    source = CorporateIssuanceEventSource(
        public_source=CorporateIssuancePublicSource(records=public_records),
        sdr_source=SDRHedgeInferenceEventSource(swaps=sdr_swaps),
    )
    window_rule = SettlementWindowRule(entry_offset_business_days=-1, exit_offset_business_days=0)
    tenor_bucket_to_tenor = tenor_bucket_to_tenor or {"0-3Y": "2Y", "3-7Y": "5Y", "7-12Y": "10Y", "12-20Y": "15Y", "20Y+": "30Y", "UNKNOWN": "5Y"}

    def query_factory(*, event: KnownDemandEvent, **_: Any):
        tenor = tenor_bucket_to_tenor.get(event.payload.get("maturity_bucket") or "UNKNOWN", "5Y")
        sign = -abs(abs_bpv) if event.direction_hint != "RECEIVE_FIXED" else abs(abs_bpv)
        return IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV, tenor=tenor, curve=curve, structure_kwargs={"bpv": sign}, tags=(event.event_id,))

    return FlowAlphaStrategySpec(name="IRS Corporate Issuance Rate Lock", source=source, query_factory=query_factory, window_rule=window_rule)


def rate_move_state_signal_spec(*, fetch: Callable[[dt.datetime], Optional[float]], tenor: str = "5Y", curve: str = "USD-SOFR-1D", abs_bpv: float = 50_000.0, entry_threshold: float = 3.0, exit_threshold: float = 1.0) -> FlowAlphaStrategySpec:
    source = RateMoveStateSignalSource(fetch=fetch, entry_threshold=entry_threshold, exit_threshold=exit_threshold)

    def query_factory(*, signal: Optional[Mapping[str, Any]] = None, **_: Any):
        delta = float((signal or {}).get("delta", 0.0))
        sign = -abs(abs_bpv) if delta > 0 else abs(abs_bpv)
        return IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV, tenor=tenor, curve=curve, structure_kwargs={"bpv": sign})

    return FlowAlphaStrategySpec(name="IRS Rate Move State Signal", source=source, query_factory=query_factory)
