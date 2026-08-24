# Gamma P&L vs Vega P&L — verbatim algebra from six Quantitative Finance Stack Exchange sources

> **Provenance note.** None of the six requested `.md` files exist. `C:/Users/chris/Downloads/convexityrv_markdown/` contains 97 files and none of the six named ones — the PDF→markdown conversion was never run for these. All six source PDFs **do** exist in `C:/Users/chris/Downloads/convexityrv/`, and I read them directly with the PDF reader. Page counts: Link between Vega and Gamma (3pp), Option: link between Vega and Gamma (7pp), Long Gamma vs Vega (4pp), Gamma Pnl vs Vega Pnl (4pp), Vol/Gamma/Vega essentially all the same (2pp), Realizing the same PnL as Gamma Vs Vega (4pp). Attribution below uses the document titles exactly as given in the task.

---

## 1. The conversion identity: Vega = σ·S²·τ·Gamma

This single identity appears, independently derived, in **four** of the six documents. It is the only sizing rule the sources state.

### 1.1 `options - Link between Vega and Gamma`

Question (Trajan, asked Mar 16 2016, 16 votes, 21k views) quotes **Taleb, *Dynamic Hedging***:

> "The vega is the integral of the gamma profits ( ie expected gamma rebalancing P/L) over the duration of the option at one volatility minus the same integral at a different volatility…Mathematically, it is:
>
> **Vega = σtS²Gamma**
>
> where *S* is the asset price, *t* the time left to expiration and *σ* the volatility."

Asker's complaint, verbatim: "I cannot understand the first sentence because it gives no indication of which volatilities to pick nor what the integrand of the integral would be. Shortly after Taleb states the formula above, again no justification as to where it came from."

**Gordon's answer (15 votes, accepted):** "Under the Black-Scholes model,

