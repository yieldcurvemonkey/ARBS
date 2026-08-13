# Reading the dealer ladder panel

For whoever looks at the chart. Two pages, no code.

---

## What you are looking at

Every USD swap print on the SDR tape is repriced against a minute-resolution
Citi curve at the moment it traded. If it printed **above** our mid, the
customer paid up, so the **dealer received fixed** and is now **long duration**.
If it printed below, the dealer paid.

The panel sums that, per key-rate bucket, per day.

```
customer pays fixed  ->  dealer RECEIVED fixed  ->  dealer long duration  ->  BLUE
customer receives    ->  dealer PAID fixed      ->  dealer short duration ->  AMBER
```

The number behind each bar is **signed DV01 in USD per basis point**, weighted
by how confident the call is. A print we are 90% sure about counts 0.8 of its
size; a coin flip counts nothing.

---

## The two views are not interchangeable

**Left — the z grid.** Ten buckets down, sixty sessions across. Each cell is how
unusual that bucket's flow was *for that bucket*. Blue = unusually
dealer-received, amber = unusually dealer-paid, grey = an ordinary day.

**Right — one bucket's own history.** The actual signed DV01, in dollars, day by
day, for whichever bucket you clicked.

**You may read across the grid. You may not read across the levels.** That is
not a style rule, it is the single hardest limit on this data, and it has a
number:

> We can orient **76%** of the DV01 that prints in 0–1Y and only **50%** of what
> prints in 15–20Y. Same tape, same method — the long end just has more
> packages whose direction cannot be read at all.

So a bar chart of dollars across buckets would show 15–20Y as roughly half its
true size, and nothing on the screen would say so. **The panel refuses to draw
it.** If you ask the API for two buckets' levels at once it returns an error
rather than a chart.

The z grid is safe for exactly the same reason it looks less concrete: dividing
by a bucket's own history cancels the missing half out. "5y is more one-sided
for 5y than 10y is for 10y" is a real statement. "Dealers are longer 5y than
10y" is not available from this data at any price.

---

## The number next to every aggregate

**Coverage.** Under half of the tape's DV01 reaches the ladder. The exact
figure is on the panel — click it and you get the rest, by reason and by
dollar share. It is computed over the complete partition, not over the cells
that happen to have an answer, which is a distinction worth a moment:
averaging coverage across the cells that *do* have a direction quietly skips
every bucket-day where nothing could be oriented, and on one window that read
67% where the truth was 45%.

The biggest hole — **more than 40% of all DV01** — is packages of four or more
legs. For most of those, several *different and mutually contradictory* sets of
leg directions reconcile to the reported package price equally well. There is
no right answer to pick, so none is picked. This is structural. It is not
waiting on engineering.

> **The panel's number will not match the 57.89% in the backend's own write-up,
> and they are not the same statistic.** That figure is *universe-level*
> retention over the whole 610-day tape: what survives the eligibility rules.
> The panel's is what survives everything — eligibility, then repricing, then
> the key-rate projection, then the ladder — over whatever window is loaded,
> and it includes Fed Funds and the lifecycle series. Lower, and it is the one
> that describes what you are actually looking at.

That hole is not random, and it leans the wrong way: the packages we drop are
**more** customer-facing than the ones we keep (98% customer-to-dealer against
82%) and carry more block risk. **Whatever this panel says about the size of
customer flow, the truth is bigger.**

---

## Six things that will mislead you if nobody says them

**1. This is flow, not a position.** When a dealer nets risk away through
compression, or allocates a block to funds, nothing prints. So the offsetting
trade never arrives and a running total only ever grows. There is deliberately
no cumulative line here. If you want a position, you have to assume a decay and
name the half-life, and it is then a model rather than a measurement.

**2. Customer flow and street flow are separate lines. Keep them separate.**
D2C is customers loading risk onto dealers. D2D is the street passing risk
around itself — informative ("the street is distributing"), but it is not new
inventory. VENUE_UNKNOWN is a third residue and is not a rounding of either.
The toggle never sums them.

**3. One day is mostly noise.** Which packages happened to print moves the
coverage behind a bucket by more than 25% on somewhere between a quarter and
two-thirds of days, depending on the bucket. The series is informative about
itself out to roughly a week. A single day against the day before is mostly
composition.

**4. The 1–2Y bucket's level drifts for a measurement reason.** Its coverage is
falling about 5 percentage points a year, so its dollar level trends downward
whether or not anything is happening. It ends the sample carrying a ~26%
measurement-driven change. Use the **cov-adj** toggle for that bucket, or read
its z. The other nine buckets barely care which basis you pick.

**5. The clock is when the print became public, not when it traded.** Blocks
arrive late; the row tells you how late. Stamping on execution time would let
you "see" trades before the market could.

**6. A greyed-out direction means we declined, not that nothing happened.**
Hover it — it says which of the reasons applies. An empty cell on a busy day is
a missing call, not a quiet market.

**7. Do not trade the 0–1Y bucket off this.** FOMC-dated swaps — the
meeting-to-meeting ones — are **28% of that bucket's risk**, and we price them
against a curve that has no meeting steps in it. It is a smooth curve, so it
averages straight across the step the trade exists to express. Measured: those
prints land 4–7× further from our mid than everything else on the same day, and
which side they land on **flips from one meeting to the next** — +1.6 bp into
July 2024, −1.2 bp into September. Both Fed Funds and SOFR do it together,
which is how we know it is the curve and not a plumbing mistake.

