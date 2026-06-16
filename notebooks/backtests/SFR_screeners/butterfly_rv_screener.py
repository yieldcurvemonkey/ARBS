"""SOFR Butterfly Relative Value Screener — 3 Layers.

Layer 1: Variance consistency (BKM model-free moments)
Layer 2: Probability space (kink sharpness vs distributional width)
Layer 3: Fragility (tail sensitivity of the weakest leg)
"""

import datetime
import math
import sys
import warnings

sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

import numpy as np
import pandas as pd
import QuantLib as ql

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import get_fomc_meetings_list
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from RVUtils.ImpliedDistribution import SFRImpliedDistribution

import pytz
NYC_tz = pytz.timezone("America/New_York")

# ─── Config ───────────────────────────────────────────────────────────────────
AS_OF = datetime.date(2026, 5, 27)
CURVE = "USD-SOFR-1D-Q12STIRT"

# Butterfly spacings: legs are `spacing` quarters apart.
# 1 = 3mo (consecutive), 2 = 6mo, 3 = 9mo, 4 = 12mo gap fly.
# A 6mo gap fly has legs 2 quarters apart, e.g. M6-Z6-M7 (+1 M6, -2 Z6, +1 M7).
SPACINGS = {1: "3mo", 2: "6mo", 3: "9mo", 4: "12mo"}

IMM_TENORS = [
    "IMM_1xIMM_2", "IMM_2xIMM_3", "IMM_3xIMM_4", "IMM_4xIMM_5",
    "IMM_5xIMM_6", "IMM_6xIMM_7", "IMM_7xIMM_8", "IMM_8xIMM_9",
    "IMM_9xIMM_10", "IMM_10xIMM_11", "IMM_11xIMM_12", "IMM_12xIMM_13",
]

IMM_CODE_TO_SFR = {
    "M6": "SFRM26", "U6": "SFRU26", "Z6": "SFRZ26",
    "H7": "SFRH27", "M7": "SFRM27", "U7": "SFRU27", "Z7": "SFRZ27",
    "H8": "SFRH28", "M8": "SFRM28", "U8": "SFRU28", "Z8": "SFRZ28",
    "H9": "SFRH29",
}

# ─── Step 1: Fetch curve and compute butterflies ──────────────────────────────
print("=" * 76)
print(f"SOFR BUTTERFLY RV SCREENER | as_of = {AS_OF}")
print("=" * 76)

ts = NYC_tz.localize(datetime.datetime.combine(AS_OF, datetime.time(17, 0)))
curve_mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
curve_handle = curve_mdp.get_pricer(request=dict(curve_name=CURVE, timestamp=ts))

contracts = []
prices = []
rates = []

for t in IMM_TENORS:
    q = IRSwapQuery(curve=CURVE, tenor=t).resolve_query(ts, pricer_or_curve=curve_handle)
    pkg, _ = q.resolve_package(pricer_or_curve=curve_handle)
    eff = pkg[0].__dict__["kwargs"]["effective"]
    price = 100 - pkg[0].__dict__["kwargs"]["fixed_rate"]
    rate = pkg[0].__dict__["kwargs"]["fixed_rate"] * 100  # in percent
    imm = ql.IMM.code(ql.Date(eff.day, eff.month, eff.year))
    contracts.append(imm)
    prices.append(price)
    rates.append(rate)

print(f"\nStrip ({len(contracts)} contracts): {' '.join(contracts)}")
print(f"Rate range: {min(rates):.3f}% - {max(rates):.3f}%\n")

# Calendar spreads (bps, price space: near − deferred) — consecutive (3mo)
cal_spreads = {}
for i in range(len(contracts) - 1):
    name = f"SP {contracts[i]}-{contracts[i+1]}"
    val = (prices[i] - prices[i+1]) * 10000
    cal_spreads[name] = val

