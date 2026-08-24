# Gamma P&L, break-even vol, and the fixed-vs-floating hedging-vol decomposition

## Source note — READ FIRST

**The seven `.md` files named in the request do not exist.** `C:/Users/chris/Downloads/convexityrv_markdown/` contains 97 converted files, but none of the seven; the markdown conversion pipeline evidently ran before these were downloaded (all seven PDFs are timestamped 2026-08-24 10:01–10:03, and the only QuantSE `.md` files in that folder are older carry/convexity threads).

All seven exist as PDFs under **`C:/Users/chris/Downloads/convexityrv/`** with byte-identical names minus the `.md` suffix. Everything below is extracted from those PDFs. Nothing is missing.

| # | Source document (short name used below) | Path |
|---|---|---|
| D1 | *options - Gamma PnL Formula and Break-Even volatility* | `C:/Users/chris/Downloads/convexityrv/options - Gamma PnL Formula and Break-Even volatility - Quantitative Finance Stack Exchange.pdf` |
| D2 | *options - What is gamma to do with realized volatility?* | `C:/Users/chris/Downloads/convexityrv/options - What is gamma to do with realized volatility_ - Quantitative Finance Stack Exchange.pdf` |
| D3 | *Delta Hedging with fixed Implied Volatility **or floating** Implied Volatility?* | `C:/Users/chris/Downloads/convexityrv/Delta Hedging with fixed Implied Volatility or floating Implied Volatility_ - Quantitative Finance Stack Exchange.pdf` |
| D4 | *options - Delta Hedging with fixed Implied Volatility **to get rid of vega**?* | `C:/Users/chris/Downloads/convexityrv/options - Delta Hedging with fixed Implied Volatility to get rid of vega_ - Quantitative Finance Stack Exchange.pdf` |
| D5 | *volatility - Continuous delta hedge formula* | `C:/Users/chris/Downloads/convexityrv/volatility - Continuous delta hedge formula - Quantitative Finance Stack Exchange.pdf` |
| D6 | *portfolio management - Delta hedge value formula* | `C:/Users/chris/Downloads/convexityrv/portfolio management - Delta hedge value formula - Quantitative Finance Stack Exchange.pdf` |
| D7 | *options - Bergomi: Skew arbitrage* | `C:/Users/chris/Downloads/convexityrv/options - Bergomi_ Skew arbitrage - Quantitative Finance Stack Exchange.pdf` |

Six further related threads sit unconverted in the same folder and were **not** extracted (outside the enumerated set): *Gamma Pnl vs Vega Pnl*, *Link between Vega and Gamma*, *Long Gamma vs Vega*, *Vol, Gamma, Vega — essentially all the same?*, *Option: link between Vega and Gamma*, *black scholes - Realizing the same PnL as Gamma Vs Vega*.

---

# 1. The gamma-P&L / theta accounting identity

## 1.1 D1 — the discrete two-term form (question body, `roz`, asked 2019-08-28)

> When we derive the P&L of a delta hedged option we obtain:

$$\mathrm{P\&L} = \tfrac{1}{2}\Gamma(\delta S)^2 - \theta\,\delta t$$

Note the sign convention: **D1 carries `θ` as a positive quantity that is subtracted** (a cost paid). D2 below uses the opposite convention (`θ` itself negative). This is the single most common implementation sign error across the set — see §5.

## 1.2 D2 — derivation of the ½Γ dS² term from the average delta (`Newquant`, answered 2023-07-04)

Starting point:

$$PnL = \Delta * dS = \frac{dO}{dS} * dS$$

> Consider your position with $S = S_0$. As S moves to $S_1$, the P/L between gained over the two points is given by the average $\Delta$ between $S_0$ and $S_1$, multiplied by $dS$:

$$PnL = \frac{\Delta_0 + \Delta_1}{2} * dS$$

> We know that

$$\Delta_1 = \Delta_0 + \Gamma_0 * dS$$

$$\therefore PnL = \frac{\Delta_0 + \Delta_0 + \Gamma_0 * dS}{2} * dS = \frac{2\Delta_0 + \Gamma_0 * dS}{2} * dS = \Delta_0 * dS + \frac{\Gamma_0}{2} * dS^2$$

> In the case of delta hedged portfolio at $t_0$, the offsetting delta term $-\Delta_0$ leaves the PnL as

$$PnL = \frac{\Gamma_0}{2} * dS^2$$

Then, from GBM:

$$dS = \mu S\,dt + \sigma S\,dW$$

> Taking expectation of the square of dS leaves us with:

$$dS^2 = \sigma^2 S^2\,dt$$

> Leaving our PnL formula as:

$$\frac{\Gamma_0}{2} * \sigma^2 S^2\,dt$$

## 1.3 D2 — the theta identity stated as an exact offset

