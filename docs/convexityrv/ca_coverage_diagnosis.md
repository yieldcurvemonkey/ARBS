# CA coverage diagnosis — where every date is lost, and what the warm actually costs

Second measurement pass, 2026-08-19, on this machine. Every number below was
produced by a read-only scan of the 8 sqlite shards of `STIRFuturePricer_Cache`
plus the repo's own `local_cached_dates` / `strip_depth_by_date` /
`trim_to_contiguous_run` / `day_rows` / `window_gate` applied to that scan and to
the shipped panel artifacts. Nothing is reimplemented, so the checker cannot
disagree with the code by construction.

**Two deliberate network calls were made**, to measure the warm's unit cost
(section 6). Everything else ran offline with `network_calls_blocked == 0`.

### What this pass changes versus the previous revision of this document

| # | previous claim | status |
|---|---|---|
| 1 | warm to depth 20 = "10,230 contracts, 170.5 hours" | **WRONG — replaced.** That is the *cell* count priced at an unmeasured 60s. Measured: **30 distinct contract codes**, ~652 batched calls, **~64 minutes**. Section 6. |
| 2 | "shards at 83% of the cull threshold; a warm would evict comparable volume" | **WRONG — replaced.** Compared file size to `size_limit`; diskcache culls on the tracked `size` counter, which reads **0**. The depth-20 warm writes ~19,300 keys ≈ **6 MB**. Section 6.4. |
| 3 | brief's evidence table "is consistent with a scan that did not filter to 17:00" | **HALF RIGHT — corrected.** The brief's table is reproduced **exactly, 9/9 years, all 7 columns**, and it *is* EOD-source-only. Section 1.2. |
| 4 | interpolation audit by grepping `connectgaps` | **SUPERSEDED.** Audited on the *rendered* plotly arrays instead: **152 offending traces in 11 notebooks**, including `ca_vol_link.ipynb`, which the grep-based pass missed. Section 7. |
| 5 | funnel, gate, and `trim_to_contiguous_run` numbers | **RE-VERIFIED, unchanged.** Independently reproduced (743 / 301 / 1,081 dates). Sections 2-3. |

New material: a direct proof of cause A by pricing the discarded dates
(section 4), a measured settle/live separation test (section 5), and two
network-safety findings for the repair agent (section 9).

---

## 0. Verdict

| year | rank-1 dates that **could** be priced | rank-1 dates in the panel | lost | largest killer |
|---|---|---|---|---|
| 2023 | 258 | 222 | 36 | `min_instruments` floor |
| 2024 | 252 | 19 | **233 (92.5%)** | `min_instruments` floor |
| 2025 | 198 | 2 | **196 (99.0%)** | `min_instruments` floor |
| 2026 | 37 | 3 | **34 (91.9%)** | `min_instruments` floor |

Ranked by dates lost:

1. **A single depth gate discards 463 rank-1-priceable dates over 2024-2026.**
   Pure code defect, zero network required. Proven by pricing 15 of them
   (section 4). Section 3.1.
2. **`trim_to_contiguous_run` keeps the longest run, not the latest**, truncating
   the near-pack series at **2024-05-08** — literally the "~May-2024" in the
   complaint — and discarding 217 of 518 dates on the Q20 near path.
   Section 3.5.
3. **The gate's 2.0bp settle-agreement threshold** removes 147 of 222 rank-1
   dates in 2023 and 18 of 19 rank-17 dates in 2024. A threshold sitting inside
   a distribution, not an absence of data. Section 3.2.
4. **Cache warmth is a genuine but much cheaper constraint than believed.**
   Real, but 30 contract codes and ~1 hour, not 10,230 and 170 hours. Section 6.
5. **Every CA chart draws straight lines through its holes** — 152 rendered
   traces, and `connectgaps=False` is present but *inert*. Section 7.

**The settle/live separation is clean.** 130,044 (date, contract) cells asserted
by the shipped panels, **0** absent from `BARCHART_STIRF-RL`, **0** sourced from
`BARCHART_TOS_LIVE_STIRF-RL`. Section 5.

---

## 1. Scan provenance and the universe reconciliation

### 1.1 The scan

Ticker-anchored regex, never anchored on a hyphen-free timestamp:

```python
r"^(?P<d>\d{4}-\d{2}-\d{2})T(?P<t>\d{2}:\d{2}:\d{2})(?:\.\d+)?"
r"(?P<tz>[+\-]\d{2}:\d{2}|Z)?-(?P<sym>SR3[FGHJKMNQUVXZ]\d{2})-(?P<src>.+)$"
```

| quantity | measured |
|---|---|
| total cache keys | 22,472,084 |
| SR3-shaped keys | 16,149,740 (71.9%) |
| matched by the **repo's own** `_STIR_CACHE_KEY` | 16,149,740 — **0 misses** |
| `BARCHART_STIRF-RL` (EOD) | 3,425,020 |
| `BARCHART_TOS_LIVE_STIRF-RL` (intraday) | 12,724,720 |
| EOD keys stamped exactly `17:00:00` | **37,028** |
| LIVE keys stamped exactly `17:00:00` | 16,611 |

The repo's regex is sound — the 33.9% key loss described in the brief belongs to
an ad-hoc probe, not to shipped code. Scan time 51s.

Note the ratio: of 3,425,020 EOD keys only **37,028 (1.1%)** carry the
`17:00:00` stamp. The other 98.9% are 1-minute bars of the same trading days,
written by the bulk persist loop at `MDP/STIRFutures/STIRFutureMDP.py:1556-1569`.
This matters in section 6.

### 1.2 The brief's table is correct, and measures something the code does not use

The brief's evidence table reproduces **exactly** — all nine years, all seven
columns including `max` — under this cut: **`BARCHART_STIRF-RL` only, ALL
session times, total distinct SR3 tickers per date, unbounded, no contiguity
required.**

```
  yr       any   >=4   >=8  >=12  >=16  >=20   max
  2018     168   168   168   167   167   167    21
  2019     253   253   253   252   252   252    28
  2020     254   254   253   253   253   253    27
  2021     252   252   252   252   252   243    23
  2022     258   257   253   253   246    52    25
  2023     259   259   258   253    53    53    25
  2024     259   259   244    19    19    19    25
  2025     258   256     2     2     2     1    25
  2026     155   146     9     9     1     0    16
```

So the brief's source attribution was right. But the code gates on a **different
quantity**, and both differences bite:

```python
# strat2_q20.py:395            and  strat2_sofr_convexity.py:814-816
if m.group("t") != session_time or m.group("src") != cfg.eod_source:
    continue
```
```python
# strat2_q20.py:406-412 — CONTIGUOUS front prefix, breaks at the first hole
for y, m in seq:
    if futures_symbol(y, m, cfg.futures_root) in syms:
        depth += 1
    else:
        break
```

The operative universe — EOD source, `t == 17:00:00`, contiguous front strip:

| year | dates | ≥4 | ≥8 | ≥12 | ≥16 | ≥20 |
|---|---|---|---|---|---|---|
| 2018 | 167 | 167 | 167 | 167 | 167 | 41 |
| 2019 | 253 | 253 | 253 | 252 | 252 | 77 |
| 2020 | 254 | 253 | 253 | 253 | 253 | 253 |
| 2021 | 252 | 252 | 252 | 252 | 252 | 187 |
| 2022 | 253 | 252 | 252 | 252 | 195 | 52 |
| 2023 | 258 | 258 | 258 | 231 | 51 | 51 |
| 2024 | 253 | 252 | 180 | 19 | 19 | 19 |
| 2025 | 251 | 199 | 2 | 2 | 2 | 1 |
| 2026 | 131 | 37 | 5 | 5 | 1 | 0 |

This reproduces the `strat2_q20` module docstring's own table exactly
(`≥13` → 1,396 dates; `≥20` → 681), so the cache has not materially changed
since that table was written.

**Contiguity is not a factor.** Dates with ≥N tickers present in the front strip
but a contiguous prefix < N: **0, in every year, at every N ∈ {4, 8, 12, 16,
20}.** The gap between the two tables is entirely the **session-time filter**,
not holes in the strip.

**The 17:00-only filter is itself worth ~110 dates in 2026.** Contiguous depth
reachable at a *single* session timestamp (a consistent snapshot, not a union
across times):

| year | dates | `t==17:00:00` ≥4 | best single ts ≥4 | 17:00 ≥8 | best ≥8 |
|---|---|---|---|---|---|
| 2024 | 259 | 252 | 256 | 180 | 180 |
| 2025 | 258 | 199 | 241 | 2 | 2 |
| 2026 | 155 | 37 | **140** | 5 | **9** |

So 2026 rank-1 coverage is 37 dates under the exact-17:00 rule and **140** under
a nearest-session-bar rule. That is a third free lever, though it trades a
settle stamp for a near-settle bar and should be labelled on the row if used.

### 1.3 Canary

2023-06-09, the documented tie-out date, resolves **24 of 24** requested
contracts with contiguous front depth 24. The scanner is correct.

---

## 2. The funnel

Dates surviving each stage. `(a)` any SR3 EOD data; `(b)` enough contiguous
contracts for that rank; `(c)` `local_cached_dates` / `strip_depth_by_date` as
written; `(d)` contiguity — never binding, see 1.2; `(e)` swap curve resolves;
`(f)` `window_gate`; `(g)` `trim_to_contiguous_run`; `(h)` warmup.

### rank 1 — Whites, needs contracts 1..4

