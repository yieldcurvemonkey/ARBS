# Does Fed *language* move the priced path? — Study A, and the Jackson Hole answer

**2026-08-25 · branch `feat/fedspeak-event-conditioning` · worktree `ARBS-fec`**

Implements the quant's brief (`STUDY_fedspeak_event_conditioning.md`). Study A
was to be run first because it can end the programme for the price of one
regression. It was, and it does — but not in the way the brief expected.

---

## 1. The Jackson Hole question, answered before any new study

The ask was for a study supporting a **receiver into Jackson Hole** — long
SR3H27, on the thesis that the July/August soft patch shows up in Warsh's tone on
28 August.

That needs no new study, only the arithmetic of the lead this desk already
measured. At a lead of `L` weeks, the data surfacing in Fed language on date `D`
is the surprise composite as it stood `L` weeks before `D`:

| date | z at L=5 | z at L=11 | z at L=14 |
|---|---|---|---|
| **2026-08-28 — Jackson Hole** | **+0.262** | **+0.580** | **+0.632** |
| 2026-09-16 — FOMC | −0.275 | +0.578 | **+1.164** |
| 2026-10-28 — FOMC | −0.373 | −0.275 | −0.001 |
| 2026-12-09 — FOMC | −0.373 | −0.373 | −0.373 |

**Every lead is positive at Jackson Hole, including JWS's own five weeks.** At
the measured 11–14 weeks the data reaching Fed language on Friday is
mid-May to mid-June, which was the tail of the hot run. The September FOMC is
hotter still (+1.164 at L=14).

The soft patch turns the reading negative only from **late October**, and by
9 December every lead agrees. **If the lead study is worth believing, the
receiver is into December — and December is where the pay leg of a 2×1 sits.**

This confirms the quant's reading and strengthens it: the trade is not merely
unsupported at the measured lead, it is unsupported at *JWS's own* lead too.

---

## 2. Study A — the link nobody had measured

The chain is `data → Fed language → price`. #490 measured link 1 (real).
#497/#501 measured end-to-end (dead). Nobody had measured link 2 alone.

**Design.** Regress the event-window change in the **priced meeting step** on the
contemporaneous change in the Fed sentiment index, at communication events only.

* `y` is the priced meeting step from `RVUtils.MeetingProb.meeting_ladder` — a
  CME-FedWatch anchor-walk on ZQ settles. *(The brief supposed a joint
  least-squares ZQ/SR3 fit; no such object exists in the repo. The ladder's first
  four jumps tie to the ZQQ26→ZQG27 settle spread to 0.3bp, the residual being
  intra-month day-weighting.)*
* `y` is defined on a **fixed pair of meetings** — the two whose effective date
  is strictly after the exit session, matched by effective date on both marks.
  At an FOMC event a meeting resolves inside the window; differencing "the next
  two" would measure the roll, and on a decision day the roll *is* the decision.
* `x` is the daily point-in-time sentiment index. Daily, not weekly: a weekly
  index cannot move inside a three-day window. Measured, it moves on 60.4% of
  days.

### Result

| arm | n | β (bp/sd) | HC3 t | R² | bootstrap 95% CI | verdict |
|---|---|---|---|---|---|---|
| JPM (tradeable) | 53 | **+2.150** | +0.46 | 0.016 | [−4.50, +6.84] | DEAD |
| FedLock 2021+ (association) | 98 | **+2.159** | +1.18 | 0.014 | [−1.34, +5.95] | DEAD |
| FedLock, JPM window | 44 | **+1.686** | +0.70 | 0.009 | [−4.74, +5.92] | DEAD |

Two independent judge models, one shared event calendar, the same sign and
near-identical magnitude — and **not one confidence interval excludes zero.**

### What makes this different from the four PRs before it

**The effect is not too small to trade.** A typical set-piece event moves the
index about half a standard deviation, so the fitted path move is **+0.985bp**
(JPM), +0.765bp (FedLock), +0.759bp (window) per event, and **+1.362bp** at a
90th-percentile event — against a **0.50bp** SR3 round trip, at **19.0** such
events a year.

Every earlier study died at the cost line. **This one clears it and dies at the
standard error.**

**And the sample cannot be relieved.** To reach |t| = 2 at the measured slope and
noise would take **983 events — 49 more years** on the tradeable arm, and 280
events (**9 more years**) even on the un-gateable FedLock arm. Nor can it be
extended backwards: the FOMC registry the ladder needs starts **2021-01-27**, and
before that an unregistered meeting month is silently treated as an anchor month,
which *corrupts* rather than truncates the bootstrap.