# Butterflies for each spacing: spacing=1 → 3mo fly, spacing=2 → 6mo gap fly.
# Legs are i, i+spacing, i+2*spacing. Spreads span `spacing` quarters each.
butterflies = []
for spacing, gap_label in SPACINGS.items():
    for i in range(len(contracts) - 2 * spacing):
        ni, mi, fi = i, i + spacing, i + 2 * spacing
        near, mid, far = contracts[ni], contracts[mi], contracts[fi]
        bf_val = (prices[ni] - 2 * prices[mi] + prices[fi]) * 10000
        sp_near = (prices[ni] - prices[mi]) * 10000
        sp_far = (prices[mi] - prices[fi]) * 10000
        butterflies.append({
            "name": f"BF {near}-{mid}-{far}",
            "gap": gap_label,
            "spacing": spacing,
            "near": near, "mid": mid, "far": far,
            "near_symbol": IMM_CODE_TO_SFR[near],
            "mid_symbol": IMM_CODE_TO_SFR[mid],
            "far_symbol": IMM_CODE_TO_SFR[far],
            "bf_bps": bf_val,
            "sp_near_bps": sp_near,
            "sp_far_bps": sp_far,
            "near_rate": rates[ni],
            "mid_rate": rates[mi],
            "far_rate": rates[fi],
        })

print("Calendar Spreads (bps):")
for k, v in cal_spreads.items():
    print(f"  {k}: {v:+.2f}")

for spacing, gap_label in SPACINGS.items():
    print(f"\n{gap_label.upper()} Butterflies (bps):")
    for bf in butterflies:
        if bf["spacing"] == spacing:
            print(f"  {bf['name']}: {bf['bf_bps']:+.2f}")

# ─── Step 2: FOMC meeting overlay ───��────────────────────────────────────────
fomc_dates_raw = get_fomc_meetings_list(as_of=AS_OF, n_plus_years=2)
fomc_dates = []
for d in fomc_dates_raw:
    if hasattr(d, 'date') and not isinstance(d, datetime.date):
        d = d.date()
    elif isinstance(d, datetime.datetime):
        d = d.date()
    fomc_dates.append(d)
fomc_dates = [d for d in fomc_dates if d > AS_OF]

# Map IMM codes to their accrual windows (approximate: IMM month start)
IMM_MONTH_MAP = {"H": 3, "M": 6, "U": 9, "Z": 12}

def imm_to_approx_dates(code: str):
    """Return approximate (start, end) dates for an IMM quarter."""
    month_char = code[0]
    year = 2020 + int(code[1])
    month = IMM_MONTH_MAP[month_char]
    start = datetime.date(year, month, 15)
    end_month = month + 3
    end_year = year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    end = datetime.date(end_year, end_month, 15)
    return start, end

def count_fomc_in_window(start, end, fomc_list):
    return sum(1 for d in fomc_list if start <= d < end)

for bf in butterflies:
    near_start, near_end = imm_to_approx_dates(bf["near"])
    mid_start, mid_end = imm_to_approx_dates(bf["mid"])
    far_start, far_end = imm_to_approx_dates(bf["far"])
    # Per-leg accrual-quarter meetings (used for asymmetry detection)
    bf["fomc_near"] = count_fomc_in_window(near_start, near_end, fomc_dates)
    bf["fomc_mid"] = count_fomc_in_window(mid_start, mid_end, fomc_dates)
    bf["fomc_far"] = count_fomc_in_window(far_start, far_end, fomc_dates)
    bf["fomc_total"] = bf["fomc_near"] + bf["fomc_mid"] + bf["fomc_far"]
    # Gap-window meetings: for gap flies the curvature is driven by meetings
    # BETWEEN the legs. near_gap = meetings from near-leg start to mid-leg start;
    # far_gap = mid-leg start to far-leg start. For 3mo flies these ~= per-leg.
    bf["fomc_near_gap"] = count_fomc_in_window(near_start, mid_start, fomc_dates)
    bf["fomc_far_gap"] = count_fomc_in_window(mid_start, far_start, fomc_dates)

# ─── Step 3: Fetch SABR smiles and compute BKM + BL moments ──────────────────
print("\n" + "-" * 76)
print("Fetching SABR smiles and computing BKM/BL moments...")
print("-" * 76)

stirfo_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")

# Use SABR extrapolation for dense strike grid (200 pts).
# If delta-mode SABR fails (thin liquidity on far contracts), fall back to
# listed strikes which fetch directly from Barchart.
dist = SFRImpliedDistribution(
    use_sabr_vols=True,
    sabr_extrapolation=True,
    sabr_n_strikes=200,
)

# Minimum std (bps) for a leg to be "informative" in variance comparisons.
# Below this, the contract is near-expiry and its variance is mechanically
# collapsing — any "excess" at neighboring legs is trivially true.
MIN_INFORMATIVE_STD_BPS = 25.0

smile_cache = {}
moment_cache = {}

all_symbols = set()
for bf in butterflies:
    all_symbols.update([bf["near_symbol"], bf["mid_symbol"], bf["far_symbol"]])