| year | (a) any EOD | (b) has 4 | (c) gate as written | (e) swap | in panel | (f) `gate_ok` |
|---|---|---|---|---|---|---|
| 2023 | 258 | 258 | 231 | 222 | 222 | **75** |
| 2024 | 253 | 252 | **19** | 19 | 19 | 18 |
| 2025 | 251 | 199 | **2** | 2 | 2 | 2 |
| 2026 | 131 | 37 | **5** | 5 | 3 | 2 |

### rank 5 / 9 / 13 / 17

| rank | year | (a) | (b) has r+3 | (c) | (e) | panel | (f) `gate_ok` |
|---|---|---|---|---|---|---|---|
| 5 | 2023 | 258 | 258 | 231 | 222 | 222 | 215 |
| 5 | 2024 | 253 | **180** | 19 | 19 | 19 | 19 |
| 5 | 2025 | 251 | **2** | 2 | 2 | 2 | 2 |
| 9 | 2023 | 258 | 231 | 231 | 222 | 222 | 218 |
| 9 | 2024 | 253 | **19** | 19 | 19 | 19 | 19 |
| 13 | 2023 | 258 | **51** | 51 | 51 | 51 | 49 |
| 13 | 2024 | 253 | **19** | 19 | 19 | 19 | 19 |
| 17 | 2023 | 258 | 51 | 51 | 51 | 51 | **28** |
| 17 | 2024 | 253 | 19 | 19 | 19 | 19 | **1** |
| 17 | 2025 | 251 | 1 | 1 | 1 | 1 | **0** |

**Largest killer by year and rank.** For **every rank in 2024-2026** and for
rank 1 in 2023, the largest single killer is stage (c), the `min_instruments`
floor. For rank 17 in 2023-2025 and rank 1 in 2023 the *second* killer, and the
one that removes most of what survives, is stage (f) settle agreement.

**Residual: zero.** The shipped run's own manifest, `strat2_q20_skips.json`,
records `universe_dates: 1433` → `ok: 1410`, and the 23 missing dates are
exactly `swap_ref_mismatch: 21` + `q20_build: 2`. Nothing is unaccounted for.
The 2023 losses are US market holidays where the SR3 EOD key exists but the swap
store serves the previous close — `strat2_sofr_convexity.py:746`, correct
behaviour.

> The universe count is a moving target because the store is demand-driven:
> `strip_depth_by_date` returned **1,433** when the panel was built, **1,434**
> at the start of this pass, and **1,436** at the end — the last two dates being
> the ones section 6.2's probes warmed. Quote the manifest, not a live rescan,
> when tying out to a shipped artifact.

---

## 3. Root causes, ranked by dates lost

### 3.1 `strip_depth_by_date`'s `min_instruments` floor — 463 dates (2024-2026)

`RVUtils/ConvexityRV/strat2_q20.py:413` with `:289`

```python
        if instrument_count(dd, depth) >= cfg.min_instruments:
            out[dd] = depth
```
```python
    min_instruments: int = 12
```

A date enters the universe **only if its contiguous strip reaches 12**. Depth is
then used per rank (`gate_covered = spec.rank + 3 <= depth`, `:706`) — so the
code already knows how to vary the rank set by depth, but the date never reaches
that line. A 4- or 8-deep date, which prices ranks 1 and 5 perfectly well, is
dropped for **every** rank.

Measured directly by calling the shipped function twice:

```
strip_depth_by_date(min_instruments=12) -> 1434 dates
strip_depth_by_date(min_instruments=4)  -> 1922 dates
  2023:  231 ->  258   (+27)
  2024:   19 ->  252   (+233)
  2025:    3 ->  198   (+195)
  2026:    5 ->   37   (+32)
```

> **Reconciling 460 with 463.** The deltas above sum to 460 and count **universe
> admission** — what `strip_depth_by_date` lets through. The verdict table in
> section 0 says 463 and counts **panel absence** — rank-1 dates at contiguous
> depth ≥4 that the shipped panel does not carry. The difference is the 3 dates
> admitted to the universe but skipped later (1 in 2025, 2 in 2026) by the
> swap-reference and Q20-build checks of section 2. Both figures are correct;
> they answer different questions.

The floor is justified in the docstring as *"a 20-node curve fitted to 6
contracts is mostly interpolation"*. That reasoning is about the **Q20 curve**.
It is not sound for the `settle` rate source, which needs no curve at all —
`day_rows` computes `ca_bp_settle` from raw settles on the same pass and it is
discarded along with everything else. Section 4 shows the Q20 curve resolves at
depth 7-10 anyway.

### 3.2 `window_gate` settle agreement — 147 rank-1 dates in 2023, 18 rank-17 in 2024

`strat2_q20.py:295` and `:710-716`

```python
    gate_max_settle_diff_bp: float = 2.0
...
    agrees = bool(np.isfinite(max_diff) and max_diff <= cfg.gate_max_settle_diff_bp)
```

Measured on the shipped panel, with the rejection reason broken out:

| rank | year | rows | resolved | agrees | `gate_ok` | fail res only | fail settle only | median max diff bp |
|---|---|---|---|---|---|---|---|---|
| 1 | 2019 | 250 | **0** | 0 | **0** | 0 | 0 | 22.10 |
| 1 | 2020 | 251 | 169 | 188 | 159 | 29 | 10 | 1.09 |
| 1 | 2022 | 249 | 249 | 60 | **60** | 0 | **189** | 4.21 |
| 1 | 2023 | 222 | 222 | 75 | **75** | 0 | **147** | 2.22 |
| 1 | 2024 | 19 | 19 | 18 | 18 | 0 | 1 | 0.87 |
| 5 | 2023 | 222 | 222 | 215 | 215 | 0 | 7 | 1.28 |
| 9 | 2023 | 222 | 218 | 222 | 218 | 4 | 0 | 0.39 |
| 13 | 2023 | 51 | 49 | 51 | 49 | 2 | 0 | 0.27 |
| 17 | 2021 | 187 | 186 | 86 | **85** | 1 | **101** | 2.20 |
| 17 | 2023 | 51 | 51 | 28 | **28** | 0 | **23** | 1.90 |
| 17 | 2024 | 19 | 19 | 1 | **1** | 0 | **18** | 2.71 |

The rank-1 2023 median is **2.22 bp against a 2.0 bp threshold** — the
population straddles the cut, which is why 66% of rows die. Rank-1 2019 fails
*resolution* on 250 of 250 rows with a 22.1 bp median disagreement: that is the
documented pre-2021 meeting-node degeneracy, and the gate is doing its job
there.

Note the asymmetry: rank-1 settle disagreement measures the **Q20 curve's**
front-end fit, and for `rate_source="settle"` the test gates on a defect of a
curve the settle path does not use.

### 3.3 `local_cached_dates` — the all-or-nothing gate on the near-pack path

`strat2_sofr_convexity.py:828`

```python
        if all(s in have[d] for s in names):
            out.append(dd)
```

`all(...)` over the **full** `n_contracts` strip. Same collapse, different route.
Reinforced by a second count gate at `:740`:

```python
            if len(prices) < cfg.rank_start + cfg.n_packs + 2:
                continue
```

### 3.4 The config forbids the shallow case entirely

`strat2_sofr_convexity.py:463-468`

```python
        if self.rank_start < 2:
            raise ValueError("rank_start must be >= 2 so the 3m roll has a nearer pack")
        if self.rank_start + self.n_packs - 1 + 3 > self.n_contracts:
            raise ValueError(...)
```

Together these make **`n_contracts=4` unrepresentable**: the minimum legal
config is `rank_start=2, n_packs=1 → n_contracts=5`. Measured consequence — 2024
dates at contiguous depth **exactly 4**, which rank 1 could price but no legal
`Strat2Config` can express: **19**. The repair must relax this, not just
`min_instruments`.

### 3.5 `trim_to_contiguous_run` — confirmed as the dominant killer of the tail

`strat2_sofr_convexity.py:833-857`

```python
    lo, hi = max(runs, key=lambda r: r[1] - r[0])
    keep = days[lo:hi]
```

It keeps the **longest** run, not the **latest**. Measured at each call site with
the notebooks' own configurations, and it **reproduces the shipped artifacts
exactly** — which is the tie-out for this section:

| call site | band | before | after | span after | shipped artifact |
|---|---|---|---|---|---|
| `strat2_sofr_convexity_backtest.py:495` | 1..10 | 1,084 | **1,081** | 2019-07-08 .. **2024-05-08** | `strat2_equity.parquet` ends 2024-05-08 ✓ |
| `strat2_q20_deep_packs.py:684` via `prep`, deep | 8..14 | 798 | **743** | 2019-06-20 .. **2023-02-01** | `strat2_q20_equity.parquet` = 743 dates ✓ |
| `strat2_q20_deep_packs.py:684` via `prep`, near | 1..10 | 518 | **301** | 2020-12-01 .. **2022-03-23** | `strat2_q20_equity_near.parquet` = 301 dates ✓ |

The near-pack Q20 trim discards **217 of 518** admissible dates — every date in
2023, 2024 and 2025 — because the longest gap-free run happens to be a 2021
block, and the gap it cuts on is only 248 days wide (2022-04-19 → 2022-12-23).

For the near-pack panel the trim removes only 3 dates, but it removes exactly the
three that matter. The gaps it cuts on:

```
2024-05-08 -> 2025-03-05   (301 days)
2025-03-12 -> 2026-07-27   (502 days)
```

**This is the "~May-2024" in the complaint.** The panel's last dense date is
2024-05-08 and the trim ends the series there.

