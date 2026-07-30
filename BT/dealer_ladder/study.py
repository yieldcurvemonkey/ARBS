"""Study machinery for gates G2-G5.

Everything here takes panels in and returns frames out — no DB, no network — so
each gate is testable on synthetic data with a planted answer, which is how the
tests verify that a gate can actually detect what it claims to detect.

Gate ordering is not cosmetic. G2 (does the ladder lead measurable futures flow?)
runs BEFORE any price test, because if nothing leads the flow then a price result
cannot be attributed to a hedging channel and has to be relabelled. G3 asks
whether a price effect is just the swap-futures basis wearing a costume. Only then
does G4 evaluate the one pre-registered trading rule, and G5 asks what survives
execution.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from BT.dealer_ladder import hy, stats


# --------------------------------------------------------------------------
# shared: align a signal panel to a target panel as a long frame
# --------------------------------------------------------------------------
def align_long(signal: pd.DataFrame, target: pd.DataFrame, *, extra=None) -> pd.DataFrame:
    """Long frame of (ts, bucket, signal, target[, extras]) on the shared support.

    Inner-joins on BOTH axes and drops rows where either side is missing, so a
    bucket present in the ladder but absent from the futures data (or the reverse)
    silently contributes nothing rather than producing NaN-padded rows that later
    inflate a denominator.
    """
    cols = [c for c in signal.columns if c in target.columns]
    idx = signal.index.intersection(target.index)
    if not len(cols) or not len(idx):
        return pd.DataFrame(columns=["ts", "bucket", "signal", "target"])
    s = signal.loc[idx, cols].stack(future_stack=True).rename("signal")
    y = target.loc[idx, cols].stack(future_stack=True).rename("target")
    out = pd.concat([s, y], axis=1).dropna()
    out.index.names = ["ts", "bucket"]
    out = out.reset_index()
    for name, panel in (extra or {}).items():
        e = panel.reindex(index=idx, columns=cols).stack(future_stack=True).rename(name)
        e.index.names = ["ts", "bucket"]
        out = out.merge(e.reset_index(), on=["ts", "bucket"], how="left")
    return out


def blocks_of(frame: pd.DataFrame, ts_col="ts") -> np.ndarray:
    return stats.day_codes(frame[ts_col])


# --------------------------------------------------------------------------
# G2 — mechanism ordering
# --------------------------------------------------------------------------
def hy_lead_lag_by_day(x_panel: pd.DataFrame, y_panel: pd.DataFrame, *,
                       lags=hy.DEFAULT_LAGS_MINUTES) -> pd.DataFrame:
    """Per (session, bucket) Hayashi-Yoshida lead-lag of X against Y.

    **PASS LEVELS, NOT INCREMENTS.** ``hy.hy_corr`` differences both inputs itself
    (``dx = np.diff(xv)``), because the Hayashi-Yoshida estimator is defined on
    increments living on the intervals between observations. So the research plan's
    requirement that the ladder enter as INCREMENTS and never as EWMA levels is
    satisfied by handing it the LEVEL: the differencing happens inside. Handing it
    an already-differenced series would silently compute second differences and the
    statistic would measure nothing meaningful. Likewise the futures side must be a
    CUMULATIVE signed-volume series so that its internal difference is the per-bar
    signed volume.

    X is the ladder, Y the futures side. Positive LLS means X leads Y — see ``hy``'s
    sign convention, which was pinned numerically rather than argued.

    Returns one row per (day, bucket) with the LLS, the peak lag, and the signed
    correlation AT that peak. Reporting both matters: LLS measures TIMING and is
    sign-blind about direction, so a large positive LLS with a negative peak
    correlation means the ladder leads futures in the OPPOSITE direction to the
    hypothesis — which would be a real finding, not a pass.
    """
    rows = []
    cols = [c for c in x_panel.columns if c in y_panel.columns]
    if not cols:
        return pd.DataFrame(columns=["day", "bucket", "lls", "peak_lag_min",
                                     "peak_rho", "n_x", "n_y"])
    xd = stats.day_codes(x_panel.index)
    yd = stats.day_codes(y_panel.index)
    for day in np.unique(xd):
        xs, ys = x_panel[xd == day], y_panel[yd == day]
        if xs.empty or ys.empty:
            continue
        for bucket in cols:
            x = xs[bucket].dropna()
            y = ys[bucket].dropna()
            if len(x) < 3 or len(y) < 3:
                continue
            curve = hy.hy_curve(x.index, x.to_numpy(), y.index, y.to_numpy(), lags=lags)
            finite = {l: r for l, r in curve.items() if np.isfinite(r)}
            peak_lag = max(finite, key=lambda l: abs(finite[l])) if finite else np.nan
            rows.append({
                "day": int(day), "bucket": bucket,
                "lls": hy.lls(curve),
                "peak_lag_min": peak_lag,
                "peak_rho": finite.get(peak_lag, np.nan),
                "n_x": len(x), "n_y": len(y),
            })
    return pd.DataFrame(rows)


def summarise_lead_lag(ll: pd.DataFrame, value="lls") -> dict:
    """Day-blocked verdict on a lead-lag table, with sign consistency."""
    if ll.empty:
        return {"n": 0, "mean": np.nan, "t": np.nan, "stars": "",
                "share_agreeing": np.nan, "p_sign": np.nan}
    res = stats.cluster_mean_t(ll[value].to_numpy(), ll["day"].to_numpy())
    sc = stats.sign_consistency(ll[value].to_numpy(), ll["day"].to_numpy())
    return {**res, "stars": stats.stars(res["t"]),
            "share_agreeing": sc["share_agreeing"], "p_sign": sc["p_sign"]}


def flow_response_event_study(increments: pd.DataFrame, signed_flow: pd.DataFrame, *,
                              horizons_min=(5, 15, 30, 60), quantile=0.9) -> pd.DataFrame:
    """After a LARGE signed ladder innovation, does signed futures flow follow?

    Events are innovations in the top ``quantile`` by absolute size, measured per
    bucket so a thinly-traded contract is not silently excluded by a pooled
    threshold. The response is cumulative signed flow over each horizon, SIGNED BY
    THE INNOVATION so that a positive mean means "flow followed the ladder".

    The hypothesised hedge is a SALE when the ladder is positive (dealer long
    futures-equivalent must sell), so the mechanism predicts flow OPPOSITE in sign
    to the innovation. The sign convention is therefore stated explicitly in the
    returned ``expected_sign`` column rather than left to the reader.
    """
    rows = []
    cols = [c for c in increments.columns if c in signed_flow.columns]
    for bucket in cols:
        inc = increments[bucket].dropna()
        if inc.empty:
            continue
        thresh = inc.abs().quantile(quantile)
        events = inc[inc.abs() >= thresh]
        flow = signed_flow[bucket]
        for ts, size in events.items():
            direction = np.sign(size)
            for h in horizons_min:
                # STRICTLY forward. A label-inclusive slice from ts would include the
                # bar labelled ts, whose sign comes from the price change INTO ts and
                # whose volume is the minute ending at ts -- both predate the
                # innovation. G2 exists to establish ordering, so a window reaching
                # backward cannot support it, and that is exactly the direction of
                # contamination that manufactures a spurious lead.
                window = flow.loc[ts + pd.Timedelta(microseconds=1):
                                  ts + pd.Timedelta(minutes=h)]
                if window.empty:
                    continue
                rows.append({
                    "ts": ts, "bucket": bucket, "horizon_min": h,
                    "innovation": float(size),
                    "flow_signed_by_innovation": float(direction * window.sum()),
                    "expected_sign": -1,   # hedging predicts flow AGAINST the ladder
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# G3 — circularity: does the ladder add anything over basis/curve/liquidity?
# --------------------------------------------------------------------------
def horse_race(long_frame: pd.DataFrame, *, signal_col="signal", target_col="target",
               controls=()) -> pd.DataFrame:
    """OLS of target on [1, signal, *controls] with day-clustered inference.

    Reports the signal's coefficient both alone and beside the controls. The
    interesting number is not significance in isolation but whether the
    coefficient SURVIVES: if it collapses once the swap-futures basis and curve
    shape are in the regression, the effect lives in the basis and the thesis is a
    different one.

    Deliberately linear and small. A flexible learner here would make the
    "does it survive controls" question unanswerable.

    Every row carries ``design_rank``, ``design_cols``, ``design_cond`` and
    ``rank_deficient``. A survival claim made over a rank-deficient design is not worth
    making, and the collinearity that would cause it is plausible here rather than
    hypothetical: ``basis_bp`` and ``abs_basis_bp`` coincide whenever the basis rarely
    changes sign, and the independent-basis pair has the same structure.
    """
    df = long_frame.dropna(subset=[signal_col, target_col]).copy()
    if df.empty:
        return pd.DataFrame(columns=["spec", "term", "coef", "se", "t", "n"])
    # BOTH specs are fitted on the SAME complete-case rows. Otherwise "signal only"
    # gets every row while "signal + controls" silently drops rows where any control
    # is NaN, and the two t-statistics are then not comparable: a coefficient
    # unchanged in magnitude but fitted on 60% of the rows loses ~1.3x of its t, so
    # G3 would report "does not survive" from sample shrinkage alone. Structural NaN
    # is real here -- a deferred contract's minute coverage is far below the front
    # six's, and an expired contract's column is NaN for the tail of the window.
    all_terms = [c for c in [signal_col, *controls] if c in df.columns]
    common = df.dropna(subset=all_terms)
    out = []
    for spec, terms in (("signal only", [signal_col]),
                        ("signal + controls", [signal_col, *controls])):
        terms = [t for t in terms if t in df.columns]
        sub = common
        if sub.empty or len(terms) == 0:
            continue
        b = stats.day_codes(sub["ts"])
        X = np.column_stack([np.ones(len(sub))] + [sub[t].to_numpy(float) for t in terms])
        y = sub[target_col].to_numpy(float)
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        # Rank and conditioning are REPORTED, not assumed. `pinv` below silently
        # absorbs a rank-deficient design and returns a minimum-norm solution with
        # standard errors that mean very little -- and this control block is exactly
        # where that can happen, since basis_bp and abs_basis_bp are near-collinear
        # whenever the basis rarely changes sign, as are the independent-basis pair.
        # "The signal survives the controls" is not a claim worth making over a design
        # whose rank is lower than its column count.
        rank = int(np.linalg.matrix_rank(X))
        cond = float(np.linalg.cond(X)) if X.shape[1] else float("nan")
        # cluster-robust sandwich, clustering on day
        XtX_inv = np.linalg.pinv(X.T @ X)
        meat = np.zeros((X.shape[1], X.shape[1]))
        for g in np.unique(b):
            Xg, ug = X[b == g], resid[b == g]
            s = Xg.T @ ug
            meat += np.outer(s, s)
        ng = len(np.unique(b))
        scale = ng / max(ng - 1, 1)
        cov = scale * XtX_inv @ meat @ XtX_inv
        se = np.sqrt(np.clip(np.diag(cov), 0.0, None))
        for i, name in enumerate(["const"] + terms):
            t = beta[i] / se[i] if se[i] > 0 else np.nan
            out.append({"spec": spec, "term": name, "coef": float(beta[i]),
                        "se": float(se[i]), "t": float(t) if t == t else np.nan,
                        "n": int(len(sub)), "n_blocks": int(ng),
                        "design_rank": rank, "design_cols": int(X.shape[1]),
                        "design_cond": cond,
                        "rank_deficient": bool(rank < X.shape[1])})
    return pd.DataFrame(out)


def leave_one_bucket_out(long_frame: pd.DataFrame, statistic) -> pd.DataFrame:
    """Recompute ``statistic`` with each bucket held out, one at a time.

    A result that depends on a single contract is a single-contract story. This is
    the cheap version of the audit's leave-one-contract-out requirement.
    """
    rows = []
    for bucket in sorted(long_frame["bucket"].unique()):
        sub = long_frame[long_frame["bucket"] != bucket]
        res = statistic(sub)
        rows.append({"held_out": bucket, **res})
    rows.append({"held_out": "<none>", **statistic(long_frame)})
    return pd.DataFrame(rows)


def residualise(long_frame: pd.DataFrame, signal_col="signal", controls=()) -> pd.Series:
    """Signal orthogonalised against ``controls`` — the "residual flow" variant.

    Fitted on the WHOLE frame, which is fine for a diagnostic (it asks whether any
    independent variation exists at all) but would be look-ahead in a trading rule.
    Never feed the output of this into G4.
    """
    terms = [c for c in controls if c in long_frame.columns]
    if not terms:
        return long_frame[signal_col]
    sub = long_frame.dropna(subset=[signal_col, *terms])
    X = np.column_stack([np.ones(len(sub))] + [sub[t].to_numpy(float) for t in terms])
    y = sub[signal_col].to_numpy(float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = pd.Series(y - X @ beta, index=sub.index)
    return resid.reindex(long_frame.index)


# --------------------------------------------------------------------------
# G4 — the trading rule
# --------------------------------------------------------------------------
def trade_ledger(z_panel: pd.DataFrame, rate_bp: pd.DataFrame, *, horizon_min,
                 threshold, cost_bp_by_bucket, predicted_sign=+1,
                 stale_min=None, max_stale_min=None, direction_panel=None) -> pd.DataFrame:
    """Non-overlapping trades from a |z| >= threshold rule. One row per trade.

    Rules, all pre-registered:
      - a trigger while that bucket already has a position open is IGNORED, so
        trades never overlap within a bucket and the day-blocked standard error is
        not inflated by mechanical serial correlation;
      - exit is exactly ``horizon_min`` later, and a trade whose exit price is
        unavailable is dropped rather than closed at a stale or invented price;
      - ``position`` is in RATE space: +1 profits when the rate rises.

    TRIGGER AND DIRECTION ARE SEPARATE, and that separation matters. The locked spec
    triggers on ``|z| >= threshold`` but predicts the sign of the rate change from the
    LADDER LEVEL: a dealer long futures-equivalent (positive ladder) must SELL futures,
    pushing price down and rate up. ``z`` is the level minus its TRAILING MEAN, and
    that mean is systematically negative because 68-82% of prints are PAID and PAID
    means negative delta_dv01 -- so ``sign(z)`` and ``sign(level)`` disagree over the
    whole region ``mu < level < 0``, measured at ~35% of triggers on a realistically
    skewed bucket. Using ``sign(z)`` would take the position OPPOSITE the hypothesis on
    a third of trades and could report a genuine effect as negative.

    Pass ``direction_panel`` (the ladder LEVEL) to sign from it; the fallback to
    ``sign(z)`` exists only for callers with no level to hand, and the returned frame
    always records both so the disagreement can never be silent.
    """
    rows = []
    cols = [c for c in z_panel.columns if c in rate_bp.columns]
    for bucket in cols:
        z = z_panel[bucket]
        r = rate_bp[bucket]
        cost = float(cost_bp_by_bucket.get(bucket, 0.0))
        open_until = None
        for ts, zv in z.items():
            if not np.isfinite(zv) or abs(zv) < threshold:
                continue
            if open_until is not None and ts < open_until:
                continue
            exit_ts = ts + pd.Timedelta(minutes=horizon_min)
            if ts not in r.index or exit_ts not in r.index:
                continue
            entry, exit_ = r.loc[ts], r.loc[exit_ts]
            if not (np.isfinite(entry) and np.isfinite(exit_)):
                continue
            if max_stale_min is not None and stale_min is not None \
                    and bucket in stale_min.columns:
                s_in = stale_min[bucket].get(ts, np.nan)
                s_out = stale_min[bucket].get(exit_ts, np.nan)
                # BOTH ends: a fresh entry against a 25-minute-stale exit measures a
                # 35-minute move and calls it a 60-minute one, and the reverse pairing
                # measures 85. Either way the realised holding period stops being the
                # pre-registered horizon.
                if ((np.isfinite(s_in) and s_in > max_stale_min)
                        or (np.isfinite(s_out) and s_out > max_stale_min)):
                    continue
            level = np.nan
            if direction_panel is not None and bucket in direction_panel.columns:
                try:
                    level = float(direction_panel.at[ts, bucket])
                except Exception:
                    level = np.nan
            basis = level if np.isfinite(level) else zv
            if not np.isfinite(basis) or basis == 0.0:
                continue
            pos = int(predicted_sign * np.sign(basis))
            gross = pos * float(exit_ - entry)
            stale_entry = stale_exit = np.nan
            if stale_min is not None and bucket in stale_min.columns:
                try:
                    stale_entry = float(stale_min.at[ts, bucket])
                except Exception:
                    stale_entry = np.nan
                try:
                    stale_exit = float(stale_min.at[exit_ts, bucket])
                except Exception:
                    stale_exit = np.nan
            rows.append({
                "ts": ts, "exit_ts": exit_ts, "bucket": bucket, "z": float(zv),
                "ladder_level": level, "signed_from": ("level" if np.isfinite(level)
                                                       else "zscore"),
                "sign_disagrees": bool(np.isfinite(level)
                                       and np.sign(level) != np.sign(zv)),
                "entry_stale_min": stale_entry, "exit_stale_min": stale_exit,
                "position": pos, "entry_bp": float(entry), "exit_bp": float(exit_),
                "gross_bp": gross, "cost_bp": cost, "net_bp": gross - cost,
            })
            open_until = exit_ts
    return pd.DataFrame(rows)


def evaluate_trades(ledger: pd.DataFrame, *, value="net_bp", n_boot=2000, seed=0,
                    alpha=0.05) -> dict:
    """Day-blocked verdict on a trade ledger."""
    if ledger.empty:
        return {"n": 0, "mean": np.nan, "se": np.nan, "t": np.nan, "stars": "",
                "lo": np.nan, "hi": np.nan, "hit_rate": np.nan,
                "share_agreeing": np.nan, "p_sign": np.nan, "n_blocks": 0}
    b = blocks_of(ledger)
    ci = stats.day_blocked_ci(ledger[value].to_numpy(), b, n_boot=n_boot,
                              alpha=alpha, seed=seed)
    sc = stats.sign_consistency(ledger[value].to_numpy(), b)
    share_long = (float((ledger["position"] > 0).mean())
                  if "position" in ledger.columns else float("nan"))
    return {**ci, "stars": stats.stars(ci["t"]),
            "hit_rate": float((ledger[value] > 0).mean()),
            # How ONE-SIDED the rule was. 84% of prints are PAID, PAID means negative
            # delta_dv01, and the position is signed from the ladder LEVEL -- so the
            # rule can be overwhelmingly directional without that being visible in the
            # mean or the t. Measured on Jan-Feb: 80% of triggers take the short-rates
            # side, rising above 95% on the deferred contracts. A reader has to see
            # this to know whether they are looking at a signal or at a bet on drift.
            "share_long": share_long,
            "share_agreeing": sc["share_agreeing"], "p_sign": sc["p_sign"]}


def constant_position_benchmark(ledger: pd.DataFrame, n_boot=2000, seed=0) -> pd.DataFrame:
    """What ALWAYS-long and ALWAYS-short would have earned over the same trades.

    The comparison that makes a one-sided rule interpretable. The ladder level is
    negative in 94.6% of (minute, bucket) cells, because 84% of prints are PAID and PAID
    means negative ``delta_dv01`` -- so a rule signed from the level takes the
    short-rates side on ~80% of triggers. At that imbalance the strategy's return is
    substantially a bet on the window's rate drift, and "net X bp with t = Y" cannot be
    read as evidence about the LADDER unless it is set against what the same entries and
    exits would have paid with the sign held constant.

    Uses the ledger's own entry/exit prices and costs, so the only thing that varies is
    the position. If the rule does not beat the better of the two constants, the ladder
    is contributing nothing beyond direction.
    """
    cols = ["variant", "mean_bp", "t", "stars", "n", "n_blocks", "share_long"]
    if ledger.empty or not {"entry_bp", "exit_bp"} <= set(ledger.columns):
        return pd.DataFrame(columns=cols)
    b = blocks_of(ledger)
    move = ledger["exit_bp"].to_numpy(float) - ledger["entry_bp"].to_numpy(float)
    cost = (ledger["cost_bp"].to_numpy(float) if "cost_bp" in ledger.columns
            else np.zeros(len(ledger)))
    rows = []
    variants = [("as traded", ledger["position"].to_numpy(float)
                 if "position" in ledger.columns else np.ones(len(ledger))),
                ("always long rates (+1)", np.ones(len(ledger))),
                ("always short rates (-1)", -np.ones(len(ledger)))]
    for name, pos in variants:
        net = pos * move - cost
        r = stats.day_blocked_ci(net, b, n_boot=n_boot, seed=seed)
        rows.append({"variant": name, "mean_bp": r["mean"], "t": r["t"],
                     "stars": stats.stars(r["t"]), "n": r["n"],
                     "n_blocks": r["n_blocks"],
                     "share_long": float((pos > 0).mean())})
    return pd.DataFrame(rows)


def cost_bp_map(buckets, cost_cfg, near_expiry: dict, root_by_bucket: dict) -> dict:
    """{bucket: round-trip cost in bp} from the front/back tick split."""
    out = {}
    for b in buckets:
        root = root_by_bucket.get(b)
        if root is None:
            continue
        out[b] = cost_cfg.round_trip_bp(root, near_expiry=bool(near_expiry.get(b, False)))
    return out


# --------------------------------------------------------------------------
# placebos
# --------------------------------------------------------------------------
def placebo_sign_shuffle(prints: pd.DataFrame, seed=0) -> pd.DataFrame:
    """Permute the SIGN of delta_dv01 within each session, preserving magnitudes.

    Kills direction while leaving print intensity, timing and size untouched. If
    the effect survives this, it was never about direction.
    """
    rng = np.random.default_rng(seed)
    out = prints.copy()
    day = pd.to_datetime(out["visibility_timestamp"]).dt.tz_convert(
        "America/New_York").dt.date if pd.to_datetime(
        out["visibility_timestamp"]).dt.tz is not None else pd.to_datetime(
        out["visibility_timestamp"]).dt.date
    vals = out["delta_dv01"].astype(float).to_numpy()
    signs = np.sign(vals)

    # Both loops below are ordered explicitly, because a seeded RNG consumed POSITIONALLY is
    # only reproducible if the positions are. Iterating `pd.unique(day)` spends the seed in
    # whatever order the rows happened to arrive, and permuting `signs[m]` in frame order
    # lands those draws on whichever prints happened to sit there. Two runs over identical
    # data then disagree: measured 2026-07-30, this arm moved -0.4476 (n=1636) to -0.4644
    # (n=1631) between runs of the same config while every other placebo -- all
    # order-independent transforms -- reproduced bit-identically.
    #
    # `data._PRINTS_SQL` now carries a total ORDER BY, which fixes the usual path. This is
    # the second line of defence: a caller that re-orders, filters or concatenates the frame
    # must not silently change what the placebo means.
    key = (out["unit_key"].astype(str) + "|" + out["bucket_key"].astype(str)).to_numpy()
    for d in sorted(pd.unique(day)):
        idx = np.flatnonzero((day == d).to_numpy())
        if idx.size < 2:
            continue
        stable = idx[np.argsort(key[idx], kind="stable")]
        signs[stable] = rng.permutation(signs[stable])

    out["delta_dv01"] = np.abs(vals) * signs
    return out


def placebo_shift_arrival(prints: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Shift every visibility timestamp by ``minutes`` (positive = later)."""
    out = prints.copy()
    out["visibility_timestamp"] = (pd.to_datetime(out["visibility_timestamp"])
                                   + pd.Timedelta(minutes=minutes))
    return out


