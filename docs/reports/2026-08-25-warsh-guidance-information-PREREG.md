# Does each Warsh speaker event carry more information? — pre-registration

Written **before** any outcome was computed. Only the event counts in §0 were
known at the time of writing, and they are reported there because they decide
what is answerable at all.

The desk's own record justifies the discipline: on the last comparable review,
**12 of 12** post-hoc defects favoured the hypothesis under test
(`feedback_adversarial_review_flatters`).

---

## 0. What is already known, before any test

Era boundary is the **June-2026 FOMC**: the guidance drop was announced *at* that
meeting, so July-2026 is the first meeting priced knowing there is no guidance
(`project_front_month_premium`).

| | guidance era | Warsh era |
|---|---|---|
| span | 64.6 months | **2.3 months** |
| discretionary speeches, JPM | 10.11/mo | 7.94/mo (**n = 18**) |
| discretionary speeches, FedLock | 9.85/mo | 4.91/mo (**n = 10**) |
| scheduled events | 2.26/mo | 2.65/mo (**n = 6**) |

Two consequences fixed in advance:

* **The scheduled-event test — the one that answers the selection objection — is
  not decidable now at n = 6.** Its result will be reported as a placement table,
  never as a t-statistic.
* The two corpora disagree by **44%** on how many discretionary events the Warsh
  window contains (18 vs 10). That disagreement is measurement uncertainty on the
  arrival rate itself and is reported as a finding, not smoothed away.

---

## 1. The claim, decomposed

> "Under Warsh, forward guidance is gone, so each speaker event carries more
> marginal information than under the old regime."

Let `P_t` be the market's distribution over the policy path.

* `H_t` — its uncertainty at time `t`
* `I_e` — information delivered by event `e` = `H_before − E[H_after]`
* `λ` — event arrival rate

Total information flow per unit time = `λ · E[I_e]` + the non-event channel.

**The claim is about `E[I_e]`.** It is a statement about the conditional,
per-event quantity.

The pushback —

> "warsh's lack of forward guidance is pure optionality... he gets to decide what
> is real news and just stays silent when it suits him... no information is
> information!"

— is a statement about **`λ` (down)** and about **the non-event channel (up)**.

**These are different terms of the same decomposition, and both can hold at
once.** `E[I_e]` can rise while `λ` falls and `λ·E[I_e]` stays flat. So as
literally stated, the two positions are not in contradiction, and a test that
finds "Warsh speaks less" does not touch the claim.

The pushback does contain one objection that **is** a genuine challenge to the
claim, and it is not the one it appears to be:

> **Selection.** If Warsh speaks *because* there is news, then `E[I_e | he spoke]`
> rises mechanically with no change in how informative his communication is. The
> conditional is inflated by the filter, not by the regime.

That is the objection worth testing, and it has an identification.

---

## 2. Three hypotheses

**H1 — the claim.** Guidance pinned the path; with it gone the prior is wide, so
each event has more entropy available to remove and removes more of it.

**H2 — the trader.** Optionality. Fewer events, selected; the information moves
into silence and into the non-event channel.

**H3 — Citadel (2026-08-25).** *"the market response to Chair Warsh's presser
likely reflects a lack of clarity around his reaction function."* Events move the
strip because the market is **confused**, not because it **learned**. A big price
move with no reduction in uncertainty is noise, not information.

H3 is not a variant of H2. It agrees with H1 that events move price a lot, and
disagrees about whether that constitutes information.

---

## 3. Prediction table — fixed in advance

| # | test | H1 (claim) | H2 (trader) | H3 (opacity) |
|---|---|---|---|---|
| T1 | arrival rate `λ`, season-matched | ~flat | **↓** | ~flat |
| T2 | premise: path distance-from-degeneracy | ↑ | ↑ | ↑ |
| T3a | \|Δpath\| at **discretionary** events | ↑ | ↑ *(selection)* | ↑ |
| T3b | \|Δpath\| at **scheduled** events | **↑** | **~flat** | ↑ |
| T4 | Δuncertainty at events, DiD vs guidance era | **↓ more** | ~flat | **↑ / flat** |
| T5 | event share of path variance (3 buckets) | ↑ | **↓** | ↑ |
| T6 | silence-gap variance vs matched guidance gaps | ~flat | **↑** | ↑ |

**The two cells that decide it:**

* **T3b separates H1 from H2.** On scheduled events Warsh *cannot* filter — he has
  to appear at the presser. If the per-event response is elevated there too, the
  selection story does not explain it. At n = 6 this is a placement table, and the
  honest output is the date at which it becomes decidable.
* **T4 separates H1 from H3.** Information means uncertainty falls. Confusion
  means it does not. Measured as a difference-in-differences against guidance-era
  events of the same type, because event premium decays through an event even when
  zero information arrives — the calendar day passes either way. Measured at
  `t+0` **and** `t+1..t+5`, because opacity predicts uncertainty *elevated after*
  the event, which is invisible at the close.

T1 and T6 are H2's own predictions and are given a fair test.

---

## 4. Measurement decisions fixed in advance

* **"Uncertainty" is not ladder dispersion.** `jump_bp` is `E[Δrate]`, a point
  estimate; its dispersion across meetings is the shape of the *mean path*, not
  uncertainty about it. The measure used is **distance from degeneracy** —
  `|jump − nearest multiple of 25|` — which is what `project_front_month_premium`
  already computed, and it is called that, not entropy. Corroborated against SR3
  front-contract ATM implied vol where the cache serves it.
* **T1 must be season-matched.** June–August contains recess and the pre-Jackson
  Hole period. The 64.6-month all-season base rate is the wrong comparator; the
  matched windows are Jun-18–Aug-25 of prior years, and for JPM only 2023+, where
  the corpus is dense.
* **T5 needs three buckets — speaker event / data release / quiet.** The Citadel
  note states the Warsh window's data ran dovish (payroll misses and revisions,
  two better inflation prints). A two-bucket split books data-day variance into
  "non-event" and manufactures support for H2. If the quiet bucket is near-empty
  once event and release days are removed from ~48 business days, that is reported
  rather than a degenerate share.
* **No t-statistic will be computed on the six scheduled Warsh events.**

---

## 5. What cannot be tested

*"and may not last"* is a claim about the future of a 2.3-month-old regime. There
is no sample. It is recorded as an open risk, not tested.

---

## 6. Existing evidence, declared up front

`project_front_month_premium`, already verified in-house, bears directly on T4 and
is **not** neutral between the hypotheses:

| sample | n | premium at T−1 | on-the-day collapse |
|---|---|---|---|
| guidance era, HOLDs | 14 | −0.22bp | +0.26bp |
| Warsh no-guidance, HOLDs | 2 | **+4.51bp** | **+4.47bp** |

Uncertainty survives to T−1 and **dies at the event**. That is information
delivered *at* the event — the opposite of "the silence does the work." Two
caveats attach and are carried wherever this is cited: these are **decisions, not
speeches**, and June-26 was priced under old-regime expectations, so **n = 1**
meeting was ever priced knowing there is no guidance.
