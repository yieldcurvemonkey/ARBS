# Refactor: reprice the USD swap SDR tape off Citi Velocity curves and infer dealer direction across the whole curve

## How to work on this

**This is a long-running task. Expect many hours, possibly days of wall clock.** Plan for
resumability from the start: keep a ledger, commit often, and assume your session may be
compacted or interrupted.

**You have full authority. Work autonomously.** I am away from the computer and will not be
able to answer questions or approve anything. Make every design and implementation decision
yourself. Where you would normally stop and ask, instead: pick the option you can best defend,
**write down what you chose and why**, and continue. If you hit something genuinely ambiguous,
implement the interpretation that is easiest to reverse and say so in your notes.

Do not stop to check in. Do not ask which approach I prefer. Do not wait for approval before
starting the expensive parts. The only thing I want protected is that you **never merge to
`main`** — open a PR and leave it for me.

Anything you consider risky or surprising, put in the PR body and in your notes rather than
holding the work.

---

## What this is about

The USD swap SDR trade tape records printed OTC swaps with an execution timestamp, a traded
fixed rate, notionals, tenors, and — for off-market trades — an `other_payment_amount`. It does
**not** record which side the dealer took. That has to be inferred by repricing the trade against
the market as it stood at the moment of execution and seeing which side of mid the print landed.

That inference already exists, but only for a narrow slice: the short end and FOMC-dated swaps,
priced off Barchart STIR futures and ERIS curves. **This task generalises it to the entire curve
and moves it onto Citi Velocity Excel add-in curves.**

Concretely, the target is dealer-direction inference for:

- **USD SOFR** OIS across all tenors, not just sub-3y
- **USD Fed Funds** OIS across all tenors
- **SOFR / Fed Funds basis** swaps

…and to retire the Barchart STIRF and ERIS curve dependencies from this path.

---

## The direction logic

The rule itself is simple. Two cases:

**On-market trades** (no `other_payment_amount` reported): reprice the swap on the curve to get
the model's fair fixed rate. If the model rate is **higher** than the reported traded rate, the
customer **received** fixed and the dealer **paid** fixed. And vice versa.

**PV / off-market trades** (an `other_payment_amount` is reported): compute the swap's PV on the
curve. If the PV is **lower** than the reported other payment amount, the dealer **paid** fixed
and the customer **received** fixed. And vice versa.

**Reprice against the curve timestamped one minute before the reported execution timestamp**, and
compute risk (DV01) from that same curve snapshot. Using the trade's own execution-minute curve
would contaminate the comparison with the trade you are trying to classify.

**Do not take my phrasing of these rules as authoritative over the existing implementation.**
`SDRUtils/stir_flow/classifier.py::classify_unit` already implements both branches with a
specific sign convention (`s2m`, `npv_pay`, `dealer_bought`, `itm_side`). A previous
investigation concluded that classifier is **correct** — an apparent "wrong directions" bug
turned out to be a charting artefact (SOFR trades plotted against the Fed Funds line), not a
classifier error. So: read that code, understand its sign conventions, and **tie your
generalised implementation out against it on the trades it already covers**. If your version
disagrees with it on a short-end SOFR trade, your version is probably wrong. That tie-out is the
single best regression test available to you, and I would build it early.

---

## Where things are

### The existing direction machinery

```
SDRUtils/stir_flow/
  classifier.py        <- the direction rules (classify_unit); read this first
  pricing.py           <- CurvePricer, snap_timestamp (the t-1min logic already exists)
  config.py            <- CURVE_SOURCE, CURVE_FOR, DV01 buckets, exclusions, SUB3Y_HORIZON_DAYS
  confidence.py        <- confidence scoring / flip probability
  trade_selection.py   <- which trades enter the signed universe; venue whitelisting
  ladder.py, book.py, unwinds.py, vintage.py, curve_warm.py, tick_size.py
SDRUtils/_swappulse_scripts/backfill_stir_direction.py
SDRUtils/_swappulse_scripts/backfill_stir_direction_range.py
SDRUtils/_swappulse_scripts/_stir_direction_golden.py   <- golden-file regression fixtures
BT/dealer_ladder/                                        <- the research/backtest layer on top
```