def placebo_live_parity(prints: pd.DataFrame, floor_min=15) -> pd.DataFrame:
    """Floor every visibility at execution + ``floor_min`` — production's delay.

    A FLOOR, not a shift: a print already delayed 30 or 60 minutes by its legal
    class keeps its later time.
    """
    out = prints.copy()
    exec_ts = pd.to_datetime(out["execution_timestamp"])
    vis = pd.to_datetime(out["visibility_timestamp"])
    out["visibility_timestamp"] = np.maximum(
        vis.to_numpy(), (exec_ts + pd.Timedelta(minutes=floor_min)).to_numpy())
    return out


def placebo_rotate_buckets(panel: pd.DataFrame, shift=1) -> pd.DataFrame:
    """Map each bucket's signal onto ANOTHER bucket's returns.

    Tests whether the effect is bucket-specific or generic curve continuation. A
    rotation rather than a shuffle so the deferred/front structure is preserved.
    """
    cols = list(panel.columns)
    if len(cols) < 2:
        return panel.copy()
    # bucket i receives bucket (i+shift)'s series, so a join against bucket i's
    # own returns is a deliberately mismatched pair
    rotated = {cols[i]: panel[cols[(i + shift) % len(cols)]].to_numpy()
               for i in range(len(cols))}
    return pd.DataFrame(rotated, index=panel.index)[cols]


