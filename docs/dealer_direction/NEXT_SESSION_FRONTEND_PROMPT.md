# Dealer direction and risk-bucket analytics in the USD swap tape front end

## How to work on this

**Long-running task — expect days, not hours.** Keep a ledger, commit often, assume
your context may be compacted.

**Work autonomously. You have full authority over every design and implementation
decision.** I am away from the computer and cannot answer questions or approve
anything. Where you would normally stop and ask: pick the option you can best
defend, write down why, and continue. When genuinely torn, prefer the
interpretation that is easiest to reverse.

Do not stop to check in. Do not wait for approval before the expensive parts.
**Never merge to `main`** — open a PR and leave it.

## First: make a worktree

```
git -C C:/Users/chris/clee/ARBS fetch origin
git -C C:/Users/chris/clee/ARBS worktree add C:/Users/chris/clee/ARBS-fe -b feat/tape-direction-frontend origin/main
```

Short sibling path, not a nested one — on Windows the path limit bites on
`node_modules` first. Always name the tree (`git -C C:/Users/chris/clee/ARBS-fe ...`);
never rely on `cd` having stuck.

**Read `docs/dealer_direction/` in PR #441 before you start.** Specifically
`WHAT_THE_LADDER_SUPPORTS.md` (the limits), `LEDGER.md` (the measurements) and
`INDICATOR.md`. That PR is the backend this work displays. It is not merged; you
will need to branch from it or cherry-pick, and deciding which is your call —
say which and why.

---

## Scope

**In scope:** getting an inferred dealer direction and a signed risk-bucket
ladder in front of a user of the USD swap tape, and the data seam that feeds it.

**Out of scope, but stated because it bounds the design:** improving the
direction inference itself, extending its coverage, the futures hedge-ratio
projection, and any trading signal. The inference is done and reviewed; your job
is to surface it honestly, not to re-open it.

---

## The one architectural fact that decides everything

**Direction cannot be computed at request time.** It needs `rateslib`, the local
Citi Velocity minute curve store, and roughly **60 seconds of CPU per tape day**
for pricing plus key-rate risk. A Next.js route handler cannot do that, and the
curve store is a local Parquet/DuckDB cache the web tier has no access to.

So the shape is forced: **a batch job materialises direction and risk into
Postgres, and the front end reads it.** Building that table is the first half of
this task and the more important half. A beautiful panel over a table that does
not exist is worth nothing.

Two tables, roughly — argue for a different split if you can defend it:

- **Per-unit direction.** `unit_key`, `as_of_date`, both timestamps plus the
  availability timestamp, `dealer_direction`, `p`, `signed_weight`, the rule that
  produced it, the exclusion reason where there is one, and the provenance
  (curve name, snapshot instant, realised lag, whether notional was imputed).
- **Aggregated ladder.** Per `(bucket, date, venue_class, series)`: the signed
  DV01, the gross, the unit count, and **the coverage fraction behind it**.

The per-unit key-rate vector is 28 pillars against ~2.3M units — about 65 million
rows if stored long. Decide deliberately how to store it (array column, wide
pivot, or only the aggregate) and **measure the read cost** before committing.
The consumer is a web page; a query that takes eight seconds is a design failure
even if it is correct.

**The join is natural and you should verify it early.** The display view
`arbs_usd_swap_tape_display_v3` is **package-grained** — its primary key is
`package_id`, with `legs_json` carrying the legs. The direction feature's unit is
the same object: `unit_key` is `package_id` for packages and `trade_id` for
singletons. One direction per row of the tape you already render. Confirm that
holds on real data before building on it.

---

## What must be on screen, and what must never be

This is the part that matters most, and it is the part a front end gets wrong by
default, because the wrong thing is the natural thing to draw.

### Never: a level comparison across buckets

DV01 retention runs **0.761 at 0–1Y down to 0.495 at 15–20Y** — a **1.54×
cross-bucket scaling distortion** — because the packages the classifier cannot
orient are not a random sample of the tape. So:

> **"The 5y bucket against its own history" is supportable.**
> **"Dealers are longer 5y than 10y" is not.**

A bar chart of signed DV01 across tenor buckets is exactly the forbidden view,
and it is the first chart anyone would draw. The Python side already refuses it
in the API rather than in a docstring — `indicator.cross_section()` raises, the
level column is bucket-suffixed so a naive concat gives a NaN block diagonal, and
there is no `to_frame` accessor. **Carry that refusal into the front end.** A
comment saying "don't do this" is not a control.

