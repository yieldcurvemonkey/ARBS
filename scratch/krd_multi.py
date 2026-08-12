"""Multi-shape validation: analytic zero-KRD vs exact reprice, and (via the
zero->par Jacobian) vs rateslib Portfolio.delta(solver=...).  Plus Fed Funds
curve and Jacobian-stability measurements."""
import os, time, datetime, statistics
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import numpy as np
import pandas as pd
import rateslib as rl
from Caching.curve_store import CurveStore

LADDER = ["3M", "6M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y", "7Y",
          "10Y", "12Y", "15Y", "20Y", "25Y", "30Y"]
K = len(LADDER)
store = CurveStore.default()
pd.set_option("display.width", 240)


class Engine:
    def __init__(self, row):
        self.row = row
        self.curve = CurveStore.reconstruct_curve(row)
        c = self.curve
        self.REF = c.nodes.initial
        self.CAL = rl.get_calendar(c.meta.calendar)
        self.SPOT = self.CAL.lag_bus_days(self.REF, 2, True)
        self.NODE_DATES = list(c.nodes.nodes)
        self.NODE_DF = np.array([float(c.nodes.nodes[d]) for d in self.NODE_DATES])
        self.NODE_DAYS = np.array([(pd.Timestamp(d) - pd.Timestamp(self.REF)).days
                                   for d in self.NODE_DATES], float)
        self.LN_DF = np.log(self.NODE_DF)
        self.CONV, self.CALN, self.MODF = c.meta.convention, c.meta.calendar, c.meta.modifier
        self.spec = "usd_irs"
        self.ladder = [self.irs(t, c) for t in LADDER]
        self.par = np.array([float(i.rate(curves=c).real) for i in self.ladder])
        self.pv01 = np.array([float(i.leg1.analytic_delta(disc_curve=c).real) for i in self.ladder])
        self.mats = [i.leg1.schedule.termination for i in self.ladder]
        self.GRID = np.array([(pd.Timestamp(m) - pd.Timestamp(self.REF)).days for m in self.mats], float)
        self.NODE_AMP = self.tent(self.NODE_DAYS) * (self.NODE_DAYS / 365.0)[:, None]
        self._sched = {}

    def irs(self, term, curves, notional=100e6, fixed_rate=None, effective=None):
        kw = dict(effective=effective or self.SPOT, termination=term, spec=self.spec,
                  curves=curves, notional=notional)
        if fixed_rate is not None:
            kw["fixed_rate"] = fixed_rate
        return rl.IRS(**kw)

    def tent(self, t_days):
        t = np.atleast_1d(np.asarray(t_days, float))
        G = self.GRID
        W = np.zeros((t.size, K))
        for a, tv in enumerate(t):
            if tv <= G[0]:
                W[a, 0] = 1.0
            elif tv >= G[-1]:
                W[a, -1] = 1.0
            else:
                j = int(np.searchsorted(G, tv) - 1)
                f = (tv - G[j]) / (G[j + 1] - G[j])
                W[a, j], W[a, j + 1] = 1.0 - f, f
        return W

    def g_cont(self, t_days):
        t = np.atleast_1d(np.asarray(t_days, float))
        return self.tent(t) * (t / 365.0)[:, None]

    def g_node(self, t_days):
        t = np.atleast_1d(np.asarray(t_days, float))
        return np.column_stack([np.interp(t, self.NODE_DAYS, self.NODE_AMP[:, j]) for j in range(K)])

    def df(self, d):
        return np.exp(np.interp(d, self.NODE_DAYS, self.LN_DF))

    def schedule(self, term, effective=None):
        key = (str(effective or self.SPOT), str(term))
        if key not in self._sched:
            irs = self.irs(term, self.curve, notional=1.0, fixed_rate=1.0, effective=effective)

            def pull(cf, typ):
                d = pd.DataFrame(cf); d = d[d["Type"] == typ]
                f = lambda c: np.array([(pd.Timestamp(x) - pd.Timestamp(self.REF)).days for x in d[c]], float)
                return f("Acc Start"), f("Acc End"), f("Payment"), np.array(d["DCF"], float)
            self._sched[key] = (
                pull(irs.leg1.cashflows(rate_curve=self.curve, disc_curve=self.curve), "FixedPeriod"),
                pull(irs.leg2.cashflows(rate_curve=self.curve, disc_curve=self.curve), "FloatPeriod"))
        return self._sched[key]

    def krd(self, term, notional, fixed_rate, gfun=None, effective=None):
        gfun = gfun or self.g_cont
        (s1, e1, p1, dcf1), (s2, e2, p2, dcf2) = self.schedule(term, effective)
        dfp1 = self.df(p1)
        cf1 = -notional * dcf1 * (fixed_rate / 100.0)
        out = ((cf1 * dfp1)[:, None] * (-gfun(p1))).sum(axis=0)
        dfs, dfe, dfp2 = self.df(s2), self.df(e2), self.df(p2)
        ratio = dfs / dfe
        out = out + ((notional * ratio * dfp2)[:, None] * (gfun(e2) - gfun(s2))
                     + (notional * (ratio - 1.0) * dfp2)[:, None] * (-gfun(p2))).sum(axis=0)
        return out * 1e-4

    def shocked(self, j, bump_bp):
        sc = bump_bp * 1e-4
        nodes = {d: float(self.NODE_DF[i] * np.exp(-sc * self.NODE_AMP[i, j]))
                 for i, d in enumerate(self.NODE_DATES)}
        return rl.Curve(nodes=nodes, convention=self.CONV, calendar=self.CALN,
                        modifier=self.MODF, interpolation="log_linear", id=f"sh{j}")

    def reprice_krd(self, term, notional, fixed_rate, effective=None, bump=0.5):
        ins = self.irs(term, self.curve, notional=notional, fixed_rate=fixed_rate, effective=effective)
        out = []
        for j in range(K):
            up = float(ins.npv(curves=self.shocked(j, +bump)).real)
            dn = float(ins.npv(curves=self.shocked(j, -bump)).real)
            out.append((up - dn) / (2 * bump))
        return np.array(out)

    def jacobian(self):
        J = np.zeros((K, K))
        for i, t in enumerate(LADDER):
            J[i, :] = self.krd(t, 100e6, float(self.par[i])) / self.pv01[i]
        return J

    def risk_solver(self):
        nodes = {self.REF: 1.0}
        for m in self.mats:
            nodes[m] = float(self.curve[m])
        rc = rl.Curve(nodes=dict(sorted(nodes.items())), convention=self.CONV,
                      calendar=self.CALN, modifier=self.MODF,
                      interpolation="log_linear", id="RISK")
        insts = [self.irs(t, rc) for t in LADDER]
        slv = rl.Solver(curves=[rc], instruments=insts, s=list(self.par),
                        instrument_labels=LADDER, id="RISK", func_tol=1e-8, conv_tol=1e-10)
        return rc, slv


