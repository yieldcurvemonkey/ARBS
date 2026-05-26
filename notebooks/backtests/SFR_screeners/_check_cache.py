import sys, datetime, time
sys.path.insert(0, r"C:\Users\chris\clee\ARBS")
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
syms = ["SFRM26","SFRU26","SFRZ26","SFRH27","SFRM27","SFRU27","SFRZ27","SFRH28","SFRM28","SFRU28","SFRZ28","SFRH29"]
d = datetime.date(2026, 5, 22)

t_total = time.time()
for s in syms:
    t0 = time.time()
    mode = "delta"
    try:
        smile = mdp.fetch_sabr_smile({"symbol": s, "as_of": d, "show_tqdm": False})
    except Exception:
        mode = "listed"
        try:
            smile = mdp.fetch_sabr_smile({"symbol": s, "as_of": d, "strike_offsets_bps": "listed", "show_tqdm": False})
        except Exception as e:
            print(f"  {s}: MISS  ({time.time()-t0:.2f}s) - {e}")
            continue
    elapsed = time.time() - t0
    cached = "HIT" if elapsed < 1.0 else "SLOW"
    print(f"  {s}: {cached}  ({elapsed:.2f}s) mode={mode} n_pts={len(smile.points)}")

print(f"\n  TOTAL: {time.time()-t_total:.2f}s")
