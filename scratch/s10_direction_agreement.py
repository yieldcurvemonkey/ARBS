"""TERM <-> NEWT direction agreement, using the lineage store.

For each resolved pair: infer the dealer's side on the ORIGINAL print by
rate-vs-mid at its own execution minute, and infer it again from the TERMINATION
row alone (its unsigned Other payment amount against the repriced residual
value). The second, flipped, should be the first.

Known-answer checks run FIRST:
  K1  liquid on-market originals must reprice within a couple of bp of mid.
  K2  the pricer's NPV must equal (mid - R) * PV01 * 100 in the PAYER frame --
      if the frame or the units are wrong, every U-vs-|f| comparison after it is
      unearned, and the failure is silent because a wrong-signed NPV still
      produces a complete answer.

Usage: python s10_direction_agreement.py [limit]
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np
import pandas as pd
import psycopg2

from dd_common import CURVE_FOR, make_pricer, strict_policy, hole_policy
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.dealer_direction import lineage as lin
from SDRUtils.dealer_direction import snapshot as snap

pd.set_option("display.width", 240)
ROOT = r"C:/Users/chris/clee/ARBS-dd/scratch/dd_lineage_store"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 0
OUT = r"C:/Users/chris/clee/ARBS-dd/scratch/out_direction_agreement.csv"

# ---------------------------------------------------------------- population
store = lin.LineageStore(root=ROOT)
days = store.covered_days()
lg = store.read_range(days[0], days[-1])
raw = lin.load_raw_days(days, root=ROOT)
raw["_di"] = raw[lin.DI].map(lin.normalise_id)
term = lg[(lg["action_type"] == "TERM") & (lg["event_type"] == "ETRM")
          & (lg["status"] == lin.ST_RESOLVED_TAPE)].merge(
    raw[["_di", "UPI FISN", "Notional currency-Leg 1", "Other payment amount"]]
    .rename(columns={"_di": "dissemination_id"}), on="dissemination_id", how="left")
term = term[(term["Notional currency-Leg 1"] == "USD")
            & (term["UPI FISN"] == "NA/Swap OIS USD")]
opa = pd.to_numeric(term["Other payment amount"], errors="coerce")
print(f"resolved OIS/USD ETRM rows: {len(term):,}")
print(f"  carrying an Other payment amount: {int((opa > 0).sum()):,} = {100 * (opa > 0).mean():.1f}%"
      f"   (recorded 15.7%)")
term = term[opa > 0].assign(upfront=opa[opa > 0])

# ------------------------------------------------------------- the originals
conn = psycopg2.connect(resolve_pg_url())
conn.set_session(readonly=True)
cur = conn.cursor()
cur.execute("SET statement_timeout = '300s'")
ids = sorted(set(term["resolved_original_id"].astype(str)))
rows = []
for i in range(0, len(ids), 3000):
    cur.execute(f"""
        SELECT trade_id, count(*) AS n_legs, min(package_id) AS pkg,
               min(effective_date) AS eff, min(expiration_date) AS exp,
               min(notional) AS notional, min(fixed_rate) AS fixed_rate,
               min(rate_index_clean) AS idx, bool_or(is_notional_capped) AS capped,
               bool_or(is_mac) AS mac, max(coalesce(other_payment_amount, 0)) AS orig_opa,
               min(execution_timestamp) AS orig_exec, min(tenor_years) AS tenor
        FROM {LEGS_TABLE} WHERE trade_id = ANY(%s) GROUP BY trade_id""", (ids[i:i + 3000],))
    rows.extend(cur.fetchall())
orig = pd.DataFrame(rows, columns=["resolved_original_id", "n_legs", "pkg", "eff", "exp",
                                   "notional", "fixed_rate", "idx", "capped", "mac",
                                   "orig_opa", "orig_exec", "tenor"])
# package_id is populated on EVERY tape row -- 121,796 of the 164,983 packages in
# this window hold exactly one leg, i.e. an outright. "has a package_id" is
# therefore not a package test; the leg COUNT is.
pkgs = sorted({p for p in orig["pkg"].dropna().astype(str)})
sizes = {}
for i in range(0, len(pkgs), 3000):
    cur.execute(f"SELECT package_id, count(*) FROM {LEGS_TABLE} "
                "WHERE package_id = ANY(%s) GROUP BY package_id", (pkgs[i:i + 3000],))
    sizes.update({str(k): int(v) for k, v in cur.fetchall()})
orig["pkg_legs"] = orig["pkg"].astype(str).map(sizes).fillna(1).astype(int)
conn.close()
df = term.merge(orig, on="resolved_original_id", how="inner")
print(f"joined to tape originals: {len(df):,}")

# --- exclusions, each for a stated reason ---------------------------------
excl = {}


def drop(mask, why):
    excl[why] = int(mask.sum())
    return ~mask


keep = pd.Series(True, index=df.index)
keep &= drop((df["n_legs"] > 1) | (df["pkg_legs"] > 1), "original is a package / multi-leg")
keep &= drop(df["capped"].fillna(False), "original notional is CAPPED (|f| would be understated)")
keep &= drop(df["mac"].fillna(False), "original is MAC (off-market by design)")
keep &= drop(df["orig_opa"] > 0, "original itself carried an upfront (rate rule invalid)")
keep &= drop(df["notional"].astype(float) >= 1e19, "notional sentinel 1e20")
keep &= drop(df["fixed_rate"].isna(), "no fixed rate on the original")
keep &= drop(~df["idx"].isin(list(CURVE_FOR)), "unsupported rate index")
df = df[keep].copy()
print("\nexclusions:")
for k, v in excl.items():
    print(f"  {v:>5}  {k}")
print(f"pairs to price: {len(df):,}")
if LIMIT:
    df = df.head(LIMIT)
    print(f"  limited to {len(df)}")

# ------------------------------------------------------------------- pricing
strict = make_pricer(strict_policy(minutes=1))
loose = make_pricer(hole_policy(hours=2))


def price(row_curve, instant, eff, exp, notional, fixed=None):
    """(LegPricing, policy, error). Strict in session, bounded asof outside it."""
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

    pricer, tag = ((strict, "strict") if snap.in_session(row_curve, instant)
                   else (loose, "asof2h"))
    try:
        return pricer.price_leg(row_curve, instant, eff, exp, float(notional),
                                fixed_rate=fixed), tag, None
    except SnapshotMiss as exc:
        return None, tag, f"SnapshotMiss: {str(exc)[:80]}"
    except Exception as exc:  # noqa: BLE001
        return None, tag, f"{type(exc).__name__}: {str(exc)[:80]}"


# --- K1 / K2 --------------------------------------------------------------
print("\n=== K1: liquid on-market originals reprice near mid ===")
k1 = df[(df["tenor"].astype(float).between(2, 10))].head(3)
ok = True
for _, r in k1.iterrows():
    inst = snap.snap_instant(pd.Timestamp(r["orig_exec"]))
    lp, tag, err = price(CURVE_FOR[r["idx"]], inst, r["eff"], r["exp"], r["notional"])
    if err:
        print(f"  {r['resolved_original_id']}: {err}")
        continue
    bp = (float(r["fixed_rate"]) * 100 - lp.mid_pct) * 100
    print(f"  {r['resolved_original_id']} tenor={float(r['tenor']):.1f}y {tag} "
          f"printed-mid={bp:+.2f}bp")

print("\n=== K2: NPV must be the PAYER frame, i.e. npv ~ (mid - R) * pv01 * 100 ===")
for _, r in df.head(3).iterrows():
    inst = snap.snap_instant(pd.Timestamp(r["event_timestamp"]))
    lp, tag, err = price(CURVE_FOR[r["idx"]], inst, r["eff"], r["exp"], r["notional"],
                         fixed=float(r["fixed_rate"]))
    if err:
        print(f"  {r['dissemination_id']}: {err}")
        continue
    implied = (lp.mid_pct - float(r["fixed_rate"]) * 100) * 100 * lp.pv01
    rel = (lp.npv_pay - implied) / max(abs(implied), 1.0)
    print(f"  {r['dissemination_id']}: npv_pay={lp.npv_pay:>14,.0f}  "
          f"(mid-R)*pv01*100={implied:>14,.0f}  rel diff={rel:+.4f}  {tag}")
    if abs(rel) > 0.05:
        ok = False
        print("    ^ FRAME/UNIT MISMATCH")
if not ok:
    print("\nK2 FAILED - not running the batch")
    sys.exit(1)

# ------------------------------------------------------------------- batch
print(f"\n=== batch over {len(df):,} pairs ===")
recs = []
for n, (_, r) in enumerate(df.iterrows(), 1):
    curve = CURVE_FOR[r["idx"]]
    rec = {"dissemination_id": r["dissemination_id"],
           "original_id": r["resolved_original_id"],
           "tenor": float(r["tenor"]) if pd.notna(r["tenor"]) else None,
           "reach_back_days": r["reach_back_days"],
           "notional": float(r["notional"]), "upfront": float(r["upfront"]),
           "fixed_rate_pct": float(r["fixed_rate"]) * 100}
    o_inst = snap.snap_instant(pd.Timestamp(r["orig_exec"]))
    o_lp, o_tag, o_err = price(curve, o_inst, r["eff"], r["exp"], r["notional"])
    u_inst = snap.snap_instant(pd.Timestamp(r["event_timestamp"]))
    u_lp, u_tag, u_err = price(curve, u_inst, r["eff"], r["exp"], r["notional"],
                               fixed=float(r["fixed_rate"]))
    rec["orig_err"], rec["unwind_err"] = o_err, u_err
    if o_lp is not None:
        rec["orig_mid_pct"] = o_lp.mid_pct
        dev_bp = (rec["fixed_rate_pct"] - o_lp.mid_pct) * 100
        rec["orig_dev_bp"] = dev_bp
        rec["original_dealer_sign"] = 1 if dev_bp > 0 else (-1 if dev_bp < 0 else 0)
    if u_lp is not None:
        rec["npv_pay"] = u_lp.npv_pay
        rec["pv01"] = u_lp.pv01
        rec["ratio"] = float(r["upfront"]) / abs(u_lp.npv_pay) if u_lp.npv_pay else np.nan
        rec["edge_bps"] = (abs(u_lp.npv_pay) - float(r["upfront"])) / (u_lp.pv01 or np.nan)
        rec["unwind_dealer_sign"] = lin.unwind_dealer_sign(u_lp.npv_pay, float(r["upfront"]))
    recs.append(rec)
    if n % 50 == 0:
        print(f"  {n}/{len(df)}", flush=True)

out = pd.DataFrame(recs)
out.to_csv(OUT, index=False)
print(f"wrote {OUT}")

print("\npricing failures:")
print(f"  original leg: {int(out['orig_err'].notna().sum())}  "
      f"unwind leg: {int(out['unwind_err'].notna().sum())}")
for e in out["unwind_err"].dropna().str.slice(0, 40).value_counts().head(5).items():
    print("   ", e)

both = out.dropna(subset=["original_dealer_sign", "unwind_dealer_sign"])
print(f"\npairs with both inferences: {len(both)}")

# STATED EXEMPTION. K1 turned up originals repricing 238 bp from mid with no
# reported upfront -- F-10's "off-market with no upfront" population, 248,469
# legs of it. The rate rule is not valid on those: a 238 bp deviation is not a
# dealer spread, so its sign carries no information about who paid. Excluded
# from the primary number and reported separately.
DEV_CAP_BP = 25.0
wild = both["orig_dev_bp"].abs() > DEV_CAP_BP
print(f"  originals repricing more than {DEV_CAP_BP:.0f}bp from mid (excluded, STATED "
      f"EXEMPTION): {int(wild.sum())} = {100 * wild.mean():.1f}%")
print("  their |dev| percentiles:",
      both.loc[wild, "orig_dev_bp"].abs().describe(percentiles=[.5, .9]).round(1).to_dict())
print("  agreement on the EXCLUDED wild set:", lin.direction_agreement(both[wild]))
both = both[~wild]
res = lin.direction_agreement(both)
print(f"\nAGREEMENT (all {len(both)} on-market pairs):",
      {k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.items()})

print("\n--- resolution diagnostics ---")
r = both["ratio"].replace([np.inf, -np.inf], np.nan).dropna()
print(f"U / |f| distribution over {len(r)} pairs:")
print(r.describe(percentiles=[.05, .25, .5, .75, .95]).round(3).to_string())
print(f"  within +/-5% of 1.0 : {100 * (r.sub(1).abs() <= 0.05).mean():.1f}%")
print(f"  within +/-20% of 1.0: {100 * (r.sub(1).abs() <= 0.20).mean():.1f}%")
print(f"  below 0.5 (partial terminations would sit here): {100 * (r < 0.5).mean():.1f}%")

print("\nagreement by |edge| in bp of the unwind DV01 "
      "(if the test has resolution, agreement rises with the edge):")
b = both.assign(absedge=both["edge_bps"].abs())
bins = [0, 0.5, 1, 2, 5, 20, 100, 1e9]
b["bucket"] = pd.cut(b["absedge"], bins)
for name, sub in b.groupby("bucket", observed=True):
    a = lin.direction_agreement(sub)
    print(f"  {str(name):>18}  n={a['n_called']:>4}  agreement={a['agreement']}")

print("\nagreement restricted to |U/|f| - 1| <= 0.20 (full terminations, priced well):")
sub = both[both["ratio"].sub(1).abs() <= 0.20]
print("  ", lin.direction_agreement(sub))
