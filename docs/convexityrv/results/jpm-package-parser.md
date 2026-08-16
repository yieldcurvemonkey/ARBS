All deliverables are built and verified. Final report:

---

# JPM U.S. Futures & Options Package → vol panels

## Deliverables (all absolute paths)

| what | path |
|---|---|
| locator + parsers | `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/jpm_package.py` |
| batch driver | `C:/Users/chris/clee/ARBS-cvx/scripts/parse_jpm_packages.py` |
| tests (35, mutation-checked) | `C:/Users/chris/clee/ARBS-cvx/tests/test_convexity_rv_jpm_package.py` |
| fixture builder | `C:/Users/chris/clee/ARBS-cvx/tests/fixtures/build_jpm_package_fixtures.py` |
| fixtures (gitignored) | `C:/Users/chris/clee/ARBS-cvx/tests/fixtures/jpm_packages/` (4 page-extracts, 15–575 kB) |

Parquets in `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/`:

| file | rows × cols |
|---|---|
| `jpm_pkg_treasury_vol.parquet` | 21,286 × 48 |
| `jpm_pkg_stir_vol.parquet` (ED 2019-2023 + SOFR 3M 2024-2026) | 18,914 × 48 |
| `jpm_pkg_midcurve_vol.parquet` | 18,879 × 48 |
| `jpm_pkg_otc_exchange_ratio.parquet` | 5,212 × 15 |
| `jpm_pkg_maturity_structure.parquet` | 5,118 × 14 |
| `jpm_pkg_skew.parquet` | 59,503 × 17 |
| `jpm_pkg_skew_atm.parquet` (ATM vol / vol-beta / futures px per panel) | 7,432 × 12 |
| `jpm_pkg_coverage.json` | 325 kB |

**7 files, not 3**, because routing is by **product**, not title: the v2025 generation prints the SOFR 3M table on a page mis-titled "Treasury Volatility Summary". Splitting on the title would have put SOFR rows in the Treasury panel. Also added `.gitignore` entry for `tests/fixtures/jpm_packages/` (licensed excerpts, regenerable).

## 1. Page map and how it drifts

Located by title text on every page (page 1 skipped — it is the TOC). Two document generations, split exactly at the corpus gap:

- **legacy** 2019-08-26 … 2024-11-15 as_of, **1,306 files**
- **v2025** 2024-12-11 … 2026-08-12 as_of, **410 files**

Page numbers drift 19→32 for the same report. Composition changes, with dates:

| report | last seen (as_of) | note |
|---|---|---|
| Eurodollar Volatility Summary | **2023-06-13** | 941 files |
| Eurodollar MidCurve Volatility Summary | **2023-04-14** (last non-empty); title to 2023-06-13 | 940 files |
| Eurodollar Volatility Skew Report | 2023-04-14 | |
| U.S. Treasuries Volatility Skew Report | **2024-11-15** | 1,197 files |
| Treasury OTC and Exchange Volatility | **2024-11-15** | 1,303 files |
| Volatility Summary – Other / – Currencies | **2024-11-15** | not parsed (see §6) |
| Short-Dated SOFR Swaption Volatility Report | from 2023-03-10 | not parsed |
| Treasury Volatility Summary | throughout | **2 pages** from 2024-12-11 (Treasury + SOFR) |
| Maturity Structure of Treasury Volatility | throughout | 1,706 files |

Corpus gap: **no files between as_of 2024-11-15 and 2024-12-11** (25 days). `2024-11-13` is a 36-page skeleton issue. Treasury Volatility Summary is absent on **49 dates** (full list in `page_absent_dates` in the coverage JSON; clusters are 2023-01-09..18, 2023-12-19..2024-01-26, plus singletons).

**No SOFR MidCurve successor ever appears.** I scanned every page of all 1,716 files for midcurve product banners — after 2023 the package simply stopped carrying midcurve vol.

## 2. Date convention — decided, then measured

Every row carries `as_of` (3:00pm NY close) **and** `business_date`. **Join on `as_of`.**

