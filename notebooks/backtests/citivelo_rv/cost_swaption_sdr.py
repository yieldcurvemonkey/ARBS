"""CM-1: a MEASURED USD swaption transaction-cost line.

Local CFTC SDR swaption prints vs the same-day Citi Velocity swaption-cube
EOD mid (SwaptionCubeStore asset USD-SWAPTIONVOL-CITIVELOEXCEL), the swaption
analogue of the SR3 MBO cost study.

Pipeline (all idempotent, all local, no network / DB / Excel):

  extract   sdr_cache/CFTC/RATES/<y>/<m>/<date>.parquet -> per-day normalized
            swaption-row cache (both SDR schema vintages; the UPI columns only
            exist from 2024-01-29).
  dedup     global lifecycle-chain resolution: base print = NEWT-TRAD, latest
            CORR supplies economics, EROR kills the chain, MODI/TERM ignored.
  price     per execution-date: EOD Citi curve (CurveStore fast path through
            IRSwapsMDP source=CITIVELO_EXCEL) -> forward + annuity from
            discount factors; Bachelier implied vol of the print premium
            (both premium-timing hypotheses); trilinear cube-mid interpolation
            (linear in strike offset, bilinear in log-expiry / log-tenor).
  aggregate cells parquet + summary tables (funnel, premium-convention
            discriminator, straddle-premium arbitration, smear-vs-close).
  verify    (i) synthetic print planted at the cube mid through the REAL
            row-processing path; (ii) the same print under a mutated notation
            parse (bps treated as decimal) must FAIL; (iii) cube-node premium
            priced by rateslib's native swaption backend, inverted through
            THIS module's (F, A, T), must meet the store-served vol < 0.1bp.

Outputs (notebooks/data/citivelo_rv/, gitignored):
  swaption_cost_prints.parquet   one row per resolved print, with flags
  swaption_cost_cells.parquet    per (expiry bucket x tenor bucket x |offset|
                                 bucket x universe) cost stats
  swaption_cost_funnel.json      row counts at every filter stage
  swaption_cost_summary.txt      every table the findings note quotes

Run:  C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 cost_swaption_sdr.py
      [--days N] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--force-price]
      [--verify-only] [--skip-verify]
"""

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import sys

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-rv")

import argparse
import bisect
import datetime
import glob
import json
import math
import time
import warnings
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

warnings.filterwarnings("ignore", category=UserWarning, module="rateslib")

# ----------------------------------------------------------------- constants

SDR_DIR = Path(r"C:\Users\chris\clee\ARBS\sdr_cache\CFTC\RATES")  # READ-ONLY
OUT_DIR = Path(r"C:\Users\chris\clee\ARBS-rv\notebooks\data\citivelo_rv")
EXTRACT_DIR = OUT_DIR / "sdr_swaption_extract"
PRINTS_FP = OUT_DIR / "swaption_cost_prints.parquet"
CELLS_FP = OUT_DIR / "swaption_cost_cells.parquet"
FUNNEL_FP = OUT_DIR / "swaption_cost_funnel.json"
SUMMARY_FP = OUT_DIR / "swaption_cost_summary.txt"

CUBE_ASSET = "USD-SWAPTIONVOL-CITIVELOEXCEL"
CURVE_NAME = "USD-SOFR-1D"

WINDOW_START = datetime.date(2023, 12, 1)
WINDOW_END = datetime.date(2026, 7, 21)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

#: UPI FISN -> (option right, product class). Exact strings, on purpose: the
#: repo's substring-based classify_product_type marks "NA/O Opt Epn" rows as
#: both call-like and opt-like depending on order; here a chooser is a chooser.
FISN_MAP = {
    "NA/O Call Epn OIS USD": ("payer", "ois"),
    "NA/O P Epn OIS USD": ("receiver", "ois"),
    "NA/O Call Epn Fxd Flt USD": ("payer", "fxdflt"),
    "NA/O P Epn Fxd Flt USD": ("receiver", "fxdflt"),
    "NA/O Opt Epn OIS USD": ("chooser", "ois"),
    "NA/O Opt Epn Fxd Flt USD": ("chooser", "fxdflt"),
}

#: pre-UPI Option Type -> right
OLD_RIGHT_MAP = {
    "PAYER": "payer",
    "RECEIVER": "receiver",
    "STRADDLE": "straddle",
    "CALL": "payer_cp",  # CALL/PUT-labelled European rows are kept but
    "PUT": "receiver_cp",  # quarantined: mostly cancellables/exotics.
}

STANDARD_TAILS = [1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0]
TAIL_TOL_YEARS = 16.0 / 365.25

EXPIRY_BUCKETS = [  # (lo, hi, label) on T in act/365 years
    (0.0, 0.055, "<3W"),
    (0.055, 0.15, "1M"),
    (0.15, 0.40, "2-3M"),
    (0.40, 0.65, "6M"),
    (0.65, 1.15, "9M-1Y"),
    (1.15, 2.30, "18M-2Y"),
    (2.30, 5.60, "3-5Y"),
    (5.60, 99.0, "7Y+"),
]
OFFSET_BUCKETS = [
    (0.0, 5.0, "ATM(<5)"),
    (5.0, 25.0, "5-25"),
    (25.0, 50.0, "25-50"),
    (50.0, 100.0, "50-100"),
    (100.0, 200.5, "100-200"),
]
TENOR_LABELS = [1, 2, 3, 4, 5, 7, 10, 15, 20, 30]

#: verification (ii) hook: when True, notation code 4 (bps) is parsed as if it
#: were decimal. Exists so the checker can be shown to fail.
_MUTATE_NOTATION = False

ANNUAL_TO_DAILY = math.sqrt(252.0)  # 15.87

# ------------------------------------------------------------------ helpers


def log(msg: str) -> None:
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def _parse_strike(value, notation):
    """Strike -> decimal, honoring the CFTC notation code (1/3/4).

    parse_notation_scalar is the repo's canonical implementation of the
    100x-class trap; the mutation hook below exists only for verification (ii).
    """
    from SDRUtils.core.parsing import parse_notation_scalar, to_float

    if _MUTATE_NOTATION:
        return to_float(value)  # WRONG on purpose: ignores code 4 (bps)
    return parse_notation_scalar(value, notation)


def _to_float(value):
    from SDRUtils.core.parsing import to_float

    return to_float(value)


# ------------------------------------------------------------------ extract

EXTRACT_COLS = {
    "Dissemination Identifier": "diss_id",
    "Original Dissemination Identifier": "orig_diss_id",
    "Action type": "action",
    "Event type": "event",
    "Execution Timestamp": "exec_ts",
    "Event timestamp": "event_ts",
    "Effective Date": "effective_date",
    "Expiration Date": "expiration_date",
    "First exercise date": "first_exercise",
    "Maturity date of the underlier": "maturity",
    "Strike Price": "strike_raw",
    "Strike price notation": "strike_notation",
    "Option Premium Amount": "premium_raw",
    "Option Premium Currency": "premium_ccy",
    "Notional amount-Leg 1": "notional_raw",
    "Notional currency-Leg 1": "notional_ccy",
    "Package indicator": "package",
    "Package transaction price": "package_price_raw",
    "Block trade election indicator": "block",
    "Cleared": "cleared",
    "Platform identifier": "platform",
}
NEW_ONLY = ["UPI FISN", "UPI Underlier Name"]
OLD_ONLY = ["Product name", "Option Type", "Option Style"]


