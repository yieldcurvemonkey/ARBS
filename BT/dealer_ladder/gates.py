"""Gate-ordered execution of the dealer-ladder research protocol (G0 -> G5).

The ORDER is the method, not presentation. Price-prediction tests run LAST and only
on strata that survived the earlier gates, because a price result whose mechanism
was never established is a different claim from one whose mechanism was. Each gate
returns frames and a short verdict, and a FAILED gate is a reportable result — the
runner keeps going and records it rather than routing around it.

Every artifact is written to a results directory as CSV so the notebook renders
what was computed rather than recomputing it, and so a partial run is resumable.
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import os

import numpy as np
import pandas as pd

from BT.dealer_ladder import audit, config as cfg, controls, data, labels
from BT.dealer_ladder import signals, stats, study

RESULTS_DIRNAME = "BT/results/dealer_ladder"


# --------------------------------------------------------------------------
@dataclasses.dataclass
class GateContext:
    """Everything the gates read. Built once; each gate is a pure-ish function of it."""
    config: cfg.LadderStudyConfig
    window: tuple
    prints_all: pd.DataFrame          # unfiltered, for provenance accounting
    prints: pd.DataFrame              # signed universe
    grid: pd.DatetimeIndex
    contracts: list                   # [(bucket, eff, mat, is_ser)]
    rates_bp: dict                    # space -> gridded implied rate (bp)
    volumes: dict                     # space -> gridded volume
    stale_min: dict                   # space -> staleness in minutes
    implied_bp: dict                  # space -> curve-implied contract rate (bp)
    signal: dict                      # space -> {"level","increment","z"}
    results_dir: str

    def buckets(self, space):
        return list(self.rates_bp.get(space, pd.DataFrame()).columns)


def _write(ctx, name, frame):
    os.makedirs(ctx.results_dir, exist_ok=True)
    path = os.path.join(ctx.results_dir, f"{name}.csv")
    (frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)).to_csv(path)
    return path


def _verdict(gate, passed, headline, **detail):
    return {"gate": gate, "pass": None if passed is None else bool(passed),
            "headline": headline, **detail}


# --------------------------------------------------------------------------
def contract_calendar(as_of, spaces=("FUTURES", "FED_FUNDS"), count=6) -> list:
    """``[(bucket_key, eff, mat, is_ser)]`` for the front ``count`` of each space.

    Front six per the pre-registered basket. ``is_ser`` selects the monthly
    averaged spec for ZQ and the quarterly compounded one for SR3, matching how the
    ladder itself builds these contracts.
    """
    from SDRUtils.stir_flow.ladder import FUTURES_SPACE_SPEC, contract_grid

    out = []
    for space in spaces:
        root, is_ser = FUTURES_SPACE_SPEC[space]
        for bucket, eff, mat in contract_grid(pd.Timestamp(as_of).date(), root)[:count]:
            out.append((bucket, eff, mat, is_ser))
    return out


def load_context(conn, config=None, *, window=None, results_dir=None,
                 spaces=("FUTURES", "FED_FUNDS"), show_progress=True) -> GateContext:
    """Assemble the study's inputs. The only step that touches DB or vendor."""
    config = config or cfg.LadderStudyConfig()
    window = window or (config.window.start, config.window.end)
    results_dir = results_dir or RESULTS_DIRNAME

    prints_all = data.load_prints(conn, window)
    prints = data.apply_universe(prints_all, config.universe) if not prints_all.empty \
        else prints_all

    days = data.trading_days(window)
    grid = data.decision_grid(days, config.signal)

    # the contract set is as-of dependent; take the calendar at the window START so
    # bucket keys stay fixed across the study, and report roll explicitly instead
    contracts = contract_calendar(window[0], spaces=spaces,
                                  count=config.primary.n_contracts)

    rates_bp, volumes, stale_min, implied_bp, signal = {}, {}, {}, {}, {}
    from SDRUtils.stir_flow import config as sconfig
    from SDRUtils.stir_flow.pricing import CurvePricer

    pricer = CurvePricer()
    for space in spaces:
        buckets = [b for b, *_ in contracts if _space_of(b) == space]
        if not buckets:
            continue
        lo = pd.Timestamp(grid.min()).floor("D")
        hi = pd.Timestamp(grid.max()).ceil("D")
        bars = data.load_futures_minutes(buckets, lo, hi, show_tqdm=show_progress)
        closes, stale = data.to_minute_grid(bars.get("Close", pd.DataFrame()))
        vols, _ = data.to_minute_grid(bars.get("Volume", pd.DataFrame()),
                                      ffill_limit_min=0)
        r = data.price_to_rate_bp(closes) if not closes.empty else pd.DataFrame()
        rates_bp[space] = r.reindex(grid) if not r.empty else r
        volumes[space] = vols.reindex(grid) if not vols.empty else vols
        stale_min[space] = stale.reindex(grid) if not stale.empty else stale

        curve_name = sconfig.CURVE_FOR["SOFR" if space == "FUTURES" else "FED_FUNDS"]
        space_contracts = [c for c in contracts if _space_of(c[0]) == space]
        # warm BEFORE asking for implied rates: the backfill only warmed print
        # minutes, and a cold decision-grid minute costs ~14s and ~24 vendor requests
        warm_decision_grid(pricer, curve_name, grid, verbose=show_progress)
        implied_bp[space] = controls.curve_implied_contract_rates(
            pricer, curve_name, grid, space_contracts)

        sig_cfg = dataclasses.replace(config.signal, space=space)
        signal[space] = signals.build_signal(prints, grid, sig_cfg, buckets=buckets)

    return GateContext(config=config, window=window, prints_all=prints_all,
                       prints=prints, grid=grid, contracts=contracts,
                       rates_bp=rates_bp, volumes=volumes, stale_min=stale_min,
                       implied_bp=implied_bp, signal=signal, results_dir=results_dir)


