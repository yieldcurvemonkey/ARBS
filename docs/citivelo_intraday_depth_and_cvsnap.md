# How deep is Citi's intraday history, and can `CVSNAP` reach past it?

Measured live against the signed-in add-in on **2026-08-09**, in about 380 `CV*`
calls. Raw results in `analysis_outputs/snap_probe_*.json`; the tool is
`scripts/citivelo_snap_depth_probe.py` and it re-runs.

## The short answer

| question | answer |
|---|---|
| Is `CVTSHIST` capped at two years of minute data? | **No.** It reaches **4.9 to 10.1 years** depending on the curve. The "two years" was the *span* cliff, not retention. |
| Can `CVSNAP` reach history `CVTSHIST` cannot? | **No.** Same store, same floor, tested on seven curves at three depths each. |
| Is `CVSNAP` worth building an acquisition path on? | **No** — and the measurements below are the reason, not an opinion. |
| So how do we get ten years of minute curves? | `CVTSHIST` at `MI01`, chunked under the span cliff, run to each curve's measured floor. That is `scripts/citivelo_deep_intraday_warm.py`. |

## What each curve can actually give

Floors bisected to ±21 days on `RATES.*.PAR.10Y`, holding the request span at
4 days so a coarse answer means retention rather than the span rule.

| curve | 1-minute from | years | any intraday from | years | notes |
|---|---|---|---|---|---|
| `EUR_EURIBOR` (`RATES.SWAP_LIBOR.EUR`) | **2016-07-06** | 10.1 | 2016-07-06 | 10.1 | the deepest series Citi serves |
| `JPY_TONAR` | **2017-12-06** | 8.7 | 2017-12-06 | 8.7 | |
| `EUR_EONIA` | **2017-12-06** | 8.7 | 2017-12-06 | 8.7 | retired 2025-08-15 |
| `USD_FEDFUND` | **2018-09-05** | 7.9 | **2017-12-06** | 8.7 | sparse era below 2018-09 |
| `USD_SOFR` | **2021-09-15** | 4.9 | 2021-09-15 | 4.9 | |
| `EUR_EUROSTR` | **2021-09-15** | 4.9 | 2021-09-15 | 4.9 | |
| `JPY_TONAR_LCH` | **2024-01-17** | 2.6 | 2024-01-17 | 2.6 | the CCP-split twin, six years shallower |

Three things in that table are worth stating out loud.

**`2017-12-06` is an archive epoch, not a coincidence.** `USD_FEDFUND`,
`JPY_TONAR` and `EUR_EONIA` all floor within one bisection step of it. Whatever
Citi did to its intraday store in late 2017, it applies across indices.

**`EUR_EURIBOR` predates that epoch by 17 months.** It is on a different store,
and it is the only one of the requested curves that can honour a literal
ten-year request.

**`JPY_TONAR` is the JPY curve to warm, not `JPY_TONAR_LCH`.** The existing
minute warm holds `JPY-TONAR-1D-LCH`, which floors at 2024-01-17. The uncleared
index reaches 2017-12-06. They are genuinely different curves — the JSCC/LCH
basis is real — but for a long intraday history there is only one candidate.

**SOFR's daily history claims to start in 1990.** `CVTSHIST DAILY period="MAX"`
returns 9,262 rows for `RATES.OIS.USD_SOFR.PAR.10Y` beginning 1990-01-01, which
is 28 years before the index existed. Citi is back-casting. The intraday store
does not do this — it starts 2021-09-15 — so nothing in this warm is affected,
but do not read that daily series as SOFR before 2018.

## `CVSNAP` reads the same store as `CVTSHIST`

Four independent measurements, all pointing the same way.

**1. Where both serve, they agree to the digit.** `CVSNAP` at a minute stamp
against the `MI01` row at that same minute, 2026-05-06, six curves:

```
USD_SOFR       snap=3.95079  mi01=3.95079  diff=0.0 bp
USD_FEDFUND    snap=3.902    mi01=3.902    diff=0.0 bp
EUR_EUROSTR    snap=2.83161  mi01=2.83161  diff=0.0 bp
EUR_EURIBOR    snap=3.0532   mi01=3.0532   diff=0.0 bp
JPY_TONAR      snap=2.28875  mi01=2.28875  diff=0.0 bp
JPY_TONAR_LCH  snap=2.29     mi01=2.29     diff=0.0 bp
```

**2. Below the floor, `CVSNAP` returns nothing.** Three stamps (09:30, 12:00,
15:00 local) at 30, 120 and 365 days under each curve's measured intraday floor
— **0 of 3 served, on every curve, at every depth.**

**3. The one apparent exception was our own measurement's fault.** `USD_FEDFUND`
answered with three distinct values 168 days below what the first pass called
its floor. It turned out the floor test asked *"is the median spacing one
minute?"*, and below its dense era that curve still serves real intraday data at
~8-minute spacing:

```
date          rows   median spacing   first .. last
2018-08-15     289          10.5min   2018-08-12 18:58 .. 2018-08-15 19:46
2018-08-08     274           9.0min   2018-08-05 18:31 .. 2018-08-08 19:53
2018-03-14     333           8.0min   2018-03-11 18:32 .. 2018-03-14 19:56
2017-08-23       0                -
2016-08-03       0                -
```

`CVTSHIST` serves 2018-03-14. So did `CVSNAP`. Neither serves 2017-08-23. The
probe now bisects **two** floors — dense-minute and any-intraday — precisely so
that a density boundary cannot be mistaken for a retention one again.

