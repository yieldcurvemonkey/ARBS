"""Is the T3 (permanent-voter) median tilt a FRONT-END channel, or ambient?

The one surviving cell of 16 was T3_board median|d| ratio 1.304, rotation p 0.027,
on the clean rung-(c) sample. If Fedspeak drives the FRONT END specifically, that
tilt must be larger on the 3m IMM forward than on a 5y SOFR rate, which has no
plausible 3m-forward channel to a speech.

Same days, same tier flag, same null. Only the target series changes.
"""
import json

import numpy as np
import pandas as pd

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
SEED = 20260825
NDRAW = 5000

CHAIR = {"Powell", "Yellen"}
NY = {"Williams", "Dudley"}
GOVERNORS = {"Jefferson", "Waller", "Bowman", "Cook", "Barr", "Brainard",
             "Clarida", "Quarles", "Kugler", "Miran"}

p = pd.read_parquet(f"{OUT}/panel_daily.parquet")
p.index = pd.to_datetime(p.index)
p["speakers"] = p["speakers"].fillna("")
spk = p["speakers"].apply(lambda s: {x.strip() for x in str(s).split(",") if x.strip()})
p["has_principal"] = spk.apply(lambda s: bool(s & (CHAIR | NY | GOVERNORS)))
p["has_any"] = p.is_speech_day.astype(bool)

mask = (~p.is_fomc_day.astype(bool) & ~p.is_cpi_day.astype(bool)
        & ~p.is_nfp_day.astype(bool) & ~p.is_imm_roll.astype(bool))

diag = pd.read_parquet(f"{OUT}/rates_diagnostic.parquet")
diag.index = pd.to_datetime(diag.index)

targets = {}
for c in diag.columns:
    lc = str(c).lower()
    if "imm_3ximm_4" in lc or lc.endswith("2y outright rate") or lc.endswith("5y outright rate"):
        targets[str(c)] = diag[c].diff().abs() * 100

rng_master = np.random.default_rng(SEED)
offs = rng_master.integers(21, len(p) - 21, size=NDRAW)

res = {"tier": "T3_board_perm_voters", "sample": "rung_c_clean",
       "question": "is the median tilt front-end specific?"}

for name, series in targets.items():
    d = pd.DataFrame({"a": series}).join(p[["has_principal", "has_any"]], how="inner")
    d = d[mask.reindex(d.index).fillna(False)].dropna()
    n = len(d)
    a = d.loc[d.has_principal, "a"]
    b = d.loc[~d.has_any, "a"]
    obs_mean = a.mean() / b.mean()
    obs_med = a.median() / b.median()

    f0 = d.has_principal.values
    col = d["a"].values
    bm, bmd = b.mean(), b.median()
    mn, dn = [], []
    for o in offs:
        f = np.roll(f0, o % n)
        aa = col[f]
        if len(aa) < 20:
            continue
        mn.append(aa.mean() / bm)
        dn.append(np.median(aa) / bmd)
    mn, dn = np.asarray(mn), np.asarray(dn)
    pm = float(np.mean(np.abs(mn - np.median(mn)) >= abs(obs_mean - np.median(mn))))
    pmd = float(np.mean(np.abs(dn - np.median(dn)) >= abs(obs_med - np.median(dn))))

    res[name] = {"n_days": int(n), "n_principal": int(len(a)), "n_nospeech": int(len(b)),
                 "mean_ratio": round(float(obs_mean), 4), "rotation_p_mean": round(pm, 4),
                 "median_ratio": round(float(obs_med), 4), "rotation_p_median": round(pmd, 4),
                 "null_median_of_median_ratio": round(float(np.median(dn)), 4)}

print(json.dumps(res, indent=1))
with open(f"{OUT}/zz_principal_placebo.json", "w") as f:
    json.dump(res, f, indent=1)

fe = [k for k in res if "IMM" in k.upper()]
if fe:
    front = res[fe[0]]["median_ratio"]
    others = [res[k]["median_ratio"] for k in res
              if isinstance(res[k], dict) and k not in fe and "n_days" in res[k]]
    print("\n--- READING ---")
    print(f"front-end (IMM 3x4) median ratio {front:.3f} vs other tenors {[round(o,3) for o in others]}")
    if others and front <= max(others) * 1.05:
        print("NOT front-end specific: the same tilt appears on tenors with no 3m-forward")
        print("Fedspeak channel. Reads as ambient news-flow on busy days, not a Fed channel.")
    else:
        print("Front-end specific: the tilt is materially larger on the 3m forward.")
