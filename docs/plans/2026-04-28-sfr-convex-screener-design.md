# Design Doc: SOFR Convex Linear Structure Screener

**Owner:** Chris Lee
**Status:** Draft v1 — for implementation
**Audience:** Claude Code instance with access to existing research infra (curves + RN PDFs)
**Last updated:** 2026-04-28

---

## 0. TL;DR

Build a screener that ranks 3M SOFR futures **calendar spreads** and **butterflies** by the asymmetry of their **option-implied payoff distribution**. The premise: a linear structure inherits asymmetry from the risk-neutral PDFs of its constituent contracts. When constituent PDFs are skewed or have non-Gaussian tails, the structure's P&L distribution can be materially convex even though the structure itself contains no options. The output is a ranked list of structures where being right pays meaningfully more than being wrong loses, **before paying optionality premium**.

This is the practical answer to: *"I have a directional macro view. I don't want to trade vol. What's the highest-Sharpe linear expression?"*

---

## 1. Motivation

### 1.1 The problem this solves

A trader with a directional view in the front end has three families of expressions:

1. **Outright receive/pay** in a single contract (e.g., SFRZ6).
2. **Curve or fly** in linear space (e.g., SFRZ6/SFRM7 calendar, SFRZ6/M7/Z7 1:-2:1 fly).
3. **Options structures** (receivers, payer flies, risk reversals).

(3) explicitly buys/sells convexity and pays/receives premium. It is the cleanest way to express asymmetric views, but the trader pays for it in vega and theta.

(1) and (2) are linear and carry no option premium, but their **payoff distributions are not symmetric** when the underlying contracts have skewed RN PDFs. The typical desk doesn't quantify this — they eyeball "feels asymmetric" or rely on point-estimate carry/roll. There's an opportunity to systematize.

### 1.2 The concrete intuition

Take the canonical example we discussed:

- Jun26 €STR priced ~22bp of hikes against a 25bp baseline hike. Downside ~3bp, upside ~7–12bp on a dovish surprise. JPM tactically receives — not because they think Lagarde is dovish in absolute terms, but because the **payoff distribution of receiving 22bp into an event with bounded right tail is asymmetric**.

The same logic applies in SOFR futures, but with one extra layer: a **butterfly or calendar** between two contracts inherits the asymmetry of *both* PDFs, plus their joint structure. A fly centered on a contract whose RN PDF is highly skewed will itself have a skewed payoff distribution — even though the trade is constructed entirely from linear instruments.

### 1.3 Why now

Per JPM's published BL-extracted distributions for Z6 and M7 (their 4/24/26 weekly), a Fed hold is the modal outcome through mid-2027 with **significant extended left and right tails**. That fat-tailed environment is exactly where linear-space convexity should be detectable. If the screener returns nothing, that's also useful information — it tells you the linear structures are roughly fair and you need to either accept carry-and-pray or pay up for explicit optionality.

### 1.4 What this is not

- Not a directional signal generator. It does not tell you whether to be paid or received.
- Not an options screener. No vega, no theta, no premium accounting.
- Not a sizing engine. It outputs distributional metrics; sizing happens downstream.
- Not a backtester (Phase 1). Backtest hooks come later (Phase 4).

---

## 2. Inputs

The codebase has two existing capabilities the screener depends on. **Use existing modules — do not re-implement curve construction or BL extraction.** If their interfaces don't fit cleanly, write thin adapters.

### 2.1 SOFR futures curve

- **Universe:** All listed 3M SOFR futures with non-zero open interest. Minimum 16 contracts (whites + reds + greens + blues). Each contract identified by IMM code (e.g., `SFRZ6`, `SFRH7`).
- **Per contract:** mid price, settlement, expiry date, underlying reference period, DV01 (constant $25/bp/contract for SR3), open interest, recent daily returns (60d minimum for correlation estimation).
- **Curve-level:** continuous OIS forward curve for carry/roll computation.

### 2.2 Risk-neutral PDF per contract