def _space_of(bucket_key: str) -> str:
    return "FED_FUNDS" if str(bucket_key).startswith("FF") else "FUTURES"


def warm_decision_grid(pricer, curve_name, grid, *, warm_jobs=8, verbose=True) -> dict:
    """Warm every DECISION-grid minute for ``curve_name``, one bulk call per session.

    Necessary because the backfill only ever warms the minutes prints ACTUALLY
    happened at (~445/session), and the decision grid is a different set — 5-minute
    marks across the session. A grid minute that is absent from an otherwise-present
    store partition falls through to a full single-point build, which was measured at
    ~14 s and ~24 vendor requests. Across 138 sessions x 96 decisions that is both
    hours of wall clock and a quota burst large enough to throttle anything else
    running.

    Batched per session rather than in one enormous call so memory stays flat and a
    failure costs one day, not the window.
    """
    from SDRUtils.stir_flow.curve_warm import warm_pricer

    grid = pd.DatetimeIndex(grid)
    et = grid.tz_convert("America/New_York") if grid.tz is not None else grid
    days = pd.Series(et.date, index=grid)
    totals = {"bulk_seeded": 0, "built": 0, "reused": 0, "failed": 0}
    for day in pd.unique(days):
        demand = {(curve_name, ts) for ts in grid[(days == day).to_numpy()]}
        res = warm_pricer(pricer, demand, max_workers=warm_jobs)
        for k in totals:
            totals[k] += int(res.get(k, 0))
    if verbose:
        print(f"  warmed decision grid for {curve_name}: {totals}")
    return totals


