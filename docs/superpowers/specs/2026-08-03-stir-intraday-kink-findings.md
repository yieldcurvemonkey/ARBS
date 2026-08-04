# SR3 kink-fade at 4-hour frequency — findings

**Branch** `feat/stir-kink-intraday` · **2026-08-03**

## The question

> Does running the kink-fade on intraday signals, starting at 4-hour frequency,
> change the answer the EOD labs gave?

## The answer

**No, and the reason is arithmetic rather than empirical.**

A round trip costs **2.0bp at every frequency** — four contracts, half a tick
each way. `E|move|` does not: it shrinks with the horizon. So moving to intraday
holding periods makes the exact ratio that killed both EOD labs strictly worse.

**At 4 hours, with perfect foresight of the direction, nothing clears its cost:**

| horizon | 3m | 6m | 9m | 12m |
|---|---:|---:|---:|---:|
| **4h** | −1.58 | −1.13 | −0.75 | **−0.52** |
| 8h | −1.42 | −0.78 | −0.23 | +0.13 |
| 12h | −1.31 | −0.51 | +0.19 | +0.63 |
| 1d | −1.08 | +0.10 | +1.16 | +1.84 |
| 21d | +1.77 | +7.90 | +13.22 | +16.21 |

*(oracle net of the 2.0bp round trip, front legs 1–4, bounce-corrected)*

The best 4-hour structure in the complex is the 12m fly at **−0.52bp per trade**,
and it is an oracle — no signal can do better. This is a STOP on the same rule
both prior labs used.

## What the intraday data did buy

Three things the daily panel could not measure at all.

### 1. The minimum viable holding period

The shortest horizon at which each spacing's pond exceeds its boat:

| spacing | first horizon that clears 2.0bp |
|---|---|
| 3m | 10 days |
| 6m | 1 day |
| 9m | 12 hours |
| 12m | **8 hours** |

The daily lab's finest resolution was one day, so "somewhere under a day" was
the best answer available to it. The wider the fly the sooner it pays — the same
lever that made wider spacings better in the EOD lab, now expressed in time
rather than in basis points.

### 2. The cost model is honest, audited against the tape

Roll's effective spread, backed out of the lag-1 autocovariance of bar moves,
comes to **0.94–1.36bp** against the **2.0bp** the backtests charge. The round
trip was never a guess and it is, if anything, conservative.

### 3. The FOMC bar — the thesis's own mechanism, observed

The daily lab had one price per day, so a decision and the eight hours around it
were a single observation. The 12:00–16:00 CT bar contains the 13:00 CT
announcement.

| spacing | decision bar | ordinary bar | ratio | next bar | next-bar corr |
|---|---:|---:|---:|---:|---:|
| 6m | 2.99bp | 0.97 | **3.09×** | 0.85 | **+0.18** |
| 9m | 4.67bp | 1.33 | **3.52×** | 1.11 | **+0.24** |
| 12m | 5.59bp | 1.57 | **3.56×** | 1.47 | **+0.14** |

The decision moves the fly ~3.5× an ordinary bar — **and the move sticks.**
Next-bar correlation is *positive*, and the bar after a decision moves *less*
than an ordinary bar, not more. A dislocation being corrected would show
negative correlation and elevated follow-on movement. This is the opposite: the
meeting move is information being priced, and it is priced once.

**It also reproduces the daily lab from an unrelated direction.** Decision bars
are 0.56% of all bars carrying ~12× the variance of an ordinary one, so they
account for roughly **6.5%** of a fly's variance. The EOD lab put the FOMC
calendar at **1–6%** by decomposing variance onto meeting dates. Two
measurements sharing no code, no panel and no method, agreeing on the size.

## Execution timing is worth nothing — except one bar where it costs

Six panels from the identical bars, one per bar-of-day. Same structures, same
signal, same 21-day horizon, same cost; **only the execution time changes.**
Paired against the 12:00 CT settle bar across 27 identical configurations:

| hour CT | vs settle | paired t | NW t | % configs better |
|---|---:|---:|---:|---:|
| 00:00 | −0.14 | −0.51 | −0.47 | 40.7% |
| 04:00 | −0.33 | −1.78 | −1.28 | 33.3% |
| **08:00** | **−0.97** | **−4.54** | **−3.94** | **18.5%** |
| 16:00 | +0.05 | 0.17 | 0.13 | 37.0% |
| 20:00 | +0.19 | 0.59 | 0.60 | 44.4% |

**No hour beats the settle.** Executing at 08:00 CT — the US morning, spanning
the 08:30 ET releases and the most volatile bar of the day — costs **0.97bp per
trade**, about half a round trip. Trade away from the noisiest bar; nothing pays
you to seek it out.

The *unpaired* view of the same table showed a 0.88–1.83bp spread between best
and worst hour, which reads like a tradeable execution edge. Pairing shows it is
one bad bar plus noise. With ~65 trades per cell the unpaired comparison had no
power at all; the configurations pair exactly, and that is the whole difference.

## Three errors made and corrected, all of which flattered a conclusion

Recorded because the pattern matters more than the individual mistakes.

### `cm_slot` is the belly, not the front leg