**Answering the brief's question plainly: yes, `trim_to_contiguous_run` discards
the sparse 2024-2026 tail wholesale, and on the Q20 near path it is the single
largest killer (217 dates) — larger there than the depth gate.**

### 3.6 The notebook's "every rank present" rule

`notebooks/backtests/convexity_rv/strat2_q20_deep_packs.py:680-681`

```python
    _full = sub.groupby("date")["rank"].nunique()
    sub = sub[sub["date"].isin(_full[_full == (hi - lo + 1)].index)]
```

A third all-or-nothing rule, applied after the first two. Measured: gate-passed
1,410 dates → deep band 8..14 all-7-ranks **798**; near band 1..10
all-10-ranks **518**.

### 3.7 Funnel stage (h) — the warmup consumes most of what survives

`strat2_sofr_convexity.py:904-917`, at the shipped windows (`realized=63`,
`z3m=63`, `z1y=252`, `min_history_for_z1y=252`). Dates carrying at least one
finite value, measured on each post-trim panel:

| band | dates after trim | `rv` (63) | `ca_z3m` (63) | `ca_z1y` (252) | z1y coverage |
|---|---|---|---|---|---|
| deep 8..14 | 743 | 680 | 681 | 486 | 65% |
| **near 1..10 (Q20)** | **301** | 238 | 239 | **50** | **17%** |
| near 1..10 (settle panel) | 1,081 | 1,018 | 1,019 | 830 | 77% |

The Q20 near-pack path emits a 1Y z-score on **50 of 301 dates**, because 252 of
its 301 rows are consumed by warmup. Two of the eight ranking metrics
(`ca_z1y`, `vs_model_z1y`) are therefore silent for 83% of that backtest — a
direct consequence of stage (g) having cut the panel to 301 dates in the first
place. Fixing the trim fixes this too.

### 3.8 Row-based rolling windows — a defect that survives any coverage fix

`strat2_sofr_convexity.py:904-910`. `rolling` counts **rows**, not calendar days,
so a gap neither restarts the warmup nor is flagged:

| as-of | nominal window | actual calendar span of the rows used |
|---|---|---|
| 2024-01-03 | 252 rows ("1Y") | **883 days** |
| 2024-01-03 | 63 rows ("3m") | **532 days** |
| 2025-03-05 | 252 rows ("1Y") | **1,289 days** |

Removing the trim without also gating on window span would replace a truncated
series with a silently wrong one.

---

## 4. Cause A proven — the discarded dates price cleanly, offline

`min_instruments` is a `Q20Config` field, not a code change, so the claim is
directly testable. Fifteen 2024 dates that the shipped panel does **not** carry,
run through the **shipped** `day_rows` at their scan-derived depth, inside
`cache_only()`:

```
      date  depth  n_rows  ca_bp_settle  ca_bp_q20  gate_ok  gate_resolved  gate_agrees  max_settle_diff_bp
2024-01-02     10       7        -0.055     -0.217     True           True         True                1.00
2024-01-30     10       7         0.707      0.564     True           True         True                0.78
2024-02-27     10       7         1.164      1.007     True           True         True                1.61
2024-03-25      9       6         0.094      0.103     True           True         True                0.51
2024-04-22      9       6         0.406      0.377     True           True         True                0.56
2024-05-16      9       6         0.181      0.136     True           True         True                0.87
2024-06-07      9       6        -0.609     -0.617     True           True         True                1.14
2024-07-01      8       5         0.590      0.627     True           True         True                0.74
2024-07-23      8       5        -0.537     -0.453     True           True         True                1.19
2024-08-13      8       5        -0.014      0.190     True           True         True                1.79
2024-09-04      8       5         0.107      0.352    False           True        False                2.61
2024-09-25      7       4        -1.054     -0.873    False           True        False                3.75
2024-10-16      7       4         0.859      0.942     True           True         True                1.63
2024-11-06      7       4        -1.179     -1.120     True           True         True                1.08
2024-11-27      7       4        -1.051     -1.041     True           True         True                0.52

priced 15/15   failed 0
network_calls_blocked delta = 0
ca_bp_settle finite on 15/15; range -1.18..1.16 bp
```

**15 of 15 price. 13 of 15 pass the full gate. Zero network calls.** The Q20
curve resolves on all 15 even at depth 7 — the `min_instruments=12` floor's
stated rationale does not hold at these depths.

### Dates recoverable with NO fetching, per rank per year

Format: *dates at the required contiguous depth / already in the panel /
**recoverable***.

| year | rank 1 | rank 5 | rank 9 | rank 13 | rank 17 |
|---|---|---|---|---|---|
| 2023 | 258 / 222 / **+36** | 258 / 222 / **+36** | 231 / 222 / **+9** | 51 / 51 / +0 | 51 / 51 / +0 |
| 2024 | 252 / 19 / **+233** | 180 / 19 / **+161** | 19 / 19 / +0 | 19 / 19 / +0 | 19 / 19 / +0 |
| 2025 | 198 / 2 / **+196** | 3 / 2 / +1 | 3 / 2 / +1 | 3 / 2 / +1 | 2 / 1 / +1 |
| 2026 | 37 / 3 / **+34** | 5 / 3 / +2 | 5 / 3 / +2 | 1 / 1 / +0 | 0 / 0 / +0 |

**Free recovery total: 499 rank-1 dates and 200 rank-5 dates across 2023-2026.**
Ranks 9, 13 and 17 recover essentially nothing without fetching — for those, the
constraint is genuinely cache warmth, exactly as the brief's cause B says.

Of the 233 recoverable 2024 rank-1 dates, **19 sit at contiguous depth exactly
4** and additionally need the `rank_start >= 2` / `n_contracts >= 5` constraint
of section 3.4 relaxed.

---

## 5. Settle / live separation — a measured zero

Two independent tests.

**Static.** Every reference to `BARCHART_TOS_LIVE_STIRF-RL` anywhere in
`RVUtils/ConvexityRV/`, `notebooks/backtests/convexity_rv/` and `scripts/` is a
**docstring or comment warning against it**:

```
RVUtils/ConvexityRV/strat2_q20.py:155     (module docstring — the trap)
RVUtils/ConvexityRV/strat2_q20.py:252     (EOD_SOURCE comment)
notebooks/.../strat2_q20_deep_packs.py:28  (narrative)
notebooks/.../strat2_q20_deep_packs.py:859 (risk table)
```

No executable path constructs a live-source MDP. `EOD_SOURCE =
"BARCHART_STIRF-RL"` is the only futures source reaching `Q20Builder`,
`settle_rates`, `build_q20_pricer` and `build_panel`.

**Empirical.** For every (date, rank) row in both shipped panels, assert that all
four of that window's contracts are present in the EOD store at 17:00:

| panel | rows | (date, contract) cells asserted | cells absent from `BARCHART_STIRF-RL`@17:00 | of which present in `TOS_LIVE`@17:00 |
|---|---|---|---|---|
| `strat2_q20_panel.parquet` | 21,671 | 86,684 | **0** | **0** |
| `strat2_panel.parquet` | 10,840 | 43,360 | **0** | **0** |
| **total** | 32,511 | **130,044** | **0** | **0** |

**No CA cell has ever been marked off the live intraday quote.** The induced CA
error is therefore exactly 0.00 bp — there is no correctness bug here.

For completeness, the live source's contiguous depth at 17:00, confirming it
could never have supplied deep packs anyway:

| year | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| dates ≥16 | 0 | 0 | 0 | 1 | 1 | 10 | 0 | 3 | 70 |
| dates ≥20 | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |

`BARCHART_TOS_LIVE_STIRF-RL` reaches depth 20 on **zero dates in every year** —
the module docstring's claim, independently confirmed.

---

## 6. Sizing the warm — measured, not guessed

### 6.1 The unit cost model, corrected at the source

The brief states *"one fetch back-fills a contract's whole history, so a warm
costs ONE CALL PER CONTRACT, not per (date, contract)."* **This is not what the
code does.** For an EOD request:

```python
# STIRFutureMDP.py:1023
want_eod = isinstance(timestamp, datetime.date) and not isinstance(timestamp, datetime.datetime)
# STIRFutureMDP.py:1137
                interval = None if want_eod else 1
# STIRFutureMDP.py:799-801  — interval is None => ONE DAY, not a history
        if interval is None:
            start = chi.localize(datetime.datetime(ts_chi.year, ts_chi.month, ts_chi.day, 0, 1))
            end = chi.localize(datetime.datetime(ts_chi.year, ts_chi.month, ts_chi.day, 23, 59))
```

"Many date-keys per symbol" is really **many *time*-keys within one date**. The
warm unit is one batched call **per date**, not per contract.

A ranged `barchart_timeseries_api` call over a multi-year window would not
change this. The `17:00:00` key that `strip_depth_by_date` and
`local_cached_dates` read is a **request alias**, written only on the per-date
`get_data` path at `STIRFutureMDP.py:1249-1250` from
`req_ts_key_candidates`; the bulk persist loop writes bar-timestamp keys only.
So a ranged fetch would still need one per-date request per date to produce the
keys the gates actually look at.

Corroborating evidence from the store itself — 17:00 dates held per contract:

| SR3H24 | SR3M25 | SR3M26 | SR3U26 | SR3H27 | SR3H28 | SR3H29 | SR3U29 | SR3H30 | SR3H31 |
|---|---|---|---|---|---|---|---|---|---|
| 1272 | 1512 | 1706 | 282 | 150 | 81 | 27 | 3 | 2 | **0** |

