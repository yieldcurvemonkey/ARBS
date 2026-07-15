# SDR Dealer Positioning Delta Ladder: Independent Feasibility Audit

**Date:** 15 July 2026  
**Scope:** An adversarial review of the proposition that public US swap-trade reporting can identify dealer positioning, convert it to a futures-equivalent delta ladder, and front-run forced dealer hedging in SR3/ZQ. This is an audit of the mechanism, not an implementation review.

## Verdict first

**Verdict: dead as specified.** The proposed signal may be worth salvaging as an anonymous, model-labelled customer-flow or swap/futures-basis continuation study, but public Part 43 data do not establish the two facts required to call it a dealer-inventory or forced-dealer-hedge signal:

1. the public record does not identify the counterparties or which party paid/received an off-market payment; and
2. observed swap flow is not the dealer's remaining risk after netting, internalization, futures, options, cash, and other offsets.

The highest-priority falsification test is therefore data provenance, not a backtest: obtain an independently labelled sample of tickets/confirmations and demonstrate that the vendor's direction and D2C fields identify the dealer-side fixed payer/receiver at an accuracy materially above chance. If the vendor cannot document non-public source data or a validated convention, the mechanism fails before statistics begin.

| Claim | Feasibility grade | Subjective probability of economically tradable result |
|---|---:|---:|
| Public-data dealer inventory that predicts forced hedging at minute horizons | F | 2% |
| Same mechanism at hourly horizons | F | 7% |
| Same mechanism at daily horizons | D- | 12% |
| Narrow post-disclosure anonymous flow/basis continuation signal after all gates | C- | 15-25% |

These are deliberately conservative research priors, not estimates from a completed sample. A six-month study can decisively reject a large, obvious effect; it cannot establish that a subtle effect is durable, causal, or capacity-bearing.

### Post-review update: PR #351

