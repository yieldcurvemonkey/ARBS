# Does each Warsh speaker event carry more information? — verdict

Scored against the prediction table in
`2026-08-25-warsh-guidance-information-PREREG.md`, fixed before any outcome was
computed.

**Short answer: the claim is half right, the trader's objection fails on its own
two predictions, and the half of the claim that is wrong is the half that
matters for a position.**

Warsh events **move** the strip more. They **resolve** less. Those are different
things, and under guidance they moved together.

---

## The one-line result

> In the guidance era, event days resolved uncertainty about the *next* meetings
> **more** than non-event days did. Under Warsh the contrast **flips sign**:
> event days fail to resolve while non-event days still do.

| era | Δ degeneracy distance, t→t+5 | |
|---|---|---|
| | **event days** | **non-event days** |
| guidance (JPM, n 561 / 844) | **−0.50bp** | −0.24bp |
| guidance (FedLock, n 557 / 848) | **−0.48bp** | −0.26bp |
| Warsh (JPM, n 19 / 25) | **+0.09bp** | −0.73bp |
| Warsh (FedLock, n 13 / 31) | **+0.35bp** | −0.68bp |

Negative = the market became more decided. Both contrasts are measured **inside
the same window**, so neither can be a period effect. Mann-Whitney p 0.097 (JPM)
and 0.080 (FedLock) on the Warsh contrast.

---

## 1. The two positions are about different terms

Total information flow = `λ · E[I_e]` + the non-event channel, where `λ` is the
event arrival rate and `I_e = H_before − E[H_after]`.

* **The claim** — "each speaker event carries more marginal information" — is
  about **`E[I_e]`**, a per-event conditional.
* **The pushback** — "pure optionality… stays silent when it suits him… no
  information is information" — is about **`λ`** and the **non-event channel**.

`E[I_e]` can rise while `λ` falls. As literally stated the two positions are not
in contradiction, and "Warsh speaks less" would not refute the claim even if it
were true.

The pushback does contain one objection that bites, and it is not that one:

> **Selection.** If he speaks *because* there is news, `E[I_e | he spoke]` rises
> with no change in how informative his communication is.

That objection has an identification — and the data runs against it.

---

## 2. The premise is real, and larger than anyone claimed

Distance from an all-or-nothing outcome, `|jump − 25·round(jump/25)|`, averaged
over the next four live meetings. Zero = every meeting priced as a near-certainty;
12.5 = every meeting priced as a coin toss.

| | guidance (n 1,406) | Warsh (n 49) |
|---|---|---|
| next 4 meetings | 5.19bp | **8.09bp** |
| **front meeting** | 3.21bp | **8.29bp** |
| sd (next 4) | 2.56 | 0.88 |

The front meeting went from **3.21 to 8.29 of a possible 12.5** — a 2.6× rise,
with a *smaller* standard deviation, i.e. persistently undecided rather than
occasionally so. On the last session it reads **9.0**.

Citadel's *"September is a coin toss, containing very little asymmetry"* is not a
figure of speech. It is this number.

---

## 3. Events move the strip more — but only the ones he cannot choose

`|y|` = |change in the summed jump of a **fixed** meeting pair| across a ±1-day
window, in bp. Roll-safe: the pair is fixed strictly after the exit session, so
no meeting resolves inside any window (gate G-W2, 800 legs checked, 0 violations).

| | guidance | Warsh | |
|---|---|---|---|
| **scheduled** (JPM) | 4.05 (n 70) | **4.66** (n 6) | ↑ |
| **scheduled** (FedLock) | 3.70 (n 132) | **4.66** (n 6) | ↑ |
| discretionary (JPM) | 2.58 (n 438) | 2.36 (n 17) | ↓ |
| discretionary (FedLock) | 2.87 (n 569) | 2.42 (n 10) | ↓ |

Median placement of the six scheduled Warsh events in the guidance-era
distribution **of their own type**: **70th percentile** (JPM), **72nd**
(FedLock). No t-statistic is computed on six events; six percentiles are the
result.