- **Method:** Breeden-Litzenberger applied to options on 3M SOFR futures.
- **Output:** Discretized RN PDF over a grid of underlying outcomes. Default grid: ±200bp from current forward in 1bp bins. Wing extrapolation method (SVI or rational interpolation) should already be standardized in the existing module — do not re-derive.
- **Caveat to surface in output:** RN ≠ real-world. The screener reports RN-implied metrics. Real-world payoff distributions will differ by the price of risk. Document this explicitly.

### 2.3 Auxiliary

- **Realized vol per contract** (e.g., 21d std of daily yield changes) — for IV/RV cross-check.
- **Historical contract returns** — for empirical correlation matrix and historical payoff distribution comparison.

---

## 3. Methodology

### 3.1 Structure universe

For a universe of $N$ contracts $\{C_1, C_2, \ldots, C_N\}$ ordered by expiry:

**Calendar spreads** (long-short, signed): $\{(C_i, C_j) : i < j, j - i \in \{1, 2, 4\}\}$

**Butterflies** (1:-2:1, equally weighted by contracts; risk-weighted variants in Phase 2): $\{(C_i, C_j, C_k) : i < j < k, j - i = k - j, j - i \in \{1, 2, 4\}\}$

**Optional Phase 2 additions:**
- Risk-weighted flies (DV01-balanced).
- Condors (1:-1:-1:1).
- Cross-color flies (e.g., red/green/blue).

For SR3, every contract has the same $25/bp DV01, so equally-weighted flies are already DV01-neutral on a per-contract basis. This simplifies vs. Treasury futures.

### 3.2 Joint distribution construction

This is the load-bearing modeling assumption. **Implement in phases.**

**Phase 1 — Marginal-only with deterministic shifts (sanity baseline):**
For each grid scenario, assume all legs move by the same number of bp. Compute structure P&L as a function of that single shift. Use the marginal PDF of the *front* contract as the probability weight. This is wrong in general but useful as a sanity check and for fast iteration.

**Phase 2 — Gaussian copula on marginals (recommended default):**
- Marginals from BL extraction (the PDFs themselves).
- Correlation matrix: 60-day rolling correlation of daily yield changes across the curve.
- Sample $N_{\text{sim}} = 100{,}000$ joint draws via Gaussian copula.
- Compute structure P&L for each draw → empirical payoff PDF.

**Phase 3 — Empirical copula:**
- Use historical rank-correlations directly (empirical copula on past joint moves).
- More robust to tail dependence than Gaussian copula.
- Phase 3 because it requires careful handling of insufficient sample size in deferred contracts.

**Caveat to document in the output:** The joint distribution assumption is the largest single source of model error in this screener. Always report the structure under both Phase 1 (perfect correlation) and Phase 2 (Gaussian copula) so the user can see how much the joint structure matters. If the asymmetry signal is only present under one assumption, that's a warning flag.

### 3.3 Payoff distribution and metrics

Given a payoff PDF $f_{\Pi}(\pi)$ for structure $S$:

**Central moments:**
- $\mathbb{E}[\Pi]$ — expected P&L (risk-neutral), in bp of structure.
- $\sigma[\Pi]$ — standard deviation.
- Skewness and excess kurtosis.

**Tail / asymmetry:**
- $\mathbb{P}[\Pi > 0]$ — probability of profit.
- $\mathbb{E}[\Pi \mid \Pi > 0]$ and $\mathbb{E}[\Pi \mid \Pi < 0]$ — conditional expected gains and losses.
- **Asymmetry ratio:** $A = \mathbb{E}[\Pi \mid \Pi > 0] \cdot \mathbb{P}[\Pi > 0] \,/\, |\mathbb{E}[\Pi \mid \Pi < 0] \cdot \mathbb{P}[\Pi < 0]|$. $A > 1$ means upside contribution to EV exceeds downside contribution.
- 5th, 25th, 50th, 75th, 95th percentile P&L.
- **Tail ratio:** $|q_{95}(\Pi)| / |q_5(\Pi)|$.