for sym in sorted(all_symbols):
    smile = None
    # Try delta-mode SABR first (fast, uses ~10 strikes)
    for attempt, fetch_kwargs in enumerate([
        {"symbol": sym, "as_of": AS_OF, "show_tqdm": False},
        {"symbol": sym, "as_of": AS_OF, "strike_offsets_bps": "listed", "show_tqdm": False},
    ]):
        try:
            smile = stirfo_mdp.fetch_sabr_smile(fetch_kwargs)
            break
        except Exception as e:
            if attempt == 0:
                pass  # silently try listed-strike fallback
            else:
                print(f"  {sym}: FAILED (both delta and listed) - {e}")

    if smile is None:
        moment_cache[sym] = None
        continue

    smile_cache[sym] = smile
    try:
        snapshot = dist.extract(smile, run_bl=True, run_gm=False, run_bkm=True)
        moment_cache[sym] = {
            "bkm": snapshot.bkm_result,
            "bl": snapshot.bl_result,
            "forward_rate": smile.params.forward_rate,
            "tte": smile.params.time_to_expiry,
        }
        bkm = snapshot.bkm_result
        bl = snapshot.bl_result
        tte_days = int(smile.params.time_to_expiry * 365)
        print(f"  {sym}: fwd={smile.params.forward_rate:.4f}% "
              f"BKM_std={bkm.std_rate*100:.1f}bps "
              f"BL_std={bl.std_rate*100:.1f}bps "
              f"skew={bkm.skewness_rate:+.3f} "
              f"TTE={tte_days}d "
              f"n_pts={len(smile.points)}")
    except Exception as e:
        print(f"  {sym}: smile OK but extraction FAILED - {e}")
        moment_cache[sym] = None

# ─── Step 4: Layer 1 — Variance Consistency ──────────────────────────────────
print("\n" + "=" * 76)
print("LAYER 1: VARIANCE CONSISTENCY (BKM model-free moments)")
print("=" * 76)

for bf in butterflies:
    m_near = moment_cache.get(bf["near_symbol"])
    m_mid = moment_cache.get(bf["mid_symbol"])
    m_far = moment_cache.get(bf["far_symbol"])

    if m_near and m_mid and m_far and m_near["bkm"] and m_mid["bkm"] and m_far["bkm"]:
        var_near = m_near["bkm"].variance_rate
        var_mid = m_mid["bkm"].variance_rate
        var_far = m_far["bkm"].variance_rate

        var_interp = (var_near + var_far) / 2.0
        var_excess = var_mid - var_interp

        std_near = m_near["bkm"].std_rate * 100
        std_mid = m_mid["bkm"].std_rate * 100
        std_far = m_far["bkm"].std_rate * 100
        std_interp = (std_near + std_far) / 2.0
        std_excess = std_mid - std_interp

        fly_abs = max(abs(bf["bf_bps"]), 0.5)
        var_signal = std_excess / fly_abs

        # Time-adjusted std excess: under constant vol, std ~ sigma*sqrt(T).
        # Extract implied vol at each leg: vol_i = std_i / sqrt(T_i)
        # Interpolate vol linearly at T_mid, then compute expected std.
        # Excess relative to this sqrt(T)-adjusted benchmark is the true signal.
        tte_near = max(m_near["tte"], 1e-6)
        tte_mid = max(m_mid["tte"], 1e-6)
        tte_far = max(m_far["tte"], 1e-6)

        vol_near = std_near / math.sqrt(tte_near)
        vol_far = std_far / math.sqrt(tte_far)

        # Linear interpolation of implied vol in TTE space
        w = (tte_mid - tte_near) / max(tte_far - tte_near, 1e-6)
        vol_interp = vol_near * (1 - w) + vol_far * w
        std_interp_adj = vol_interp * math.sqrt(tte_mid)

        std_excess_adj = std_mid - std_interp_adj
        var_signal_adj = std_excess_adj / fly_abs

        bf["var_near"] = var_near
        bf["var_mid"] = var_mid
        bf["var_far"] = var_far
        bf["var_interp"] = var_interp
        bf["var_excess"] = var_excess
        bf["std_near"] = std_near
        bf["std_mid"] = std_mid
        bf["std_far"] = std_far
        bf["std_interp"] = std_interp
        bf["std_excess"] = std_excess
        bf["var_signal"] = var_signal
        bf["tte_near"] = tte_near
        bf["tte_mid"] = tte_mid
        bf["tte_far"] = tte_far
        bf["std_interp_adj"] = std_interp_adj
        bf["std_excess_adj"] = std_excess_adj
        bf["var_signal_adj"] = var_signal_adj

        # Near-expiry filter still applies (dead leg makes any comparison noisy)
        near_dead = std_near < MIN_INFORMATIVE_STD_BPS
        tte_imbalanced = std_near < (std_mid * 0.6)
        bf["near_expiry_distorted"] = near_dead or tte_imbalanced
        if near_dead:
            bf["var_signal_note"] = (
                f"MECHANICAL: near leg {bf['near']} std={std_near:.0f}bps < {MIN_INFORMATIVE_STD_BPS:.0f}bps. "
                f"Near-dead leg makes interpolation meaningless."
            )
        elif tte_imbalanced:
            bf["var_signal_note"] = (
                f"TTE-IMBALANCED: near leg {bf['near']} std={std_near:.0f}bps < 60% of mid "
                f"std={std_mid:.0f}bps. Linear interp underestimates mid due to sqrt(T) scaling. "
                f"Time-adjusted excess ({std_excess_adj:+.1f}bps) is the proper signal."
            )
        else:
            bf["var_signal_note"] = None
    else:
        bf["var_excess"] = None
        bf["var_signal"] = None
        bf["std_near"] = None
        bf["std_mid"] = None
        bf["std_far"] = None
        bf["std_excess"] = None
        bf["std_excess_adj"] = None
        bf["var_signal_adj"] = None
        bf["near_expiry_distorted"] = False
        bf["var_signal_note"] = None

