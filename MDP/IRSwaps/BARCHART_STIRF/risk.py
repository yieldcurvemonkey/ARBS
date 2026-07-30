import rateslib as rl

from Query.IRSwaps.IRSwapQuery import IRSwapQuery 
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer

from typing import Union
from Query.Base.BaseQuery import BaseQuery


def build_delta_risk_ladder(
    queries: list[Union[str, BaseQuery]],
    curve_handle: RLIRSwapCurve,
    *,
    stirf_mdp_handle: STIRFutureMDP | None = None,
    timestamp=None,
):
    """Build a risk ladder from IRS queries, STIR future queries, or mixed.

    - str tenors → IRSwapQuery (backward compat).
    - STIRFutureQuery → fetches pricers via stirf_mdp_handle.
    """
    ts = timestamp or curve_handle._meta_data["timestamp"]
    _dense_curve = curve_handle.handle()
    curve_name = curve_handle._meta_data["requested_curve_name"]
    ref_curve_key = curve_handle.id()
    _fixings = curve_handle.index()

    _risk_pillar_nodes = {curve_handle.reference_date(): 1.0}
    risk_rates = []
    instrument_labels = []
    _builders: list[tuple[str, any]] = []

    for q_raw in queries:
        # ---- IRS path ----
        if isinstance(q_raw, str) or (isinstance(q_raw, BaseQuery) and q_raw.product == "IRS"):
            if isinstance(q_raw, str):
                q_raw = IRSwapQuery(curve=curve_name, tenor=q_raw)
            q_resolved = q_raw.resolve_query(ts, pricer_or_curve=curve_handle)
            pkg, _ = q_resolved.resolve_package(pricer_or_curve=curve_handle)
            irs = pkg[0]
            risk_rates.append(irs.rate().real)
            mat = max(irs.leg1.cashflows()["Acc End"])
            _risk_pillar_nodes[mat] = float(_dense_curve[mat])
            label = q_resolved.structure_kwargs.get("tenor") or str(mat)
            instrument_labels.append(label)
            _builders.append(("IRS", q_resolved))

        # ---- STIR future path ----
        elif isinstance(q_raw, BaseQuery) and q_raw.product == "STIRFUTURE":
            assert stirf_mdp_handle is not None, "stirf_mdp_handle required for STIRFutureQuery"
            q_resolved = q_raw.resolve_query(ts, pricer_or_curve=curve_handle)
            skw = q_resolved.structure_kwargs or {}
            symbol = skw.get("symbol") or q_resolved.symbol or q_resolved.tenor or ""

            if symbol:
                pricers = stirf_mdp_handle.fetch_pricers_flat([symbol], ts)
            elif skw.get("effective_date") and skw.get("maturity_date"):
                eff, mat = skw["effective_date"], skw["maturity_date"]
                stirf_on_dense = curve_handle.build_stirf(effective_date=eff, maturity_date=mat)
                risk_rates.append(stirf_on_dense.rate(curves=_dense_curve).real)
                mat_dt = rl.dt(mat.year, mat.month, mat.day)
                _risk_pillar_nodes[mat_dt] = float(_dense_curve[mat_dt])
                label = f"STIRF {eff}x{mat}"
                instrument_labels.append(label)
                _builders.append(("STIRF_DATES", (eff, mat, False)))
                continue
            else:
                raise ValueError(f"STIRFutureQuery has no symbol or dates: {q_resolved}")

            for pricer_label, p in pricers.items():
                risk_rates.append(float(p._rate))
                mat_dt = rl.dt(p._maturity_date.year, p._maturity_date.month, p._maturity_date.day)
                _risk_pillar_nodes[mat_dt] = float(_dense_curve[mat_dt])
                instrument_labels.append(p.bbg_id())
                _builders.append(("STIRF_PRICER", p))
        else:
            raise TypeError(f"Unsupported query type: {type(q_raw)}")

    # ---- build risk curve (sort nodes, dedup handled by dict) ----
    risk_rl_curve = rl.Curve(
        nodes=dict(sorted(_risk_pillar_nodes.items())),
        convention=_dense_curve.meta.convention,
        calendar=_dense_curve.meta.calendar,
        interpolation="log_linear",
        id=f"{ref_curve_key}-RISK",
    )
    _risk_meta = dict(curve_handle.meta())
    _risk_meta["id"] = f"{ref_curve_key}-RISK"
    _risk_meta["reference_curve_name"] = ref_curve_key
    risk_curve_handle = RLIRSwapCurve(
        rl_curve_id=f"{ref_curve_key}-RISK",
        rl_curve_handle=risk_rl_curve,
        fixings=_fixings,
        meta_data=_risk_meta,
    )

    # ---- second pass: rebuild instruments on the risk curve ----
    rl_risk_instruments = {}
    for label, (product, data) in zip(instrument_labels, _builders):
        if product == "IRS":
            q_risk = data.resolve_query(ts, pricer_or_curve=risk_curve_handle)
            pkg, _ = q_risk.resolve_package(pricer_or_curve=risk_curve_handle)
            rl_risk_instruments[label] = pkg[0]
        elif product == "STIRF_PRICER":
            rl_risk_instruments[label] = data.build_for_solver(
                risk_rl_curve, fallback_fixings=_fixings
            )
        elif product == "STIRF_DATES":
            eff, mat, is_ser = data
            rl_risk_instruments[label] = risk_curve_handle.build_stirf(
                effective_date=eff, maturity_date=mat, is_ser=is_ser,
            )

    rl_risk_ladder_solver = rl.Solver(
        curves=[risk_rl_curve],
        instruments=rl_risk_instruments.values(),
        instrument_labels=rl_risk_instruments.keys(),
        s=risk_rates,
        id=f"{ref_curve_key}-RISK",
        func_tol=1e-8,
        conv_tol=1e-10,
    )

    return risk_curve_handle, rl_risk_ladder_solver