def extract_one(fp: Path) -> pd.DataFrame:
    import pyarrow.parquet as pq

    names = set(pq.read_schema(fp).names)
    is_new = "UPI FISN" in names
    want = [c for c in EXTRACT_COLS if c in names] + [c for c in (NEW_ONLY if is_new else OLD_ONLY) if c in names]
    df = pd.read_parquet(fp, columns=want)

    if is_new:
        fisn = df["UPI FISN"].astype(str)
        mask = fisn.str.startswith("NA/O ") & fisn.str.endswith(" USD")
        df = df.loc[mask].copy()
        rc = df["UPI FISN"].map(FISN_MAP)
        df["right"] = rc.map(lambda t: t[0] if isinstance(t, tuple) else None)
        df["pclass"] = rc.map(lambda t: t[1] if isinstance(t, tuple) else None)
        unk = df["right"].isna()
        fisn_u = df.loc[unk, "UPI FISN"].astype(str)
        df.loc[unk, "pclass"] = np.where(
            fisn_u.str.contains("Nstd"), "nstd",
            np.where(df.loc[unk, "UPI Underlier Name"].astype(str).str.contains("Term|LIBOR|SIFMA|Average", regex=True), "nonsofr", "other"),
        )
        df.loc[unk, "right"] = np.where(
            fisn_u.str.contains("Call"), "payer",
            np.where(fisn_u.str.contains(r"O P ", regex=True), "receiver", "other"),
        )
        df["style"] = np.where(fisn.loc[df.index].str.contains("Epn"), "EUROPEAN",
                               np.where(fisn.loc[df.index].str.contains("Brm"), "BERMUDAN", "OTHER"))
    else:
        mask = (df.get("Product name") == "InterestRate:Option:Swaption") & (df["Notional currency-Leg 1"] == "USD")
        df = df.loc[mask].copy()
        ot = df["Option Type"].astype(str).str.strip().str.upper()
        df["right"] = ot.map(OLD_RIGHT_MAP).fillna("other")
        df["style"] = df["Option Style"].astype(str).str.strip().str.upper().replace("", "OTHER")
        df["pclass"] = np.where(df["right"].isin(["payer", "receiver", "straddle"]) & (df["style"] == "EUROPEAN"),
                                "ois_pre_upi", "other")

    out = df.rename(columns={k: v for k, v in EXTRACT_COLS.items() if k in df.columns})
    keep = list(EXTRACT_COLS.values()) + ["right", "pclass", "style"]
    for c in keep:
        if c not in out.columns:
            out[c] = None
    out = out[keep]
    out["vintage"] = "upi" if is_new else "pre_upi"
    out["file_date"] = fp.stem
    for c in ("diss_id", "orig_diss_id", "strike_raw", "premium_raw", "notional_raw", "package_price_raw"):
        out[c] = out[c].astype("string")
    for c in ("effective_date", "expiration_date", "first_exercise", "maturity"):
        out[c] = pd.to_datetime(out[c], errors="coerce")
    for c in ("exec_ts", "event_ts"):
        out[c] = pd.to_datetime(out[c], errors="coerce", utc=True)
    return out


def phase_extract(files: list) -> pd.DataFrame:
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    t0 = time.time()
    for i, fp in enumerate(files):
        cache = EXTRACT_DIR / f"{fp.stem}.parquet"
        if cache.exists():
            frames.append(pd.read_parquet(cache))
        else:
            day = extract_one(fp)
            tmp = cache.with_suffix(".tmp")
            day.to_parquet(tmp, index=False)
            os.replace(tmp, cache)
            frames.append(day)
        if (i + 1) % 40 == 0 or i + 1 == len(files):
            log(f"extract {i + 1}/{len(files)} files ({time.time() - t0:.0f}s)")
    return pd.concat(frames, ignore_index=True)


# -------------------------------------------------------------------- dedup


def phase_dedup(raw: pd.DataFrame, funnel: dict) -> pd.DataFrame:
    """Resolve lifecycle chains to one row per print.

    Base = the NEWT-TRAD dissemination. The latest CORR in the chain supplies
    the economics (strike/premium/notional/dates); an EROR anywhere kills the
    chain; MODI and TERM rows are ignored for economics. Execution timestamp
    always comes from the base NEWT.
    """
    funnel["raw_rows_extracted"] = int(len(raw))
    # Normalize dissemination ids: the raw parquet serves orig ids as floats,
    # so a naive stringification yields '658530069.0' and no CORR/EROR ever
    # links to its NEWT. Found on the 30-day shakeout (corr_applied == 0).
    for c in ("diss_id", "orig_diss_id"):
        raw[c] = (
            raw[c].astype("string").str.strip().str.replace(r"\.0+$", "", regex=True).replace({"": None, "<NA>": None, "nan": None, "None": None})
        )
    funnel["rows_by_action"] = raw["action"].astype(str).str.upper().value_counts(dropna=False).to_dict()
    raw = raw.sort_values(["event_ts", "diss_id"], kind="stable")
    raw = raw.drop_duplicates(subset=["diss_id", "action", "event", "event_ts"], keep="last")
    funnel["rows_after_exact_dup_drop"] = int(len(raw))

    # chain roots: orig_diss_id points at the dissemination being superseded.
    root_of: dict = {}
    roots = np.empty(len(raw), dtype=object)
    for i, (did, oid) in enumerate(zip(raw["diss_id"].tolist(), raw["orig_diss_id"].tolist())):
        if oid is None or oid is pd.NA or (isinstance(oid, str) and not oid.strip()):
            root = root_of.get(did, did)
        else:
            root = root_of.get(oid, oid)
        if did:
            root_of[did] = root
        roots[i] = root
    raw = raw.assign(_root=roots)

    econ_cols = ["strike_raw", "strike_notation", "premium_raw", "premium_ccy", "notional_raw",
                 "notional_ccy", "package", "package_price_raw", "block",
                 "effective_date", "expiration_date", "first_exercise", "maturity"]

    n_eror = n_no_newt = n_corr_applied = n_revived = 0
    out_rows = []
    for root, g in raw.groupby("_root", sort=False):
        acts = g["action"].astype(str).str.upper()
        if (acts == "EROR").any():
            # REVI (Revive) resurrects a chain killed in error; the chain is
            # dead only if the last EROR is not followed by a REVI.
            last_eror = g.loc[acts == "EROR", "event_ts"].max()
            last_revi = g.loc[acts == "REVI", "event_ts"].max() if (acts == "REVI").any() else pd.NaT
            if pd.isna(last_revi) or last_revi < last_eror:
                n_eror += 1
                continue
            n_revived += 1
        base_mask = (acts == "NEWT") & (g["event"].astype(str).str.upper() == "TRAD")
        if not base_mask.any():
            n_no_newt += 1
            continue
        base = g.loc[base_mask].iloc[0]
        row = base.copy()
        corr = g.loc[acts == "CORR"]
        if len(corr):
            n_corr_applied += 1
            last = corr.iloc[-1]
            for c in econ_cols:
                v = last[c]
                if v is not None and not (isinstance(v, float) and pd.isna(v)) and v is not pd.NaT and str(v).strip() not in ("", "<NA>", "NaT", "nan"):
                    row[c] = v
        out_rows.append(row)

    prints = pd.DataFrame(out_rows).drop(columns=["_root"], errors="ignore").reset_index(drop=True)
    funnel["chains_dropped_eror"] = n_eror
    funnel["chains_revived_after_eror"] = n_revived
    funnel["chains_without_newt_trad"] = n_no_newt
    funnel["chains_with_corr_applied"] = n_corr_applied
    funnel["prints_after_dedup"] = int(len(prints))
    return prints


# ----------------------------------------------------------- economics parse


