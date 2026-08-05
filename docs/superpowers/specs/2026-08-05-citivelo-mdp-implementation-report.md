# Citi Velocity MDP — implementation report

**Date:** 2026-08-05
**Branch:** `feat/citivelo-excel-timeseries` (worktree `../ARBS-cve`)
**Status:** implemented; hermetic suite green; core facts verified against the live add-in
**Implements:** `2026-08-05-citivelo-mdp-implementation-prompt.md`, on the design in
`2026-08-04-citivelo-excel-timeseries-design.md`

---

## What exists now

At the start of this session there was a catalog, a set of probe scripts, and a
`Prober.probe_tshist()` that returned a validity verdict and a single cell. There
was no fetcher, no cache, no MDP source, no Query, no TB integration and no curve
construction.

There now is. Roughly 12,000 lines across:

```
MDP/CitiVelocityExcel/
  errors.py excel_constants.py block_parser.py frequencies.py     transport + parsing
  com_client.py testing.py                                        the COM bridge and its fake
  catalog.py tags.py                                              grammar + typed builders
  cache.py quotes.py source.py mdp.py pricer.py                    cache + the MDP surface
  curves/   conventions.py rl_builder.py ql_builder.py par_grid.py
  vol/      cube_data.py ql_cube.py rl_cube.py
  bonds/    universe.py conventions.py rl_bonds.py ql_bonds.py
  inflation/ indices.py rl_inflation.py ql_inflation.py
  xccy/     basis_data.py rl_xccy.py ql_xccy.py
  options/  spread_options.py midcurves.py
  harvest/verify_live.py                                          the bounded live probe
  README.md
Query/CitiVelocity/    _CitiVeloLeg.py CitiVeloStructure.py CitiVeloValue.py
                       CitiVeloQuery.py adapter.py               product "CITIVELO"
TB/CitiVelocityTB.py                                             fast path + equivalence proof
tests/test_citivelo_*.py  (10 modules)
notebooks/timeseries/citivelo_excel.ipynb
```

**Tests:** 317 hermetic tests pass; 9 integration tests self-skip without a
signed-in Excel. No test needs network, a database or Excel.

---

## Verified against the live add-in, 2026-08-05

`MDP/CitiVelocityExcel/harvest/verify_live.py`, 6 `CV*` calls, Excel unharmed.
This exists because the hermetic suite is structurally circular on these points -
it proves the client agrees with a fake built from the same understanding.

| Question | Answer | Was |
|---|---|---|
| Unit of `ATM_RFR.NORMAL` on the wire | **basis points** — `USD 1Y10Y` = `80.9518` | declared, not measured |
| 44-tenor par grid in one call | **yes** — 1 `CVTSHIST`, 23×44, zero failures | proven only for the add-in's own export |
| Explicit `start=`/`end=` bounds | **honoured** — `yyyyMMdd` gave exactly the 11 days asked for | format inferred |
| `RATES.SWAP_LIBOR` serves | **yes, per currency** — EUR/AUD/INR valid; GBP/JPY empty | shape never confirmed |
| `SWAP_SPREAD` vs `CVMETADATA` | **11/11 tenors serve** via `CVTSHIST` | asserted from the design notes |
| Curve from real quotes | rateslib reprices its 44 inputs to **1.4e-03 bp** | never done on real data |
| rateslib vs QuantLib, real curve | 10Y×10Y forward gap **1.7e-04 bp** | synthetic only |
| Fast path vs repricing, real data | 10y quote `4.210550`, repriced `4.210550` — **0.0000 bp** | synthetic only |

Reference quotes 2026-08-05: 2Y 4.04128, 5Y 4.04945, 10Y 4.21055, 30Y 4.42447
(design spec had 2026-08-04: 2Y 4.05114, 10Y 4.22537 — consistent).

GBP and JPY returning *empty* rather than *bad tag* is the expected shape of an
IBOR family after those currencies migrated to RFR. The grammar is right; the
coverage is per currency.

---

## The two hard requirements, and how they were met

### The timeseries fast path

`BaseTimeseriesTB` prices every query at every timestep through `MDP.get_pricer`.
For Velocity that is pathological: most queries **are already a tag**, so repricing
them means stripping a curve — a solver run — at every timestep to recover a number
the add-in already published.

`TB/CitiVelocityTB.py` routes:

- **fast** — every leg resolves to a tag and every value is the published quote.
  All tags across all such queries go out in ONE `CVTSHIST` sweep of the window;
  each timestep is then an `asof` slice and a weighted sum.
- **reprice** — anything `RL_*`/`QL_*`, or a leg with no direct tag. Per-timestep
  `get_pricer`, with the whole par grid pre-warmed so the slow path is also one
  sweep rather than 44 tags per step.

`plan().summary()` shows which route each query took and why. Measured: 3 queries ×
12 timesteps = **1** `CVTSHIST` call on the fast path.

### The equivalence proof

`assert_fast_path_matches()` runs the same structures both ways. It is meaningful
rather than circular because the curve is calibrated to the very quotes the fast
path reads: a 10y par rate repriced off a grid containing that 10y quote must
reproduce it to solver tolerance.

| Backend | max abs difference |
|---|---|
| rateslib (`func_tol=1e-9`) | **7.1e-06** |
| QuantLib | **3.4e-09** |
| rateslib, live data | **0.0000 bp** |

`test_equivalence_helper_catches_a_real_divergence` biases the repricing path by
1 bp and asserts the helper raises — so the agreement is a measurement, not a
tautology. `test_equivalence_helper_refuses_an_empty_comparison` makes sure an
empty comparison can never read as a pass.

---

## Bugs found and fixed during integration

- **`pricer.py` called `rl_settlement_date(reference=...)`** where the bonds API
  takes `as_of=`. `TypeError` on every bond metric. Caught by exercising the path
  end to end rather than by reading it.
