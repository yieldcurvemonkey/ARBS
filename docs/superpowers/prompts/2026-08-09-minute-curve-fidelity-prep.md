# Prep task: make the minute-curve read honest about *which* minute it served

## How to work on this

**Work autonomously — I am away and cannot answer questions or approve anything.** You have full
authority over design and implementation. Where you would normally stop and ask, pick the option
you can best defend, write down why, and continue.

This is a **preparation task** for a much larger piece of work (dealer-direction inference on the
USD swap SDR tape, repriced off Citi Velocity curves). It is deliberately scoped small and sharp:
the larger task is blocked on trusting that when you ask for the curve at a specific minute, you
either get that minute or you find out you didn't. Right now neither is true.

Expect this to take a while — the measurement half is more work than the patch half, and the
measurement is the more valuable deliverable. **Open a PR; never merge to `main`.**

---

## The problem

Dealer direction is inferred by repricing a printed swap against the market as it stood just
before execution — specifically the curve snapshot at **t − 1 minute** from the trade's execution
timestamp — and seeing which side of mid the print landed. The whole inference rests on that
snapshot being (a) genuinely close to t−1min and (b) genuinely *before* the trade.

The current minute read satisfies neither, and fails silently in three distinct ways.

### Where it lives

`MDP/IRSwaps/IRSwapsMDP.py::_load_citivelo_excel_minute_store_point` — the read path for the
`<curve>-CITIVELOEXCELMIN` assets. Roughly:

```python
window = day_window(store, asset, (local_date, local_date - 1d, local_date + 1d))
position = int((stamps - pd.Timestamp(wanted).tz_convert("UTC")).abs().values.argmin())
row = window.frame.iloc[[position]]
```

### Failure 1 — it can serve a snapshot from *after* the trade

`.abs().argmin()` is nearest in **either direction**. If the nearest stored minute is after the
execution timestamp, that is what you get. For valuation that is a rounding choice; for direction
inference it is circular — a post-trade curve may already reflect the market impact of the very
print you are trying to classify, which biases the call toward "the trade moved the market", i.e.
toward whatever direction the trade actually was.

Note the same file's *other* path already learned a version of this lesson: a comment in
`_load_citivelo_curve_store_point` records that `nearest` used to jump **forward** to 01:00 ET and
was changed, with measured errors (5Y mean |error| 3.55 bp, p90 7.30 bp, max 12.05 bp; 2Y max
23.12 bp). Read that comment — it is the closest existing precedent for the measurement you are
about to do.

### Failure 2 — there is no staleness bound on this path at all

`_assert_snapshot_fresh` / `_max_snapshot_staleness` exist in the same class and are called from
`_load_citivelo_curve_store_point` and the ERIS-live path. **They are not called here.** So the
served snapshot can be arbitrarily far from what you asked for and nothing warns.

Worth understanding before you copy it: the existing guard's default is
`ARBS_MAX_CURVE_STALENESS_HOURS=12`. **Twelve hours is the wrong order of magnitude for this use
case** — it was designed to catch "the feed died overnight and we're serving yesterday's close",
not "give me the minute before this trade". A request at 14:32 served from 02:32 would pass it.
Do not simply wire the existing guard in and call it done; the tolerance that matters here is
measured in minutes.

### Failure 3 — the ±1 day window plus a blanket `except Exception`

The window is `(local_date, local_date - 1, local_date + 1)`. Combined with nearest-in-either-
direction and no staleness bound, an empty or thin partition for the requested day can silently
resolve to **yesterday's or tomorrow's** curve. An overnight move of a few basis points will
invert most direction calls, because most prints land within a basis point or two of mid.

The whole block is wrapped in `except Exception: ... return None`, which then degrades to building
from live Excel. That is correct behaviour for a *valuation* caller and wrong for a *research*
caller who needs determinism and would rather fail loudly than get a different curve.

### Failure 4 — density is a gradient and nothing exposes it

"Day present in the store" is not "1-minute data available". Sampled snapshot counts per day:

| curve | early | mid | recent |
|---|---|---|---|
| `USD-SOFR-1D-CITIVELOEXCELMIN` | 2022-08-31: **18** | 2024-08-19: 1,320 | 2026-08-07: 1,020 |
| `USD-FEDFUNDS-1D-CITIVELOEXCELMIN` | 2026-02-09: 240 | 2026-05-10: 180 | 2026-08-07: 1,020 |