`enumerate_structures` tags a structure with its **belly** slot
(`panel.py:118`), so for spacing `s` it runs `1+s .. max_slot−s`. Filtering
`cm_slot <= 4` as "front slots" keeps front legs 1–3 at 3m, 1–2 at 6m, only slot
1 at 9m, and **nothing at all at 12m** — the widest spacing silently vanished
from every table with no error. The front leg is `cm_slot − spacing`.

### The bounce correction assumed normality and inflated the answer

Removing a noise component from an observed move cannot make the move larger.
The first implementation converted a corrected variance through
`E|X| = sqrt(2/π)·sd` and produced a "corrected" oracle **above** the raw one.
That identity is Gaussian; this data has `E|X|/sd` of **0.59–0.69**, kurtosis
**26–136**, and 6–15% of bar moves exactly zero. Applied as a scale factor on
the measured mean absolute move instead, it is distribution-free and monotone.

### A falling variance ratio does not demonstrate reversion

The natural argument — pure bounce is a fixed noise term, so `VR(q)` must climb
back toward 1, and a `VR` that keeps falling is therefore real reversion — is
**wrong**. The noise enters `Var(r_q)` *once* regardless of `q` while the
denominator scales with `q`:

> `VR(q) = (q·σ²_w + 2σ²_u) / (q·(σ²_w + 2σ²_u))  →  σ²_w/(σ²_w + 2σ²_u)`

so pure bounce falls **monotonically to a constant well below 1**. A synthetic
pure-bounce series reproduces the same shape as the real data. The error was
caught by a unit test written to assert the claim, which failed.

The defensible test compares the observed profile against a pure-bounce
benchmark at the **same measured Roll spread**. Doing that changes the finding:

| spacing | gap at 2 bars | 6 | 12 | 30 | 126 |
|---|---:|---:|---:|---:|---:|
| 6m | −0.007 | +0.012 | +0.010 | +0.121 | +0.190 |
| 12m | −0.001 | −0.004 | −0.038 | +0.042 | +0.090 |

**Out to 12 bars (two days) the observed variance ratio is fully explained by
bid-ask bounce.** Genuine reversion only appears past ~30 bars, consistent with
the 28–53 day half-lives the daily lab fitted. The reversion is real; it does
not live at four hours, and the falling `VR` never showed that it did.

## Panel notes

**Coverage.** 8,602 bars × 44 contracts × 172,893 rows, 2021-01 → 2026-07,
Central. Six bars per session at 00/04/08/12/16/20 CT. Median 21 pre-accrual
contracts per bar.

**Reconciliation with the daily lab.** Aggregated to 21 days the intraday panel
is 1.32× the EOD panel on every spacing — a suspiciously constant ratio, and the
signature of a sample difference rather than noise. Barchart serves 240-minute
bars only from 2021-01 while the EOD panel starts 2018-01, so the intraday window
is dominated by the 2022–23 hiking cycle and excludes the quiet 2018–19 and ZIRP
2020 stretches. **On the common window the ratio is 1.045–1.105** (12m the
closest, 3m the loosest) and the level sds agree to a few percent. Every
comparison is run on the common window.

**The front contract is the stalest.** 34.1% of slot-1 bars close unchanged
against 10.8% at slot 16, despite slot 1 carrying ~10× the volume. Most of the
front contract's reference quarter is already fixed, so it trades heavily at a
price that cannot move. That is economics, not a data defect, but it means
front-slot packages carry a real staleness tax.

**Wide flies trended in this sample.** De-meaned against a large unconditional
drift (+0.14 to +0.21bp/day), `E[fwd|z>2] − E[fwd|z<−2]` is **negative at every
hour for the 6m fly** (reversion) and **positive at most hours for the 12m**
(momentum). Every backtest cell is negative gross as well as net — in 2021–2026
fading a wide fly's z-score lost money before costs. Consistent with the daily
lab's overall verdict and with the regime.

## ZQ was excluded, on data grounds

Fed Funds intraday coverage is 1,507 bars from 2025-02 at rank 1, 489 from
2025-11 at rank ~6, and **4 bars** for ZQZ27 — roughly 1–1.5 years, collapsing
past rank 6. Against a residual whose 21-day move was 1.52bp there is nothing to
measure, and an underpowered league table would be worse than none.

## What I would test next

1. **Finer bars for the FOMC event study only.** The 3.5× decision-bar move is
   the sharpest thing here, and a 4-hour bar smears the announcement across four
   hours of trading. 1- or 5-minute bars around 48 decisions is a small, cheap
   fetch and would separate the announcement jump from the afternoon around it.
2. **The 08:00 CT penalty deserves a mechanism.** It is worth half a round trip
   and is the only execution result with a real t-stat. Is it spread widening,
   adverse selection around the 08:30 releases, or a stale-leg artifact in the
   bar? Volume and staleness are already in the panel.
3. **Minimum holding period as a design constraint, not a finding.** 8h for 12m
   and 10 days for 3m is a usable rule for sizing any future STIR RV study's
   horizon before it is built.
4. **Do not re-run the fade at higher frequency.** The oracle forbids it, and
   the forbidding is arithmetic. Any future intraday work here should be about
   execution or event structure, not about holding period.