def pre_arrival_target(rate_bp: pd.DataFrame, horizon_min: int) -> pd.DataFrame:
    """The realised CHANGE over the horizon BEFORE the decision instant.

    Returns a CHANGE, not a level. Do NOT hand this to ``trade_ledger``, which treats
    its target as a LEVEL panel and differences it itself -- doing so computes
    ``r(t+h) - 2r(t) + r(t-h)``, a second difference, which is the forward statistic
    MINUS the backward one and inverts the placebo's reading in both directions. Use
    ``pre_arrival_level_panel`` for the ledger path; this form is for direct
    inspection.
    """
    return rate_bp - rate_bp.shift(freq=pd.Timedelta(minutes=horizon_min)).reindex(
        rate_bp.index)


def pre_arrival_level_panel(rate_bp: pd.DataFrame, horizon_min: int) -> pd.DataFrame:
    """A LEVEL panel whose ledger exit-minus-entry is the PRE-arrival change.

    ``trade_ledger`` computes ``target[t + h] - target[t]``. Feeding it the rate panel
    shifted FORWARD by h makes that ``r(t) - r(t - h)`` -- the backward window -- while
    keeping the ledger's arithmetic untouched. This is the placebo whose entire job is
    to detect look-ahead, so it has to measure the thing it claims to.
    """
    return rate_bp.shift(freq=pd.Timedelta(minutes=horizon_min)).reindex(rate_bp.index)