- **The cache changed the index dtype on a round trip** (`datetime64[ns]` in,
  `datetime64[us]` out) because it wrote `pa.timestamp("us")`. Caught by a test.
- **`pricer.py` imported the private `rl_builder._make_irs`.** The repo has a
  recorded bug of exactly this shape (`citivelo_curve_service.py` imports two
  private names from a sibling builder and breaks on a rename with no test
  catching it). Promoted to `make_rl_irs`.
- Two analytics bugs found by the inflation agent sweeping all 17 indices:
  `_zcis_kwargs` collided on `leg2_index_method`/`leg2_index_lag` for the 14
  non-spec indices (every non-USD/EUR/GBP index was dead), and `RLIndexCurve`'s
  lag/method were re-derived properties so an overridden curve handed its swaps
  the table's lag. Both fixed.

---

## What is NOT verified, stated plainly

**Nothing outside the table above has been checked against a Citi quote.** Every
other number is internal consistency between two independent implementations on
synthetic inputs. Self-consistency does not prove the conventions match the market.

- **Bonds.** `fetch_universe()` has never touched a live Excel; the `CVCURVEBOND`
  block layout and column headers are unconfirmed. Nine countries' conventions are
  market knowledge, not library-supplied. CHN coupon frequency is *assumed*
  semi-annual for all 302 Chinese bonds and an annual payer would simply be wrong.
  BRA is worse: the two backends disagree on Bus/252 accrued itself and neither
  implements the domestic NTN-F quote — **do not trade off BRL numbers**.
  *Highest-value next step: fetch `YIELD`/`PRICE`/`DURATION`/`DV01` for ~20 bonds
  across countries and reconcile.*
- **Vol.** Only the ATM unit was measured. `PREMIUM`, `FWDPREMIUM` and the
  `OTM_RFR` skew branches still carry a declared unit. Only USD's axes were
  harvested, so a non-USD skew cube is shape-inferred (and warns). AUD, DKK, KRW,
  NOK and SEK have no `_RFR` branch at all — whether Citi lacks it or the walk
  never reached it is not known. The strike-to-offset anchor uses OUR forward, not
  Citi's ATM forward, which is not published on that branch.
- **Inflation.** A self-consistent round trip is **structurally blind** to the
  observation lag — this is asserted as a test, not hidden. 14 of 17 indices carry
  market-standard conventions. AUD_AUCPI's 3-month lag is a guess.
- **Cross-currency.** MTM notional reset is not modelled on the QuantLib side
  (worth up to 0.026 bp at 30Y, measured). AUD_BBSW and NZD_BKBM are refused
  outright — IBOR legs, no pricing path. Only EUR/USD, SEK/USD and DKK/USD were
  exercised of ~180 recorded pairs.
- **Options.** Both families were harvested only to the measure level; expiry and
  pair/underlying come from the desk's documented shape. The served price/vol units
  are stored raw with no conversion. The payoff orientation and the midcurve start
  convention are declared constants, and the midcurve start is worth 24% of the
  premium if wrong.
- **Curves.** Six currencies (DKK ILS MXN SGD THB ZAR) are market-standard. Their
  two backends agree perfectly *because they read the same convention row* — that
  agreement is one assumption checked against itself, not evidence. MXN Fondeo's
  28-day roll is approximated as monthly; treat MXN as indicative.
- **rateslib is 2.1.1, not 2.7.** `IRSabrCube` and `IRSplineCube` **do not exist**,
  and there is no rateslib `Swaption` either. The rateslib-side cube is built from
  `PPSplineF64` + `rl.IRS` forwards + the repo's own Bachelier, behind an interface
  an `IRSabrCube` backend could drop into later. The spec's 2.7 doc links do not
  apply to this environment.

---

## Operational notes

- The MDP source string is **`citivelo_excel`**. The existing `CITIVELO` /
  `CITI_VELO` / `CITIVELOCITY` aliases in `IRSwapsMDP` are untouched — the
  dealer-ladder study and 930 warmed CurveStore partitions depend on their current
  semantics.
- The cache root is **outside the repo** (`ARBS_CACHE_DIR` → platformdirs →
  `%LOCALAPPDATA%`), overridable with `CITIVELO_EXCEL_CACHE_DIR`. The one in-repo
  precedent produces constant `git status` churn and 16k bond tags would make that
  unbearable.
- Live tests are opt-in behind `CITIVELO_EXCEL_LIVE_TESTS=1` **and** a reachable
  add-in. They drive the user's own Excel process; attaching because a test
  happened to be collected is not acceptable.
- `verify_live.py` is deliberately ~12 calls. Do not grow it into a sweep. Put
  sweeps in a script that checkpoints, and never `Stop-Process` a client mid-call.

---

## Suggested next steps, in value order

1. **Reconcile bonds against Citi.** ~20 bonds across countries, compare
   `YIELD`/`DURATION`/`DV01`. This is the largest unverified surface.
2. **Measure the remaining vol units** — one `PREMIUM` and one `OTM_RFR` node.
   Extend `verify_live.py`; it is three lines.
3. **Probe the non-USD vol axes** so the skew cubes stop being shape-inferred.
4. **Probe `SPREAD_OPTIONS` / `MIDCURVES` below the measure level** to settle the
   expiry and pair grammar.
5. **Decide whether to warm a CurveStore asset** for the multi-currency curves. The
   machinery is there (`CurveSnapshot` + `write_day`); the asset name must be
   dedicated and `reference_key` must stay a `RATES(LIB)_CURVE_DEFINITIONS` key.
6. **`CVSTREAM`** remains out of scope — entitled, but an RTD push model needing a
   live event loop rather than request/response.
