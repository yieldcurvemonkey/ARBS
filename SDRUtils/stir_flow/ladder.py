"""Layer 1: project classified prints onto delta risk ladders (ladder spec section 4).

Labeling (audit follow-up, Task A2): output is a model-labelled D2C flow
proxy, not dealer inventory. Direction is inferred from price vs. curve mid
(or NPV vs. reported upfront for off-market prints); it is not observed
counterparty identity or a confirmed dealer position, and it is uncertified
against external truth labels (desk tickets). Venue is a platform heuristic
upstream of this module -- see SDRUtils.stir_flow.trade_selection.venue_status
and SDRUtils.stir_flow.config.D2C_PLATFORM_WHITELIST for the whitelist that
must gate any *signed research* use of this ladder.
"""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd

from SDRUtils.stir_flow import config
from SDRUtils.stir_flow import ladder_conventions as conv

N_MEETINGS = 12
N_SFR = 12
N_BASIS_MONTHS = 12
MEETING_TENORS = [f"fomc_{i}" for i in range(1, N_MEETINGS + 1)]
# Sign flip per solver type: rateslib delta sign convention differs between
# IRS-based solvers (MEETING) and STIRFuture-based solvers (FUTURES).
# IRS solver: payer swap → raw delta POSITIVE → need ×-1 for "PAID = negative"
# STIR solver: payer swap → raw delta NEGATIVE → need ×+1 for "PAID = negative"
# Golden tests are the arbiter per space.
_RL_SIGN_BY_SPACE = {
    "MEETING": -1.0,
    "FUTURES": +1.0,
    "SERFF_BASIS_SOFR": +1.0,
    "SERFF_BASIS_SPREAD": +1.0,
}
RL_DELTA_TO_FUTURES_EQ = -1.0  # legacy alias; per-space dict is authoritative


@dataclasses.dataclass
class RiskModel:
    space: str                     # MEETING | FUTURES | SERFF_BASIS
    curve_handle: object
    solver: object
    label_to_bucket: dict


def extract_bucket_deltas(delta_df, label_to_bucket, *, basis_prefix=None) -> dict:
    # Case-insensitive match: rateslib/IRSwapQuery tenor normalization uppercases
    # instrument labels (e.g. requested "fomc_1" -> solver label "FOMC_1"), so
    # label_to_bucket keys built from the pre-normalization request token would
    # never match delta_df's post-normalization labels on a case-sensitive lookup.
    out: dict = {}
    lookup = {str(k).upper(): v for k, v in label_to_bucket.items()}
    for idx, row in delta_df.iterrows():
        label = idx[-1] if isinstance(idx, tuple) else idx
        if basis_prefix is not None:
            if not str(label).startswith(basis_prefix):
                continue
            label = str(label)[len(basis_prefix):]
        elif str(label).startswith("cvx_"):
            continue
        key = str(label).upper()
        if key not in lookup:
            continue
        bucket = lookup[key]
        out[bucket] = out.get(bucket, 0.0) + float(row.iloc[0])
    return out


def build_risk_models(curve_name, curve_handle, ts, stirf_mdp, include_basis: bool) -> list:
    from MDP.IRSwaps.BARCHART_STIRF.risk import (
        build_basis_risk_ladder, build_delta_risk_ladder,
    )
    from Query.IRSwaps._CENTRAL_BANK_DATES import resolve_central_bank_tenor
    from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery

    models = []

    # MEETING space: fomc_1..12 tenor strings; bucket = absolute meeting eff date
    as_of = pd.Timestamp(ts).date()
    meeting_map = {}
    for tok in MEETING_TENORS:
        dates = resolve_central_bank_tenor(curve_handle.id(), tok, as_of=as_of)
        if dates is None:
            continue
        meeting_map[tok] = conv.meeting_bucket_key(dates[0])
    m_curve, m_solver = build_delta_risk_ladder(list(meeting_map.keys()), curve_handle)
    models.append(RiskModel("MEETING", m_curve, m_solver, meeting_map))

    # FUTURES space: SFRCM1..12; bucket = absolute contract id (solver labels ARE ids)
    sfr_queries = [STIRFutureQuery(symbol=f"SFRCM{i}") for i in range(1, N_SFR + 1)]
    f_curve, f_solver = build_delta_risk_ladder(
        sfr_queries, curve_handle, stirf_mdp_handle=stirf_mdp, timestamp=ts
    )
    fut_map = {label: label for label in f_solver.instrument_labels}
    models.append(RiskModel("FUTURES", f_curve, f_solver, fut_map))

    # SERFF basis split (FED_FUNDS prints only)
    if include_basis:
        b_curve, b_solver, _stir_solver = build_basis_risk_ladder(
            [str(i) for i in range(1, N_BASIS_MONTHS + 1)],
            curve_handle, stirf_mdp_handle=stirf_mdp, timestamp=ts,
        )
        # b_solver.instrument_labels are all "cvx_<SER bbg_id>" (the OIS/basis leg);
        # the matching pure-SOFR labels live one level down in the STIR pre-solver.
        # Bucket key = contract month, resolved from the SER pricers' effective dates
        # (bbg_id alone doesn't carry month info reliably) rather than the raw label.
        ser_pricers = stirf_mdp.fetch_pricers_flat(
            [f"SERCM{i}" for i in range(1, N_BASIS_MONTHS + 1)], ts
        )
        basis_map = {
            p.bbg_id(): conv.contract_month_key(p.effective_date())
            for p in ser_pricers.values()
        }
        models.append(RiskModel("SERFF_BASIS", b_curve, b_solver, basis_map))

    return models


