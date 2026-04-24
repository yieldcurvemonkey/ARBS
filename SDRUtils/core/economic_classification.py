"""
Canonical Economic-vs-Administrative classification matrix.

This is the single source of truth used by every downstream aggregator
(flow, volume, PnL, new-risk, FOMC bucketing). Phase 3 ships the matrix;
Phase 4 wires consumers to read the materialized columns.

See design §5.2 for the full matrix and §6 (D1/D2) for rationale.

Reference: CFTC Part 43/45 v3.1 Tech Spec §43.2, §45.8(g)/(i), §45.10(d),
Appendix F lifecycle examples.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

import pandas as pd


class EconomicKind(str, Enum):
    ECONOMIC_FLOW = "ECONOMIC_FLOW"
    ECONOMIC_UNWIND = "ECONOMIC_UNWIND"
    ECONOMIC_AMENDMENT = "ECONOMIC_AMENDMENT"
    RESTATEMENT = "RESTATEMENT"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    VALUATION = "VALUATION"
    ERROR = "ERROR"
    ERROR_RECOVERY = "ERROR_RECOVERY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EconomicClassification:
    """Classification record for a single SDR event.

    Attributes:
        kind: Coarse enum used for grouping and dashboard filters.
        contributes_to_flow: Aggregator gate for directional flow.
        contributes_to_volume: Aggregator gate for trade-count volume.
        contributes_to_pnl: Aggregator gate for P&L.
        contributes_to_pnl_as_delta: True for amendment/partial-unwind
            rows whose PnL must be measured as the delta against prior
            state (versus full-PnL terminations).
        on_p43: True if the event appears in the Part 43 public tape
            (see [Tech Spec Appendix F] P43 visibility column).
        reason: Human-readable citation for the rule.
    """

    kind: EconomicKind
    contributes_to_flow: bool
    contributes_to_volume: bool
    contributes_to_pnl: bool
    contributes_to_pnl_as_delta: bool
    on_p43: bool
    reason: str


# Convenience builders for readability.
def _flow(reason: str) -> EconomicClassification:
    return EconomicClassification(
        kind=EconomicKind.ECONOMIC_FLOW,
        contributes_to_flow=True,
        contributes_to_volume=True,
        contributes_to_pnl=True,
        contributes_to_pnl_as_delta=False,
        on_p43=True,
        reason=reason,
    )


def _unwind(reason: str, *, full: bool = True) -> EconomicClassification:
    return EconomicClassification(
        kind=EconomicKind.ECONOMIC_UNWIND,
        contributes_to_flow=True,
        contributes_to_volume=False,
        contributes_to_pnl=True,
        contributes_to_pnl_as_delta=not full,
        on_p43=True,
        reason=reason,
    )


def _amendment(reason: str) -> EconomicClassification:
    return EconomicClassification(
        kind=EconomicKind.ECONOMIC_AMENDMENT,
        contributes_to_flow=True,
        contributes_to_volume=False,
        contributes_to_pnl=True,
        contributes_to_pnl_as_delta=True,
        on_p43=True,
        reason=reason,
    )


def _admin(reason: str, *, on_p43: bool = True) -> EconomicClassification:
    return EconomicClassification(
        kind=EconomicKind.ADMINISTRATIVE,
        contributes_to_flow=False,
        contributes_to_volume=False,
        contributes_to_pnl=False,
        contributes_to_pnl_as_delta=False,
        on_p43=on_p43,
        reason=reason,
    )


def _restatement(reason: str) -> EconomicClassification:
    return EconomicClassification(
        kind=EconomicKind.RESTATEMENT,
        contributes_to_flow=False,
        contributes_to_volume=False,
        contributes_to_pnl=False,
        contributes_to_pnl_as_delta=False,
        on_p43=True,
        reason=reason,
    )


def _error(reason: str) -> EconomicClassification:
    return EconomicClassification(
        kind=EconomicKind.ERROR,
        contributes_to_flow=False,
        contributes_to_volume=False,
        contributes_to_pnl=False,
        contributes_to_pnl_as_delta=False,
        on_p43=True,
        reason=reason,
    )


def _error_recovery(reason: str) -> EconomicClassification:
    return EconomicClassification(
        kind=EconomicKind.ERROR_RECOVERY,
        contributes_to_flow=False,
        contributes_to_volume=False,
        contributes_to_pnl=False,
        contributes_to_pnl_as_delta=False,
        on_p43=True,
        reason=reason,
    )


def _valuation(reason: str) -> EconomicClassification:
    return EconomicClassification(
        kind=EconomicKind.VALUATION,
        contributes_to_flow=False,
        contributes_to_volume=False,
        contributes_to_pnl=False,
        contributes_to_pnl_as_delta=False,
        on_p43=False,
        reason=reason,
    )


# Canonical matrix. Keys: (action, event_type). event_type=None means
# amendment-insensitive; amendment distinctions handled in classify_event.
MATRIX: Mapping[Tuple[str, Optional[str]], EconomicClassification] = {
    ("NEWT", "TRAD"): _flow("§43.2; [Example 1]"),
    ("NEWT", "NOVA"): _admin("[Example 4]; §45.8(g) — CP rotation, no net risk change"),
    ("NEWT", "CLRG"): _admin("[Example 6]; §45.8(i) — β/γ clearing accept", on_p43=False),
    ("NEWT", "ALOC"): _admin("[Example 11] — allocation split", on_p43=False),
    ("NEWT", "EXER"): _flow("[Appendix F] — exercise produces live swap"),
    ("NEWT", "PTNG"): _admin("§45.10(d) — SDR transfer, no economic change", on_p43=False),
    ("NEWT", "COMP"): _admin("§43.2 — compression exclusion", on_p43=False),

    ("TERM", "TRAD"): _unwind("[Example 3] — bilateral termination", full=True),
    ("TERM", "ETRM"): _unwind("[Example 3]; [#31 fn] — early termination", full=True),
    ("TERM", "NOVA"): _admin("[Example 4] — old-RC leg of novation"),
    ("TERM", "CLRG"): _admin("[Example 6]; §43.3(a)(5) — α pre-clear leg"),
    ("TERM", "CLAL"): _admin("[Appendix F] — clearing allocation unwind", on_p43=False),
    ("TERM", "ALOC"): _admin("[Example 11] — allocation cleanup", on_p43=False),
    ("TERM", "COMP"): _admin("§43.2; [Example 7] — compression exclusion", on_p43=False),

    ("PRTO", "PTNG"): _admin("§45.10(d) — SDR port transfer", on_p43=False),
    ("PRTO", None): _admin("§45.10(d) — SDR port transfer", on_p43=False),

    ("MODI", "NOVA"): _admin("[Example 5] — partial novation residual"),

    ("CORR", None): _restatement("[Appendix F] — correction replaces prior"),
    ("CORR", "TRAD"): _restatement("[Appendix F] — correction replaces prior"),

    ("EROR", None): _error("§45.14 — marked erroneous"),
    ("EROR", "TRAD"): _error("§45.14 — marked erroneous"),
    ("REVI", None): _error_recovery("§45.14; [Example 2] — error recovery"),
    ("REVI", "TRAD"): _error_recovery("§45.14; [Example 2] — error recovery"),

    ("VALU", None): _valuation("§45.4(c) — EOD valuation"),
    ("MARU", None): _valuation("§45.4(c) — margin update"),
}


_UNKNOWN_CLASS = EconomicClassification(
    kind=EconomicKind.UNKNOWN,
    contributes_to_flow=False,
    contributes_to_volume=False,
    contributes_to_pnl=False,
    contributes_to_pnl_as_delta=False,
    on_p43=True,
    reason="UNMAPPED — action×event combo not in matrix",
)


def _coerce_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, str):
        s = value.strip().upper()
        if s in {"TRUE", "1", "Y", "YES"}:
            return True
        if s in {"FALSE", "0", "N", "NO"}:
            return False
        return None
    return bool(value)


def classify_event(
    action: Optional[str],
    event: Optional[str],
    amendment_indicator: Optional[bool],
    *,
    post_priced: bool = False,
    is_compression: bool = False,
    prime_brokerage: bool = False,
    clearing_exception: Optional[str] = None,
    is_schedule_step: bool = False,
) -> EconomicClassification:
    """Classify a single SDR event against the canonical matrix.

    Overrides applied in order:
      1. PRIME_BROKERAGE=True → ADMINISTRATIVE (§43.3(a)(6)).
      2. clearing_exception='AFFL' → ADMINISTRATIVE (§43.2 inter-affiliate).
      3. is_compression=True → ADMINISTRATIVE (§43.2 compression exclusion).
      4. MODI-TRAD Amendment=True → ECONOMIC_AMENDMENT.
      5. MODI-TRAD Amendment=False and is_schedule_step=True → ADMIN (H13).
      6. MODI-TRAD Amendment=False → ADMINISTRATIVE null-fill / post-price backfill.
      7. Otherwise, lookup MATRIX[action, event]. Falls back to
         MATRIX[action, None] if the event-specific cell is missing.

    Args:
        action: Action type prefix (NEWT/TERM/MODI/CORR/EROR/REVI/VALU/MARU/PRTO).
        event: Event type suffix (TRAD/NOVA/CLRG/COMP/EXER/ALOC/PTNG/ETRM/CLAL).
        amendment_indicator: MODI amendment flag. None → flagged as
            MODI_AMENDMENT_NONE warning by validator.
        post_priced: True for post-priced / block trades; doesn't change
            classification, preserved here for matrix extensibility.
        is_compression: True when the event is part of a compression cycle
            (from lifecycle_v2 or SDR `is_compression_spec`).
        prime_brokerage: True when [#54] Prime brokerage transaction
            indicator is set (mirror swap, §43.3(a)(6)).
        clearing_exception: Clearing exception code from [#11]. 'AFFL'
            routes 100%-owned inter-affiliate trades to ADMINISTRATIVE.
        is_schedule_step: True for scheduled amortization MODIs (H13).

    Returns:
        ``EconomicClassification`` record with booleans for aggregator gates.
    """
    act = str(action).strip().upper() if action is not None else ""
    evt_raw = str(event).strip().upper() if event is not None else None
    evt = evt_raw if evt_raw else None
    # NEWT / TERM / MODI with a missing event_type default to TRAD. This
    # mirrors how the CFTC tape labels plain lifecycle actions without a
    # sub-type — absent a more specific signal, treat as a vanilla trade.
    if evt is None and act in {"NEWT", "TERM", "MODI"}:
        evt = "TRAD"
    amend = _coerce_bool(amendment_indicator)

    if prime_brokerage:
        return _admin("§43.3(a)(6) — prime brokerage mirror excluded")

    if clearing_exception and str(clearing_exception).strip().upper() == "AFFL":
        return _admin("§43.2 — 100%-owned inter-affiliate excluded")

    if is_compression and act in {"NEWT", "TERM", "MODI"}:
        return _admin("§43.2 — compression cycle excluded")

    if act == "MODI" and evt == "TRAD":
        if amend is True:
            return _amendment("[#28] — MODI with Amendment=True; ECONOMIC_AMENDMENT")
        if amend is False:
            if is_schedule_step:
                return _admin("H13 — scheduled amortization step (not amendment)")
            return _admin("§43.3(a)(4) — MODI Amend=False; null-fill / post-price backfill")
        # amend is None — defer to state-machine validator flag. Default
        # to administrative so we don't over-count flow on malformed rows.
        return _admin("MODI Amendment=None — deferring to state-machine validator")

    if (act, evt) in MATRIX:
        return MATRIX[(act, evt)]
    if (act, None) in MATRIX:
        return MATRIX[(act, None)]
    return _UNKNOWN_CLASS


def enrich_economic_class(df: pd.DataFrame) -> pd.DataFrame:
    """Materialize economic_class and contributes_* columns on a DataFrame.

    Expected columns (present in the trade tape after _enrich_event_type):
      event_action (e.g. "NEWT-TRAD"), amendment_indicator,
      is_compression, prime_brokerage_transaction_indicator,
      clearing_exception, lc_was_scheduled_amortization.

    Missing columns are treated as absent / False. The function never
    raises — every row gets a classification, even if all inputs are
    null; unmapped rows get ``EconomicKind.UNKNOWN`` so a Phase 3
    integration test can flag matrix gaps without crashing.
    """
    if df.empty:
        for col in (
            "economic_class",
            "contributes_to_flow",
            "contributes_to_volume",
            "contributes_to_pnl",
            "contributes_to_pnl_as_delta",
            "on_p43",
            "economic_class_reason",
        ):
            df[col] = pd.Series([], dtype="object")
        return df

    action_col = df.get("event_action", pd.Series([""] * len(df), index=df.index))
    parts = action_col.astype(str).str.split("-", n=1)
    actions = parts.str[0].str.upper()
    events = parts.str[1].fillna("").str.upper()
    events = events.where(events != "", None)

    amend = df.get("amendment_indicator", pd.Series([None] * len(df), index=df.index))
    comp = df.get("is_compression", pd.Series([False] * len(df), index=df.index)).fillna(False)
    pb = df.get(
        "prime_brokerage_transaction_indicator",
        pd.Series([False] * len(df), index=df.index),
    ).fillna(False)
    clr_excp = df.get("clearing_exception", pd.Series([None] * len(df), index=df.index))
    sched_step = df.get(
        "lc_was_scheduled_amortization", pd.Series([False] * len(df), index=df.index)
    ).fillna(False)

    kinds: list[str] = []
    flow_ok: list[bool] = []
    vol_ok: list[bool] = []
    pnl_ok: list[bool] = []
    pnl_delta: list[bool] = []
    p43_ok: list[bool] = []
    reasons: list[str] = []

    for i in range(len(df)):
        cls = classify_event(
            actions.iat[i],
            events.iat[i] if i < len(events) else None,
            _coerce_bool(amend.iat[i]) if len(amend) > i else None,
            is_compression=bool(comp.iat[i]),
            prime_brokerage=bool(pb.iat[i]),
            clearing_exception=clr_excp.iat[i] if len(clr_excp) > i else None,
            is_schedule_step=bool(sched_step.iat[i]),
        )
        kinds.append(cls.kind.value)
        flow_ok.append(cls.contributes_to_flow)
        vol_ok.append(cls.contributes_to_volume)
        pnl_ok.append(cls.contributes_to_pnl)
        pnl_delta.append(cls.contributes_to_pnl_as_delta)
        p43_ok.append(cls.on_p43)
        reasons.append(cls.reason)

    df["economic_class"] = kinds
    df["contributes_to_flow"] = flow_ok
    df["contributes_to_volume"] = vol_ok
    df["contributes_to_pnl"] = pnl_ok
    df["contributes_to_pnl_as_delta"] = pnl_delta
    df["on_p43"] = p43_ok
    df["economic_class_reason"] = reasons
    return df


def filter_economic(
    df: pd.DataFrame,
    kind: str,
) -> pd.DataFrame:
    """Filter a DataFrame by a single contributes_to_* gate.

    Args:
        df: Enriched tape (after enrich_economic_class).
        kind: One of ``"flow"``, ``"volume"``, ``"pnl"``.

    Returns:
        Sub-DataFrame containing only rows whose gate is True.
    """
    col_map = {
        "flow": "contributes_to_flow",
        "volume": "contributes_to_volume",
        "pnl": "contributes_to_pnl",
    }
    col = col_map.get(kind)
    if col is None or col not in df.columns:
        return df
    mask = df[col].fillna(False).astype(bool)
    return df[mask]