# --------------------------------------------------------------------------
# G0 — labels and provenance
# --------------------------------------------------------------------------
def run_g0(ctx, conn=None, *, independent_source="citivelo", label_limit=0) -> dict:
    """Provenance: who is in the universe, and does an independent mid agree?

    Reports the exclusion ladder, the PAID/RECEIVED skew by stratum, the p_flip
    coverage share (because the `expected` weighting silently falls back to 1.0
    wherever p_flip is absent), and — the substance — the independent-mid flip rate.
    """
    out = {}
    uni = ctx.config.universe
    out["exclusion_ladder"] = data.exclusion_ladder(ctx.prints_all, uni)
    _write(ctx, "g0_exclusion_ladder", out["exclusion_ladder"])

    per_unit = ctx.prints_all.drop_duplicates("unit_key")
    skew = (per_unit.groupby(["venue_bucket", "curve_bucket", "market_bucket"],
                             dropna=False)
            .agg(n=("unit_key", "nunique"),
                 paid_share=("dealer_direction", lambda s: float((s == "PAID").mean())),
                 p_flip_share=("has_p_flip", "mean"))
            .reset_index())
    out["skew_by_stratum"] = skew
    _write(ctx, "g0_skew_by_stratum", skew)

    signed = ctx.prints.drop_duplicates("unit_key")
    out["universe_summary"] = pd.DataFrame([{
        "n_units_all": int(per_unit["unit_key"].nunique()),
        "n_units_signed": int(signed["unit_key"].nunique()),
        "paid_share_signed": float((signed["dealer_direction"] == "PAID").mean())
        if len(signed) else np.nan,
        "p_flip_coverage_signed": float(signed["has_p_flip"].mean()) if len(signed) else np.nan,
        "n_code_vintages": int(per_unit["code_vintage"].nunique(dropna=False)),
    }])
    _write(ctx, "g0_universe_summary", out["universe_summary"])

    # independent-mid flip study (SOFR only -- both sources are SOFR curves)
    if conn is not None:
        from SDRUtils._swappulse_scripts.backfill_stir_ladder import _load_units

        units = _load_units(conn, ctx.window[0], ctx.window[1])
        drows = (ctx.prints.drop_duplicates("unit_key")
                 .to_dict(orient="records"))
        recon = labels.reclassify_units(units, drows, source=independent_source,
                                        limit=label_limit)
        out["label_recon"] = recon
        if not recon.empty:
            _write(ctx, "g0_label_recon", recon)
            out["flip_by_confidence"] = labels.flip_rate_table(recon, ("our_confidence",))
            out["flip_by_trade_type"] = labels.flip_rate_table(recon, ("trade_type",))
            out["skew_vs_independent"] = labels.direction_skew_table(recon)
            for name in ("flip_by_confidence", "flip_by_trade_type",
                         "skew_vs_independent"):
                _write(ctx, f"g0_{name}", out[name])
            overall = float(recon["flipped"].mean()) if recon["flipped"].notna().any() else np.nan
            out["implied_accuracy"] = labels.implied_accuracy_bounds(overall)

    n_vint = int(out["universe_summary"]["n_code_vintages"].iloc[0])
    out["verdict"] = _verdict(
        "G0", None,
        f"signed universe {int(out['universe_summary']['n_units_signed'].iloc[0])} units; "
        f"{n_vint} code vintage(s); "
        f"flip rate {out.get('implied_accuracy', {}).get('flip_rate', float('nan')):.3f}",
        single_vintage=(n_vint == 1))
    return out


