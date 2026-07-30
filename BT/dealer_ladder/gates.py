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
from BT.dealer_ladder import lockout, session_quality, signals, stats, study

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
    front_rank: dict                  # space -> per-(minute, contract) front rank
    indep_implied_bp: dict            # space -> INDEPENDENT-curve implied rate (bp)
    block_share: dict                 # space -> decayed share of |DV01| from blocks
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
    """``[(bucket_key, eff, mat, is_ser)]`` for the front ``count`` of each space
    AS OF a single date. ``is_ser`` selects the monthly averaged spec for ZQ and the
    quarterly compounded one for SR3, matching how the ladder builds these.

    For a multi-month study use ``window_contract_calendar`` instead: the absolute
    contracts behind "the front six" change as the strip rolls.
    """
    from SDRUtils.stir_flow.ladder import FUTURES_SPACE_SPEC, contract_grid

    out = []
    for space in spaces:
        root, is_ser = FUTURES_SPACE_SPEC[space]
        for bucket, eff, mat in contract_grid(pd.Timestamp(as_of).date(), root)[:count]:
            out.append((bucket, eff, mat, is_ser))
    return out


def window_contract_calendar(window, spaces=("FUTURES", "FED_FUNDS"), count=6) -> list:
    """Union of every contract that is in the front ``count`` on ANY session.

    A superset of every date's basket, so the target can be fetched once and then
    narrowed per date by the front-rank mask. Freezing the basket at the window
    start would spend the last weeks trading an expired contract the ladder never
    emits; freezing it at the window end would look ahead.
    """
    out = []
    for space in spaces:
        out.extend(controls.window_contract_union(window, space, count))
    return out


def load_context(conn, config=None, *, window=None, results_dir=None,
                 spaces=("FUTURES", "FED_FUNDS"), show_progress=True,
                 with_independent=True, independent_source="citivelo",
                 bars_cache=None) -> GateContext:
    """Assemble the study's inputs. The only step that touches DB or vendor."""
    config = config or cfg.LadderStudyConfig()
    window = window or (config.window.start, config.window.end)
    results_dir = results_dir or RESULTS_DIRNAME

    prints_all = data.load_prints(conn, window)
    prints = data.apply_universe(prints_all, config.universe) if not prints_all.empty \
        else prints_all

    days = data.trading_days(window)

    # Session-quality gate. Three defects found by the dataset audit are session-scoped -- a
    # feed that died mid-session, a run where the tape stopped emitting large packages, and
    # sessions where the classification mid is displaced by several bp -- so they are removed
    # by dropping whole sessions rather than by truncating the window. Off unless asked for:
    # the pre-registered spec must run unchanged, and this is the robustness arm.
    sq_cfg = getattr(config, "session_quality", None)
    excluded_days, session_quality_table = set(), None
    if sq_cfg is not None and getattr(sq_cfg, "enabled", False):
        session_quality_table = session_quality.assess_sessions(conn, window, sq_cfg)
        excluded_days = set(session_quality_table.loc[
            session_quality_table["excluded"], "session_date"])
        if excluded_days:
            days = [d for d in days if pd.Timestamp(d).date() not in excluded_days]
            if not prints.empty:
                keep = ~pd.to_datetime(prints["as_of_date"]).dt.date.isin(excluded_days)
                prints = prints[keep]
            if show_progress:
                print(f"  session-quality gate: excluded {len(excluded_days)} sessions, "
                      f"{len(days)} remain")

    grid = data.decision_grid(days, config.signal)

    # The basket is a RANK statement ("front six") whose absolute contracts roll, so
    # fetch the union over the window and narrow per session with front_rank below.
    contracts = window_contract_calendar(window, spaces=spaces,
                                         count=config.primary.n_contracts)

    rates_bp, volumes, stale_min, implied_bp, signal = {}, {}, {}, {}, {}
    front_rank, indep_implied_bp, block_share = {}, {}, {}
    from SDRUtils.stir_flow import config as sconfig
    from SDRUtils.stir_flow.pricing import CurvePricer

    pricer = CurvePricer()
    for space in spaces:
        buckets = [b for b, *_ in contracts if _space_of(b) == space]
        if not buckets:
            continue
        lo = pd.Timestamp(grid.min()).floor("D")
        hi = pd.Timestamp(grid.max()).ceil("D")
        # Cached when the window has ENDED, so re-running the gates -- after a
        # fix, to re-render, to add a stage -- costs nothing at the vendor.
        bars = data.load_futures_minutes(buckets, lo, hi, show_tqdm=show_progress,
                                         cache_dir=bars_cache)
        closes, stale = data.to_minute_grid(bars.get("Close", pd.DataFrame()))
        vols, _ = data.to_minute_grid(bars.get("Volume", pd.DataFrame()),
                                      ffill_limit_min=0)
        r = data.price_to_rate_bp(closes) if not closes.empty else pd.DataFrame()
        rates_bp[space] = r.reindex(grid) if not r.empty else r
        # Price is a LEVEL, so sampling it onto the decision grid is right. Volume is
        # a FLOW, and reindexing a 1-minute volume panel onto a 5-minute grid keeps
        # one minute in five and silently throws the other four away -- measured at
        # 21% of true traded volume, which understated the G5 capacity headline by
        # 4.7x and handed G2 a signed-flow series whose volume came from a minute the
        # price move did not touch. Aggregate.
        volumes[space] = (data.to_grid_sum(vols, grid) if not vols.empty else vols)
        stale_min[space] = stale.reindex(grid) if not stale.empty else stale

        curve_name = sconfig.CURVE_FOR["SOFR" if space == "FUTURES" else "FED_FUNDS"]
        space_contracts = [c for c in contracts if _space_of(c[0]) == space]
        # warm BEFORE asking for implied rates: the backfill only warmed print
        # minutes, and a cold decision-grid minute costs ~14s and ~24 vendor requests
        warm_decision_grid(pricer, curve_name, grid, verbose=show_progress)
        implied_bp[space] = controls.curve_implied_contract_rates(
            pricer, curve_name, grid, space_contracts)

        front_rank[space] = controls.front_rank_panel(
            grid, space, config.primary.n_contracts).reindex(
                index=grid, columns=buckets)

        # G3's independent fair value. SR3 only: both independent sources are USD
        # SOFR curves, so there is no independent ZQ basis to build.
        if space == "FUTURES" and with_independent:
            try:
                indep_implied_bp[space] = controls.independent_implied_contract_rates(
                    grid, space_contracts, source=independent_source)
                if show_progress:
                    cov = float(indep_implied_bp[space].notna().mean().mean())
                    print(f"  independent implied ({independent_source}) coverage "
                          f"{cov:.1%}")
            except Exception as exc:  # a missing second source must not stop the gate
                print(f"  independent implied ({independent_source}) FAILED: "
                      f"{type(exc).__name__}: {exc}")

        block_share[space] = controls.block_share_panel(
            prints, grid, space=space, half_lives=config.signal.half_lives,
            buckets=buckets)

        sig_cfg = dataclasses.replace(config.signal, space=space)
        built = signals.build_signal(prints, grid, sig_cfg, buckets=buckets)
        # Mask the SIGNAL, not the target: a contract outside that session's front N
        # simply produces no decision, so nothing downstream has to remember the rule.
        in_front = front_rank[space].notna()
        for key in ("level", "increment", "z"):
            built[key] = built[key].where(in_front.reindex_like(built[key]))
        signal[space] = built

    return GateContext(config=config, window=window, prints_all=prints_all,
                       prints=prints, grid=grid, contracts=contracts,
                       rates_bp=rates_bp, volumes=volumes, stale_min=stale_min,
                       implied_bp=implied_bp, signal=signal, front_rank=front_rank,
                       indep_implied_bp=indep_implied_bp, block_share=block_share,
                       results_dir=results_dir)


