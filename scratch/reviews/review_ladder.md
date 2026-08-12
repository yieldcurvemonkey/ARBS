# Adversarial review — `ladder` module (`ladder.py`, `health.py`, `provenance.py`, `tests/test_dealer_direction_ladder.py`)

Baseline: **50 passed** (`tests/test_dealer_direction_ladder.py`).

**Measurement tool validated first.** Mutations were applied by a pytest plugin that rebinds module attributes at `pytest_configure` (no file on disk edited — other agents are in this tree). Harness validated before any survivor was believed: a no-op plugin → 50 passed; a known-kill plugin (`visibility_date` → UTC date) → exactly `test_the_ladder_date_is_a_new_york_date_not_a_utc_date` red. 38 mutations run in total.

---

## A. Silent degradation (highest value here)

**A1. `provenance.py:188-191` — `getattr(pricing, ..., default)` converts an interface drift into a monitoring blackout that reports clean.**
The `getattr` defaults are needed only for `pricing is None`. When `pricing` is a real, fully-priced object whose field was renamed (`snapshot_policy` → `policy`, `snapshot_lag_seconds` → `lag_seconds`), `build` silently writes the *never-priced sentinel* `""` / `None`. Measured (R11):
```
snapshot_policy: ''   snapshot_lag_seconds: None   failure_reason: None
health.served_mask   -> [False]
overnight_hole_fraction -> NO_DATA  nan  {'n_unserved': 1}
```
Concrete failure: rename one `UnitPricing` field and every row of a successful run is classified UNSERVED. `overnight_hole_fraction` → NO_DATA, `snapshot_lag_distribution` puts 100% in UNSERVED, `snapshot_lag_metrics` reports `n_future=0` over an empty served set. Nothing raises; the run looks like a day with no curve problems. This is the exact `_require` doctrine (health.py:116-125) violated from the value side rather than the column side.

**A2. `ladder.py:243/252/259` + `provenance.py:320` — ladder-stage exclusions never reach `failure_reason`, so the coverage table overstates coverage.**
`provenance.build` takes `failure_reason` from `call.exclusion` only. But two exclusions are *created inside the ladder*: `EXCL_PRICING_ERROR` when a called unit has no risk row (ladder.py:259) and `EXCL_DEAD_ZONE` under `drop_dead_zone` (ladder.py:252). Those live only in the returned `excluded` frame. A caller building provenance the documented per-unit way gets (R6):
```
ladder excluded B: ['PRICING_ERROR']
coverage_table:  IN_LADDER  2  2000.0  share 1.0  n_fallback 0
```
B is reported IN_LADDER at 100% coverage while the ladder threw it out. `provenance.py:320` labels anything with a null `failure_reason` as IN_LADDER — i.e. absence of a reason is taken as success. The test at line 842 shows the intended manual stitching, but nothing in either module enforces it and no API performs the join.

**A3. `ladder.py:219-220, 232` — risk rows for a unit not in `units` vanish with no accounting.**
The loop iterates `units` and looks up `by_unit`; the reverse is never checked. The loudness is asymmetric and backwards: a unit without a call **raises** (ladder.py:236), a duplicate call **raises** (ladder.py:225), but a krd row without a unit is dropped in silence. Measured (R4): a `GHOST` row carrying 9,000,000 of DV01 produced `rows=['A'], excluded=[]` — the whole point of returning two frames ("`excluded` is what makes coverage a partition") is defeated for exactly that class.

**A4. `ladder.py:232, 372` — the same `Unit` twice is double-counted, and `n_units` hides it.**
Calls are de-duplicated; units are not. Measured (R5) with one unit passed twice and one krd row:
```
n_units  delta_dv01  abs_dv01  mean_abs_signed_weight
      1      1600.0    2000.0                    0.8
```
Expected 800.0. `n_units=("unit_key","nunique")` reports 1 — the cell claims one unit while carrying two units' risk, so the one column a reader would use to spot it actively conceals it. `assert_series_disjoint` returns clean on that aggregate (the key *is* unique; the duplication is upstream of the key).

**A5. `health.py:336-339` — `rolling_recycling_kappa` on history shorter than the window returns a frame with only one column.**
When no window closes, `rows` is empty and the function returns a frame carrying **only** `reference_kappa`. Measured (R1): 30 days at `window_days=90` → `columns: ['reference_kappa'], len: 0`, and `out["kappa"]` raises `KeyError: 'kappa'`. The `len(x)==0` branch three lines above returns all seven documented columns, so the two empty paths disagree. Concrete failure: a monitor loop that starts on a short history crashes on column access instead of reporting NO_DATA.