**This pattern is the opposite of what selection predicts.** Selection says the
*discretionary* events — the ones he chooses — should be elevated, and the
scheduled ones flat, because he cannot filter a press conference. Observed:
scheduled up, discretionary flat-to-**down**.

So the objection that actually had teeth does not describe the data. **That is a
point for the claim**, and it is the strongest one available.

Caveat carried everywhere: **n = 6**. At the observed 2.65 scheduled events per
month, n = 20 is reached **2027-02-02** and n = 30 on **2027-05-28**. Before then
this cell is a description, not a test.

---

## 4. But the moves are not information

This is where the claim breaks, and it is the finding with the most support
behind it.

**The naive version overstates it.** Regressing the five-day change in degeneracy
distance on its own starting level plus a Warsh indicator gives a coefficient of
**+1.99bp (JPM, t 5.59)** and **+2.20bp (FedLock, t 5.67)**, p < 0.0001, and it
survives restricting the guidance side to the trailing 24 months (+1.96 / +2.24,
t 5.5). It also survives the obvious mechanical alternative: the mean-reversion
term is strongly negative (−0.28 to −0.34, t −9 to −12), and since the Warsh
window *starts* high at 8.5 of 12.5, reversion alone predicts a **fall**. The rise
is against that bias, not produced by it.

**That t is still not real, and the placebo says so.** Every Warsh event sits
inside one 2.3-month window, so the indicator is a **period dummy**, and 23
overlapping five-day windows are not 23 independent draws. Sliding a matched
49-business-day window through the guidance era and refitting:

| | placebo windows | placebo coef (mean, sd, max) | real | p(coef) | **p(\|t\|)** |
|---|---|---|---|---|---|
| JPM | 137 | −0.07, 0.63, +1.65 | +1.99 (t 5.59) | 0.0000 | **0.0365** |
| FedLock | 251 | −0.00, 0.76, +2.46 | +2.20 (t 5.67) | 0.0040 | **0.0359** |

Placebo `|t|` reaches 6.8–6.9 on windows where nothing happened. **The honest p is
≈ 0.036, not < 0.0001.** Reported because the specification that produced the
bigger number is the one a reader would otherwise take at face value.

**The test that is immune to all of this is the within-window contrast** in the
table at the top: inside the Warsh window, non-event days *do* resolve
uncertainty (−0.73 / −0.68) and event days do not (+0.09 / +0.35). A summer-wide
drift lifts both columns equally. It does not flip their order.

**What resolves and what does not.** The degeneracy measure reads meetings
strictly *after* `t+5`, so it never contains the meeting that just happened. That
makes this compatible with — and sharper than — `project_front_month_premium`,
which found the front-month premium dying **on** the decision day (+4.47bp
collapse). **The meeting that occurs resolves; the market's view of the meetings
after it gets less decided.** Which is precisely Citadel's reading: the presser
moved the strip because the reaction function got murkier, not clearer.

---

## 5. The trader's two signature predictions both fail

**λ — is he speaking less?** Season matching is not a refinement here; the window
is 18 June to 25 August and contains the summer recess and the run-up to Jackson
Hole. Matched to the same calendar window of prior years:

| corpus | matched years | Warsh 2026 | ratio | exact-Poisson p |
|---|---|---|---|---|
| JPM (dense 2023+) | 16, 20, 27 | **18** | 0.86 | **0.66** |
| FedLock | 19, 17, 12, 16, 19 | **10** | 0.60 | **0.14** |

JPM's 18 sits **between** 2023's 16 and 2024's 20. FedLock's 10 is the lowest of
six but does not reach significance. **"He stays silent when it suits him" is not
established once you control for the season.**

An earlier all-season read of this same data gave 10.11/mo → 7.94/mo and looked
like support. That was the artefact the season match was pre-committed to catch.
The two corpora also disagree by 44% on the Warsh count (18 vs 10), which is
measurement uncertainty on `λ` itself.

**Silence — does the strip do more work when he is quiet?** Runs of ≥3
consecutive non-speech business days, movement per business day inside the gap:

| corpus | guidance | Warsh |
|---|---|---|
| JPM | 2.00bp/day (n 99) | **1.76** (n 5) |
| FedLock | 1.81bp/day (n 111) | **1.65** (n 5) |

