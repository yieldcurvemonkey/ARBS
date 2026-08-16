# REAL LISTED CONTRACT PANEL — DELIVERED

**196,560 rows · 228 contracts · 1,368 series · 2019-01-02..2026-08-14.** 21/21 tests pass; 10/11 mutations caught (11th is a proven no-op, pinned by its own test).

## 1. UNITS VERDICT (the gate — settled per root, per row)

**`ABPV` = annualised normal (Bachelier) bp/yr YIELD vol.** Confirmed three independent ways:
- **vs CM control** at matched TTE: ratio 0.999–1.000, med|diff| 0.11–0.26 bp (ladder-interp), corr 0.995–0.9999.
- **vs swaption cube**: US@30d/1Mx30Y 1.129 (corr 0.946), US@30d/1Mx20Y 1.090, US@90d/3Mx30Y 1.153, TY@30d/1Mx10Y 1.097, TY@90d/3Mx10Y 1.101 — the same 4–15% listed-over-OTC basis the CM panel documented, right sign (Treasury yield + delivery option).
- **cross-vendor, zero network**: QuikStrike ABPV vs the independent `sfr_rv_lab` Bachelier-implied ATM vol on matched (date, contract) — **ratio median 0.9998** [p05 0.985, p95 1.018], corr 0.9863, 3,975 rows / 14 contracts. Same merge shows **|my tte − their tte| = 0.00 days median AND max**, independently validating the expiry rule.

**`ATM` is NOT the same number in the two asset classes** — the most dangerous thing in the panel:

| root | ABPV/ATM median | meaning |
|---|---|---|
| SFR | **100.0000**, exact on **80.7%** of 15,204 rows | normal vol in **price points/yr** (≡ %/yr of rate). Affine `P=100−R`. Exact on **94–99%** per TTE bucket 0.08–2.5y; misses localised to the expiry tail (49% exact <0.08y) and newly-listed >3y end (4%), where the vendor uses different marks. `abpv_atm_scale` emits `scale_exact` to filter. |
| US | **860.6** → implied ModDur **11.62 y** | **lognormal price vol, decimal**. Ratio = `1e4/ModDur_ctd`. Store-measured CTD ModDur 11.58–11.63 y. |
| TY | **1703.9** → implied ModDur **5.87 y** | same; store-measured 5.85–5.91 y. |

Only 17% (US) / 7% (TY) of rows sit within 1% of their root's own median — the ratio genuinely *moves*, as a CTD duration should. **Pooling US with TY gives 1499 and a 6.67 y "duration" belonging to neither contract**; `units_report` keys on root for that reason.

**`25D_CALL`/`25D_PUT`: same units as that asset's ATM.** `25D_RR ≡ 25D_CALL − 25D_PUT` **exactly** — corr 1.000000, max|resid| **1.4e-17** on all three roots. Convert to bp/yr with the panel's own `ABPV/ATM` scale — **no external DV01 needed**.