**A6. `health.py:519-532` — `imputed_notional_fraction` degrades two different wrong ways on a renamed flag column.**
Measured (R2) with `notional_imputed_flag` instead of `notional_imputed`:
- no `weights` → `value=nan`, `status=NO_DATA`, silent (the `_require` failure mode this file's own docstring at health.py:119 declares unacceptable);
- with `weights` → `IndexError: Boolean index has wrong length: 0 instead of 4` at health.py:532.

**A7. `health.py:915-918` — `pricing_success_by_stratum` uses `legs.get(col, default)` for `is_capped` and the index column; health.py:119 says that spelling is wrong.**
`_require` (health.py:901) demands only `as_of_date`, `effective_date`, `priced`. Measured (R3) with `is_capped_flag` / `index_name`: **two priced BASIS legs report `BASIS status = NO_DATA`.** The BASIS row is the inverted alarm — "a *successfully priced* BASIS leg is the alarm" — and a column rename disables it permanently and quietly. CAPPED likewise reports NO_DATA forever.

---

## B. Tests that cannot fail

### B1. Tests that pass while the specific behavior they name is broken

- **`tests/…ladder.py:413` `test_a_mid_biased_off_venue_scores_zero_not_one`** — the file header calls this "THE test", and it does not reach the kappa formula. Mutating `_kappa`'s return to `return float(hit), hit, chance, False` (i.e. kappa ≡ the naive hit rate) leaves this test **green**: with both series all `+1`, `chance = 1.0` and the function short-circuits at health.py:382 returning a hard-coded `0.0` (R9). What the test pins is the degenerate branch (confirmed: mutating that `0.0` → `1.0` does turn it red), not the marginal correction it claims to pin. Four *other* tests catch the kappa mutation, so the behaviour is covered — but not by the test whose docstring asserts it.
- **`tests/…ladder.py:539` `test_the_dead_zone_alarm_is_two_sided`** — deleting the absolute-limit override inside the reference branch (`health.py:496-497`) leaves all 50 green. Its second half calls `dead_zone_fraction(many)` with **no** reference, which alarms through the ordinary `direction="above"` threshold. The docstring's claim that "the upper absolute limit is still enforced" *when a reference is supplied* is unpinned.
- **`tests/…ladder.py:555` `test_imputed_notional_fraction_is_weighted_as_well_as_counted`** — deleting the DV01 escalation (`health.py:552-556`) leaves all 50 green. The asserted `status == ALARM` is already produced by the count (`value=0.25 ≥ alarm 0.10`); the comment `# 70% of DV01 imputed` attributes it to the wrong branch. Only the `detail["dv01_share"]` assert touches the weighted path, and it tests the arithmetic, not the escalation.

### B2. Correct implementation, zero pinning (mutation survived all 50)

| # | Mutation | Survives |
|---|---|---|
| m2 | `ladder._assert_weight_agrees_with_side` → no-op | ✅ |
| m20 | `aggregate`: `mean_abs_signed_weight = 1.0` | ✅ |
| m32 | `aggregate`: `abs_dv01` computed from `delta_dv01` not `dv01_if_received` | ✅ |
| m24 | `assert_series_disjoint` → no-op | ✅ |
| m25 | `interdealer_flow` selects `VENUE_D2C` | ✅ |
| m26 | `snapshot_lag_metrics`: `n_in_over` forced to 0 | ✅ |
| m27 | `health_report` sorts best-first (an ALARM lands last) | ✅ |
| m28 | `annuity_dv01_proxy_from_dates`: past-start `max(0.0, …)` clamp removed | ✅ |
| m29 | `orient_to_received`: `dealer_sign == 0` guard removed | ✅ |
| m30 | `unit_ladder_rows`: unit-with-no-call raise → silent `continue` | ✅ |
| m35 / m36 / m37 | see B1; m37 = overnight-hole p90 thresholds set to 1e18 | ✅ |

**m2 is the one that matters.** `_assert_weight_agrees_with_side` (ladder.py:283-314) is the module's central sign guard, and it is *correct* — verified directly, it raises on both failures it names:
```
signed_weight=p       -> "signed_weight 0.9 is not 2p-1 = 0.8 for p=0.9…"
flipped dealer_sign   -> "signed_weight 0.8 and dealer_sign -1 disagree on the side…"
```
But the fixture `_call` (test line 85) always derives `signed_weight` from `conv.signed_weight(p)` and `dealer_sign` from `p`, so no test ever constructs an inconsistent call. The two failure modes the module exists to prevent — a producer shipping `signed_weight = p`, and a producer computing `dealer_sign` against a flipped convention — are guarded by an assert no test proves is live.

m30 is the same shape: the "no direction call" error is documented as the thing that keeps coverage accounting whole, and removing it (units silently skipped) is undetected.

m27 is worth noting on its own: `health_report`'s docstring says the ordering exists "so that a single ALARM cannot be lost in a long OK list", and reversing the sort is invisible to the suite.

---

## C. Claims no measurement supports

- **`health.py:689`** — "128 truncated SOFR days exist". Unsupported as cited. `docs/2026-08-09-citivelo-minute-curve-fidelity.md:613` measures **161** truncated-end SOFR days (33,832 minutes), 141 for Fed Funds, **302** total (:694, :771). `128` appears nowhere in `docs/` or `scratch/`.
- **`health.py:290-292`** — "90 days is also the reach-back that holds 90.7% of the flippable lineage population". `LEDGER.md:568` measures **≤63 d → 90.7%**; the ~90-day figure in the same sentence of the LEDGER is **90%**. The 90.7% belongs to 63 days, and it is the stated justification for the default window.
- **`health.py:516`** — "every band moved by 1.7-3.6x". Computed from the `LEDGER.md:839` nine-band table the range is **1.55x–3.57x**: the 6m-1y band moved 1.1bn→1.7bn = 1.55x and the 3-6m band 1.2bn→2.0bn = 1.67x, both below the quoted floor on a claim quantified over "every band".
- **`health.py:778-780`** — "the observed hour-00 population is served at 1-97 minutes" presents an n=7 sample as a population fact. `LEDGER.md:484`: "**7/7** hour-00 prints served at 1–97 min lag".
- **`health.py:369-370`** — "A degenerate marginal — one series entirely one sign — makes the chance rate 1 and kappa `0/0`". False as stated: `chance = px·py + (1−px)(1−py)`, so `px=1, py=0.5` gives `chance = 0.5`, not 1, and `degenerate=False`. The single-degenerate case therefore never sets the flag that forces ALARM. Behaviour mostly survives (kappa evaluates to 0.0 and the placebo alarm usually catches it), but on a series short enough that `_placebo_p95` returns `None` (health.py:394) the only remaining test is `warn=0.10, direction="below"` → a fully one-sided classifier reports **WARN, not ALARM**.

Everything else ties out against `docs/dealer_direction/LEDGER.md`: F-3 (2,289,646 legs; p50=p90=0 both classes; p99 1,091/911s; max 1,352,256s block), F-7 platform mix (51,260 XXXX / 28,401 XOFF / 25,192 TREU) and cap schedule (3.01%, 68,946, nine bands, 2024-10-07, D2C 3.00%/D2D 3.11%, 15.4% DV01, 10.6–16.0%, 12.8–13.9%, 5.9% vs 1.2%), F-15 (200/200, 48.8x IQR ratio), F-16 (55 sentinels, 99.99994%, 37% forward-starting, 58.08%≈58.1%, median ratio 1.00), F-19/21 (5.23 min / 11.3 min), F-20 (21.70%/55.5%, 5.43%/40.5%, ~0.5bp, ~7x, 78% PAID), T-4 (single UNKNOWN, "fixings contain more fixings than expected"), T-7 (`870c71f0698b` / `468474ca6f84`), T-3 (200/294 on 2026-07-24), D11 (≥34pp), and the 0.24–0.29bp / ≤1.43bp overnight-hole drift table.

---

## D. Sign errors — clean

Traced by hand and then through the real functions (`scratch/ddrev2_signtrace.py`).

**OUTRIGHT**, printed 4.00% vs mid 3.98%: `structure_price` → 400.0 bp vs 398.0 bp → deviation **+2.0 bp** → `dealer_side` → **+1 = DEALER_RECEIVED** → `dealer_received_signs = (1,)`, identical to `stir_flow.ladder_conventions.dealer_leg_signs('OUTRIGHT','RATE_VS_MID','RECEIVED',1) = [1]`. With `p = 0.90` (p(customer paid fixed)), `signed_weight = +0.80`, `delta_dv01 = 0.80 × 4500 = +3600 > 0`. Matches the pinned convention exactly: customer pays fixed → dealer RECEIVED → `delta_dv01 > 0`.

**CURVE 2s5s** (the two-negation trap): `o = (-1, +1)`, `q = (-1.0, +1.0)`; traded 3.50/4.00 → P = +50.0 bp, mid → +48.0 bp, deviation +2.0 → `dealer_side = +1` → `dealer_received_signs = (-1, +1)`, identical to the frozen predecessor's `[-1, 1]`. The two flips cancel as documented (`dealer_received_signs == dealer_sign * o`).

**`orient_to_received`** round-trips correctly: `delta_dv01 = -4500, dealer_sign = -1` → `dv01_if_received = +4500`.

**Caveat:** `krd.py` is listed in `provenance.VINTAGE_SOURCES:78` but does not exist, so nothing in the tree produces `dv01_if_received`. The chain is verified only up to the ladder's input contract; the sign of the producer is untestable today. Related: `lifecycle.py` (`VINTAGE_SOURCES:79`) is also absent — intentional per the docstring, but it means the current digest is partly a hash of `<missing>` markers.

## E. Lookahead — clean

Every row is stamped on `Clocks.visibility` and keyed on the **New York** date (`ladder.py:120-144`, `_unit_meta:323`); `execution`/`event`/`pricing` are carried but never aggregation keys. The naive-timestamp branch is right for the reason given (converting a date-only EOD fallback would hand back the previous day). `decayed_flow` groups on `visibility_date`. `d2d_recycling_kappa`'s forward window (`health.py:230-232`) starts at `k=1`, so no print is ever paired against itself. No curve is read at or after a print anywhere in these three files.

## F. Interface drift — one item, already covered

`ladder` and `provenance` read only fields that exist on `types.Unit` / `Clocks` / `DirectionCall` / `UnitPricing`, and `conventions.signed_weight` / `RULE_RATE` are used with the right signatures. The one drift hazard is A1 (the `getattr` defaults on `UnitPricing`, which convert drift into silence rather than an `AttributeError`).

## G. Minors, one line each

- `provenance.py:300-312` — a unit whose DV01 is exactly `0.0` (not NaN) passes the "sizeless unit" guard and reports a 0.0% share (R7), which is verbatim the failure the error message at :308-312 describes; only NaN is caught.
- `health.py:230-232` — `horizon_days > n` crashes: `ValueError: operands could not be broadcast together with shapes (2,) (0,) (2,)` (R8), rather than returning NO_DATA.
- `health.py:597-600` — `is_overnight_hole` matches only `max_lag=`, ignoring `method=`: a bounded **nearest-either-direction** policy (`method=nearest max_lag=60s`) returns `False`, i.e. is classified as the strict in-session branch (R10) — the shipped default that serves 1.09% of legs a future curve.
- `provenance.py:231-234` — `annuity_dv01_proxy(flat_rate=0)` raises `ZeroDivisionError`; the limit is well-defined (`A(x) → x`).
- `health.py:284, 328` — `rolling_recycling_kappa` hard-codes `n_bootstrap=0` and also forwards `**kwargs`; a caller passing `n_bootstrap=` gets `TypeError: got multiple values`.
- `health.py:309` — `_align_daily(d2c, d2d)` result in `rolling_recycling_kappa` is used only for a length test; the axis is recomputed at :318-319.

## Evidence

`C:\Users\chris\clee\ARBS-dd\scratch\ddrev2_mut0.py` (harness validation, no-op), `ddrev2_mut1.py` (known-kill), `ddrev2_mut.py` / `ddrev2_mut_b.py` / `ddrev2_mut_c.py` (38 mutations, selected by `DDREV_MUT`), `ddrev2_repro.py` (R1–R10), `ddrev2_signtrace.py` (sign trace + R11). Run as `PYTHONPATH=…/scratch ARBS_SUPABASE_ENABLED=0 C:/Users/chris/anaconda3/envs/stir/python.exe -m pytest tests/test_dealer_direction_ladder.py -q -p ddrev2_mut`. No module file was edited; no thresholds relaxed; nothing committed.