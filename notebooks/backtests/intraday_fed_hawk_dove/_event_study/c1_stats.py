"""Chart-1 statistics: pre-slope, event jump, how much lands when, drift, reversion.

Every number is day-clustered.  Paired statistics are computed on the events that
have BOTH offsets priced, so a numerator and a denominator never come from
different event sets.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

import numpy as np
import pandas as pd

from c_common import (HERE, OFFSETS, PRE_OFFSETS, arm_paths, cluster_bootstrap_ratio,
                      cluster_mean_se, cluster_ols, load_rank3, signed_path, wide)

SHARE_AT = [5, 15, 30, 60]
ANCHOR = -60


def jnum(x):
    if isinstance(x, (np.floating, np.integer)):
        return float(x)
    return x


def paired(piv, meta, a, b):
    """Per-event (value at b) - (value at a) on events priced at both."""
    s = meta["stance_sign"].to_numpy()
    va, vb = piv[a].to_numpy() * s, piv[b].to_numpy() * s
    ok = np.isfinite(va) & np.isfinite(vb)
    return vb[ok] - va[ok], meta["date"].to_numpy()[ok], int(ok.sum())


def pre_slope(piv, meta, drop_anchor):
    """Pooled OLS of the signed path on minutes-from-speech over [-120, -5]."""
    offs = [o for o in PRE_OFFSETS if not (drop_anchor and o == ANCHOR)]
    s = meta["stance_sign"].to_numpy()
    ys, xs, cs = [], [], []
    for o in offs:
        v = piv[o].to_numpy() * s
        ok = np.isfinite(v)
        ys.append(v[ok]); xs.append(np.full(ok.sum(), o, float))
        cs.append(meta["date"].to_numpy()[ok])
    y = np.concatenate(ys); x = np.concatenate(xs); c = np.concatenate(cs)
    X = np.column_stack([np.ones_like(x), x])
    r = cluster_ols(y, X, c, names=["const", "slope"])
    return dict(slope_bp_per_min=r["slope"]["coef"],
                slope_bp_per_hour=r["slope"]["coef"] * 60.0,
                se_bp_per_hour=r["slope"]["se"] * 60.0,
                t=r["slope"]["t"], n_rows=r["n"], n_days=r["n_clusters"],
                offsets_used=offs)


def book_stats(piv, meta, tag, do_bootstrap=True):
    out = {"tag": tag}
    n_hawk = int((meta["stance_sign"] == 1).sum())
    n_dove = int((meta["stance_sign"] == -1).sum())
    out["n_events"] = int(len(meta))
    out["n_hawk"] = n_hawk
    out["n_dove"] = n_dove
    out["n_days"] = int(meta["date"].nunique())
    out["years"] = {str(k): int(v) for k, v in
                    meta["speech_ts"].dt.year.value_counts().sort_index().items()}

    # ---- paths
    sp = signed_path(piv, meta)
    out["signed_path"] = {str(o): dict(mean=jnum(sp.loc[o, "mean"]), se=jnum(sp.loc[o, "se"]),
                                       t=jnum(sp.loc[o, "t"]), n=int(sp.loc[o, "n"]))
                          for o in OFFSETS}
    ha, da = arm_paths(piv, meta, 1), arm_paths(piv, meta, -1)
    out["hawk_path"] = {str(o): dict(mean=jnum(ha.loc[o, "mean"]), se=jnum(ha.loc[o, "se"]),
                                     n=int(ha.loc[o, "n"])) for o in OFFSETS}
    out["dove_path"] = {str(o): dict(mean=jnum(da.loc[o, "mean"]), se=jnum(da.loc[o, "se"]),
                                     n=int(da.loc[o, "n"])) for o in OFFSETS}

    # ---- pre-event slope
    out["pre_slope_excl_anchor"] = pre_slope(piv, meta, drop_anchor=True)
    out["pre_slope_incl_anchor"] = pre_slope(piv, meta, drop_anchor=False)

    # ---- jump across the event, paired -5 -> +5
    dv, cl, n = paired(piv, meta, -5, 5)
    out["jump_m5_to_p5"] = dict(**{k: jnum(v) for k, v in cluster_mean_se(dv, cl).items()})
    for sgn, nm in ((1, "hawk"), (-1, "dove")):
        sel = (meta["stance_sign"] == sgn).to_numpy()
        va, vb = piv[-5].to_numpy(), piv[5].to_numpy()
        ok = sel & np.isfinite(va) & np.isfinite(vb)
        out[f"jump_m5_to_p5_{nm}_raw_drate"] = {
            k: jnum(v) for k, v in
            cluster_mean_se((vb - va)[ok], meta["date"].to_numpy()[ok]).items()}

    # ---- hawk-minus-dove gap at each of a few offsets, via day-clustered OLS
    out["gap_hawk_minus_dove"] = {}
    for o in (-5, 0, 5, 30, 60, 240, 300):
        v = piv[o].to_numpy()
        hk = (meta["stance_sign"] == 1).to_numpy().astype(float)
        ok = np.isfinite(v)
        X = np.column_stack([np.ones(ok.sum()), hk[ok]])
        r = cluster_ols(v[ok], X, meta["date"].to_numpy()[ok], names=["const", "hawk"])
        out["gap_hawk_minus_dove"][str(o)] = dict(
            gap_bp=r["hawk"]["coef"], se=r["hawk"]["se"], t=r["hawk"]["t"],
            n=r["n"], n_days=r["n_clusters"])

    # ---- balanced-through-+240 subset: shares landed, drift share
    thru = [o for o in OFFSETS if o <= 240]
    bal = piv[thru].notna().all(axis=1)
    pb, mb = piv.loc[bal], meta.loc[bal]
    sgn = mb["stance_sign"].to_numpy()
    out["balanced_240"] = dict(n_events=int(bal.sum()),
                               n_hawk=int((mb["stance_sign"] == 1).sum()),
                               n_dove=int((mb["stance_sign"] == -1).sum()),
                               n_days=int(mb["date"].nunique()))
    v240 = pb[240].to_numpy() * sgn
    m240 = cluster_mean_se(v240, mb["date"].to_numpy())
    out["balanced_240"]["move_at_240_bp"] = {k: jnum(v) for k, v in m240.items()}
    out["shares_landed"] = {}
    for o in SHARE_AT:
        vo = pb[o].to_numpy() * sgn
        mo = cluster_mean_se(vo, mb["date"].to_numpy())
        share = mo["mean"] / m240["mean"] if m240["mean"] != 0 else np.nan
        rec = dict(move_bp=jnum(mo["mean"]), se=jnum(mo["se"]), share_of_240=jnum(share))
        if do_bootstrap:
            bs = cluster_bootstrap_ratio(vo, v240, mb["date"].to_numpy(), n_draw=2000)
            rec["share_ci95"] = [jnum(bs["lo"]), jnum(bs["hi"])]
        out["shares_landed"][str(o)] = rec
    v30 = pb[30].to_numpy() * sgn
    drift_num = v240 - v30
    md = cluster_mean_se(drift_num, mb["date"].to_numpy())
    out["drift_after_30"] = dict(
        move_bp=jnum(md["mean"]), se=jnum(md["se"]), t=jnum(md["t"]),
        share_of_240=jnum(md["mean"] / m240["mean"]) if m240["mean"] else np.nan)
    if do_bootstrap:
        bs = cluster_bootstrap_ratio(drift_num, v240, mb["date"].to_numpy(), n_draw=2000)
        out["drift_after_30"]["share_ci95"] = [jnum(bs["lo"]), jnum(bs["hi"])]

    # ---- reversion, paired +240 -> +300
    dv, cl, n = paired(piv, meta, 240, 300)
    rv = cluster_mean_se(dv, cl)
    out["revert_240_to_300"] = {k: jnum(v) for k, v in rv.items()}
    s = meta["stance_sign"].to_numpy()
    va, vb = piv[240].to_numpy() * s, piv[300].to_numpy() * s
    ok = np.isfinite(va) & np.isfinite(vb)
    out["revert_240_to_300"]["mean_at_240_paired"] = jnum(va[ok].mean())
    out["revert_240_to_300"]["mean_at_300_paired"] = jnum(vb[ok].mean())
    out["revert_240_to_300"]["retained_share"] = jnum(vb[ok].mean() / va[ok].mean()) if va[ok].mean() else np.nan

    # ---- arm-balanced composite at +240 (the roster is 3.4:1 hawk)
    h240 = cluster_mean_se(piv.loc[meta["stance_sign"] == 1, 240].to_numpy(),
                           meta.loc[meta["stance_sign"] == 1, "date"].to_numpy())
    d240 = cluster_mean_se(piv.loc[meta["stance_sign"] == -1, 240].to_numpy(),
                           meta.loc[meta["stance_sign"] == -1, "date"].to_numpy())
    out["arm_balanced_240"] = dict(
        hawk_mean_drate=jnum(h240["mean"]), dove_mean_drate=jnum(d240["mean"]),
        arm_balanced_signed_bp=jnum((h240["mean"] - d240["mean"]) / 2.0),
        event_weighted_signed_bp=jnum(sp.loc[240, "mean"]))
    return out


def main():
    ev, pl = load_rank3()

    # Barkin 2025-04-09 11:00 - the 90-day tariff-pause day.  The +29.5bp lands
    # between +120 and +180, two hours after the speech, and no calendar column
    # flags it.  It is NOT dropped; it is reported as a stated sensitivity.
    bark = ev[(ev["speaker"] == "Barkin") &
              (ev["speech_ts"].dt.strftime("%Y-%m-%d %H:%M") == "2025-04-09 11:00")]
    bark_id = int(bark["event_id"].iloc[0]) if len(bark) else None
    print("Barkin 2025-04-09 11:00 event_id:", bark_id,
          "| in non-overlapping headline subset:",
          bool(len(bark) and not bark["is_overlapping"].iloc[0]))

    books = {}
    piv_no, meta_no = wide(ev[~ev["is_overlapping"]])
    books["nonoverlap"] = book_stats(piv_no, meta_no, "non-overlapping, signed, rank 3")

    piv_all, meta_all = wide(ev)
    books["all"] = book_stats(piv_all, meta_all, "all events, signed, rank 3")

    piv_pl, meta_pl = wide(pl)
    books["placebo"] = book_stats(piv_pl, meta_pl, "placebo (time-of-day + calendar matched), rank 3")

    # ---- sensitivity: headline gap at +240 with Barkin excluded
    if bark_id is not None and bark_id in piv_no.index:
        keep = piv_no.index != bark_id
        p2, m2 = piv_no.loc[keep], meta_no.loc[keep]
        v = p2[240].to_numpy()
        hk = (m2["stance_sign"] == 1).to_numpy().astype(float)
        ok = np.isfinite(v)
        X = np.column_stack([np.ones(ok.sum()), hk[ok]])
        r = cluster_ols(v[ok], X, m2["date"].to_numpy()[ok], names=["const", "hawk"])
        sp2 = signed_path(p2, m2)
        books["nonoverlap"]["sensitivity_ex_barkin_20250409"] = dict(
            gap_bp=r["hawk"]["coef"], se=r["hawk"]["se"], t=r["hawk"]["t"],
            n=r["n"], n_days=r["n_clusters"],
            signed_mean_240_bp=jnum(sp2.loc[240, "mean"]),
            signed_t_240=jnum(sp2.loc[240, "t"]))

    # ---- robustness: |bucket| >= 1 cut (the repo's absolute_bucket NEUTRAL filter)
    b1 = meta_no["bucket"].abs() >= 1
    sp_b1 = signed_path(piv_no.loc[b1], meta_no.loc[b1])
    books["nonoverlap"]["robustness_bucket_ge1"] = dict(
        n_events=int(b1.sum()),
        n_hawk=int((meta_no.loc[b1, "stance_sign"] == 1).sum()),
        n_dove=int((meta_no.loc[b1, "stance_sign"] == -1).sum()),
        signed_240_bp=jnum(sp_b1.loc[240, "mean"]), signed_t_240=jnum(sp_b1.loc[240, "t"]),
        signed_30_bp=jnum(sp_b1.loc[30, "mean"]), signed_t_30=jnum(sp_b1.loc[30, "t"]))

    # ---- composition check: does the unbalanced fan match the balanced one?
    thru = [o for o in OFFSETS if o <= 240]
    bal = piv_no[thru].notna().all(axis=1)
    sp_bal = signed_path(piv_no.loc[bal], meta_no.loc[bal])
    sp_unbal = signed_path(piv_no, meta_no)
    books["nonoverlap"]["balanced_vs_unbalanced"] = {
        str(o): dict(unbalanced=jnum(sp_unbal.loc[o, "mean"]),
                     balanced=jnum(sp_bal.loc[o, "mean"]),
                     diff=jnum(sp_unbal.loc[o, "mean"] - sp_bal.loc[o, "mean"]))
        for o in thru}

    (HERE / "c1_stats.json").write_text(json.dumps(books, indent=1, default=jnum), encoding="utf-8")

    # ---- human-readable report
    lines: list[str] = []
    def W(s=""):
        lines.append(s)
        print(s)

    for key in ("nonoverlap", "all", "placebo"):
        b = books[key]
        W("=" * 78)
        W(f"{key.upper()}  -  {b['tag']}")
        W(f"  n={b['n_events']} signed events ({b['n_hawk']} hawk / {b['n_dove']} dove) "
          f"on {b['n_days']} distinct days;  years {b['years']}")
        ps = b["pre_slope_excl_anchor"]
        W(f"  PRE-EVENT SLOPE (-120..-5, anchor -60 excluded): "
          f"{ps['slope_bp_per_hour']:+.3f} bp/hour  (SE {ps['se_bp_per_hour']:.3f}, t={ps['t']:+.2f}, "
          f"{ps['n_rows']} rows / {ps['n_days']} days)")
        ps2 = b["pre_slope_incl_anchor"]
        W(f"                   (anchor included):            "
          f"{ps2['slope_bp_per_hour']:+.3f} bp/hour  (t={ps2['t']:+.2f})")
        j = b["jump_m5_to_p5"]
        W(f"  JUMP -5 -> +5 (paired):  {j['mean']:+.4f} bp  (SE {j['se']:.4f}, t={j['t']:+.2f}, "
          f"n={j['n']} events / {j['n_clusters']} days)")
        g = b["gap_hawk_minus_dove"]["240"]
        W(f"  HAWK-minus-DOVE gap at +240: {g['gap_bp']:+.3f} bp  (SE {g['se']:.3f}, t={g['t']:+.2f}, "
          f"n={g['n']} / {g['n_days']} days)")
        bal240 = b["balanced_240"]
        W(f"  BALANCED-through-+240 subset: n={bal240['n_events']} "
          f"({bal240['n_hawk']}H/{bal240['n_dove']}D, {bal240['n_days']} days); "
          f"signed move at +240 = {bal240['move_at_240_bp']['mean']:+.4f} bp "
          f"(t={bal240['move_at_240_bp']['t']:+.2f})")
        for o in SHARE_AT:
            r = b["shares_landed"][str(o)]
            ci = r.get("share_ci95")
            W(f"     landed by +{o:>3}m: {r['move_bp']:+.4f} bp = {r['share_of_240'] * 100:7.1f}% of +240"
              + (f"   CI95 [{ci[0] * 100:.0f}%, {ci[1] * 100:.0f}%]" if ci else ""))
        d = b["drift_after_30"]
        ci = d.get("share_ci95")
        W(f"     DRIFT after +30m: {d['move_bp']:+.4f} bp = {d['share_of_240'] * 100:.1f}% of +240 "
          f"(t={d['t']:+.2f})" + (f"  CI95 [{ci[0] * 100:.0f}%, {ci[1] * 100:.0f}%]" if ci else ""))
        r = b["revert_240_to_300"]
        W(f"  REVERSION +240 -> +300 (paired, n={r['n']}): {r['mean']:+.4f} bp (t={r['t']:+.2f}); "
          f"{r['mean_at_240_paired']:+.4f} -> {r['mean_at_300_paired']:+.4f} bp "
          f"({r['retained_share'] * 100:.0f}% retained)")
        ab = b["arm_balanced_240"]
        W(f"  COMPOSITE at +240: event-weighted {ab['event_weighted_signed_bp']:+.4f} bp   "
          f"arm-balanced {ab['arm_balanced_signed_bp']:+.4f} bp "
          f"(hawk d_rate {ab['hawk_mean_drate']:+.4f}, dove d_rate {ab['dove_mean_drate']:+.4f})")
        W()

    W("=" * 78)
    W("SENSITIVITY / ROBUSTNESS (headline book)")
    s = books["nonoverlap"].get("sensitivity_ex_barkin_20250409")
    if s:
        W(f"  +240 gap EXCLUDING Barkin 2025-04-09 (tariff-pause day): "
          f"{s['gap_bp']:+.3f} bp (t={s['t']:+.2f}); signed mean {s['signed_mean_240_bp']:+.4f} bp "
          f"(t={s['signed_t_240']:+.2f})")
    rb = books["nonoverlap"]["robustness_bucket_ge1"]
    W(f"  |bucket|>=1 cut (n={rb['n_events']}, {rb['n_hawk']}H/{rb['n_dove']}D): "
      f"signed +30m {rb['signed_30_bp']:+.4f} bp (t={rb['signed_t_30']:+.2f}), "
      f"+240m {rb['signed_240_bp']:+.4f} bp (t={rb['signed_t_240']:+.2f})")
    bv = books["nonoverlap"]["balanced_vs_unbalanced"]
    worst = max(bv.items(), key=lambda kv: abs(kv[1]["diff"]))
    W(f"  balanced-vs-unbalanced fan: largest per-offset gap {worst[1]['diff']:+.4f} bp at "
      f"offset {worst[0]} (unbal {worst[1]['unbalanced']:+.4f} vs bal {worst[1]['balanced']:+.4f})")
    W(f"  at offset 0:   unbal {bv['0']['unbalanced']:+.4f} vs bal {bv['0']['balanced']:+.4f} bp")

    (HERE / "c1_stats.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\nwrote c1_stats.json / c1_stats.txt")


if __name__ == "__main__":
    main()