# --------------------------------------------------------------------------
# G5 — economics and capacity
# --------------------------------------------------------------------------
def capacity_curve(ledger: pd.DataFrame, volumes: pd.DataFrame, *,
                   participation=(0.01, 0.05, 0.10), dv01_per_contract=25.0) -> pd.DataFrame:
    """Portfolio DV01 reachable at each participation rate, per the audit's formula.

    Capacity is a DEPTH question and this repo has no historical depth or
    top-of-book data — only minute volume. So this is explicitly a VOLUME-based
    SENSITIVITY, not a capacity claim: it answers "if you could take p of traded
    volume in the minutes you traded, how much DV01 is that", which is an upper
    bound on what depth would allow. Labelled as such in the output.

    The holding window is ``(entry, exit]`` — STRICTLY after entry. The volume panel is
    right-closed, so the bar stamped at the entry minute covers the interval *ending*
    there and was therefore traded before the position existed. Including it, as the
    first version did, inflates a 60-minute holding window by one bar in twelve: ~8% of
    the headline capacity number, in the optimistic direction.

    Trades whose bucket is missing from the volume panel are COUNTED and reported rather
    than dropped, because a median taken over a silently reduced subset is not the
    statistic it claims to be.
    """
    cols = ["participation", "median_dv01_per_trade", "total_dv01",
            "n_trades_priced", "n_trades_dropped", "basis"]
    if ledger.empty or volumes.empty:
        return pd.DataFrame(columns=cols)
    per_trade, dropped = [], 0
    for _, tr in ledger.iterrows():
        v = volumes.get(tr["bucket"])
        if v is None:
            dropped += 1
            continue
        idx = pd.DatetimeIndex(v.index)
        window = v[(idx > tr["ts"]) & (idx <= tr["exit_ts"])]
        per_trade.append(float(window.sum()) if len(window) else 0.0)
    per_trade = np.asarray(per_trade, dtype=float)
    if per_trade.size == 0:
        return pd.DataFrame(columns=cols)

    rows = []
    for p in participation:
        lots = per_trade * p
        rows.append({
            "participation": p,
            "median_dv01_per_trade": float(np.nanmedian(lots) * dv01_per_contract),
            "total_dv01": float(np.nansum(lots) * dv01_per_contract),
            "n_trades_priced": int(per_trade.size),
            "n_trades_dropped": int(dropped),
            "basis": "traded-volume sensitivity over (entry, exit], NOT measured depth",
        })
    return pd.DataFrame(rows)


