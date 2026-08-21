import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from MDP.ETFHoldings import store as HS
from MDP.ETFHoldings.universe import spec

for t in ["TLT", "TLH", "IEF", "IEI", "GOVT", "SHY"]:
    try:
        sp = spec(t)
    except KeyError as e:
        print(t, "NO SPEC", e)
        continue
    cov = HS.coverage(t)
    print("=" * 60)
    print(t, sp.maturity_band, "AUM", f"{sp.aum_usd/1e9:.2f}bn", "inception", sp.inception)
    if cov.empty:
        print("  NO HOLDINGS DATA")
    else:
        print(cov.to_string(index=False))
