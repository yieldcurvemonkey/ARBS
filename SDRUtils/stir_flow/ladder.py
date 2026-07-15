"""Layer 1: project classified prints onto delta risk ladders (ladder spec section 4)."""
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
# Sign flip: rateslib delta is dNPV per +1bp instrument-rate bump; a received-fixed
# (long futures-equivalent) book LOSES on higher rates, so persisted convention
# (+ = dealer long futures-equiv) requires one flip. Golden test is the arbiter.
RL_DELTA_TO_FUTURES_EQ = -1.0


@dataclasses.dataclass
class RiskModel:
    space: str                     # MEETING | FUTURES | SERFF_BASIS
    curve_handle: object
    solver: object
    label_to_bucket: dict


def extract_bucket_deltas(delta_df, label_to_bucket, *, basis_prefix=None) -> dict:
    out: dict = {}
    for idx, row in delta_df.iterrows():
        label = idx[-1] if isinstance(idx, tuple) else idx
        if basis_prefix is not None:
            if not str(label).startswith(basis_prefix):
                continue
            label = str(label)[len(basis_prefix):]
        elif str(label).startswith("cvx_"):
            continue
        if label not in label_to_bucket:
            continue
        bucket = label_to_bucket[label]
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