def net_of_costs_table(ledger: pd.DataFrame, attenuation=(0.6, 0.7, 0.8)) -> pd.DataFrame:
    """Gross, net, and attenuation-scaled net per bp, with day-blocked t.

    The attenuated rows scale the GROSS edge and subtract the full cost, because the
    round trip is paid whether or not the direction label was right. Attenuating the
    net number would discount the cost too, overstating each row by
    ``2 * cost * (1 - a)`` — see ``stats.attenuate``.
    """
    if ledger.empty:
        return pd.DataFrame(columns=["measure", "mean_bp", "t", "stars", "n"])
    b = blocks_of(ledger)
    rows, mean_by = [], {}
    for label, col in (("gross", "gross_bp"), ("net of costs", "net_bp")):
        r = stats.cluster_mean_t(ledger[col].to_numpy(), b)
        mean_by[col] = r["mean"]
        rows.append({"measure": label, "mean_bp": r["mean"], "t": r["t"],
                     "stars": stats.stars(r["t"]), "n": r["n"]})
    mean_cost = float(ledger["cost_bp"].mean()) if "cost_bp" in ledger.columns else 0.0
    rows.append({"measure": "round-trip cost", "mean_bp": -mean_cost,
                 "t": np.nan, "stars": "", "n": rows[-1]["n"]})
    for a in attenuation:
        rows.append({"measure": f"net, accuracy a={a:.2f}",
                     "mean_bp": stats.attenuate(mean_by["gross_bp"], a, mean_cost),
                     "t": np.nan, "stars": "", "n": rows[0]["n"]})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# trial ledger
# --------------------------------------------------------------------------
class TrialLedger:
    """Append-only record of every configuration evaluated, in order.

    The audit asks for this by name. Its point is that a family-wise correction is
    only honest if the family is the one actually searched, including manual
    one-offs and discarded variants — so this records unconditionally, and nothing
    ever removes a row.
    """

    def __init__(self):
        self._rows = []

    def record(self, label, config: dict, result: dict, *, note="") -> None:
        self._rows.append({"trial": len(self._rows) + 1, "label": label,
                           **{f"cfg_{k}": v for k, v in config.items()},
                           **{f"res_{k}": v for k, v in result.items()},
                           "note": note})

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self._rows)

    def __len__(self):
        return len(self._rows)