# ================================================================= SOFR
DAY = datetime.date(2026, 6, 15)
raw = store.read_raw_nodes("USD-SOFR-1D-CITIVELOEXCELMIN", start=DAY, end=DAY)
mid = raw.iloc[len(raw) // 2].to_dict()
E = Engine(mid)
print(f"SOFR curve @ {mid['timestamp_utc']}  ref={E.REF} spot={E.SPOT}")

rc, slv = E.risk_solver()
J = E.jacobian()
JinvT = np.linalg.inv(J).T

fwd5 = rl.add_tenor(E.SPOT, "5Y", "MF", E.CALN)
fwd1 = rl.add_tenor(E.SPOT, "1Y", "MF", E.CALN)
CASES = [
    ("spot 2Y payer par",        "2Y",  200e6, float(E.par[LADDER.index("2Y")]),  None),
    ("spot 10Y payer par",       "10Y", 100e6, float(E.par[LADDER.index("10Y")]), None),
    ("spot 30Y receiver par",    "30Y", -50e6, float(E.par[LADDER.index("30Y")]), None),
    ("spot 7Y payer OFF-market", "7Y",  250e6, 2.50,                              None),
    ("spot 20Y recv OFF-market", "20Y", -75e6, 6.00,                              None),
    ("5Yx5Y payer",              "5Y",  300e6, 4.20,                              fwd5),
    ("1Yx10Y receiver",          "10Y", -150e6, 4.10,                             fwd1),
    ("spot 6M payer",            "6M",  1000e6, float(E.par[LADDER.index("6M")]), None),
    ("spot 25Y payer odd size",  "25Y", 37.5e6, 4.4444,                           None),
]

rows = []
for name, term, notl, fr, eff in CASES:
    ana = E.krd(term, notl, fr, effective=eff)
    ana_node = E.krd(term, notl, fr, gfun=E.g_node, effective=eff)
    rep = E.reprice_krd(term, notl, fr, effective=eff)
    ins_rc = E.irs(term, rc, notional=notl, fixed_rate=fr, effective=eff)
    d = rl.Portfolio([ins_rc]).delta(solver=slv)
    sol = d[d.columns[0]].to_numpy(float)
    conv = JinvT @ ana
    tot = abs(sol.sum())
    rows.append(dict(
        case=name,
        total_par_dv01=sol.sum(),
        total_zero_krd=ana.sum(),
        V1_max_pct=np.abs(ana_node - rep).max() / tot * 100,
        raw_zero_vs_solver_max_pct=np.abs(ana - sol).max() / tot * 100,
        conv_par_vs_solver_max_pct=np.abs(conv - sol).max() / tot * 100,
        conv_par_vs_solver_max_usd=np.abs(conv - sol).max(),
        conv_sum_rel_pct=(conv.sum() - sol.sum()) / tot * 100,
    ))
res = pd.DataFrame(rows)
print("\n===== agreement across trade shapes (SOFR 2026-06-15 16:00Z, 15-bucket ladder) =====")
print(res.round(4).to_string(index=False))

# one full ladder printout for a forward-start case (shape test)
name, term, notl, fr, eff = CASES[5]
ana = E.krd(term, notl, fr, effective=eff)
ins_rc = E.irs(term, rc, notional=notl, fixed_rate=fr, effective=eff)
sol = rl.Portfolio([ins_rc]).delta(solver=slv).iloc[:, 0].to_numpy(float)
print(f"\n----- ladder detail: {name} -----")
print(pd.DataFrame({"bucket": LADDER, "zero_krd": ana, "par_converted": JinvT @ ana,
                    "solver_par": sol, "diff": (JinvT @ ana) - sol}).round(2).to_string(index=False))

# ================================================== Jacobian stability
print("\n===== zero->par Jacobian stability =====")
J_open = Engine(raw.iloc[60].to_dict()).jacobian()
J_close = Engine(raw.iloc[-60].to_dict()).jacobian()
print(f"same day, 05:00Z+60m vs 02:00Z-60m : max|dJ| = {np.abs(J_open-J_close).max():.5f} "
      f"(J diag range {np.diag(J).min():.3f}-{np.diag(J).max():.3f})")
DAY2 = datetime.date(2026, 6, 1)
raw2 = store.read_raw_nodes("USD-SOFR-1D-CITIVELOEXCELMIN", start=DAY2, end=DAY2)
J_2wk = Engine(raw2.iloc[len(raw2)//2].to_dict()).jacobian()
print(f"2026-06-01 vs 2026-06-15           : max|dJ| = {np.abs(J-J_2wk).max():.5f}")


def krd_err_from_stale_J(Jstale):
    errs = []
    for name, term, notl, fr, eff in CASES:
        a = E.krd(term, notl, fr, effective=eff)
        ins_rc = E.irs(term, rc, notional=notl, fixed_rate=fr, effective=eff)
        s = rl.Portfolio([ins_rc]).delta(solver=slv).iloc[:, 0].to_numpy(float)
        errs.append(np.abs(np.linalg.inv(Jstale).T @ a - s).max() / abs(s.sum()) * 100)
    return max(errs)


print(f"worst-case par error using the OPEN-of-day Jacobian at mid-day : "
      f"{krd_err_from_stale_J(J_open):.4f}% of total DV01")
print(f"worst-case par error using a 2-WEEK-STALE Jacobian             : "
      f"{krd_err_from_stale_J(J_2wk):.4f}% of total DV01")

# ================================================== Fed Funds curve
print("\n===== FED FUNDS minute curve =====")
rawf = store.read_raw_nodes("USD-FEDFUNDS-1D-CITIVELOEXCELMIN", start=DAY, end=DAY)
print(f"rows={len(rawf)}")
rf = rawf.iloc[len(rawf) // 2].to_dict()
print("reference_key", rf["reference_key"], "interp", rf["interpolation"],
      "nodes", len(rf["node_dates"]), "ts", rf["timestamp_utc"])
F = Engine(rf)
ins = F.irs("10Y", F.curve, notional=100e6, fixed_rate=4.0)
cf2 = pd.DataFrame(ins.leg2.cashflows(rate_curve=F.curve, disc_curve=F.curve))
cf2 = cf2[cf2["Type"] == "FloatPeriod"]
lhs = np.array(cf2["Cashflow"], float)
dfs = np.array([float(F.curve[pd.Timestamp(x)]) for x in cf2["Acc Start"]])
dfe = np.array([float(F.curve[pd.Timestamp(x)]) for x in cf2["Acc End"]])
rhs = -np.array(cf2["Notional"], float) * (dfs / dfe - 1.0)
print(f"[V0-FF] telescoping max rel err = {np.abs((lhs-rhs)/lhs).max():.3e}")
rcf, slvf = F.risk_solver()
Jf = F.jacobian(); JfinvT = np.linalg.inv(Jf).T
errs = []
for name, term, notl, fr, eff in CASES[:5]:
    a = F.krd(term, notl, fr)
    s = rl.Portfolio([F.irs(term, rcf, notional=notl, fixed_rate=fr)]).delta(solver=slvf).iloc[:, 0].to_numpy(float)
    errs.append((name, np.abs(a - s).max() / abs(s.sum()) * 100,
                 np.abs(JfinvT @ a - s).max() / abs(s.sum()) * 100))
print(pd.DataFrame(errs, columns=["case", "raw_zero_vs_solver_pct", "conv_par_vs_solver_pct"]).round(4).to_string(index=False))
