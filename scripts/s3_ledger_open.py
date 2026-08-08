"""Append session-3's opening ledger rows. Append-only; never rewrites."""
import json
import pathlib

LEDGER = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "superpowers" /
          "ledgers" / "2026-08-08-citivelo-rv-loop-ledger.jsonl")

ROWS = [
    {
        "ts": "2026-08-09T10:00:00", "id": "L-0075", "kind": "note", "family": None,
        "text": (
            "SESSION 3 OPENS. State of record read in the handover's order (ledger 91 rows through "
            "L-0074, findings, design, checker charter, memory). BRANCH: PR #405 MERGED to main "
            "(main is 01095918, the merge commit), so session 3 cuts feat/citivelo-rv-loop-s3 from "
            "origin/main rather than continuing on s2. WORKTREE: stays C:/Users/chris/clee/ARBS-rv "
            "for the L-0046 reason - the loop's 87 gitignored panels live there and are the tie-out "
            "targets; a fresh worktree would strand them. Since s2 is fully merged, cutting the new "
            "branch in-place strands nothing. QUEUE ITEMS 1 AND 2 BOTH RE-CHECKED AND BOTH STILL "
            "BLOCKED, with evidence rather than assumption: (1) famb STRG forward run - L-0047 "
            "requires on-or-after 2026-09-02, today is 2026-08-09, NOT previewed; (2) SR3 listed-"
            "butterfly re-cost - DATABENTO_API_KEY absent from process env, from ARBS/.env, from "
            "~/.databento (directory does not exist) and from every .env in either tree; databento "
            "0.83.0 is installed but keyless and the filesystem still holds exactly ONE dbn file "
            "(Downloads/glbx-mdp3-20260715.mbo.dbn.zst). L-0048's unblocker statement stands "
            "unchanged. SO SESSION 3 IS QUEUE ITEM 3: a new family at loop N, on the one genuinely "
            "unexplored conditioning axis (L-0067/handover section 6). trials_total carried forward "
            "= 37. Curve coverage RE-MEASURED and materially better than the design doc records: "
            "USD-SOFR-1D-CITIVELOEXCEL now serves 5,506 days 2005-01-03..2026-08-07 (the warm "
            "extension completed), not the 1,346 the design table lists."
        ),
        "trials_delta": 0, "trials_total": 37,
    },
    {
        "ts": "2026-08-09T10:05:00", "id": "L-0076", "kind": "note", "family": None,
        "text": (
            "USER DIRECTIVES, mid-session, BINDING ON THE MACHINE from here (recorded in the ledger "
            "because they arrived in a transcript and would otherwise be lost at the session "
            "boundary): (1) every QueryDrivenBacktest notebook this program ships must carry an "
            "EQUITY CURVE PLOT - pattern named by the user at "
            "notebooks/backtests/famb_fade_qdb_run.ipynb (equity = pd.Series(bt.mtm_history), "
            "ax.step(where='post'), with Sharpe / NW t / maxDD printed alongside); (2) it must "
            "integrate the repo's backtest ANALYTICS - pattern named by the user at "
            "notebooks/backtests/tfp_swap_spread_backtest.ipynb: QueryBacktestTearSheet."
            "from_backtest(bt).plot_plotly(), a closed-positions frame from "
            "bt.portfolio.closed_positions_log with per-trade P&L, a trade timeline of cumulative "
            "realised P&L, and a signal-vs-P&L overlay. These extend, and do not replace, the "
            "sv_qdb_certification template and the session-2 rule that any newly graded hypothesis "
            "ships its QDB notebook as part of grading. The two assertions that caught the session-2 "
            "silent-no-op traps (non-zero marks AND a closed-position count) stay mandatory - a "
            "handsome equity curve of a book that never traded is exactly the failure they exist to "
            "catch, and a plot makes that failure MORE persuasive, not less."
        ),
        "trials_delta": 0, "trials_total": 37,
    },
    {
        "ts": "2026-08-09T10:20:00", "id": "L-0077", "kind": "note", "family": "F7",
        "text": (
            "PRE-EMPTIVE LOOKAHEAD CLOSE, measured before the family that would have benefited from "
            "it was registered. THE PART 43 FILE DATE IS THE DISSEMINATION DATE, NOT THE EXECUTION "
            "DATE, and the gap is large enough to manufacture a flow-conditioning result on its own. "
            "Measured on five files spread across the 643-day cache: rows whose ET execution date "
            "equals the file date are 84.1% (2023-12-01), 77.7% (2024-08-14), 92.4% (2025-04-08), "
            "89.2% (2025-11-28) and 69.6% (2026-07-21) - so between 8% and 30% of every file is "
            "prints executed EARLIER, overwhelmingly at lag 1 (5,812 of 20,068 rows on 2026-07-21) "
            "with a thin tail out to 1,276 days. A day-t flow variable aggregated by EXECUTION "
            "timestamp therefore contains prints that had not been disseminated by the day-t close, "
            "and the un-disseminated ones are disproportionately the large/blocked prints that ARE "
            "the signal. BINDING: F7's flow variable is aggregated by FILE DATE and by nothing else. "
            "TWO MORE INPUTS MEASURED AT THE SAME TIME. (a) NOTIONAL CAPS: 3.33% of USD rows carry a "
            "capped notional string ('1,100,000,000+'), and capping truncates exactly the top of the "
            "size distribution - so F7's shock statistic is pre-stated as COUNT-based, with a "
            "notional-weighted arm as a registered sensitivity in which capped values are read at "
            "their floor (which understates a shock, the conservative direction). (b) PACKAGE "
            "LINKAGE WORKS: 'Package indicator' is populated (9,018 True of 20,068 rows on "
            "2026-07-21; 2,742 of 5,104 USD rows) and execution-timestamp linking within a file "
            "resolves package-flagged USD rows into 921 groups of size 2 (395), 1 (245), 3 (137), "
            "4 (51), 6 (26), 5 (19) - i.e. 2- and 3-leg curve packages are directly reconstructable "
            "without touching the prod tape, its ptp_group_id regression or its statement-timeout "
            "trap. scripts/s3_sdr_diag.py."
        ),
        "trials_delta": 0, "trials_total": 37,
    },
    {
        "ts": "2026-08-09T10:25:00", "id": "L-0078", "kind": "note", "family": None,
        "supersedes": "L-0072 (its consequence 2; the conclusion it supported is unchanged)",
        "text": (
            "AN IMPORTED CLAIM DOES NOT DESCRIBE THIS DATA - COMPRESSION IS ON THE PART 43 TAPE. "
            "L-0072 took from pfin/SwapPulse's economic_classification.py that ('*','COMP') carries "
            "on_p43 = False (compression excluded from Part 43 by 43.2) and used it to STRIKE "
            "compression as a candidate explanation for CM-2's mid-peak. Measured on ten files "
            "spread across the cache (47,029 USD-OIS rows): there are 246 NEWT+COMP USD-OIS rows, "
            "on 5 of the 10 days, and ALL 246 carry a parsed fixed rate; 431 rows carry event COMP "
            "under some action. So the import is wrong about this tape, and any future study that "
            "relies on on_p43 flags to define a universe must verify them against the file rather "
            "than trust the matrix. THE CONCLUSION L-0072 SUPPORTED IS NEVERTHELESS UNCHANGED, for a "
            "different and better reason: CM-2's own universe filter is action == NEWT AND event == "
            "TRAD, which excludes every one of those rows regardless of what the regulation says - "
            "so labelled compression cannot explain CM-2's mid-peak because CM-2 never contained it. "
            "What remains unexcluded and unmeasured is the mid-printed population that is NOT "
            "labelled COMP: portfolio/list trades, inter-affiliate prints and unwinds struck at mid, "
            "all of which carry NEWT+TRAD. L-0060's level therefore stays unclaimable, and the "
            "honest statement of why is now 'other mid-printed populations remain unseparated', not "
            "'compression is excluded by regulation'. Note the direction: this correction does not "
            "flatter anything - it removes a reason to be confident. scripts/s3_comp_check.py."
        ),
        "trials_delta": 0, "trials_total": 37,
    },
    {
        "ts": "2026-08-09T10:30:00", "id": "L-0079", "kind": "parked", "family": "F9-side",
        "text": (
            "PARKED WITH ITS REASONING, so a later session does not re-derive it as though it were "
            "new: inferring trade SIDE from the SIGNED deviation of a print against a contemporaneous "
            "mid (the Lee-Ready tick-rule route) is a genuinely different route from the one L-0041 "
            "closed - L-0041 and its re-confirmation in L-0073 are about the SDR FIELDS, and both "
            "sibling programs block on a side_mapping gate and take direction from CME futures open "
            "interest instead. Nobody tried the price route, and CM-2 already built the machinery "
            "(every print priced against a same-day curve). IT IS NOT RUN THIS SESSION, for three "
            "stated reasons: (1) F7 does not need side - it takes magnitude and timing from the flow "
            "and direction from the curve; (2) the validation burden is the whole session - CM-2 "
            "measured the deviation as 3.3bp overnight against 0.508bp at the 15:00 ET stamp, so "
            "away from the stamp hour the signed deviation is dominated by intraday DRIFT rather "
            "than aggression, and restricting to the stamp hour costs most of the sample; (3) CM-2's "
            "deviation distribution PEAKS at mid with no dip, so a large share of prints carry no "
            "usable sign at all. If it is ever run, the validation is the standard one and must be "
            "registered first: the classified side must predict the subsequent short-horizon move, "
            "with a shuffled-print-time control, and the drift confound handled by measuring against "
            "a contemporaneous intraday mark rather than the EOD stamp."
        ),
        "trials_delta": 0, "trials_total": 37,
    },
]


def main() -> None:
    existing = {json.loads(ln)["id"] for ln in
                LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()}
    with LEDGER.open("a", encoding="utf-8") as fh:
        for r in ROWS:
            if r["id"] in existing:
                print(f"SKIP {r['id']} (already present)")
                continue
            fh.write(json.dumps(r) + "\n")
            print(f"APPEND {r['id']}")


if __name__ == "__main__":
    main()
