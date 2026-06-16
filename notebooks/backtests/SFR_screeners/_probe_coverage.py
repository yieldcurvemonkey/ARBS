"""Probe smile-cache coverage + realistic warm per-date cost across the year."""
import sys, datetime, time
sys.path.insert(0, r"C:\Users\chris\clee\ARBS")
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from RVUtils.ImpliedDistribution import SFRImpliedDistribution

mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
dist = SFRImpliedDistribution(use_sabr_vols=True, sabr_extrapolation=True, sabr_n_strikes=200)
syms = ["SFRM26","SFRU26","SFRZ26","SFRH27","SFRM27","SFRU27","SFRZ27","SFRH28","SFRM28","SFRU28","SFRZ28","SFRH29"]

probe_dates = [
    datetime.date(2025, 6, 16),
    datetime.date(2025, 9, 15),
    datetime.date(2025, 12, 15),
    datetime.date(2026, 2, 17),
    datetime.date(2026, 4, 15),
    datetime.date(2026, 5, 22),
]

for d in probe_dates:
    t0 = time.time()
    n_hit = n_miss = 0
    slow_syms = []
    extract_t = 0.0
    for s in syms:
        ts0 = time.time()
        smile = None
        for kw in [{"symbol": s, "as_of": d, "show_tqdm": False},
                   {"symbol": s, "as_of": d, "strike_offsets_bps": "listed", "show_tqdm": False}]:
            try:
                smile = mdp.fetch_sabr_smile(kw); break
            except Exception:
                continue
        f_elapsed = time.time() - ts0
        if smile is None:
            n_miss += 1
            continue
        n_hit += 1
        if f_elapsed > 1.0:
            slow_syms.append(f"{s}:{f_elapsed:.1f}s")
        te0 = time.time()
        try:
            dist.extract(smile, run_bl=False, run_gm=False, run_bkm=True)
        except Exception:
            pass
        extract_t += time.time() - te0
    total = time.time() - t0
    print(f"{d}: {n_hit}/12 fetched, {n_miss} miss | fetch+extract total={total:.1f}s "
          f"(extract={extract_t:.1f}s) | slow_fetch=[{', '.join(slow_syms) if slow_syms else 'none'}]")
