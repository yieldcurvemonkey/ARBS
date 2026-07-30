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
import functools

import pandas as pd

from SDRUtils.stir_flow import config
from SDRUtils.stir_flow import ladder_conventions as conv

N_MEETINGS = 12
N_SFR = 12
N_FF = 12
N_BASIS_MONTHS = 12
MEETING_TENORS = [f"fomc_{i}" for i in range(1, N_MEETINGS + 1)]

# Futures spaces are built CURVE-IMPLIED from the contract calendar (no vendor
# fetch): bucket_space -> (CME root, build_stirf is_ser flag). The is_ser flag
# selects the contract-structure spec on the ladder curve --
# ReferenceRate2 = "usd_stir"  (quarterly IMM, 3M compounded)  -> SR3
# ReferenceRate3 = "usd_stir1" (calendar month, averaged)      -> ZQ / SR1
# which reproduces exactly the spec RLSTIRFuturePricer.rl_spec() picks for the
# corresponding fetched pricer. Verified per space by network golden.
FUTURES_SPACE_SPEC = {
    "FUTURES": ("SR3", False),
    "FED_FUNDS": ("ZQ", True),
}
CME_TO_BBG = {"SR3": "SFR", "SR1": "SER", "ZQ": "FF"}
MONTHLY_ROOTS = {"SR1", "ZQ"}
# Sign flip, ONE constant for EVERY bucket space. rateslib's solver delta is
# dNPV per +1bp bump of the instrument's own *rate*, and every risk model here
# (IRS meeting strip, SR3 strip, ZQ strip, SERFF basis) is calibrated in rate
# space -- so a payer swap has POSITIVE raw delta in all of them, and exactly one
# flip lands the persisted convention (+ = dealer long futures-equivalent =
# dealer RECEIVED fixed).
#
# HISTORY (2026-07-29, PR #354 cleanup): this used to be a per-space dict with
# +1.0 for FUTURES/FED_FUNDS/SERFF_BASIS, which inverted those spaces relative to
# MEETING. The persisted table proved it: over 07/02-07/13 OUTRIGHTs, MEETING was
# 868/868 PAID-negative and 249/249 RECEIVED-positive, while FED_FUNDS was
# 288 PAID-POSITIVE / 74 RECEIVED-NEGATIVE and FUTURES was split 348 negative /
# 461 positive on PAID alone. A per-space constant cannot produce mixed signs
# within one space, so the dict was papering over the real defect: the legacy
# <ROOT>CM<n> fetch path built its risk curve from vendor settlement prices on
# nodes seeded from a different (decision-time) curve, yielding an ill-conditioned
# Jacobian -- hence not just flipped but mis-scaled deltas (e.g. |sum| = 55,575
# and 67,882 against structure DV01s of 8,274 and 10,126). The curve-implied
# dates path removed the ill-conditioning; the single constant restores the sign.
# Goldens in tests/test_stir_ladder_projection.py pin both facts per space.
RL_DELTA_TO_FUTURES_EQ = -1.0


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


@functools.lru_cache(maxsize=512)
def contract_grid(as_of: datetime.date, root: str, count: int = 12) -> tuple:
    """Contract calendar for `root` as of `as_of`: ((bbg_id, effective, maturity), ...).

    Pure calendar arithmetic -- no vendor call. Mirrors
    ``MDP.STIRFutures.STIRFutureMDP``'s ``<ROOT>CM<n>`` alias resolution and its
    instrument builder exactly, so the grid is the same contract set the fetch
    path would have returned: quarterly roots use the IMM cutoff and rateslib IMM
    dates; monthly roots run first-business-day-of-month to
    first-business-day-of-next-month. Dates are ``datetime`` (rateslib 2.x
    rejects ``datetime.date``).
    """
    import rateslib as rl

    from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import (
        _imm_cutoff, _next_contracts, cme_code_effective_date,
        first_business_day_next_month,
    )

    monthly = root in MONTHLY_ROOTS
    valid_months = list(range(1, 13)) if monthly else [3, 6, 9, 12]
    cutoff = None if monthly else _imm_cutoff
    symbols = _next_contracts(as_of, prefix=root, count=count,
                              valid_months=valid_months, cutoff_fn=cutoff)
    grid = []
    for sym in symbols:
        code = sym[len(root):]
        if monthly:
            eff = pd.Timestamp(cme_code_effective_date(code))
            mat = pd.Timestamp(first_business_day_next_month(eff))
        else:
            eff = pd.Timestamp(rl.scheduling.get_imm(code=code))
            mat = pd.Timestamp(rl.scheduling.next_imm(eff))
        grid.append((f"{CME_TO_BBG.get(root, root)}{code}",
                     eff.to_pydatetime(), mat.to_pydatetime()))
    return tuple(grid)