Two things there are already correct and worth keeping:

- `pricing.py::snap_timestamp` does the t-1min snap — converts to New York, truncates to the
  minute, subtracts one minute, falling back from `original_execution_timestamp` to
  `execution_timestamp`. **One caveat, measured:** for a print in the 00:01 ET minute it
  produces exactly midnight ET, which `resolve_request` reads as *end-of-day* — resolving to
  that day's close, ~16 h after the trade. See the curve-state section below; do not treat
  this function as unconditionally safe.
- `config.py::CURVE_SOURCE = "BARCHART_STIRF-RL"` with
  `CURVE_FOR = {"SOFR": "USD-SOFR-1D-Q12xM12STIRT", "FED_FUNDS": "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"}`
  is the seam you are replacing. Note the Fed Funds curve today is a *blend* (SERFF/MIX23), not a
  clean Citi curve.

`config.py::SUB3Y_HORIZON_DAYS = 1105` (~3y) is the current maturity cutoff. Removing that
restriction is a substantial part of "across the entire curve" — but understand *why* it was set
before you delete it. The short end was chosen partly because STIR futures give a clean, liquid,
tick-quantised reference there. The long end will not behave the same way, and your confidence
model probably needs to change with it.

### The curve source you are moving to

`IRSwapsMDP(source="citivelo_excel_rl")` — see `MDP/IRSwaps/IRSwapsMDP.py`. Accepted source
tokens are `CITIVELO_EXCEL`, `CITIVELO-EXCEL`, `CITIVELO_EXCEL-RL`, `CITIVELO_EXCEL_RL` (RL =
rateslib backend) and `CITIVELO_EXCEL-QL` / `CITIVELO_EXCEL_QL` (QuantLib). These are **distinct
from** the older workbook-based `CITIVELO` source — do not confuse them.

Supporting machinery lives under `MDP/CitiVelocityExcel/`:

```
tags.py          <- the tag grammar. RATES.SWAP_LIBOR, RATES.BASIS_SWAPS, RATES.FRA, ...
catalog.py       <- Citi's field/instrument dictionary (~20k UI selections)
curves/
  conventions.py <- per-index conventions; there IS a FedFunds entry
  rl_builder.py  <- rateslib curve construction
  ql_builder.py  <- QuantLib curve construction
  par_grid.py, ibor_builder.py
pricer.py        <- has branches for SWAP_LIBOR and BASIS_SWAPS families
```

### The tape itself

**PR #413 is merged — the tape is on `arbs_usd_swap_tape_*_v3`.** `arbs_usd_swap_tape_*_v2` is
owned by a *different writer* — a cron job on another host that serves a different front end —
and its rows carry **none** of the enrichment (0% `ptp_group_id`, 0% `event_timestamp`,
0% `special_tenor_type`) since 2026-07-23.

**Read v3, not v2.** Table names come from `SDRUtils/_swappulse_scripts/_tape_tables.py`
(`LEGS_TABLE`, `PACKAGES_TABLE`, …) — import them, never hardcode a suffix. There is a writer
guard (`assert_writable_generation`) that refuses to write v2; do not defeat it.

Note that `SDRUtils/stir_flow/trade_selection.py` and `unwinds.py` were repointed at v3 during
that migration.

---

## The state of the Citi curves — as of 2026-08-10

**Read this whole section before designing anything.** A dedicated prep task (PR #426, branch
`feat/minute-curve-fidelity`, **not yet merged**) measured the minute curves and built the
infrastructure this refactor needs. It resolved two gaps an earlier draft of this prompt listed as
blockers, and found one trap that would otherwise have silently corrupted your results.

### Both USD curves now cover the whole tape