$$\text{Gamma} = \frac{N'(d_1)}{S\,\sigma\,\sqrt{T-t}}$$

$$\text{Vega} = S\,N'(d_1)\,\sqrt{T-t}.$$

Then, it is easy to see that

$$\text{Vega} = S^2\,\sigma\,(T-t)\,\text{Gamma}."$$

Gordon in comments (Mar 16 2016 at 19:34), on the *integral* half of Taleb's claim: "For the first part, it is pretty trick. See Peter Carr's 'FAQ in option pricing theory', and a longer discussion is in Marc Henrard's 'Parameter risk in the Black & Scholes model'."

**XXXXXXX answer (1 vote, Mar 2 2024):** "I believe in its most fundamental form it is best to internalize that the expected gamma rebalancing P/L = Option price at one volatility. Thus the difference of the option prices at different volatilities by this interpretation shall be the vega, or the sensitivity of an options price to a change in implied vol."

### 1.2 `options - Long Gamma vs Vega`

**Quantuple's answer (11 votes):** "Vega (denoted by ν in what follows) is the *first order* sensitivity of the option price with respect to volatility σ. Gamma (denoted by Γ in what follows), is the *second order* sensitivity of the option price with respect to the underlying spot price S.

Because for a semi-martingale $(S_t)_{t\ge 0}$ there is a direct link between the variance of the random variable $S_t$ for any fixed $t$ and its quadratic variation over $[0,t]$, it is only logical that there exists a link between Vega and Gamma.

Under BS assumptions, one can show that for an option evaluated at $t$ with time to maturity $\tau = T - t$

$$\nu(\tau) = \Gamma(\tau)\,\sigma\,S_t^2\,\tau$$

see Appendix A of Chapter 5 of Bergomi's book 'Stochastic Volatility Modeling' for a demonstartion and this Wiki page to see that it indeed holds under BS."

**Caveat on scope of the identity** — Hans, comment (May 11 2023): "Bergomi's derivation relies on the volatility being independent of $S$, so it is not different from the Black-Scholes formula."

The answer also carries surface plots of $\nu(\tau,S)$ and $\Gamma(\tau,S)$ over spot 50–150 (K=100) and $\tau\in[0,1]$: vega is a broad hump peaking at large $\tau$, ATM (scale to ~40); gamma is a narrow spike at $S\to K$, $\tau\to 0$ (scale to ~0.3). Isoline panels show gamma's contours collapsing onto the strike as $\tau\to0$ while vega's stay wide.

### 1.3 `options - Gamma Pnl vs Vega Pnl` — the identity used *inverted*, as a hedge ratio

Gordon writes it as a substitution for gamma: "$\theta \approx -\tfrac{1}{2}\gamma S^2\sigma^2$ and $\gamma = \frac{\nu}{S^2\sigma T}$; see, for example, Black–Scholes model."

### 1.4 `black scholes - Realizing the same PnL as Gamma Vs Vega`

**Kurt G.'s answer (2 votes):** "In the Black Scholes model with continuous dividend yield $q$ the following formulas hold for calls and puts:

$$\text{gamma}\quad \partial_x^2 C(t,S_t) = e^{-q(T-t)}\frac{\phi(d_1)}{S_t\,\sigma\,\sqrt{T-t}},$$

$$\text{vega}\quad \partial_\sigma C(t,S_t) = S_t\,e^{-q(T-t)}\,\phi(d_1)\,\sqrt{T-t}.$$

- Because $d_1 = \pm\frac{\ln(S_t/K)+\sigma^2(T-t)/2}{\sigma\sqrt{T-t}}$ the vega depends nonlinearly on vol. Hence, even the simplistic PnL $\text{vega}\cdot(\sigma - s)$ depends nonlinearly on $\sigma$.
- There is a simple relationship $S_t^2\,\partial_x^2C(t,S_t)\,\sigma(T-t) = \partial_\sigma C(t,S_t)$ between gamma and vega."

---

## 2. The exact P&L decomposition and the gamma-P&L integrand

### 2.1 `options - Gamma Pnl vs Vega Pnl` — Gordon (27 votes, accepted, +50 bounty). The canonical chain.

Question (Trajan, May 4 2018, 23 votes, 36k views), verbatim including its own erroneous formula: "Why does Gamma Pnl have exposure to realised volatility, but Vega Pnl only has exposure to implied volatility? I am confused as to why gamma pnl is affected (more) by IV and why vega pnl isnt affected (more) by RV? Essentially how do you show what gamma pnl will be mathematically and how do you show what vega pnl will be? I believe that **gamma pnl is spot x (vega x IV - RV)** [sic — this is the claim Gordon's answer corrects; Gordon asks in comments 'Where did you get this? Can you please provide us the source?']. Also does gamma pnl usually dominate (in $ terms) the vega pnl of an options, as most literature is on gamma pnl?"

Gordon's answer:

"For an option with price $C$, the P&L, with respect to changes of the underlying asset price $S$ and volatility $\sigma$, is given by

$$P\&L = \delta\Delta S + \frac{1}{2}\gamma(\Delta S)^2 + \nu\Delta\sigma,$$

where $\delta$, $\gamma$, and $\nu$ are respectively the delta, gamma, and vega hedge ratios. Then it is clear the vega P&L has exposure to the change of the implied volatility $\sigma$. Note that, for the gamma P&L,

$$\frac{1}{2}\gamma(\Delta S)^2 = \frac{1}{2}\gamma S^2\,\frac{1}{\Delta t}\left(\frac{\Delta S}{S}\right)^2\Delta t,$$

where $\frac{1}{\Delta t}\left(\frac{\Delta S}{S}\right)^2$ is the realized variance, and $\sqrt{\frac{1}{\Delta t}\left(\frac{\Delta S}{S}\right)^2}$ is the realized volatility. To see why $\sqrt{\frac{1}{\Delta t}\left(\frac{\Delta S}{S}\right)^2}$ is the realized volatility, we assume that, heuristically,

$$dS_t = S_t\left(r\,dt + \sigma_{Re}\,dW_t\right),$$

where $\sigma_{Re}$ is the realized volatility and $\{W_t, t\ge0\}$ is a standard Brownian motion. Then

$$\sqrt{\frac{1}{\Delta t}\left(\frac{\Delta S}{S}\right)^2} \approx \sigma_{Re}.$$

Consider the delta neutral portfolio $\Pi = C - \frac{\partial C}{\partial S}S$. Assuming that the interest rate and volatility are not change during the small time period $\Delta t$. The P&L of the portfolio is given by

$$P\&L^\Pi_{\Delta t} = \frac{1}{2}\gamma(\Delta S)^2 + \theta\Delta t,$$

where $\theta$ is the theta hedge ratio. For small interest rate, which we assume to be zero, $\theta \approx -\frac{1}{2}\gamma S^2\sigma^2$ and $\gamma = \frac{\nu}{S^2\sigma T}$; see, for example, Black–Scholes model. Then

$$\begin{aligned}
P\&L^\Pi_{\Delta t} &\approx \frac{1}{2}\gamma S^2\frac{1}{\Delta t}\left(\frac{\Delta S}{S}\right)^2\Delta t - \frac{1}{2}\gamma S^2\sigma^2\Delta t\\
&\approx \frac{1}{2}\gamma S^2\sigma_{Re}^2\Delta t - \frac{1}{2}\gamma S^2\sigma^2\Delta t\\
&= \frac{1}{2}\gamma S^2(\sigma_{Re}+\sigma)(\sigma_{Re}-\sigma)\Delta t\\
&\approx \gamma S^2\sigma(\sigma_{Re}-\sigma)\Delta t \qquad \text{(assuming that }\sigma_{Re}\approx\sigma)\\
&= \frac{\nu}{T}(\sigma_{Re}-\sigma)\Delta t.
\end{aligned}$$

The cumulative P&L, over the interval $[0,T]$, is then $\nu(\sigma_{Re}-\sigma)$."

**This is the operative result for sizing.** Three things to note, all inside the verbatim chain:
- The exact instantaneous gamma-vs-theta P&L is **variance-linear**: $\tfrac12\gamma S^2(\sigma_{Re}^2-\sigma^2)\Delta t$.
- It is converted to **vol-linear** only by factorising $(\sigma_{Re}^2-\sigma^2)=(\sigma_{Re}+\sigma)(\sigma_{Re}-\sigma)$ and then replacing $(\sigma_{Re}+\sigma)\to 2\sigma$, explicitly flagged "(assuming that $\sigma_{Re}\approx\sigma$)".
- Only then does $\gamma=\nu/(S^2\sigma T)$ collapse it to $\frac{\nu}{T}(\sigma_{Re}-\sigma)\Delta t$, integrating to $\nu(\sigma_{Re}-\sigma)$ over $[0,T]$.

**dm63's answer (8 votes)** in the same document: "Gamma p/l is by definition the p/l due to realized volatility being different from implied. Vega p/l is by definition the p/l due to moves in implied volatility. The second part of the question you have answered yourself. **Short dated options have more gamma exposure, long dated options have more vega exposure.**"

Comment, tommylicious (Mar 14 2024): "best explanation of getting from gamma term in ito expansion to the gamma pnl formula i've seen & frankly maybe the only one."

### 2.2 `volatility - Option: link between Vega and Gamma` — Newquant (2 votes, accepted). The same chain, hedged-at-implied.

Question (Enrico, May 30 2024, 3 votes) quotes **Taleb, *Dynamic Hedging*, Chapter 9**:

> "The vega is the integral of the gamma profits over the duration of the option at one volatility minus the same integral at a different volatility. The vega P/L that results from the volatility going higher for a long option holder should be equal to the expected sum of the gamma profits over the period should the market goess his way."

nbbo2 comment: "Briefly 'gamma p&L' refers to the P&L on a dynamic replication strategy, a strategy of trading the underlying to maintain the correct delta over time. Sometimes referred to as gamma scalping (q.v.)."

Newquant: "When you hedge an option's delta at implied volatility, the resulting PnL over timestep, dt, is:

$$PnL = \left(\Delta_i * dS + \frac{\Gamma_i dS^2}{2} + \Theta * dt\right) - \Delta_i * dS$$

Leaving:

$$\frac{\Gamma_i dS^2}{2} + \Theta * dt$$

In the BSM framework, where $\sigma_i == \sigma_r$, Theta = Gamma, but when there is a mismark between $\sigma_i$ & $\sigma_r$, the resulting PnL over timestep, dt, is

$$\frac{\Gamma_i * S^2}{2} * (\sigma_r^2 - \sigma_i^2) * dt$$

Which translates to the difference between realised and implied variance over dt, scaled by the cash gamma priced at implied volatility. Where the gamma is negative for a short option postion and vice versa for a long. So the cumulative PnL becomes:

$$\sum_{t=0}^{T}\frac{\Gamma_{i,t} * S_t^2}{2} * (\sigma_{i,t}^2 - \sigma_i^2) * dt$$

[**sic** — the first vol in the bracket is printed $\sigma_{i,t}$; from the preceding line and the following integral it must be $\sigma_{r,t}$, i.e. realized. Treat as a typo.]

As you increase the hedging frequency, reducing dt, in the limit at $dt \to 0$, the cumulative PnL can be written:

$$\int_t^T \frac{\Gamma_{i,t} * S_t^2}{2} * (\sigma_{i,t}^2 - \sigma_i^2) * dt$$

Which leads us to Taleb's statement that Vega PnL is the integral of the gamma PnL over T-t at two different volatilties.

One can also plot out the expected PnLs; **Vega * $(\sigma_i - \sigma_r)$, Cash Gamma * $(\sigma_i^2 - \sigma_r^2)$** to find that vega PnL locally approximates the expected gamma PnL."

### 2.3 The ATMF closed-form comparison (same document, Newquant) — where "the same P&L" is asserted

"Why? Take the BSM gamma formula:

$$\Gamma = \frac{n(d1)}{S * \sigma * \sqrt{T}}$$

Then let's approximate for an ATMF option, where d1 = 0:

$$\Gamma = \frac{1}{S * \sigma_i * \sqrt{2*\pi*T}}$$

Integrating w.r.t T:

$$\int \frac{1}{S*\sigma_i*\sqrt{2*\pi*T}}\,dT = \frac{\sqrt{2T}}{S*\sigma_i*\sqrt{\pi}}$$

So, the approximate Gamma PnL (0.5 * Cash Gamma * (rv^2 - iv^2)) simplifies to:

$$\frac{S*\sqrt{T}}{\sigma_i*\sqrt{2\pi}} * (\sigma_r^2 - \sigma_i^2)$$

So where $\sigma_i \approx \sigma_r$, this approximates to:

$$\frac{S*\sqrt{T}}{\sqrt{2\pi}} * (\sigma_r - \sigma_i)$$

BSM vega is $Vega = S * n(d1) * \sqrt{T}$, thus Vega PnL is $S * n(d1) * \sqrt{T} * (\sigma_r - \sigma_i)$, and we again approximate the vega to be the vega at the ATMF strike (approximating n(d1) to $1/\sqrt{2\pi}$), we are left with:

Vega PnL = $\frac{S\sqrt{T}}{\sqrt{2\pi}} * (\sigma_r - \sigma_i)$

Comparing with the gamma PnL approximation:

Gamma PnL = $\frac{S\sqrt{T}}{\sqrt{2\pi}} * (\sigma_r - \sigma_i)$

**So locally for ATMF options, Vega PnL = Gamma PnL.** Where Vega PnL is the change in option value marked at different IVs, and Gamma PnL is the integral (realistically a cumulative sum) of spread between realised and implied variance, scaled by cash gamma multiplied by dt."

> **⚠ Internal factor-of-2 discrepancy in this source, flagged.** The step from $\frac{S\sqrt T}{\sigma_i\sqrt{2\pi}}(\sigma_r^2-\sigma_i^2)$ to $\frac{S\sqrt T}{\sqrt{2\pi}}(\sigma_r-\sigma_i)$ drops a factor of 2: $(\sigma_r^2-\sigma_i^2)=(\sigma_r+\sigma_i)(\sigma_r-\sigma_i)\approx 2\sigma_i(\sigma_r-\sigma_i)$, so the line should read $\frac{2S\sqrt T}{\sqrt{2\pi}}(\sigma_r-\sigma_i)$. Everything upstream of that line checks out arithmetically: $\int_0^T\Gamma(\tau)d\tau = \frac{2\sqrt T}{S\sigma_i\sqrt{2\pi}} = \frac{\sqrt{2T}}{S\sigma_i\sqrt\pi}$ (correct), and $\tfrac12 S^2\times$ that $=\frac{S\sqrt T}{\sigma_i\sqrt{2\pi}}$ (correct).
>
> **INFERENCE (mine, not in any source) — resolution, and it matters for sizing:** the factor 2 is not a pure algebra slip whose "correction" should be used; it is the signature of a *modelling* difference between this derivation and Gordon's. Newquant integrates the **frozen-ATM gamma profile** $\Gamma(\tau)\propto\tau^{-1/2}$ over the whole life, and $\int_0^T\tau^{-1/2}d\tau = 2\sqrt T = 2\,T\cdot T^{-1/2}$, i.e. twice "gamma-at-inception × T". Gordon instead **freezes $\gamma$, $S$, $\nu$ at their $t=0$ values** and integrates $\Delta t$ to $T$, landing on $\nu(\sigma_{Re}-\sigma)$ with no 2. Gordon's answer is the one consistent with $C(\sigma_r)-C(\sigma_i)\approx\nu\cdot\Delta\sigma$; the frozen-ATM time-integral overstates because in expectation spot diffuses off the strike and the realised average cash gamma is *lower* than the always-ATM profile. **An implementer who sizes off the time-integral of ATM gamma will be 2× the vega-consistent size.** Use $\nu = \sigma S^2\tau\Gamma$ evaluated once, not $\int\Gamma\,d\tau$.

### 2.4 `black scholes - Realizing the same PnL as Gamma Vs Vega` — Kurt G.'s exact hedging-error identity

"It is well known that in the Black Scholes model with implied vol $s$ and realized vol $\sigma$ the PnL from delta hedging a long position in an option is

$$C(T,S_T) - \Pi_T = \frac{\sigma^2 - s^2}{2}\int_0^T S_t^2\,\partial_x^2 C(t,S_t)\,dt. \qquad (1)$$

(see this post). The formula you use in Method 2 is similar but not exactly equal to this. The option price $C(t,S_t)$ in (1) uses implied vol $s$ throughout. If I understand Method 1 correctly you use the realized vol $\sigma$ to calculate $C(t,S_t)$ throughout and otherwise perform the same hedging strategy. This means that in the derivation that led to (1) we have $\sigma = s$ and therefore a **zero** hedging PnL. That's also intuitively clear because knowing the realized vol $\sigma$ in advance and using that to price and hedge the option will exactly replicate the final payoff $C(T,S_T)$. I do not think that the expectation of (1) is zero. In fact it is known that if the realized vol $\sigma$ is larger than the implied vol $s$ there is almost always a profit from the delta hedging strategy of a long gamma position."

Then, substituting the gamma↔vega identity into (1):

"We can therefore write (1) as

$$C(T,S_T) - \Pi_T = \frac{\sigma^2 - s^2}{2}\int_0^T \frac{\partial_\sigma C(t,S_t)}{\sigma(T-t)}\,dt. \qquad (2)$$

which is similar but not exactly equal to your Method 1."

Note that (1) and (2) carry the **variance** difference $\frac{\sigma^2-s^2}{2}$ outside the integral — no $\sigma_r\approx\sigma_i$ approximation has been made at this point. The whole vol-space representation is obtained only by dividing the vega integrand by $\sigma(T-t)$, which reintroduces the maturity weighting.

---

## 3. When gamma P&L and vega P&L are THE SAME, and when they diverge

### 3.1 Conditions for equality, stated by source

| Condition | Stated in | Verbatim / near-verbatim |
|---|---|---|
| $\sigma_{Re}\approx\sigma$ (realized close to implied) | `options - Gamma Pnl vs Vega Pnl` (Gordon) | "$\approx \gamma S^2\sigma(\sigma_{Re}-\sigma)\Delta t$ **(assuming that $\sigma_{Re}\approx\sigma$)**" |
| $\sigma_i\approx\sigma_r$, ATMF strike, $d_1=0$, $n(d_1)\to1/\sqrt{2\pi}$ | `volatility - Option: link between Vega and Gamma` (Newquant) | "So **locally** for ATMF options, Vega PnL = Gamma PnL." |
| Vol levels close enough that first order is exact | `volatility - Option: link between Vega and Gamma` (Arshdeep) | "$Vega * (Vol1 - Vol2) = C(t,S(t),vol1) - C(t,S(t),vol2)$ (1=2) where vol1 and vol2 are close enough for 1 and 2 to be the same." |
| Only **locally**, and only in **expectation** | `volatility - Option: link between Vega and Gamma` (Newquant) | "…to find that vega PnL **locally approximates** the **expected** gamma PnL." |
| Only in expectation; gamma path is path-dependent | `black scholes - Realizing the same PnL as Gamma Vs Vega` (asker, Method 2) | "my pnl will be path dependent, but the **expected** pnl would be…" |
| ATM options have no volga ⇒ price linear in vol | `black scholes - Realizing the same PnL as Gamma Vs Vega` (SwaptionGamma comment, Jul 30 2023) | "I was just thinking of atm options, which have **no volga & are linear in volatility**, so method 1 is a linear function of remarking the implied to the actual realized." |
| Gamma being highest ATM is what makes the two agree | `black scholes - Realizing the same PnL as Gamma Vs Vega` (dm63 comment, Feb 23 2022) | "gamma p/l would be quadratic if gamma were constant across all market prices, but it isn't. Gamma is high when the option is atm and lower everywhere else. **This results in the 2 methods agreeing.**" |

### 3.2 Divergence channels, stated by source

**(a) The $(\sigma_{Re}+\sigma)$ factor — the variance-vs-vol wedge.** From `options - Gamma Pnl vs Vega Pnl` (Gordon), before the approximation: $\frac12\gamma S^2(\sigma_{Re}+\sigma)(\sigma_{Re}-\sigma)\Delta t$. The vega-space form uses $2\sigma$ in place of $(\sigma_{Re}+\sigma)$. Equivalently, in `black scholes - Realizing the same PnL as Gamma Vs Vega`, Kurt G.'s (1) carries $\frac{\sigma^2-s^2}{2}$ exactly, with no linearisation.

**(b) Linear-in-vol vs quadratic-in-vol.** `black scholes - Realizing the same PnL as Gamma Vs Vega`, question setup by SwaptionGamma (5 votes), verbatim:

> "Consider a delta hedged option postion. Futhermore assume that I can perfectly forecast realized volatility over the life of the option. Vol I buy the option at = Implied Vol (IV). Realized volatility over the life of the option = Realized Vol (RV) Furthermore, suppose RV > IV. Now, there are 2 ways in which I can monetize RV being greater than IV.
>
> **Method 1->** I remark the vol of the option to RV (realize the pnl as vega PnL today). Then, given that I am heding the option using the correct realized volatility, my cumulative delta hedging pnl at expiry will be known, and should perfectly offset my theta. In this case, **PnL realized = Vega x (RV-IV)**. This pnl will be a **linear function of RV.**
>
> **Method 2->** I do not remark my vol, and delta hedge the option using the IV as the marked vol. In this case, of course, my pnl will be path dependent, but the expected pnl would be =
>
> **0.5 x \$Gamma x (RV-IV)**
>
> The gamma PnL, of course, is a **quadratic function of RV.**
>
> My questions are ->
> a. Is the pnl in method 1 = expected PnL in method 2?
> b. If yes, how is the PnL in method 1 a linear function of RV, while the PnL in method 2 a quadratic function of RV."

[**sic** on `0.5 x $Gamma x (RV-IV)`: the asker calls it "a quadratic function of RV" in the same breath, and every other source writes the cash-gamma term against $(\sigma_r^2-\sigma_i^2)$ — cf. Newquant's "the approximate Gamma PnL (0.5 * Cash Gamma * (rv^2 - iv^2))" and Gordon's $\frac12\gamma S^2(\sigma_{Re}^2-\sigma^2)\Delta t$. Read it as $0.5\times\$\Gamma\times(RV^2-IV^2)$.]

**(c) The worked numbers — this is the whole divergence in three lines.** Same document, "Elaborating on question b->", verbatim:

> "A common heuristic seems to be.
> I pay **100cents** for a swaption with **IV=2bp/day**
> If realized vol = **2.1bp/day**, total PnL = **10c**
> If realized vol = **2.2bp/day**, total PnL = **30c**
> So it's not a linear function of realized vol. But if I remark to RV and realized the PnL as a vega pnl, the pnl will be a linear function of RV (since an atm straddle is a linear function of volatility)."

*(+0.1bp/day of outperformance pays 10c; +0.2bp/day pays 30c, i.e. 3× not 2× — variance, not vol.)*

**(d) Vega itself is nonlinear in vol.** `black scholes - Realizing the same PnL as Gamma Vs Vega` (Kurt G.): "Because $d_1 = \pm\frac{\ln(S_t/K)+\sigma^2(T-t)/2}{\sigma\sqrt{T-t}}$ the vega depends nonlinearly on vol. Hence, even the simplistic PnL $\text{vega}\cdot(\sigma-s)$ depends nonlinearly on $\sigma$." SwaptionGamma's reply: "This is great - thank you. If vega is a non-linear function of vol, then of course, the inconsistency between method 1 and 2 is resolved."

**(e) Method 1's exact P&L is ZERO, not $\nu(RV-IV)$.** Kurt G.: pricing *and hedging* at the known realized vol makes $\sigma = s$ in (1), "and therefore a **zero** hedging PnL… knowing the realized vol $\sigma$ in advance and using that to price and hedge the option will exactly replicate the final payoff." I.e. the $\nu\times(RV-IV)$ is captured entirely as the mark-up at inception, and nothing further accrues.

**(f) Theta is the transfer mechanism.** `black scholes - Realizing the same PnL as Gamma Vs Vega`, will (comment, Jan 23 2022): "your first statement is correct. For the second, you will realise approximately the same on the delta hedging (you'll have slightly different deltas, but it will be close), **the main difference will be that you pay less theta over the life of the trade. The amount less you pay will be that same vega pnl in your first case.**" And: "if you take an out ofthe money option, then all the value it has will decay away as you head towards maturity. If you make that option more expensive by increasing the vol, then you're just going to decay away all that gain later."

**(g) Gamma P&L is never identically zero.** `volatility - Option: link between Vega and Gamma`, Arshdeep (comment, Jun 2 2024): "Gamma PnL is usually what we call the second term in the ito expansion. **It is never 0 unless the spot never moved or gamma is 0.** If you mean hedging error when realized vol is different, there is the formula. I don't think you can compute it, you can use MC." (Answering Enrico's "if the realized volatility is equal to the implied one… the gamma P/L are zero?" — Arshdeep: "Yes, though it is very theoretical.")

### 3.3 The maturity split — the structural reason a gamma leg and a vega leg are different instruments

- `options - Long Gamma vs Vega`, Alex C (comment, Feb 21 2018): "**Gamma increases at T->0 and S->K, Vega increases as T becomes large.** So they vary with maturity in different ways." Follow-up: "So the difference between the two is a function of time?" — Alex C: "I am not saying that. I only wanted to 'prove' to you that they are not the same thing."
- `options - Gamma Pnl vs Vega Pnl`, dm63: "Short dated options have more gamma exposure, long dated options have more vega exposure."
- `volatility - Option: link between Vega and Gamma`, JohnGalt (2 votes): "This is simple. If you are far away from maturity, your option price will more sensitive to volatility on your underlying, effective change on your underlying price won't have any significative impact. On the opposite, if the maturity is closer your option price will be more sensitive to effective change on the underlying price. for the volatility, since it has annual range, we are days before maturity, you can easily see it won't have much impact. **I like to see Gamma as 'realized volatility' and the Vega as 'gamma reserve'.**" And in comments (Jun 5 2024): "If the current volatility won't allow you to get back above the strike, you will have a big vega and a small gamma, because you hope for more volatility and since you are far away from strike a small effective change won't matter so much. on the opposite, if your volatility allows you to easily hit above the strike, you will care for effective change."

### 3.4 Long gamma ≠ long vega: constructions that separate them

- `options - Long Gamma vs Vega`, top answer: "**Long gamma is being long realized volatility. Long vega is being long implied volatility.** Long gamma positions benefit when realized volatility goes up or the actual underlying has volatility. Long vega positions benefit when the price of volatility goes up."
- `options - Long Gamma vs Vega`, AlRacoon (24 votes, accepted): "Being long plain vanilla options, one is long both gamma and long vega. However, this is not so if one starts to combine options in strategies. One can construct positions where one is long gamma and short vega. A simple example would be a simple calendar spread--if one is long an at-the-money call with short maturity, one is long gamma and long vega. If one shorts an at-the-money longer dated maturity call on the same underlying, one is short gamma and short vega. However, the short longer dated call will be less long gamma than the shorter dated one; and short more vega than the shorter dated one. The combined position will be long gamma and short vega. The position will benefit if realized volatility goes up before the shorter dated call expires, and if implied volatility goes down."
- `options - Vol, Gamma, Vega -- essentially all the same?`, user42108 (comment, 10 votes): "One way to think about it is that **trading vega is a bet on implied vol whereas trading gamma is a bet on realised vol.**"
- `options - Vol, Gamma, Vega -- essentially all the same?`, Chris Taylor (8 votes, accepted): "They are not the same, but they are related. Gamma is sensitivity to realized volatility. Vega is sensitivity to implied volatility. Vanilla options are always long gamma and long vega, so they are 'long vol' and saying 'I am a buyer of vol/gamma/vega' means that you are taking a position that benefits from a rise in volatility (either realized or implied). Although vanilla options are long both gamma and vega, they are generally **long in different amounts. Near expiry options have more gamma, and far expiry options have more vega.** That means you can construct a **long gamma/vega flat** portfolio by buying short-term options and hedging the vega with a short position in long-term options, or you can construct a **gamma flat/long vega** portfolio buy buying long-term options and hedging the gamma with short-term options. Each of these portfolios would be 'long vol' but one is only long gamma, and the other is only long vega."

---

## 4. The convexity / expectation-space argument (why vega exists at all)

`volatility - Option: link between Vega and Gamma`, Arshdeep (1 vote):

"We know by the link, the call valued at the incorrect vol (beta) loses gamma PnL. We know the call valued rightly loses no PnL (all strategies are fair in the risk neutral world). So a difference of call prices is the (expected) gamma PnL. The difference is vega times change in vol. This links vega to expected gamma PnL.

**I am also adding intuition, which is much simpler if you see prices as expectations**

Prices are expectations against density (payoff*mass). If you have a convex payoff (high gamma), then increasing volatility creates a larger price separation because it is taking advantage of the convexity to increase the overall value of the expectation.

Example: $Payoff: [1, 1, 3, 10, 20]$, $Density: [0, 0.33, 0.33, 0.33, 0]$ So expectation is $14/3$.

Now density: $[0.1, 0.1, 0.1, 0.1, 0.1]$ So expectation is $31/3$.

If the payoff was not convex (0 gamma), it would look like $[-1, 1, 3, 5, 7]$

and you can check that increasing vol makes no difference. So 'vega' is a way of taking advantage of gamma."

> **[sic] flag.** As rendered, the second density $[0.1,0.1,0.1,0.1,0.1]$ sums to 0.5, not 1. **INFERENCE:** the intended second density is almost certainly uniform $[0.2,0.2,0.2,0.2,0.2]$, giving $(1+1+3+10+20)/5 = 35/5 = 21/3$, i.e. "$21/3$" mis-rendered as "$31/3$". This reading is forced by the author's own linear-payoff check: with $[-1,1,3,5,7]$, the narrow density gives $(1+3+5)/3 = 3$ and the uniform density gives $(-1+1+3+5+7)/5 = 3$ — identical, exactly as claimed. Either way the qualitative point stands: widening the density lifts $14/3 \to$ a strictly larger number for the convex payoff and leaves the linear payoff at 3.

Arshdeep's other answer (2 votes) in the same document, the delta-hedged version of the same argument:

"$Vega * (Vol1 - Vol2) = C(t,S(t),vol1) - C(t,S(t),vol2)$ (1=2) where vol1 and vol2 are close enough for 1 and 2 to be the same. Now we delta hedge both calls at implied volatility. We ignore that change in delta and theta while shifting vol slightly as they are second order. Look at $dC(t,S(t),vol1) - dC(t,S(t),vol2) + delta*dS - delta*dS$ (3)… Integrate (3), and realize at expiry it is 0. So initial value equals the integral of (3), which the link shows to be gamma profits."

---

## 5. Every stated sizing rule, collected

There is exactly **one** sizing rule in these six documents, stated four times in four algebraically identical forms. Everything else is a condition on its validity.

$$\boxed{\;\nu = \sigma\,S^2\,\tau\,\Gamma \qquad\Longleftrightarrow\qquad \Gamma = \frac{\nu}{S^2\,\sigma\,\tau}\;}$$

| Form | Source | Notation used |
|---|---|---|
| $\text{Vega} = \sigma t S^2 \text{Gamma}$ | `options - Link between Vega and Gamma` (Taleb, quoted) | $t$ = time left to expiration |
| $\text{Vega} = S^2\sigma(T-t)\text{Gamma}$ | `options - Link between Vega and Gamma` (Gordon) | derived from the BS pair |
| $\nu(\tau) = \Gamma(\tau)\sigma S_t^2\tau$ | `options - Long Gamma vs Vega` (Quantuple) | $\tau = T-t$; Bergomi Ch.5 App.A |
| $\gamma = \dfrac{\nu}{S^2\sigma T}$ | `options - Gamma Pnl vs Vega Pnl` (Gordon) | used *as a substitution* mid-derivation |
| $S_t^2\partial_x^2C\cdot\sigma(T-t) = \partial_\sigma C$ | `black scholes - Realizing the same PnL as Gamma Vs Vega` (Kurt G.) | with continuous dividend yield $q$ |

The **P&L-level** sizing consequence, from `options - Gamma Pnl vs Vega Pnl` (Gordon): a delta-neutral gamma position held over $[0,T]$ earns cumulative $\nu(\sigma_{Re}-\sigma)$ — i.e. **a gamma position of $\gamma$ is, in expectation and to first order in $(\sigma_{Re}-\sigma)$, exactly a vega position of $\nu = \gamma\sigma S^2 T$.**

Two constraints on applying it:
1. **Validity constraint (Gordon, verbatim):** "(assuming that $\sigma_{Re}\approx\sigma$)". Outside that, use $(\sigma_{Re}+\sigma)$ not $2\sigma$, i.e. the exact ratio between the variance-space and vol-space P&L is $\frac{\sigma_{Re}+\sigma}{2\sigma}$.
2. **Scope constraint (Hans, `options - Long Gamma vs Vega`):** "Bergomi's derivation relies on the volatility being independent of $S$, so it is not different from the Black-Scholes formula." The identity is a Black-Scholes identity, not a model-free one.

---

## 6. Implications for sizing a convexity-adjustment leg against a swap butterfly

Ground rules for this section: claims traceable to a source are attributed; everything else is marked **INFERENCE**.

### 6.1 What the sources establish that carries over directly

1. **A pure-variance price and a vol-linear proxy are related by exactly one factor: $\sigma S^2 \tau$.** Sourced: `options - Link between Vega and Gamma` (Gordon; Taleb), `options - Long Gamma vs Vega` (Quantuple), `options - Gamma Pnl vs Vega Pnl` (Gordon), `black scholes - Realizing the same PnL as Gamma Vs Vega` (Kurt G.). There is no second, independent sizing rule in these documents.

2. **The two legs have identical P&L only under a named, checkable list of conditions** — realized close to implied ($\sigma_r\approx\sigma_i$), at-the-money-forward ($d_1=0$), *locally*, and *in expectation*, not path by path. Sourced: Gordon's "(assuming that $\sigma_{Re}\approx\sigma$)" and Newquant's "So **locally** for ATMF options, Vega PnL = Gamma PnL", plus Newquant's "vega PnL **locally approximates** the **expected** gamma PnL".

3. **The divergence is a variance-vs-vol wedge with an explicit size: $\frac{\sigma_r+\sigma_i}{2\sigma_i}$.** Sourced: Gordon's factorisation $\frac12\gamma S^2(\sigma_{Re}+\sigma)(\sigma_{Re}-\sigma)\Delta t$ and Kurt G.'s exact $\frac{\sigma^2-s^2}{2}$ prefactor in (1)/(2), which never linearises.

4. **The wedge is empirically large at small vol dislocations.** Sourced verbatim: `black scholes - Realizing the same PnL as Gamma Vs Vega` — 100c premium, IV 2bp/day; RV 2.1 → 10c; RV 2.2 → **30c**. A 2× move in the vol *differential* pays 3×. Any sizing rule fitted at one $(\sigma_r-\sigma_i)$ level will be wrong at another.

5. **A vol-space hedge is itself nonlinear in vol.** Sourced: Kurt G. — "even the simplistic PnL $\text{vega}\cdot(\sigma-s)$ depends nonlinearly on $\sigma$" via $d_1$. Mitigated but not eliminated at-the-money: SwaptionGamma's "atm options… have no volga & are linear in volatility"; dm63's "gamma p/l would be quadratic if gamma were constant across all market prices, but it isn't. Gamma is high when the option is atm and lower everywhere else. This results in the 2 methods agreeing."

6. **Maturity is the axis that separates the two exposures, and therefore the axis on which the hedge is constructed or broken.** Sourced: "Gamma increases at T->0 and S->K, Vega increases as T becomes large" (Alex C); "Short dated options have more gamma exposure, long dated options have more vega exposure" (dm63); Chris Taylor's explicit gamma-flat/vega-flat calendar constructions; AlRacoon's calendar spread that is *long gamma and short vega simultaneously*. Two instruments both described as "long vol" can be long opposite things.

7. **The frozen-gamma time integral and the point-evaluated identity are not the same number.** Sourced (as a discrepancy, not as a claim): `volatility - Option: link between Vega and Gamma` contains a factor-of-2 slip between $\frac{S\sqrt T}{\sigma_i\sqrt{2\pi}}(\sigma_r^2-\sigma_i^2)$ and $\frac{S\sqrt T}{\sqrt{2\pi}}(\sigma_r-\sigma_i)$; §2.3 above documents the arithmetic.

### 6.2 Mapping onto CA $= \tfrac12\sigma^2 T_1^2$ — all INFERENCE

Taking the task's convexity-adjustment formula $CA = \tfrac12\sigma^2T_1^2$ as given (I do not relitigate the convention; none of these six documents discusses futures/FRA convexity):

- **INFERENCE — the CA leg is a variance-space instrument, structurally identical to the $\tfrac12\gamma S^2(\sigma_r^2-\sigma_i^2)$ term.** $CA$ is exactly linear in $\sigma^2$ with $\partial CA/\partial(\sigma^2) = \tfrac12 T_1^2$. That is the same shape as Kurt G.'s (1), where the *entire* variance dependence sits in the prefactor $\frac{\sigma^2-s^2}{2}$ and the $T_1^2$ plays the role of $\int_0^T S_t^2\partial_x^2C\,dt$. The CA leg *is* the "$\$\Gamma$ leg" in the taxonomy of these documents.

- **INFERENCE — the CA leg's vega is $\partial CA/\partial\sigma = \sigma T_1^2$**, and this is the number to match against a vol-space proxy. Note it is the *direct analogue* of $\nu = \sigma S^2\tau\Gamma$: identifying $S^2\tau\Gamma \leftrightarrow T_1^2$ recovers exactly $\nu = \sigma\cdot(\text{variance-space sensitivity}\times 2)$… concretely, $\partial CA/\partial\sigma = 2\sigma\cdot\partial CA/\partial(\sigma^2)$, which is the same $2\sigma$ that Gordon substitutes for $(\sigma_{Re}+\sigma)$. **The $2\sigma$ conversion factor is the whole sizing rule.**

- **INFERENCE — a swap butterfly used as a "linear-space vol proxy" is a vol-space (vega-like) leg, and the mismatch against the CA leg is exactly the 10c/30c phenomenon.** If the butterfly's P&L is (approximately) linear in the vol/dislocation variable while the CA leg is linear in $\sigma^2$, then a ratio computed at one $\sigma$ is a *tangent*, not a hedge. Sizing by $\sigma T_1^2$ hedges the first-order move only; the residual is $\tfrac12 T_1^2(\Delta\sigma)^2$, positive for both signs of $\Delta\sigma$ — the CA leg keeps a convexity residual that no static linear proxy removes. Source-anchored: Gordon's $(\sigma_{Re}+\sigma)$ factor and the 100c/10c/30c worked example.

- **INFERENCE — the hedge ratio is $\sigma$-dependent and must be restated as $\sigma$ moves.** $\partial CA/\partial\sigma = \sigma T_1^2$ scales *with the level of vol*, so a ratio set at $\sigma_0$ is wrong by $\sigma/\sigma_0$ at a new level. This is the direct analogue of Gordon's $\gamma = \nu/(S^2\sigma T)$ carrying $\sigma$ in the denominator, and of Kurt G.'s $\partial_\sigma C/(\sigma(T-t))$ integrand in (2) carrying both $\sigma$ *and* a $1/(T-t)$ time weighting. A static contract-count ratio is a point-in-time linearisation, not a standing hedge.

- **INFERENCE — the $T_1^2$ vs $\tau$ maturity loading is the analogue of the gamma/vega maturity split, and is where a two-leg structure will leak.** The sources are unanimous that gamma-space and vega-space exposures load on maturity differently (Alex C, dm63, Chris Taylor, JohnGalt, and Quantuple's surface plots). The CA leg's $T_1^2$ is a *steep* maturity loading; a butterfly's vol sensitivity will not share it. Expect the two legs to agree at one point on the curve and diverge along it — precisely the mechanism by which AlRacoon's calendar spread ends up long gamma and short vega at the same time. **Do not assume a ratio fitted at one $T_1$ transports to another.**

- **INFERENCE, and the most actionable item — do NOT size the CA leg off a time-integral of a frozen ATM gamma profile; that is 2× too large.** Newquant's $\int_0^T\Gamma(\tau)d\tau$ with $\Gamma\propto\tau^{-1/2}$ gives $2\sqrt T$, i.e. twice "gamma-at-inception × T", while Gordon's frozen-greek route gives $\nu(\sigma_{Re}-\sigma)$ with no factor 2, and the latter is the one consistent with $C(\sigma_r)-C(\sigma_i)\approx\nu\Delta\sigma$. Use the identity evaluated once, $\nu = \sigma S^2\tau\Gamma$ (equivalently $\partial CA/\partial\sigma = \sigma T_1^2$), not an integral over the life. The source itself is internally inconsistent on this point (§2.3), so a naïve implementer reading Newquant's intermediate line would be 2× the vega-consistent size.

- **INFERENCE — decide up front whether you are monetising the CA leg by remarking or by carrying it, because the sources say those are different P&Ls.** `black scholes - Realizing the same PnL as Gamma Vs Vega` distinguishes Method 1 (remark to the correct vol, book $\nu\times(RV-IV)$ today, then earn *zero* further hedging P&L per Kurt G.) from Method 2 (carry at the old mark, path-dependent, with will's "the main difference will be that you pay less theta over the life of the trade"). A CA leg marked to a model $\sigma$ and a butterfly marked to market are on opposite sides of that distinction; their P&L timings will not line up even where the terminal totals do.

### 6.3 Explicitly NOT supported by these six sources

- Nothing in these documents addresses futures/FRA convexity, SOFR, swap butterflies, or any linear-rates proxy for vol. The entire application layer is inference by analogy from the Black-Scholes gamma/vega identity.
- No source gives a rule for choosing between variance-matching ($\partial/\partial\sigma^2$) and vol-matching ($\partial/\partial\sigma$) hedge ratios; they only establish that the two differ by $2\sigma$ (exactly $\sigma_r+\sigma_i$ before linearisation).
- No source quantifies the residual of a linear hedge against a variance leg over a realistic range of $\sigma$; the only empirical datapoint is the 100c / 10c / 30c heuristic, which is stated as "a common heuristic" and is not derived.
- The identity is Black-Scholes-specific: "Bergomi's derivation relies on the volatility being independent of $S$" (Hans, `options - Long Gamma vs Vega`). Any skew/smile dependence of the SOFR vol surface on the rate level breaks it and is out of scope of every source read here.