> However as you know already, gamma is not free, one must pay theta away. Without even deriving a formula for theta, we know that for a fair market, the expectation of owning an option should be 0. As in nobody expects to make or lose money when transacting (of course that's different due to risk premiums, tx costs, etc, but fine for this example). **If our instantaneous P/L from $\Gamma$ over the period $dt$ is $x$, then our theta must be $-x$.**

and, later in the same answer:

> Finally, since we pay $\Theta$ away at a proportional level to $\frac{\Gamma S^2\sigma^2}{2}$ …

**This is the accounting identity in its cleanest stated form:**

$$\Theta = -\frac{\Gamma S^2 \sigma_i^2}{2}$$

## 1.4 D5 — the identity derived exactly from the Black–Scholes PDE (`LocalVolatility`, answered 2017-04-03)

D5 gives the only fully rigorous derivation in the set. Setup wording verbatim:

> In your case, you are selling and delta hedging the option using the implied volatility $\sigma_{(i)}$ while the actual volatility of the underlying asset is $\sigma_{(r)}$. Your portfolio profit and loss is given by the sum of value changes of (i) the derivative and (ii) the hedging position, both using the implied volatility. We have

$$\mathrm{d}\Pi_t = \mathrm{d}V_t^{(i)} - \Delta_t^{(i)}\,\mathrm{d}S_t - r\left(V_t^{(i)} - \Delta_t^{(i)}S_t\right)\mathrm{d}t.$$

> Since

$$\mathrm{d}V_t^{(i)} = \frac{\partial V^{(i)}}{\partial t}\mathrm{d}t + \underbrace{\frac{\partial V^{(i)}}{\partial S}}_{=\Delta^{(i)}}\mathrm{d}S_t + \frac{1}{2}\underbrace{\frac{\partial^2 V^{(i)}}{\partial S}}_{=\Gamma^{(i)}}\mathrm{d}\langle S\rangle_t,$$

*(the $\partial S$ in the gamma denominator is `[sic]` — the rendered PDF drops the exponent; it is $\partial S^2$, as the next display and the PDE below both write correctly.)*

> we get

$$\mathrm{d}\Pi_t = \left(\frac{\partial V^{(i)}}{\partial t} + \frac{1}{2}\sigma_{(r)}^2 S_t^2 \frac{\partial^2 V^{(i)}}{\partial S^2} - r\left(V_t^{(i)} - \Delta_t^{(i)}S_t\right)\right)\mathrm{d}t.$$

> Now we use that $V^{(i)}$ satisfies the Black-Scholes PDE

$$\frac{\partial V^{(i)}}{\partial t} + rS_t\underbrace{\frac{\partial V^{(i)}}{\partial S}}_{=\Delta^{(i)}} + \frac{1}{2}\sigma_{(i)}^2 S_t^2 \underbrace{\frac{\partial^2 V^{(i)}}{\partial S^2}}_{=\Gamma^{(i)}} - rV^{(i)} = 0$$

> to obtain

$$\boxed{\ \mathrm{d}\Pi_t = \frac{1}{2}\left(\sigma_{(r)}^2 - \sigma_{(i)}^2\right)S_t^2\,\Gamma^{(i)}\,\mathrm{d}t.\ }$$

**The two volatilities enter at two different places, and this is the whole mechanism:** $\sigma_{(r)}$ enters through the quadratic variation $\mathrm{d}\langle S\rangle_t$ of the *actual* path; $\sigma_{(i)}$ enters through the PDE that the *model value used for hedging* satisfies. The gamma that weights the difference is $\Gamma^{(i)}$ — the gamma at implied vol.

D5's own gloss, verbatim:

> I.e. over each short interval, your profit and loss is proportional to the difference in realized to implied variance times the current gamma (computed using the implied volatility). **While $\mathrm{d}\Pi_t$ is deterministic, the overall hedging profit and loss over the lifetime of the option is path-dependent. Its absolute value is higher for paths that fluctuate around the strike (where the gamma is higher).**

D5 references: Ahmad, Riaz and Paul Wilmott (2005) *"Which Free Lunch Would You Like Today, Sir? Delta Hedging, Volatility Arbitrage and Optimal Portfolios,"* Wilmott Magazine; Carr, Peter (2005) *"FAQs in Option Pricing Theory"* (Question 9); Wilmott, Paul (2006) *Paul Wilmott on Quantitative Finance*, Vol. 1, Wiley, 2nd Edition, Chapter 12 "How to Delta Hedge".

`nbbo2` comment on D5: *"See this answer … for the daily P&L. For the overall P&L you integrate this from 0 to T."*

`LocalVolatility` comment on D5: *"Chapter 12 'How to Delta Hedge' in Wilmott's 'Paul Wilmott on Quantitative Finance' discusses this problem in detail. In particular it shows how your hedging p&l differs when using either the implied or the estimated (true) volatility for computing the hedge ratio."*

D5 question parameters (posed but never numerically answered): $S_0 = 1000$, $\sigma_i = 0.25$, $\mu = 0.10$, expiry one year; *"How does the formula look like in terms of $\sigma_r$? What happens if $\sigma_r = 0$? $> \sigma_i$? $< \sigma_i$?"*

## 1.5 D6 — the SAME formula, plus the critical average-vs-exact distinction

Question body (`Mahi`, asked 2017-03-23):

> When we delta hedge with implied volatility, and dynamically adjust every day, I believe the PnL theoretically is

$$PnL = 0.5\,\Gamma S^2(\sigma_r^2 - \sigma_i^2)\,dt$$

> where $\sigma_r$ is realized volatility.
>
> My question is, how accurate is this? I am trying to do a delta hedge experiment, and I find that **my daily PnLs range wildly, yet the values given by above formula remain somewhat small (< 1)?**
>
> I compute my daily PnL as

$$'\text{change in call price'} + \Delta \cdot '\text{change in spot price}'$$

> since the first term gives us what we lost/gained through the call, and the second gives us what we earned shorting the stock. **But these two formulas don't match .... however the aggregate results do?**

**`Mark Joshi` (answered 2017-03-24, score 4):**

$$PnL = 0.5\,\Gamma S^2(\sigma_r^2 - \sigma_i^2)\,dt$$

> **this is an average P&L rather than an exact one. So it should agree with your other formula on average but not each day.**

**`Quantuple` (answered 2017-03-24, score 4):**

> At the order 1 in $dt$ you should rather use

$$0.5\,\Gamma(S,\sigma_i)\,S^2\left((dS/S)^2 - \sigma_i^2\,dt\right)$$