| asset | days | span | priced |
|---|---|---|---|
| `USD-SOFR-1D-CITIVELOEXCELMIN` | 1,286 | 2022-06-30 → 2026-08-07 | 97.58% |
| `USD-FEDFUNDS-1D-CITIVELOEXCELMIN` | 926 | 2023-08-24 → 2026-08-07 | 97.19% |

Fed Funds went 155 → 926 days with zero uncovered quarters. **Both predate the tape start
(2024-03-01), so the SOFR/Fed-Funds asymmetry that earlier drafts treated as the main planning
constraint no longer exists.** Fed Funds is fit across the whole tape on the same terms as SOFR.

**Read the local `CurveStore.default()`, not Supabase** — the Supabase L2 lags badly and will make
Fed Funds look absent. `available_dates(name)`; `read_raw_nodes(name, start=..., end=...)` is
keyword-only after the first argument.

### The Citi USD session — measured, not assumed

`MDP/IRSwaps/CITIVELO_EXCEL/citi_session.py` codifies this. Established over 815 SOFR and 794 FF
days, split by DST regime so each boundary's anchoring was established rather than assumed:

| boundary | EDT | EST | anchored in |
|---|---|---|---|
| first / last row, Mon–Thu | 01:00 / 22:59 ET | 01:00 / 22:59 ET | **New York** |
| Friday close | 17:59 ET | 16:59 ET | **UTC** (21:59) |
| Sunday open | 17:00 ET | 16:00 ET | **UTC** (21:00) |

The week runs on a UTC clock; the day runs on a New York one. Both DST transitions fall inside the
weekend. Use `citi_session.publishes(curve_name, instant)`, `expected_minutes(curve_name, day)`
and `is_truncated(...)` rather than re-deriving any of it.

**A stale comment not to trust:** `_already_dense` on branch `feat/citivelo-snap-history`
documents "Mon–Thu end 19:59". For USD the measured close is **22:59 ET**, and 19:59 is precisely
the *truncation* signature — a completeness gate built on that model marks all 302 damaged days
complete and skips exactly the ones needing repair. The Friday and Sunday halves of that comment
are right and non-obvious; only Mon–Thu is wrong.

### There is a permanent two-hour hole every night, and it is cheap

Citi publishes **no USD curve between 23:00 and 00:59 ET on any night**. Established five ways
(the fetch does request that window and gets nothing back; the same code returns clean sessions
for GBP; US holidays publish normally; interior gaps are 96% isolated single minutes). No fetch
change reaches it. **Every leg printed in the 00:xx ET hour is unclassifiable at minute
resolution, permanently.** It is 76.2% of all future-serving contamination.

The owner's decision is to accept it and serve the last preceding curve. That decision is sound
and it was priced — 22:59 ET against 01:00 ET the next morning, 30 clean weeknights:

| tenor | p50 | p90 | max |
|---|---|---|---|
| 2Y | 0.27 bp | 0.91 | 1.43 |
| 5Y | 0.24 bp | 0.87 | 1.18 |
| 10Y | 0.29 bp | 0.83 | 1.16 |
| 30Y | 0.28 bp | 0.71 | 1.34 |

Roughly **3× cheaper than an equivalent 120-minute stretch of the trading day** (5Y p90 2.63 bp) —
23:00–01:00 ET is the quiet middle of the Asian session. And a stale curve *predates* the print,
so unlike a future one it cannot be circular.

**The weekend is a non-issue**: 110 SOFR legs and 5 Fed Funds legs across the entire tape, max
backward lag 96 minutes.

### The one thing inside that hour you must NOT wave through

`snap_timestamp` produces **exactly midnight ET** for every print in the 00:01 ET minute, and
`resolve_request` reads exact midnight as *end-of-day*. Those prints therefore resolve to that
day's **close — roughly 16 hours after the trade**. Everything else in the hole is stale and
unbiased; this one is from the future, which is exactly the circularity the t−1min rule exists to
remove.

