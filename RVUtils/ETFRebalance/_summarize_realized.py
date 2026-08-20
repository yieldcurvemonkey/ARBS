"""Read the realized-trade CSVs and print the compact numbers needed for the final summary."""
from __future__ import annotations
import os
import pandas as pd

pd.set_option("display.width", 240)
pd.set_option("display.max_rows", 300)

DATA = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "notebooks", "backtests", "etf_rebalance", "_data"))

def p(name):
    return os.path.join(DATA, f"realized_{name}.csv")

COST_BP = 0.5

print("=" * 100)
print("TIMING DIAGNOSTIC (publication-lag finding)")
print("=" * 100)
td = pd.read_csv(p("timing_diagnostic"))
print(td.to_string(index=False))

print("\n" + "=" * 100)
print("CURVE QC")
print("=" * 100)
cq = pd.read_csv(p("curve_qc"))
print(cq.to_string(index=False))

print("\n" + "=" * 100)
print("BASIC FACTS (item 1) -- key rows")
print("=" * 100)
bf = pd.read_csv(p("basic_facts"))
key_metrics = ["frac_cells_active_gt_bp", "frac_dpar_exactly_zero", "frac_dates_flagged_flow_day",
              "pooled_autocorr_lag1_cusip_demeaned_unaligned", "pooled_autocorr_lag1_cusip_demeaned_aligned",
              "mean_per_cusip_autocorr_lag1", "median_per_cusip_autocorr_lag1",
              "P(same_sign_trade_next_day | |active_bp|>1bp today, unaligned)",
              "P(same_sign_trade_next_day | |aligned_bp|>1bp today, aligned)"]
print(bf[bf["metric"].isin(key_metrics)].to_string(index=False))
print("\nactive_bp percentiles:")
print(bf[bf["metric"].str.startswith("active_bp_pctile")].to_string(index=False))

print("\n" + "=" * 100)
print("PRICE IMPACT (item 2)")
print("=" * 100)
pi = pd.read_csv(p("price_impact"))
print(pi.to_string(index=False))

print("\n" + "=" * 100)
print("REVERSAL/CONTINUATION (items 3/4): best thesis cells per ticker/family")
print("=" * 100)
ic = pd.read_csv(p("ic_table"))
thesis = ic[ic["family"].isin(["active", "aligned"])].dropna(subset=["q_spread_bp"])
best_rows = []
for (tkr, fam), g in thesis.groupby(["ticker", "family"]):
    row = g.loc[g["q_spread_bp"].abs().idxmax()]
    best_rows.append(row)
best_df = pd.DataFrame(best_rows).sort_values(["ticker", "family"])
cols = ["ticker", "family", "k_days", "exec_lag", "true_lag", "horizon", "kind",
       "ic_mean", "ic_t", "q_spread_bp", "q_spread_t", "q_n_dates"]
print(best_df[cols].to_string(index=False))
best_df["mult_of_cost"] = best_df["q_spread_bp"].abs() / COST_BP
print("\nmultiple of cost (q_spread_bp / 0.5bp):")
print(best_df[["ticker", "family", "q_spread_bp", "mult_of_cost"]].to_string(index=False))

print("\nnull (raw/expected) best per ticker, for reference:")
nullc = ic[ic["family"].isin(["raw", "expected"])].dropna(subset=["q_spread_bp"])
null_best = nullc.loc[nullc.groupby("ticker")["q_spread_bp"].apply(lambda s: s.abs().idxmax())]
print(null_best[cols].to_string(index=False))

print("\n" + "=" * 100)
print("CALENDAR NULL (deletion/addition) -- max |q_spread_bp| per ticker, for scrape-bought-nothing test")
print("=" * 100)
cal = pd.read_csv(p("calendar_null")).dropna(subset=["q_spread_bp"])
cal_best = cal.loc[cal.groupby("ticker")["q_spread_bp"].apply(lambda s: s.abs().idxmax())]
print(cal_best.to_string(index=False))

print("\n" + "=" * 100)
print("LOOKAHEAD CHECK (item 5) -- lag 0 (illegal, diagnostic) vs 1/2 (legal)")
print("=" * 100)
la = pd.read_csv(p("lookahead_check"))
print(la.to_string(index=False))

print("\n" + "=" * 100)
print("FLOW-DAY ROBUSTNESS -- best cell re-run excluding flow days")
print("=" * 100)
rb = pd.read_csv(p("flow_day_robustness"))
print(rb.to_string(index=False))

print("\n" + "=" * 100)
print("YEARLY STABILITY -- best cell sign by year")
print("=" * 100)
yr = pd.read_csv(p("yearly_stability"))
for (tkr, cfg), g in yr.groupby(["ticker", "config"]):
    g = g.sort_values("year")
    n_pos = (g["q_spread_bp"] > 0).sum()
    n_neg = (g["q_spread_bp"] < 0).sum()
    print(f"{tkr} {cfg}: {n_pos} positive / {n_neg} negative years (of {len(g)})")

print("\n" + "=" * 100)
print("FUNNEL")
print("=" * 100)
fn = pd.read_csv(p("funnel"))
print(fn.to_string(index=False))

cc_path = p("config_count").replace(".csv", ".txt")
if os.path.exists(cc_path):
    print("\n" + "=" * 100)
    print("CONFIG COUNT")
    print("=" * 100)
    print(open(cc_path).read())