So the honest verdict is **not** the brief's expected "coefficient ≈ 0, stop". It
is: *positive, consistent, economically meaningful if real, and unresolvable on
any data that will exist this decade.*

### The decision confound, measured

On the same window the decision-day slope is **+29.271** against **+1.686** at
non-decision events — a ratio of **17.4**. Pooling them would have produced a
large, apparently strong coefficient that is a fact about rate *decisions*, not
about language. That is why the primary cut is set-piece **non-decision** events
(minutes, press conferences, semiannual testimony, Jackson Hole).

---

## 3. The regime reading of #491 — tested, and it does not survive

#491 found the lead replicates recently and dies over 21 years; the default
reading is overfitting. The competing reading is that the trade needs
front-meeting premium, which forward guidance removed — so a long sample pools a
regime where the mechanism is impossible with one where it might work.

| regime | joint weeks | argmax lag | corr at argmax |
|---|---|---|---|
| pre-statement (1985–1994) | 0 | — | not measurable |
| statement, no projections (1994–2003) | 0 | — | not measurable |
| balance of risks (2003–2011) | 369 | **−9w** | **0.0879** |
| dots / guidance (2012–2025) | 730 | **+2w** | **0.1054** |
| no guidance (2026–) | 32 | — | not measurable |

**It tracks nothing.** The correlation is the same size in both measurable
regimes and the argmax lag *flips sign* between them. The two earliest regimes
are unmeasurable — and not for want of Fedspeak: FedLock carries 307 dated
speeches in the 1990s, but Citi's daily surprise sub-indices begin in 2003, so no
joint week can exist before then. **#491's overfitting reading stands.**

---

## 4. Two things the brief got wrong, corrected here

1. **There is no joint least-squares ZQ/SR3 ladder.** The only `least_squares` in
   `RVUtils.MeetingProb` fits per-meeting *probabilities* to SR3 option premiums
   with the ZQ support held fixed. The priced step is `MeetingLattice.jump_bp`
   from a deterministic anchor-walk.
2. **The event universe had to be set-piece.** Using every scored communication
   made almost every business day an event day and collapsed the matched
   non-event-day pool to 154 — the null could not be computed. Restricting to the
   ~19/yr set-piece calendar restores it *and* sharpens the question, because an
   ordinary speech day then becomes an eligible control.

A third correction was found while building: the JPM corpus carries **no field
identifying the kind of communication**, so its set-piece universe was silently
decisions-and-minutes-only. That made the JPM slope read **−6.22** against
FedLock's +2.01 — a difference of *universe* masquerading as a difference of
*judge*. With one shared calendar (dates from FedLock's `speech_type`, which is a
fact, not a score) all three arms read +1.7 to +2.2.

---

## 5. What shipped

```
notebooks/rv/
  fed_event_conditioning.py            data, panel, Study A, gates, regime split
  fed_event_conditioning_run.py        headless runner (~2 min)
  fed_event_conditioning_rv.{py,ipynb} the study      (50/50 figures audited)
  run_fed_event_conditioning.py        build + execute + verify + audit
  _audit_fed_event_conditioning_numbers.py
  _probe_fec_feasibility.py            the three load-bearing assumptions
tests/
  test_fed_event_conditioning.py       15 tests
```

Gates: `G-E1` records that the two in-repo FOMC schedules differ by one day on
essentially every meeting (this study uses `SDRUtils.analytics.fomc`);
`G-E2` requires every hand-entered Jackson Hole date to be corroborated by a real
communication in the corpus; `G-E3` asserts no dependent variable spans a meeting
that resolved inside its own window.

Reproduce:

```
conda run -n stir python notebooks/rv/fed_event_conditioning_run.py
conda run -n stir python notebooks/rv/run_fed_event_conditioning.py
```

Fully offline — ZQ settles from the shared `BT/serff` parquet cache, sentiment
from the committed snapshots. No network, no Excel/COM.

---

## 6. The recommendation

**Do not put on the Jackson Hole receiver on this signal.** At every lead this
desk has measured — including the five weeks the note claims — the data reaching
Fed language on 28 August is hot.

If the lead is believed at all, it points at a receiver into **October–December**,
which is an argument about the back leg of an existing 2×1 rather than about
Friday.

And Study A says the language channel itself, while positive and large enough to
matter, cannot be established as real on any sample that will exist for a decade.
That is a reason to stop looking here, not a reason to trade it.