**4. There is nothing left for a snap grid to fix.** The remaining argument for
`CVSNAP` was that a sparse-era `MI01` cross-section might be *ragged* — 44 tenors
printing at 44 different minutes, so no single stamp carries a whole curve.
Measured on 2018-03-14:

| | stamps × tenors | tenors per stamp | stamps with ≥4 tenors |
|---|---|---|---|
| `USD_FEDFUND` sparse | 224 × 15 | median 15, min 15, max 15 | 224/224 (100%) |
| `USD_FEDFUND` dense (2024-03-13) | 2,641 × 44 | median 44, min 44, max 44 | 2,641/2,641 (100%) |
| `JPY_TONAR` sparse | 1,659 × 15 | median 15, min 15, max 15 | 1,659/1,659 (100%) |

Every published stamp carries every tenor that exists at that date. The sparse
era is **synchronous, just less frequent**, and the ordinary signature-grouping
build solves it unchanged.

### `CVTICK` is not a history function either

The one entitled `CV*` function that had never been called. Four argument
shapes; it answers:

```
Error: Parameter 'Refresh Seconds' must be an integer.
```

It is an RTD/streaming primitive in the `CVSTREAM` family. With date bounds it
returns the pending sentinel and no block. There is no third store.

## What `CVSNAP` is still good for

Not acquisition — but it is the only primitive that reads **one instant without
fetching a window**, at ~0.5 s for one tag and ~1.0 s for a 44-tenor grid. That
makes it the right tool for:

- **tie-out**: confirming a stored curve's inputs against Citi at one minute,
  for the cost of a single call rather than a 5,800-row window;
- **spot checks inside a long build**, where pulling a window would cost Excel
  memory the run cannot spare.

It is the wrong tool for anything that needs many instants: a 1-minute grid over
ten years is ~1.8M calls, which at the measured 0.52 s each is **11 days of
continuous Excel driving** — for data `CVTSHIST` hands over in ~3,100 windowed
calls.

## Cost of the thing that does work

Measured on the live run, `MI01`, 44 tags, 5-day windows:

| | |
|---|---|
| wall time | ~3.6 s per window, ~52 business days per 60-day chunk |
| Excel memory | **~35–46 MB per window**, and it only ever grows |
| implication | ~60–100 windows per Excel session before the ceiling |

Excel memory, not time, is the binding constraint — which is why
`citivelo_deep_intraday_warm.py fetch --auto-restart` exists: it rescues unsaved
workbooks, restarts Excel, waits out the ~13–25 minute silent re-authentication,
and resumes on the **same chunk**. Work is banked per day file, so a failed
restart costs time and never data.

## What to run, in order

```bash
# 1. what is left, and how much is already done
conda run -n stir python scripts/citivelo_deep_intraday_warm.py plan

# 2. the Excel-bound half. Unattended, resumable, newest-first.
conda run -n stir python scripts/citivelo_deep_intraday_warm.py fetch --auto-restart

# 3. the CPU half. OIS curves take the existing builder, EURIBOR the dual-curve one.
conda run -n stir python scripts/citivelo_deep_intraday_warm.py build --workers 8

# 4. the check that can fail: CVSNAP against the stored curve's own par rate,
#    sampled per era so the sparse and self-discounted eras are actually covered
conda run -n stir python scripts/citivelo_deep_intraday_warm.py verify --per-era 5

# 5. the SWAP TIMESERIES cache, which reads the curves step 3 wrote
conda run -n stir python scripts/citivelo_intraday_ts_warm.py warm --workers 10
```

Step 5 needs no changes to benefit. `citivelo_intraday_ts_warm.py` prices its
structure universe off `USD-SOFR-1D-CITIVELOEXCELMIN`, and this warm both extends
that asset (2022-08 → **2021-09**) and **upgrades 2022-08 → 2023-12 from
ten-minute to true one-minute** — the stretch its own documentation calls out as
"ten-minute data wearing a one-minute index, which is worse than useless in a
mean-reversion study". Re-run it over that range once the build lands.

The other four curves are **not** in that script's universe: it is written around
one curve (`CURVE = "USD-SOFR-1D"`). Extending it is a separate piece of work and
deliberately not bundled here — it is a proven pipeline holding 231M rows, and
the curve cache has to exist before there is anything to price off.

## Reproducing any of this

```bash
# the whole battery, ~380 CV* calls
conda run -n stir python scripts/citivelo_snap_depth_probe.py --stage all --out probe.json

# just the claim you doubt
conda run -n stir python scripts/citivelo_snap_depth_probe.py --stage selfcheck
conda run -n stir python scripts/citivelo_snap_depth_probe.py --stage floor --curves USD_SOFR
conda run -n stir python scripts/citivelo_snap_depth_probe.py --stage snapwalk \
    --floors-json analysis_outputs/snap_probe_floor2.json
conda run -n stir python scripts/citivelo_snap_depth_probe.py --stage cvtick
```

`--stage selfcheck` runs first in the full battery and **stops the run if it
fails**. It asks for two windows whose answers are already known from
`MDP/CitiVelocityExcel/windowed.py`'s measured ladder — 4 days of `MI01` must
come back at 1-minute spacing, 30 days at 10-minute — because a spacing
measurement that is itself broken would report retention limits that are not
there, which is exactly the class of error this whole exercise exists to catch.

**A retired curve needs `--anchor`.** The bisection starts from a date it
believes serves, defaulting to three months ago. `EUR_EONIA` stopped publishing
on 2025-08-15, so that anchor finds nothing and the bisection concludes the curve
has no intraday history at all rather than eight and a half years of it. Use
`--anchor 2025-06-11`.