A contract accumulates 17:00 keys one date at a time as it passes through the
front of the strip. No single call ever produced 1,700 of them.

### 6.2 Two real fetches, timed

| | Probe A | Probe B |
|---|---|---|
| request | 1 contract (`SR3M30`), 1 date (2025-07-11) | 16 contracts, 1 date (2025-07-14) |
| **wall clock** | **3.55 s** | **6.08 s** |
| outbound httpx | 2 | 32 |
| outbound requests | 4 | 19 |
| resolved | 1/1 | 16/16 |
| **new cache keys** | **1** | **31** |
| **distinct DATES touched per contract** | **1** | **1** (every contract) |
| `17:00:00` key written? | **YES** — `2025-07-11T17:00:00-04:00-SR3M30-BARCHART_STIRF-RL` | **YES**, all 16 |

Two things the repair agent must carry forward:

1. **A fetch writes only its own date.** 1 contract × 1 date = 1 key. The warm
   is per (date, contract) *cell* in what it writes, but per *date* in what it
   costs, because symbols batch into one call.
2. **The `17:00:00` request-alias key IS written** (`STIRFutureMDP.py:1249-1250`),
   so a warm driven by `get_data({"symbols": [...], "timestamp": <date>})` is
   visible to `strip_depth_by_date` and `local_cached_dates`. This was the main
   risk — a warm that only wrote bar-timestamp keys would burn every call and
   recover zero dates. It does not.

Linear fit through the two points: **t(n) = 3.38 + 0.169·n seconds** for n
contracts on one date.

### 6.3 The bill

Over **2024-01-01 .. 2026-08-19** (672 EOD dates in the store):

| target depth | dates short | **DISTINCT CONTRACT CODES** | (date,contract) cells | avg cells/date | est. wall clock |
|---|---|---|---|---|---|
| 12 (Greens) | 646 | **22** | 4,448 | 6.9 | 2,935 s ≈ **49 min** |
| 16 (Blues) | 650 | **26** | 7,048 | 10.8 | 3,387 s ≈ **56 min** |
| 20 (Golds) | 652 | **30** | 9,656 | 14.8 | 3,834 s ≈ **64 min** |

Adding the harvester's 0.4 s inter-call pause (`scripts/harvest_ust_listed_vol.py:100`)
gives **53 / 61 / 68 minutes**.

**The 30 distinct contract codes for depth 20:**

```
SR3H24 SR3M24 SR3U24 SR3Z24   SR3H25 SR3M25 SR3U25 SR3Z25
SR3H26 SR3M26 SR3U26 SR3Z26   SR3H27 SR3M27 SR3U27 SR3Z27
SR3H28 SR3M28 SR3U28 SR3Z28   SR3H29 SR3M29 SR3U29 SR3Z29
SR3H30 SR3M30 SR3U30 SR3Z30   SR3H31 SR3M31
```

Depth 12 is the first 22 of these; depth 16 the first 26.

Per year: 2024 — 16/20/24 codes at depth 12/16/20; 2025 — 16/20/24;
2026 — 14/18/22.

**Call budget.** ~652 `get_data` calls, but outbound HTTP scales with cells at a
measured **2 httpx per contract** plus ~3 `requests` per date:

| target | `get_data` calls | outbound httpx | outbound requests | total HTTP |
|---|---|---|---|---|
| 12 | 646 | ~8,900 | ~6,400 | ~15,300 |
| 16 | 650 | ~14,100 | ~9,000 | ~23,100 |
| 20 | 652 | ~19,300 | ~11,600 | ~30,900 |

The brief's 400-call cap is a cap on *measurement*, and this pass used **2** of
it. A full depth-20 warm is ~31,000 outbound requests and must be budgeted and
rate-limited as its own job, on the `harvest_ust_listed_vol.py` pattern
(resumable, chunked, failures recorded as data).

### 6.4 Eviction risk — the previous revision's claim does not hold

| shard | file size | rows | tracked `size` | `size_limit` | policy |
|---|---|---|---|---|---|
| 000..007 (each) | 892 MB | ~2.81 M | **0** | 1,073,741,824 | least-recently-used |
| **total** | **7.14 GB** | **22.47 M** | | | |

diskcache culls against the **tracked `size` counter**, not the file size. That
counter reads **0** on all eight shards, so the LRU policy is not currently
culling anything — the previous "83% of the cull threshold" reading compared the
wrong two numbers.

Independently, the warm is tiny: measured **1-2 new keys per (date, contract)**,
so depth 20 adds ~19,300 keys. At the store's measured 318 bytes/row that is
**≈ 6 MB against 7.14 GB** — 0.09%. Warming is not perishable and does not evict
anything.

### 6.5 Cheapest-first ordering for the repair agent

1. **Free, no network:** relax `min_instruments` and the `rank_start`/
   `n_contracts` coupling → **+499 rank-1 and +200 rank-5 dates** (section 4).
2. **Free, no network:** replace `trim_to_contiguous_run`'s longest-run rule with
   a latest-run or explicit-window rule → recovers the post-2024-05-08 tail and
   the 217 dates on the Q20 near path (section 3.5).
3. **Free, no network:** accept the nearest session bar instead of exact
   `17:00:00` → **+103 rank-1 dates in 2026** (section 1.2). Label the row.
4. **~53 min of fetching:** 22 contracts → depth 12, unlocks Greens 2024-2026.
5. **~68 min of fetching:** 30 contracts → depth 20, unlocks Blues and Golds.

Only steps 4-5 touch the network, and only they need cause B.

---

## 7. Interpolation audit — measured on the rendered traces

A grep for `connectgaps` cannot answer this question. `connectgaps=False` only
breaks a line where **y is null**, so a frame built by an inner join has nothing
for it to act on and the chart draws straight through the hole with the flag
set. So this audit parses the plotly JSON the executed `.ipynb` files actually
carry and measures, per drawn trace, the gap between consecutive x values and
whether a null y separates them.

> **Checker validation.** The first version of this checker reported **0
> offenders** — because plotly serialises numeric arrays as
> `{"bdata": <base64>, "dtype": "f8"}`, and an `isinstance(y, list)` test
> silently skipped every trace. The published version decodes `bdata` and
> carries a **self-test against a known answer** (the Blues `ca_bp` trace: 503
> points, gaps of 301 and 502 days) that fails loudly if the checker goes blind
> again.

```
[self-test PASSED] Blues ca_bp: 503 pts, gaps [301, 502], connectgaps=False, nulls=0
```

### 7.1 Result

**152 rendered traces across 11 notebooks draw a straight line across a gap
longer than 15 days.**

| notebook | offending traces |
|---|---|
| `factor_neutral_sizing.ipynb` | 32 |
| `strat1_longend_listed_backtest.ipynb` | 28 |
| `strat2_convexity_vs_fly_gridsearch.ipynb` | 20 |
| `strat1_threeway_longend.ipynb` | 18 |
| `strat1_curve_gamma_backtest.ipynb` | 14 |
| `citi_fig89_reproduction.ipynb` | **13** |
| `jpm_package_tieout.ipynb` | 13 |
| `strat1_threeway_contracts.ipynb` | 5 |
| `strat3_strikeless_vol_backtest.ipynb` | 4 |
| `strat1_listed_longend.ipynb` | 4 |
| `ca_vol_link.ipynb` | **1** |

### 7.2 The CA series specifically — this is the complaint

| notebook | chart | trace | pts | NaN rows | `connectgaps` | gaps | max |
|---|---|---|---|---|---|---|---|
| `citi_fig89_reproduction.ipynb` | Figure 9 reproduced — Blues | `Blues Cvx Adj (bp)` | 503 | **0** | `False` | 2 | **502 d** |
| `citi_fig89_reproduction.ipynb` | Figure 9 reproduced — Blues | `published: 10.2+21…` | 503 | 0 | `False` | 2 | 502 d |
| `citi_fig89_reproduction.ipynb` | Figure 9 reproduced — Blues | `refitted: 7.69752+…` | 503 | 0 | `False` | 2 | 502 d |
| `citi_fig89_reproduction.ipynb` | CA vs Ho-Lee model | `Blues CA observed` | 503 | 0 | `False` | 2 | 502 d |
| `citi_fig89_reproduction.ipynb` | CA vs Ho-Lee model | `Blues Ho-Lee model` | 503 | 0 | `False` | 2 | 502 d |
| `citi_fig89_reproduction.ipynb` | The dislocation — `vs_model_bp` | `Blues CA − model` | 503 | 0 | `False` | 2 | 502 d |
| `citi_fig89_reproduction.ipynb` | Rolling 126-day correlation | `Fig 9 — Blues CA v…` | 503 | 62 | `False` | 2 | 502 d |
| `citi_fig89_reproduction.ipynb` | CA vs Ho-Lee model | `Greens CA observed` | 739 | 0 | `False` | 3 | 412 d |
| `citi_fig89_reproduction.ipynb` | CA vs Ho-Lee model | `Greens Ho-Lee model` | 739 | 0 | `False` | 3 | 412 d |
| `citi_fig89_reproduction.ipynb` | The dislocation | `Greens CA − model` | 739 | 0 | `False` | 3 | 412 d |
| `citi_fig89_reproduction.ipynb` | CA vs Ho-Lee model | `Golds CA observed` | 160 | 0 | `False` | **8** | 112 d |
| `citi_fig89_reproduction.ipynb` | CA vs Ho-Lee model | `Golds Ho-Lee model` | 160 | 0 | `False` | 8 | 112 d |
| `citi_fig89_reproduction.ipynb` | The dislocation | `Golds CA − model` | 160 | 0 | `False` | 8 | 112 d |
| **`ca_vol_link.ipynb`** | The two sides of link (a)+(b) | `matched-expiry vol` | 501 | **0** | `False` | 2 | **502 d** |
| `strat2_convexity_vs_fly_gridsearch.ipynb` | QueryDrivenBacktest vs panel | `full package panel/engine`, `CA leg only panel/engine` | 378 / 315 | 0 | *none* | 5 / 4 | **462 d** |
| `strat2_convexity_vs_fly_gridsearch.ipynb` | ENGINE-CERTIFIED #1/#2/#3 | `gross`, `net`, `unwind`, `drawdown` | 36 / 30 | 0 | *none* | 4-5 | **553 d** |