- legacy: cover `As of 3:00 pm …` / `For Business: …`; page header `08 June 2023` = as_of.
- v2025: cover has no dates; page header `Dec 11, 2024`, later labelled `Closes as Of: Aug 12, 2026` = as_of.
- **The filename is neither** — it disagrees with the cover's "For Business" on **273 of 1,306** legacy files (Friday packages saved Saturday; 338 Saturday-named files). Nothing joins on it.

Three independent measurements of the one-day question:

| test | correct (`as_of`) | shifted −1d | shifted +1d |
|---|---|---|---|
| `as_of + days_cal` == CME option expiry (n=21,286) | **99.986%** | 0.014% | 0.000% |
| `\|listed ATM×100 − JPM pct implied\| ≤ 0.005` | **41.7%** (median 0.0062, p95 0.11) | 2.10% (median 0.171) | 2.25% (median 0.169) |
| `ABPV/(JPM bp·√252)` IQR width | **0.054** | 0.076 | 0.074 |

The medians at ±1d are still ~1.5% of the vol level — this is exactly the "close enough to look right" failure the task warned about; only the dispersion gives it away.

## 3. Two corrections to the stated priors

**(a) The suggested self-check is false.** `Business Day(t) ≠ Implied Current(t−1)` — median |diff| 0.15 vs 0.07 same-day; only 21.6% within 0.05. `Business Day` is a **same-day** quantity: the same option re-implied on a 252-business-day clock instead of 365 calendar days. `Current × √(cal/bus) × √(252/365)` reproduces it to a **median 0.248% of the vol level, p90 1.83%** (n=18,749).

The check that *does* grade date handling is the printed `Change (1d)`:

| panel | `Chg(1d) == Cur(t) − Cur(t−1)` within 0.015 | median residual |
|---|---|---|
| treasury (n=19,616) | **98.03%** | 0.0000 |
| stir (n=16,790) | **98.53%** | 0.0000 |
| midcurve (n=5,446) | **99.63%** | 0.0000 |

**(b) The OTC page layout was misread in the brief.** It is not "Implied N/A, Historical 0.93, 6M Avg 1.02". It is a 3-column × 2-row table — columns `Current / 6M Avg / FV`, rows `Implied / Historical`, and **Historical has no FV cell** (5 cells, not 6). For 2023-06-08, 30s: Implied Current N/A, Implied 6M-Avg N/A, Implied FV 0.84; Historical Current 0.93, Historical 6M-Avg 1.02.

Answering the open question: **`Implied Current` and `Implied 6M Avg` are N/A on 100% of 1,303 dates, in all four panels** — they never populate. Only `implied_fv` (93.3–96.2%) and `historical_current`/`historical_avg` (99.3–99.5%; 71%/80% for the 2s panel) carry data.

## 4. Units (measured, not assumed)