Down, not up. (Medians go the other way — 1.33 → 1.88 in both — on five gaps.)

---

## 6. Where the variance went

Share of squared daily path change, three buckets. Speaker days take precedence
over release days on collision, so the speaker bucket is the generous one.

| | guidance share | Warsh share | guidance RMS | Warsh RMS |
|---|---|---|---|---|
| speaker (JPM) | 43.6% | **57.7%** | 3.70bp | **2.81bp** |
| release | 39.5% | 17.8% | 4.09bp | 2.64bp |
| quiet | 17.0% | 24.5% | 2.66bp | 1.75bp |

**The share rose and the level fell.** Speaker days claim a bigger slice of a
smaller pie, and in absolute terms move the strip *less* than guidance-era
speaker days did. The shrinking pie is not a Warsh effect either — path RMS by
year runs 0.69 (2021), 5.30 (2022), 4.22, 3.47, 2.83, 1.87 (2026). It is a
four-year decline the Warsh window continues; against the trailing 24 months the
ratio is 0.77.

Warsh release days number 7 (JPM) / 9 (FedLock). Thin, and flagged.

---

## 7. Scorecard

| # | test | H1 claim | H2 trader | H3 opacity | observed | supports |
|---|---|---|---|---|---|---|
| T1 | λ, season-matched | ~flat | ↓ | ~flat | ~flat (p .66) / ↓ns (p .14) | H1, H3 |
| T2 | degeneracy | ↑ | ↑ | ↑ | **↑↑ 3.21→8.29 front** | premise, all |
| T3a | discretionary \|y\| | ↑ | ↑ | ↑ | **↓** | none |
| T3b | scheduled \|y\| | ↑ | ~flat | ↑ | **↑, 70–72nd pct** | H1, H3 |
| T4 | Δuncertainty | ↓ more | ~flat | **↑/flat** | **↑, contrast flips** | **H3** |
| T5 | event var share | ↑ | ↓ | ↑ | ↑ share, ↓ level | H1, H3 |
| T6 | silence gaps | ~flat | ↑ | ↑ | **↓** | H1 |

**H2 scores zero on its own two signature cells.** H1 takes T3b and T6. **H3 —
reaction-function opacity — is the only hypothesis that takes the cell everything
else hangs on.**

---

## 8. What to say to the trader

1. *"No information is information"* is a claim about `λ` and about silence. Both
   are measured here and **both go the wrong way for it**: season-matched speech
   frequency is statistically unchanged, and the strip moves **less** during
   Warsh silences than during guidance-era ones.
2. The objection with real force was **selection** — and it predicts the
   discretionary events light up while the scheduled ones don't. **The data shows
   the reverse.** On n = 6, with the decidability date on the record.
3. **He is nonetheless right that this isn't more information** — just not for
   the reason given. Warsh events move the strip and leave the *next* meetings
   less decided than before. The information content of an event is not its price
   impact, and under this chair the two have come apart.

## 9. What it means for a position

If events move price without resolving uncertainty, then **selling event
volatility is the wrong side of this regime** — the crush that pays for it is
what stopped happening. Owning gamma through set-piece events is better priced
than it was under guidance, and the event to fade is the *decision* (which does
resolve — the front-month premium dies on the day) rather than the *talk*.

That is a hypothesis this study supports but does not test. Testing it needs the
SR3 option surface across the same event windows, and it is the obvious next
piece of work.

---

## 10. Limits, stated plainly

* **2.3 months, 23–16 events, six of them scheduled.** Everything here is a
  description of one window. The scheduled cell becomes a test in Feb–May 2027.
* Warsh events are **not independent** — they overlap and share one macro
  backdrop. The period placebo is the correction; the honest p on the regression
  form is ≈0.036 and the within-window contrast is p ≈0.08–0.10.
* The two corpora disagree on the event count by 44%. Every headline is reported
  on both, and none of the conclusions flips between them.
* *"…and may not last"* is untestable on a 2.3-month regime. It is a live risk,
  not a finding.