def _space_of(bucket_key: str) -> str:
    return "FED_FUNDS" if str(bucket_key).startswith("FF") else "FUTURES"


def _mask_to_front(built: dict, ctx, space: str) -> dict:
    """Restrict a freshly-built signal to that session's front-N basket.

    ``load_context`` applies this once, but every caller that REBUILDS a signal must
    re-apply it or it silently trades the window UNION instead of the pre-registered
    basket -- 8 SR3 contracts rather than 6, including ranks 7 and 8 at the window
    start and an expired contract at the end. That would make the max-t variant, the
    family-wise correction and the placebo reference row all describe a wider universe
    than the protocol declares.
    """
    mask = ctx.front_rank.get(space)
    if mask is None or not len(mask):
        return built
    ok = mask.notna()
    return {k: (v.where(ok.reindex_like(v)) if hasattr(v, "where") else v)
            for k, v in built.items()}


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
def _load_units_chunked(conn, start, end, *, months=1):
    """`_load_units` over the window, but one month at a time.

    The single-shot version scans six months of `arbs_usd_swap_tape_legs_v2` joined to
    `arbs_usd_swap_tape_packages_v2` in one statement, which holds an AccessShare lock on both
    for ~100 s. When the tape ingest runs a schema migration -- `ALTER TABLE
    arbs_usd_swap_tape_packages_v2 ADD COLUMN` needs AccessExclusive -- the two collide, and the
    one that dies is this read, with `statement timeout`. It killed G0 on the 2026-07-30
    robustness run.

    Twelve short reads each sit far inside the timeout and release between migrations. Raising
    `statement_timeout` instead would be the wrong trade: it lengthens the window in which a prod
    migration is blocked by research work.

    Chunking is safe here because a unit never straddles a month. `ALL_PKG_LEGS_SQL` fetches a
    package's legs by `package_id` rather than by date, so a package discovered in one chunk is
    still assembled complete; a package found in two chunks yields the same `unit_key` from the
    same legs, and merging the dicts is idempotent.

    The chunk boundaries are NOT part of the vintage: this lives in the read-side study package,
    not in `VINTAGE_SOURCES`, so the stamped dataset is untouched.
    """
    from SDRUtils._swappulse_scripts.backfill_stir_ladder import _load_units

    edges = pd.date_range(pd.Timestamp(start), pd.Timestamp(end) + pd.offsets.Day(1),
                          freq=pd.DateOffset(months=months)).tolist()
    if not edges or edges[-1] <= pd.Timestamp(end):
        edges.append(pd.Timestamp(end) + pd.offsets.Day(1))

    units, failed = {}, []
    for lo, hi in zip(edges, edges[1:]):
        a = max(pd.Timestamp(lo), pd.Timestamp(start)).date()
        b = min(pd.Timestamp(hi) - pd.offsets.Day(1), pd.Timestamp(end)).date()
        if a > b:
            continue
        try:
            units.update(_load_units(conn, a, b))
        except Exception as exc:
            # One month lost to a timeout is a thinner label study, not a dead gate. Record
            # it so a partial G0 can never be mistaken for a complete one.
            failed.append((str(a), str(b), f"{type(exc).__name__}: {exc}"))
            try:
                conn.rollback()
            except Exception:
                pass
    if failed:
        print(f"  G0 unit load: {len(failed)} of {len(edges) - 1} chunks FAILED "
              f"-- the label study is partial")
        for a, b, why in failed:
            print(f"    {a}..{b}: {why[:110]}")
    return units


def run_g0(ctx, conn=None, *, independent_source="citivelo", label_limit=0,
           label_per_day=40) -> dict:
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

    # Independent-mid flip study (SOFR only -- both sources are SOFR curves).
    # Deliberately run over ON-MARKET prints INCLUDING curve-suspect ones, not just
    # the signed universe: the flip rate BY curve_bucket is the diagnostic that says
    # whether the curve-suspect gate is catching the right prints, and restricting to
    # curve-clean would throw exactly that comparison away.
    if conn is not None:
        units = _load_units_chunked(conn, ctx.window[0], ctx.window[1])
        pool = ctx.prints_all[
            ctx.prints_all["classification_method"].isin(cfg.ON_MARKET_METHODS)
            & ctx.prints_all["dealer_direction"].isin(("PAID", "RECEIVED"))
        ].drop_duplicates("unit_key")
        study_out = labels.flip_study(
            units, pool.to_dict(orient="records"), source=independent_source,
            limit=label_limit, per_day=label_per_day, seed=ctx.config.stats.seed,
            strata=pool)
        out.update({k: v for k, v in study_out.items() if k != "recon"})
        out["label_recon"] = study_out["recon"]
        if not study_out["recon"].empty:
            _write(ctx, "g0_label_recon", study_out["recon"])
            for name in ("flip_by_confidence", "flip_by_trade_type",
                         "flip_by_curve_bucket", "flip_by_hour",
                         "skew_vs_independent", "skew_vs_independent_by_hour",
                         "mid_offset_bps", "flip_mechanism", "pflip_calibration"):
                if name in out:
                    _write(ctx, f"g0_{name}", out[name])
            # a dict, so it needs shaping before it can be an artifact like the rest
            if isinstance(out.get("implied_accuracy"), dict):
                _write(ctx, "g0_implied_accuracy",
                       pd.DataFrame([out["implied_accuracy"]]))

    n_vint = int(out["universe_summary"]["n_code_vintages"].iloc[0])
    out["verdict"] = _verdict(
        "G0", None,
        f"signed universe {int(out['universe_summary']['n_units_signed'].iloc[0])} units; "
        f"{n_vint} code vintage(s); "
        f"flip rate {out.get('implied_accuracy', {}).get('flip_rate', float('nan')):.3f}",
        single_vintage=(n_vint == 1))
    return out


