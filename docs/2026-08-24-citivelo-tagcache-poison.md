# HANDOVER — something is writing swaption vol into the OIS par-rate tags. Find it and stop it.

## Work autonomously

**You have full permission to make every design and implementation decision.** The
person who set this up has stepped away and will not answer questions, review a plan,
or unblock you. Do not stop to ask. Choose, justify the choice in the writeup, and
keep going.

**Nothing below is a diagnosis.** It is the terrain: what is broken, what has been
measured, and which traps have already cost someone a rebuild. **Nobody has found the
root cause. That is your job, and you should find it yourself rather than confirming
anyone's guess** — including the guesses implied by the notes below. Where I state a
finding, it is measured and you can re-derive it. Where I state a belief, I have
labelled it as one, and you should treat it as a lead to falsify, not a conclusion to
build on.

---

## The bug

The Citi Velocity daily tag cache serves **swaption normal volatility under the OIS
par-rate tags**. Reading `RATES.OIS.USD_SOFR.PAR.2Y` returns ~102 on a day the 2y
SOFR OIS was 4.24%.

Measured on 2026-08-24, and you should re-measure before doing anything:

```
RATES.OIS.USD_SOFR.PAR.2Y   5,507 daily rows, 2005-01-03 -> 2026-08-21
  2,600 of them (47.2%) lie outside any band a USD par rate can occupy
  first impossible 2015-10-08, last impossible 2026-07-29, max 164.649
```

The whole "par curve" on 2023-06-01, as the cache serves it:

| tenor | 1Y | 2Y | 3Y | 5Y | 7Y | 10Y | 20Y | 30Y |
|---|---|---|---|---|---|---|---|---|
| cached | 144.5 | 102.0 | 92.4 | 164.6 | 163.5 | 128.7 | 137.6 | 113.8 |

The real 2y that day was **4.2361%**. That table is not a curve — not monotone, not in
percent, not within 20x of anything. It is a vol surface wearing a rate curve's name.

**44 `RATES.OIS.USD_SOFR.PAR.*` parquets are affected**, the whole tenor family.

## What makes this hard, and why it survived

**The poisoned days are INTERLEAVED with good ones.** The cache merges incoming into
existing rather than replacing, so only the days the vol series covered were
overwritten. The series therefore still plots as a plausible line and only fails a
value check, never a shape check. Nothing downstream noticed for as long as it has
been happening.

**It is not static.** A note written 2026-08-21 recorded the last poisoned day as
2026-08-17 with 08-18 onward correct. On 2026-08-24 the last poisoned day reads
**2026-07-29**. Something has partially healed the tail since. Do not assume today's
extent equals yesterday's — **snapshot the current state to a file before you touch
anything**, or you will lose the ability to tell your repair from the drift.

---

## What is already known — measured, not inferred

- **The fingerprint is a scrambled mapping, not an offset.** On 2026-08-17 cached
  `PAR.30Y` = `76.5078` = the `SwaptionCubeStore` ATM `vol_bp` at **6M x 10Y**,
  exactly. `PAR.1Y` = vol(2M, 5Y). `PAR.5Y` = vol(3M, 1Y). Whatever writes these is
  not shifting a tenor axis by one; it is landing cube grid points on rate tags under
  some other correspondence. **Working out that correspondence exactly is probably
  the fastest route to the writer**, because it tells you the shape of the iteration
  that produced it. Re-derive it — do not trust the three pairs above.
- **The first poisoned day, 2015-10-08, is the swaption cube's own first day.** That
  is unlikely to be a coincidence and it bounds where to look.
- **The cache is the wrong side; the add-in is right.** `CurveStore`
  `USD-SOFR-1D-CITIVELOEXCEL` for 2026-08-14 reprices the 2y to **4.02772** (rebuilt
  from its stored discount factors) against a `direct="live"` read that agrees to
  ~1e-8bp, while the tag said 67.1 that week. So this is a cache-write defect, not a
  vendor problem.
- **A bulk rewrite happened on 2026-08-21, 07:06-09:36**: 2,839 parquets, of which
  1,989 were `RATES.VOL.USD.*` (exactly the cube grid size) plus the 44 PAR. That
  process was never identified.
- **And it is still happening.** On 2026-08-24 all 44 PAR parquets carry an mtime of
  **15:46:04-15:46:08**, and 10,475 parquets in the same directory were written
  2026-08-23 11:00. Whatever this is, it runs repeatedly and recently.

**A belief, not a finding:** the 15:46 rewrite on 2026-08-24 happened while another
session was reading those tags through `CitiVeloTagCache().read(...)`. `cache.py`
carries both a `merge(existing, incoming)` and a `write(...)`, and a comment in it
says "``get`` writes through here". **Whether a READ can trigger a write, and whether
that is the mechanism here, is exactly the thing to establish rather than assume.** It
is equally possible a scheduled warm is responsible and the timing is coincidence.

---

## Where to look, and what not to trust

```
MDP/CitiVelocityExcel/cache.py        the tag cache: merge(), write(), the read path
MDP/CitiVelocityExcel/                the rest of the Excel/COM bridge
RVUtils/ or MDP/ swaption cube store  the 1,989-tag RATES.VOL.USD.* family
scripts/                              warm/backfill entry points, cron-shaped things
```

Cache root: `C:\Users\chris\AppData\Local\ARBS\ARBS\Cache\citivelo_excel\DAILY\CLOSE`
(14,535 parquets). A tag's file is `<TAG>.parquet` with a `.meta.json` sibling — **the
sidecars may record who wrote and when; read them before reverse-engineering
anything.**

Questions worth answering, in roughly this order. They are questions, not steps:

1. **Exactly which values land where?** Reconstruct the full PAR-tenor -> (expiry,
   tenor) correspondence across several dates. A stable mapping means one buggy
   iteration; an unstable one means something ordering-dependent (a dict, a set, a
   concurrent writer).
2. **Does the poisoned value for a given day come from that day's cube?** If yes the
   writer has the right date and the wrong tag. If no, both axes are wrong.
3. **Who writes?** Instrument `write()`/`merge()` to log a stack trace and the calling
   process, then reproduce. A live reproduction beats any amount of reading.
4. **Is a read a write?** Establish it one way or the other with a test, not by
   inspection.
5. **Is the tag family the only casualty?** 44 PAR tags are known. 14,535 parquets
   exist. Apply a value-plausibility check across the whole cache and find out what
   else is wrong — that number is currently unknown and it may be the real story.

---

## Traps this repo has already paid for

- **`conda run` rejects multiline `-c`** and **two concurrent `conda run` invocations
  can produce EMPTY output with exit 0** — a fake pass. Call
  `C:/Users/chris/anaconda3/envs/stir/python.exe` directly. Always set
  `ARBS_SUPABASE_ENABLED=0`.
- **Heredocs collapse backslashes.** Anything containing `\` or backticks goes in a
  file written with the Write tool, not a heredoc. This cost me four attempts in one
  session.
- **Start in a NEW git worktree**, short sibling path:
  `git -C C:/Users/chris/clee/ARBS worktree add ../ARBS-<short> -b <branch>`. The
  primary checkout has in-flight notebook work. **Every git command names its tree**
  (`git -C <path> ...`); a push succeeding is not evidence you were in the right one.
- **`git checkout -- MDP/FixedRateBonds/reference_data_cache` reverts SOURCE files**,
  not just the rotating parquet cache. Name the `ust_reference_data` subdirectory.
  Running any UST basket code deletes a tracked parquet, so the tree looks dirty after
  the test suite.
- **Driving Excel over COM is a measured hazard** — `reference_citivelo_addin_com_hazards`
  records two AccessViolation triggers that kill Excel, and
  `reference_excel_restart_signin_stalls` records that a restart cannot sign the add-in
  back in unattended (4/4 attempts). If your investigation needs a live read, budget
  for that and prefer `direct="live"` through `TimeseriesBuilder`, which reads through
  the poisoning correctly because it has no cache to be wrong.
- **Fast gate:** `conda run -n stir python -m pytest tests -m "not slow and not network
  and not db"` (~30 min). Deselect
  `tests/test_excel_supervisor.py::test_not_signed_in_means_keep_waiting`; it hangs.
  `tests/test_citivelo_read_path_perf.py::test_fixings_kwargs_resolve_once_per_wrapper`
  is a known flake that passes in isolation. **Grep the summary line for real counts —
  never trust the exit code.**

---

## What already exists, so you do not rebuild it

PR #497 (`feat/fed-detachment-rv`) added two things you can use immediately:

- **`notebooks/rv/fed_detachment_prices.curve_store_par_rate(tenor_years)`** — the
  clean 2y (or any tenor) par rate, built from the CurveStore's stored discount
  factors. 5,516 daily curves from 2005-01-03, no COM. Ties out to 4.02772 on
  2026-08-14 against a recorded 4.02995. **This is your ground truth for validating a
  repair**, and it is independent of whatever you find.
- **`fed_detachment_prices.gate_rate_sanity(series)`** — asserts every value lies in
  -1% to 15%. Blunt, and it is what would have caught this on day one.

`fed_detachment_prices.tag_cache_poison_report()` measures the current extent.

---

## The blast radius, which is the reason this matters

Two studies already merged to `main` read this tag with no sanity check and regress
forward changes in it against a Fed sentiment index to conclude the relationship "does
not reach the price":

- `notebooks/rv/fed_sentiment_lead.py:1075` (12 cells)
- `notebooks/rv/fedlock_sentiment_lead.py:724` (18 cells)

Measured: the forward change they actually regressed correlates **-0.06 to -0.08**
with the real forward change in the 2y rate, and carries roughly **84x** its
volatility (sd 1,887bp against 22.5bp at the 4-week horizon). Their conclusion
probably survives — spurious variance biases a regression toward zero, so "we found
nothing" is what you would get either way — but it survives by accident. **Re-running
those two sections on a clean series is in scope if you want it; say clearly whether
you did.**

---

## What "done" looks like

1. **The root cause, named and demonstrated.** Not "something cube-shaped" — the
   actual code path, shown to produce the defect on demand. If you cannot reproduce
   it, say so plainly and report what you ruled out; a well-evidenced "here are the
   four candidates and why three are eliminated" is a real deliverable.
2. **A fix that makes it impossible, not unlikely.** A guard at the write boundary
   beats a guard at every read site. Consider what a tag family even means: if a
   writer can address a tag it does not own, that is the defect, and a value check is
   only a symptom filter.
3. **A repair of the existing data**, validated against `curve_store_par_rate` — with
   the pre-repair state snapshotted first. Say how many rows moved and how you know
   the new ones are right. **The cache is shared and other work reads it: treat
   overwriting it as destructive, snapshot before, and verify after.**
4. **A regression test that fails without the fix.** Mutate the fix out and confirm
   the test goes red — a test that passes with the guard deleted is not a test.
5. **A sweep of the other 14,491 parquets** for the same class of defect, with the
   count reported. If it is zero, that is a finding. If it is not, that is a bigger
   one.
6. **The writeup**, including what you ruled out and what would change the answer.

Update `project_citivelo_tagcache_vol_poison` in memory when you are done — it
currently says "Not yet repaired" and records the 2026-08-21 event, my 2026-08-24
measurements, and the shipped-work blast radius.