### Instead: `z` may cross buckets

`z` is **exactly invariant to a constant retention factor**. So a z-scored
cross-bucket view is legitimate and is the right way to say something
cross-sectional: *"5y is unusually one-sided for 5y, and more unusually so than
10y is for 10y."* Build that.

### Coverage is not a footnote

**Only 57.89% of DV01 is oriented.** A ladder that renders as though it were
complete is a lie, and the user cannot see the 42% that is missing. Put the
coverage fraction on screen next to every aggregate, and make the exclusion
breakdown reachable in one click, by DV01 share and by reason. The dominant
reason is `UNORIENTABLE_PKG` at 39.97% of DV01, and **64.2% of `PKG-4+` DV01 is
genuinely unidentifiable** — several mutually inconsistent sign vectors fit the
same package price. That is structural, not a backlog item.

### Abstentions are information, not blanks

A unit with no call must say *why* — dead zone, no curve, ambiguous package
signs, unsupported index. A blank cell reads as "no flow" when it means "we
declined". Every excluded unit carries exactly one reason code; use it.

### Three series, never merged

`D2C`, `D2D` and `VENUE_UNKNOWN` are separate. Dealers recycling risk among
themselves is informative — *"the street is distributing"* is its own signal —
but it is not customer flow loading dealer inventory. Never sum them into one
line.

### Flow, not inventory

Compression and allocation are **never publicly reported**, so a running sum
accumulates an unbounded, monotone error with no offsetting print. Do not offer a
naive cumulative chart. If you offer cumulation at all, it must be a decayed flow
with a stated half-life, labelled as a model.

### The availability clock

Every aggregation stamps on when the print became *public*, never on execution
time. Using execution time is lookahead. The row carries all three timestamps;
show the lag where it matters (blocks arrive delayed, and a block print and an
ASAP print of the same size are not the same event).

---

## Traps that are sitting in the data waiting for you

**`dealer_spread_est` and `opa_sign_confidence` are already in the display view
and they are NOT direction.** This is the trap most likely to cost you a day.
`opa_sign` is **direction-blind by symmetry** — the solver minimises
`min(|Σsᵢopaᵢ − PTP|, |Σsᵢopaᵢ + PTP|)`, so a sign vector and its global
complement score identically, and the orientation is settled by a tie-break, not
economics. `dealer_spread_est` is literally the dollar residual: always
non-negative, and its mean is flat across `sign(opa_signed_net)`. It carries
**zero** directional information despite the name. Do not surface it as though it
did.

**Do not sum `total_risk` or `gross_risk` from the view.** 55 legs carry
`notional = 1e20` — the spec's own "value not available" sentinel for field #31 —
and they dominate every aggregate. `SDRUtils/dealer_direction/sanity.py` has the
validated predicate. Check `package_adjusted_dv01` before trusting it too; it was
not audited by this work.

**Recovered `PKG-N` packages have a sign but no `p`.** They cannot be
probability-weighted into the ladder until a package `tau` is fitted. Either
exclude them from the weighted aggregate and say so, or show them as a separate
unweighted count — but do not silently treat a missing `p` as 0.5 or 1.0.

**A sign that renders inverted teaches the reader the wrong thing permanently.**
The pinned convention is:

```
customer pays fixed -> dealer RECEIVED fixed -> dealer long duration -> delta_dv01 > 0
p = p(customer paid fixed);  ladder weight = signed_weight(p) = 2p - 1
```

Two independent sign inversions were caught during the backend work, one in the
core convention module and one in a notebook that printed a raw decimal with a
`%` appended. Both produced completely plausible output. **Hand-trace one real
trade end to end with printed numbers before you build any chart on top of it**,
and put that trace in a test.

**Weight by `2p − 1`, not `p`.** At `p = 0.5` a `p`-weighted contribution is half
a long position, not a coin flip.

**The tape's `_v2` generation belongs to a different writer** on the host `sky`.
`src/lib/tape-tables.ts` pins `TAPE_GENERATION = 'v3'` and its comment explains
why that is a constant and not an env var. Any new table you add must follow the
same pattern.

---

## Where the code is

