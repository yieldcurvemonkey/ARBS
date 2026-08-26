import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
import numpy as np, pandas as pd
D = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
ev = pd.read_parquet(D + r"\event_paths.parquet")
s = ev[(ev.offset_min == 240) & (ev.contract_rank == 3) &
       ev.stance_score_exante.notna() & ev.d_rate_bp_from_baseline.notna()].copy()
print("slab rows", len(s))
print("stance_score == 0 exactly:", int((s.stance_score_exante == 0).sum()))
print("stance_sign value counts:", dict(s.stance_sign.value_counts()))
print("signed_d_bp isna in slab:", int(s.signed_d_bp.isna().sum()))
bad = s[s.signed_d_bp.isna()]
print("\nrows with NaN signed_d_bp:")
print(bad[["speaker", "speech_ts", "stance_score_exante", "stance_sign",
           "d_rate_bp_from_baseline", "signed_d_bp"]].to_string())
ok = s[s.signed_d_bp.notna()]
diff = (ok.signed_d_bp - ok.d_rate_bp_from_baseline * ok.stance_sign).abs()
print("\nON NON-NAN ROWS: max |signed - raw*sign| =", diff.max(), " n =", len(ok))
print("identity holds on all non-NaN rows:", bool(diff.max() < 1e-12))