Review of [PR #351](https://github.com/yieldcurvemonkey/ARBS/pull/351) changes one narrow conclusion: the clean on-market branch is a coherent, falsifiable **price-implied dealer-swap-flow proxy** if the print is genuinely D2C and the pre-trade curve is an accurate executable mid. It is no longer fair to describe this subset as impossible to infer in principle.

The PR assigns a traded rate or structure above the t-minus-one-minute curve mid to dealer RECEIVED and a price below it to dealer PAID. That is economically coherent for a genuine client/dealer trade: a customer paying above fair implies the dealer receives fixed, and conversely below fair. The implementation has focused test coverage for its pricing, arithmetic, package construction, tick logic, and persistence; the local non-network suite passed 34 tests with one network test deselected.

The POC is nevertheless one classified day: 562 units, 67.3% PAID and 32.2% RECEIVED, with a 30-day ticks-only calibration. It reports curve-suspect rates of 54.7% in FOMC JUL26 and 100% in FOMC OCT26, including a documented approximately two-bp stale JUL26 curve node. Those observations are useful diagnostics, not an independent accuracy result.

It does not change the thesis verdict or probabilities. The direction is still a model inference, not an observed party-side field; the repo's D2C value is a platform heuristic; the confidence score is an assumed curve-error model rather than a truth-label calibration; and no test establishes remaining dealer inventory, post-disclosure futures hedging, or executable alpha. The off-market UFRO/PTP branch is a conditional positive-dealer-edge inference, not an observed cash-direction field; it belongs in a separately validated stratum rather than being rejected as logically impossible.

## Ranked kill risks and the cheapest decisive test

| Rank | Kill risk | Why it is decisive | Cheapest test | Pass condition |
|---:|---|---|---|---|
| 1 | Price-implied dealer direction is modelled, not measured | A curve-versus-price sign can be valid for a genuine D2C print, but may be wrong because of a bad mid, price convention, or a false D2C premise. | Audit raw fields, platform provenance, and 200-500 independently known tickets. | DV01-weighted balanced accuracy lower 95% CI above 75%, by platform, product and pricing type. |
| 2 | D2C is a platform/model label, not public party identity | Part 43 protects party anonymity. A platform heuristic can mix D2D or unknown flow into customer flow. | Platform-level field dictionary and matched confirmations. | Whitelist validated D2C platforms; route unknown/missing platforms to UNKNOWN. |
| 3 | Public flow is not remaining dealer inventory | Observed customer swaps can be immediately offset internally or externally; aggregate residual risk may be near zero. | Test for subsequent aggressive CME hedge flow after the actual dissemination time. | Signed predicted hedge must precede measurable downstream hedge flow, not merely price movement. |
| 4 | Dissemination delay/look-ahead | Legal delay is not uniformly one minute; many blocks are delayed at least 15 minutes and other classes longer. | Replay using raw SDR receipt/dissemination timestamps and legal delay class. | Every feature is available before the simulated decision; no inferred +1 minute fallback. |
| 5 | Futures-basis circularity | The same futures curve helps define the signal and is then traded. An apparent forecast can be contemporaneous basis mean reversion or marking. | Independent fair-value labels and a nonlinear matched-basis horse race. | Effect remains after basis, curve, returns, liquidity and event controls; hedge flow confirms ordering. |
| 6 | Economics/capacity disappear at executable prices | Correct deferred-SR3 ticks and depth can turn a marginal gross effect negative. | Historical top-of-book/depth and trade-through replay, including fees. | Conservative lower confidence bound on net alpha is positive at the stated size. |
| 7 | Search-driven significance | Minutes, half-lives, products, curve conventions, filters and event windows create a large implicit trial count. | Locked primary specification and day-blocked joint bootstrap. | Family-wise adjusted p below 0.05 and stable post-lockout result. |

## 1. Can dealer-side direction actually be inferred?

### On-market swaps

A standalone at-market fixed rate can yield a conditional dealer-side inference, not merely a generic economic-direction label. If a print is genuinely dealer-to-customer and is compared with a contemporaneous, independently executable swap mid, then a rate above mid supports dealer fixed RECEIVED and a rate below mid supports dealer fixed PAID. This is the logic implemented by PR #351 for outrights, curves and flies.

That conditional is material. The classifier does not observe either party or a dealer payer/receiver field. It applies the rule to a t-minus-one-minute BARCHART STIR-futures-derived curve and calls the output dealer direction. Its confidence layer derives a probability of flip from the same-bucket tick/dispersion model under a normal-error assumption; it does not estimate accuracy against known dealer-side labels. The ambiguous-print fallback is weaker still because it infers direction from the preceding reported swap rate rather than a quote or confirmation. Treat it as excluded from the primary research universe.

The critical D2C premise also has a concrete repo limitation: the tape creates venue by mapping platform identifier through classify_venue, which returns D2D only for six known IDB platform codes and returns D2C for every other value, including unknown or missing identifiers. Thus D2C is presently a platform classification heuristic, not observed customer/dealer identity. It can be useful after platform-by-platform validation, but should not be written as a confirmed party mapping.

If the true trade-to-mid distance is h and the independent mid error is approximately Gaussian with standard deviation sigma, the idealized sign accuracy is Phi(h/sigma). An 80% accuracy hurdle requires sigma no larger than roughly 1.19h; a 90% hurdle requires sigma no larger than roughly 0.78h. Thus a measured 0.18-0.67 bp charge is not automatically reassuring:

* if it is a one-sided half-spread, an 80% classifier needs roughly 0.21-0.80 bp mid precision;
* if it is a full bid-offer spread, the relevant h is half as large and the requirement is roughly 0.11-0.40 bp.

That is demanding in the exact FOMC/far-date cells where the current design finds the most suspect curve fits. The repo's own design notes show strong concentration of curve-suspect trades in distant meeting buckets; excluding them should be the default, not a minor sensitivity.

### Off-market, UFRO, and package-priced swaps

The CFTC technical specification treats the other-payment amount as a broad price-adjustment field; it can represent fair-value adjustment or another reason a swap is off-market. The public dissemination schema does not publish the counterparty designation or which party paid/received that amount. Package transaction price is also a package-level field and need not identify an individual component's economic payment. See the [CFTC Part 43/45 Technical Specification](https://www.cftc.gov/media/9921/Part43_45TechnicalSpecification12132023CLEAN/download) and the [Part 43 final rule](https://www.cftc.gov/LawRegulation/FederalRegister/finalrules/2020-21568.html), which requires public data to avoid identifying transaction parties.

That absence does not make the PR #351 rule invalid. It means the rule is a conditional economic inference rather than an observed cash-direction label. Let F be the absolute curve-implied NPV of the pay-fixed leg and U the absolute reported upfront amount. Under three explicit assumptions:

1. U is the one-off payment that transfers the off-market swap's value, not an unrelated package or lifecycle field;
2. F is an accurate contemporaneous fair value; and
3. the dealer earns a non-negative bilateral charge on the D2C transaction,

the direction follows from the sign of the residual. If U is below F, the model assigns the dealer the in-the-money swap side and a charge of F minus U. If U is above F, it assigns the dealer the opposite side and a charge of U minus F. This exactly matches the implementation: it chooses the side that makes the dealer's modelled edge equal to the absolute difference between curve NPV and reported upfront. In that sense, the rule is analogous to price-versus-mid classification for an on-market trade.

The real limitation is identification, not arithmetic. The public print alone cannot distinguish this positive-dealer-edge explanation from a dealer price improvement, a bad curve, a non-standard payment purpose, a package allocation error, or a loss-making trade. Because the classifier constructs a non-negative dealer charge by choosing the side, a positive charge cannot validate the assumption; it is imposed by construction. The appropriate label is therefore positive-edge-implied dealer direction.

Use this branch in a separately reported, pre-registered stratum. Require clean standalone payment semantics, an uncertainty/abstention band around U equal to F, independent fair-value sensitivity, and either confirmation-level labels or a documented source convention before promoting it into the primary aggregate ladder. Always report full reversal and omission sensitivities for the UFRO/PTP stratum.

### Required label study

Use a held-out, independently truth-labelled sample. Stratify by:

* standalone on-market, off-market/UFRO, package, post-priced, block, and non-block trades;
* OIS, FOMC-dated, 2-year and other maturity buckets;
* liquidity/volatility regime and venue/source;
* predicted fixed payer and receiver.

Report a DV01-weighted confusion matrix, balanced accuracy, calibration, coverage, and the lower 95% confidence bound for every stratum. The overall lower bound must exceed 75%, with 80% as the operating target. Do not allow an unlabelled sample to choose rules and a labelled sample to certify them.

The existing roughly 67/33 predicted dealer-direction split is a warning, not evidence. With 550-950 independent observations it would be many standard deviations from 50/50, but client flow is serially correlated and the expected population split is not known. It demands a provenance audit and an explicit sensitivity to reversing/abstaining in the problematic strata.

Classification error directly attenuates the tradeable signal. With independent sign accuracy a, expected signed exposure is multiplied by 2a - 1: 60% accuracy retains 20%, 75% retains 50%, and 80% retains 60%. Correlated mid errors or systematic payer/receiver inversion are worse than this benign calculation.

## 2. Does D2C flow map to dealer inventory?

Not from public Part 43 alone. Public reporting is deliberately anonymous; CFTC rules require that dissemination not disclose or facilitate identification of transaction parties. A vendor can add value through non-public feeds, venue relationships, entity-resolution data, or proprietary conventions, but the audit must establish which one applies. If its D2C field is inferred from the same public record, then it is a model label, not an observed counterparty identity.

For the current repo, this is not hypothetical: PR #351 selects venue equal to D2C, but the upstream tape derives that value by classifying only a fixed list of six IDB platform identifiers as D2D and all other identifiers as D2C. The correct next state is an explicit platform whitelist with UNKNOWN for unvalidated or missing identifiers, plus a platform-level confusion matrix against independently known counterparty classes.

There is an accounting nuance worth preserving. If one observed every new customer-to-dealer swap with correct side and DV01, the negative of aggregate customer flow equals aggregate dealer **swap** exposure. Dealer-to-dealer swaps cancel only in that aggregate accounting identity. The trade thesis, however, requires **remaining hedgeable dealer risk**. That differs because dealers can net across customers, affiliate/internalize, hedge with futures, options, cash Treasuries, cleared swaps, or client facilitation before the public record arrives.

The available evidence argues for caution, not an exact capture percentage. A CFTC expected-net-notional report illustrates enormous gross interest-rate dealer positions with much smaller netted amounts, while a CFTC study of banks finds that offsetting positions leave essentially no net rate risk on average; neither is a live, front-end-dealer inventory measure. See [CFTC expected net notional data](https://www.cftc.gov/sites/default/files/2020-08/ENNs_IRS_Jun2020_ada.pdf) and [Banks and Derivatives](https://www.cftc.gov/sites/default/files/2024-04/Banks_and_Derivatives%20%2811%29%20-%20ada.pdf). Aggregate dealer books may be very close to flat even when reported customer notional is large.

**Safe label:** anonymous, model-labelled D2C new-flow proxy.  
**Unsafe label:** dealer inventory, dealer gamma, or forced dealer hedge flow.

The right empirical test is not a balance-sheet assertion: after a signed, correctly delayed qualifying print, is there a predictable, signed increase in aggressive SR3/ZQ or closely matched hedge trading? If not, no price-only regression can establish the proposed hedge channel.

## 3. Is the information already priced by the time it is public?

The public data are available as soon as technologically practicable after receipt at the SDR, subject to legally prescribed dissemination delays. The rule is designed for public transparency, not exclusivity. Current delay classes include 15 minutes for SEF/DCM blocks and certain cleared large notional off-facility swaps, 30 minutes for some non-cleared dealer transactions, one hour for some non-dealer transactions, and longer cases. See [17 CFR Part 43 Appendix C](https://ecfr.io/Title-17/Part-43/Appendix-appendix-c-to-part-43) and the [CFTC final rule](https://www.cftc.gov/LawRegulation/FederalRegister/finalrules/2020-21568.html).

This invalidates the simple decision rule "block plus 15 minutes, otherwise plus one minute." The study must use actual raw dissemination timestamps where available, otherwise the most conservative applicable legal delay. The current implementation plan correctly calls for an all-plus-15-minute parity test, but parity is not enough; it must be a full arrival-time replay.

The relevant question is whether the dealer hedge is delayed beyond dissemination, not whether the original customer trade predicts a move. Dealers may hedge before, during, or immediately after client execution. A transparent public print can only have value if residual positioning is sizeable and the hedge is systematically staged afterwards. Evidence from centralized IRS trading shows greater transparency and competition improved liquidity, which is economically useful but makes a large public-information rent less plausible; see [Benos, Payne and Vasios, Bank of England](https://www.bankofengland.co.uk/-/media/boe/files/working-paper/2018/centralized-trading-transparency-and-interest-rate-swap-market-liquidity-update).

My prior for a reproducible edge is therefore extremely low at minutes, low at hours, and merely low at daily horizons. The strategy should begin at 30-minute to four-hour horizons after a validated actual arrival time, not assert a sub-minute advantage it cannot possess.

## 4. Does the forced-hedging premise make economic sense?

### Ordinary swap delta

For a vanilla front-end OIS, a dealer can hedge delta gradually across futures, swaps and cash instruments. The hedge ratio changes smoothly with the curve. CME's worked example of a 2-year SOFR swap uses a strip of eight futures contracts and shows that a 100 bp rate move changes the futures hedge by only about 2.3%; see [CME's SOFR swap hedging example](https://www.cmegroup.com/articles/2025/price-and-hedging-usd-sofr-interest-swaps-with-sofr-futures.html). That is not proof no discrete execution occurs, but it is inconsistent with treating a 25 bp move as self-evident evidence of a large mechanical FOMC-node hedge kink.

### Gamma, MBS, swaptions, and the FOMC lattice

Mortgage and swaption hedgers can generate convex flows, but public Part 43 swap prints do not identify the relevant option book, hedge trigger, or its mapping into a specific meeting contract. MBS duration is generally multi-year rather than a pure next-meeting exposure; Federal Reserve work on mortgage hedging focuses on long-term rates and ten-year swap-implied volatility. See [Federal Reserve MBS duration analysis](https://www.federalreserve.gov/pubs/feds/2011/201101/) and [mortgage hedging and long-term rates](https://www.federalreserve.gov/econres/feds/does-mortgage-hedging-amplify-movements-in-long-term-interest-rates.htm).

An observed FOMC kink has at least four live alternatives: policy-expectation discovery, calendar-weight/settlement mechanics, curve relative value, or the signal construction's futures-basis feedback. The forced-hedge explanation is admissible only after the direct downstream-flow test distinguishes it.

### Better reference mechanisms

The contrast is useful. Treasury auction supply has a finite, public supply shock, known event window, and direct dealer participation; it is a much cleaner mechanism benchmark than anonymous swaps. A study of primary-dealer Treasury positions finds issuance to be an important driver and positions to be partially offset; see [How Do Treasury Dealers Manage Their Positions?](https://www.newyorkfed.org/research/staff_reports/sr299.html). Private/disaggregated FX order flow has also historically been informative, but that does not transfer automatically to delayed anonymous public reporting; see [Evans and Lyons, BIS](https://www.bis.org/publ/bispap02j.pdf).

## 5. Is the ladder circular because the same futures curve defines the signal and the trade?

The answer is not a pure mathematical tautology, but the endogeneity risk is severe. Let b_i equal observed swap rate minus the futures-implied fair rate. If the futures curve produces the mid, determines payer/receiver sign, prices the futures-equivalent ladder, and is the asset traded, a future-return result can be a combination of contemporaneous basis marking, curve-fit error, and mean reversion rather than evidence of dealer hedging.

Add the following to the Task 10 checklist:

1. Build labels and fair values from a source independent of the target future whenever possible; run leave-one-contract and cross-market variants.
2. Run a nonlinear matched-basis horse race including b_i, sign(b_i) times DV01, absolute basis, curve level/slope/curvature, recent returns, realized volatility, quoted spread/depth, time of day, roll, and FOMC indicators.
3. Match on trade size, maturity and time; test residualized flow rather than raw ladder alone.
4. Test event ordering directly: predicted hedge sign must forecast subsequent aggressive CME trade, before any price response attributed to it.
5. Use price-independent placebos, such as swapped signs, shifted arrivals, unrelated futures and future-period labels.

If the effect vanishes with independent labels, residual controls, or no downstream hedge flow, the honest conclusion is a basis/relative-value feature, not a dealer-inventory mechanism. It may still be tradable, but it is a different thesis.

## 6. Can the economics survive real execution and capacity constraints?

The tick assumption in the current task plan is wrong for most deferred SR3 contracts. SR3 is 25 dollars per bp, but the 0.25 bp / 6.25 dollar minimum increment applies only in the final four months before last trading day; other quarterly contracts trade in 0.5 bp / 12.50 dollar increments. ZQ is about 41.67 dollars per bp and has a 0.5 bp / 20.835 dollar increment. See [CME SOFR futures contract details](https://www.cmegroup.com/education/articles-and-reports/understanding-sofr-futures) and [CME's interest-rate product introduction](https://www.cmegroup.com/articles/2026/introduction-to-interest-rates-products.html).

Thus an eight-leg deferred SR3 strip faces roughly 0.45-0.50 bp of round-trip quoted spread in portfolio-DV01 terms before fees, queue loss, legging, adverse selection and impact, even under an optimistic one-tick execution convention. Treat that as a lower bound, not a cost estimate.

Capacity is a depth question, not a daily-volume question. For executable, non-double-counted lots q_i at a chosen participation p:

* SR3 portfolio DV01 = p times 25 times sum(q_i);
* ZQ portfolio DV01 = p times 41.67 times sum(q_i).

At 10% touch participation, 100/500/1,000 executable SR3 lots per leg across eight legs correspond to 2,000/10,000/20,000 dollars per bp. For one ZQ leg, 25/100/250 lots correspond to about 104/417/1,042 dollars per bp. These are sensitivities, not claims about available depth. Do not count implied packs/bundles and outrights twice. The [CME liquidity tool documentation](https://www.cmegroup.com/education/demos-and-tutorials/cme-liquidity-tool-user-guide) is the appropriate source for historical contract-level depth/cost-to-trade extraction.

For a symmetric one-bp win/loss and conservative cost C, expected net bp is pW - (1-p)L - C. At C = 0.5 bp, a 52% hit rate loses about 0.46 bp/trade; even 58% wins with 1.6 bp wins and 1 bp losses is essentially breakeven. Capacity should be reported as a curve of measured net alpha versus actual fill model and a hard risk cap, not inferred from aggregate SOFR volume.

## 7. Is six months statistically capable of proving anything?

It is sufficient to reject a large effect, not to prove a small one. The number of economically independent observations is far below the number of minute bars. With 90/240-minute half-lives, integration windows are roughly 260/693 minutes. A six-month, 125-trading-day sample contains only about 188/70 such score epochs before gating, not 48,750 independent minutes; correlated contracts should not be counted as independent replications.

For an 80% powered standardized mean test, the approximate minimum detectable effect is:

| Independent observations | One primary test | 20 variants, Bonferroni illustration | 100 variants, illustration |
|---:|---:|---:|---:|
| 30 | 0.511 | 0.706 | 0.789 |
| 125 | 0.251 | 0.346 | 0.387 |
| 250 | 0.177 | 0.244 | 0.273 |
| 500 | 0.125 | 0.173 | 0.193 |

The study has many implicit choices: source and timing fields, trade filters, direction rules, curve construction, cash-flow treatment, horizons, half-lives, futures baskets, event filters, thresholds and costs. HAC errors and a single six-week holdout do not neutralize this search space.

Pre-register one primary test, one horizon, one product basket, one delay convention, one cost model, and one fixed exposure rule. For all secondary variants, use day-blocked or stationary bootstrap max-t / Romano-Wolf family-wise adjustment, preserving cross-contract correlation. Keep a trial ledger that includes manual searches. Useful references are [White's Reality Check](https://doi.org/10.1111/1468-0262.00152), [Romano-Wolf stepdown inference](https://doi.org/10.1111/j.1468-0262.2005.00615.x), [Harvey, Liu and Zhu on factor selection](https://doi.org/10.1093/rfs/hhv059), and [Lo on Sharpe-ratio statistics](https://doi.org/10.2469/faj.v58.n4.2453).

## 8. Required pre-registration: evidence that would convince me

This is the proposed decision protocol. It should be frozen before inspecting the new validation period.

| Gate | Locked evidence requirement | Failure interpretation |
|---|---|---|
| Field provenance | Vendor documents source and semantics of direction/D2C fields; no reliance on an undocumented public-data inference. | Cannot claim dealer side or D2C. |
| Direction truth | DV01-weighted balanced-accuracy lower 95% CI above 75% overall and no catastrophic relevant stratum. | Do not sign ladder; anonymous unsigned flow only. |
| Arrival integrity | Raw receipt/dissemination time replay; all features lagged to legal/public availability; all-plus-15-minute sensitivity. | Look-ahead invalidates result. |
| Mechanism | Correctly signed predicted ladder leads subsequent aggressive CME hedge flow, with timing and matched controls. | No support for forced hedge channel. |
| Circularity | Effect survives independent/leave-one-out fair value, matched-basis controls and residual flow tests. | Relabel as basis RV or reject. |
| Statistical control | One primary raw t at least 3, joint bootstrap family-wise p below 0.05 for secondary family. | Treat as exploratory. |
| Net economics | Lower confidence bound on net alpha positive after deferred-SR3 ticks, fees, slippage, impact, queue assumptions and hard capacity. | Not tradeable. |
| Placebos | Sign shuffle, time shift, unrelated contracts, pre-arrival and post-window tests behave as pre-specified. | Likely leakage or generic return continuation. |
| Lockout | Six-week untouched period has correct sign and positive conservative net result. | No live deployment; determine in advance whether it burns the configuration. |

Passing every gate supports a small paper-traded pilot, not a production allocation. Any failure of field provenance, truth labels, arrival integrity, or downstream hedge ordering kills the stated mechanism.

## Known unknowns that can overturn a historical result

The study must segment, not merely control, for capped notionals, packages/workups, post-priced swaps, changes in reporting taxonomy, roll, liquidity, and Fed funding regimes. Current funding conditions are not stationary: the Federal Reserve began shorter-term Treasury purchases in December 2025 to maintain ample reserves, while recent repo/IORB dynamics show sensitivity to bill supply, dealer capacity, financing and GSE activity. See the [Federal Reserve announcement](https://www.federalreserve.gov/newsevents/pressreleases/monetary20251210a.htm) and [New York Fed market commentary](https://www.newyorkfed.org/newsevents/speeches/2026/per260709). Treasury clearing changes also have staged compliance dates that can alter dealer balance-sheet and hedge channels; see the [SEC implementation page](https://www.sec.gov/featured-topics/treasury-clearing-implementation).

## Steelman: the version worth testing

Do not begin with a synthetic dealer book or a gamma claim. Start with a sparse, post-disclosure study:

1. Use confirmation-validated, standalone, new-risk D2C observations only; exclude packages, capped notionals, curve-suspect trades and ambiguous direction. Treat UFRO/PTP as a distinct positive-edge-implied stratum until its payment semantics and sign accuracy are independently validated.
2. Use actual dissemination time plus at least 15 minutes, a single projected futures basket, and 30-minute to four-hour horizons; exclude FOMC announcement windows initially.
3. Use independent fair values and signed downstream CME aggressive-flow validation before price prediction.
4. Condition on funding, volatility, liquidity and basis regime; size from historical executable depth with conservative costs.
5. Call the output a post-disclosure customer-flow/basis continuation feature unless direct evidence demonstrates residual dealer hedging.

This version has low expected capacity and a meaningful chance of a null result, but it is coherent and falsifiable. The best first deliverable is a mechanical hedge-validation study, not an optimized price backtest.

## Audit conclusion

The existing infrastructure can still be useful. Its value is as a controlled event database, timing-replay engine, and basis/flow research platform. It should not be presented as measuring public dealer inventory until external labels and hedge-ordering evidence clear the hard gates above. Correcting the timing and deferred-SR3 tick assumptions is mandatory before any economics or out-of-sample conclusion is interpreted.