`SnapshotPolicy.strict()` already refuses it. **A policy relaxed to admit the overnight hole must
not relax this.** `snap_timestamp` lives in `SDRUtils/stir_flow/pricing.py` — the function this
refactor builds on — so it is directly in your path, not a distant edge case.

### Use SnapshotPolicy; do not hand-roll the lookup

`MDP/IRSwaps/CITIVELO_EXCEL/snapshot_policy.py` — a frozen dataclass with `method`, `max_lag`,
`allow_future`, `on_miss`, plus `SnapshotPolicy.strict(...)`, `.legacy()`, `.is_legacy()`,
`.fingerprint()`, `.describe()`, and a `SnapshotMiss` exception. Defaults reproduce the legacy
behaviour so existing valuation callers are unaffected; **strict is opt-in, and strict is what you
want.**

`SDRUtils/stir_flow/pricing.py::CurvePricer` now takes `curve_kwargs`, fixed per instance and
passed to `_get_curve`. That is deliberate: `_handles` is keyed on `(curve_name, ts)`, so a
per-call policy would let one caller's terms be silently reused for another caller's request for
the same minute. There is also a public `build()` so the warmer seeds the cache on identical terms
— previously a strict pricer got its cache seeded with legacy-selected curves and then served them.

**Do not admit the hole by globally setting `max_lag=2h`.** That also admits two-hour staleness at
10:00 on a Tuesday, worth 2.63 bp p90 instead of 0.87. Branch on whether Citi publishes:

```python
policy = (SnapshotPolicy.strict(minutes=1)
          if citi_session.publishes(curve, snap)
          else SnapshotPolicy(method="asof", max_lag=timedelta(hours=2),
                              allow_future=False, on_miss="raise"))
```

The 2 h bound on the second branch is not decoration — it is what still catches a truncated night.

### 302 truncated days — a real, partly recoverable defect

About 19% of Mon–Thu days stop at exactly **23:59 UTC** (27/144 EDT and 27/140 EST — the same
count on a UTC clock, which no market event produces). Cause: the warmer writes a day file once
and never rewrites it, so a chunk boundary inside a local day freezes it. On 190 dates one USD
curve stops early while the other, fetched separately, runs to 22:59.

**302 days / 63,866 minutes, one row per day with a cause, in
`docs/2026-08-10-citivelo-minute-repair-list.csv`.**

It matters more than the 12.6% headline suggests, because it inflates the nightly hole for a fifth
of the legs sitting in it:

| preceding session | legs | p50 lag | p90 | max |
|---|---|---|---|---|
| complete | 23,854 (79%) | 52 min | 106 | **120** |
| truncated | 6,224 (21%) | 244 min | 304 | **360** |

The clean-day max of exactly 120 minutes is the session model and the data agreeing to the minute.
The 360 is self-inflicted. **On SOFR 87.5% of contamination is irrecoverable, which makes the gate
more important, not less. On Fed Funds it reverses — 62% is recoverable, so repair it before
relying on Fed Funds.**

### Density is a gradient, and there is now an API for it

`MDP/IRSwaps/CITIVELO_EXCEL/density.py` — `day_density(...)`, `DayDensity.present()`,
`.is_dense(...)`, `.covers(instant, tolerance=...)`. Defaults `DEFAULT_MIN_SNAPSHOTS = 800` and
`DEFAULT_MAX_GAP = 5 minutes`. Use `covers()` to ask whether a *specific instant* is supported
rather than inferring it from a day-level count.

### SOFR/FF basis — the remaining genuine unknown

No basis curve exists in either store. `RATES.BASIS_SWAPS.SOFR_FEDFUND_BASIS.<ccy>.<tenor>` is a
documented tag family and `pricer.py` has a `BASIS_SWAPS` branch, but nothing is warmed.

With SOFR and Fed Funds now both deep and independently built, a basis swap may be priceable from
the two curves directly. Whether that is *correct* — whether the implied basis matches Citi's
quoted basis — is the open empirical question, and it is now cheap to test because both curves
cover the same span. Do that comparison early: it decides whether basis trades are in scope.