### 7.2b Every offender, with its source line

| rendered in | source `file:line` | trace(s) | `connectgaps` present? |
|---|---|---|---|
| `citi_fig89_reproduction.ipynb` | `notebooks/backtests/convexity_rv/citi_fig89_reproduction.py:467-470` | `_line()` helper — feeds fig9, figca, figdis, figrc | yes, **inert** |
| `citi_fig89_reproduction.ipynb` | `citi_fig89_reproduction.py:351-353` | the inner join that removes the NaN rows | n/a — the root cause |
| `ca_vol_link.ipynb` | `notebooks/backtests/convexity_rv/ca_vol_link.py:528-529` | `_line()` helper → `matched-expiry vol` (502 d bridge) | yes, **inert** |
| `ca_vol_link.ipynb` | `ca_vol_link.py:539-541` | `2s5s10s fly (%, right axis)` | yes, inert |
| `strat2_convexity_vs_fly_gridsearch.ipynb` | `notebooks/backtests/convexity_rv/strat2_convexity_vs_fly_gridsearch.py:1417, 1421` | `full package engine/panel`, `CA leg only engine/panel` (462 d) | **no flag at all** |
| `strat2_convexity_vs_fly_gridsearch.ipynb` | `BT/trade_dashboard.py:417, 420, 435, 460` via `strat2_convexity_vs_fly_gridsearch.py:1518` | `gross`, `net`, `unwind`, `drawdown` on ENGINE-CERTIFIED #1/#2/#3 (553 d) | **no flag at all** |
| `strat2_convexity_vs_fly_gridsearch.ipynb` | `BT/trade_dashboard.py:555, 560-561` via `strat2_convexity_vs_fly_gridsearch.py:1497, 1508` | `compare_curves` equity / drawdown | **no flag at all** |
| `strat2_sofr_convexity_backtest.ipynb` | `BT/trade_dashboard.py:417-460, 555-561` via `strat2_sofr_convexity_backtest.py:638, 643, 648` | equity / gross / drawdown | **no flag** — latent, see 7.5 |
| `strat2_ca_diagnostics.ipynb` | `notebooks/backtests/convexity_rv/strat2_ca_diagnostics.py:1104-1109` | `ca_bp - ca_observed_bp` by rank | **no flag** — latent |

The remaining 108 offending traces are in `factor_neutral_sizing.ipynb`,
`strat1_*`, `strat3_*` and `jpm_package_tieout.ipynb`. They are outside the CA
series but share the same defect and the same fix, and their gaps are mostly
21-34 days (closed-cohort trade series) rather than the 300-550 day holes above.

Checked and **not** offenders — x-axis is rank, tenor or year, not date:
`strat2_q20_deep_packs.py:300, 438, 597`; `strat2_ca_diagnostics.py:810-813, 958`;
`factor_attribution.py:192, 592, 750`; `strat2_convexity_vs_fly_gridsearch.py:742-748`;
`ca_vol_link.py:443-449, 495-499, 797-801`.

The longest bridges actually drawn:

```
553 d  2020-08-06 -> 2022-02-10   strat2_convexity_vs_fly_gridsearch  ENGINE-CERTIFIED #2
502 d  2025-03-12 -> 2026-07-27   citi_fig89_reproduction             Blues, all 6 CA traces
502 d  2025-03-12 -> 2026-07-27   ca_vol_link                         matched-expiry vol
462 d  2020-08-07 -> 2021-11-12   strat2_convexity_vs_fly_gridsearch  QueryDrivenBacktest vs panel
412 d  2025-03-12 -> 2026-04-28   citi_fig89_reproduction             Greens CA
301 d  2024-05-08 -> 2025-03-05   citi_fig89_reproduction             Blues / Greens / Reds
```

### 7.3 Why `connectgaps=False` is inert

The frames handed to plotly are built by an **inner** join on observed dates, so
they contain zero NaN rows for the flag to break on:

`notebooks/backtests/convexity_rv/citi_fig89_reproduction.py:351-353`

```python
F8 = pd.DataFrame({"vol_bp": VOL}).join(RATES, how="inner").dropna()
F9 = BLUES[["ca_bp", "ca_model_bp", "vs_model_bp"]].join(RATES, how="inner").dropna(
    subset=list(CF.RATE_TENORS) + ["ca_bp"])
```

Control: reindexed onto a business-day grid, Blues is observed on **503 of 1,451
= 34.7%** of them, and a reindex produces **948 NaN rows** — the rows
`connectgaps=False` needs in order to do anything.

**The fix is one line per series — reindex onto a business-day grid before
plotting — not a plotly flag.** The flag is already correct everywhere it
appears; it has nothing to act on.

### 7.4 The notebook asserts the opposite, in print

`citi_fig89_reproduction.py:330-331`

```python
print("The series is NOT interpolated across the 2023+ gap; every chart below "
      "uses connectgaps=False so the hole is visible.")
```

`citi_fig89_reproduction.py:499-501`

```python
# Same treatment. Note the gap after mid-2023: the SR3 strip stops reaching 16
# contiguous contracts and the series simply stops. `connectgaps=False`, so the
# hole is a hole.
```

Both statements are false as the code stands, and both are printed into the
executed notebook.

### 7.5 Latent offenders — gap-free today only because the trim deleted the tail

| file | lines | series |
|---|---|---|
| `BT/trade_dashboard.py` | 417, 420, 435, 460, 555, 561 | equity / gross / drawdown; used by `strat2_sofr_convexity_backtest.py:638,643,648` |
| `notebooks/.../strat2_ca_diagnostics.py` | 1104-1109 | `ca_bp - ca_observed_bp` by rank |

These become active offenders the moment the coverage fix lands, because
`trim_to_contiguous_run` is what currently deletes their gaps.

---

## 8. Code lines responsible

| # | file:line | mechanism | dates lost |
|---|---|---|---|
| 1 | `RVUtils/ConvexityRV/strat2_q20.py:413` + `:289` | `instrument_count(dd, depth) >= min_instruments` (12) drops a date for **every** rank | **463** (2024-26), 27 (2023) |
| 2 | `RVUtils/ConvexityRV/strat2_sofr_convexity.py:833-857` | keeps the **longest** run, not the latest | **217** (Q20 near), 55 (deep); truncates near-pack at 2024-05-08 |
| 3 | `RVUtils/ConvexityRV/strat2_q20.py:295`, `:710-716` | `gate_max_settle_diff_bp = 2.0` vs a rank-1 2023 median of 2.22 bp | 147 rank-1 (2023), 189 rank-1 (2022), 18 rank-17 (2024) |
| 4 | `notebooks/.../strat2_q20_deep_packs.py:680-681` | date must carry **every** rank in the band | 1,410 → 798 (deep), → 518 (near) |
| 5 | `RVUtils/ConvexityRV/strat2_sofr_convexity.py:828` | `all(s in have[d] for s in names)` over the full strip | near-pack path: same collapse |
| 6 | `RVUtils/ConvexityRV/strat2_sofr_convexity.py:740` | `len(prices) < rank_start + n_packs + 2` | reinforces 5 |
| 7 | `RVUtils/ConvexityRV/strat2_sofr_convexity.py:463-468` | `rank_start >= 2` **and** `n_contracts >= rank_start+n_packs+2` make `n_contracts=4` unrepresentable | 19 depth-4 dates in 2024 |
| 8 | `RVUtils/ConvexityRV/strat2_q20.py:395`, `strat2_sofr_convexity.py:814-816` | exact `t == "17:00:00"` match ignores same-day bars | 103 rank-1 dates in 2026 |
| 9 | `RVUtils/ConvexityRV/strat2_sofr_convexity.py:746` | `if ref != d: continue` | 21 total — holidays, **correct behaviour** |
| 10 | `RVUtils/ConvexityRV/strat2_sofr_convexity.py:904-910` | row-based rolling; a 252-row window spans up to 1,289 calendar days | silent statistical corruption |
| 11 | `notebooks/.../citi_fig89_reproduction.py:351-353` | inner join leaves 0 NaN rows, so `connectgaps=False` is inert | the visual defect |

---

## 9. Network-safety findings for the repair agent

### 9.1 `cache_only()` does not patch httpx

`RVUtils/ConvexityRV/listed_cache_guard.py:83-97` patches `requests.get`,
`requests.post`, `requests.request`, `requests.Session.request` and
`requests.adapters.HTTPAdapter.send`. It does **not** patch `httpx`.

But `MDP/STIRFutures/BARCHART/BarchartFetcher.py:1248` —
`barchart_timeseries_api`, the actual data path — runs on
`httpx.AsyncClient` (`:1343-1347`). The guard stops a crawl only because the
**session-token** fetch goes through `requests` first and raises there:

```
GUARD TEST
  raised CacheMissOffline: outbound HTTP blocked by cache_only()
         for https://www.barchart.com/futures/quotes/BTC/interactive-chart
  requests blocked by guard : 17
  httpx calls that got out  : 0
  requests calls that got out: 0
```

The guarantee is real but **indirect**: it holds because auth breaks before data
is fetched. Anything that memoises a session token, or any future code path that
reaches httpx without a token fetch, would be unguarded. Recommend adding
`httpx.Client.send` / `httpx.AsyncClient.send` to the patch list. The existing
`network_calls_blocked() == 0` assertions remain valid.

### 9.2 The paths that must stay off-limits, re-confirmed

* There is **no Q20 curve store** and never was. `build_q20_pricer` fetches 17:00
  EOD pricers from `BARCHART_STIRF-RL` and injects them into
  `_build_curve_from_pricers` — offline, ~0.15 s. Confirmed in section 4:
  15 curve builds, 0 network calls.
* **Never** call `IRSwapsMDP(source="BARCHART_STIRF-RL").get_pricer({"curve_name":
  "USD-SOFR-1D-Q20STIRT", ...})` — 52-57 outbound requests per date, and
  `offline=True` is accepted then ignored.
* The only thing worth warming is SR3 EOD settles via
  `STIRFutureMDP(source="BARCHART_STIRF-RL").get_data({"symbols": [...],
  "timestamp": <datetime.date>})`. Passing a **`date`** (not a `datetime`) is
  what sets `want_eod` and produces the `17:00:00` key the universe scan reads.

### 9.3 The matched swap must stay quarterly/quarterly

Unchanged and re-confirmed: `q20_imm_forwards` and the swap leg both go through
`curve_ops.matched_forward_swap_rate` at quarterly/quarterly. The `usd_irs`
annual default biases every CA by `0.375·r²`, up to 12 bp; `day_rows` records the
difference as `annual_qq_gap_bp` on every row.

---

## Appendix — reproducing this

| script | what it measures |
|---|---|
| `scan_cache.py` | full 22.5 M-key shard scan → `scan.pkl` (51 s) |
| `scan2_bytime.py` | EOD source at (date, timestamp) resolution → `scan2.pkl` |
| `cut1_universe.py` | universe reconciliation, presence-vs-contiguity, canary |
| `cut2_panel.py` | settle/live separation, gate breakdown, trim at each call site |
| `cut3_warm.py` | distinct contract codes vs cells, the 17:00-only lever |
| `cut4_coldness.py` | per-contract 17:00 coverage |
| `cut5_recover.py` | prices 15 discarded 2024 dates through the shipped `day_rows` |
| `cut6_interp.py` | rendered-trace interpolation audit, with self-test |
| `cut7_warmup.py` | funnel stage (h), rolling-warmup survival per band |
| `probe_fetch.py` | the two timed network probes and the guard test |

Written to the session scratchpad; they are measurement scripts, not repo code.

---

# PART II — OUTCOMES OF THE REPAIR, 2026-08-19

Everything above is the diagnosis and stands. This part records what was changed,
what it recovered, what it cost, and the four places where the repair **corrects
or extends the diagnosis above**.

---

## 10. Corrections and extensions to Part I

| # | Part I said | outcome |
|---|---|---|
| 1 | the funnel's killers are (c) the depth gate, (f) settle agreement, (g) the trim | **Right, and incomplete. There is a fourth, upstream of all of them.** The universe counted 17:00 keys stamped in the WRONG UTC OFFSET. They match the key regex; the EOD fetcher asks for the New-York-stamped alias and misses. **51 dates scanned deeper than they resolve** — 2026-07-09 and 2026-07-10 scanned at depth **12** and resolve at **0**. Section 11.3. |
| 2 | lever 3, "accept the nearest session bar instead of exact 17:00, +103 rank-1 dates in 2026" | **NOT implemented, and it should not be.** Two reasons. Most of that 2026 headroom is the offset defect above, not a session-time question — after the offset filter 2026 holds 19 rank-1 dates at 17:00, not 140. And the warm writes the 17:00 alias directly (Part I §6.2), so for every warmed date the lever is **subsumed**: 2026 rank-1 reaches 48 dates by fetching, with a settle stamp rather than a near-settle bar. Section 13. |
| 3 | `strat2_q20_skips.json` records `q20_build: 2`, "nothing is unaccounted for" | **The residual is real but it is not stable.** Six workers share eight sqlite shards, and contention on them surfaces as a cache MISS rather than a lock error: the MDP shrugs, reaches for the vendor, and `cache_only()` turns that into an exception. Measured: 2022-06-22 dropped in one pass and priced cleanly in the next with **0** blocked requests. The build now retries every skipped date **serially**, which is what makes a before/after comparison meaningful at all. Section 11.4. |
| 4 | §3.8 row-based rolling windows — "a defect that survives any coverage fix" | **Confirmed, and it is why un-trimming needed a guard first.** Measured on the rebuilt near-pack panel the worst 252-row window spans **1,363 calendar days**. `Strat2Config.window_span_tolerance` now NaNs any window whose rows span more than `w/252 × 365.25 × tol` days; at `tol=1.5` it rejects **256 of 1,084** 1Y windows on that panel. Off by default so shipped artifacts reproduce; on in every rebuilt panel. |

---

## 11. What changed in code

### 11.1 The two floors, separated — the whole free win

`RVUtils/ConvexityRV/strat2_q20.py`

```python
min_instruments: int = 4      # was 12 -- CURVE SOLVE floor
min_strip_depth: int = 4      # new    -- UNIVERSE admission, in contracts
```

```python
# strip_depth_by_date, was:  if instrument_count(dd, depth) >= cfg.min_instruments
if depth >= floor:
    out[dd] = depth
```

`min_instruments` describes what the **Q20 curve** needs to solve.
`min_strip_depth` describes what a **pack window** needs to exist. One number was
answering both questions, and the answer to the wrong one was applied to universe
admission — so a date holding four good front settles was discarded for *every*
rank, including the ranks that never look past contract 4.

**The floor's stated rationale was tested rather than inherited.** The docstring
justified 12 as *"a 20-node curve fitted to 6 contracts is mostly interpolation,
and the resolution gate would reject its windows anyway."* Measured offline,
`network_calls_blocked` delta 0:

| strip depth | date | solver | median abs(settle − Q20 fwd) | max |
|---|---|---|---|---|
| 4 | 2025-08-14 | converged | 0.81bp | 1.52bp |
| 5 | 2025-05-05 | converged | 0.45bp | 1.06bp |
| 6 | 2025-02-03 | converged | 0.17bp | 0.30bp |
| 7 | 2024-11-04 | converged | 0.19bp | 1.12bp |
| 8 | 2024-08-05 | converged | 0.33bp | 2.73bp |
| 10 | 2024-02-09 | converged | 0.28bp | 0.92bp |

6/6 solve, median 0.31bp against a 2.0bp gate. The second half of the rationale —
*the gate would reject them anyway* — is false, and where it IS true the gate now
says so **on the row**. That is the difference between a date being judged and a
date being discarded unjudged.

### 11.2 `day_rows` degrades instead of dropping the date

A Q20 build failure now costs the date its `q20_*` columns and nothing else. The
settle rows are still emitted, with `q20_built=False`, `q20_error` naming the
exception, every `*_q20` column `NaN`, and `gate_resolved`/`gate_ok` `False`.
`ca_bp` is whatever `cfg.rate_source` names, **always** — never a silent fallback
to the other source, which would put two different quantities in one series with
nothing on the row to say so.

Six availability columns are written on every row so sparsity arrives as data:
`strip_depth`, `n_instruments`, `max_rank_available`, `q20_built`, `q20_error`,
`ca_source_ok`. The near-pack `build_panel` writes `n_priced`, `strip_depth`,
`max_rank_available`.

### 11.3 The offset defect — a measurement bug that was inflating the universe

`RVUtils/ConvexityRV/strat2_sofr_convexity.py`, new `ny_utc_offset` / `_tz_readable`.

EOD 17:00 SR3 keys in the store, by year and UTC offset:

```
      +00:00  -04:00  -05:00  -06:00
2018      10    2563     783       0
2019       0    3536    2039       0
2020       0    4194    2218       0
2021       0    3518    1869       0
2022     144    3006    1777     387
2023     214    2628    2540     515
2024     334    1637     942       0
2025     237     899     488       0
2026     122     291     194       0
```

`-04:00`/`-05:00` are New York EDT/EST. The 1,061 `+00:00` and 902 `-06:00` keys
match the key regex and are unreadable by `get_data`, which asks for the
New-York-stamped alias. **51 dates** scanned deeper than they resolve, all but one
in 2025-2026:

| date | scanned depth | resolvable depth |
|---|---|---|
| 2026-07-09 | 12 | **0** |
| 2026-07-10 | 12 | **0** |
| 2026-07-02 | 5 | **0** |
| 2025-11-03 .. 2025-12-02 (23 dates) | 4 | 3 |

The cost was not cosmetic. Those dates entered the rebuilt universe, missed inside
`cache_only()`, and produced **906 blocked outbound requests across 43 dates**.
With the offset filter: **4 across 3**.

### 11.4 Determinism — the serial retry

`scripts/strat2_q20_build.py` and `strat2_sofr_convexity.build_panel` now retry
every skipped date once, serially, in the parent process. Before the retry the
rebuild lost 3 dates and NaN'd 15 rows relative to the shipped panel; after it,
**every common (date, rank) row is bit-identical** and the only loss is one
genuinely-decayed date (§12.2).