def phase_parse(prints: pd.DataFrame, funnel: dict) -> pd.DataFrame:
    from SDRUtils.core.parsing import parse_notional

    df = prints.copy()

    funnel["prints_by_class"] = df["pclass"].value_counts(dropna=False).to_dict()
    funnel["prints_by_right"] = df["right"].value_counts(dropna=False).to_dict()

    keep_class = df["pclass"].isin(["ois", "fxdflt", "ois_pre_upi"])
    keep_right = df["right"].isin(["payer", "receiver", "straddle"])
    keep_style = df["style"] == "EUROPEAN"
    funnel["dropped_class_nonvanilla"] = int((~keep_class).sum())
    funnel["dropped_right_or_style"] = int((keep_class & ~(keep_right & keep_style)).sum())
    df = df.loc[keep_class & keep_right & keep_style].copy()

    ccy = df["premium_ccy"].astype(str).str.strip().str.upper()
    ok_ccy = ccy.isin(["USD", "", "NAN", "NONE"])
    funnel["dropped_nonusd_premium_ccy"] = int((~ok_ccy).sum())
    df = df.loc[ok_ccy].copy()

    # Resolve the option expiry and the underlying swap end. The UPI vintage
    # reports option expiry in BOTH 'Expiration Date' and 'First exercise
    # date' and the swap end in 'Maturity date of the underlier'. The pre-UPI
    # vintage is reporter-inconsistent: 'Expiration Date' is sometimes the
    # option expiry and sometimes the SWAP end (with 'Maturity date of the
    # underlier' absent or duplicating it), while 'First exercise date' is
    # reliably the option expiry when present. Robust rule for both vintages:
    #   option expiry = First exercise date, else Expiration Date;
    #   swap end     = Maturity-of-underlier if > expiry + 60d,
    #                  else Expiration Date if > expiry + 60d, else missing.
    fe, xp, mt = df["first_exercise"], df["expiration_date"], df["maturity"]
    opt_expiry = fe.where(fe.notna(), xp)
    min_end = opt_expiry + pd.Timedelta(days=60)
    swap_end = mt.where(mt.notna() & (mt > min_end), pd.NaT)
    swap_end = swap_end.where(swap_end.notna(), xp.where(xp > min_end, pd.NaT))
    df["expiration_date"] = opt_expiry
    df["maturity"] = swap_end

    nots = df["notional_raw"].map(parse_notional)
    df["notional"] = [t[0] for t in nots]
    df["is_capped"] = [t[1] for t in nots]
    df["premium"] = df["premium_raw"].map(_to_float)
    df["strike"] = [
        _parse_strike(v, n) for v, n in zip(df["strike_raw"].tolist(), df["strike_notation"].tolist())
    ]
    # percent-looking strikes (pre-UPI STRADDLE rows report e.g. 4.015 under
    # notation 3): rescue-with-flag rather than silently drop.
    df["strike_rescued"] = (df["strike"] > 0.5) & (df["strike"] <= 15.0)
    df.loc[df["strike_rescued"], "strike"] = df.loc[df["strike_rescued"], "strike"] / 100.0
    funnel["strikes_rescued_percent_looking"] = int(df["strike_rescued"].sum())

    ok_prem = df["premium"].notna() & (df["premium"] > 0)
    ok_notl = df["notional"].notna() & (df["notional"] > 0)
    ok_strk = df["strike"].notna() & (df["strike"] >= 0.001) & (df["strike"] <= 0.12)
    ok_dates = df["expiration_date"].notna() & df["maturity"].notna() & df["exec_ts"].notna()
    funnel["dropped_zero_or_missing_premium"] = int((~ok_prem).sum())
    funnel["dropped_bad_notional"] = int((ok_prem & ~ok_notl).sum())
    funnel["dropped_bad_strike"] = int((ok_prem & ok_notl & ~ok_strk).sum())
    funnel["dropped_missing_dates"] = int((ok_prem & ok_notl & ok_strk & ~ok_dates).sum())
    df = df.loc[ok_prem & ok_notl & ok_strk & ok_dates].copy()

    # execution date in ET; late-report gate
    df["exec_et"] = df["exec_ts"].dt.tz_convert(ET)
    df["exec_date"] = df["exec_et"].dt.date
    fdate = pd.to_datetime(df["file_date"]).dt.date
    lag_days = (pd.to_datetime(fdate.astype(str)) - pd.to_datetime(df["exec_date"].astype(str))).dt.days
    df["report_lag_days"] = lag_days
    df["is_late_report"] = lag_days > 7
    in_window = (df["exec_date"] >= WINDOW_START) & (df["exec_date"] <= WINDOW_END)
    funnel["dropped_exec_out_of_window"] = int((~in_window).sum())
    df = df.loc[in_window].copy()
    funnel["flagged_late_report_gt7d"] = int(df["is_late_report"].sum())

    # expiry must be after execution
    ok_exp = pd.to_datetime(df["expiration_date"]).dt.date > df["exec_date"]
    ok_mat = df["maturity"] > df["expiration_date"]
    funnel["dropped_expiry_before_exec_or_mat_before_expiry"] = int((~(ok_exp & ok_mat)).sum())
    df = df.loc[ok_exp & ok_mat].copy()

    funnel["prints_after_parse"] = int(len(df))
    return df.reset_index(drop=True)


# --------------------------------------------------- straddle pair detection


def phase_straddles(df: pd.DataFrame, funnel: dict) -> pd.DataFrame:
    """Detect two-leg straddle pairs (UPI vintage reports straddles as a
    payer row + a receiver row at the same instant/strike/dates/notional).

    Adds: is_straddle (single synthetic straddle row built from the pair or a
    pre-UPI STRADDLE row), is_straddle_leg (the constituent legs, excluded
    from the outright universe), straddle_prem_kind:
      'single_row'  pre-UPI STRADDLE row - premium unambiguous (the total)
      'one_leg'     pair with the premium on one leg, 0 on the other - total
      'dup_equal'   pair with byte-equal premiums on both legs - ambiguous:
                    total is either P (duplicated) or 2P (per-leg); both IVs
                    are computed and the aggregate phase arbitrates.
    """
    df = df.copy()
    df["is_straddle"] = df["right"] == "straddle"
    df["is_straddle_leg"] = False
    df["straddle_prem_kind"] = np.where(df["is_straddle"], "single_row", "")
    df["straddle_prem_total_a"] = np.where(df["is_straddle"], df["premium"], np.nan)  # A: reported=total
    df["straddle_prem_total_b"] = np.nan  # B: reported=per-leg (2x)

    legs = df[df["right"].isin(["payer", "receiver"])]
    key_cols = ["exec_ts", "expiration_date", "maturity", "strike", "notional"]
    grp = legs.groupby(key_cols, sort=False)
    pair_rows = []
    n_pairs = n_oneleg = n_dup = n_uneq = 0
    leg_idx = []
    for key, g in grp:
        if len(g) != 2 or set(g["right"]) != {"payer", "receiver"}:
            continue
        p = g["premium"].to_numpy(dtype=float)
        row = g.iloc[0].copy()
        row["right"] = "straddle"
        row["is_straddle"] = True
        row["is_straddle_leg"] = False
        if (p == 0).sum() == 1:
            kind, total_a, total_b = "one_leg", float(p.max()), np.nan
            n_oneleg += 1
        elif p[0] == p[1] and p[0] > 0:
            kind, total_a, total_b = "dup_equal", float(p[0]), float(2 * p[0])
            n_dup += 1
        elif (p > 0).all():
            kind, total_a, total_b = "sum_legs", float(p.sum()), np.nan
            n_uneq += 1
        else:
            continue
        row["straddle_prem_kind"] = kind
        row["straddle_prem_total_a"] = total_a
        row["straddle_prem_total_b"] = total_b
        row["package"] = bool(g["package"].astype(bool).any())
        pair_rows.append(row)
        leg_idx.extend(g.index.tolist())
        n_pairs += 1

    df.loc[leg_idx, "is_straddle_leg"] = True
    funnel["straddle_pairs_detected"] = n_pairs
    funnel["straddle_pairs_premium_on_one_leg"] = n_oneleg
    funnel["straddle_pairs_equal_premium_both_legs"] = n_dup
    funnel["straddle_pairs_unequal_premiums_summed"] = n_uneq
    funnel["straddle_single_rows_pre_upi"] = int((df["right"] == "straddle").sum())
    if pair_rows:
        df = pd.concat([df, pd.DataFrame(pair_rows)], ignore_index=True)
    return df