# ─── Step 5: Layer 2 — Probability Space ─────────────────────────────────────
print("\n" + "=" * 76)
print("LAYER 2: PROBABILITY SPACE (kink sharpness vs distributional width)")
print("=" * 76)

for bf in butterflies:
    # Probability of a 25bp move in each quarter
    prob_near = bf["sp_near_bps"] / 25.0
    prob_far = bf["sp_far_bps"] / 25.0
    prob_change = (prob_near - prob_far)  # = butterfly / 25
    bf["prob_near"] = prob_near
    bf["prob_far"] = prob_far
    bf["prob_change"] = prob_change

    # Kink sharpness: |butterfly / 25| as percentage points
    bf["kink_pp"] = abs(bf["bf_bps"] / 25.0) * 100

    # Compare kink sharpness to distributional width at the middle leg
    m_mid = moment_cache.get(bf["mid_symbol"])
    if m_mid and m_mid["bkm"]:
        mid_std_bps = m_mid["bkm"].std_rate * 100
        # Kink-to-width ratio: how sharp is the kink relative to the
        # uncertainty at the middle leg? High ratio = market is very
        # confident about timing, low ratio = kink is small vs uncertainty
        bf["kink_width_ratio"] = abs(bf["bf_bps"]) / max(mid_std_bps, 1.0)
        bf["mid_std_bps"] = mid_std_bps
    else:
        bf["kink_width_ratio"] = None
        bf["mid_std_bps"] = None

# ─── Step 6: Layer 3 — Fragility ─────────────────────────────────────────────
print("\n" + "=" * 76)
print("LAYER 3: FRAGILITY (tail sensitivity of weakest leg)")
print("=" * 76)

TAIL_SHIFT_PCT = 0.01  # 1% probability mass migration

for bf in butterflies:
    m_near = moment_cache.get(bf["near_symbol"])
    m_mid = moment_cache.get(bf["mid_symbol"])
    m_far = moment_cache.get(bf["far_symbol"])

    if m_near and m_mid and m_far and m_near["bkm"] and m_mid["bkm"] and m_far["bkm"]:
        # Approximate how much the mean shifts under 1% tail migration
        # delta_mean ≈ tail_shift_pct × 4σ (covers ~95% of distribution)
        range_near = 4.0 * m_near["bkm"].std_rate * 100  # bps
        range_mid = 4.0 * m_mid["bkm"].std_rate * 100
        range_far = 4.0 * m_far["bkm"].std_rate * 100

        delta_near = TAIL_SHIFT_PCT * range_near
        delta_mid = TAIL_SHIFT_PCT * range_mid
        delta_far = TAIL_SHIFT_PCT * range_far

        # Butterfly sensitivity to tail shift
        fly_sensitivity = abs(delta_near - 2 * delta_mid + delta_far)
        fly_abs = max(abs(bf["bf_bps"]), 0.5)
        fragility = fly_sensitivity / fly_abs

        # Also compute which leg is the "weakest" (widest distribution)
        widths = {"near": range_near, "mid": range_mid, "far": range_far}
        weakest_leg = max(widths, key=widths.get)

        bf["fragility"] = fragility
        bf["fly_sensitivity_bps"] = fly_sensitivity
        bf["weakest_leg"] = weakest_leg
        bf["range_near"] = range_near
        bf["range_mid"] = range_mid
        bf["range_far"] = range_far
    else:
        bf["fragility"] = None
        bf["weakest_leg"] = None