> to get the **true P&L increment, not the average one** (see Mark Joshi's answer).
>
> Also this gives you the **replication error** i.e. difference between the option price evolution (which you are *long*) and that of your *self-financing* delta hedge (= assumes you hedge in a self-financing fashion by transferring cash between stock and cash account with no exogenous infusion/withdrawal of cash).

**`Alex C` comment (2017-03-25):**

> You could perhaps say that Mark Joshi's answer is the **ex-ante** estimate of Tuesday's P&L that you form on Monday close not knowing what the Stock market will do tomorrow, while Quantuple's answer is the **ex-post** estimate you form on Tuesday close once you know what the stock market return $\frac{dS}{S}$ was today.

**This is the single most important distinction in the whole set for implementation.** The two forms are:

| Form | Expression | Meaning |
|---|---|---|
| Ex-ante / average | $\tfrac12 \Gamma S^2(\sigma_r^2 - \sigma_i^2)\,dt$ | expectation; small and smooth |
| Ex-post / exact | $\tfrac12 \Gamma(S,\sigma_i) S^2\!\left((dS/S)^2 - \sigma_i^2 dt\right)$ | realization; ranges wildly day to day |

They agree in aggregate and disagree every single day. Sizing off the first sizes the *mean*; the realized path delivers the second.

## 1.6 D4 — the OP's decomposition (and a transcription hazard)

`Clement` (asked 2017-06-08) writes the Greek decomposition as:

$$dPNL = \vartheta * d\sigma + \theta * dt + 0.5 * dS^2 * \Gamma$$

and then states what he calls the well-known daily delta-hedged P&L:

$$dPNL = 0.5 * (\sigma_i^2 - RV^2)\Gamma * S * dt \qquad \text{with } RV = \text{realized volatility} = ds/S$$

> **⚠ Transcribed verbatim, but this line is wrong on two counts relative to every other source in the set:** the variance difference is written $(\sigma_i^2 - RV^2)$ — sign-reversed versus D2/D5/D6's $(\sigma_r^2 - \sigma_i^2)$ — and it carries $S$, not $S^2$. Neither answer on the thread endorses or corrects it, and `Clement` himself later says *"my formula is inexact"*. Do not implement from this line. Use D5/D6.

## 1.7 D2 — the option premium as the integral of gamma P&L (`Newquant`)

> One interesting point to consider is that the price of the option must be equal to the expected profits for holding it over it's lifetime. For a market neutral position (instantaneously riskless) that is kept neutral over it's life through continuous hedging (without cost), the price of the option should be equal to integral (continuous sum) of $\Gamma$ PnL over it's life. Formulaically:

$$Cost = \frac{1}{2}\int_0^T S_t^2 \sigma_r^2 \Gamma\, dt$$

> Assuming $S_t$ as a constant, which, for small $\sigma_r$, and 0 carry is not too far from truth, the formula for an ATM option is approximately:

$$\Gamma_{s,v,t} = \frac{1}{S * \sigma\sqrt{2\pi t}}$$

> which simplifies the cost formula to:

$$\frac{1}{2}\int \frac{S\sigma_r}{\sqrt{2\pi t}}dt = \frac{S\sigma_r\sqrt{T}}{\sqrt{2\pi}}$$

*(Arithmetic check, INFERENCE — verified numerically: this integrates correctly — $\tfrac12 \cdot \tfrac{S\sigma_r}{\sqrt{2\pi}}\int_0^T t^{-1/2}dt = \tfrac12 \cdot \tfrac{S\sigma_r}{\sqrt{2\pi}} \cdot 2\sqrt T$ — and reproduces the standard ATM approximation $\approx 0.399\,S\sigma\sqrt T$, i.e. the familiar $0.4\,S\sigma\sqrt T$ rule. Numeric check at S=1, σ=0.2, T=1: integral = 0.079788, closed form = 0.079788, 0.4·Sσ√T = 0.080.)*

And the closing statement of D2 — the clearest single statement in the whole set of what the P&L is a bet on:

> to maturity, **we are replicating them at realised volatility, whilst paying implied volatility**, this means that our final payoffs are given by

$$\int_0^T \frac{\Gamma S^2}{2} * (\sigma_r^2 - \sigma_i^2)\,dt$$

## 1.8 D2 — the BS gamma worked number (`Newquant`)

> Let's take a real example. The asset price is 1, with 30 DTE options trading on it. We select the option with the largest gamma, which is right around the spot price, and it has a volatility of 20%. This equates to a Black Scholes gamma of:

$$\frac{n(d1)}{s\sigma\sqrt t} \approx \frac{1}{1 * 0.2\sqrt{2\pi t}} \approx 7$$

*(Verified: both forms evaluate to 6.9577 at S=1, σ=0.2, t=30/365. The source's "≈ 7" is right.)*

> With our initial $\Delta$ at 0.51, this means that for any change in the underlying price, $dS$, we expect our delta to change by $\Gamma * dS = 7 * dS$. So if the underlying moved to 1.01, our new $\Delta$ would be expected to be $0.51 + 7 * (1.01 - 1) = 0.58$, evaluating the delta under BSM shows that our new delta is 0.5801, up 0.691 from 0.511, it is less than 0.7 because of higher order greeks which change the gamma as price moves.

> **⚠ "up 0.691 from 0.511" is internally inconsistent in the source** — $0.5801 - 0.511 = 0.0691$ (verified), not $0.691$, and the comparison "less than 0.7" should read "less than 0.07". Transcribed verbatim; the decimal is misplaced in the original post. The *point* (higher-order greeks make the realized delta change fall short of the linear $\Gamma\,dS$ prediction) survives the typo.

> Remember that greeks just describe risk, or sensitivities, they are slopes of P/Ls through different input values like spot:delta, IV:vega, and time:Theta. Gamma is the slope of delta with spot, speed is the slope of gamma with spot, and so on.

---

# 2. Break-even volatility / break-even move

## 2.1 D1 — the break-even move, derived (question body)

> and setting equal to zero and rearranging we obtain:

$$\tfrac{1}{2}\Gamma(\delta S)^2 - \theta\delta t = 0$$
$$\implies \tfrac{1}{2}\Gamma(\delta S)^2 = \theta\delta t$$
$$\implies (\delta S)^2 = 2\frac{\theta\delta t}{\Gamma}$$
$$\implies \delta S = \sqrt{\frac{2\theta\delta t}{\Gamma}}$$

> Suppose $\delta t = 1\ \mathrm{day}$ so that we obtain the break-even daily move in the underlying to be:

$$\boxed{\ \delta S_{Break-Even} = \sqrt{\frac{2\theta}{\Gamma}}.\ }$$

## 2.2 D1 — the question that matters for rehedge frequency

> My question is this. Suppose for concreteness $\Gamma$ and $\theta$ are such that our break-even daily move, $\delta S_{Break-Even}$, is 10. Does this mean that we break even when the **end of day price** on the underlying has changed by 10 or more OR does this mean that we merely need to realize a **total change** of 10 across that day (but not necessarily end the day with a price that is different by 10). For example: if the underlying starts the day at 20 and follows the path : 20 -> 22 -> 20 -> 26, then we have realized a total of 2 + 2 + 6 = 10 if we sum up each individual incriment (vs 26-20=6 as the total change).

## 2.3 D1 — the answer: NO, break-even moves do not add up linearly (`Misha Wolynski`, answered 2021-02-23)

> **Good question. The answer to this is no.** Let us work through a simple example to see why. Assume that the Gamma is $10$ and that the break-even move is $1$. For simplicity, also assume that, these are unchanged by price moves in the underlying (this is reasonably accurate for small price moves), so:
>
> - $\Gamma = 10$
> - $\delta S_{Break-Even} = 1$
>
> Note that we are dealing with a Delta-hedged portfolio here, so the starting value of Delta is $0$, i.e. $\Delta = 0$. However, once the price moves, the Delta will equal the Gamma times the price move, i.e.: $\Delta = \Gamma \times \delta S$. Hence, once the break-even move happens (i.e. when $\delta S = \delta S_{Break-Even}$), the Delta will equal the Gamma times the break-even move, i.e. $\Delta = \Gamma \times \delta S_{Break-Even} = 10 \times 1 = 10$. This means that when you Delta-hedge this to lock in the break-even move, your cash inflow will be $\Delta \times \delta S_{Break-Even} = 10 \times 1 = 10$. Hence, in this example, you need to make $10$ currency units to break even.
>
> Now, let's see what happens if the price instead changes by HALF of a break-even move, i.e. $\delta S = 0.5$. As before, the delta becomes $\Delta = \Gamma \times \delta S = 10 \times 0.5 = 5$. If you Delta-hedge to lock in this move, your cash inflow will be $\Delta \times \delta S = 5 \times 0.5 = 2.5$.
>
> As you can see, **when you lock in the profit on half of a break-even move, it is equal to one quarter of the profit on a whole break-even move, not to one half.** This is because you lock in a smaller price move on a smaller volume (in this case, half the price move on half the volume naturally gives you one quarter of the profit). **Thus, if your hedging strategy is to lock in the profit more frequently, you need a larger number of smaller moves and the total move you need will be bigger than one break-even move.**

**Worked numbers to preserve:** $\Gamma = 10$, $\delta S_{BE} = 1$ → cash inflow $10 \times 1 = 10$. Half move $\delta S = 0.5$ → $\Delta = 5$, cash inflow $5 \times 0.5 = 2.5 = \tfrac14 \times 10$. Quadratic, not linear.

## 2.4 Reconciling the two break-even forms — INFERENCE

Neither D1 nor D2 does this substitution explicitly, but combining §1.3's $\theta = \tfrac12\Gamma S^2\sigma_i^2$ into §2.1's $\delta S_{BE} = \sqrt{2\theta\delta t/\Gamma}$ gives

$$\delta S_{BE} = \sqrt{\frac{2 \cdot \tfrac12 \Gamma S^2 \sigma_i^2 \cdot \delta t}{\Gamma}} = S\,\sigma_i\sqrt{\delta t}$$

i.e. **the break-even move is exactly the one-standard-deviation move at implied vol over the rehedge interval**, and $\Gamma$ cancels out of it entirely. **INFERENCE** — supported by, but not stated in, D1 + D2/D5. *(Verified numerically: Γ=10, S=100, σ=0.2, δt=1/252 → both sides = 1.259882.)*
Consequence: $\Gamma$ scales the *size* of the P&L but not the *hurdle rate*; the hurdle is set by $\sigma_i$ and $\delta t$ alone.

## 2.5 D7 — break-evens generalised beyond gamma (`SI7`, accepted answer)

The only source in the set that extends break-even thinking to a multi-factor structure:

> The key idea behind this strategy is based on **the relationship between Theta and the second derivatives (Gamma, Vanna, Volga)**, which is also mentioned in the book. You can easily use a break down of Theta into these three components on a maturity slice-by-slice basis and **derive implied break even levels for dSpot, dSpot*dVol and dVol**. Given the market implied break even levels (which will be different for different slices), you can then evaluate cheapness/richness of these break-even levels based on your own assessment or historical behavior. This is NOT constrained to any of the model restrictions in the book.

---

# 3. Fixed vs floating implied vol in the hedge — what it does to the decomposition

## 3.1 D4 — the question, stated precisely (`Clement`)

Setup: $\sigma_e$ = expected future realized volatility; $\sigma_{i0}$ = initial implied volatility. *"if its implied volatility $\sigma_{i0}$ is lower than $\sigma_e$ then i want to buy the option and delta hedge at a certain frequency (daily for example)."*

> I've always delta hedged using a floating IV which is changing daily but i realized this may not best thing to do.

> My concern with this is that i have the feeling that **we are only looking at $\Gamma$ and $\theta$ influences in the case we are delta hedging using floating IV every day.**
>
> Looking at this formula, **PNL at maturity should not be IV path dependant, however running simulations i get to very different PNL at maturity using a floating IV. So is this formula only true when using a fixed IV to hedge daily?**

> If we want to get rid of the vega effect then we need to replicate the same option with a constant IV so that the vega does not have any effect on PNL. But does this mean that we can use any IV to hedge the option? This makes no sense to me?

## 3.2 D4 — the decisive statement (`Clement`, comment 2017-06-09)

> I don't mean vega hedge my portfolio, my formula is inexact. I mean having a PNL at maturity that is not IV path dependent. **If i delta hedge with floating IV, PNL at maturity is IV path dependent, while it's not if i use a constant IV over the life of the option.**

**This is the crux of fixed-vs-floating in one line.** Fixed hedging vol ⇒ terminal P&L is a function of the realized *spot* path only. Floating hedging vol ⇒ terminal P&L additionally depends on the *implied vol* path.

## 3.3 D4 — why the vega term vanishes under a fixed vol (`julien` + `Clement` exchange on Ahmad–Wilmott)

`julien`'s answer (score 5) is a pointer:

> Ahmad, Riaz and Paul Wilmott (2005) "Which free lunch would you like today, Sir? Delta hedging, volatility arbitrage and optimal portfolios," *Wilmott Magazine*, Nov. 2005, pp. 64—79 … which tackles this exact issue.

`Clement`'s objection (comment, 2017-06-13), quoting p.67 of the paper:

> Basically he writes :

$$dV^i = \Theta^i dt + \Delta^i dS + 0.5\sigma^2 S^2\Gamma^i dt$$

> Actually i would decompose $dV^i$ as follows :

$$dV^i = \Theta^i dt + \Delta^i dS + 0.5\sigma^2 S^2\Gamma^i dt + vega * d\sigma^i$$

> What is wrong with my reasonning? Even if we are using a constant volatility, price of market is moving and implied volatility changes should impact prices variations.

Second objection (same commenter), quoting p.67 case 2:

> I feel like the author is going from

$$dV^i = 0.5(\sigma^2 - \sigma*^2)S^2\Gamma^i dt$$

> to

$$0.5(\sigma^2 - \sigma*^2)\int_{t_0}^{t} e^{-r(t-t_0)}S^2\Gamma^i dt$$

> just with actualization and integration but implied volatility $\sigma*$ is changing after every rebalancing, he cannot integrate it like a constant? Maybe the point i'm missing here is that the author is supposing implied volatility constant but that's a big assumption that is a key in my understanding of this problem. My question is more about floating IV vs fixed IV than which fixed IV to use.

`julien`'s resolution (comment, 2017-06-20):

> Haven't read the paper in a while but iirc, **volatility is assumed constant. Which means dsigma = 0.** The price is moving due to passage of time, change of underlying but that can still happen with constant implied volatility. I think it also covers your second comment: Implied vol is considered constant. **This paper basically tries to measure the impact of using one fixed IV (the one you bought the option at) or another (your expectation of future realized).**

**So the mechanism is explicit:** the clean $\tfrac12(\sigma_r^2-\sigma_i^2)S^2\Gamma\,dt$ result holds because $d\sigma = 0$ kills the $vega \times d\sigma$ term. Hedge at a floating vol and that term is *not* zero, and the clean identity no longer describes your terminal P&L.

## 3.4 D4 — expected P&L is invariant; the distribution is not

`dm63` (answered 2017-06-09, score 1):

> My intuition is that **your expected p/l from delta hedging is the same, regardless of what vol you use at each step** (since this just changes your series of spot transactions, each of which has zero expected value). However if you hedge at a vol much lower than the IV, or a vol which is much higher than the IV, **your eventual p/l will be more risky than just using the IV at each step. Meaning, it will have a wider distribution.** For example, using a zero vol to hedge would result in no delta hedging p/l on any day except the days you cross the strike, which is highly path dependent. I'm not sure how to prove that explicitly.

`Antoine Conze` (comment, 2017-06-09) supplies the proof sketch:

> **Expected (under the risk neutral measure) PnL is always the same whether you hedge or not: this is because the (discounted) hedging portfolio is a martingale.** As you pointed what will depend on the hedging strategy is the PnL distribution.

`nbbo2` (comment, 2017-06-09):

> There is no such thing as "getting rid of Vega" if you (dynamically) trade only the underlying AFAIK, you would need some other vol sensitive asset...

`Quantuple` (comment, 2017-06-09):

> Note that **if you choose to hedge with a fixed IV your prices won't be marked to the market anymore**, which may lead to some problems with your risk department.

`LocalVolatility` (comment): *"See also Question IX in Carr's 'FAQs in Option Pricing Theory'."*

## 3.5 D3 — the practitioner decomposition (`phlsmk`, accepted, score 10)

The answer is organised as exactly two effects:

> (1) Vega mark-to-market (m2m) PnL vs. theta/gamma profile
> (2) Change in risk and PnL due to higher order risks (vanna, volga)

Opening position:

> Generally speaking, in the real world, **you'd always want to use the correct implied vol.**

### Vega mark-to-market PnL vs. theta/gamma profile

> In a simple, pure Black Scholes world implied volatility is of course constant. **Your PnL, should you delta hedge an option to expiry in isolation, is dependent upon both the level and path of realised volatility.** That's because the gamma of the option, i.e. the frequency/magnitude with which you need to delta hedge, **is highest near the strike of the option, closer to expiry, and with a lower implied volatility.** Hull has nice plots of these relationships.

The two branches, given the 20% → 25% reprice in the question:

> - **raise the implied vol** you're using for the option price/risk which will mean **instant positive vega PnL, a change in delta on top of your gamma (dDelta/dVol, or vanna), but also therefore a higher theta bill and lower gamma going forward.** you can lock in the vega PnL by selling the option back or a similar option.
> - **ignore the change in implied volatility** if you intend to hold the option to maturity, which means the vega m2m PnL is somewhat irrelevant.

The key conditional statement — **which hedging vol is better depends on the shape of the realized path:**

> If it's your intention to hold and hedge the option to maturity, **you can calculate the delta with any implied volatility you like.** Broadly speaking, **a higher vol (positive vega PnL upfront, higher theta bill, less gamma) would benefit you if realised changes in the underlying ended up being evenly distributed in time and magnitude, and a lower vol (negative vega PnL upfront, lower theta bill, more gamma) would ultimately benefit you if the realised changes were large and centered around the strike near expiry.** You can convince yourself of this by running some simulations with delta hedging done using different implied vol levels.

### Change in risk and PnL due to higher order risks (vanna, volga)

> If you're using a more realistic stochastic vol model for a market making book or portfolio, your main concern is that (a) the model is arbitrage free and (b) your greeks for a larger group of trades is consistent.
>
> **If you are hedging one option within a portfolio and do not account for the vanna/volga contributions to your change in delta, that is you do not remark the implied vol of that one option, then your portfolio delta is inaccurate, i.e. you've effectively chosen not to mark your portfolio to market and have delayed taking higher order PnL and hedging the associated change in risk.**
>
> On market making and particularly exotic trading books, these higher order contributions to your delta drive a significant percentage of overall PnL, so **using the correct implied volatility for your delta is as important as using the correct spot price for the underlying.**

### D3 — expected vs distribution, and the loss-exceeds-premium counterexample

`AFK` comment: *"When you say 'you can calculate the delta with any implied volatility you like', it seems that you are saying that in the BS model, if you hold the opton until maturity, the expected P&L at maturity is independent of the vol used to delta hedge, is that right?"*

`phlsmk` reply (2015-10-27):

> **Almost, in the model the expected P&L at maturity is very, very close with different vols used. The expected max/min, and standard deviation of profits will vary, though (higher vol used, higher max profit).** Key practical differences are the P&L profiles of mark-to-market vs. mark-to-model until expiry, and of course the non-continuity of hedging and returns in the real world. A very nice, succinct paper is "Which Free Lunch Would You Like Today, Sir?: Delta Hedging, Volatility Arbitrage and Optimal Portfolios" by Ahmad and Wilmott. It has great detail on returns with different hedging vols.

> **If you buy an option, delta hedge it to expiry, can you lose more money than your premium?**
>
> **Yes!** A simple example: What is your PnL if you buy a delta-hedged 3 month 37.00 (5% delta) call option on INTC for 0.05 (spot is 35). The stock trades sideways and then rallies instantly to 36.99 into expiry and then the call expires worthless. You've lost your premium, the option has expired worthless, and you've lost money on your delta hedge.

*(Preserved worked numbers: 3-month, strike 37.00, 5-delta, premium 0.05, spot 35, terminal 36.99.)*

---

# 4. Which volatility the P&L is actually a bet on

Direct statements, per source.

**D2 (`nbbo2`, comment on the question):**

> They key word here is "delta-neutral", **if you are long an option and you are dynamically hedged your profit will be zero if Volatility turns out equal to what was priced into the option, positive if vol turns out greater and negative if vol turns out less than expected.** It is a consequence of the fact that options are priced with a volatility forecast in mind and will retrospectively turn out cheap/just right/expensive depending how volatile the underlying is in reality.

Followed by explicit confirmation in the comment thread:

> `dopller`: *"@nbbo2 when you say that vol turns out greater then do you mean RV > IV"*
> `dopller`: *"and when you say that vol turns lesser than expected, do you mean RV < IV ?"*
> `nbbo2`: **"Yes and Yes. You got it."**

And: *"See here and here for mathematical formula for P&L on a delta hedged position. **The profit is proportional to $\Gamma$**"*

**D2 (`Newquant`), closing line — the sharpest formulation in the set:**

> to maturity, **we are replicating them at realised volatility, whilst paying implied volatility**, this means that our final payoffs are given by $\int_0^T \frac{\Gamma S^2}{2} * (\sigma_r^2 - \sigma_i^2)dt$

**D2 (`Jan Stuller`, accepted answer) — why small moves lose:**

> **why do you lose money if there are only "small moves" in the underlying?** Because it costs money to be long Gamma (this is true for any asset, **including Bonds**): even a delta-hedged long Gamma position will always require an initial investment to set up (i.e. in case of options, this would be the premium that we pay to buy the option): **this premium will not be recovered for "small" moves in the underlying (specifically if those moves correspond to lower realized volatility than what had been priced as the implied volatility into the option).**

and the convexity framing:

> We make money on larger moves up or down because being long the option means we are long convexity (i.e. gamma, i.e. we are long a pay-off that has a positive second derivative with respect to the uderlying: just think of it as a graph: **if we are long a graph that has a pay-off $x^2$ and we are short a graph that has a pay-off $x$, we are long "gamma" (or convexity)**).

*(D2's supporting worked setup: option on 100 units, $\Delta = 0.6$, hedge = short 60 stocks. "when the value of the underlying stock increases, we lose money on the hedge, but we make money on the option: and because the option value is non-linear, we make **more** money on the option than we lose on the hedge"; "What if the value of the stock decreases? The value of holding 60 stocks decreases **more** than the value of the option: therefore we again make money (cause we are short the stocks)." Second answer, on gamma as auto-deleverager: "If the gamma is positive it means that the delta increases as the underlying goes up, and delta decreases as it goes down. I.E you get longer the rising asset, and shorter the falling asset. This is ideal as gamma acts as an auto-(de)leverager.")*

**D5:** *"your profit and loss is proportional to the difference in realized to implied variance times the current gamma (computed using the implied volatility)."*

**D3:** *"Your PnL, should you delta hedge an option to expiry in isolation, is dependent upon both the level **and path** of realised volatility."*

**Summary of what the bet actually is, across sources:** the bet is on **realized variance minus implied variance, integrated against dollar gamma computed at the implied vol** — *not* on realized vol as a scalar, because the dollar-gamma weight is itself path-dependent (D5: *"higher for paths that fluctuate around the strike"*; D3: *"level and path"*). And the ex-post per-step realization uses the actual squared return $(dS/S)^2$, not $\sigma_r^2\,dt$ (D6).

---

# 5. Sign and convention hazards found across the set

Collected because they are implementation traps, all evidenced above:

1. **`θ` sign.** D1: $\mathrm{P\&L} = \tfrac12\Gamma(\delta S)^2 - \theta\delta t$ treats $\theta$ as a **positive cost**. D2: *"If our instantaneous P/L from $\Gamma$ over the period $dt$ is $x$, then our theta must be $-x$"* — $\Theta$ is itself **negative**. Both appear in the same extraction; they are not the same variable.
2. **D5's prose says "selling", its algebra is long.** D5 states *"you are selling and delta hedging the option"* but derives $\mathrm{d}\Pi_t = \mathrm{d}V_t^{(i)} - \Delta_t^{(i)}\mathrm{d}S_t - \ldots$, which is a **long option / short delta** portfolio, and lands on $+\tfrac12(\sigma_r^2-\sigma_i^2)S^2\Gamma\,dt$ — the long-gamma sign (profit when realized exceeds implied). The boxed formula is the long convention; the word "selling" is inconsistent with it.
3. **D4's stated daily P&L is sign-reversed and dimensionally off** ($(\sigma_i^2 - RV^2)\Gamma S\,dt$). See §1.6. Unendorsed by the thread's answers.
4. **Average vs exact.** $\tfrac12\Gamma S^2(\sigma_r^2-\sigma_i^2)dt$ is the *expectation*; the realized increment is $\tfrac12\Gamma(S,\sigma_i)S^2((dS/S)^2 - \sigma_i^2 dt)$ (D6). Mixing them silently produces a backtest whose daily series is far too smooth — exactly `Mahi`'s reported symptom (*"my daily PnLs range wildly, yet the values given by above formula remain somewhat small (< 1)"*).
5. **D2's "up 0.691 from 0.511"** is a misplaced decimal (should be 0.0691 / 0.0701). See §1.8.

---

# 6. D7 (Bergomi: Skew arbitrage) — the gamma-neutral spread case

Included in full because it is the only source in the set covering a **spread position whose gamma has been neutralised**, i.e. structurally the closest analogue to a convexity leg traded against a second structure.

## 6.1 The setup (`Volwiz`, asked 2020-11-18, score 20)

> In his paper "Smile Dynamics IV" (https://www.fields.utoronto.ca/programs/scientific/09-10/finance/derivatives/bergomi.pdf) as well as in his book "Stochastic Volatility Modeling" (Chapter 9.10) Lorenzo Bergomi proposes a "Skew Arbitrage Strategy". As I understand his logic, he is saying that **for short maturities the skew stickiness ratio should be close to 2** (i.e. the implied ATM vol move for an dS_rel % spot move is **2 * Skew * dS_rel**). However, empirically the realised absolute spot move tends to be less than that, so one could buy a **gamma neutral 1 month 95/105 risk reversal, delta hedge and hold it for one day**. Since we are gamma neutral, as given by a Taylor expansion this position's PnL should be determined by
>
> **skew PnL + Vega PnL + "Mark to Market PnL"**
>
> - **"skew PnL" is proportional to realised spot vol covariance minus implied spot vol variance** and will on average be positive as the realised stickiness is smaller than the implied one.
> - **Vega PnL is small compared to the rest and basically just adds some noise.**
> - **"Mark to Market PnL" comes from recalibrating the vol model.**

The vol model, quadratic in log-moneyness:

$$\widehat{\sigma}(x) = \sigma_0\left(1 + \alpha(\sigma_0)\,x + \frac{\beta(\sigma_0)}{2}x^2\right)$$

> So each day, we would have to recalibrate the skew and curvature. In his book and paper Bergomi says that this Mark to Market PnL should be negligible. However, **if I buy a 30 day option today, this will be a 29 day option tomorrow. The 95/105 skew decays (i.e. becomes more negative) as time to maturity goes down, so there should be a downward drift on the PnL.** I tried to replicate the strategy and can indeed observe such a downward drift. It is smaller than the skew PnL, but has a **non negligible** effect on the PnL. In my replication I am using the S&P and my time period is 2010 to 2019, while Bergomi is using Eurostoxx and 2002-2010, so it is possible that I am picking up on a structural difference or a regime shift.

## 6.2 The empirical decomposition (`Volwiz`, edit) — preserve these numbers

> I am adding a plot with a decomposition for the PnL of the **35day 95/105 gamma neutral risk reversal for the S&P**. Unfortunately I only have data until **March 13 2020** … "PnL Total" is the PnL of the position. **"MTM" is the PnL from remarking the skew parameter and the quadratic ("vol of vol") parameter. "Vega" is the PnL from ATM moves and "Cross Gamma Theta" the PnL from dSdATM minus the theta.** As can be seen from the plot, **MTM brings a steady decay**, as I suggested in my question. I would call this decay quite significant, as it **basically eats up the PnL from Cross Gamma Theta since 2018.**

> The following scatter plot show Cross Gamma Theta PnL on the x-axis vs the Vega hedged PnL of the risk reversal on y-axis. **The regression beta (with 0 intercept) is 1.05 and R^2 is 76%.**

> Now I am showing Cross Gamma Theta PnL on x-axis vs total PnL on y-axis. **Regression beta is 2.38 and R^2 57%**

**Reading of those two regressions:** against the *vega-hedged* P&L the driver loads 1.05 with $R^2$ 76% — the decomposition is clean. Against *total* P&L the beta doubles to 2.38 and $R^2$ falls to 57% — the un-hedged residual terms (MTM decay in particular) both amplify and decorrelate the outcome.

## 6.3 The answer (`SI7`, accepted, +100 bounty, 2020-11-21)

On skew decay:

> From a theoretical perspective, I don't see any mistake in your thinking regarding skew decay but two questions arise from my end: The EuroStoxx backtesting approach in the book (9.10.) is based on the lognormal implied vol dynamic for which **Bergomi shows that in the Limit T->0 the skew is constant and independent of ATM vol** (that result is actually derived in 8.5.1). Hence, one would suspect that the skew decay component should not really be decisive in his EuroStoxx example, right? … For example, in **Figure 9.8.** in the book, you can see the impact of different P&Ls to the total P&L of this strategy.

On generalising past the model restrictions — see §2.5 for the Theta → (Gamma, Vanna, Volga) break-even decomposition.

**Words of caution (verbatim, all three):**

> - Check the footnotes in the book: **"Also, unwinding and restarting a new position on a daily basis is not practical: in our backtest, factoring in a bid/offer spread of 0.2 points of volatility on each leg of our spread position wipes out the strategy's P&L."** But if you don't roll, you quickly get concerned with the next point:
> - **The strategy may start gamma-neutral but don't ignore the impact of Gamma-speed (third derivatives). In turbulent markets, on the downside you are getting caught short gamma in your delta hedged risk reversal and skew tends to get steeper. A horrible P&L scenario.** It may work well if markets are rising (getting you long gamma and skew tends to flatten). So, **the strategy -though initially gamma neutral with negligible Volga impact- can quickly turn into a leveraged directional bet.** As a hint: Apply your backtesting strategy to data from March 2020 during the peak of the Covid-19 crisis.
> - There are more risks involved which may have a significant impact but are not considered in theoretical approaches. For example, **what about hedging your delta neutral risk reversal with Futures and the basis between the index and the future explodes to 60 points** as there is a high dividend uncertainty in the index?

## 6.4 The model-dependence caveat (`Frido`, answered 2025-10-31)

> the statement of Bergomi quoted by the OP "As I understand his logic, he is saying that for short maturities the skew stickiness ratio should be close to 2" can be refined.
>
> **For stochastic volatility models this is true only if the so-called Hurst parameter is equal to 0.5. If the skew is indeed generated by a stochastic volatility model with Hurst parameter value H, then the short dates SSR is in fact H+3/2. So for H < 1/2, i.e. rough vol models, the SSR can be less than 2.**
>
> For a 'simple/straightforward' derivation of this see: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5392865
>
> **Why is this relevant: because what may be perceived as an 'arbitrage' (ie empirical is less than 2) may not be an arbitrage at all if vol is rough.**

$$\mathrm{SSR}_{T\to 0} = H + \tfrac{3}{2}$$

---

# 7. Implications for sizing a convexity-adjustment leg against a swap butterfly

Every numbered claim below is either (a) directly supported by the sources, with attribution, or (b) explicitly marked **INFERENCE**. All seven sources are equity/FX-options threads; **none of them discusses swaps, swap butterflies, or convexity adjustments**, so every bridge into the rates context is inference and is marked as such.

### 7.1 Size on dollar gamma, not gamma

The variance spread is weighted by $S^2\Gamma$, never by $\Gamma$ alone: $\mathrm{d}\Pi_t = \tfrac12(\sigma_{(r)}^2 - \sigma_{(i)}^2)S_t^2\Gamma^{(i)}\mathrm{d}t$ [D5], $PnL = 0.5\Gamma S^2(\sigma_r^2-\sigma_i^2)dt$ [D6, both question and Joshi], $\int_0^T \frac{\Gamma S^2}{2}(\sigma_r^2-\sigma_i^2)dt$ [D2]. **A sizing rule that equalises $\Gamma$ across two legs at different underlying levels does not equalise their P&L per unit of variance spread.**

**INFERENCE:** in a rates application the analogue of $S^2\Gamma\sigma^2$ under a normal/bp-vol convention is $\Gamma_y \sigma_{bp}^2$ (the $S^2$ disappears because bp vol is already absolute rather than proportional). None of the seven sources is in rate space, and none states this; it follows from their lognormal-vs-normal distinction, not from their text.

### 7.2 Use the implied-vol gamma as the weight

D5 is explicit that the gamma multiplying the variance difference is $\Gamma^{(i)}$, computed at implied: *"times the current gamma (computed using the implied volatility)"*. D6's Quantuple writes it into the notation: $0.5\,\Gamma(S,\sigma_i)\,S^2(\ldots)$. **Do not weight by a realized-vol or historical gamma.**

### 7.3 Size the expectation with $\sigma_r^2$; expect the realization to be the squared return

The two forms and their exact status are in §1.5. $\tfrac12\Gamma S^2(\sigma_r^2-\sigma_i^2)dt$ is *"an average P&L rather than an exact one … it should agree with your other formula on average but not each day"* [D6, Mark Joshi]; the per-step truth is $0.5\Gamma(S,\sigma_i)S^2((dS/S)^2 - \sigma_i^2 dt)$ [D6, Quantuple].

**Practical consequence, supported by D6's question itself:** a sizing calculation done in the average form and then compared against a realized daily P&L series will look broken — *"my daily PnLs range wildly, yet the values given by above formula remain somewhat small (< 1)"* — while *"the aggregate results do"* match. **If a sizing harness reports a smooth daily P&L, it is computing the ex-ante form and not the realization.**

### 7.4 One scalar size cannot control the outcome, because the weight is path-dependent

D5: *"While $\mathrm{d}\Pi_t$ is deterministic, the overall hedging profit and loss over the lifetime of the option is path-dependent. Its absolute value is higher for paths that fluctuate around the strike (where the gamma is higher)."* D3: P&L *"is dependent upon both the level **and path** of realised volatility"*, and gamma *"is highest near the strike of the option, closer to expiry, and with a lower implied volatility."*

**Therefore:** two positions sized to identical dollar gamma *today* deliver different P&L for the same realized variance spread if the path spends its time in different regions. Sizing is a statement about $t_0$ only.

### 7.5 Rehedge frequency is part of the sizing decision, not separable from it

D1's whole answer. Gamma P&L is quadratic in the increment: half a break-even move yields **one quarter** of the break-even P&L ($\Gamma=10$, $\delta S_{BE}=1$: full move → $10\times1=10$; half move → $5\times0.5=2.5$). *"if your hedging strategy is to lock in the profit more frequently, you need a larger number of smaller moves and the total move you need will be bigger than one break-even move."*

**A sizing rule quoted per-day at a daily rehedge is not the same rule at an intraday rehedge**, even holding the position constant.

### 7.6 The break-even hurdle does not depend on size

$\delta S_{Break-Even} = \sqrt{2\theta/\Gamma}$ [D1]; substituting $\theta = \tfrac12\Gamma S^2\sigma_i^2$ [D2 §1.3] gives $\delta S_{BE} = S\sigma_i\sqrt{\delta t}$ — **INFERENCE** (§2.4), the substitution is not performed in any source. If it holds, $\Gamma$ cancels: **size scales the P&L, it does not move the hurdle.** The hurdle is set by $\sigma_i$ and the rehedge interval alone. That separates two decisions that are easy to conflate: *whether* the trade is on the right side of break-even (a function of $\sigma_i$ vs expected realized) and *how much* it pays (a function of dollar gamma).

### 7.7 Fixed vs floating hedging vol changes what the terminal P&L is a function of

- **Fixed hedging vol:** terminal P&L is **not implied-vol-path-dependent**; the clean $\tfrac12(\sigma_r^2-\sigma_i^2)S^2\Gamma\,dt$ identity holds because $d\sigma = 0$ kills the $vega \times d\sigma$ term [D4 — `Clement`'s comment for the claim, `julien`'s comment for the mechanism, §3.2–3.3]. Cost: *"your prices won't be marked to the market anymore"* [D4, `Quantuple`], and you have *"delayed taking higher order PnL and hedging the associated change in risk"* [D3].
- **Floating hedging vol:** you take vega m2m P&L immediately, your delta picks up a vanna contribution (*"a change in delta on top of your gamma (dDelta/dVol, or vanna)"*), and you face *"a higher theta bill and lower gamma going forward"* [D3]. Terminal P&L becomes IV-path-dependent [D4].
- **Neither choice moves the expectation.** *"your expected p/l from delta hedging is the same, regardless of what vol you use at each step"* [D4, `dm63`]; *"Expected (under the risk neutral measure) PnL is always the same whether you hedge or not: this is because the (discounted) hedging portfolio is a martingale. As you pointed what will depend on the hedging strategy is the PnL distribution."* [D4, `Antoine Conze`]; *"the expected P&L at maturity is very, very close with different vols used. The expected max/min, and standard deviation of profits will vary, though (higher vol used, higher max profit)."* [D3, `phlsmk`].

**So the hedging-vol choice is a variance-of-outcome decision, not an expected-value decision.** A sizing rule that optimises expected P&L is indifferent to it; a sizing rule with a risk budget is not.

### 7.8 Which hedging vol suits which path shape

Verbatim from D3, the only source that states the trade-off directionally:

> a higher vol (positive vega PnL upfront, higher theta bill, less gamma) would benefit you **if realised changes in the underlying ended up being evenly distributed in time and magnitude**, and a lower vol (negative vega PnL upfront, lower theta bill, more gamma) would ultimately benefit you **if the realised changes were large and centered around the strike near expiry**.

Also D4 `dm63`: hedging at a vol far from IV in *either* direction widens the P&L distribution; the degenerate case (*"using a zero vol to hedge would result in no delta hedging p/l on any day except the days you cross the strike"*) is maximally path-dependent.

### 7.9 A gamma-neutral construction does not stay gamma-neutral

D7 is the direct warning, and it is about exactly this shape of trade (a spread whose gamma has been neutralised so that a *different* second-order term carries the thesis):

> The strategy may start gamma-neutral but don't ignore the impact of **Gamma-speed (third derivatives)**. In turbulent markets, on the downside you are getting caught short gamma … **the strategy -though initially gamma neutral with negligible Volga impact- can quickly turn into a leveraged directional bet.**

**INFERENCE:** a convexity-adjustment leg sized against a butterfly is a two-legged structure whose intended exposure is the residual after a first-order cancellation. D7's failure mode — the neutralised order re-emerging through the next derivative under stress — is the generic hazard of that construction, not a fact about risk reversals specifically. The sources support the mechanism; the transfer to a CA/fly pair is mine.

### 7.10 The residual/recalibration term can consume the thesis

D7's measured result: **MTM** (P&L from remarking the skew and vol-of-vol parameters) *"brings a steady decay … it basically eats up the PnL from Cross Gamma Theta since 2018."* The betas quantify it: 1.05 / $R^2$ 76% against the vega-hedged P&L, but 2.38 / $R^2$ 57% against total P&L (§6.2).

**INFERENCE:** the analogue for a CA leg is that the P&L attributable to re-fitting whatever curve/vol object prices the adjustment is a term in its own right, with a sign (a decay) rather than zero mean. D7 shows a case where the author of the strategy asserted it was negligible and a replication found it was not.

### 7.11 Costs are quoted against the same yardstick as the edge

D7, quoting Bergomi's own footnote: *"factoring in a bid/offer spread of **0.2 points of volatility on each leg** of our spread position **wipes out the strategy's P&L**."* And D1's structural result (§7.5) means the cost scales with rehedge count while the gamma P&L per rehedge falls quadratically — **more frequent rehedging pays proportionally less per hedge while costing the same per hedge.**

### 7.12 A delta-hedged long-convexity position can lose more than its premium

D3: *"If you buy an option, delta hedge it to expiry, can you lose more money than your premium? **Yes!**"* — worked: 3-month 37.00 strike 5-delta call on INTC at 0.05, spot 35, stock sideways then instantly to 36.99 into expiry, expires worthless, *"You've lost your premium, the option has expired worthless, and you've lost money on your delta hedge."*

**A sizing rule that treats the premium as the maximum loss on a delta-hedged convexity leg is wrong.**

### 7.13 The "richness" that motivates the trade may be a model artefact

D7 `Frido`: SSR $\to 2$ as $T\to 0$ **only if $H = 0.5$**; in general $\mathrm{SSR}_{T\to0} = H + \tfrac32$, so for rough vol ($H < 1/2$) the SSR is below 2 — *"what may be perceived as an 'arbitrage' (ie empirical is less than 2) may not be an arbitrage at all if vol is rough."*

**INFERENCE:** the general lesson — that the reference value against which a structure is judged rich is itself a model output with a free parameter, and mis-specifying that parameter manufactures apparent edge — transfers directly to a convexity adjustment measured against a model-implied fair value. The specific SSR/Hurst result does not transfer; it is a statement about equity skew dynamics.

### 7.14 What the sources do NOT support

Stated explicitly so the sizing rule does not over-claim:

- **No source gives a rates convexity-adjustment formula**, a swap-butterfly hedge ratio, or any DV01/PV01-based sizing rule. The single mention of bonds in the entire set is D2's parenthetical *"this is true for any asset, including Bonds"* about long gamma costing money.
- **No source addresses cross-gamma between two different underlyings** (which is what a CA leg vs a fly of a different tenor structurally involves). D7's "Cross Gamma" is $dS \cdot d\mathrm{ATM}$ — spot against that same underlying's own vol — not two rate points against each other.
- **No source quantifies the correct rehedge frequency.** D1 establishes the *direction* (more frequent ⇒ larger total move needed) without an optimum.
- **No source resolves whether fixed or floating is "right".** D3 says *"you'd always want to use the correct implied vol"* for a portfolio/market-making context; D4's thread establishes that fixed removes the IV-path dependence of terminal P&L. These are answers to different questions, and both are stated in the set.