- https://rateslib.com/py/en/2.7.x/z_multicurveframework.html
- https://rateslib.com/py/en/2.7.x/z_multicsa.html

rateslib is **2.7.1**. The in-repo precedent for a genuine dual-curve build is the EURIBOR path,
which resolves an ESTR discount curve per day rather than self-discounting and reports its
discount source explicitly.

### Convention fidelity

Recently rebuilt curves report max reprice error **0.0023–0.0030 bp**. An older tie-out citing
1.6–6.1 bp on 4 of 17 curves predates that work and should not be quoted as current. One cause was
fixed in passing: stored EURIBOR curves were reconstructing on the **New York calendar** because
`RATESLIB_CURVE_DEFINITIONS` had no entry, so `reconstruct_curve` fell back to act360/nyc, warned
once, and carried on — 0.045 bp, silently. **If you add a curve, register its rateslib definition.**

Still measure the bias for the curves you actually rely on. Direction inference is far more
bias-sensitive than valuation: most prints land within a basis point or two of mid, so a
systematic bias inverts calls rather than merely degrading them.

### Sequencing

PR #426 is **not merged**. Decide early whether to build on that branch, wait for it, or rebase
onto it — but do not re-solve these problems, and do not build on the legacy
nearest-with-no-bound lookup. The full measurement report is
`docs/2026-08-09-citivelo-minute-curve-fidelity.md` on that branch (§20 covers the overnight-hole
decision), and `scripts/citivelo_minute_lag_audit.py` is there if you need to re-measure.

## Package trades — be very careful here

**This is where I expect the most damage if you are careless.** The tape is not a stream of
outright swaps. It carries packages: curves, flies, PKG-N with arbitrary leg counts, spreadovers,
matched-maturity, invoice swaps, MAC, compression lists, and PTP-grouped structures where a single
package transaction price covers many legs. The v3 backfill produced packages with **17 legs
across 13 distinct tenors**, and PTP grouping is present on ~54% of legs.

Things that will bite you:

- **A package has one price, not one price per leg.** For an on-market package the reported rate
  on an individual leg may be nowhere near that leg's own mid — the *package* is on-market, not
  the leg. Classifying leg-by-leg and voting will produce confident nonsense on curves and flies.
- **`other_payment_amount` / `package_transaction_price` attach at the package level** and can be
  notation-polluted. `config.py::PTP_USD_FLOOR = 500.0` exists precisely because sub-floor values
  are notation artefacts, not dollars. There is also `PTP_UFRO_DISAGREE_RATIO` for when the
  upfront and the PTP disagree by more than 2×.
- **Structure DV01 is not the sum of leg DV01s.** `classifier.py::structure_dv01` already handles
  this per structure kind; a fly's risk is not the sum of three absolute PV01s.
- **The current implementation excludes several package types outright**
  (`EXCLUDED_TRADE_TYPES` in `config.py`: MAC, SPREADOVER*, MATCHED_MATURITY*, INVOICE*). You are
  asked to **support all package types**, so those exclusions have to be revisited one by one —
  each was excluded for a reason, and some of those reasons (e.g. a spreadover's direction is
  about the *spread*, not the swap rate) mean the direction question itself is different, not
  merely harder.
- **Sign conventions on multi-leg structures.** "Dealer paid fixed" is unambiguous on an outright
  and needs a convention on a curve trade. Pick one, document it prominently, and make sure the
  research layer in `BT/dealer_ladder/` agrees with it.

Do not let package handling be an afterthought bolted on at the end. It is most of the difficulty.

---

## Environment and repo conventions

- **Python:** `C:\Users\chris\anaconda3\envs\stir\python.exe`, invoked **directly**. Do **not**
  use `conda run` — parallel invocations collide on a temp file and return empty output with exit
  code 0, which looks exactly like a passing test run.