# ─── Step 7: Composite Signal & Output ───────────────────────────────────────
print("\n" + "=" * 76)
print("COMPOSITE SCREENER RESULTS")
print("=" * 76)

# Build DataFrame
rows = []
for bf in butterflies:
    row = {
        "Butterfly": bf["name"],
        "Gap": bf["gap"],
        "Level (bps)": bf["bf_bps"],
        "Prob Δ (pp)": bf["bf_bps"] / 25.0 * 100 if bf["bf_bps"] else 0,
        "Std Near": bf.get("std_near"),
        "Std Mid": bf.get("std_mid"),
        "Std Far": bf.get("std_far"),
        "Std Excess": bf.get("std_excess"),
        "Adj Excess": bf.get("std_excess_adj"),
        "Var Signal": bf.get("var_signal"),
        "Adj Signal": bf.get("var_signal_adj"),
        "Kink/Width": bf.get("kink_width_ratio"),
        "Fragility": bf.get("fragility"),
        "Weakest": bf.get("weakest_leg"),
        "FOMC (N/M/F)": f"{bf.get('fomc_near',0)}/{bf.get('fomc_mid',0)}/{bf.get('fomc_far',0)}",
    }
    rows.append(row)

df = pd.DataFrame(rows)

# Print detailed results, grouped by gap
print(f"\n{'Butterfly':<16} {'Gap':>4} {'Level':>6} {'Prob':>5} {'Std_N':>5} {'Std_M':>5} {'Std_F':>5} {'StdExc':>6} {'AdjExc':>6} {'VarSig':>6} {'AdjSig':>6} {'K/W':>5} {'Frag':>5} {'FOMC':>7}")
print("-" * 124)
prev_gap = None
for _, r in df.iterrows():
    if r["Gap"] != prev_gap:
        print(f"  --- {r['Gap']} gap flies ---")
        prev_gap = r["Gap"]
    std_n = f"{r['Std Near']:.0f}" if r['Std Near'] is not None else "-"
    std_m = f"{r['Std Mid']:.0f}" if r['Std Mid'] is not None else "-"
    std_f = f"{r['Std Far']:.0f}" if r['Std Far'] is not None else "-"
    std_exc = f"{r['Std Excess']:+.1f}" if r['Std Excess'] is not None else "-"
    adj_exc = f"{r['Adj Excess']:+.1f}" if r.get('Adj Excess') is not None else "-"
    var_sig = f"{r['Var Signal']:+.2f}" if r['Var Signal'] is not None else "-"
    adj_sig = f"{r['Adj Signal']:+.2f}" if r.get('Adj Signal') is not None else "-"
    kw = f"{r['Kink/Width']:.3f}" if r['Kink/Width'] is not None else "-"
    frag = f"{r['Fragility']:.3f}" if r['Fragility'] is not None else "-"
    print(f"{r['Butterfly']:<16} {r['Gap']:>4} {r['Level (bps)']:+6.1f} {r['Prob Δ (pp)']:+5.0f} {std_n:>5} {std_m:>5} {std_f:>5} {std_exc:>6} {adj_exc:>6} {var_sig:>6} {adj_sig:>6} {kw:>5} {frag:>5} {r['FOMC (N/M/F)']:>7}")

# ─── Interpretation ──────────────────────────────────────────────────────────
print("\n" + "=" * 76)
print("SIGNAL INTERPRETATION")
print("=" * 76)