```
SDRUtils/dashboard/                                  Next.js 15.3, React 19, TS 5
  src/lib/tape-tables.ts                             TAPE_GENERATION = 'v3'; add yours here
  src/app/api/usd-swaps-tape-v2/                     the API routes (route.logic.ts + route.ts + __tests__)
  src/features/usd-swaps-tape-v2/components/
    UsdSwapsTradeTape.tsx                            the page
    TradeTapeTable/                                  the row grid -> the direction column goes here
    AnalyticsPanel/                                  ~20 cards -> the risk-bucket panel goes here
    TradeTapeCharts/ VolumeGrid/ OverridesPanel/
  __tests__/e2e/usd-swaps-v2.test.ts

SDRUtils/dealer_direction/                           the backend, PR #441
  conventions.py   the sign convention, pinned
  universe.py      units, exclusions, venue
  midprice.py      repricing against the Citi minute curve
  probability.py   the mixture fit, tau, p
  krd.py           the 28-pillar signed key-rate profile
  ladder.py indicator.py                             aggregation and the daily series
  provenance.py                                      the per-row audit trail

notebooks/dealer_direction/dealer_direction_showcase.ipynb
                                                     an executed end-to-end reference
notebooks/dealer_direction/dd_nb.py                  a tested pipeline: legs -> units -> price -> KRD -> ladder
BT/dd_signals/s2_positioning.py                      the same pipeline at 371-day scale
```

`dd_nb.py` and `s2_positioning.py` are the two working end-to-end drivers. **Read
one before writing a backfill** rather than re-deriving the call sequence.

Charting: `recharts`, `chart.js`, `d3` and `plotly` are all in `package.json`.
**Match whatever the neighbouring `AnalyticsPanel` cards use** rather than
introducing a fourth.

---

## Environment

- Python: `C:\Users\chris\anaconda3\envs\stir\python.exe`, invoked **directly**.
  Never `conda run` — parallel invocations collide on a temp file and return
  empty output with exit code 0, which looks exactly like a passing test run.
- `ARBS_SUPABASE_ENABLED=0` before anything that imports `Caching`.
- Dashboard: `npm install --legacy-peer-deps`. **`npm test` only** — a bare
  `npx jest` bypasses the ESM mocks and produces false Supabase failures. A
  `node_modules` junction breaks turbopack dev; install into the worktree.
- The dev server reads the **production** Supabase via `SWAPPULSE_DB_*` defaults.
  Reads are cheap. **A backfill deletes and rewrites a whole `as_of` day** — be
  certain which table you are writing.
- **Verify in Chrome MCP locally before committing any front-end change.** A
  screenshot of the panel is the minimum evidence that it renders.
- **Disk: `C:` on this box oscillates and has hit zero.** Put caches on `D:`.
  A `node_modules` plus a curve cache will not fit if you are careless.

---

## Method notes, all from real failures on the backend work

**Validate a measurement tool against a known-good case before trusting it.** A
probe once concluded a day of data was unreachable because it called production's
own fetcher with a narrower window than production uses. Two agents believed it.

**Exit code 0 is not success.** `cmd | tail` then `$?` is `tail`'s status.

**A job reporting "done" is not evidence it did anything.** A backfill recorded
days as `ok` on exit code 0 while the upstream returned an empty frame. A unit of
work succeeded only if the rows it was supposed to produce exist.

**Write the failing test first.** Then mutate your implementation and confirm the
test goes red. Nineteen of thirty-one mutants survived one module's test suite on
the backend, including one that let a published z-score be inverted while every
test passed — because every test was comparative and a global sign flip cancels
inside all of them.

**When you relax a threshold or add an exemption, get it checked by something
other than yourself.**

---

## What "done" looks like

- **A PR, not merged**, with the design and the options you rejected.
- **A materialised direction + ladder table**, with a runner, and a measured
  statement of how long a full backfill takes and what a single day costs.
- **The tape row grid showing an inferred side with its confidence**, and an
  abstention that says why rather than showing nothing.
- **A risk-bucket panel** that shows within-bucket levels over time and
  cross-bucket `z` — and that structurally cannot render a cross-bucket level
  comparison.
- **Coverage visible wherever an aggregate is**, with the exclusion breakdown one
  click away.
- **A hand-traced sign test** pinning one real trade from tape row to rendered
  direction.
- **Chrome MCP screenshots** of every new view.
- **A short note on what the panel can and cannot be used for**, written for
  someone who will read the chart and not the code.
- **Anything unfinished, stated plainly as unfinished.**
