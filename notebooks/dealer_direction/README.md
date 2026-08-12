# `notebooks/dealer_direction/`

Dealer-direction inference on the CFTC Part 43 USD swap tape: per-trade direction
with a calibrated probability, a signed key-rate DV01 profile, and a daily
street-positioning indicator.

| file | what it is |
|---|---|
| `dealer_direction_showcase.ipynb` | **the deliverable.** Executed end to end, all outputs stored |
| `dd_nb.py` | the notebook's helper module: every API mismatch, convention trap and cache decision, behind functions that return data and print nothing |
| `data/` | precomputed artefacts the notebook **loads**; see `data/PROVENANCE.md` |
| `_out/` | what the notebook **writes**: 12 summary CSVs + 14 figures |

---

## Run it

```bash
ARBS_SUPABASE_ENABLED=0 C:/Users/chris/anaconda3/envs/stir/python.exe -m nbconvert \
    --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 \
    notebooks/dealer_direction/dealer_direction_showcase.ipynb
```

Invoke the interpreter **directly**. Never `conda run` — parallel invocations
collide on a temp file and return empty output with exit code 0, a fake pass.

`dd_nb.py`'s self-test is a separate entry point and asserts the same shapes:

```bash
C:/Users/chris/anaconda3/envs/stir/python.exe -W ignore notebooks/dealer_direction/dd_nb.py
```

### Cost

| | wall clock |
|---|---|
| notebook, warm stage cache | **~25 s** |
| pipeline stages alone, warm | ~8 s |
| pipeline stages alone, **cold** | ~180 s (60 s per tape day; pricing is 70–80 % of it) |

Stage caches live in `D:\ddnb_cache` — **nothing large lands on `C:`**, which has
run to zero twice. The whole three-day cache is under 10 MB.

The cache key is a digest of every `SDRUtils/dealer_direction/*.py` **plus
`dd_nb.py`'s entire text, comments included**. Editing a docstring in `dd_nb.py`
invalidates it and costs a ~3-minute rebuild. That is the deliberate side of the
trade: hashing only the imported modules would let an edit to `dd_nb`'s own
`_rate_deviation` serve stale marks, and a wrong mark is silent while a rebuild
is merely slow.

---

## The window

Configured in **one place**, at the top of the notebook:

```python
WINDOW_START = "2025-06-16"
WINDOW_END   = "2025-06-18"
```

It is also the only path-like thing configured by hand. `NB_DIR` is *derived*
from the kernel's working directory (`DD_NB_DIR` overrides it) and raises rather
than guessing: `dd_nb.py` sets `REPO` from its own location, so a wrong `NB_DIR`
would silently run one checkout's pipeline against another's caches. `CACHE_DIR`
is pinned to `D:\ddnb_cache` deliberately.

Monday to Wednesday of the June 2025 FOMC, chosen by measurement: post-2024-07 so
terminations exist; inside s2's design sample so the hold-out stays shut and the
calibration is genuinely trailing; 13 recovered `PKG-N` against 159
`PKG_SIGNS_AMBIGUOUS`; both venue classes plus the `VENUE_UNKNOWN` residual every
day; one clean day (06-16, 100 % priced) and one holed day (06-17, 94.46 %).

Widening it re-runs the pipeline cold and re-reads the tape for the missing days.
`config(indices=("SOFR", "FED_FUNDS"))` widens the pricing population — a
one-word change, supported by construction and **not exercised by any test**.

---

## The rule the notebook is built around

> **A number the notebook prints is either recomputed in front of you, or it was
> loaded from a file listed in `data/PROVENANCE.md` — and where a cell computes
> *on* an input it did not produce, the banner names that input. There is no
> fourth case.**

Every cell carries a `COMPUTED` or `LOADED` banner. Every `LOADED` banner names
the file and cites a `data/PROVENANCE.md` section. A cell that computes on a
loaded input prints a `NOT COMPUTED HERE:` line naming it — because two inputs
make that third case real, and both are too large to live in `data/`:

| § | input | what depends on it |
|---|---|---|
| `PROVENANCE.md` §7.1 | `D:\dd_signals_cache\s2_pos\calibrations.pkl` — s2's rolling fits, **unpickled, never fitted here** | `tau`, `b0`, the dead zone → `p` → `2p-1` → **every** `delta_dv01`; §5's 397 bucket fits, gate counts and pooling ladder |
| `PROVENANCE.md` §7.2 | `D:\ddnb_cache\stage\<digest>` — the stage cache | the `price_units` and `krd_frame` stages: the marks, the deviations, the 28-pillar KRD |

The stage cache is content-keyed on every `SDRUtils/dealer_direction/*.py` plus
`dd_nb.py`, so it **cannot be stale** — but that is not the same as having been
computed in front of you. §1 prints `pipe.timings.source` and
`dd_nb.cache_report()`, which say per stage which of the two it was, and §3
re-prices its demonstrated unit live against the cached mark
(`deviation_diff 0.0`).