The rest of the ladder is unaffected: outside 0–1Y and 2–3Y, meeting-dated
trades are under 2% of any bucket. Individual FOMC-dated rows in the tape say
so when you hover them.

---

## What it is not

It is **not counterparty-observed**. Nobody told us who did what; it is inferred
from price against a model mid, and it has never been checked against a desk
ticket, because there are none to check against.

It is **not a trading signal**, and nothing here is a backtest. A separate
pre-registered study asked whether this flow predicts anything intraday and
found nothing that survived its own null. That question is closed. This is a
positioning read.

**Fed Funds prints are included and are the weakest part.** The
no-bias result behind the whole method was measured on SOFR. Filter to SOFR if
the answer matters.

---

## Where the numbers come from

`arbs_dd_ladder_v1`, rebuilt from `arbs_dd_unit_v1` by a nightly-able batch job.
Every row carries the git revision that produced it and the tape generation it
read; both are printed in the panel header. The limits above are measured, and
each of them is sourced in `WHAT_THE_LADDER_SUPPORTS.md` and `INDICATOR.md`.

---

# Reading the intraday prints chart

The second panel is a different tool with a different question. The ladder asks
*how is the dealer community positioned in 7-10y this week*. This one asks
**where did 10y actually trade today, and which way did the dealer go on each
print**.

## What is on it

One day, one tenor, one index, one venue class. Never two of anything — a 2Y and
a 30Y do not share a rate axis, and SOFR sits 1.5-2.4 bp off the Fed Funds curve,
so overlaying them would draw that basis as if it were bid-offer.

- **A triangle per print.** Up and sky = the dealer RECEIVED fixed (long
  duration). Down and amber = the dealer PAID fixed. A grey dot is a print the
  model declined to call. The area is the structure's DV01, so a big triangle is
  a big risk transfer, not a big number of trades.
- **A line: the mid.** Solid means it is the real thing — a modelled par rate
  every minute, from the same curve every mark was priced against. Dashed means
  there was no grid for that tenor and the line is only joining the prints to
  each other.
- **Stems below**, showing how far off mid each print landed.

## The single most important sentence

**The line is modelled. It is not a quote and it is not a level you could have
traded on.** It is the same model the direction call comes from, which is why
the marks sit on it — not evidence that the model is right.

## Why a mark can sit off the line

Because it is a **different swap**, nearly always. The line is the canonical
spot swap for that tenor. A print with a broken maturity, or an IMM start, is a
few days away from that, and a few days of maturity moves the fair rate a
fraction of a basis point.

The panel gives you the number rather than making you guess: the **`mark vs
line`** chip reports the median, p95 and max distance between each mark's own
mid and the line above it. Median is normally **0.0000 bp** — for a spot
standard swap the two are literally the same instrument. If the median moves off
zero, something has changed and you should not trust the chart until you know
what.

## Where the line stops

It **breaks** across 23:00-00:59 ET. That is Citi's publication gap: no curve
exists there. Prints in that window were repriced off a stale snapshot, and
their tooltip says so. A line drawn across it would be asserting the mid did not
move through two hours when the truth is that nobody knows.

It also breaks on any gap over 10 minutes. Inside a live session the grid is
never more than 5 minutes apart, so a break is always a real absence.

## What is filtered out by default, and why it matters

These are not tidying. Each one changes what the chart is *about*:

- **Off-market prints.** A trade with an upfront has an arbitrary fixed rate —
  it is off mid *by construction*. Showing them stretched the y-axis **31x** on
  the reference day, from about 8% of the rows. You can switch them on; they are
  pinned to the edge as hollow chevrons and never allowed to own the axis.
- **Forward starts.** A 10y10y is not a 10Y. Measured 66 bp apart.
- **FOMC-dated swaps.** Repriced against a curve with no meeting steps, so their
  distance from mid is mostly model error: 6.8x wider on Fed Funds, 4.0x on
  SOFR.
- **Package legs.** A steepener's dealer received one leg and paid the other, so
  painting a leg with the structure's direction would be wrong half the time.
  They can be shown, as rings, with no direction and no mid.

Every one of these reports how many it hid. "11 off-market prints were hidden"
and "there were none today" are different facts.

## Tenor matching is stricter than it looks

The chart matches on the strict tenor label, not the loose one. `10Y` in the
loose sense spans 9.50-10.49 years — a **six-month band**. Strict is
9.984-10.027. There is a `band` toggle if you want the wider set; it tells you
how many extra prints that bought.

## What it will not do

- It will not put a per-leg mid on a package. A curve or fly deviation is a
  spread across legs and cannot be split back into per-leg mids.
- It will not plot on the availability clock. This chart is on the **execution**
  clock — where it traded, not what you could have known — because the mid it is
  drawn against is a function of execution time. The ladder is the opposite, and
  deliberately so.
- It will not fade marks by conviction. Most calls sit inside the mid's own
  measurement error; fading by that would grey out nearly everything while
  removing no error at all.