# --------------------------------------------------------------------------
# G1 — arrival integrity
# --------------------------------------------------------------------------
def run_g1(ctx, *, space=None, sample_grid=200) -> dict:
    """Automated no-lookahead audits. A gate that must PASS for anything later to mean anything."""
    space = space or ctx.config.signal.space
    sig_cfg = dataclasses.replace(ctx.config.signal, space=space)
    buckets = ctx.buckets(space)
    rng = np.random.default_rng(ctx.config.stats.seed)
    grid = ctx.grid
    if sample_grid and len(grid) > sample_grid:
        grid = pd.DatetimeIndex(sorted(rng.choice(grid, size=sample_grid, replace=False)))

    def build(p, ts):
        return signals.ladder_panel(p, pd.DatetimeIndex([ts]), space=space,
                                    half_lives=sig_cfg.half_lives,
                                    weighting=sig_cfg.weighting,
                                    include_suspect=sig_cfg.include_suspect,
                                    buckets=buckets).iloc[0]

    level = ctx.signal[space]["level"]
    verdicts = audit.run_g1_battery(
        ctx.prints[ctx.prints["bucket_space"] == space], build, grid,
        panel=level,
        standardise_fn=lambda p: signals.trailing_zscore(p, sig_cfg.z_window_days))
    frame = pd.DataFrame(verdicts)
    _write(ctx, "g1_audits", frame)
    ok = bool(frame["pass"].all())
    return {"audits": frame,
            "verdict": _verdict("G1", ok,
                                "all arrival audits pass" if ok else
                                "LOOK-AHEAD DETECTED — downstream gates are void")}


# --------------------------------------------------------------------------
# G2 — mechanism ordering (before any price test)
# --------------------------------------------------------------------------
def run_g2(ctx, *, space=None) -> dict:
    """Does a signed ladder innovation PRECEDE measurable signed futures flow?"""
    space = space or ctx.config.signal.space
    inc = ctx.signal[space]["increment"]
    closes = ctx.rates_bp.get(space, pd.DataFrame())
    vols = ctx.volumes.get(space, pd.DataFrame())
    out = {}
    if inc.empty or closes.empty or vols.empty:
        return {"verdict": _verdict("G2", None, "no data")}

    flow = data.signed_volume(-closes, vols)   # price direction = -rate direction
    ll = study.hy_lead_lag_by_day(inc, flow)
    out["lead_lag"] = ll
    _write(ctx, f"g2_lead_lag_{space}", ll)
    out["lead_lag_summary"] = pd.DataFrame([study.summarise_lead_lag(ll)])
    _write(ctx, f"g2_lead_lag_summary_{space}", out["lead_lag_summary"])

    ev = study.flow_response_event_study(inc, flow)
    out["flow_events"] = ev
    if not ev.empty:
        _write(ctx, f"g2_flow_events_{space}", ev)
        rows = []
        for h, g in ev.groupby("horizon_min"):
            r = stats.cluster_mean_t(g["flow_signed_by_innovation"].to_numpy(),
                                     stats.day_codes(g["ts"]))
            rows.append({"horizon_min": h, **r, "stars": stats.stars(r["t"]),
                         "expected_sign": -1})
        out["flow_response"] = pd.DataFrame(rows)
        _write(ctx, f"g2_flow_response_{space}", out["flow_response"])

    summ = out["lead_lag_summary"].iloc[0]
    lead = bool(np.isfinite(summ["t"]) and summ["t"] >= 3.0 and summ["mean"] > 0)
    out["verdict"] = _verdict(
        "G2", lead,
        f"ladder-leads-flow LLS mean={summ['mean']:.4g} t={summ['t']:.2f}"
        f"{summ['stars']} over {int(summ['n_blocks'])} sessions"
        + ("" if lead else " — forced-hedge channel UNSUPPORTED; any price result "
                           "must be relabelled flow/basis continuation"))
    return out