`LOADED` cells never re-run a registered test: re-running a pre-registration on a
different window and reporting the new number is a second draw, not a robustness
check.

## The tape is read **read-only**

One `SELECT` (`universe.LEGS_SQL`). No `INSERT`, no `UPDATE`, no DDL, no temp
tables — the notebook asserts this on the query text itself. In practice the
three pilot days are served from `D:\ddnb_cache\legs` and the database is not
touched at all.

### If the caches are cold

| cold | what it needs |
|---|---|
| `D:\ddnb_cache\legs` | a production Postgres URL, from `resolve_pg_url`'s ladder: `DATABASE_URL`, else `PG_URL`, else the `SWAPPULSE_DB_*` defaults. Warm, none is read and the run is fully offline. |
| `D:\ddnb_cache\stage` | nothing external; ~180 s to rebuild three tape days |
| `D:\dd_signals_cache\s2_pos\calibrations.pkl` | `s2_positioning.py build` → `target` → `signal` (the pickle is written by **`signal`**, not `build`). `dd_nb.taus` raises `FileNotFoundError` naming the file and that chain rather than falling back to an in-window fit — the fallback is a different claim and would surface four cells later as a strictly-prior assertion, blaming window ordering for a missing file. |

## Retracted numbers are shown as corrections, never as current

| withdrawn | stands in its place |
|---|---|
| package recovery **79.12 %** (`RETRACTED`) | **57.89 %** — the recovery is +0.93 pp, not +22 pp |
| package recovery **71.92 %** (`SUPERSEDED`) | same; 64.22 % of `PKG-4+` DV01 is genuinely unidentifiable |
| S2's "powered null" (`WITHDRAWN`) | S2 is **UNINFORMATIVE**: β +0.024, t +0.04, edge −0.32 bp |
| R0's pre-print trough (`ARTIFACT`) | −0.1075 / t −5.90 becomes +0.0159 / t +1.955 when only the mid rule changes |
| S1's pre-registered sign | predicted sign is **β > 0**, not β < 0 (`S_DEVIATIONS.md` D1) |

---

## What the notebook contains

1. **Setup and provenance** — environment, tape generation, the read-only proof,
   the window, the pipeline timed stage by stage.
2. **The convention** — `conventions.dealer_received_signs` reproducing the
   frozen `stir_flow.ladder_conventions.dealer_leg_signs` on all 18 cases it
   supports. The first draft of that function inverted every leg of every
   structure at once and only this comparison caught it.
3. **One trade, end to end** — snap → curve → per-leg mid → deviation in bp → tau
   → p → `2p-1` → dealer side → per-leg received signs → 28-pillar KRD, with the
   mirror print on the other side of mid so the sign is visible.
4. **The universe** — the pilot window computed, the 610-day study loaded;
   exclusion tables with DV01 shares; package recovery and the identification
   gate.
5. **Direction at scale** — deviations, the fitted mixture, tau, the p
   distribution, the dead zone, and **the fit's own gate refusing buckets** — the
   gate that stopped a false positive in the signal work.
6. **The three rules** — rate, upfront, package price; Trap A (46 of 1,522
   point-call/`2p-1` disagreements) and Trap B (the S3 gap, illustrated not
   solved).
7. **Risk buckets** — the signed key-rate ladder, one trade and one day.
8. **Positioning** — daily levels, the guard refusing cross-bucket levels and
   cumulation, and the exact invariance of z to a constant retention factor.
9. **The regression studies** — a live estimator validation on synthetic data
   with a planted effect (computed), then R0 / R0b / S1 / S2 (loaded).
10. **What this cannot say** — eleven quantified limits.

---

## Two facts the notebook establishes that the docs do not

Both are recomputed in the notebook rather than asserted, and both go the safe
way:

- **`S_DEVIATIONS.md` D1's "convention-dependent for 11 of 35 cells" is 0 of
  35.** Re-running S1's own frozen verdict ladder over `s1_results.csv`
  reproduces the file exactly under the pre-registered sign and changes **no**
  verdict under the corrected one: `sign_ok` enters the ladder only through the
  `WRONG_SIGN` branch, which also requires a significant β, and nothing is
  significant. `sign_ok` itself flips on all 35 — a different quantity.
- **The two calibration gates leave nothing.** Of 397 bucket fits, 93 resolve `h`
  above `MIN_SEPARATION`, and **0** of those also reach `MIN_BUCKET_N`. Every
  bucket that resolves a spread is too small to be trusted with it; every bucket
  large enough is unseparated. The served tau is therefore always the wide,
  capped one — the model declining to claim a side it cannot see.

`S_DEVIATIONS.md`'s "all 14 swap-spread cost buckets, separation 0.025–0.050" is
also the `venue != ALL` subset of a 21-row table; the notebook reconciles the two
counts rather than picking one.
