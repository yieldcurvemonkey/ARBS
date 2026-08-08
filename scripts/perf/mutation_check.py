"""Break each fix, confirm its test fails, put it back.

A test that still passes with the code it covers reverted is not a test, it is a
comment. Every mutation below removes exactly one property of one change, names
the test that is supposed to notice, and the script fails loudly if that test
still passes.

    <env>/python.exe scripts/perf/mutation_check.py

The edits are applied to the working tree and reverted in a ``finally``. Run it
on a clean tree; it refuses to start otherwise, because a crash mid-run with
unrelated edits present would be indistinguishable from a lost change.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
TESTS = "tests/test_citivelo_read_path_perf.py"


@dataclass
class Mutation:
    name: str
    path: str
    old: str
    new: str
    test: str
    removes: str


MUTATIONS = [
    Mutation(
        name="fixings-memo-key-drops-reference-date",
        path="MDP/IRSwaps/CITIVELO_EXCEL/fixings.py",
        old="""        key = (
            str(curve_name), citi_index, reference_date,
            bool(prefer_official), bool(fill_gaps),
        )""",
        new="""        key = (
            str(curve_name), citi_index,
            bool(prefer_official), bool(fill_gaps),
        )""",
        test="test_fixings_memo_does_not_leak_a_later_date_into_an_earlier_request",
        removes="reference_date from the memo key, so a later date's fixings serve an earlier curve",
    ),
    Mutation(
        name="fixings-memo-hands-out-its-own-object",
        path="MDP/IRSwaps/CITIVELO_EXCEL/fixings.py",
        old="        return replace(hit, series=hit.series.copy(), contributions=dict(hit.contributions))",
        new="        return hit",
        test="test_fixings_memo_hands_out_a_copy",
        removes="the defensive copy, so a caller mutating its fixings poisons every later request",
    ),
    Mutation(
        name="day-cache-never-revalidates",
        path="MDP/IRSwaps/CITIVELO_EXCEL/day_cache.py",
        old="            if hit.signature == signature:",
        new="            if True:",
        test="test_day_window_revalidates_when_the_partition_changes",
        removes="the mtime check, so an appended session is served truncated forever",
    ),
    Mutation(
        name="day-cache-reads-a-cold-partition",
        path="MDP/IRSwaps/CITIVELO_EXCEL/day_cache.py",
        old="""    for day, sig in zip(days, signature):
        if sig is None:
            continue""",
        new="""    for day, sig in zip(days, signature):
        if False:
            continue""",
        test="test_day_window_treats_a_cold_partition_as_absent",
        removes="the has_day contract, so a cold day hits the reader (and its L2 pull)",
    ),
    Mutation(
        name="par-rate-solved-twice",
        path="Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py",
        old="            setattr(irswap, _PAR_RATE_ATTR, (self, self._rl_curve_handle, par))",
        new="            pass",
        test="test_par_rate_is_computed_once_per_built_swap",
        removes="the par-rate handoff, restoring the second full IRS.rate() per reported rate",
    ),
    Mutation(
        name="par-rate-cache-ignores-the-curve",
        path="Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py",
        old="            if owner is self and handle is self._rl_curve_handle:",
        new="            if True:",
        test="test_par_rate_cache_is_not_reused_for_a_different_curve",
        removes="the identity guard, so a swap re-priced on another curve returns the first curve's rate",
    ),
    Mutation(
        name="fixings-identifier-rederived-per-leg",
        path="Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py",
        old="        if cached is not None and cached[0] is self._fixings:",
        new="        if False:",
        test="test_fixings_kwargs_resolve_once_per_wrapper",
        removes="the per-wrapper memo, restoring a clean+sort+SHA of the whole history per leg",
    ),
    Mutation(
        name="fixings-kwargs-cache-ignores-reassignment",
        path="Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py",
        old="        if cached is not None and cached[0] is self._fixings:",
        new="        if cached is not None:",
        test="test_fixings_kwargs_cache_follows_a_reassigned_series",
        removes="the identity guard, so replacing a curve's fixings has no effect",
    ),
    Mutation(
        name="omit-fixings-ignores-seasoning",
        path="Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py",
        old="            if start is not None and reference is not None and start >= reference:",
        new="            if True:",
        test="test_omit_unused_fixings_drops_them_only_for_a_forward_start",
        removes="the elapsed-period gate, so a seasoned swap is priced with no published fixings",
    ),
    Mutation(
        name="omit-fixings-on-by-default",
        path="Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py",
        old='        raw = str(os.getenv("ARBS_RL_OMIT_UNUSED_FIXINGS", "")).strip().lower()',
        new='        raw = str(os.getenv("ARBS_RL_OMIT_UNUSED_FIXINGS", "1")).strip().lower()',
        test="test_omit_unused_fixings_is_off_unless_asked_for",
        removes="the default-off promise, silently changing every reported rate by a rounding step",
    ),
    Mutation(
        name="bulk-ignores-ignore-cache",
        path="MDP/IRSwaps/IRSwapsMDP.py",
        old="""        store_eligible = (
            self.source.upper() not in CITIVELO_EXCEL_QL_TOKENS
            and not request.get("force_refresh", request.get("ignore_cache", ignore_cache))
            and not request.get("no_curve_store", False)
        )""",
        new="""        store_eligible = (
            self.source.upper() not in CITIVELO_EXCEL_QL_TOKENS
        )""",
        test="test_bulk_get_data_honours_ignore_cache",
        removes="the freshness guard, so a caller asking for a rebuild gets the cache",
    ),
    Mutation(
        name="bulk-serves-the-wrong-snapshot",
        path="MDP/IRSwaps/IRSwapsMDP.py",
        old="""                positions = {
                    original: int(
                        (stamps - pd.Timestamp(wanted).tz_convert("UTC")).abs().values.argmin()
                    )
                    for original, wanted in wants
                }""",
        new="""                positions = {original: 0 for original, wanted in wants}""",
        test="test_bulk_get_data_matches_single_point_intraday",
        removes="the nearest-snapshot search, so every request gets the window's first row",
    ),
]


def _run(test: str) -> bool:
    """True when the test PASSES."""
    proc = subprocess.run(
        [PY, "-m", "pytest", f"{TESTS}::{test}", "-x", "-q", "-p", "no:randomly",
         "--no-header", "-W", "ignore"],
        cwd=ROOT, capture_output=True, text=True,
    )
    return proc.returncode == 0


def main() -> int:
    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True
    ).stdout
    staged = [line for line in dirty.splitlines() if line and not line.startswith("??")]
    if staged:
        print("Refusing to run: the working tree has uncommitted changes.\n" + "\n".join(staged))
        return 2

    failures = []
    for mutation in MUTATIONS:
        target = ROOT / mutation.path
        source = target.read_text(encoding="utf-8")
        if source.count(mutation.old) != 1:
            failures.append(f"{mutation.name}: anchor not found exactly once in {mutation.path}")
            print(f"SKIP {mutation.name}: anchor text is stale")
            continue

        print(f"\n=== {mutation.name}")
        print(f"    removes: {mutation.removes}")
        try:
            target.write_text(source.replace(mutation.old, mutation.new), encoding="utf-8")
            passed = _run(mutation.test)
        finally:
            target.write_text(source, encoding="utf-8")

        if passed:
            failures.append(f"{mutation.name}: {mutation.test} STILL PASSED with the fix removed")
            print(f"    FAIL  {mutation.test} still passed -> it does not test this")
        else:
            print(f"    ok    {mutation.test} failed, as it must")

    print("\n" + "=" * 70)
    if failures:
        for f in failures:
            print("FAIL " + f)
        return 1
    print(f"All {len(MUTATIONS)} mutations were caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