# ------------------------------------------------------------------- pricing


class DayCtx:
    """Everything needed to price one execution day's prints."""

    def __init__(self, as_of: datetime.date, crv, cube_frame: pd.DataFrame, cal):
        import rateslib as rl

        self.as_of = as_of
        self.as_of_dt = datetime.datetime(as_of.year, as_of.month, as_of.day)
        self.crv = crv
        self.cal = cal
        self._df_cache: dict = {}
        self._fa_cache: dict = {}
        self._rl = rl

        # cube grid -> arrays for trilinear interpolation
        cf = cube_frame
        offs = np.array(sorted(cf["offset_bp"].unique()), dtype=float)
        exp_tokens = list(dict.fromkeys(cf["expiry"]))
        ten_tokens = list(dict.fromkeys(cf["tenor"]))
        exp_T = {}
        for tok in exp_tokens:
            d = rl.add_tenor(self.as_of_dt, str(tok), "MF", cal)
            exp_T[tok] = float(rl.dcf(self.as_of_dt, d, "act365f"))
        ten_Y = {tok: float(str(tok).rstrip("Yy")) for tok in ten_tokens}
        exp_tokens = sorted(exp_tokens, key=lambda t: exp_T[t])
        ten_tokens = sorted(ten_tokens, key=lambda t: ten_Y[t])
        piv = cf.set_index(["expiry", "tenor", "offset_bp"])["vol_bp"]
        vols = np.empty((len(exp_tokens), len(ten_tokens), len(offs)))
        for i, e in enumerate(exp_tokens):
            for j, t in enumerate(ten_tokens):
                for k, o in enumerate(offs):
                    vols[i, j, k] = piv.get((e, t, o), np.nan)
        self.exp_T = np.array([exp_T[t] for t in exp_tokens])
        self.ten_Y = np.array([ten_Y[t] for t in ten_tokens])
        self.offs = offs
        self.vols = vols

    # -- discounting ------------------------------------------------------

    def df(self, d: datetime.datetime) -> float:
        v = self._df_cache.get(d)
        if v is None:
            v = float(self.crv[d])
            self._df_cache[d] = v
        return v

    # -- underlying forward + annuity -------------------------------------

    def forward_annuity(self, swap_start: datetime.datetime, maturity: datetime.datetime):
        """(forward decimal, discounted fixed annuity per unit notional).

        Annual fixed leg, ACT/360, modified-following on the NYC calendar,
        2-business-day payment lag - the standard USD SOFR OIS the cube's own
        rateslib backend builds (verification iii pins this against it).
        Schedule rolls FORWARD from the swap start (anniversaries of the
        start date), front-stubbed if the tail is not an integer number of
        years, ending on the recorded maturity.
        """
        key = (swap_start, maturity)
        hit = self._fa_cache.get(key)
        if hit is not None:
            return hit
        rl = self._rl
        months = (maturity.year - swap_start.year) * 12 + (maturity.month - swap_start.month)
        # nudge by day-of-month so e.g. 119.8 months reads as 120
        if maturity.day - swap_start.day > 15:
            months += 1
        elif maturity.day - swap_start.day < -15:
            months -= 1
        n_full = months // 12
        unadj = []
        rem = months - 12 * n_full
        if rem:
            unadj.append(swap_start)  # front stub start
        for k in range(n_full, -1, -1):
            unadj.append(maturity - relativedelta(months=12 * k))
        # de-dup guard (rem==0 -> first anniversary IS swap_start)
        dates = []
        for d in unadj:
            if not dates or d > dates[-1]:
                dates.append(d)
        adj = [self.cal.roll(d, "mf", False) for d in dates]
        ann = 0.0
        flt = 0.0
        for s, e in zip(adj[:-1], adj[1:]):
            alpha = float(rl.dcf(s, e, "act360"))
            pay = self.cal.add_bus_days(e, 2, True)
            dpay = self.df(pay)
            ann += alpha * dpay
            flt += (self.df(s) / self.df(e) - 1.0) * dpay
        fwd = flt / ann if ann > 0 else float("nan")
        out = (fwd, ann)
        self._fa_cache[key] = out
        return out

    # -- cube mid interpolation -------------------------------------------

    def mid_vol(self, T: float, tenor_years: float, offset_bp: float):
        """Interpolated cube mid, linear in offset, bilinear in log-expiry and
        log-tenor, flat outside the grid. Returns (vol_bp, out_of_grid)."""
        oog = (
            T < self.exp_T[0] - 1e-9 or T > self.exp_T[-1] + 1e-9
            or tenor_years < self.ten_Y[0] - 1e-9 or tenor_years > self.ten_Y[-1] + 1e-9
            or offset_bp < self.offs[0] - 1e-9 or offset_bp > self.offs[-1] + 1e-9
        )
        x = math.log(min(max(T, self.exp_T[0]), self.exp_T[-1]))
        y = math.log(min(max(tenor_years, self.ten_Y[0]), self.ten_Y[-1]))
        o = min(max(offset_bp, self.offs[0]), self.offs[-1])

        lx = np.log(self.exp_T)
        ly = np.log(self.ten_Y)
        i = min(max(bisect.bisect_right(lx, x) - 1, 0), len(lx) - 2)
        j = min(max(bisect.bisect_right(ly, y) - 1, 0), len(ly) - 2)
        wx = 0.0 if lx[i + 1] == lx[i] else (x - lx[i]) / (lx[i + 1] - lx[i])
        wy = 0.0 if ly[j + 1] == ly[j] else (y - ly[j]) / (ly[j + 1] - ly[j])
        v = 0.0
        for di, wxi in ((0, 1.0 - wx), (1, wx)):
            for dj, wyj in ((0, 1.0 - wy), (1, wy)):
                smile = self.vols[i + di, j + dj, :]
                v += wxi * wyj * float(np.interp(o, self.offs, smile))
        return v, oog


def _invert_print_iv(unit_pv: float, strike: float, forward: float, tte: float, right: str):
    """Present-valued premium per unit (notional*annuity) -> normal vol bp.

    Same construction as MDP.CitiVelocityExcel.vol.spot_check: receivers via
    put-call parity, straddles via C = (S + (F-K))/2, then the repo's only
    non-QuantLib Bachelier inverter.
    """
    from RVUtils.ImpliedDistribution._bachelier import bachelier_implied_vol, put_to_call_parity

    if right == "receiver":
        unit_pv = put_to_call_parity(unit_pv, strike, forward, 1.0)
    elif right == "straddle":
        unit_pv = 0.5 * (unit_pv + (forward - strike))
    iv = bachelier_implied_vol(unit_pv, strike, forward, tte, 1.0)
    return iv * 1e4 if np.isfinite(iv) else np.nan


def _unit_price(strike: float, forward: float, vol_bp: float, tte: float, right: str) -> float:
    from RVUtils.ImpliedDistribution._bachelier import bachelier_call_price

    c = bachelier_call_price(strike, forward, vol_bp / 1e4, tte, 1.0)
    if right == "payer":
        return c
    if right == "receiver":
        return c - (forward - strike)
    return 2.0 * c - (forward - strike)  # straddle