# --------------------------------------------------------------------------
# G3 — circularity battery
# --------------------------------------------------------------------------
def run_g3(ctx, *, space=None, horizon_min=None) -> dict:
    """Does the ladder survive the basis, curve shape, momentum, vol and liquidity?"""
    space = space or ctx.config.signal.space
    horizon_min = horizon_min or ctx.config.primary.horizon_min
    rates = ctx.rates_bp.get(space, pd.DataFrame())
    if rates.empty:
        return {"verdict": _verdict("G3", None, "no target data")}

    target = data.forward_rate_change_bp(rates, horizon_min)
    z = ctx.signal[space]["z"]
    panels = controls.build_control_panels(
        rates_bp=rates, volumes=ctx.volumes.get(space, pd.DataFrame()),
        implied_bp=ctx.implied_bp.get(space, pd.DataFrame()),
        ladder_level=ctx.signal[space]["level"],
        contracts=[c for c in ctx.contracts if _space_of(c[0]) == space],
        grid=ctx.grid)
    long = study.align_long(z, target, extra=panels)
    out = {"long": long}
    if long.empty:
        return {**out, "verdict": _verdict("G3", None, "no aligned observations")}

    ctrl = [c for c in controls.DEFAULT_CONTROLS if c in long.columns]
    race = study.horse_race(long, controls=ctrl)
    out["horse_race"] = race
    _write(ctx, f"g3_horse_race_{space}", race)

    def _stat(sub):
        r = stats.cluster_mean_t((np.sign(sub["signal"]) * sub["target"]).to_numpy(),
                                 stats.day_codes(sub["ts"]))
        return {"mean_bp": r["mean"], "t": r["t"], "n": r["n"]}

    out["leave_one_out"] = study.leave_one_bucket_out(long, _stat)
    _write(ctx, f"g3_leave_one_out_{space}", out["leave_one_out"])

    resid = long.assign(signal=study.residualise(long, controls=ctrl))
    out["residual_race"] = study.horse_race(resid, controls=[])
    _write(ctx, f"g3_residual_race_{space}", out["residual_race"])

    alone = race[(race["spec"] == "signal only") & (race["term"] == "signal")]
    both = race[(race["spec"] == "signal + controls") & (race["term"] == "signal")]
    t_alone = float(alone["t"].iloc[0]) if len(alone) else np.nan
    t_both = float(both["t"].iloc[0]) if len(both) else np.nan
    survives = bool(np.isfinite(t_both) and abs(t_both) >= 2.0
                    and np.sign(t_both) == np.sign(t_alone))
    out["verdict"] = _verdict(
        "G3", survives,
        f"signal t alone={t_alone:.2f}, beside controls={t_both:.2f}"
        + ("" if survives else " — effect lives in the controls; relabel as "
                              "basis/RV, not a dealer-inventory mechanism"),
        controls_used=ctrl)
    return out


# --------------------------------------------------------------------------
# G4 — the pre-registered price test, then the secondary family
# --------------------------------------------------------------------------
def _root_and_expiry(ctx, space):
    from SDRUtils.stir_flow.ladder import FUTURES_SPACE_SPEC

    root = FUTURES_SPACE_SPEC[space][0]
    roots = {b: root for b, *_ in ctx.contracts if _space_of(b) == space}
    near = data.near_expiry_mask(list(roots), ctx.window[1], ctx.config.cost)
    return roots, near


def run_primary(ctx, *, in_sample=True) -> dict:
    """The ONE locked test. Nothing here is tunable — see config's docstring."""
    p = ctx.config.primary
    space = p.target_space
    rates = ctx.rates_bp.get(space, pd.DataFrame())
    if rates.empty:
        return {"verdict": _verdict("G4-primary", None, "no target data")}
    lo, hi = (ctx.config.window.in_sample() if in_sample
              else ctx.config.window.lockout())
    mask = _date_mask(rates.index, lo, hi)
    rates_w = rates[mask]
    z = ctx.signal[space]["z"].reindex(rates_w.index)
    target_rates = data.forward_rate_change_bp(rates, p.horizon_min)  # noqa: F841

    roots, near = _root_and_expiry(ctx, space)
    costs = study.cost_bp_map(list(rates_w.columns), ctx.config.cost, near, roots)
    ledger = study.trade_ledger(
        z, rates_w, horizon_min=p.horizon_min, threshold=p.z_threshold,
        cost_bp_by_bucket=costs, predicted_sign=p.predicted_sign,
        stale_min=ctx.stale_min.get(space), max_stale_min=None)
    res = study.evaluate_trades(ledger, n_boot=ctx.config.stats.n_boot,
                               seed=ctx.config.stats.seed)
    tag = "in-sample" if in_sample else "LOCKOUT"
    passed = bool(np.isfinite(res["t"]) and res["mean"] > 0 and res["t"] >= p.t_pass)
    return {
        "ledger": ledger,
        "result": pd.DataFrame([{**res, "segment": tag}]),
        "net_table": study.net_of_costs_table(
            ledger, attenuation=ctx.config.stats.attenuation_grid),
        "verdict": _verdict(
            f"G4-primary({tag})", passed,
            f"net {res['mean']:.4f}bp/trade, t={res['t']:.2f}{res['stars']}, "
            f"n={res['n']} trades over {res['n_blocks']} sessions "
            f"(pass needs mean>0 and t>={p.t_pass})"),
    }