**Carry-adjusted:**
- 3M roll-down P&L for the structure assuming the curve shape is unchanged. Add to $\mathbb{E}[\Pi]$ for "carry-adjusted EV."
- Sign of carry — flag structures where carry and asymmetry agree (both positive) vs. disagree.

### 3.4 IV/RV cross-check

For each constituent contract, report:
- Implied vol from BL inversion (or the 0DTE-equivalent from the option chain if available).
- 21d realized vol.
- IV/RV ratio.

**Use case:** If the screener flags a fly as having attractive asymmetry, but every constituent's IV/RV ratio is >1.5, the asymmetry may be partially "paid for" by rich vol — i.e., when realized distributions normalize toward historical, the asymmetry shrinks. Flag for user judgment, do not auto-filter.

### 3.5 Historical realized payoff distribution

For each candidate structure, compute the **realized 3M payoff distribution** over the past 5 years (rolling 3M windows of structure P&L). Compare RN-implied metrics to historical empirical metrics:
- If RN asymmetry ratio is much higher than historical, the implied distribution is unusually skewed — could be edge or could be a regime change.
- If they're aligned, the screener is finding a structurally asymmetric trade rather than a transient mispricing.

---

## 4. Scoring and ranking

**Composite score (default):**
$$\text{Score}(S) = w_1 \cdot \text{normalize}(A) + w_2 \cdot \text{normalize}(\mathbb{P}[\Pi > 0]) + w_3 \cdot \text{normalize}(\mathbb{E}[\Pi] + \text{carry}) + w_4 \cdot \text{normalize}(\text{tail ratio})$$