Roughly 811 of SOFR's 1,233 stored days are "dense"; the rest are a ten-minute era or sparser.
Some of that is being re-solved at true 1-minute by a running backfill, so **re-measure rather
than trusting these numbers**. On an 18-snapshot day, "t−1min" is not a meaningful request at all,
and the caller currently has no way to know that it got something else.

---

## What I would like out of this

Two deliverables. The measurement matters more than the patch — a patch built on an unmeasured
assumption is how this codebase has been bitten repeatedly.

### 1. Measure the realised lag, across the actual tape period

For the curves and date range the direction work will use — `USD-SOFR-1D-CITIVELOEXCELMIN` over
the SDR tape span (tape starts 2024-03-01) and `USD-FEDFUNDS-1D-CITIVELOEXCELMIN` over its
shallower span (starts 2026-02-09) — quantify what a t−1min request actually returns:

- distribution of **signed** (requested − served) lag: median, p90, p99, max, and crucially the
  **fraction served from the future** (negative lag)
- how that distribution varies by day density, by time of day (the feed's first row is ~01:00 ET
  and it stops between ~11:58 and ~16:00 ET depending on the day), and by curve
- how often the ±1 day window resolves to a **different calendar day** than requested
- **translate lag into basis points.** A lag figure alone does not tell anyone whether it matters.
  Reprice a representative swap (say 2Y, 5Y, 10Y, 30Y) at the served snapshot versus the true
  nearest-preceding snapshot, and report the rate difference distribution. The precedent
  measurement in `_load_citivelo_curve_store_point`'s comment did exactly this and it is why that
  bug was taken seriously.

Sample real execution timestamps from the tape (`arbs_usd_swap_tape_legs_v3` — table names come
from `SDRUtils/_swappulse_scripts/_tape_tables.py`, import them, never hardcode a suffix) rather
than a synthetic uniform grid. The distribution of trade times is not uniform and the tails are
where this hurts.

### 2. Patch the read path so the caller can trust it

I am not prescribing the design. What the direction work needs from it:

- **Backward-only lookup must be available**, so a caller can guarantee it never prices against a
  post-trade curve.
- **A caller-supplied tolerance in minutes**, with a miss being detectable rather than silent.
- **The served timestamp and the realised lag must reach the caller**, so downstream can record
  them per trade and gate on them. A direction call made against a 40-minute-stale curve should be
  *marked*, not silently pooled with one made against a 30-second-stale curve.
- **A way to ask whether a day is dense enough** to support minute-resolution work at all, without
  reading the whole partition.
- **Do not break existing valuation callers.** They legitimately want nearest-with-fallback and
  a soft `None` on miss. Whatever you do should be opt-in for the strict path, or default-safe in
  a way you have verified against current callers. Find them first —
  `grep` for `_load_citivelo_excel_minute_store_point` and for the `-CITIVELOEXCELMIN` asset
  suffix, and check `SDRUtils/stir_flow/pricing.py::CurvePricer` which is what the direction work
  will actually call through.

Consider whether the existing `_assert_snapshot_fresh` should be generalised (a tolerance
parameter rather than one global env-var hour count) rather than adding a second parallel
mechanism. Two guards with different semantics on adjacent code paths is how the current
inconsistency arose.

---

## Context you will need

### Environment

- Python: `C:\Users\chris\anaconda3\envs\stir\python.exe`, invoked **directly**. Do **not** use
  `conda run` — parallel invocations collide on a temp file and return empty output with exit
  code 0, which looks exactly like a passing test run.
- `ARBS_SUPABASE_ENABLED=0` before anything that imports `Caching`.
- Work in a **new git worktree** on a short sibling path (e.g. `../ARBS-min`), never the primary
  checkout. Always `git -C <path> ...`; never rely on `cd` having stuck.
- Fast gate: `python -m pytest tests -m "not slow and not network and not db"` — ~30 min, ~5,400
  tests. A small number of failures are pre-existing on `main`; verify that against `main` in a
  clean worktree rather than assuming, and say which ones you checked.

### The two stores — read the local one