def _date_mask(index, lo, hi):
    idx = pd.DatetimeIndex(index)
    et = idx.tz_convert("America/New_York") if idx.tz is not None else idx
    d = pd.Series(et.date, index=idx)
    return ((d >= lo) & (d <= hi)).to_numpy()


def run_grid(ctx, ledger_sink=None, *, in_sample=True) -> dict:
    """The secondary family, judged by day-blocked Romano-Wolf over whole sessions."""
    g, p = ctx.config.grid, ctx.config.primary
    lo, hi = (ctx.config.window.in_sample() if in_sample
              else ctx.config.window.lockout())
    per_variant, rows = {}, []
    for target_space in g.target_spaces:
        rates = ctx.rates_bp.get(target_space, pd.DataFrame())
        if rates.empty:
            continue
        mask = _date_mask(rates.index, lo, hi)
        rates_w = rates[mask]
        roots, near = _root_and_expiry(ctx, target_space)
        costs = study.cost_bp_map(list(rates_w.columns), ctx.config.cost, near, roots)
        for sig_space in g.spaces:
            if sig_space not in ctx.signal:
                continue
            for hl in g.half_lives_min:
                for weighting in g.weightings:
                    sig_cfg = dataclasses.replace(
                        ctx.config.signal, space=sig_space,
                        half_life_default_min=hl,
                        half_life_block_min=max(hl, ctx.config.signal.half_life_block_min),
                        weighting=weighting)
                    built = signals.build_signal(
                        ctx.prints, ctx.grid, sig_cfg,
                        buckets=list(rates.columns) if sig_space == target_space else None)
                    zz = built["z"].reindex(rates_w.index)
                    common = [c for c in zz.columns if c in rates_w.columns]
                    if not common:
                        continue
                    for horizon in g.horizons_min:
                        label = (f"{sig_space}->{target_space}|hl{int(hl)}"
                                 f"|{weighting}|h{horizon}")
                        led = study.trade_ledger(
                            zz[common], rates_w[common], horizon_min=horizon,
                            threshold=p.z_threshold, cost_bp_by_bucket=costs,
                            predicted_sign=p.predicted_sign)
                        r = study.evaluate_trades(led, n_boot=200,
                                                  seed=ctx.config.stats.seed)
                        rows.append({"variant": label, **r})
                        if not led.empty:
                            per_variant[label] = led
                        if ledger_sink is not None:
                            ledger_sink.record(label, {
                                "signal_space": sig_space, "target": target_space,
                                "half_life": hl, "weighting": weighting,
                                "horizon": horizon}, {"mean": r["mean"], "t": r["t"]})
    league = pd.DataFrame(rows)
    out = {"league": league}
    if not league.empty:
        _write(ctx, "g4_league", league)
        out["best_and_median"] = _best_and_median(league)
        _write(ctx, "g4_best_and_median", out["best_and_median"])
        out["romano_wolf"] = _romano_wolf_over_variants(per_variant, ctx)
        if out["romano_wolf"] is not None:
            _write(ctx, "g4_romano_wolf", out["romano_wolf"])
    return out