with default weights $(w_1, w_2, w_3, w_4) = (0.4, 0.2, 0.3, 0.1)$, normalization done cross-sectionally across the universe (z-score within the day's run).

**Filters (defaults; all user-tunable via config):**
- Min open interest per leg: 5,000 contracts.
- Min average daily volume per leg: 1,000 contracts (rolling 20d).
- Max bid-ask spread per leg: 0.5bp.
- Min absolute carry-adjusted EV: 0.5bp / 3M.
- Exclude structures where any leg has BL inversion warnings (negative density, wing extrapolation flag, etc.).

**Output two views:**
1. **Top 20 by composite score.**
2. **Top 10 by asymmetry ratio alone**, even if EV is negative — these are "if you have a directional view in this direction, this is the highest-Sharpe linear expression."

---

## 5. Output schema

### 5.1 Per-structure record

```json
{
  "structure_id": "SFRZ6_SFRM7_SFRZ7_FLY_1_-2_1",
  "structure_type": "butterfly",
  "legs": [
    {"contract": "SFRZ6", "weight": 1, "price": 96.45, "dv01": 25},
    {"contract": "SFRM7", "weight": -2, "price": 96.62, "dv01": 25},
    {"contract": "SFRZ7", "weight": 1, "price": 96.78, "dv01": 25}
  ],
  "current_level_bp": -3.5,
  "carry_3m_bp": 1.2,
  "rolldown_3m_bp": 0.8,

  "payoff_distribution": {
    "mean_bp": 2.1,
    "std_bp": 8.4,
    "skew": 0.65,
    "excess_kurt": 1.8,
    "p_profit": 0.58,
    "ev_given_profit_bp": 6.2,
    "ev_given_loss_bp": -3.6,
    "asymmetry_ratio": 1.72,
    "percentiles_bp": {"p5": -12.1, "p25": -3.2, "p50": 1.4, "p75": 6.8, "p95": 18.4},
    "tail_ratio": 1.52,
    "carry_adjusted_ev_bp": 4.1
  },

  "joint_assumption": "gaussian_copula_60d",
  "alternative_under_perfect_correlation": {
    "asymmetry_ratio": 1.31,
    "carry_adjusted_ev_bp": 2.8
  },

  "iv_rv_diagnostics": [
    {"contract": "SFRZ6", "iv": 0.82, "rv_21d": 0.71, "iv_rv_ratio": 1.15},
    {"contract": "SFRM7", "iv": 0.95, "rv_21d": 0.68, "iv_rv_ratio": 1.40},
    {"contract": "SFRZ7", "iv": 1.04, "rv_21d": 0.72, "iv_rv_ratio": 1.44}
  ],

  "historical_comparison_5y": {
    "realized_asymmetry_ratio_median": 1.10,
    "realized_asymmetry_ratio_p95": 1.85,
    "current_rn_percentile": 0.78
  },

  "warnings": [],
  "composite_score": 1.42,
  "rank": 3
}
```

### 5.2 Run-level outputs

- `screener_results_{date}.csv` — flat ranked table for quick review.
- `screener_results_{date}.json` — full per-structure detail (above schema).
- `screener_summary_{date}.html` — small dashboard with:
  - Top 20 ranked table.
  - Histogram of payoff PDF for top 5 structures.
  - Side-by-side: RN-implied vs. historical realized payoff distribution.
  - IV/RV heatmap across the SOFR strip.

The HTML dashboard is for the morning meeting prep workflow. Keep it static (write to disk, no server).

---

## 6. Edge cases and pitfalls

- **BL extraction wing sensitivity.** RN PDF tails depend heavily on wing interpolation method. The screener's asymmetry ratio is most sensitive in the tails. Surface BL warnings (e.g., negative density flagged) directly in the per-structure output.
- **Risk-neutral vs. real-world.** The asymmetry ratio is RN. A structure that scores well RN-implied may be priced that way *because* the market demands compensation for the skew. The historical realized comparison (Section 3.5) is the partial check — but document this caveat prominently in any output the user sees.
- **Joint distribution model risk.** Already covered; surface both Phase 1 and Phase 2 results to make the dependence visible.
- **Liquidity in deferred contracts.** Greens and blues have thinner option markets. BL extraction may be unreliable. Filter or flag.
- **Fed meeting clustering.** SOFR contract reference periods straddle FOMC meetings non-uniformly. Z6 contains ~2 FOMC meetings; M7 contains ~3. The PDF "shape" is partly determined by how many discrete jump-risk events sit inside the contract's reference period. Don't try to "correct" for this — it's exactly what the screener is supposed to detect — but document it.
- **Calendar effects on roll.** Roll-down for a structure is sensitive to the curve interpolation used (linear vs. cubic spline vs. Nelson-Siegel). Use the same convention as the rest of the codebase; do not re-roll your own.
- **Stat significance of historical comparison.** 5 years × ~84 non-overlapping 3M windows = ~84 observations per structure. That's noisy. Use it as context, not a hard filter.

---

## 7. Open questions — RESOLVED 2026-04-28

These were design-time questions; user has answered them and the implementation plan reflects these decisions:

1. **Default correlation window:** 60d.
2. **Wing extrapolation method for BL:** module uses **SABR + ghost points**, not SVI. Codebase wins. Document.
3. **Non-equal-weighted flies:** Phase 2.
4. **Color filter for the universe:** **whites + reds + greens (12 contracts)** for Phase 1.
5. **Output cadence:** notebook-driven; user runs as needed.

Additional decisions:
- **Joint distribution method:** Support BOTH (a) the existing common-state `JointDistributionSnapshot.linear_combination_distribution` and (b) historical Gaussian copula on 60d daily-change correlation. Configurable; report both per design doc Section 3.2.
- **HTML dashboard:** dropped. Frontend is a Jupyter notebook at `notebooks/rv/run_sfr_convex_screener.ipynb`. CSV + JSON written to disk.
- **Output path:** `data/screener_results/sfr_convex_screener/{YYYY-MM-DD}/`.
- **Module location:** `RVUtils/SFRConvexScreener/`.
- **BL bug fixes:** comprehensive — all six identified issues fixed before screener depends on the module.

---

## 8. Why this matters (the editorial part)

This screener is the practical answer to a recurring trap: a directional view gets expressed in the wrong instrument because the trader didn't quantify the asymmetry of available linear alternatives. The Dec26 receive example from our prior discussion is the canonical case — receiving Dec26 outright at 3.54% is a *negative-EV linear bet on a tail* because the modal outcome (Fed hold) eats the 6bp of priced cuts. A 2s/3s/4s reds fly or a M7/Z7/H8 fly might express the same dovish bias with materially better asymmetry — but the only way to know is to compute it.

The bigger principle: as a rates trader transitioning toward macro, position-taking improves much more from sharpening **expression selection** than from sharpening directional calls. Most macro views, once held, are roughly 50–55% accurate. The difference between a survivable career and a blow-up is whether the linear instrument chosen has +1.5 asymmetry or -1.2 asymmetry. This screener makes that visible. Use it before sizing any directional trade.

---

## Appendix A: Reference math

**Breeden-Litzenberger:** Given European call prices $C(K)$ at strikes $K$ on a single underlying $S$ with maturity $T$:
$$f_S(K) = e^{rT} \frac{\partial^2 C(K)}{\partial K^2}$$
The risk-neutral PDF $f_S$ is the second derivative of the call price wrt strike, scaled by the discount factor.

**Asymmetry ratio (formal):**
$$A = \frac{\int_0^{\infty} \pi \cdot f_\Pi(\pi) \, d\pi}{\left| \int_{-\infty}^{0} \pi \cdot f_\Pi(\pi) \, d\pi \right|}$$
This is the ratio of the upper-half partial expectation to the magnitude of the lower-half partial expectation. $A = 1$ for symmetric distributions; $A > 1$ for upside-skewed payoffs.

**Gaussian copula sampling:**
1. Compute correlation matrix $\Sigma$ from historical daily returns.
2. Sample $Z \sim \mathcal{N}(0, \Sigma)$.
3. Map each component via its empirical CDF: $U_i = \Phi(Z_i)$, then $X_i = F_i^{-1}(U_i)$ where $F_i$ is the marginal RN CDF from BL.
4. $\mathbf{X}$ is a joint sample with the prescribed marginals and Gaussian dependence.

---

## Pre-implementation explorer findings (binding constraints)

The implementation plan was built from the following confirmed facts about the existing codebase:

- **Closest analog:** `BT/signals/sfr_cal_spread_rv.py` + `notebooks/rv/run_sfr_rv_screener.py`. Mirror its dataclass-config + `build_snapshot` shape.
- **Reusable from `RVUtils/ImpliedDistribution`:** `JointDistributionSnapshot.linear_combination_distribution(weights)` already produces the structure payoff PDF under the calibrated common-state joint. Marginals via `SFRImpliedDistribution.extract`. Plotting via `plot_linear_combination_distribution` etc.
- **Reusable data fetch:** `IRSwapsMDP(source="BARCHART_STIRF-RL").get_pricer({"curve_name": "USD-SOFR-1D-Q12STIRT", ...})`; `STIRFutureMDP.get_data` (use `datetime.date` as `timestamp` to get OI); `STIRFutureOptionMDP.fetch_sabr_smile`. Front-month resolution: `_next_contracts(as_of, prefix="SR3", count=12, valid_months=[3,6,9,12], cutoff_fn=_imm_cutoff)` from `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/tos.py`.
- **Curve carry / roll:** use `IRSwapValue.ROLL_BPS_RUNNING` via `IRSwapQuery` — pattern in `notebooks/pricers/sfr.ipynb`.
- **Conventions:** `@dataclass` configs (mutable), `@dataclass(frozen=True)` results; `logger = logging.getLogger(__name__)`; NYC tz via pytz; no YAML / Pydantic / HTML templating; tests live flat in `tests/`; all Python via `conda run -n stir`.
- **BL bugs to fix first:** percentile uses non-interpolating searchsorted; rate-floor truncation silent; negative-density clipping silent; no `warnings` field on result types; GM non-convergence not surfaced; American exercise undocumented.

These are reflected end-to-end in the implementation plan.