- **`bp_*` is a DAILY basis-point yield vol**, not annualised. The Dec-2024 issues label it `Implied (bp) per day` outright. Against our own panel at lag 0: `ABPV/(bp·√252)` — **SFR median 0.9977, IQR (0.9932, 1.0024)**; TY 1.0128; US 1.0449 (the US/TY residual is JPM's own CTD-duration conversion). Multiply JPM bp by √252 to compare with ABPV.
- **`pct_*` for money-market products is a lognormal YIELD vol.** Independent proof from the midcurve page: `(100−F)bp × pct/100 / √252` reproduces the printed bp with **median ratio 1.0020, IQR (0.984, 1.023)** over 6,224 rows.
- **`pct_*` for Treasuries is the lognormal PRICE vol** and is *identical* to our `ATM`: `listed ATM×100 / JPM pct` median **0.9996**, IQR **(0.9990, 1.0004)**, i.e. agreement to the last printed digit. (Same underlying CME/QuikStrike settlement vols — a strong parse validation, a weak independence claim.)
- **v2025 money-market futures prices print in 32nds**, not hundredths. `96-06` for SFRU26 on 2026-08-12 = 96.1875; the same PDF's SOFR pack page prints **96.190** for that contract. Reading the dash as a decimal would be wrong by 0.13 and would never crash. Legacy Eurodollar pages print plain decimals (`99.880`). Raw string always retained in `futures_price_raw`.

## 5. Expiry-rule grading (both rules, as requested)

`as_of + days_cal` vs each rule, n = 21,286:

- corrected `ust_expiry`: **99.986%**
- repo `definitions/USTFutureOptions.option_expiry_date`: **96.350%**

On the **780 rows / 10 contracts** where the two disagree, JPM agrees with the corrected rule **99.62%** and with the repo rule **0.38%**:

| contract | corrected | repo rule | rows |
|---|---|---|---|
| USF21 / TYF21 / FVF21 | 2020-12-24 | **2020-12-25 (Christmas Day)** | 61 each |
| USF22 / TYF22 / FVF22 | 2021-12-23 | 2021-12-24 | 61 each |
| USM22 / TYM22 / FVM22 | 2022-05-20 | 2022-05-27 (Memorial Day counted) | 164/119/119 |
| USF27 | 2026-12-24 | **2026-12-25 (Christmas Day)** | 12 |

Independent confirmation of the defect, from a source that had nothing to do with how it was found.

## 6. Coverage and the complete failure list

1,716/1,716 files opened; **0 unexplained failures**.

| report | files with page | parsed ok | parsed_empty | failed | rows |
|---|---|---|---|---|---|
| Treasury Volatility Summary | 1,667 | 1,667 | 0 | 0 | 27,026 |
| Eurodollar Volatility Summary | 941 | 941 | 0 | 0 | 13,174 |
| Eurodollar MidCurve Vol Summary | 940 | 898 | **42** | 0 | 18,879 |
| Treasury OTC and Exchange Vol | 1,303 | 1,303 | 0 | 0 | 5,212 |
| Maturity Structure | 1,706 | 1,706 | 0 | 0 | 5,118 |
| U.S. Treasuries Vol Skew | 1,197 | 1,197 | 0 | 0 | 59,503 |

**That is the entire failure list:** 42 `parsed_empty` (2023 MidCurve pages where every cell is `-`), 5 OTC days with empty Implied/Historical stubs (2024-01-05..11, emitted as null rows, not failures), and 3 rows out of 21,286 where `days_cal` drops one short of the as_of gap. Nothing else.

**MidCurve — the highest-value page — is largely gone before the file ends.** Non-null implied vol by tenor:

| tenor | implied vol | historicals / futures px |
|---|---|---|
| ED 1Yr MidCurve | 2019-08-26 … **2022-12-15** | to 2023-04-14 |
| ED 2Yr MidCurve | 2019-08-26 … **2021-12-09** | to 2023-04-14 |
| ED 3Yr MidCurve | 2019-08-26 … **2020-12-09** | to 2023-04-14 |
| ED 4Yr MidCurve | 2019-08-26 … **2019-12-12** | to 2023-04-14 |
| ED 5Yr MidCurve | **never populated on any date** | to 2023-04-14 |

**Skew report was tractable** — table columns sit at x<335, chart tick labels at x≥335, so they separate cleanly. Parsed in full (59,503 strike rows + 7,432 caption rows with ATM vol, vol beta, futures price).

**Not parsed, deliberately:** `Volatility Summary – Other` / `– Currencies` are rotated-270° landscape pages with vertical header text — but I checked their contents and they carry **S&P, Gold, Silver, Crude, Nat Gas**, not Treasuries. **There is no Ultra Bond, Ultra 10Y or 2-Year Treasury anywhere in the package** — only Bond / Note / 5-Year Note, on any date, in either generation. Nothing was lost by skipping them.

## 7. Continuity

Nearest-expiry day-on-day relative move, median / p99 / count >100%: Bond 4.47% / 44.0% / 0 · Note 4.78% / 46.7% / 2 · 5Y 5.21% / 46.5% / 5 · ED 8.99% / 99.0% / 9 · SOFR 3M 9.62% / 167% / 8 · ED 1Yr MC 8.00% / 105% / 7. Every outlier inspected is March-2020 or a contract in its final days — no step changes, i.e. no wrong-column grabs. One genuine source outlier retained as printed: 2022-06-08 OTC 10s `implied_fv = 191.06` is what the PDF says.

## 8. Spot-checks, PDF text vs delivered parquet

**(1)** `2023-06-09` p26 — PDF: `Current 11.07 11.12 11.40 11.51 7.24 7.10 …` / `Futures Price 127-20 127-20 127-20 127-21 113-235 …`
Parquet: as_of 2023-06-08, business_date 2023-06-09, Treasury Bond Jul 23, `pct_impl_current=11.07`, `pct_impl_chg_1d=-0.34`, `pct_impl_business_day=11.24`, `bp_impl_current=5.8`, `days_cal/bus=15/10`, `futures_price_raw='127-20'` → 127.625, `bpv=185.68`. ✔

**(2)** `2019-08-27` p31 — PDF: `Current 73.54 75.53 72.02 70.51 66.23 79.15 …` / `Current 6.3 6.1 5.8 5.6 5.1 …` / `Futures Price 98.675 …`
Parquet: as_of 2019-08-26, ED 1Yr MidCurve Sep 19, `pct_impl_current=73.54`, `bp_impl_current=6.3`, `futures_price=98.675`, `bpv=25.0`. ✔

**(3)** `2026-08-13` p31 — PDF (positional; the plain text dump is scrambled in v2025): `Secured ON Financing Rate 3M` / `Aug 26 Sep 26 Oct 26 …` / `Current 12.19 11.21 17.54 …` / `Current 2.9 2.7 4.4 …` / `Futures Price 96-06 96-06 96-01+ …`
Parquet (`jpm_pkg_stir_vol`): as_of 2026-08-12, business_date 2026-08-13, `pct_impl_current=12.19`, `bp_impl_current=2.9`, `futures_price_raw='96-06'` → 96.1875, `days_cal/bus=2/2`. ✔

## 9. Tests

`pytest tests/test_convexity_rv_jpm_package.py` → **35 passed**. Every expected number is quoted from the PDF in the assertion.

Mutation-checked, 12 mutants: **10 caught**, 2 verified *equivalent* (not gaps) — `base = as_of.year//100*100 → 1900` is neutralised by the roll-forward branch, and the `len(cols) >= 3` threshold is inert because the header row is chosen by max column count. The century branch is dead for a 2019–2026 archive, so I added a direct unit test for it; that mutant is now caught. Caught mutants include: row-label stem, 32nds half-tick, glued-`$` split, row `ytol`, glued `Jan25` header, required-metric guard, empty-page guard, OTC column anchors, and the banner-order assertion.

That last one mattered: my first contiguity check accepted a *permuted* product assignment (Bond numbers under the Note heading) because a permutation is still contiguous. The mutation test caught it and `_assign_columns` now asserts column order matches banner order.

## Design notes worth carrying forward

- Parsing is positional (`get_text("words")` + y-clustering). The v2025 plain-text dump interleaves row labels *between* values — any `split("\n")` approach silently mis-columns those files.
- Row rule: take the **last `n_cols` value-like tokens**; everything left is the label. Survives labels starting with digits (`10 day`, `3 Year High`), `*` markers as separate words, and glued cells (`$167.35$167.35`).
- Hard-fail everywhere: `JpmParseError` carries (file, page, row label, reason); `JpmEmptyPage` subclasses it so "legitimately all dashes" is counted separately from "layout broke". A `_REQUIRED_METRICS` check catches silent section renames — it is what caught the Dec-2024 `Implied (bp) per day` / `Change(5d)` drift, which otherwise would have dropped the whole basis-point block without a single error.
- `hist_from_old_otr` is attributed **per column**, not per page (verified on 2021-06-16, where the `*` covers Bond's 10/20/50-day bp rows and Note/5Y's 20/50-day rows).