def _best_and_median(league: pd.DataFrame) -> pd.DataFrame:
    """Best AND median config, the repo's anti-selection convention.

    A league table showing only the winner is a maximum statistic reported as if it
    were a draw. The median row is what the family looks like when you did not get
    to choose.
    """
    ok = league.dropna(subset=["t"])
    if ok.empty:
        return pd.DataFrame()
    best = ok.loc[ok["t"].idxmax()].to_dict()
    med_t = float(ok["t"].median())
    median_row = ok.iloc[(ok["t"] - med_t).abs().argmin()].to_dict()
    return pd.DataFrame([{"role": "best-config", **best},
                         {"role": "median-config", **median_row}])


def _romano_wolf_over_variants(per_variant: dict, ctx) -> pd.DataFrame | None:
    """Align every variant's per-session mean net bp, then step down over sessions."""
    if not per_variant:
        return None
    series = {}
    for label, led in per_variant.items():
        s = led.copy()
        s["day"] = pd.DatetimeIndex(s["ts"]).tz_convert("America/New_York").date
        series[label] = s.groupby("day")["net_bp"].mean()
    panel = pd.DataFrame(series).dropna(how="all")
    if panel.empty or panel.shape[1] < 2:
        return None
    panel = panel.fillna(0.0)
    blocks = np.arange(len(panel))          # one block per session
    return stats.romano_wolf(panel, blocks, n_boot=ctx.config.stats.n_boot,
                             seed=ctx.config.stats.seed)


def run_placebos(ctx, *, space=None) -> dict:
    """The five pre-specified placebos, each with what firing would mean."""
    space = space or ctx.config.primary.target_space
    p = ctx.config.primary
    rates = ctx.rates_bp.get(space, pd.DataFrame())
    if rates.empty:
        return {"verdict": _verdict("G4-placebos", None, "no target data")}
    lo, hi = ctx.config.window.in_sample()
    rates_w = rates[_date_mask(rates.index, lo, hi)]
    roots, near = _root_and_expiry(ctx, space)
    costs = study.cost_bp_map(list(rates_w.columns), ctx.config.cost, near, roots)
    sig_cfg = dataclasses.replace(ctx.config.signal, space=space)
    buckets = list(rates.columns)

    def evaluate(prints, target=None, rotate=False):
        built = signals.build_signal(prints, ctx.grid, sig_cfg, buckets=buckets)
        z = built["z"].reindex(rates_w.index)
        if rotate:
            z = study.placebo_rotate_buckets(z)
        tgt = rates_w if target is None else target.reindex(rates_w.index)
        led = study.trade_ledger(z, tgt, horizon_min=p.horizon_min,
                                 threshold=p.z_threshold, cost_bp_by_bucket=costs,
                                 predicted_sign=p.predicted_sign)
        return study.evaluate_trades(led, n_boot=300, seed=ctx.config.stats.seed)

    prints = ctx.prints
    rows = [
        {"placebo": "none (reference)", "expect": "the effect, if any",
         **evaluate(prints)},
        {"placebo": "sign shuffle within session",
         "expect": "destroyed; survival means intensity not direction",
         **evaluate(study.placebo_sign_shuffle(prints, ctx.config.stats.seed))},
        {"placebo": "arrival +1 grid step later",
         "expect": "largely preserved; loss means knife-edge timing",
         **evaluate(study.placebo_shift_arrival(prints, ctx.config.signal.grid_minutes))},
        {"placebo": "live parity (visibility floored at exec+15m)",
         "expect": "attenuated, same sign",
         **evaluate(study.placebo_live_parity(prints, 15))},
        {"placebo": "rotated buckets",
         "expect": "~0; survival means generic curve continuation",
         **evaluate(prints, rotate=True)},
        {"placebo": "pre-arrival window",
         "expect": "~0; a result means leakage or anticipation",
         **evaluate(prints, target=study.pre_arrival_target(rates, p.horizon_min))},
    ]
    frame = pd.DataFrame(rows)
    _write(ctx, "g4_placebos", frame)
    return {"placebos": frame}