def price_day(ctx: DayCtx, day_df: pd.DataFrame, funnel: dict) -> list:
    import rateslib as rl

    rows = []
    close_et = datetime.datetime.combine(ctx.as_of, datetime.time(17, 0), tzinfo=ET)
    for _, r in day_df.iterrows():
        exp = pd.Timestamp(r["expiration_date"]).to_pydatetime().replace(tzinfo=None)
        mat = pd.Timestamp(r["maturity"]).to_pydatetime().replace(tzinfo=None)
        try:
            swap_start = ctx.cal.add_bus_days(ctx.cal.roll(exp, "f", False), 2, True)
        except Exception:
            funnel["dropped_calendar_error"] = funnel.get("dropped_calendar_error", 0) + 1
            continue
        tail_years = (mat - swap_start).days / 365.25
        near = min(STANDARD_TAILS, key=lambda n: abs(tail_years - n))
        is_std = abs(tail_years - near) <= TAIL_TOL_YEARS
        tenor_years = near if is_std else tail_years
        T = float(rl.dcf(ctx.as_of_dt, exp, "act365f"))
        if T <= 1.0 / 365.0:
            funnel["dropped_expired_vs_cube_date"] = funnel.get("dropped_expired_vs_cube_date", 0) + 1
            continue
        try:
            fwd, ann = ctx.forward_annuity(swap_start, mat)
        except Exception:
            funnel["dropped_curve_range"] = funnel.get("dropped_curve_range", 0) + 1
            continue
        if not (np.isfinite(fwd) and np.isfinite(ann) and ann > 0):
            funnel["dropped_curve_range"] = funnel.get("dropped_curve_range", 0) + 1
            continue

        K = float(r["strike"])
        offset_bp = (K - fwd) * 1e4
        mid_bp, oog = ctx.mid_vol(T, tenor_years, offset_bp)
        notional = float(r["notional"])
        df_settle = ctx.df(swap_start)

        right = r["right"]
        if right == "straddle":
            prem_a = float(r["straddle_prem_total_a"])
            prem_b = float(r["straddle_prem_total_b"]) if np.isfinite(r["straddle_prem_total_b"]) else np.nan
        else:
            prem_a, prem_b = float(r["premium"]), np.nan

        def _iv(prem, hyp):
            if not np.isfinite(prem) or prem <= 0:
                return np.nan
            pv = prem * (df_settle if hyp == "fwd" else 1.0)
            return _invert_print_iv(pv / (notional * ann), K, fwd, T, right)

        iv_fwd = _iv(prem_a, "fwd")
        iv_spot = _iv(prem_a, "spot")
        iv_fwd_2p = _iv(prem_b, "fwd")
        iv_spot_2p = _iv(prem_b, "spot")

        pv_mid = notional * ann * _unit_price(K, fwd, mid_bp, T, right)
        vega_1bp = notional * ann * math.sqrt(T) * float(np.exp(-0.5 * ((fwd - K) / max(mid_bp / 1e4, 1e-9) / math.sqrt(T)) ** 2) / math.sqrt(2 * math.pi)) / 1e4

        exec_ts = r["exec_ts"]
        hours_to_close = abs((exec_ts - close_et).total_seconds()) / 3600.0

        rows.append({
            "diss_id": r["diss_id"],
            "exec_ts": exec_ts,
            "exec_date": r["exec_date"],
            "cube_date": ctx.as_of,
            "vintage": r["vintage"],
            "pclass": r["pclass"],
            "right": right,
            "platform": r["platform"],
            "cleared": r["cleared"],
            "package": bool(r["package"]) if pd.notna(r["package"]) else False,
            "block": bool(r["block"]) if pd.notna(r["block"]) else False,
            "is_capped": bool(r["is_capped"]),
            "is_straddle": bool(r["is_straddle"]),
            "is_straddle_leg": bool(r["is_straddle_leg"]),
            "straddle_prem_kind": r["straddle_prem_kind"],
            "is_late_report": bool(r["is_late_report"]),
            "strike_rescued": bool(r["strike_rescued"]),
            "notional": notional,
            "premium": prem_a,
            "strike": K,
            "expiry_date": exp.date(),
            "maturity_date": mat.date(),
            "swap_start": swap_start.date(),
            "T_expiry": T,
            "tail_years_exact": tail_years,
            "tenor_years": tenor_years,
            "is_standard_tail": is_std,
            "forward": fwd,
            "annuity": ann,
            "offset_bp": offset_bp,
            "out_of_grid": oog,
            "mid_bp": mid_bp,
            "iv_fwd": iv_fwd,
            "iv_spot": iv_spot,
            "iv_fwd_2p": iv_fwd_2p,
            "iv_spot_2p": iv_spot_2p,
            "diff_fwd": iv_fwd - mid_bp if np.isfinite(iv_fwd) else np.nan,
            "diff_spot": iv_spot - mid_bp if np.isfinite(iv_spot) else np.nan,
            "pv_print_fwd": prem_a * df_settle,
            "pv_print_spot": prem_a,
            "pv_mid": pv_mid,
            "vega_1bp": vega_1bp,
            "hours_to_close": hours_to_close,
        })
    return rows


def phase_price(parsed: pd.DataFrame, funnel: dict, force: bool = False) -> pd.DataFrame:
    if PRINTS_FP.exists() and not force:
        log(f"price: reusing {PRINTS_FP}")
        return pd.read_parquet(PRINTS_FP)

    import rateslib as rl
    from Caching.swaption_cube_store import SwaptionCubeStore
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    cal = rl.get_calendar("nyc")
    store = SwaptionCubeStore.default()
    cube_dates = sorted(d for d in store.available_dates(CUBE_ASSET) if WINDOW_START <= d <= WINDOW_END)
    log(f"price: cube store has {len(cube_dates)} days in window")
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")

    # map exec_date -> latest cube date <= exec_date
    def cube_date_for(d: datetime.date):
        i = bisect.bisect_right(cube_dates, d) - 1
        if i < 0:
            return None
        cd = cube_dates[i]
        return cd if (d - cd).days <= 5 else None

    parsed = parsed.copy()
    parsed["_cube_date"] = parsed["exec_date"].map(cube_date_for)
    n_nocube = int(parsed["_cube_date"].isna().sum())
    funnel["dropped_no_cube_day"] = n_nocube
    parsed = parsed.dropna(subset=["_cube_date"])

    all_rows = []
    days = sorted(parsed["_cube_date"].unique())
    t0 = time.time()
    n_bad_days = 0
    for i, day in enumerate(days):
        day_df = parsed[parsed["_cube_date"] == day]
        try:
            cf = store.read_day(CUBE_ASSET, day)
            if cf is None or cf.empty:
                raise RuntimeError("cube miss")
            curve = mdp.get_data({"curve_name": CURVE_NAME, "timestamp": day, "offline": True})
            if curve is None:
                raise RuntimeError("curve miss")
            ctx = DayCtx(day, curve.handle(), cf, cal)
        except Exception as exc:  # noqa: BLE001 - one bad day must not kill the run
            n_bad_days += 1
            funnel["dropped_day_curve_or_cube_error"] = funnel.get("dropped_day_curve_or_cube_error", 0) + int(len(day_df))
            log(f"price: SKIP {day} ({type(exc).__name__}: {exc})")
            continue
        all_rows.extend(price_day(ctx, day_df, funnel))
        if (i + 1) % 20 == 0 or i + 1 == len(days):
            log(f"price {i + 1}/{len(days)} days, {len(all_rows)} prints ({time.time() - t0:.0f}s)")

    out = pd.DataFrame(all_rows)
    funnel["bad_days_skipped"] = n_bad_days
    funnel["prints_priced"] = int(len(out))
    funnel["prints_iv_inversion_failed_fwd"] = int(out["iv_fwd"].isna().sum()) if len(out) else 0
    tmp = PRINTS_FP.with_suffix(".tmp")
    out.to_parquet(tmp, index=False)
    os.replace(tmp, PRINTS_FP)
    log(f"price: wrote {PRINTS_FP} ({len(out)} rows)")
    return out


# ----------------------------------------------------------------- buckets


def expiry_bucket(T: float) -> str:
    for lo, hi, lab in EXPIRY_BUCKETS:
        if lo <= T < hi:
            return lab
    return "7Y+"


def tenor_bucket(y: float) -> str:
    n = min(TENOR_LABELS, key=lambda v: abs(v - y))
    return f"{n}Y" if abs(n - y) <= 0.3 else "nonstd"


def offset_bucket(a: float) -> str:
    for lo, hi, lab in OFFSET_BUCKETS:
        if lo <= a < hi:
            return lab
    return ">200"