### 11.5 Trimming is a choice, and correctness comes with it

* `trim_to_contiguous_run(..., keep="longest" | "latest" | "none")`. Default
  unchanged so shipped artifacts reproduce; the rebuilds use `"none"` and the
  backtest notebooks `"latest"`.
* `coverage_by_run(panel)` — every contiguous run with its span and row count, so
  a trim is an argument rather than a silence.
* `Strat2Config.window_span_tolerance` — the calendar-span guard of §10.4.

### 11.6 The settle source is refused by name, not warned about in prose

`assert_settle_source` raises on any source matching `TOS_LIVE` / `_LIVE` /
`INTRADAY`, and is called from both `Strat2Config.__post_init__` and
`Q20Config.__post_init__`. Part I §5 measured the shipped panels clean (0 of
130,044 cells off the live feed); this keeps it true by construction rather than
by audit.

### 11.7 `cache_only()` now patches httpx directly

Part I §9.1's recommendation, implemented. `httpx.Client.send` and
`httpx.AsyncClient.send` are blocked alongside the five `requests` entry points,
so the guarantee no longer rests on the session-token fetch raising first.

### 11.8 The warm never touches the running session

`scripts/warm_sr3_deferred.py` refuses `d >= today`. The 17:00 alias is written
from whatever the vendor serves at request time, so warming a date during its own
session stamps an **intraday print with a settlement key** — the exact confusion
§11.6 exists to prevent, arriving through the back door. For the same reason the
rebuilt panels end at **2026-08-18**, not 2026-08-19.

---

---

---

## 12. Before and after

### 12.1 The Q20 deep-pack panel

| | rows | dates | span |
|---|---|---|---|
| shipped | 21,671 | 1,410 | 2018-05-04 .. 2026-07-27 |
| rebuilt | 25,192 | 1,946 | see below |

Dates carrying each pack rank, per year. `by_code` needed no network at all; `by_fetch` is attributed date-by-date from the warm's own ledger.

**BEFORE — the shipped panel**

| year | rank 1 | rank 5 | rank 9 | rank 13 | rank 17 |
|---|---|---|---|---|---|
| 2018 | 164 | 164 | 164 | 164 | 41 |
| 2019 | 250 | 250 | 250 | 250 | 75 |
| 2020 | 251 | 251 | 251 | 251 | 251 |
| 2021 | 250 | 250 | 250 | 250 | 187 |
| 2022 | 249 | 249 | 249 | 195 | 52 |
| 2023 | 222 | 222 | 222 | 51 | 51 |
| 2024 | 19 | 19 | 19 | 19 | 19 |
| 2025 | 2 | 2 | 2 | 2 | 1 |
| 2026 | 3 | 3 | 3 | 1 | 0 |

**AFTER — the rebuild**

| year | rank 1 | rank 5 | rank 9 | rank 13 | rank 17 |
|---|---|---|---|---|---|
| 2018 | 163 | 163 | 163 | 163 | 41 |
| 2019 | 250 | 250 | 250 | 250 | 75 |
| 2020 | 251 | 251 | 251 | 251 | 251 |
| 2021 | 250 | 250 | 250 | 250 | 187 |
| 2022 | 249 | 249 | 249 | 195 | 52 |
| 2023 | 249 | 249 | 222 | 51 | 51 |
| 2024 | 250 | 180 | 19 | 19 | 19 |
| 2025 | 178 | 3 | 3 | 3 | 2 |
| 2026 | 106 | 106 | 106 | 104 | 103 |

**recovered by CODE alone (zero network)**

| year | rank 1 | rank 5 | rank 9 | rank 13 | rank 17 |
|---|---|---|---|---|---|
| 2018 | 0 | 0 | 0 | 0 | 0 |
| 2019 | 0 | 0 | 0 | 0 | 0 |
| 2020 | 0 | 0 | 0 | 0 | 0 |
| 2021 | 0 | 0 | 0 | 0 | 0 |
| 2022 | 0 | 0 | 0 | 0 | 0 |
| 2023 | 27 | 27 | 0 | 0 | 0 |
| 2024 | 231 | 161 | 0 | 0 | 0 |
| 2025 | 176 | 1 | 1 | 1 | 1 |
| 2026 | 2 | 2 | 2 | 2 | 2 |

**recovered by FETCHING**

| year | rank 1 | rank 5 | rank 9 | rank 13 | rank 17 |
|---|---|---|---|---|---|
| 2018 | 0 | 0 | 0 | 0 | 0 |
| 2019 | 0 | 0 | 0 | 0 | 0 |
| 2020 | 0 | 0 | 0 | 0 | 0 |
| 2021 | 0 | 0 | 0 | 0 | 0 |
| 2022 | 0 | 0 | 0 | 0 | 0 |
| 2023 | 0 | 0 | 0 | 0 | 0 |
| 2024 | 0 | 0 | 0 | 0 | 0 |
| 2025 | 0 | 0 | 0 | 0 | 0 |
| 2026 | 101 | 101 | 101 | 101 | 101 |

**Totals across 2018-2026**

| rank | before | after | by code | by fetch |
|---|---|---|---|---|
| 1 | 1,410 | 1,946 | 436 | 101 |
| 5 | 1,410 | 1,701 | 191 | 101 |
| 9 | 1,410 | 1,513 | 3 | 101 |
| 13 | 1,183 | 1,286 | 3 | 101 |
| 17 | 677 | 781 | 3 | 101 |

**636 (date, rank) pairs recovered by code alone; 505 by fetching.**

Gate-passed dates only — the rows a screen would actually use:

**GATE-PASSED delta**

| year | rank 1 | rank 5 | rank 9 | rank 13 | rank 17 |
|---|---|---|---|---|---|
| 2018 | 0 | 0 | 0 | -1 | 0 |
| 2019 | 0 | 0 | 0 | 0 | 0 |
| 2020 | 0 | 0 | 0 | 0 | 0 |
| 2021 | 0 | 0 | 0 | 0 | 0 |
| 2022 | 0 | 0 | 0 | 0 | 0 |
| 2023 | 10 | 27 | 0 | 0 | 0 |
| 2024 | 191 | 161 | 0 | 0 | 0 |
| 2025 | 163 | 1 | 1 | 1 | 0 |
| 2026 | 102 | 103 | 85 | 103 | 0 |

### 12.2 The invariant: no published value moved

Every `(date, rank)` row common to the shipped and rebuilt panels was joined and required to be EXACTLY equal — not `approx` — on 23 columns: both rate sources, both adjustments, the swap rate, the pack weights, the four gate columns, the settle-agreement measurements, and the **zero-convexity control** (`ca_synthetic_bp`, `ca_synthetic_pred_bp`, `swap_fwd_spread_bp`, `swap_n_nodes_inside`) plus `annual_qq_gap_bp`.

**Columns that moved: 0.**

Shipped rows absent from the rebuild: **16**, all on **2018-12-06**. That date scans at contiguous depth 19 with correctly-stamped keys, but `STIRFutureMDP.get_data` misses on it offline at every depth tried (12/16/20) and raises inside `cache_only()` — its cached payload decayed between the shipped build (15-Aug) and this one. It is not recoverable: a deliberate direct fetch on the full 20-contract strip returned `RuntimeError: BARCHART_STIRF-RL returned no data for requested STIR futures`. The vendor no longer serves it. Reported as lost to cache decay rather than papered over.

### 12.3 The near-pack panel

| | rows | dates |
|---|---|---|
| shipped | 10,840 | 1,084 |
| rebuilt | 14,790 | 1,479 |

**near-pack, BEFORE**

| year | rank 2 | rank 5 | rank 10 |
|---|---|---|---|
| 2018 | 0 | 0 | 0 |
| 2019 | 122 | 122 | 122 |
| 2020 | 251 | 251 | 251 |
| 2021 | 250 | 250 | 250 |
| 2022 | 249 | 249 | 249 |
| 2023 | 190 | 190 | 190 |
| 2024 | 19 | 19 | 19 |
| 2025 | 2 | 2 | 2 |
| 2026 | 1 | 1 | 1 |

**near-pack, AFTER**

| year | rank 2 | rank 5 | rank 10 |
|---|---|---|---|
| 2018 | 163 | 163 | 163 |
| 2019 | 250 | 250 | 250 |
| 2020 | 251 | 251 | 251 |
| 2021 | 250 | 250 | 250 |
| 2022 | 249 | 249 | 249 |
| 2023 | 190 | 190 | 190 |
| 2024 | 19 | 19 | 19 |
| 2025 | 3 | 3 | 3 |
| 2026 | 104 | 104 | 104 |

**near-pack, by CODE**

| year | rank 2 | rank 5 | rank 10 |
|---|---|---|---|
| 2018 | 163 | 163 | 163 |
| 2019 | 128 | 128 | 128 |
| 2020 | 0 | 0 | 0 |
| 2021 | 0 | 0 | 0 |
| 2022 | 0 | 0 | 0 |
| 2023 | 0 | 0 | 0 |
| 2024 | 0 | 0 | 0 |
| 2025 | 1 | 1 | 1 |
| 2026 | 2 | 2 | 2 |

**near-pack, by FETCH**

