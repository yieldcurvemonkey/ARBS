"""THE LAST UNTESTED CUT: does a PRINCIPAL moving the mic move the front end,
even though the pooled 36-name calendar does not?

Rationale (from the study's own open limitations): Powell (203 events) and
Williams (236) are pooled with 34 other names. A Chair / Vice-Chair / NY effect
diluted ~4x by pooling would look exactly like the observed null. This is the
strongest remaining chance the thesis survives.

PRE-REGISTERED before any result is seen:
  Tiers (nested, each vs the SAME no-speech baseline):
    T1 chair_only     - the sitting Chair
    T2 chair_plus_ny  - Chair + New York Fed president
    T3 board          - Chair + Vice Chairs + Governors + NY  (permanent voters)
    T4 regional_only  - days where ONLY rotating regional presidents spoke
  Statistics: mean|d| ratio and median|d| ratio vs no-speech days.
  Null: circular rotation of the tier indicator over the full index,
        offsets in [21, n-21], 5000 seeded draws. Two-sided p.
  ALL tiers reported. 4 tiers x 2 stats = 8 tests; 0.4 expected below 0.05.

Sample: rung (c) = ex-FOMC, ex-CPI, ex-NFP  (the study's headline sample),
        plus a clean variant that also drops IMM rolls.
"""
import json

import numpy as np
import pandas as pd

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
SEED = 20260825
NDRAW = 5000

# Permanent voters / principals. Regional presidents (rotating) are everyone else.
CHAIR = {"Powell", "Yellen"}
NY = {"Williams", "Dudley"}
GOVERNORS = {"Jefferson", "Waller", "Bowman", "Cook", "Barr", "Brainard",
             "Clarida", "Quarles", "Kugler", "Miran", "Bailey_gov"}

p = pd.read_parquet(f"{OUT}/panel_daily.parquet")
p.index = pd.to_datetime(p.index)
p["speakers"] = p["speakers"].fillna("")


def names(s):
    return {x.strip() for x in str(s).split(",") if x.strip()}


spk = p["speakers"].apply(names)
p["has_chair"] = spk.apply(lambda s: bool(s & CHAIR))
p["has_ny"] = spk.apply(lambda s: bool(s & NY))
p["has_gov"] = spk.apply(lambda s: bool(s & GOVERNORS))
p["has_any"] = p.is_speech_day.astype(bool)
p["has_principal"] = p.has_chair | p.has_ny | p.has_gov
p["regional_only"] = p.has_any & ~p.has_principal

TIERS = {
    "T1_chair_only": p.has_chair,
    "T2_chair_plus_ny": p.has_chair | p.has_ny,
    "T3_board_perm_voters": p.has_principal,
    "T4_regional_only": p.regional_only,
}


def stats(flag, base_nospeech, col):
    a = col[flag]
    b = col[base_nospeech]
    if len(a) < 20:
        return None
    return {"n": int(len(a)), "mean_ratio": float(a.mean() / b.mean()),
            "median_ratio": float(a.median() / b.median()),
            "mean_bp": float(a.mean()), "baseline_bp": float(b.mean())}


def rotation_p(flag_arr, nospeech_arr, col_arr, obs_mean, obs_med, n):
    rng = np.random.default_rng(SEED)
    offs = rng.integers(21, n - 21, size=NDRAW)
    m_null, d_null = [], []
    base = col_arr[nospeech_arr]
    bm, bmd = base.mean(), np.median(base)
    for o in offs:
        f = np.roll(flag_arr, o)
        a = col_arr[f]
        if len(a) < 20:
            continue
        m_null.append(a.mean() / bm)
        d_null.append(np.median(a) / bmd)
    m_null = np.asarray(m_null)
    d_null = np.asarray(d_null)
    # two-sided p about the null median
    pm = float(np.mean(np.abs(m_null - np.median(m_null)) >= abs(obs_mean - np.median(m_null))))
    pd_ = float(np.mean(np.abs(d_null - np.median(d_null)) >= abs(obs_med - np.median(d_null))))
    return pm, pd_, float(np.median(m_null)), float(np.median(d_null)), \
        float(np.percentile(m_null, 97.5)), float(np.percentile(d_null, 97.5))


out = {"design": "pre-registered 4 tiers x 2 stats; rotation null 5000 draws; seed 20260825"}

for variant, mask in [
    ("rung_c", ~p.is_fomc_day.astype(bool) & ~p.is_cpi_day.astype(bool) & ~p.is_nfp_day.astype(bool)),
    ("rung_c_clean", ~p.is_fomc_day.astype(bool) & ~p.is_cpi_day.astype(bool)
     & ~p.is_nfp_day.astype(bool) & ~p.is_imm_roll.astype(bool)),
]:
    d = p[mask].dropna(subset=["abs_d_rate_bp"])
    col = d["abs_d_rate_bp"]
    nospeech = ~d.has_any
    n = len(d)
    v = {"n_days": n, "n_nospeech": int(nospeech.sum()),
         "nospeech_mean_bp": round(float(col[nospeech].mean()), 3), "tiers": {}}
    for tname, tflag in TIERS.items():
        f = tflag.reindex(d.index).fillna(False).astype(bool)
        s = stats(f, nospeech, col)
        if s is None:
            v["tiers"][tname] = "insufficient n"
            continue
        pm, pmd, nm, nmd, m975, d975 = rotation_p(
            f.values, nospeech.values, col.values, s["mean_ratio"], s["median_ratio"], n)
        s.update({"rotation_p_mean": round(pm, 4), "rotation_p_median": round(pmd, 4),
                  "null_median_mean_ratio": round(nm, 4), "null_median_median_ratio": round(nmd, 4),
                  "null_p97.5_mean": round(m975, 4), "null_p97.5_median": round(d975, 4)})
        for k in ("mean_ratio", "median_ratio", "mean_bp", "baseline_bp"):
            s[k] = round(s[k], 4)
        v["tiers"][tname] = s
    out[variant] = v

# how many of the 8 pre-registered cells clear 5%?
hits = []
for variant in ("rung_c", "rung_c_clean"):
    for tname, s in out[variant]["tiers"].items():
        if isinstance(s, dict):
            for stat in ("rotation_p_mean", "rotation_p_median"):
                if s[stat] < 0.05:
                    hits.append(f"{variant}/{tname}/{stat}={s[stat]}")
out["cells_below_0.05"] = hits
out["cells_total"] = 16
out["expected_by_chance_at_5pct"] = 0.8

print(json.dumps(out, indent=1))
with open(f"{OUT}/zz_principal_split.json", "w") as f:
    json.dump(out, f, indent=1)