# --------------------------------------------------------------------------
# G5 — economics and capacity
# --------------------------------------------------------------------------
def run_g5(ctx, primary: dict) -> dict:
    space = ctx.config.primary.target_space
    ledger = primary.get("ledger", pd.DataFrame())
    out = {}
    if ledger is None or ledger.empty:
        return {"verdict": _verdict("G5", None, "no trades to cost")}
    out["net_table"] = study.net_of_costs_table(
        ledger, attenuation=ctx.config.stats.attenuation_grid)
    _write(ctx, "g5_net_table", out["net_table"])
    out["capacity"] = study.capacity_curve(
        ledger, ctx.volumes.get(space, pd.DataFrame()),
        dv01_per_contract=ctx.config.cost.dv01_per_contract["SR3" if space == "FUTURES" else "ZQ"])
    _write(ctx, "g5_capacity", out["capacity"])
    net = out["net_table"]
    net_row = net[net["measure"] == "net of costs"]
    mean_net = float(net_row["mean_bp"].iloc[0]) if len(net_row) else np.nan
    worst_att = stats.attenuate(mean_net, min(ctx.config.stats.attenuation_grid))
    out["verdict"] = _verdict(
        "G5", bool(np.isfinite(worst_att) and worst_att > 0),
        f"net {mean_net:.4f}bp/trade; at accuracy a="
        f"{min(ctx.config.stats.attenuation_grid):.2f} -> {worst_att:.4f}bp")
    return out


# --------------------------------------------------------------------------
def run_all(ctx, conn=None, *, run_lockout=False, label_limit=0) -> dict:
    """Every gate in order, recording each verdict even when a gate fails.

    ``run_lockout`` is OFF by default and must be turned on deliberately: the
    lockout is evaluated once, and a failure burns the configuration.
    """
    ledger_sink = study.TrialLedger()
    res = {"g0": run_g0(ctx, conn, label_limit=label_limit)}
    res["g1"] = run_g1(ctx)
    res["g2"] = run_g2(ctx)
    res["g3"] = run_g3(ctx)
    res["primary_is"] = run_primary(ctx, in_sample=True)
    ledger_sink.record("PRIMARY (in-sample)",
                       {"horizon": ctx.config.primary.horizon_min,
                        "threshold": ctx.config.primary.z_threshold},
                       {"mean": float(res["primary_is"]["result"]["mean"].iloc[0]),
                        "t": float(res["primary_is"]["result"]["t"].iloc[0])})
    res["placebos"] = run_placebos(ctx)
    res["grid"] = run_grid(ctx, ledger_sink)
    res["g5"] = run_g5(ctx, res["primary_is"])
    if run_lockout:
        res["primary_lockout"] = run_primary(ctx, in_sample=False)
        ledger_sink.record("PRIMARY (LOCKOUT — one shot)", {},
                           {"mean": float(res["primary_lockout"]["result"]["mean"].iloc[0]),
                            "t": float(res["primary_lockout"]["result"]["t"].iloc[0])})
    res["trial_ledger"] = ledger_sink.frame()
    _write(ctx, "trial_ledger", res["trial_ledger"])

    verdicts = [v["verdict"] for v in res.values()
                if isinstance(v, dict) and "verdict" in v]
    res["verdicts"] = pd.DataFrame(verdicts)
    _write(ctx, "verdicts", res["verdicts"])
    with open(os.path.join(ctx.results_dir, "verdicts.json"), "w", encoding="utf-8") as fh:
        json.dump(verdicts, fh, indent=2, default=str)
    return res
