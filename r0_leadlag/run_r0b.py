"""R0b — the one authorized re-run of R0, with the Citi minute-curve sign as X.

ONE specification, run ONCE, exactly as pre-registered in r0b_prereg.md, which inherits
r0_prereg.md verbatim except for the single change:

    X's direction sign = sign(rate - Citi minute curve mid) at the print's snapped minute,
    replacing              sign(rate - trailing same-key median).

Everything else is imported from run_r0.py rather than restated (r0b_deviations.md R0b-5):
the same bucket map, the same k = -30..+30, the same bin-of-day fixed effects and five Y
lags, the same day-clustered inference with Newey-West alongside, the same two clocks, the
same five splits, the same Y file. r0_prereg.md's PASS/FAIL/AMBIGUOUS ladder is applied
verbatim on the dissemination clock.

X is built by build_x_r0b.py, which first reproduces R0's OWN X from the same per-print
frame bit-for-bit (max |diff| = 0) before changing the sign.

Usage:  python run_r0b.py --selftest   # preflight, no real data
        python run_r0b.py              # the single real run
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Everything below is R0's, imported so it cannot drift (r0b_deviations.md R0b-5).
from run_r0 import (                                                  # noqa: E402
    DATA, OUT, DECISION_BUCKETS, LAGS, REGCOLS, IPOS, INEG, TSTAT_CRIT,
    build_grid, run_one, lincomb, diffcomb, rolling_scale, shift_global,
    x_series, selftest,
)

X_R0B = r"D:\r0b_cache\x_signed_dv01_curve.parquet"

_L: list[str] = []


def log(m: str = "") -> None:
    print(m, flush=True)
    _L.append(m)


def mass_windows(bb: np.ndarray) -> list[tuple[str, float, float]]:
    """R0's fixed windows over k, so the two runs are directly comparable (R0b-8)."""
    k = np.array(LAGS)
    tot = float(np.abs(bb).sum())
    wins = [("k -30..-18", (k >= -30) & (k <= -18)),
            ("k -17..-2", (k >= -17) & (k <= -2)),
            ("k -1", k == -1),
            ("k 0", k == 0),
            ("k +1", k == 1),
            ("k +2..+17", (k >= 2) & (k <= 17)),
            ("k +18..+30", (k >= 18) & (k <= 30))]
    return [(lab, float(bb[m].sum()), float(np.abs(bb[m]).sum() / tot) if tot else np.nan)
            for lab, m in wins]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    t_start = time.time()

    import run_r0 as _r0
    ok = selftest()
    _L.extend(_r0._LOG_LINES)          # keep R0's gate output inside R0b's own log
    if not ok:
        log("SELFTEST FAILED — refusing to run on real data.")
        return 2
    if "--selftest" in sys.argv:
        return 0

    # ---- load & verify ----------------------------------------------------
    y = pd.read_parquet(os.path.join(DATA, "y_signed_volume.parquet"))
    x = pd.read_parquet(X_R0B)                       # R0b's X: curve sign
    x_r0 = pd.read_parquet(os.path.join(DATA, "x_signed_dv01.parquet"))   # R0's X, for corr
    grid = build_grid(y)

    ysess = pd.read_csv(os.path.join(DATA, "y_sessions.csv"))
    ysess = ysess[ysess["bucket"].isin(DECISION_BUCKETS)]
    mine = grid.groupby("bucket")["sess_key"].nunique()
    theirs = ysess.groupby("bucket").size()
    sess_ok = bool((mine.sort_index() == theirs.sort_index()).all())
    dates_ok = set(zip(grid["bucket"], grid["session_date"])) == \
        set(zip(ysess["bucket"], ysess["session_date"]))

    log("=" * 100)
    log("R0b — lead-lag regression with the CURVE sign.  ONE specification, run ONCE.")
    log("=" * 100)
    log(f"X: {X_R0B}")
    log(f"session reconstruction vs data/y_sessions.csv: counts match [{sess_ok}], "
        f"dates match [{dates_ok}]")
    if not (sess_ok and dates_ok):
        log("  SESSION RECONSTRUCTION CHECK FAILED — refusing to run.")
        return 4

    n_days_tot = grid.loc[grid["keep"], "session_date"].nunique()
    n_bins_tot = int(grid["keep"].sum())
    log("")
    log(f"N_days = {n_days_tot}   (distinct CME session dates in the estimation sample)")
    log(f"N_bins = {n_bins_tot:,}  (of {len(grid):,} on Y's grid; "
        f"{len(grid) - n_bins_tot:,} dropped as session edges)")
    ksub = grid[grid["keep"]]
    for b in DECISION_BUCKETS:
        gb = ksub[ksub["bucket"] == b]
        log(f"  {b:8s} N_days = {gb['session_date'].nunique():3d}   N_bins = {len(gb):7,}")

    log("")
    log("X mass landing on Y's grid (R0b's X; the rest is outside Y's sessions / days):")
    keyset = set(zip(grid["bucket"], grid["minute_utc"]))
    for clock in ["exec", "diss"]:
        xc = x[x["clock"] == clock]
        onk = xc[[(b, m) in keyset for b, m in zip(xc["bucket"], xc["minute_utc"])]]
        log(f"  {clock}: gross DV01 on grid {onk['gross_dv01'].sum()/1e6:10,.0f} / "
            f"{xc['gross_dv01'].sum()/1e6:10,.0f} $mm/bp = "
            f"{onk['gross_dv01'].sum()/xc['gross_dv01'].sum():6.1%}")
    log("")

    # ---- plumbing check on the REAL grid and R0b's REAL X -------------------
    xs_diss = x_series(x, grid, "diss", "all")
    bcode_all = pd.factorize(grid["bucket"])[0]
    xstd_all = xs_diss / rolling_scale(xs_diss, bcode_all)
    rng = np.random.default_rng(2026)
    yfake = -0.25 * shift_global(xstd_all, 7) + rng.standard_normal(len(grid))
    yfake[~np.isfinite(yfake)] = 0.0
    gfake = grid.copy()
    gfake["signed_volume"] = yfake
    rp = run_one(gfake, xs_diss, "pooled", do_nw=False)
    i7, im7 = REGCOLS.index("x+7"), REGCOLS.index("x-7")
    sep = np.sqrt(np.diag(rp["V_cl"]))
    exp7 = -0.25 / float(np.mean(rolling_scale(yfake, bcode_all)))
    log("plumbing check on the REAL grid / R0b's REAL X (Y := -0.25*Xstd_(t-7) + noise):")
    log(f"  beta(k=+7) = {rp['beta'][i7]:+.4f}  predicted {exp7:+.4f}  "
        f"t_cl = {rp['beta'][i7]/sep[i7]:+.2f}")
    log(f"  beta(k=-7) = {rp['beta'][im7]:+.4f}   max|beta| over k != +7 = "
        f"{np.abs(np.delete(rp['beta'][:61], i7)).max():.4f}")
    plumb_ok = (abs(rp["beta"][i7] / exp7 - 1) < 0.10 and abs(rp["beta"][im7]) < 0.03
                and rp["beta"][i7] / sep[i7] < -5)
    log(f"  real-path lag orientation and sign verified [{plumb_ok}]")
    if not plumb_ok:
        log("  PLUMBING CHECK FAILED — refusing to report a verdict.")
        return 3
    log("")

    # ---- the run ----------------------------------------------------------
    scopes = [("pooled", None)] + [("bucket", b) for b in DECISION_BUCKETS]
    splits = ["all", "block", "nonblock", "D2C", "IDB"]
    rows, betas_rows = [], []

    for clock in ["exec", "diss"]:
        for split in splits:
            xs_full = x_series(x, grid, clock, split)
            for scope, b in scopes:
                if scope == "pooled":
                    g2, xs2 = grid, xs_full
                else:
                    m = (grid["bucket"] == b).to_numpy()
                    g2, xs2 = grid[m].reset_index(drop=True), xs_full[m]
                if np.all(xs2 == 0):
                    continue
                r = run_one(g2, xs2, scope, do_nw=(split == "all"))
                sp_, sn_, df_ = lincomb(r, IPOS), lincomb(r, INEG), diffcomb(r)
                b0 = r["beta"][REGCOLS.index("x+0")]
                se0 = float(np.sqrt(r["V_cl"][REGCOLS.index("x+0"), REGCOLS.index("x+0")]))
                bb = r["beta"][:61]
                secl = np.sqrt(np.diag(r["V_cl"]))[:61]
                mass = np.abs(bb).sum()
                centroid = float((np.array(LAGS) * np.abs(bb)).sum() / mass) if mass > 0 else np.nan
                # noise floor: under the global null E[sum |beta_hat_k|] = sum se_k*sqrt(2/pi)
                noise_mass = float((secl * np.sqrt(2.0 / np.pi)).sum())
                rows.append(dict(
                    clock=clock, split=split, scope=scope, bucket=(b or "POOLED"),
                    n_obs=r["n"], n_days=r["n_days"], n_clusters=r["G"],
                    sum_beta_kneg=sn_["val"], se_cluster_kneg=sn_["se_cl"], t_cluster_kneg=sn_["t_cl"],
                    se_nw_kneg=sn_["se_nw"], t_nw_kneg=sn_["t_nw"],
                    sum_beta_kpos=sp_["val"], se_cluster_kpos=sp_["se_cl"], t_cluster_kpos=sp_["t_cl"],
                    se_nw_kpos=sp_["se_nw"], t_nw_kpos=sp_["t_nw"],
                    diff_pos_minus_neg=df_["val"], se_cluster_diff=df_["se_cl"],
                    t_cluster_diff=df_["t_cl"], se_nw_diff=df_["se_nw"], t_nw_diff=df_["t_nw"],
                    beta_k0=float(b0), se_cluster_k0=se0,
                    t_cluster_k0=float(b0 / se0) if se0 > 0 else np.nan,
                    abs_ratio_pos_over_neg=(abs(sp_["val"]) / abs(sn_["val"])
                                            if sn_["val"] != 0 else np.nan),
                    post_print_share=(abs(sp_["val"]) / (abs(sp_["val"]) + abs(sn_["val"]))
                                      if (abs(sp_["val"]) + abs(sn_["val"])) > 0 else np.nan),
                    centroid_absbeta_D2=centroid,
                    abs_beta_mass=float(mass), abs_beta_mass_null=noise_mass,
                ))
                if split == "all":
                    for i, kk in enumerate(LAGS):
                        betas_rows.append(dict(clock=clock, bucket=(b or "POOLED"), k=kk,
                                               beta=float(r["beta"][i]),
                                               se_cluster=float(secl[i]),
                                               se_nw=float(np.sqrt(r["V_nw"][i, i]))))
                log(f"  fitted {clock:4s} {split:8s} {(b or 'POOLED'):8s} "
                    f"n={r['n']:7,} G={r['G']:3d}  "
                    f"S_neg={sn_['val']:+7.4f} (t {sn_['t_cl']:+6.2f})  "
                    f"S_pos={sp_['val']:+7.4f} (t {sp_['t_cl']:+6.2f})")

    tab = pd.DataFrame(rows)
    tab.to_csv(os.path.join(OUT, "r0b_table.csv"), index=False)
    bdf = pd.DataFrame(betas_rows)
    bdf.to_csv(os.path.join(OUT, "r0b_betas.csv"), index=False)

    # ---- chart: R0 and R0b on the SAME axes (task item 4) -------------------
    b_r0 = pd.read_csv(os.path.join(OUT, "r0_betas.csv"))
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 8.8), sharex=True)
    for ax, clock, ttl in zip(axes, ["exec", "diss"],
                              ["Execution clock (#96)",
                               "Dissemination clock (D3) — the decision panel"]):
        d = bdf[(bdf["clock"] == clock) & (bdf["bucket"] == "POOLED")].sort_values("k")
        o = b_r0[(b_r0["clock"] == clock) & (b_r0["bucket"] == "POOLED")].sort_values("k")
        kk, bb, ss = d["k"].to_numpy(), d["beta"].to_numpy(), d["se_cluster"].to_numpy()
        ax.fill_between(kk, bb - 1.96 * ss, bb + 1.96 * ss, alpha=0.22, color="#3b6ea5",
                        label="R0b 95% CI, day-clustered (per-lag bands unreliable, see caveat)")
        ax.plot(o["k"], o["beta"], color="#b0722a", lw=1.3, ls="--", marker="s", ms=2.2,
                label=r"R0  $\beta_k$  (trailing-median sign)")
        ax.plot(kk, bb, color="#14304f", lw=1.7, marker="o", ms=2.6,
                label=r"R0b $\beta_k$  (Citi minute-curve sign)")
        ax.axhline(0, color="#666", lw=0.8)
        ax.axvline(0, color="#c0392b", lw=1.4, ls="--", label="k = 0")
        ax.set_title(f"{ttl}   —   pooled, bucket FE", fontsize=10.5, loc="left")
        ax.set_ylabel(r"$\beta_k$  (std. Y per std. X)")
        ax.grid(alpha=0.25, lw=0.5)
        ax.legend(fontsize=7.5, loc="upper left", framealpha=0.9)
    axes[1].set_xlabel(r"$k$   (lag in minutes;  $k>0$: X precedes Y = post-print hedge window)")
    fig.suptitle("R0b vs R0 — signed futures aggressor volume on signed customer swap DV01\n"
                 r"only X's direction sign changed; pre-registered hedge channel is $\beta_k<0$ at small $k>0$",
                 fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(os.path.join(OUT, "r0b_betas.png"), dpi=160)
    plt.close(fig)

    # ---- verdict: pooled, dissemination clock, all flow ---------------------
    v = tab[(tab["clock"] == "diss") & (tab["scope"] == "pooled") & (tab["split"] == "all")].iloc[0]
    Sp, tp = v["sum_beta_kpos"], v["t_cluster_kpos"]
    Sn, tn = v["sum_beta_kneg"], v["t_cluster_kneg"]
    sig_pos, sig_neg = abs(tp) > TSTAT_CRIT, abs(tn) > TSTAT_CRIT
    ratio_ok, right_sign = abs(Sp) >= 2 * abs(Sn), Sp < 0

    if not sig_pos:
        verdict, why = "FAIL", ("post-print mass is indistinguishable from zero under "
                                "day-clustered standard errors")
    elif not right_sign:
        verdict, why = "FAIL", ("post-print mass is significant but POSITIVE; the prereg "
                                "states a positive beta of the same magnitude is a "
                                "different phenomenon, not a pass")
    elif sig_neg:
        verdict, why = "AMBIGUOUS", "both the pre-print and the post-print sums are significant"
    elif ratio_ok:
        verdict, why = "PASS", ("post-print sum is significantly negative and at least 2x "
                                "the magnitude of the pre-print sum")
    else:
        verdict, why = "FAIL", ("post-print sum is significantly negative but is less than "
                                "2x the magnitude of the pre-print sum")

    log("")
    log("=" * 100)
    log("VERDICT — pooled, DISSEMINATION clock, all flow, day-clustered SEs (r0_prereg.md verbatim)")
    log("=" * 100)
    log(f"  sum(beta_k, k <= -1) = {Sn:+.5f}   SE {v['se_cluster_kneg']:.5f}   "
        f"t = {tn:+.2f}   (NW t = {v['t_nw_kneg']:+.2f})")
    log(f"  sum(beta_k, k >=  1) = {Sp:+.5f}   SE {v['se_cluster_kpos']:.5f}   "
        f"t = {tp:+.2f}   (NW t = {v['t_nw_kpos']:+.2f})")
    log(f"  difference (pos-neg) = {v['diff_pos_minus_neg']:+.5f}  "
        f"t = {v['t_cluster_diff']:+.2f}   (NW t = {v['t_nw_diff']:+.2f})")
    log(f"  beta_(k=0)           = {v['beta_k0']:+.5f}   t = {v['t_cluster_k0']:+.2f}")
    log(f"  |S_pos| / |S_neg|    = {v['abs_ratio_pos_over_neg']:.3f}   (PASS needs >= 2.0)")
    log(f"  post-print share     = {v['post_print_share']:.3f}")
    log(f"  post-print significant [{sig_pos}]  registered sign (<0) [{right_sign}]  "
        f"pre-print significant [{sig_neg}]")
    log("")
    log(f"  VERDICT = {verdict}")
    log(f"  reason  : {why}")

    # ---- the informativeness gate (r0b_prereg.md; operationalised R0b-6) ----
    # rho is 1 by construction for R0b: X IS the curve-signed series. Computed, not
    # assumed, and the division is done as the addendum did it.
    xs_diss_std = xs_diss / rolling_scale(xs_diss, bcode_all)
    rho_r0b = float(np.corrcoef(xs_diss_std, xs_diss_std)[0, 1])
    log("")
    log("=" * 100)
    log("INFORMATIVENESS GATE (r0b_prereg.md): informative iff MDE < |pre-print mass|")
    log("=" * 100)
    log(f"  rho_R0b = corr(X_R0b, X_curve) = {rho_r0b:.6f}   (1 by construction; computed)")
    log(f"  {'scope':8s} {'MDE':>9s} {'|S_neg|':>9s} {'verdict of the gate':>22s}")
    gate_rows = []
    for scope_name in ["POOLED"] + DECISION_BUCKETS:
        rr = tab[(tab["clock"] == "diss") & (tab["split"] == "all") &
                 (tab["bucket"] == scope_name)]
        if rr.empty:
            continue
        rr = rr.iloc[0]
        mde = 1.96 * float(rr["se_cluster_kpos"]) / rho_r0b
        sneg = abs(float(rr["sum_beta_kneg"]))
        informative = mde < sneg
        log(f"  {scope_name:8s} {mde:9.4f} {sneg:9.4f} "
            f"{('INFORMATIVE' if informative else 'UNINFORMATIVE'):>22s}")
        gate_rows.append(dict(scope=scope_name, mde=mde, abs_S_neg=sneg,
                              informative=bool(informative),
                              se_cluster_kpos=float(rr["se_cluster_kpos"]),
                              sum_beta_kpos=float(rr["sum_beta_kpos"]),
                              t_cluster_kpos=float(rr["t_cluster_kpos"]),
                              t_cluster_kneg=float(rr["t_cluster_kneg"])))
    pd.DataFrame(gate_rows).to_csv(os.path.join(OUT, "r0b_gate.csv"), index=False)

    # ---- the k<0 discriminator (R0b-8), R0's windows, both runs -------------
    log("")
    log("=" * 100)
    log("THE k<0 DISCRIMINATOR — R0's own windows, both runs, pooled")
    log("=" * 100)
    for clock in ["exec", "diss"]:
        d = bdf[(bdf["clock"] == clock) & (bdf["bucket"] == "POOLED")].sort_values("k")
        o = b_r0[(b_r0["clock"] == clock) & (b_r0["bucket"] == "POOLED")].sort_values("k")
        mb, mo = mass_windows(d["beta"].to_numpy()), mass_windows(o["beta"].to_numpy())
        log(f"  {clock}:  {'window':12s} {'R0 sum':>10s} {'R0 share':>9s} | "
            f"{'R0b sum':>10s} {'R0b share':>10s}")
        for (lab, s0, m0), (_, s1, m1) in zip(mo, mb):
            log(f"        {lab:12s} {s0:+10.5f} {m0:9.1%} | {s1:+10.5f} {m1:10.1%}")
        kk = d["k"].to_numpy(); bbv = d["beta"].to_numpy()
        neg = kk <= -1
        worst = kk[neg][np.argsort(bbv[neg])[:5]]
        log(f"        most negative lags, R0b: {list(worst)}")
        rr = tab[(tab["clock"] == clock) & (tab["split"] == "all") &
                 (tab["bucket"] == "POOLED")].iloc[0]
        log(f"        sum|beta_k| observed {rr['abs_beta_mass']:.5f} vs its expectation "
            f"under the GLOBAL NULL {rr['abs_beta_mass_null']:.5f} "
            f"({rr['abs_beta_mass_null']/rr['abs_beta_mass']:.0%} of the observed mass is "
            f"what pure noise would produce) — mass shares and the D2 centroid are "
            f"contaminated by that much")
        log(f"        D2 centroid of |beta_k| = {rr['centroid_absbeta_D2']:+.3f} bins")

    # ---- how far the input actually moved (R0b-7) ---------------------------
    log("")
    log("=" * 100)
    log("rho-EQUIVALENT — corr(X_R0, X_R0b) on the regression's own standardised grid")
    log("=" * 100)
    corr_rows = []
    for clock in ["exec", "diss"]:
        a_full = x_series(x_r0, grid, clock, "all")
        b_full = x_series(x, grid, clock, "all")
        a_std = a_full / rolling_scale(a_full, bcode_all)
        b_std = b_full / rolling_scale(b_full, bcode_all)
        c_all = float(np.corrcoef(a_std, b_std)[0, 1])
        log(f"  {clock}: pooled over the whole grid = {c_all:+.3f}")
        corr_rows.append(dict(clock=clock, scope="POOLED", corr=c_all))
        for bb2 in DECISION_BUCKETS:
            m = (grid["bucket"] == bb2).to_numpy()
            c_b = float(np.corrcoef(a_std[m], b_std[m])[0, 1])
            log(f"      {bb2:8s} {c_b:+.3f}")
            corr_rows.append(dict(clock=clock, scope=bb2, corr=c_b))
    pd.DataFrame(corr_rows).to_csv(os.path.join(OUT, "r0b_xcorr.csv"), index=False)

    log("")
    log("per bucket, dissemination clock, all flow:")
    log(f"  {'bucket':8s} {'S_neg':>9s} {'t':>7s} {'S_pos':>9s} {'t':>7s} {'post share':>11s}")
    for bb2 in DECISION_BUCKETS:
        rr = tab[(tab["clock"] == "diss") & (tab["split"] == "all") &
                 (tab["bucket"] == bb2)].iloc[0]
        log(f"  {bb2:8s} {rr['sum_beta_kneg']:+9.4f} {rr['t_cluster_kneg']:+7.2f} "
            f"{rr['sum_beta_kpos']:+9.4f} {rr['t_cluster_kpos']:+7.2f} "
            f"{rr['post_print_share']:11.3f}")

    log("")
    log(f"wrote {os.path.join(OUT, 'r0b_betas.png')}")
    log(f"wrote {os.path.join(OUT, 'r0b_table.csv')}   ({len(tab)} rows)")
    log(f"wrote {os.path.join(OUT, 'r0b_betas.csv')}, r0b_gate.csv, r0b_xcorr.csv")
    log(f"elapsed {time.time() - t_start:.1f}s")

    with open(os.path.join(OUT, "r0b_run.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(_L) + "\n")
    with open(os.path.join(OUT, "r0b_verdict.txt"), "w", encoding="utf-8") as f:
        f.write(verdict + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