- Set `ARBS_SUPABASE_ENABLED=0` before anything that imports `Caching`.
- **Work in a new git worktree**, short sibling path (e.g. `../ARBS-cdd`), never in the primary
  checkout — it usually has uncommitted work. Always `git -C <path> ...`; never rely on `cd`.
- Fast test gate: `python -m pytest tests -m "not slow and not network and not db"`. It takes
  ~30 minutes and ~5,400 tests. Three failures are pre-existing on `main` (two citivelo, one perf
  budget) — verify that claim against `main` yourself rather than assuming.
- Dashboard: `npm test` only, never `npx jest` (plain jest bypasses the ESM mocks).
- The tape database is **remote production Supabase**. Reads are cheap, writes are not. Anything
  that rewrites tape rows deletes and rewrites a whole `as_of` day.

### Citi Velocity add-in specifics

The add-in is driven by COM into a **logged-in Excel session** — that is the only working
transport. It is fragile in specific documented ways: there are two distinct AccessViolation crash
signatures that kill Excel, and the naive fix for one causes the other. A 528-window fetch once
wedged Excel at 5.25 GB. There is a `memory_guard.py` and a `supervisor.py` for a reason. Read
`MDP/CitiVelocityExcel/README.md` and the harvest tooling before doing any large pull, and prefer
the already-warmed curve store over live fetching wherever you can.

Citi's wire timestamps are **America/New_York**. Convert to curve-local *before* bucketing by day.

---

## Method — lessons from the session that preceded this one

These are not generic advice. Each one cost real time or real data in this repo recently.

**Verify your own checking tools against a known-good case.** I built a probe that called
production's own fetcher and concluded a day of data was unreachable. It was wrong: the probe
fetched only day D, while production fetches D **plus D+1 forward**. The data was there. Two
independent agents ran that same flawed probe and both confirmed the wrong answer — what caught it
was the production run disagreeing. Reusing production's functions is not enough; the call has to
reproduce production's *parameters and window*.

**Exit code 0 is not success.** `cmd | tail` then `$?` gives you `tail`'s status. That produced a
fake pass twice in one session, once for pytest (really exit 1) and once for an acceptance script.
Capture exit codes without a pipeline.

**A job that reports "done" is not evidence it did anything.** A backfill runner recorded days as
`ok` on exit code 0 when the upstream had silently returned an empty frame — destroying six days of
data before it was caught, unrecoverably, because the retry path only selected `failed`. If you
write anything long-running: a unit of work succeeded only if the *rows it was supposed to produce
actually exist*.

**Derive work lists from data, not from calendars.** A holiday-calendar day list silently skipped
two days that had real trades and included two that had none — and both lists happened to total the
same number, which is exactly why nobody noticed.

**`IF NOT EXISTS` turns a crash into a silent performance collapse.** Postgres index names are
schema-global. If you create any new tables, do not let a copied index name from another
generation silently skip creation.

**When you weaken a check, get it reviewed by something other than yourself.** Twice in the last
session I relaxed an acceptance criterion; both times an independent verification pass either
corrected my reasoning or disproved my evidence outright. Exemptions and thresholds are exactly
where motivated reasoning hides.

**Subagents that spawn background watchers and then wait on them will hang forever.** Three did.
Run commands in the foreground and read the output.

---

## What I would like at the end

- A branch and a **PR, not a merge**, with a body that explains the design you chose and *why*,
  including the options you rejected.
- **The data-gap assessment written down as a first-class deliverable** — ideally a short document
  in `docs/`. For SOFR, Fed Funds, and SOFR/FF basis separately: can we price it, at what
  granularity, over what date range, with what measured convention bias, and what is missing. An
  honest "we cannot do X and here is the evidence" is worth more to me than a working pipeline
  with an unexamined assumption underneath it.
- A tie-out against the existing short-end classifier, with the disagreements enumerated and
  explained.
- Whatever you could not finish, listed explicitly as such.

Take the time to do the gap assessment properly before building on top of it. If the answer turns
out to be that Citi cannot support part of this, that is a completely acceptable outcome — say so
clearly and early rather than making it appear to work.