def run_g1(ctx, *, space=None, sample_grid=200) -> dict:
    """Automated no-lookahead audits. A gate that must PASS for anything later to mean anything.

    A VACUOUS PASS counts as a failure. The poison audits work by corrupting prints that
    should be invisible at the decision minute and checking the value does not move -- so
    if no such print exists in the sample, the audit reports clean without having tested
    anything. `max_future_prints` is therefore required to be non-zero, not merely
    reported: that exact wiring bug once passed on a builder leaking five hours of future
    flow. "Nothing detected" and "nothing to detect" must never produce the same verdict.

    ``sample_grid`` audits a random 200 of the ~13,000 decision minutes, which is a cost
    trade-off with a real limit: a leak present at 10% of minutes is certain to be caught,
    one present at 0.1% may not be. It is a check against systematic look-ahead, not proof
    of its absence at every minute.
    """
    space = space or ctx.config.signal.space
    sig_cfg = dataclasses.replace(ctx.config.signal, space=space)
    buckets = ctx.buckets(space)
    rng = np.random.default_rng(ctx.config.stats.seed)
    grid = ctx.grid
    if sample_grid and len(grid) > sample_grid:
        grid = pd.DatetimeIndex(sorted(rng.choice(grid, size=sample_grid, replace=False)))

    # The builder MUST see the whole session, not a one-element grid. ladder_panel
    # windows its per-session print chunk on `hi = gts.max()`, so a one-element grid
    # sets hi == ts and drops every not-yet-visible print BEFORE the decay matrix is
    # built -- meaning the poison audit would never evaluate the `age >= 0` gate that
    # is the actual no-lookahead mechanism. Demonstrated: with that gate deliberately
    # removed, the one-element wiring still reported PASS while the session-grid
    # builder inflated a 09:30 value 11x from a print that only became public at 14:05.
    by_session = {}
    for ts in ctx.grid:
        et = pd.Timestamp(ts).tz_convert("America/New_York")
        by_session.setdefault(et.date(), []).append(ts)

    def build(p, ts):
        day = pd.Timestamp(ts).tz_convert("America/New_York").date()
        session = pd.DatetimeIndex(by_session.get(day, [ts]))
        return signals.ladder_panel(p, session, space=space,
                                    half_lives=sig_cfg.half_lives,
                                    weighting=sig_cfg.weighting,
                                    include_suspect=sig_cfg.include_suspect,
                                    buckets=buckets).loc[ts]

    level = ctx.signal[space]["level"]
    verdicts = audit.run_g1_battery(
        ctx.prints[ctx.prints["bucket_space"] == space], build, grid,
        panel=level,
        standardise_fn=lambda p: signals.trailing_zscore(p, sig_cfg.z_window_days))
    frame = pd.DataFrame(verdicts)
    _write(ctx, "g1_audits", frame)
    all_pass = bool(frame["pass"].all())

    # Was the poison audit actually EXERCISED? Zero future prints in the sample means it
    # reported clean without testing anything, and that is not a pass.
    exercised, n_future = True, None
    if "max_future_prints" in frame.columns:
        vals = pd.to_numeric(frame["max_future_prints"], errors="coerce").dropna()
        if len(vals):
            n_future = int(vals.max())
            exercised = n_future > 0

    ok = bool(all_pass and exercised)
    if not all_pass:
        head = "LOOK-AHEAD DETECTED — downstream gates are void"
    elif not exercised:
        head = ("VACUOUS PASS — the poison audits saw zero not-yet-visible prints, so "
                "they certified nothing. Treated as a FAILURE.")
    else:
        head = (f"all arrival audits pass"
                + (f", poison audit exercised on {n_future} future prints"
                   if n_future is not None else ""))
    return {"audits": frame, "poison_exercised_on": n_future,
            "verdict": _verdict("G1", ok, head)}


# --------------------------------------------------------------------------
# G2 — mechanism ordering (before any price test)
# --------------------------------------------------------------------------
def run_g2(ctx, *, space=None, in_sample=True) -> dict:
    """Does a signed ladder innovation PRECEDE measurable signed futures flow?

    Restricted to the IN-SAMPLE segment by default. G2 and G3 are development gates
    whose outcome can prompt a re-spec of the universe or the control set, so running
    them over the whole window would consume the one-shot lockout before it is fired
    and leave the burn rule protecting nothing.
    """
    space = space or ctx.config.signal.space
    level = ctx.signal[space]["level"]
    inc = ctx.signal[space]["increment"]
    rates = ctx.rates_bp.get(space, pd.DataFrame())
    vols = ctx.volumes.get(space, pd.DataFrame())
    out = {}
    if level.empty or rates.empty or vols.empty:
        return {"verdict": _verdict("G2", None, "no data")}
    lo, hi = (ctx.config.window.in_sample() if in_sample
              else ctx.config.window.lockout())
    keep = _date_mask(rates.index, lo, hi)
    rates = rates[keep]
    vols = vols.reindex(rates.index)
    level = level.reindex(rates.index)
    inc = inc.reindex(rates.index)
    if rates.empty:
        return {"verdict": _verdict("G2", None, "no in-sample data")}

    # sign volume by PRICE direction: price moves opposite to rate, hence -rates
    flow = data.signed_volume(-rates, vols)
    # hy_corr differences its inputs, so the LADDER LEVEL and the CUMULATIVE flow
    # are what produce increment-vs-signed-volume inside. See hy_lead_lag_by_day.
    ll = study.hy_lead_lag_by_day(level, flow.cumsum())
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
    # t_pass comes from the locked PrimarySpec, not a literal. A threshold hard-coded
    # here would sit OUTSIDE the configuration fingerprint the lockout ledger records,
    # so it could be moved after seeing the holdout without the burn rule noticing.
    t_pass = ctx.config.primary.t_pass
    timing = bool(np.isfinite(summ["t"]) and summ["t"] >= t_pass and summ["mean"] > 0)

    # LLS is built from SQUARED correlations, so it is DIRECTION-BLIND: a large
    # positive LLS says the ladder leads, not which way. Under the hedging mechanism a
    # positive ladder increment means the dealer SELLS, so the signed-volume
    # correlation at the peak lag must be NEGATIVE. Certifying the channel on timing
    # alone would pass a lead in the ANTI-hedging direction -- i.e. would label a
    # refutation of the mechanism as support for it.
    rho = stats.cluster_mean_t(ll["peak_rho"].to_numpy(), ll["day"].to_numpy())
    out["peak_rho_summary"] = pd.DataFrame([{**rho, "stars": stats.stars(rho["t"])}])
    _write(ctx, f"g2_peak_rho_summary_{space}", out["peak_rho_summary"])
    direction_ok = bool(np.isfinite(rho["mean"]) and rho["mean"] < 0)

    flow_ok = None
    if "flow_response" in out and len(out["flow_response"]):
        fr = out["flow_response"]
        flow_ok = bool((fr["mean"] < 0).all())

    lead = bool(timing and direction_ok and (flow_ok is not False))
    if timing and not direction_ok:
        why = (" — the ladder LEADS but in the WRONG DIRECTION "
               f"(mean peak rho {rho['mean']:+.3f}, hedging requires negative): this "
               "REFUTES the forced-hedge channel rather than supporting it")
    elif not timing:
        why = (" — no timing lead; forced-hedge channel UNSUPPORTED, so any price "
               "result must be relabelled flow/basis continuation")
    elif flow_ok is False:
        why = (" — timing and rho agree but the signed-flow response does not match "
               "expected_sign = -1")
    else:
        why = ""
    out["verdict"] = _verdict(
        "G2", lead,
        f"LLS mean={summ['mean']:.4g} t={summ['t']:.2f}{summ['stars']}, "
        f"mean peak rho={rho['mean']:+.3f} (hedging needs < 0), "
        f"{int(summ['n_blocks'])} sessions" + why,
        timing_lead=timing, direction_ok=direction_ok, flow_sign_ok=flow_ok)
    return out