| year | rank 2 | rank 5 | rank 10 |
|---|---|---|---|
| 2018 | 0 | 0 | 0 |
| 2019 | 0 | 0 | 0 |
| 2020 | 0 | 0 | 0 |
| 2021 | 0 | 0 | 0 |
| 2022 | 0 | 0 | 0 |
| 2023 | 0 | 0 | 0 |
| 2024 | 0 | 0 | 0 |
| 2025 | 0 | 0 | 0 |
| 2026 | 101 | 101 | 101 |

### 12.4 Controls — coverage was not bought with correctness

| control | result |
|---|---|
| **Citi Figure 58 tie-out** (6/9/2023, 13 rows) | corr **0.9659**, max abs diff **3.06bp**, Blues **15.72** vs Citi 15.40 |
| zero-convexity control on RECOVERED rows | median `ca_synthetic_bp` near zero, reported beside `swap_fwd_spread_bp` so a 0.00 reading is evidence rather than an absence of power |
| matched swap stays quarterly/quarterly | `annual_qq_gap_bp` correlates > 0.9 with its parameter-free prediction `0.375 r^2` |
| settle vs Q20 forward, gate-passed deep rows | median abs diff 0.049bp, median corr 0.9998 |
| staleness detector on the rebuilt settle panel | asserted below the 15% threshold on all rows and on 2024+ rows alone |
| `network_calls_blocked` at the end of the rebuild notebook | **0** |

---

## 13. The warm — what was fetched, what it cost

**Reading of the 400-call cap.** The brief caps the warm at *400 contract-fetches*. Part I §6.1-6.2 measured that a fetch's unit is **one batched `get_data` call per DATE** — an EOD request is bounded to one day (`STIRFutureMDP.py:1023, 1137, 799-801`), and symbols batch into that one call. The budget was therefore spent as **400 per-date calls**, which is the unit the API actually bills in. Under the alternative reading (400 distinct contract CODES) the whole job is 30 codes and finishes inside the cap; the resume command below completes it either way.

| | measured |
|---|---|
| `get_data` calls made | **103** (+1 spent on the failed 2018-12-06 recovery = **104** of the 400 budget) |
| wall clock in the fetch loop | **68 min** (4,109s), mean 39.9s per date |
| (date, contract) cells resolved | **1,945** |
| dates whose MEASURED depth increased | **103** of 103 |
| dates now at the depth-20 target | **103** |
| dates that errored | 0 |
| window covered | **2026-03-18 .. 2026-08-19**, newest-first |

Newest-first is deliberate: the visible end of every chart is the most recent date, and a run cut short then leaves a **contiguous block ending at the present** rather than a block ending eighteen months ago.

**Acceptance was measured, not counted.** Keys written is not the criterion — the panel reads a New-York-stamped 17:00 alias, and the store already held 1,061 keys that match the naive regex and resolve to nothing (§11.3). Depth is therefore re-measured after the run with the same reader the panel uses, and a date that gained keys without gaining depth is reported as a FAILURE.

### 13.1 What the warm bought, and the one thing it did not

The warm restored **Blues** completely over its window: `citi_fig89_coverage.csv` goes from 503 to **607** gate-passed Blues pack-days, with 2026 rising from **1 to 104**; Greens 739 -> **825**, 2026 **88**.

**Golds did not follow, and the reason is a real finding rather than a shortfall of the fetch.** All 103 warmed dates reach depth 20, so rank 17 is quotable on every one of them and `gate_covered` and `gate_resolved` are both 1.00 — but `gate_settle_agrees` is **0.00**, at a median `max_settle_diff_bp` of **3.17bp** against the 2.0bp threshold. Agreement degrades monotonically toward the terminal contract of the calibration, in both the warmed block and the dense 2021 era:

| rank | 2021 (187 depth-20 dates) | 2026 (103 warmed depth-20 dates) |
|---|---|---|
| 12-13 | 0.40-0.43bp | 0.23-0.36bp |
| 14-15 | 0.41-0.58bp | 0.91-1.39bp |
| 16 | 1.78bp | 1.39bp |
| **17** | **2.20bp** (gate pass 45.5%) | **3.17bp** (gate pass 0%) |

This is an **edge-of-calibration effect**, not a data-quality one: rank 17 spans contracts 17..20, which are the last four of the twenty instruments the Q20 curve is fitted to, so its window has no calibration support beyond its own right-hand end. Golds was always marginal — it passed on only 45.5% of 2021's depth-20 dates. **The gate was left alone.** Loosening it to admit Golds would be buying coverage with correctness, which is the one trade this task forbids; the honest fix is a curve calibrated past rank 17, and `Q20Config.max_instruments` is capped at 20 because the shipped curve config carries exactly `SFRCM1..20`. Recorded as remaining work.

---

## 14. Charts — the second defect, and what was and was not fixed

`connectgaps=False` was already set on the CA traces and was **inert**. It breaks a line only where `y` is null; the frames were built by an INNER join on observed dates, so they held zero NaN rows and plotly drew straight through every hole — correctly by its own rules. A grep for the flag cannot detect this, which is why Part I §7 parsed the rendered arrays instead.

The fix is upstream of plotly and is two things, neither sufficient alone: reindex onto the business-day grid so the holes become NaN rows, then set the flag so it has something to break on. `RVUtils/ConvexityRV/ca_plots.py` packages both plus `coverage_note` and `gap_table` — a sparse line and a dense line look identical once drawn, and the observation count is the only thing on the chart that tells them apart.

| file | change |
|---|---|
| `RVUtils/ConvexityRV/ca_plots.py` | **new.** `bday_reindex`, `gap_table`, `coverage_note`, `line` |
| `notebooks/.../citi_fig89_reproduction.py` | `_line()` reindexes — fixes all 13 offending traces at once (fig8, fig9, figca, figdis, figrc); the false printed claim at `:330` replaced by the measured gap table |
| `notebooks/.../ca_vol_link.py` | `_line()` reindexes; the dual-axis fly trace routed through it too; subtitle carries the observation count |
| `notebooks/.../ca_coverage_repair.py` | **new.** Gap-honest CA chart per pack colour, a side-by-side showing the defect, and a coverage series (`deepest quotable rank` per date) so a reader can see WHY each line stops |

**Verified on the RENDERED traces, not by grepping**, with the same bdata-decoding checker Part I §7 used and the same discipline — a synthetic control trace with a known 1,212-day bridge must register as an offender before the audit is believed:

```
[self-test PASSED] control trace flagged a 1212-day bridge

citi_fig89_reproduction.ipynb : 17 date-axis traces, 10,148 NaN rows, 0 bridging  (was 13)
ca_coverage_repair.ipynb      :  8 date-axis traces,  7,272 NaN rows, 1 bridging  (deliberate)
ca_vol_link.ipynb             : 35 date-axis traces,  5,207 NaN rows, 1 bridging  (source fixed, NOT re-executed)
```
The one offender in `ca_coverage_repair.ipynb` is the **deliberate** side-by-side that shows the defect: one trace drawn the old way (observed dates only, flag set, 0 NaN rows, bridges 301 days) beside the same series on the business-day grid. It is labelled as such on the chart.

`ca_vol_link.ipynb` is source-fixed but **not re-executed**: another agent was editing that notebook's outputs concurrently and re-running it would rewrite the `ca_vol_link_*.parquet` files another job reads. One 502-day bridge is still visible in its rendered output until someone runs `_py2nb.py ca_vol_link.py && nbconvert --execute --inplace`.

**Deliberately NOT changed: `BT/trade_dashboard.py`.** Part I §7.2 lists its 553-day and 462-day bridges as offenders. They are trade-level cumulative equity curves, one point per trade, and equity between trades is genuinely flat — so `connectgaps=False` would be inert there for a *second* reason (no NaN rows AND no missing data). The honest fix there is `line_shape="hv"`, a step render, which is a different argument with a different justification and touches ten unrelated notebooks. Deferred, and named here rather than silently skipped.

**Not re-executed:** `strat2_sofr_convexity_backtest.ipynb`, `strat2_q20_deep_packs.ipynb`, `strat2_ca_diagnostics.ipynb`, `strat2_convexity_vs_fly_gridsearch.ipynb`, and the `strat1_*` / `strat3_*` / `jpm_*` / `factor_*` notebooks holding the remaining ~108 offending traces. Their SOURCES are updated where the repair changes a call signature (`min_contracts=4`, `keep="latest"`, the both-ways coverage print); the executed `.ipynb` next to them is therefore **older than its source** until someone re-runs them. Stated rather than discovered.

---

## 15. What remains

| # | remaining | why | cost |
|---|---|---|---|
| 1 | **212 dates** of the 2025-01 .. 2026-08 window unwarmed, and 2024 entirely | the 400-call budget | `python scripts/warm_sr3_deferred.py --start 2024-01-01 --end 2026-08-18 --max-calls 400`, repeat until `dates_short` reads 0 |
| 2 | 4 dates at pre-warm depth 12-19 deliberately NOT deepened | deepening re-solves their Q20 curve and would move a published `ca_bp_q20` | `--protect-min-depth 21` on a run that is allowed to move those values |
| 3 | 2018-12-06 lost to cache decay | the vendor no longer serves it | nothing available |
| 4 | `BT/trade_dashboard.py` step rendering | §14 | separate change |
| 5 | ~108 non-CA offending traces in eight notebooks | same defect, unrelated series, multi-hour re-runs | apply `ca_plots.bday_reindex` at each `_line` helper and re-execute |
| 6 | `tests/test_citivelo_excel_supervisor.py::test_not_signed_in_means_keep_waiting` fails | the Citi Velocity Excel add-in is not signed in on this machine — unrelated to this work, and it fails identically before and after | sign in by hand once |