**`25D_BF`: UNUSABLE as an independent quantity.** Naive identity fails (corr 0.20; residual **16%** SFR / **51%** US / **62%** TY of BF's own median). Anchor test explains it: `ATM* = mean(C,P) − BF` tracks quoted ATM in level (corr 0.934/0.974/0.967) but sits −0.26%/+0.49%/+0.60% of ATM off it with IQR ≈1% of ATM — about half of BF's size. It is a fly against an ATM anchor the panel doesn't carry. **Build flies from C/P/ATM instead**; the column is kept for provenance only.

## 2. COVERAGE (ragged — reported, not smoothed)

| root | contracts | ABPV rows | span | med rows/contract | alive/date | listing lead (med/max) | max TTE |
|---|---|---|---|---|---|---|---|
| SFR | 34 (34 quarterly) | 15,215 | 2022-01-21..2026-08-14 | 422 | 14 (max 16) | 1124 d / 1458 d | 3.99 y |
| US | 97 (33 qtr + 64 serial) | 8,440 | 2019-01-02..2026-08-14 | 82 | 4 (max 6) | 122 d / 241 d | 0.66 y |
| TY | 97 (33 qtr + 64 serial) | 8,845 | 2019-01-02..2026-08-14 | 84 | 5 (max 6) | 127 d / 241 d | 0.66 y |

Harvest cost: 1,524 planned series → 1,368 with data, 156 recorded empties, **2,208 s**. One call per contract-life, not per year — proven equivalent to chunking before relying on it (USM26 152 vs 152 rows, SFRM26 938 vs 938, max|diff| **0.0**, zero missing dates).

## 3. CM vs REAL — and what CM was hiding

Matched-TTE agreement is excellent (US_30 ratio 0.9992, med|diff| 0.64 bp; TY_30 1.0002/0.69 bp). **Serials densified the ladder enough that interpolation now beats contract-picking**: US_30 interp med|diff| **0.26** vs matched 0.64; TY_60 interp **0.11** vs 0.43 — i.e. CM's residual vs the real panel is expiry granularity, not a data difference.

**The ageing table is the term structure CM smoothed away** (real US ABPV vs same-day `US_30`):

| TTE bucket | n | ratio | med abs diff |
|---|---|---|---|
| 25–35 d | 514 | **1.002** | 0.19 bp |
| 50–75 d | 1,575 | 0.997 | 2.69 bp |
| 105–150 d | 1,390 | 1.068 | 5.43 bp |
| 150–250 d | 685 | **1.066** | 7.20 bp |

Agrees at 30 d to 0.2%, diverges to 6.6% as the contract ages — exactly as predicted. **55.9% of US observations lie outside CM's 30–90 d window entirely** (TTE p25 35 d, median 66 d, p75 105 d, max 241 d) and have no CM analogue at all. Ladder slopes 30→90 d match CM when the ladder is dense (2023-07-26: both +5.47 bp) and diverge when sparse (2019-10-04: CM −0.13 vs ladder −0.28).

## 4. THREE DATA FINDINGS

**(a) `definitions/USTFutureOptions.option_expiry_date` is defective — please route upstream.** Two failure modes, both caught by the vendor tie-out (last quote is expiry −1 bd on all 200 expired contracts):
- counts business days as Mon–Fri, ignoring holidays → **USM22/TYM22: returns 2022-05-27, correct is 2022-05-20** (Memorial Day); last quote 2022-05-19.
- missing the "if that Friday is not a business day, roll to the **prior business day**" clause → **USF21/TYF21: returns 2020-12-25, i.e. Christmas Day itself**; correct 2020-12-24. Same for USF22/TYF22 (2021-12-24 → 2021-12-23).

Fixed inside my harvester (`ust_expiry`, with `ust_expiry_legacy` retained so the gap stays measurable); **shared code untouched**. My own first correction over-rolled to the previous *Friday*, which put USF21 before its own last quote — a negative TTE, caught by the same tie-out and now a pinned mutation test. Calendar choice (GovernmentBond vs NYSE) is **immaterial** — identical on all 216 US/TY contracts 2019–2027, documented as a test rather than left unknown.

**(b) QuikStrike SR3 option history starts 2022-01-21**, despite the 2020 product launch — all pre-2022 quarterlies (SFRH19…SFRZ21) confirmed **empty**, recorded as data.

**(c) UST listing horizon ~4–8 months**: all 2027 UST contracts (USG27/USJ27/USK27/USM27, TYG27/TYJ27/TYK27/TYM27) empty. Far SFR (SFRU30/Z30, all *31) also empty.

## DELIVERABLES (absolute paths)

- `C:\Users\chris\clee\ARBS-cvx\scripts\harvest_listed_contract_vol.py`
- `C:\Users\chris\clee\ARBS-cvx\scripts\repair_listed_contract_expiries.py`
- `C:\Users\chris\clee\ARBS-cvx\scripts\verify_listed_contract_vol.py`
- `C:\Users\chris\clee\ARBS-cvx\notebooks\data\convexity_rv\listed_contract_vol.parquet`
- `C:\Users\chris\clee\ARBS-cvx\notebooks\data\convexity_rv\listed_contract_vol_coverage.json`
- `C:\Users\chris\clee\ARBS-cvx\notebooks\data\convexity_rv\listed_contract_vol_verification.json`
- `C:\Users\chris\clee\ARBS-cvx\RVUtils\ConvexityRV\listed_contracts.py`
- `C:\Users\chris\clee\ARBS-cvx\tests\test_convexity_rv_listed_contracts.py`

`listed_vol.py` re-exports all 16 public names (tail-only append; another agent was editing it concurrently, so the logic lives in `listed_contracts.py` with zero imports from `listed_vol`). CM API verified intact and `strat1_listed` / `strat1_threeway` / `strat1_curve_gamma` still import; 88 tests pass across the four convexity suites. `ust_listed_vol.parquet` untouched.