print("""
Column guide:
  Level (bps)  : Futures butterfly value in price-space basis points
  Prob Δ (pp)  : Change in implied probability of 25bp move (percentage points)
  Std N/M/F    : BKM-implied std dev (bps) at near/mid/far legs
  Std Excess   : Mid std minus linear interpolation of wings (bps)
                 Positive = mid has MORE uncertainty than neighbors
                 Negative = mid has LESS uncertainty than neighbors
  Var Signal   : Variance excess normalized by fly level
                 Large positive → fly should be CHEAPER (sell signal)
                 Large negative → fly should be RICHER (buy signal)
  K/W          : Kink-to-width ratio (fly level / mid std)
                 High = market has strong timing conviction
                 Low = kink is small relative to uncertainty
  Fragility    : Sensitivity of fly to 1% tail mass shift / fly level
                 >0.5 = HIGH fragility → size down
                 <0.2 = LOW fragility → conviction sizing OK
  Weakest      : Which leg has the widest distribution (drives fragility)
  FOMC (N/M/F) : # of FOMC meetings in near/mid/far quarters
                 Asymmetric FOMC loading justifies structural curvature
""")

# ─── Flag actionable signals ─────────────────────────────────────────────────
print("=" * 76)
print("ACTIONABLE SIGNALS")
print("=" * 76)

# ─── Data gap report ─────────────────────────────────────────────────────────
missing_syms = [sym for sym in sorted(all_symbols) if moment_cache.get(sym) is None]
if missing_syms:
    print(f"\n  DATA GAPS: {', '.join(missing_syms)}")
    print(f"  Butterflies with incomplete variance data:")
    for bf in butterflies:
        legs_missing = [leg for leg in ["near_symbol", "mid_symbol", "far_symbol"]
                        if moment_cache.get(bf[leg]) is None]
        if legs_missing:
            missing_names = [bf[l] for l in legs_missing]
            print(f"    {bf['name']}: missing {', '.join(missing_names)}")

# ─── Actionable signals (with near-expiry filter) ────────────────────────────
print("\n" + "=" * 76)
print("ACTIONABLE SIGNALS")
print("=" * 76)

for bf in butterflies:
    signals = []
    caveats = []
    vs = bf.get("var_signal")
    frag = bf.get("fragility")
    kw = bf.get("kink_width_ratio")

    # Layer 1 — use time-adjusted signal as primary
    vs_adj = bf.get("var_signal_adj")
    if vs_adj is not None and abs(vs_adj) > 0.3:
        if bf.get("near_expiry_distorted") and bf.get("std_near", 999) < MIN_INFORMATIVE_STD_BPS:
            caveats.append(f"L1 SUPPRESSED: near leg dead (std={bf.get('std_near',0):.0f}bps)")
        else:
            direction = "RICH (sell)" if vs_adj > 0 else "CHEAP (buy)"
            adj_exc = bf.get("std_excess_adj", 0)
            signals.append(f"L1 Variance: {direction} (adj_excess={adj_exc:+.1f}bps, adj_signal={vs_adj:+.2f})")
    elif vs is not None and abs(vs) > 0.3 and (vs_adj is None or abs(vs_adj) <= 0.3):
        raw_exc = bf.get("std_excess", 0)
        caveats.append(
            f"L1 raw signal ({vs:+.2f}) absorbed by sqrt(T) correction -> adj_signal={vs_adj:+.2f}. Not actionable."
        )

    # Layer 2
    if kw is not None and kw > 0.15:
        signals.append(f"L2 High timing conviction (K/W={kw:.3f})")
    elif kw is not None and kw < 0.03 and abs(bf["bf_bps"]) > 1.0:
        signals.append(f"L2 Weak kink vs uncertainty (K/W={kw:.3f})")

    # Layer 3
    if frag is not None and frag > 0.5:
        signals.append(f"L3 HIGH fragility ({frag:.3f}) -> size down")
    elif frag is not None and frag < 0.15:
        signals.append(f"L3 LOW fragility ({frag:.3f}) -> full size OK")

    # FOMC — for gap flies, the gap-window meetings (between legs) matter most
    near_gap_m = bf.get("fomc_near_gap", 0)
    far_gap_m = bf.get("fomc_far_gap", 0)
    fomc_asym = abs(near_gap_m - far_gap_m)
    if fomc_asym >= 1:
        signals.append(
            f"FOMC: asymmetric meetings between legs "
            f"({near_gap_m} in near-gap vs {far_gap_m} in far-gap) -> structural curvature justified"
        )

    if signals or caveats:
        print(f"\n  {bf['name']} [{bf['gap']}] ({bf['bf_bps']:+.2f} bps):")
        for s in signals:
            print(f"    + {s}")
        for c in caveats:
            print(f"    ~ {c}")

print("\n" + "=" * 76)
print("DONE")
print("=" * 76)