LADDER_COLUMNS = [
    "unit_key", "bucket_space", "bucket_key", "delta_dv01", "as_of_date",
    "execution_timestamp", "visibility_timestamp", "p_flip",
    "direction_confidence", "curve_suspect_trade", "is_block", "dv01",
]


def dealer_signed_packages(unit, direction_row, curve_handle, snap_ts):
    """Build the dealer's position as rl instruments on the given curve handle.

    Rateslib positive notional = pay fixed. Dealer sign +1 (received) -> rl
    notional negative. Returns list of rl instruments (one per leg).
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery

    from SDRUtils.stir_flow.ladder_conventions import dealer_leg_signs

    signs = dealer_leg_signs(
        unit.kind, direction_row["classification_method"],
        direction_row["dealer_direction"], len(unit.legs),
    )
    pkgs = []
    for (_, leg), sign in zip(unit.legs.iterrows(), signs):
        rl_notional = -sign * float(leg["notional"])   # +1 received -> negative (receiver)
        q = IRSwapQuery(
            curve=curve_handle._meta_data.get("requested_curve_name"),
            effective_date=pd.Timestamp(leg["effective_date"]).date(),
            maturity_date=pd.Timestamp(leg["expiration_date"]).date(),
            structure_kwargs={"notional": rl_notional, "fixed_rate": float(leg["fixed_rate"])},
        ).resolve_query(snap_ts, pricer_or_curve=curve_handle)
        pkg, _ = q.resolve_package(pricer_or_curve=curve_handle)
        pkgs.extend(pkg)
    return pkgs


def _project_onto_model(pkgs, model: RiskModel) -> dict:
    import rateslib as rl
    delta_df = rl.Portfolio(pkgs).delta(solver=model.solver)
    if model.space == "SERFF_BASIS":
        pure = extract_bucket_deltas(delta_df, model.label_to_bucket)
        basis = extract_bucket_deltas(delta_df, model.label_to_bucket, basis_prefix="cvx_")
        out = {("SERFF_BASIS_SOFR", k): v for k, v in pure.items()}
        out.update({("SERFF_BASIS_SPREAD", k): v for k, v in basis.items()})
        return out
    return extract_bucket_deltas(delta_df, model.label_to_bucket)


def project_unit(unit, direction_row, risk_models, pricer, curve_name, snap_ts):
    from SDRUtils.stir_flow import ladder_conventions as _conv

    first = unit.legs.iloc[0]
    vis = _conv.visibility_timestamp(
        first["execution_timestamp"],
        is_block=bool(first.get("is_block")),
        cleared=(first.get("cleared") == "I") if pd.notna(first.get("cleared")) else None,
        on_facility=str(first.get("platform_identifier", "")).upper().strip() in _conv.SEF_PLATFORM_CODES
        if pd.notna(first.get("platform_identifier")) else None,
        is_capped=bool(first.get("is_capped")),
    )
    meta = dict(
        unit_key=direction_row["unit_key"],
        as_of_date=first["as_of_date"],
        execution_timestamp=first["execution_timestamp"],
        visibility_timestamp=vis,
        p_flip=direction_row.get("p_flip"),
        direction_confidence=direction_row.get("direction_confidence"),
        curve_suspect_trade=bool(direction_row.get("curve_suspect_trade")),
        is_block=bool(first.get("is_block")),
        dv01=direction_row.get("structure_dv01"),
    )

    rows = []
    for model in risk_models:
        pkgs = None
        if model.curve_handle is not None:
            pkgs = dealer_signed_packages(unit, direction_row, model.curve_handle, snap_ts)
        deltas = _project_onto_model(pkgs, model)
        for key, val in deltas.items():
            space, bucket = key if isinstance(key, tuple) else (model.space, key)
            sign = _RL_SIGN_BY_SPACE.get(space, RL_DELTA_TO_FUTURES_EQ)
            rows.append(dict(meta, bucket_space=space, bucket_key=bucket,
                             delta_dv01=sign * float(val)
                             if model.curve_handle is not None else float(val)))

    # ENTRY mark: dealer-signed NPV at the projection snapshot
    signs = _conv.dealer_leg_signs(
        unit.kind, direction_row["classification_method"],
        direction_row["dealer_direction"], len(unit.legs),
    )
    npv = 0.0
    for (_, leg), sign in zip(unit.legs.iterrows(), signs):
        lp = pricer.price_leg(curve_name, snap_ts, leg["effective_date"],
                              leg["expiration_date"], notional=float(leg["notional"]),
                              fixed_rate=float(leg["fixed_rate"]))
        npv += -sign * lp.npv_pay          # received (+1) -> value = -npv_pay
    entry = dict(unit_key=direction_row["unit_key"], mark_ts=snap_ts,
                 mark_kind="ENTRY", npv_usd=npv, pnl_since_entry_usd=0.0,
                 curve_name=curve_name)
    return rows, entry