def build_basis_risk_ladder(
    months: list[str],
    curve_handle: RLIRSwapCurve,
    *,
    stirf_mdp_handle: STIRFutureMDP,
    timestamp=None,
    convexity_adjustments: list[float] | None = None,
):
    """Two-layer risk ladder with explicit SERFF basis sensitivity.

    Layer 1 (STIR solver): calibrates a SOFR curve from SR1 futures.
    Layer 2 (Convexity solver): calibrates an OIS curve via
        Spread(SR1_STIRFuture, IRS_on_OIS) — the SERFF basis.
    """
    ts = timestamp or curve_handle._meta_data["timestamp"]
    _dense_curve = curve_handle.handle()
    ref_curve_key = curve_handle.id()

    n = len(months)
    ser_pricers = stirf_mdp_handle.fetch_pricers_flat([f"SERCM{i}" for i in range(1, n + 1)], ts)
    ff_pricers = stirf_mdp_handle.fetch_pricers_flat([f"FFCM{i}" for i in range(1, n + 1)], ts)

    ser_list = list(ser_pricers.values())
    ff_list = list(ff_pricers.values())
    assert len(ser_list) == len(ff_list) == n

    # ---- Layer 1: STIR curve from SR1 futures ----
    stir_nodes = {curve_handle.reference_date(): 1.0}
    stir_rates, stir_labels = [], []

    for p in ser_list:
        mat_dt = rl.dt(p._maturity_date.year, p._maturity_date.month, p._maturity_date.day)
        stir_nodes[mat_dt] = float(_dense_curve[mat_dt])
        stir_rates.append(float(p._rate))
        stir_labels.append(p.bbg_id())

    sorted_stir_nodes = dict(sorted(stir_nodes.items()))

    curve_stir = rl.Curve(
        nodes=sorted_stir_nodes, convention="act360", calendar="nyc",
        interpolation="log_linear", id="stir",
    )

    instruments_stir = [
        p.build_for_solver(curve_stir) for p in ser_list
    ]

    stir_solver = rl.Solver(
        curves=[curve_stir], instruments=instruments_stir, s=stir_rates,
        instrument_labels=stir_labels, id="STIRF", func_tol=1e-8, conv_tol=1e-10,
    )

    # ---- SERFF basis from market ----
    if convexity_adjustments is None:
        convexity_adjustments = [float(sp._rate - fp._rate) for sp, fp in zip(ser_list, ff_list)]

    # ---- Layer 2: OIS curve via Spread(STIR, IRS) ----
    ois_spec = RATESLIB_CURVE_DEFINITIONS[ref_curve_key]["ReferenceRate"]
    curve_ois = rl.Curve(
        nodes=dict(sorted_stir_nodes), convention="act360", calendar="nyc",
        interpolation="log_linear", id="ois",
    )

    instruments_ois, cvx_labels = [], []
    for p in ser_list:
        eff = rl.dt(p._effective_date.year, p._effective_date.month, p._effective_date.day)
        mat = rl.dt(p._maturity_date.year, p._maturity_date.month, p._maturity_date.day)
        stir_leg = p.build_for_solver(curve_stir)
        irs_leg = rl.IRS(effective=eff, termination=mat, spec=ois_spec, curves="ois")
        instruments_ois.append(rl.Spread(stir_leg, irs_leg))
        cvx_labels.append(f"cvx_{p.bbg_id()}")

    full_solver = rl.Solver(
        pre_solvers=[stir_solver], curves=[curve_ois],
        instruments=instruments_ois, s=convexity_adjustments,
        instrument_labels=cvx_labels, id="Convexity", func_tol=1e-8, conv_tol=1e-10,
    )

    _risk_meta = dict(curve_handle.meta())
    _risk_meta["id"] = f"{ref_curve_key}-SERFF-RISK"
    _risk_meta["reference_curve_name"] = ref_curve_key
    risk_curve_handle = RLIRSwapCurve(
        rl_curve_id=f"{ref_curve_key}-SERFF-RISK",
        rl_curve_handle=curve_ois, fixings=curve_handle.index(), meta_data=_risk_meta,
    )

    return risk_curve_handle, full_solver, stir_solver