# --------------------------------------------------------------- aggregate


def _cell_stats(g: pd.DataFrame, col: str) -> dict:
    d = g[col].dropna()
    a = d.abs()
    return {
        "n": int(len(d)),
        "median_abs_bp": float(a.median()) if len(d) else np.nan,
        "p25_abs_bp": float(a.quantile(0.25)) if len(d) else np.nan,
        "p75_abs_bp": float(a.quantile(0.75)) if len(d) else np.nan,
        "median_signed_bp": float(d.median()) if len(d) else np.nan,
        "median_abs_premdiff_bp_notional": float(((g["pv_print_" + ("fwd" if col == "diff_fwd" else "spot")] - g["pv_mid"]).abs() / g["notional"] * 1e4).median()) if len(g) else np.nan,
    }


def phase_aggregate(prints: pd.DataFrame, funnel: dict) -> None:
    lines = []

    def emit(s=""):
        lines.append(s)
        print(s, flush=True)

    pr = prints.copy()
    pr["expiry_bucket"] = pr["T_expiry"].map(expiry_bucket)
    pr["tenor_bucket"] = pr["tenor_years"].map(tenor_bucket)
    pr["absoff_bucket"] = pr["offset_bp"].abs().map(offset_bucket)

    clean = (
        pr["is_standard_tail"] & ~pr["out_of_grid"] & ~pr["is_late_report"]
        & (pr["expiry_bucket"] != "<3W") & (pr["tenor_bucket"] != "nonstd")
    )
    outright = clean & ~pr["is_straddle"] & ~pr["is_straddle_leg"] & ~pr["package"] & ~pr["is_capped"]
    straddle = clean & pr["is_straddle"]

    funnel["headline_outright_universe"] = int((outright & pr["diff_fwd"].notna()).sum())
    funnel["straddle_universe"] = int((straddle & pr["diff_fwd"].notna()).sum())
    funnel["quarantined_package_legs"] = int((clean & ~pr["is_straddle"] & pr["package"]).sum())
    funnel["quarantined_capped_notional"] = int((clean & ~pr["is_straddle"] & ~pr["package"] & pr["is_capped"]).sum())

    # ---- straddle-premium arbitration (UPI-vintage equal-premium pairs) ----
    emit("=" * 78)
    emit("STRADDLE-PREMIUM ARBITRATION (is 'equal premium on both legs' the total")
    emit("or per-leg?) - discriminator: off-forward pairs cannot have equal true")
    emit("leg premiums, since P_call - P_put = N*A*(F-K) != 0.")
    dup = pr[(pr["straddle_prem_kind"] == "dup_equal") & pr["diff_fwd"].notna()]
    disc = dup[(dup["offset_bp"].abs() >= 5.0) & ((dup["notional"] * dup["annuity"] * (dup["offset_bp"].abs() / 1e4)) > 1000.0)]
    emit(f"equal-premium pairs: {len(dup)}; discriminating (|K-F|>=5bp, N*A*|F-K|>$1000): {len(disc)}")
    emit("  -> equal premiums on discriminating pairs are only possible if the")
    emit("     reported number is the PACKAGE total duplicated onto both legs.")
    # sanity cross-check vs cube on ATM straddles, both readings
    atm_str = pr[straddle & (pr["offset_bp"].abs() < 25) & pr["diff_fwd"].notna()]
    med_a = atm_str["diff_fwd"].median()
    med_b = (atm_str["iv_fwd_2p"] - atm_str["mid_bp"]).median()
    emit(f"ATM straddles, median (IV - mid) if reported=total  : {med_a:+.2f} bp  (n={atm_str['diff_fwd'].notna().sum()})")
    emit(f"ATM straddles, median (IV - mid) if reported=per-leg: {med_b:+.2f} bp  (n={(atm_str['iv_fwd_2p'] - atm_str['mid_bp']).notna().sum()})")
    single = pr[straddle & (pr["straddle_prem_kind"] == "single_row") & (pr["offset_bp"].abs() < 25) & pr["diff_fwd"].notna()]
    emit(f"pre-UPI single-row ATM straddles (unambiguous total): median {single['diff_fwd'].median():+.2f} bp (n={len(single)})")
    dup_total_wins = abs(med_a - single["diff_fwd"].median()) <= abs((med_b if np.isfinite(med_b) else 1e9) - single["diff_fwd"].median()) if len(single) else True
    emit(f"CHOSEN: equal-premium pairs read as {'TOTAL duplicated' if dup_total_wins else 'PER-LEG'}")
    if not dup_total_wins:
        swap_cols = [("iv_fwd", "iv_fwd_2p"), ("iv_spot", "iv_spot_2p")]
        m = pr["straddle_prem_kind"] == "dup_equal"
        for a, b in swap_cols:
            pr.loc[m, a] = pr.loc[m, b]
        pr.loc[m, "diff_fwd"] = pr.loc[m, "iv_fwd"] - pr.loc[m, "mid_bp"]
        pr.loc[m, "diff_spot"] = pr.loc[m, "iv_spot"] - pr.loc[m, "mid_bp"]
    funnel["straddle_dup_equal_read_as_total"] = bool(dup_total_wins)

    # ---- premium-timing hypothesis (spot vs forward premium) ----
    emit()
    emit("=" * 78)
    emit("PREMIUM-TIMING DISCRIMINATOR - the reported premium is either paid at")
    emit("spot (PV as-is) or at expiry (forward premium; PV = prem * DF(expiry)).")
    emit("Under the WRONG hypothesis the ATM-straddle signed diff grows with")
    emit("expiry like the funding leg (~ +/- 4bp of vol per year of expiry);")
    emit("under the right one it is flat. Median signed (IV - mid), ATM straddles:")
    st = pr[straddle & (pr["offset_bp"].abs() < 25)]
    tbl = []
    for lo, hi, lab in [(0.0, 0.25, "<3M"), (0.25, 0.75, "3-9M"), (0.75, 1.5, "9M-18M"), (1.5, 3.5, "18M-3Y"), (3.5, 99, ">3Y")]:
        g = st[(st["T_expiry"] >= lo) & (st["T_expiry"] < hi)]
        tbl.append({"expiry": lab, "n": g["diff_fwd"].notna().sum(),
                    "fwd_hyp_bp": g["diff_fwd"].median(), "spot_hyp_bp": g["diff_spot"].median()})
    tbl = pd.DataFrame(tbl)
    emit(tbl.to_string(index=False, float_format=lambda v: f"{v:+.2f}"))
    far = st[st["T_expiry"] >= 0.75]
    score_fwd = abs(far["diff_fwd"].median()) if len(far) else np.nan
    score_spot = abs(far["diff_spot"].median()) if len(far) else np.nan
    hyp = "fwd" if (np.isnan(score_spot) or (not np.isnan(score_fwd) and score_fwd <= score_spot)) else "spot"
    emit(f"CHOSEN premium-timing hypothesis: {hyp.upper()} premium "
         f"(|median| at >=9M expiry: fwd {score_fwd:.2f}bp vs spot {score_spot:.2f}bp)")
    funnel["premium_timing_hypothesis"] = hyp
    dcol = f"diff_{hyp}"

    # ---- FxdFlt-vs-OIS pooling gate ----
    emit()
    emit("=" * 78)
    emit("FXDFLT-vs-OIS POOLING GATE (UPI vintage; pooled only if per-cell medians")
    emit("agree within the OIS cell IQR):")
    gate_ok = True
    rowsg = []
    for (eb, tb), g in pr[outright & (pr["absoff_bucket"] == "ATM(<5)")].groupby(["expiry_bucket", "tenor_bucket"]):
        a = g[g["pclass"] == "ois"][dcol].abs()
        b = g[g["pclass"] == "fxdflt"][dcol].abs()
        if len(a) >= 10 and len(b) >= 10:
            iqr = a.quantile(0.75) - a.quantile(0.25)
            ok = abs(a.median() - b.median()) <= max(iqr, 0.25)
            gate_ok &= ok
            rowsg.append({"expiry": eb, "tenor": tb, "n_ois": len(a), "n_fxdflt": len(b),
                          "med_ois": a.median(), "med_fxdflt": b.median(), "iqr_ois": iqr, "pooled_ok": ok})
    if rowsg:
        emit(pd.DataFrame(rowsg).to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    emit(f"GATE: {'POOL fxdflt with ois' if gate_ok else 'EXCLUDE fxdflt from headline'}")
    funnel["fxdflt_pooled"] = bool(gate_ok)
    if not gate_ok:
        outright = outright & (pr["pclass"] != "fxdflt")

    # ---- cells ----
    cells = []
    for universe, mask in (("outright", outright), ("straddle", straddle)):
        for (eb, tb, ob), g in pr[mask].groupby(["expiry_bucket", "tenor_bucket", "absoff_bucket"]):
            st_ = _cell_stats(g, dcol)
            payer_med = g.loc[g["right"] == "payer", dcol].median()
            recv_med = g.loc[g["right"] == "receiver", dcol].median()
            cells.append({"universe": universe, "expiry_bucket": eb, "tenor_bucket": tb,
                          "absoff_bucket": ob, **st_,
                          "median_signed_payer_bp": payer_med, "median_signed_receiver_bp": recv_med,
                          "median_vega_1bp": g["vega_1bp"].median(),
                          "hypothesis": hyp})
    cells_df = pd.DataFrame(cells)
    tmp = CELLS_FP.with_suffix(".tmp")
    cells_df.to_parquet(tmp, index=False)
    os.replace(tmp, CELLS_FP)
    log(f"aggregate: wrote {CELLS_FP} ({len(cells_df)} cells)")

    # ---- headline table ----
    emit()
    emit("=" * 78)
    emit(f"HEADLINE (outright, non-package, non-capped, standard tail, {hyp}-premium)")
    emit("median |print IV - EOD cube mid| in ANNUAL NORMAL BP - an UPPER BOUND on")
    emit("the half-spread: prints are intraday, the mid is EOD (see smear below).")
    for ob_lab in ["ATM(<5)", "5-25", "25-50", "50-100"]:
        sub = cells_df[(cells_df["universe"] == "outright") & (cells_df["absoff_bucket"] == ob_lab) & (cells_df["n"] >= 10)]
        if sub.empty:
            continue
        piv = sub.pivot_table(index="expiry_bucket", columns="tenor_bucket", values="median_abs_bp")
        cnt = sub.pivot_table(index="expiry_bucket", columns="tenor_bucket", values="n")
        order = [lab for _, _, lab in EXPIRY_BUCKETS if lab in piv.index]
        tord = [f"{n}Y" for n in TENOR_LABELS if f"{n}Y" in piv.columns]
        emit(f"\n|offset| bucket {ob_lab}  - median |diff| bp (n):")
        piv = piv.reindex(index=order, columns=tord)
        cnt = cnt.reindex(index=order, columns=tord)
        merged = piv.round(2).astype(str) + " (" + cnt.fillna(0).astype(int).astype(str) + ")"
        merged = merged.mask(piv.isna(), "-")
        emit(merged.to_string())

    # ---- straddle table ----
    emit()
    emit("ATM STRADDLES (the premium-driven, forward-insensitive instrument):")
    sub = cells_df[(cells_df["universe"] == "straddle") & (cells_df["absoff_bucket"].isin(["ATM(<5)", "5-25"])) & (cells_df["n"] >= 5)]
    if len(sub):
        piv = sub.pivot_table(index="expiry_bucket", columns="tenor_bucket", values="median_abs_bp", aggfunc="mean")
        order = [lab for _, _, lab in EXPIRY_BUCKETS if lab in piv.index]
        tord = [f"{n}Y" for n in TENOR_LABELS if f"{n}Y" in piv.columns]
        emit(piv.reindex(index=order, columns=tord).round(2).to_string())

    # ---- smear: |diff| vs distance from the 5pm ET close ----
    emit()
    emit("=" * 78)
    emit("SMEAR - median |diff| (bp) by |execution time - 5pm ET close| (hours).")
    emit("A real spread is time-invariant; intraday drift grows with distance.")
    hrs_edges = [(0, 1, "0-1h"), (1, 2, "1-2h"), (2, 4, "2-4h"), (4, 8, "4-8h"), (8, 24, "8-24h"), (24, 1e9, ">24h")]
    for name, mask in (("ATM outrights (|off|<25bp)", outright & (pr["offset_bp"].abs() < 25)),
                       ("ATM straddles (|off|<25bp)", straddle & (pr["offset_bp"].abs() < 25))):
        rows = []
        g0 = pr[mask]
        for lo, hi, lab in hrs_edges:
            g = g0[(g0["hours_to_close"] >= lo) & (g0["hours_to_close"] < hi)]
            rows.append({"hours_to_close": lab, "n": g[dcol].notna().sum(),
                         "median_abs_bp": g[dcol].abs().median(),
                         "median_signed_bp": g[dcol].median()})
        emit(f"\n{name}:")
        emit(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:+.2f}"))

    # near-close estimate = the defensible line
    emit()
    emit("=" * 78)
    emit("NEAR-CLOSE ESTIMATE (prints within 1h of the 5pm ET close):")
    for name, mask in (("outright", outright), ("straddle", straddle)):
        g = pr[mask & (pr["hours_to_close"] < 1.0) & (pr["offset_bp"].abs() < 25)]
        med = g[dcol].abs().median()
        daily = med / ANNUAL_TO_DAILY if np.isfinite(med) else np.nan
        emit(f"  {name:9s} ATM: median |diff| {med:.2f} bp annual  ({daily:.3f} bp/day, /15.87)  n={g[dcol].notna().sum()}")

    # quarantined universes for reference
    emit()
    emit("QUARANTINED UNIVERSES, ATM (|off|<25bp), median |diff| bp:")
    for name, mask in (
        ("package legs", clean & ~pr["is_straddle"] & ~pr["is_straddle_leg"] & pr["package"]),
        ("capped notional (blocks)", clean & ~pr["is_straddle"] & ~pr["is_straddle_leg"] & ~pr["package"] & pr["is_capped"]),
        ("late reports (>7d)", pr["is_late_report"] & ~pr["is_straddle"] & ~pr["is_straddle_leg"]),
    ):
        g = pr[mask & (pr["offset_bp"].abs() < 25)]
        emit(f"  {name:26s}: {g[dcol].abs().median():6.2f} bp  (n={g[dcol].notna().sum()})")

    # counts per day sanity
    emit()
    per_day = pr[outright].groupby("exec_date").size()
    emit(f"outright headline prints/day: median {per_day.median():.0f}, mean {per_day.mean():.1f} over {len(per_day)} days")
    emit(f"(the task brief assumed ~600 USD swaption prints/day; measured usable outrights are far fewer - see funnel)")

    with open(SUMMARY_FP, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    log(f"aggregate: wrote {SUMMARY_FP}")


# ------------------------------------------------------------------ verify


def phase_verify() -> None:
    """Verification (i)-(iii). Raises AssertionError on any failure."""
    global _MUTATE_NOTATION
    import rateslib as rl
    from Caching.swaption_cube_store import SwaptionCubeStore
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    day = datetime.date(2025, 6, 10)
    store = SwaptionCubeStore.default()
    cf = store.read_day(CUBE_ASSET, day)
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    curve = mdp.get_data({"curve_name": CURVE_NAME, "timestamp": day, "offline": True})
    cal = rl.get_calendar("nyc")
    ctx = DayCtx(day, curve.handle(), cf, cal)

    print("=" * 78)
    print("VERIFICATION (i): synthetic print planted exactly at the cube mid, fed")
    print("through the REAL row path (comma-formatted premium/notional, strike in")
    print("bps under notation 4). Expect |print IV - mid| ~ 0.")

    # node 1Yx10Y, +25bp - build the synthetic through *our* forward/annuity
    expiry = rl.add_tenor(ctx.as_of_dt, "1Y", "MF", cal)
    swap_start = cal.add_bus_days(expiry, 2, True)
    maturity = swap_start + relativedelta(years=10)
    fwd, ann = ctx.forward_annuity(swap_start, maturity)
    K = fwd + 25e-4
    T = float(rl.dcf(ctx.as_of_dt, expiry, "act365f"))
    mid, _ = ctx.mid_vol(T, 10.0, (K - fwd) * 1e4)
    notional = 100_000_000.0
    pv = notional * ann * _unit_price(K, fwd, mid, T, "payer")
    prem_fwd = pv / ctx.df(swap_start)  # forward-premium convention

    def synth_frame():
        return pd.DataFrame([{
            "diss_id": "SYNTH1", "orig_diss_id": None, "action": "NEWT", "event": "TRAD",
            "exec_ts": pd.Timestamp(datetime.datetime.combine(day, datetime.time(16, 30), tzinfo=ET)).tz_convert("UTC"),
            "event_ts": pd.Timestamp(datetime.datetime.combine(day, datetime.time(16, 30), tzinfo=ET)).tz_convert("UTC"),
            "effective_date": pd.Timestamp(day), "expiration_date": pd.Timestamp(expiry),
            "first_exercise": pd.Timestamp(expiry), "maturity": pd.Timestamp(maturity),
            "strike_raw": f"{K * 1e4:.4f}", "strike_notation": 4.0,  # BPS on purpose (verification ii)
            "premium_raw": f"{prem_fwd:,.2f}", "premium_ccy": "USD",
            "notional_raw": f"{notional:,.0f}", "notional_ccy": "USD",
            "package": False, "package_price_raw": None, "block": False,
            "cleared": "N", "platform": "SYNTH", "right": "payer", "pclass": "ois",
            "style": "EUROPEAN", "vintage": "upi", "file_date": day.isoformat(),
        }])

    def run_pipeline():
        funnel: dict = {}
        p = phase_dedup(synth_frame(), funnel)
        p = phase_parse(p, funnel)
        p = phase_straddles(p, funnel)
        assert len(p) == 1, f"synthetic print did not survive the pipeline: {funnel}"
        rows = price_day(ctx, p, funnel)
        assert len(rows) == 1, f"synthetic print was not priced: {funnel}"
        return rows[0]

    row = run_pipeline()
    err_i = abs(row["diff_fwd"])
    print(f"  planted node 1Yx10Y +25bp: mid {mid:.4f}bp, pipeline IV {row['iv_fwd']:.4f}bp, |diff| = {err_i:.6f}bp")
    assert err_i < 0.05, f"verification (i) FAILED: |diff| {err_i}bp"
    print("  PASS")

    print()
    print("VERIFICATION (ii): mutate the notation parse (treat code-4 bps as")
    print("decimal) - the same assertion must now FAIL.")
    _MUTATE_NOTATION = True
    try:
        try:
            row_m = run_pipeline()
            err_ii = abs(row_m["diff_fwd"]) if np.isfinite(row_m["diff_fwd"]) else float("inf")
        except AssertionError:
            err_ii = float("inf")  # print died at the strike sanity gate = detected
    finally:
        _MUTATE_NOTATION = False
    print(f"  mutated |diff| = {err_ii if np.isfinite(err_ii) else 'inf (print rejected by strike gate)'}")
    assert not (err_ii < 0.05), "verification (ii) FAILED: the mutation was NOT caught"
    print("  PASS (mutation caught)")

    print()
    print("VERIFICATION (iii): price the 1Yx10Y +25bp node with rateslib's NATIVE")
    print("swaption backend (IRSplineCube + IRSCall), invert through THIS module's")
    print("(F, A, T); must reproduce the store-served vol to < 0.1bp.")
    from MDP.CitiVelocityExcel.vol.rl_native_cube import build_rl_native_swaption_cube

    cube_data = store.reconstruct_cube(CUBE_ASSET, day)
    native = build_rl_native_swaption_cube(cube=cube_data, rl_curve=curve.handle(), notional=notional)
    f_nat = native.forward("1Y", "10Y")
    a_nat = native.annuity("1Y", "10Y")
    t_nat = native.time_to_expiry("1Y")
    k_nat = f_nat + 25e-4
    pv_nat = native.price("1Y", "10Y", k_nat, right="payer", notional=notional)
    quoted = float(cube_data.vol("1Y", "10Y", 25.0))
    iv_mine = _invert_print_iv(pv_nat / (notional * ann), k_nat, fwd, T, "payer")
    print(f"  forward: native {f_nat * 100:.6f}%  mine {fwd * 100:.6f}%  gap {abs(f_nat - fwd) * 1e4:.4f}bp")
    print(f"  annuity: native {a_nat:.8f}  mine {ann:.8f}  rel gap {abs(a_nat - ann) / a_nat:.2e}")
    print(f"  tte    : native {t_nat:.8f}  mine {T:.8f}")
    print(f"  store vol {quoted:.4f}bp  cross-inverted {iv_mine:.4f}bp  |err| {abs(iv_mine - quoted):.4f}bp")
    assert abs(iv_mine - quoted) < 0.1, f"verification (iii) FAILED: {abs(iv_mine - quoted):.4f}bp"
    print("  PASS")

    # optional: the live-verified anchor day, if the store has it
    print()
    print("ANCHOR SCAN (live-verified 1Yx10Y +25bp vol 84.5553bp):")
    found = False
    for d in pd.date_range("2026-08-01", "2026-08-08"):
        cfd = store.read_day(CUBE_ASSET, d.date())
        if cfd is None:
            continue
        node = cfd[(cfd["expiry"] == "1Y") & (cfd["tenor"] == "10Y") & (cfd["offset_bp"] == 25.0)]
        if len(node) and abs(float(node["vol_bp"].iloc[0]) - 84.5553) < 0.01:
            print(f"  {d.date()}: store serves {float(node['vol_bp'].iloc[0]):.4f}bp == anchor. FOUND")
            found = True
            break
    if not found:
        print("  anchor day not in store (outside SDR window anyway); same-day")
        print("  self-consistency above stands in, as the task allows.")


# --------------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=None, help="limit to the first N SDR files (shakeout)")
    ap.add_argument("--start", type=str, default=None)
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--force-price", action="store_true")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.verify_only:
        phase_verify()
        return

    files = sorted(Path(p) for p in glob.glob(str(SDR_DIR / "*" / "*" / "*.parquet")))
    files = [f for f in files if WINDOW_START.isoformat() <= f.stem <= WINDOW_END.isoformat()]
    if args.start:
        files = [f for f in files if f.stem >= args.start]
    if args.end:
        files = [f for f in files if f.stem <= args.end]
    if args.days:
        files = files[: args.days]
    log(f"{len(files)} SDR files in scope ({files[0].stem} .. {files[-1].stem})")

    funnel: dict = {"sdr_files": len(files), "first_file": files[0].stem, "last_file": files[-1].stem}
    raw = phase_extract(files)
    prints = phase_dedup(raw, funnel)
    parsed = phase_parse(prints, funnel)
    parsed = phase_straddles(parsed, funnel)
    priced = phase_price(parsed, funnel, force=args.force_price)
    phase_aggregate(priced, funnel)

    with open(FUNNEL_FP, "w", encoding="utf-8") as fh:
        json.dump(funnel, fh, indent=2, default=str)
    log(f"funnel -> {FUNNEL_FP}")
    print(json.dumps(funnel, indent=2, default=str))

    if not args.skip_verify:
        phase_verify()


if __name__ == "__main__":
    main()
