"""Run sv_h2_h3.main() once the Treasury spline cache is complete, and
persist BOTH the printed report and the structured results (pickled) durably
in-worktree, per the task's constraint against leaving long-run output only
in a shell buffer.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.sv_h2_h3 import main

if __name__ == "__main__":
    result = main()
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".superpowers", "sdd", "2026-08-04-strikeless-vol", "h2_h3_results.pkl",
    )
    with open(out_path, "wb") as f:
        pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"\nStructured results pickled to {out_path}", flush=True)