`Caching/curve_store.py` — `CurveStore.default()` — is the **working store**, local parquet at
`{base}/raw/asset=<curve>/date=<YYYY-MM-DD>/`. The Supabase tables (`arbs_curve_snapshots_v1`,
`arbs_curve_intraday_blocks_v1`) are an **L2 sync target that lags badly**: as of 2026-08-09 the
local store had 1,233 days of `USD-SOFR-1D-CITIVELOEXCELMIN` and Supabase had 632, and
`USD-FEDFUNDS-1D-CITIVELOEXCELMIN` was absent from Supabase entirely. I made exactly this mistake
and concluded a curve did not exist. Read the local store.

Useful API notes: `available_dates(curve_name)`; `read_raw_nodes` is keyword-only after the first
argument — `read_raw_nodes(name, start=..., end=...)`; `has_day`, `read_raw_day`,
`reconstruct_curves_batch`. There is also `MDP/IRSwaps/CITIVELO_EXCEL/day_cache.py::day_window`,
which is what the current path uses and which exists because parsing stamps per-observation cost
21.4 ms each.

**Do not casually reorder the `(0, -1, +1)` day window.** The existing code documents that the day
order is part of the contract because the nearest-snapshot search breaks ties positionally. If you
change the search semantics, that constraint may dissolve — but say so deliberately rather than
letting it change underneath you.

### Timezones

Citi's wire stamps are **America/New_York**; the store partitions by the curve's **local trading
date**. `MDP/IRSwaps/CITIVELO_EXCEL/timestamps.py` has `resolve_request` and `from_wire_naive`.
Converting ET wire stamps to curve-local *before* day bucketing has been a real source of bugs
here. A session that runs to 19:59 local straddles the UTC date boundary, which is why the window
spans neighbouring days at all.

### A running backfill may be changing the data underneath you

A deep intraday fetch is extending and re-solving these curves (the ten-minute era is being
re-solved at true 1-minute). Two consequences: your density measurements have a shelf life, so
**stamp them with the date and the store state you measured against**; and the fetch drives Citi's
Excel add-in over COM against an Excel that a **human signed into** — do not try to automate that,
do not enable `--auto-restart` (it does not work on this machine and it evicts the user from a
live Excel session), and prefer the already-warmed store over any live fetch.

---

## Method notes — these are from recent failures in this repo, not generic advice

**Validate your measurement tool against a known-good case before trusting it.** In a recent
session I wrote a probe that called production's own fetcher and concluded a day of data was
unreachable. It was wrong: the probe fetched only day D while production fetches D **plus D+1
forward**. Two agents ran that probe and both confirmed the wrong answer; the production run
disproved it. Reusing production's functions is not enough — the call has to reproduce
production's parameters and window. For this task specifically: before you report a lag
distribution, check it against a handful of cases where you can verify the answer by hand.

**Exit code 0 is not success.** `cmd | tail` then `$?` gives you `tail`'s status. That produced a
fake pass twice in one recent session, once for pytest (really exit 1) and once for an acceptance
script. Capture exit codes without a pipeline.

**A silent fallback is the thing you are fixing — do not add another one.** The bug here is
`except Exception: return None` plus nearest-with-no-bound. If your patch introduces a new default
that quietly does something reasonable-looking, you have moved the problem rather than solved it.

**When you relax or widen a threshold, get it checked by something other than yourself.** Choosing
the tolerance is the one genuinely judgement-laden decision in this task, and it is exactly where
motivated reasoning hides. Justify the number with the measurement, not with intuition.

**Prefer a test that fails before your fix.** For each failure mode above, I would want to see a
test that reproduces it against the current code — particularly the served-from-the-future case
and the wrong-calendar-day case — and then passes after. A test written only after the fix proves
much less.

---

## What "done" looks like

- A PR (not merged) with the patch and its tests.
- A short written measurement report — in `docs/` — with the lag distributions, the basis-point
  translation, the density picture, and an explicit statement of **what date range and which
  curves are actually fit for minute-resolution direction work**, and which are not. That
  conclusion is the thing the next session needs most.
- Anything you could not determine, stated as such rather than assumed.

If the measurement shows the problem is smaller than I think — that in practice the served
snapshot is almost always the right one — that is a completely acceptable and useful outcome. Say
so with the numbers, and scale the patch down accordingly. I would rather have an accurate small
finding than a large fix for a problem that isn't there.
