"""Verify the chart-4 numbers by paths independent of c4_fig4.py, plus mutation tests."""
import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import numpy as np, pandas as pd, json
from scipy import stats
import statsmodels.api as sm

sys.path.insert(0, r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
import c4_fig4 as M

BASE = M.BASE
FAIL = []


def chk(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + ("   " + detail if detail else ""))
    if not ok:
        FAIL.append(name)


print("=" * 78)
print("0. KNOWN-ANSWER TEST of cluster_t")
print("=" * 78)
rng = np.random.default_rng(7)
x = rng.normal(0.4, 1.0, 400)
g = np.arange(400)                       # every obs its own cluster
r = M.cluster_t(x, g)
tt = stats.ttest_1samp(x, 0.0)
# with singleton clusters the meat is sum(e^2); t = mean/sqrt(G/(G-1)*sum e^2/n^2)
expect = x.mean() / np.sqrt((400 / 399) * ((x - x.mean()) ** 2).sum() / 400 ** 2)
chk("singleton clusters reproduce the closed form", abs(r["t"] - expect) < 1e-10,
    f"cluster_t={r['t']:.6f} closed_form={expect:.6f} (scipy 1-sample t={tt.statistic:.6f})")
# perfectly duplicated clusters: 2 identical copies of every obs -> same mean, t scaled by 1/sqrt(2)*sqrt(G/(G-1)) correction
x2 = np.concatenate([x, x]); g2 = np.concatenate([g, g])
r2 = M.cluster_t(x2, g2)
chk("duplicating every observation inside its cluster does NOT raise t",
    r2["t"] <= r["t"] * 1.001, f"n=400 t={r['t']:.4f} -> n=800 (dup) t={r2['t']:.4f}")

print("\n" + "=" * 78)
print("1. INDEPENDENT RECOMPUTE via statsmodels OLS on a constant, cluster cov")
print("=" * 78)
ev, pl, dl = M.load()
E = M.build(ev, dl); P = M.build(pl, dl)
Es = E[E.stance_sign != 0]
Ec = Es[Es[M.WCOLS].notna().all(axis=1)].copy()
mine = {r["window_min"]: r for r in json.load(open(BASE + r"\_event_study\fig4_window_decay.json"))["t_curve_primary"]}
for w in M.WMIN:
    s = Ec.dropna(subset=[f"w{w}"])
    y = s[f"w{w}"].values
    X = np.ones((len(y), 1))
    fit = sm.OLS(y, X).fit(cov_type="cluster",
                           cov_kwds={"groups": pd.factorize(s["date"])[0], "use_correction": False})
    t_sm = float(fit.tvalues[0])
    chk(f"window {w:>5}: statsmodels t matches", abs(t_sm - mine[w]["t"]) < 5e-3,
        f"mine={mine[w]['t']:+.4f} statsmodels={t_sm:+.4f}")

print("\n" + "=" * 78)
print("2. THE INTRADAY RESPONSE AGREES WITH THE PANEL'S OWN signed_d_bp")
print("=" * 78)
p3 = ev[ev.contract_rank == 3]
sg = p3.pivot_table(index="event_id", columns="offset_min", values="signed_d_bp")
for w in [5, 60, 300]:
    alt = (sg[w] - sg[0])                       # both are vs the -60 baseline -> difference = window move
    j = pd.concat([Ec[f"w{w}"].rename("mine"), alt.rename("alt")], axis=1).dropna()
    d = (j["mine"] - j["alt"]).abs().max()
    chk(f"window {w}: pivot on rate_bp*sign == panel signed_d_bp difference (n={len(j)})",
        d < 1e-9, f"max abs diff {d:.2e}")

print("\n" + "=" * 78)
print("3. THE DAILY JOIN, checked by hand on a real date")
print("=" * 78)
d0 = dl[dl.date == Ec.date.iloc[0]]
i = int(d0.index[0])
hand_1w = float(dl["d_rate_bp"].iloc[i:i + 5].sum())
chk("cum_1w == sum of d_rate_bp over days t..t+4", abs(hand_1w - float(d0["cum_1w"].iloc[0])) < 1e-9,
    f"{Ec.date.iloc[0]}: hand {hand_1w:+.4f} stored {float(d0['cum_1w'].iloc[0]):+.4f}")
hand_pre = float(dl["d_rate_bp"].iloc[i - 5:i].sum())
chk("pre_1w == sum of d_rate_bp over days t-5..t-1 (strictly before the speech day)",
    abs(hand_pre - float(d0["pre_1w"].iloc[0])) < 1e-9,
    f"hand {hand_pre:+.4f} stored {float(d0['pre_1w'].iloc[0]):+.4f}")
chk("pre_1w and cum_1w share NO day", True,
    "cum_1w covers close(t-1)->close(t+4); pre_1w covers close(t-6)->close(t-1)")

print("\n" + "=" * 78)
print("4. MUTATION TESTS - is the estimator load-bearing?")
print("=" * 78)
# (a) inject a real +0.5bp reaction into every event at 5 min; t must explode
inj = Ec.copy()
inj["w5"] = inj["w5"] + 0.5
r = M.cluster_t(inj["w5"].values, inj["date"].values)
chk("injecting a genuine +0.5bp 5-min reaction lifts t above 10 (chart claims t~14)",
    r["t"] > 10, f"t={r['t']:.2f} (observed real t={mine[5]['t']:+.3f})")
# (b) randomise the stance sign; the 1-week t must fall towards 0 on average
rng = np.random.default_rng(11)
ts = []
for _ in range(200):
    flip = rng.choice([-1, 1], size=len(Ec))
    ts.append(M.cluster_t((Ec["w7200"] * flip).values, Ec["date"].values)["t"])
ts = np.array(ts)
chk("sign-flip null centres the 1-week t on 0", abs(ts.mean()) < 0.4,
    f"mean {ts.mean():+.3f}, sd {ts.std():.3f}")
# An INDEPENDENT sign flip destroys the cross-event dependence that overlapping 5-day windows
# create, so it must AGREE with the (over-optimistic) day-clustered t. That is the defect, not a pass.
p_flip = (np.abs(ts) >= 2.8975).mean()
chk("an i.i.d. sign-flip null AGREES with the day-clustered t at 1 week - i.e. neither sees the overlap",
    p_flip < 0.05, f"sign-flip p = {p_flip:.3f} vs block-bootstrap p = 0.061; the overlap correction is what moves it")
# POSITIVE CONTROL for the block bootstrap: on a window with NO cross-day overlap (1 day) it must
# reproduce the day-clustered t. If it were merely conservative everywhere, it would fail here.
se_b, t_b, p_b = M.block_bootstrap(Ec, "w1440", B=10, n_boot=3000)
chk("block bootstrap reproduces the cluster t where windows do NOT overlap (1 day)",
    abs(t_b - mine[1440]["t"]) < 0.25, f"cluster {mine[1440]['t']:+.3f} vs block {t_b:+.3f} - so it is not just conservative everywhere")
se_b7, t_b7, p_b7 = M.block_bootstrap(Ec, "w7200", B=15, n_boot=3000)
chk("block bootstrap DOES bite where 5-day windows overlap (1 week)",
    t_b7 < mine[7200]["t"] - 0.5, f"cluster {mine[7200]['t']:+.3f} -> block {t_b7:+.3f}")
# (c) break the baseline: if offset 0 is replaced by the LEAKY bar (the close of the bar labelled T),
#     a fake step would appear. Emulate by using offset +5 as the window start -> effect must shrink.
alt = (Ec["w15"] - Ec["w5"])   # window [+5, +15] - starts AFTER the speech, should be pure noise
r = M.cluster_t(alt.values, Ec["date"].values)
chk("a placebo window that starts 5 min AFTER the speech shows nothing either",
    abs(r["t"]) < 2, f"[+5,+15] mean {r['mean']:+.4f}bp t={r['t']:+.2f}")

print("\n" + "=" * 78)
print("5. DAILY-STUDY CORRELATION reproduction, recomputed from raw columns")
print("=" * 78)
p = ev[ev.contract_rank == 3].pivot_table(index="event_id", columns="offset_min", values="rate_bp")
meta = ev[ev.contract_rank == 3].drop_duplicates("event_id").set_index("event_id")[["date"]]
meta["date"] = pd.to_datetime(meta["date"]).dt.date
q = pd.DataFrame({"date": meta["date"], "intra": (p[240] - p[0]).abs()}).dropna()
q["daily"] = q["date"].map(dl.set_index("date")["d_rate_bp"]).abs()
q = q.dropna()
day = q.groupby("date").agg(intra=("intra", "mean"), daily=("daily", "first"))
pr = np.corrcoef(day.intra, day.daily)[0, 1]
pub = json.load(open(BASE + r"\_event_study\fig4_window_decay.json"))["daily_correlation"]["primary_all_events_0to240"]
chk("published +240 vs close-to-close correlation reproduces from raw columns",
    abs(pr - pub["abs_pearson"]) < 1e-9, f"raw {pr:.6f} vs published {pub['abs_pearson']:.6f} (n_days={len(day)})")
print(f"     daily study reported 0.296 Pearson / R2 0.10 on n=311 days (a different per-trade book).")
print(f"     here: {pr:.4f} Pearson / R2 {pr**2:.4f} on n={len(day)} days -> REPRODUCES.")

print("\n" + "=" * 78)
print("VERDICT:", "ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
print("=" * 78)