def build_futures_risk_model(space, curve_handle, ts, count=12) -> RiskModel:
    """Curve-implied futures risk model for `space` -- zero vendor fetches.

    The contracts are built from the calendar onto the dense decision-time curve
    via ``build_delta_risk_ladder``'s STIRF_DATES branch, so the model exists at
    EVERY timestamp the curve exists. Two deliberate differences from the legacy
    ``<ROOT>CM<n>`` fetch path, both improvements:

    1. the risk curve is calibrated to the decision-time curve's own implied
       contract rates rather than to vendor settlement prices, so the ladder is a
       reparameterisation of the very curve that produced the direction call; and
    2. published fixings are cut at the curve's own fixings index, whereas the
       fetched pricer carried one extra same-day fixing that was not yet
       published at the decision timestamp (a one-day look-ahead).

    (2) is why the FRONT monthly (ZQ) bucket lands ~14% below the legacy path
    while every deferred bucket agrees to ~0.001%; SR3 agrees to <=0.03%
    throughout. See the network goldens in tests/test_stir_ladder_projection.py.
    """
    from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
    from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery

    root, is_ser = FUTURES_SPACE_SPEC[space]
    grid = contract_grid(pd.Timestamp(ts).date(), root, count)
    queries = [
        STIRFutureQuery(effective_date=eff, maturity_date=mat,
                        structure_kwargs={"label": bbg, "is_ser": is_ser})
        for bbg, eff, mat in grid
    ]
    curve, solver = build_delta_risk_ladder(queries, curve_handle, timestamp=ts)
    return RiskModel(space, curve, solver,
                     {label: label for label in solver.instrument_labels})


def build_risk_models(curve_name, curve_handle, ts, stirf_mdp, include_basis: bool) -> list:
    from MDP.IRSwaps.BARCHART_STIRF.risk import (
        build_basis_risk_ladder, build_delta_risk_ladder,
    )
    from Query.IRSwaps._CENTRAL_BANK_DATES import resolve_central_bank_tenor

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

    # FUTURES (SR3/SFR quarterly) and FED_FUNDS (ZQ/FF monthly) spaces, both
    # curve-implied. Failures are LOUD, not swallowed: the silent pass that used
    # to sit here is what let a 74%->0% projection-coverage collapse look like a
    # clean run.
    for space in ("FUTURES", "FED_FUNDS"):
        try:
            models.append(build_futures_risk_model(space, curve_handle, ts))
        except Exception as exc:  # noqa: BLE001 - one space must not kill the rest
            print(f"RISK_MODEL_ERROR {space} @ {ts}: {type(exc).__name__}: {exc}")

    # SERFF basis split (FED_FUNDS prints only). This one genuinely needs the
    # vendor: the SERFF basis IS the SR1-vs-ZQ market spread, so there is no
    # curve-implied substitute. Conditioning-only per the research plan, so a
    # miss degrades gracefully -- but it still logs.
    if include_basis:
        try:
            b_curve, b_solver, _stir_solver = build_basis_risk_ladder(
                [str(i) for i in range(1, N_BASIS_MONTHS + 1)],
                curve_handle, stirf_mdp_handle=stirf_mdp, timestamp=ts,
            )
            ser_pricers = stirf_mdp.fetch_pricers_flat(
                [f"SERCM{i}" for i in range(1, N_BASIS_MONTHS + 1)], ts
            )
            basis_map = {
                p.bbg_id(): conv.contract_month_key(p.effective_date())
                for p in ser_pricers.values()
            }
            models.append(RiskModel("SERFF_BASIS", b_curve, b_solver, basis_map))
        except Exception as exc:  # noqa: BLE001 - conditioning-only space
            print(f"RISK_MODEL_ERROR SERFF_BASIS @ {ts}: {type(exc).__name__}: {exc}")

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
            rows.append(dict(meta, bucket_space=space, bucket_key=bucket,
                             delta_dv01=RL_DELTA_TO_FUTURES_EQ * float(val)
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