# --------------------------------------------------------------------------
# G3 — circularity battery
def run_cross_check_comparison(ctx, g2_by_space: dict) -> dict:
    """SR3 versus ZQ, with the interpretation attached rather than left to the reader.

    The brief makes this the comparison the MECHANISM turns on, and the two readings
    point at different desks:

      * leads SR3 but **not** ZQ  -> liquidity-routed hedging. The dealer hedges where
        depth is, which is the SOFR strip, regardless of where the risk actually sits.
      * leads ZQ **specifically**  -> meeting-targeted. The exposure is about policy
        dates and is hedged in the contract that isolates them.
      * leads both                -> undiscriminating; consistent with either, so the
        comparison contributes nothing and should not be quoted as if it did.
      * leads neither             -> no mechanism evidence at all.

    Assembling this in code matters because the alternative is a reader holding two
    tables side by side and inferring the label, which is exactly where a preferred
    reading gets chosen. ``g2_by_space`` maps space -> the dict ``run_g2`` returned.
    """
    rows = []
    for space, res in g2_by_space.items():
        if not isinstance(res, dict):
            continue
        summ = res.get("lead_lag_summary")
        rho = res.get("peak_rho_summary")
        v = res.get("verdict") or {}
        if summ is None or not len(summ):
            continue
        s = summ.iloc[0]
        r = rho.iloc[0] if rho is not None and len(rho) else {}
        rows.append({
            "space": space,
            "root": "SR3" if space == "FUTURES" else "ZQ",
            "lls_mean": s.get("mean"), "lls_t": s.get("t"),
            "peak_rho_mean": r.get("mean"), "peak_rho_t": r.get("t"),
            "timing_lead": v.get("timing_lead"),
            "direction_ok": v.get("direction_ok"),
            "leads": bool(v.get("timing_lead") and v.get("direction_ok")),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {"comparison": frame,
                "verdict": _verdict("G2-cross-check", None, "no G2 result for either space")}

    def _leads(root):
        sub = frame[frame["root"] == root]
        return bool(sub["leads"].iloc[0]) if len(sub) else None

    sr3, zq = _leads("SR3"), _leads("ZQ")
    if sr3 and not zq:
        reading = ("leads SR3 but not ZQ -> LIQUIDITY-ROUTED hedging: the hedge goes "
                   "where depth is, not where the risk sits")
    elif zq and not sr3:
        reading = ("leads ZQ specifically -> MEETING-TARGETED: the exposure is about "
                   "policy dates and is hedged in the contract that isolates them")
    elif sr3 and zq:
        reading = ("leads BOTH -> undiscriminating, consistent with either mechanism, "
                   "so this comparison contributes nothing and must not be quoted as "
                   "if it did")
    else:
        reading = "leads NEITHER -> no mechanism evidence from the ordering test"
    frame["reading"] = reading
    _write(ctx, "g2_cross_check", frame)
    return {"comparison": frame,
            "verdict": _verdict("G2-cross-check", None, reading)}


# --------------------------------------------------------------------------
def run_g3(ctx, *, space=None, horizon_min=None, in_sample=True) -> dict:
    """Does the ladder survive the basis, curve shape, momentum, vol and liquidity?

    IN-SAMPLE by default, for the same reason as G2: a G3 failure is exactly the kind
    of verdict that prompts re-specifying the controls, and doing that with lockout
    data in the sample destroys the holdout.
    """
    space = space or ctx.config.signal.space
    horizon_min = horizon_min or ctx.config.primary.horizon_min
    rates_all = ctx.rates_bp.get(space, pd.DataFrame())
    if rates_all.empty:
        return {"verdict": _verdict("G3", None, "no target data")}

    # Difference on the FULL panel then restrict, so a horizon straddling the segment
    # boundary is computed from real prices rather than truncated to NaN.
    target_all = data.forward_rate_change_bp(rates_all, horizon_min)
    lo, hi = (ctx.config.window.in_sample() if in_sample
              else ctx.config.window.lockout())
    keep = _date_mask(rates_all.index, lo, hi)
    rates = rates_all[keep]
    target = target_all.reindex(rates.index)
    if rates.empty:
        return {"verdict": _verdict("G3", None, "no in-sample data")}
    z = ctx.signal[space]["z"].reindex(rates.index)
    def _r(frame):
        return (frame.reindex(rates.index) if frame is not None and len(frame)
                else frame)

    panels = controls.build_control_panels(
        rates_bp=rates, volumes=_r(ctx.volumes.get(space, pd.DataFrame())),
        implied_bp=_r(ctx.implied_bp.get(space, pd.DataFrame())),
        ladder_level=_r(ctx.signal[space]["level"]),
        contracts=[c for c in ctx.contracts if _space_of(c[0]) == space],
        grid=rates.index,
        independent_implied_bp=_r(ctx.indep_implied_bp.get(space)),
        block_share=_r(ctx.block_share.get(space)),
        front_rank=_r(ctx.front_rank.get(space)))
    long = study.align_long(z, target, extra=panels)
    out = {"long": long}

    # The controls are built from curves, and a curve that reads a futures bar from
    # after the decision minute would invalidate this race in either direction. The
    # builders verify their own stamps; surface what they dropped so a reader can see
    # whether the surviving control panel is thin.
    pit = {}
    for label, frame in (("decision_curve", ctx.implied_bp.get(space)),
                         ("independent_curve", ctx.indep_implied_bp.get(space))):
        a = getattr(frame, "attrs", {}) if frame is not None else {}
        if "future_curve_rows_dropped" in a:
            pit[label] = {
                "rows_dropped_future_stamp": a["future_curve_rows_dropped"],
                "drop_rate": a["future_curve_drop_rate"],
                "rows_unverifiable_stamp": a["unverifiable_stamp_rows"],
                "unverifiable_rate": a["unverifiable_stamp_rate"]}
    if pit:
        out["point_in_time"] = pd.DataFrame(pit).T.rename_axis("curve").reset_index()
        _write(ctx, f"g3_point_in_time_{space}", out["point_in_time"])
    if long.empty:
        return {**out, "verdict": _verdict("G3", None, "no aligned observations")}

    ctrl = [c for c in controls.DEFAULT_CONTROLS if c in long.columns]
    race = study.horse_race(long, controls=ctrl)
    out["horse_race"] = race
    _write(ctx, f"g3_horse_race_{space}", race)

    # SECOND race, against a basis our own curve did not produce. Run separately
    # rather than folded in: the two bases are highly collinear, so one regression
    # would inflate both SEs and confound "survives our basis" with "survives an
    # independent one" -- which are different questions.
    indep = [c for c in controls.INDEPENDENT_CONTROLS if c in long.columns]
    if indep:
        sub = long.dropna(subset=indep)
        out["horse_race_independent"] = study.horse_race(sub, controls=ctrl + indep)
        out["n_independent_rows"] = len(sub)
        _write(ctx, f"g3_horse_race_independent_{space}", out["horse_race_independent"])

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
    coef_both = float(both["coef"].iloc[0]) if len(both) else np.nan
    # The hypothesis has a DIRECTION: a positive ladder predicts the rate RISES, so a
    # positive coefficient. abs(t) alone would report an effect in the OPPOSITE
    # direction as a pass, i.e. a negative result dressed as a positive one.
    right_sign = bool(np.isfinite(coef_both)
                      and np.sign(coef_both) == np.sign(ctx.config.primary.predicted_sign))
    survives = bool(np.isfinite(t_both) and abs(t_both) >= 2.0
                    and np.sign(t_both) == np.sign(t_alone) and right_sign)
    t_indep = np.nan
    if "horse_race_independent" in out:
        row = out["horse_race_independent"]
        row = row[(row["spec"] == "signal + controls") & (row["term"] == "signal")]
        t_indep = float(row["t"].iloc[0]) if len(row) else np.nan
        survives = survives and bool(np.isfinite(t_indep) and abs(t_indep) >= 2.0
                                     and np.sign(t_indep) == np.sign(t_alone))
    if survives:
        why = ""
    elif np.isfinite(coef_both) and not right_sign:
        why = (f" — coefficient is {coef_both:+.4g}, the OPPOSITE direction to the "
               "pre-registered hypothesis: this is a negative result, not a pass")
    else:
        why = (" — effect does not survive; relabel as basis/RV, not a "
               "dealer-inventory mechanism")
    out["verdict"] = _verdict(
        "G3", survives,
        f"signal t alone={t_alone:.2f}, vs our controls={t_both:.2f} "
        f"(coef {coef_both:+.4g}), vs independent basis={t_indep:.2f}" + why,
        controls_used=ctrl, independent_controls=indep,
        sign_matches_hypothesis=right_sign)
    return out


# --------------------------------------------------------------------------
# label-free control and conditioning splits
# --------------------------------------------------------------------------
def run_label_free(ctx, *, space=None, ledger_sink=None) -> dict:
    """The primary rule driven by UNSIGNED print intensity instead of the ladder.

    Immune to classification accuracy: it uses |delta_dv01| and ignores direction
    entirely. The comparison is the point. If the signed ladder works and this does
    not, direction is carrying the result. If BOTH work similarly, the finding is a
    flow-ACTIVITY effect and the direction model is carrying nothing -- a materially
    weaker claim, and one the attenuation grid cannot rescue.

    Intensity is non-negative, so a signed rule needs a reference: it is z-scored
    against its own trailing sessions exactly like the ladder, and a HIGH-intensity
    z then predicts a rate RISE under the same convention as a positive ladder.

    ONE ASYMMETRY, stated because it affects how the comparison reads. The primary signs
    from the ladder LEVEL (a positive ladder means the dealer is long futures-equivalent,
    whatever the trailing mean happens to be), but intensity has no meaningful zero --
    every value is non-negative -- so its direction can only come from a reference, and
    the trailing mean is that reference. The two rules therefore differ in their signing
    convention as well as in whether they use the label. That is unavoidable rather than
    an oversight, but it means "the label-free cell works and the signed one does not"
    is weaker evidence about the LABEL than it looks: it is also a statement about
    level-signing versus z-signing.
    """
    space = space or ctx.config.primary.target_space
    p = ctx.config.primary
    rates = ctx.rates_bp.get(space, pd.DataFrame())
    if rates.empty:
        return {"verdict": _verdict("label-free", None, "no target data")}
    lo, hi = ctx.config.window.in_sample()
    rates_w = rates[_date_mask(rates.index, lo, hi)]
    # Build the intensity in the TARGET's own space. Using the configured signal space
    # here would silently produce an all-NaN panel whenever the two differ -- the SR3 and
    # ZQ bucket namespaces are disjoint, so the reindex below would match nothing and the
    # cell would report "no trades" rather than "cross-space is not supported".
    intensity = signals.print_intensity_panel(
        ctx.prints, ctx.grid, space=space,
        half_lives=ctx.config.signal.half_lives)
    intensity = intensity.reindex(columns=list(rates.columns))
    mask = ctx.front_rank.get(space)
    if mask is not None and len(mask):
        intensity = intensity.where(mask.notna().reindex_like(intensity))
    z = signals.trailing_zscore(intensity, ctx.config.signal.z_window_days)
    z = z.reindex(rates_w.index)
    roots, near = _root_and_expiry(ctx, space)
    costs = study.cost_bp_map(list(rates_w.columns), ctx.config.cost, near, roots)
    led = study.trade_ledger(z, rates_w, horizon_min=p.horizon_min,
                             threshold=p.z_threshold, cost_bp_by_bucket=costs,
                             predicted_sign=p.predicted_sign)
    res = study.evaluate_trades(led, n_boot=ctx.config.stats.n_boot,
                                seed=ctx.config.stats.seed)
    frame = pd.DataFrame([{**res, "signal": "unsigned print intensity"}])
    _write(ctx, "g4_label_free", frame)
    # Recorded in the trial ledger because it IS a tradable configuration that could be
    # reported as a result -- and a family-wise correction is only honest over the family
    # actually searched.
    if ledger_sink is not None:
        ledger_sink.record(f"LABEL-FREE (unsigned intensity, {space})",
                           {"horizon": p.horizon_min, "threshold": p.z_threshold,
                            "signal": "intensity"},
                           {"mean": res["mean"], "t": res["t"]})
    return {"result": frame, "ledger": led,
            "verdict": _verdict("label-free", None,
                                f"unsigned intensity: net {res['mean']:.4f}bp, "
                                f"t={res['t']:.2f}{res['stars']}, n={res['n']}")}


def run_conditioning(ctx, primary: dict, *, space=None, n_bins=3) -> dict:
    """Split the primary ledger by each conditioner and report net bp per stratum.

    Terciles rather than a regression interaction: with ~150 independent epochs an
    interaction term is not identified, whereas "does the sign hold in all three
    buckets" is answerable and is what the audit actually asks for (segment, do not
    merely control).

    THE TERCILE BOUNDARIES ARE FULL-SAMPLE, and this table is therefore DESCRIPTIVE, not
    a tradable filter. "Does the effect survive in every volatility regime" is a
    question about the sample and is legitimately asked with sample-wide cut points.
    "Only trade the top Amihud tercile" is a different claim, it needs boundaries
    knowable at decision time, and nothing here supports it. The distinction matters
    because a reader who takes a strong stratum from this table as a trading rule has
    silently added a fitted parameter to a pre-registered spec.

    A conditioner whose panel cannot be read for the traded buckets is REPORTED as
    skipped rather than dropped: a split that quietly vanished is indistinguishable from
    one that ran and showed nothing.
    """
    space = space or ctx.config.primary.target_space
    led = primary.get("ledger", pd.DataFrame())
    if led is None or led.empty:
        return {"verdict": _verdict("conditioning", None, "no trades to split")}

    rates = ctx.rates_bp.get(space, pd.DataFrame())
    panels = controls.build_control_panels(
        rates_bp=rates, volumes=ctx.volumes.get(space, pd.DataFrame()),
        implied_bp=ctx.implied_bp.get(space, pd.DataFrame()),
        ladder_level=ctx.signal[space]["level"] if space in ctx.signal
        else pd.DataFrame(0.0, index=rates.index, columns=rates.columns),
        contracts=[c for c in ctx.contracts if _space_of(c[0]) == space],
        grid=ctx.grid,
        independent_implied_bp=ctx.indep_implied_bp.get(space),
        block_share=ctx.block_share.get(space),
        front_rank=ctx.front_rank.get(space))

    rows, skipped = [], []
    declared = controls.CONDITIONING_PANELS + controls.CONDITIONING_SERIES
    for name in declared:
        if name not in panels:
            skipped.append({"conditioner": name,
                            "reason": "panel not built for this space"})
            continue
        panel = panels[name]
        vals = []
        for _i, tr in led.iterrows():
            try:
                vals.append(float(panel.at[tr["ts"], tr["bucket"]]))
            except Exception:
                vals.append(np.nan)
        s = pd.Series(vals, index=led.index)
        if s.notna().sum() < 3 * n_bins:
            skipped.append({"conditioner": name,
                            "reason": f"only {int(s.notna().sum())} of {len(s)} trades "
                                      f"could be read from the panel (need "
                                      f"{3 * n_bins})"})
            continue
        try:
            bins = pd.qcut(s, n_bins, labels=[f"q{i + 1}" for i in range(n_bins)],
                           duplicates="drop")
        except ValueError:
            skipped.append({"conditioner": name,
                            "reason": "not enough distinct values to form terciles"})
            continue
        for label, grp in led.groupby(bins, observed=True):
            r = stats.cluster_mean_t(grp["net_bp"].to_numpy(),
                                     stats.day_codes(grp["ts"]))
            rows.append({"conditioner": name, "bucket": str(label),
                         "n": r["n"], "n_blocks": r["n_blocks"],
                         "mean_net_bp": r["mean"], "t": r["t"],
                         "stars": stats.stars(r["t"]),
                         "median_value": float(grp.assign(v=s.loc[grp.index])["v"].median())})
    frame = pd.DataFrame(rows)
    out_skipped = pd.DataFrame(skipped)
    if not out_skipped.empty:
        _write(ctx, "g4_conditioning_skipped", out_skipped)
        print(f"  conditioning: {len(declared) - len(out_skipped)} of {len(declared)} "
              f"conditioners split; {len(out_skipped)} skipped "
              f"(see g4_conditioning_skipped.csv)")
    if not frame.empty:
        _write(ctx, "g4_conditioning", frame)
        signs = frame.groupby("conditioner")["mean_net_bp"].apply(
            lambda x: bool((x > 0).all() or (x < 0).all()))
        consistent = [k for k, v in signs.items() if v]
    else:
        consistent = []
    n_split = frame["conditioner"].nunique() if len(frame) else 0
    return {
        "conditioning": frame,
        "skipped": out_skipped,
        "verdict": _verdict(
            "conditioning", None,
            f"{len(consistent)}/{n_split} conditioners sign-consistent across "
            f"terciles ({len(out_skipped)} of {len(declared)} could not be split)")}


# --------------------------------------------------------------------------
# G4 — the pre-registered price test, then the secondary family
# --------------------------------------------------------------------------
def _root_and_expiry(ctx, space):
    from SDRUtils.stir_flow.ladder import FUTURES_SPACE_SPEC

    root = FUTURES_SPACE_SPEC[space][0]
    roots = {b: root for b, *_ in ctx.contracts if _space_of(b) == space}
    near = data.near_expiry_mask(list(roots), ctx.window[1], ctx.config.cost)
    return roots, near


def run_primary(ctx, *, in_sample=True, claim_lockout=True, force_lockout=False,
                lockout_note="") -> dict:
    """The ONE locked test. Nothing here is tunable — see config's docstring.

    ``in_sample=False`` reaches the holdout, and doing so CLAIMS it: the specification
    fingerprint is recorded, and a later call under a different fingerprint is refused
    (see ``lockout.py``). Enforcing that in code rather than trusting the operator is
    the point — a promise not to look twice is the weakest form of no-lookahead
    control, and the second look is exactly the one that turns a fitted result into a
    reported out-of-sample one.
    """
    p = ctx.config.primary
    if not in_sample and claim_lockout:
        rec = lockout.claim(ctx.config, ctx.results_dir, force=force_lockout,
                            timestamp=str(pd.Timestamp.now(tz="America/New_York")),
                            code_vintage=_code_vintage(), note=lockout_note)
        print(f"  LOCKOUT CLAIMED: spec {rec['spec_fingerprint']} at "
              f"{rec['claimed_at']} (vintage {rec['code_vintage']})")
    space = p.target_space
    rates = ctx.rates_bp.get(space, pd.DataFrame())
    if rates.empty:
        return {"verdict": _verdict("G4-primary", None, "no target data")}
    lo, hi = (ctx.config.window.in_sample() if in_sample
              else ctx.config.window.lockout())
    mask = _date_mask(rates.index, lo, hi)
    rates_w = rates[mask]
    z = ctx.signal[space]["z"].reindex(rates_w.index)
    roots, near = _root_and_expiry(ctx, space)
    costs = study.cost_bp_map(list(rates_w.columns), ctx.config.cost, near, roots)
    level = ctx.signal[space]["level"].reindex(rates_w.index) \
        if space in ctx.signal else None
    ledger = study.trade_ledger(
        z, rates_w, horizon_min=p.horizon_min, threshold=p.z_threshold,
        cost_bp_by_bucket=costs, predicted_sign=p.predicted_sign,
        direction_panel=level,
        # The pre-registration did NOT specify a staleness cap, so the primary runs
        # without one and the sensitivity is reported separately by
        # run_staleness_sensitivity. Staleness is recorded per trade either way, so
        # the realised-holding-period issue is visible rather than invisible.
        stale_min=ctx.stale_min.get(space), max_stale_min=None)
    res = study.evaluate_trades(ledger, n_boot=ctx.config.stats.n_boot,
                               seed=ctx.config.stats.seed)
    tag = "in-sample" if in_sample else "LOCKOUT"
    passed = bool(np.isfinite(res["t"]) and res["mean"] > 0 and res["t"] >= p.t_pass)
    bench = study.constant_position_benchmark(ledger, n_boot=ctx.config.stats.n_boot,
                                              seed=ctx.config.stats.seed)
    if not bench.empty:
        _write(ctx, f"g4_directional_benchmark_{'is' if in_sample else 'lockout'}",
               bench)
    return {
        "ledger": ledger,
        "directional_benchmark": bench,
        "result": pd.DataFrame([{**res, "segment": tag}]),
        "net_table": study.net_of_costs_table(
            ledger, attenuation=ctx.config.stats.attenuation_grid),
        "verdict": _verdict(
            f"G4-primary({tag})", passed,
            f"net {res['mean']:.4f}bp/trade, t={res['t']:.2f}{res['stars']}, "
            f"n={res['n']} trades over {res['n_blocks']} sessions, "
            f"{res.get('share_long', float('nan')):.0%} long-rates "
            f"(pass needs mean>0 and t>={p.t_pass})"),
    }


def run_staleness_sensitivity(ctx, *, caps=(None, 30, 15, 10, 5, 2, 0),
                              in_sample=True) -> dict:
    """The primary spec re-run under progressively tighter staleness caps.

    Not a gate and not a robustness knob to pick from -- the pre-registration fixed
    no cap, so the primary runs uncapped and this table exists to say how much of
    that number is measured against CARRIED-FORWARD prices rather than fresh ones.

    It matters because the target is built on a per-session minute grid with a capped
    forward-fill: SR3 deferred contracts and ZQ trade in bursts, so a nominal 60-minute
    horizon can be a 35-minute price move with 25 minutes of flat carry at one end.
    That biases the measured move toward zero (attenuation, not false positives), so a
    result that STRENGTHENS as the cap tightens is evidence the effect is real and was
    being diluted; one that vanishes was living in the carry.

    A cap of 0 requires a bar stamped at the decision minute itself at BOTH ends, which
    on this data keeps only the front contracts in the busiest hours -- so a small n
    there is coverage, not a failure.
    """
    p = ctx.config.primary
    space = p.target_space
    rates = ctx.rates_bp.get(space, pd.DataFrame())
    if rates.empty:
        return {"table": pd.DataFrame()}
    lo, hi = (ctx.config.window.in_sample() if in_sample
              else ctx.config.window.lockout())
    rates_w = rates[_date_mask(rates.index, lo, hi)]
    z = ctx.signal[space]["z"].reindex(rates_w.index)
    level = (ctx.signal[space]["level"].reindex(rates_w.index)
             if space in ctx.signal else None)
    roots, near = _root_and_expiry(ctx, space)
    costs = study.cost_bp_map(list(rates_w.columns), ctx.config.cost, near, roots)
    stale = ctx.stale_min.get(space)

    rows = []
    for cap in caps:
        led = study.trade_ledger(
            z, rates_w, horizon_min=p.horizon_min, threshold=p.z_threshold,
            cost_bp_by_bucket=costs, predicted_sign=p.predicted_sign,
            direction_panel=level, stale_min=stale, max_stale_min=cap)
        r = study.evaluate_trades(led, n_boot=ctx.config.stats.n_boot,
                                  seed=ctx.config.stats.seed)
        realised = np.nan
        if not led.empty and "entry_stale_min" in led.columns:
            # how much of the nominal horizon was actually carry, at the worse end
            worst = led[["entry_stale_min", "exit_stale_min"]].max(axis=1)
            realised = float(np.nanmean(
                np.clip(p.horizon_min - worst.to_numpy(), 0, p.horizon_min)))
        rows.append({
            "max_stale_min": ("none" if cap is None else cap),
            "n_trades": r["n"], "n_sessions": r["n_blocks"],
            "gross_bp": (float(led["gross_bp"].mean()) if not led.empty else np.nan),
            "net_bp": r["mean"], "t": r["t"],
            "stars": r["stars"],
            "mean_realised_horizon_min": realised,
            "share_of_uncapped_trades": np.nan})
    table = pd.DataFrame(rows)
    if not table.empty and table["n_trades"].iloc[0]:
        table["share_of_uncapped_trades"] = (table["n_trades"]
                                            / table["n_trades"].iloc[0])
    _write(ctx, "g4_staleness_sensitivity", table)
    return {"table": table}


def _code_vintage():
    """The pipeline's content-hash vintage, or None. Never fatal: a missing vintage
    must not be able to block the one permitted holdout evaluation."""
    try:
        from SDRUtils.stir_flow.vintage import code_vintage
        return code_vintage()
    except Exception:
        return None


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
    per_variant, rows, skipped = {}, [], []
    def _skip(sig_space, target_space, hl, weighting, reason):
        for horizon in g.horizons_min:
            skipped.append({
                "variant": f"{sig_space}->{target_space}|hl{int(hl)}"
                           f"|{weighting}|h{horizon}",
                "reason": reason})

    for target_space in g.target_spaces:
        rates = ctx.rates_bp.get(target_space, pd.DataFrame())
        if rates.empty:
            for sig_space in g.spaces:
                for hl in g.half_lives_min:
                    for weighting in g.weightings:
                        _skip(sig_space, target_space, hl, weighting,
                              f"no futures rate panel for target space {target_space}")
            continue
        mask = _date_mask(rates.index, lo, hi)
        rates_w = rates[mask]
        roots, near = _root_and_expiry(ctx, target_space)
        costs = study.cost_bp_map(list(rates_w.columns), ctx.config.cost, near, roots)
        for sig_space in g.spaces:
            if sig_space not in ctx.signal:
                # The largest silent-skip class by far: MEETING is declared in the
                # grid but is never built (it is model-internal bookkeeping, so it is
                # not a legal test target and load_context does not construct it).
                # 192 of 288 declared variants vanished here, and the reader saw 96
                # rows with nothing to say the rest were untested rather than weak.
                for hl in g.half_lives_min:
                    for weighting in g.weightings:
                        _skip(sig_space, target_space, hl, weighting,
                              f"signal space {sig_space} not built for this window")
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
                    if sig_space == target_space:
                        built = _mask_to_front(built, ctx, sig_space)
                    zz = built["z"].reindex(rates_w.index)
                    lvl = built["level"].reindex(rates_w.index)
                    common = [c for c in zz.columns if c in rates_w.columns]
                    if not common:
                        # A declared variant that cannot run must be RECORDED, not
                        # silently dropped: cross-space pairs have disjoint bucket
                        # namespaces (SFR vs FF) so a FUTURES ladder can never join a
                        # ZQ rate panel, and a reader must see that
                        # those variants were skipped rather than tested and found weak.
                        _skip(sig_space, target_space, hl, weighting,
                              "no shared bucket keys between signal and target space")
                        continue
                    for horizon in g.horizons_min:
                        label = (f"{sig_space}->{target_space}|hl{int(hl)}"
                                 f"|{weighting}|h{horizon}")
                        led = study.trade_ledger(
                            zz[common], rates_w[common], horizon_min=horizon,
                            threshold=p.z_threshold, cost_bp_by_bucket=costs,
                            predicted_sign=p.predicted_sign,
                            direction_panel=lvl[common])
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
    out = {"league": league, "skipped": pd.DataFrame(skipped)}
    if skipped:
        _write(ctx, "g4_skipped_variants", out["skipped"])
        print(f"  grid: {len(rows)} variants ran, {len(skipped)} declared variants "
              f"could not run (see g4_skipped_variants.csv)")
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


def run_placebos(ctx, *, space=None, primary=None) -> dict:
    """The five pre-specified placebos plus the reference, each with what firing means.

    Pass ``primary`` and its result becomes the reference row VERBATIM. Recomputing the
    reference here instead makes it match only by coincidence: this function rebuilds the
    signal with ``buckets=list(rates.columns)`` while ``load_context`` built it from the
    contract calendar, and those two sets differ whenever a contract returned no bars. A
    reference that drifts from the primary by even one bucket silently changes every one
    of the five comparisons, since each is read as a distance from it.

    Two reporting notes. Each row carries ``share_long``, because the sign-shuffle
    placebo does not only remove the direction signal -- it also removes the PAID skew
    that makes the real rule 80% one-sided, so the shuffled rule is near-balanced and
    part of any gap between them is position balance rather than lost information. And
    the placebos bootstrap at ``n_boot=300`` against the primary's 2000: means and
    t-statistics are unaffected (they come from the clustered estimator, not the
    bootstrap) but the interval widths are coarser and should not be compared across the
    two.
    """
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
        built = _mask_to_front(
            signals.build_signal(prints, ctx.grid, sig_cfg, buckets=buckets),
            ctx, space)
        z = built["z"].reindex(rates_w.index)
        lvl = built["level"].reindex(rates_w.index)
        if rotate:
            z = study.placebo_rotate_buckets(z)
            lvl = study.placebo_rotate_buckets(lvl)
        tgt = rates_w if target is None else target.reindex(rates_w.index)
        led = study.trade_ledger(z, tgt, horizon_min=p.horizon_min,
                                 threshold=p.z_threshold, cost_bp_by_bucket=costs,
                                 predicted_sign=p.predicted_sign,
                                 direction_panel=lvl)
        out = study.evaluate_trades(led, n_boot=300, seed=ctx.config.stats.seed)
        # Also GROSS. Each arm pays the same ~0.5bp round trip, so net-of-cost lands every
        # placebo near -0.5 regardless of what the manipulation did, and the suite stops
        # discriminating. Gross is where a destroyed signal is visibly destroyed.
        g = study.evaluate_trades(led, value="gross_bp", n_boot=300,
                                  seed=ctx.config.stats.seed)
        out.update({"gross_mean": g["mean"], "gross_t": g["t"],
                    "gross_stars": g["stars"], "gross_hit_rate": g["hit_rate"]})
        return out

    prints = ctx.prints
    reference = None
    if primary is not None:
        res = primary.get("result")
        if res is not None and len(res):
            reference = {k: v for k, v in res.iloc[0].to_dict().items()
                         if k != "segment"}
    # gross for the reference: the primary result carries net only, so this one field is
    # recomputed here. It is cross-checkable against g5_net_table's gross row, which is
    # derived independently from the primary's own ledger.
    ref_gross = {}
    if reference is not None:
        local = evaluate(prints)
        ref_gross = {k: local[k] for k in
                     ("gross_mean", "gross_t", "gross_stars", "gross_hit_rate")}
    rows = [
        {"placebo": "none (reference)", "expect": "the effect, if any",
         **(dict(reference, **ref_gross) if reference is not None else evaluate(prints))},
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
         **evaluate(prints,
                    target=study.pre_arrival_level_panel(rates, p.horizon_min))},
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

    def _measure(name):
        row = net[net["measure"] == name]
        return float(row["mean_bp"].iloc[0]) if len(row) else np.nan

    mean_net, mean_gross = _measure("net of costs"), _measure("gross")
    mean_cost = float(ledger["cost_bp"].mean()) if "cost_bp" in ledger.columns else 0.0
    # The worst case attenuates GROSS and still pays the full round trip. Attenuating
    # the net figure discounts the cost too, which overstates this by 2*cost*(1-a) --
    # 0.4bp at a=0.60 on a 0.5bp round trip, i.e. most of the edge on offer. That is
    # the difference between G5 passing and failing, and it errs toward "economic".
    worst_a = min(ctx.config.stats.attenuation_grid)
    worst_att = stats.attenuate(mean_gross, worst_a, mean_cost)
    out["verdict"] = _verdict(
        "G5", bool(np.isfinite(worst_att) and worst_att > 0),
        f"gross {mean_gross:.4f} - cost {mean_cost:.4f} = net {mean_net:.4f}bp/trade; "
        f"at accuracy a={worst_a:.2f} -> (2a-1)*gross - cost = {worst_att:.4f}bp")
    return out


# --------------------------------------------------------------------------
def run_all(ctx, conn=None, *, run_lockout=False, label_limit=0,
            force_lockout=False, lockout_note="") -> dict:
    """Every gate in order, recording each verdict even when a gate fails.

    ``run_lockout`` is OFF by default and must be turned on deliberately: the
    lockout is evaluated once, the claim is recorded in ``LOCKOUT_USED.json``, and a
    later run under a different specification is refused by ``lockout.claim``.

    NOT the canonical path. ``scripts/run_dealer_ladder_gates.py`` is what produced the
    reported results, and it adds per-stage timing and error isolation this does not: a
    stage that raises here loses every later stage, whereas the runner records the failure
    as an N/A verdict and continues. This exists as a programmatic entry point, and
    ``tests/test_dealer_ladder_artifact_names.py`` pins the two to call the SAME set of
    stages -- because two orchestration paths, only one of which is ever exercised, are a
    standing invitation to drift, and a later caller would then silently get a different
    set of gates than the report was built from.
    """
    ledger_sink = study.TrialLedger()
    res = {"g0": run_g0(ctx, conn, label_limit=label_limit)}
    res["g1"] = run_g1(ctx)
    res["g2"] = run_g2(ctx)
    res["g3"] = run_g3(ctx)
    res["g2_zq"] = run_g2(ctx, space="FED_FUNDS")
    res["g3_zq"] = run_g3(ctx, space="FED_FUNDS")
    res["cross_check"] = run_cross_check_comparison(
        ctx, {"FUTURES": res["g2"], "FED_FUNDS": res["g2_zq"]})
    res["primary_is"] = run_primary(ctx, in_sample=True)
    ledger_sink.record("PRIMARY (in-sample)",
                       {"horizon": ctx.config.primary.horizon_min,
                        "threshold": ctx.config.primary.z_threshold},
                       {"mean": float(res["primary_is"]["result"]["mean"].iloc[0]),
                        "t": float(res["primary_is"]["result"]["t"].iloc[0])})
    res["staleness"] = run_staleness_sensitivity(ctx)
    res["placebos"] = run_placebos(ctx, primary=res["primary_is"])
    res["label_free"] = run_label_free(ctx, ledger_sink=ledger_sink)
    res["conditioning"] = run_conditioning(ctx, res["primary_is"])
    res["grid"] = run_grid(ctx, ledger_sink)
    res["g5"] = run_g5(ctx, res["primary_is"])
    if run_lockout:
        res["primary_lockout"] = run_primary(
            ctx, in_sample=False, force_lockout=force_lockout,
            lockout_note=lockout_note)
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
