# Grinold-Kahn Active Portfolio Management

## Pages 81-100


### Page 81


Page 72
Raiffa, H. Decision Analysis: Introductory Lectures on Choices under Uncertainty (Reading, Mass.: 
Addison-Wesley, 1968).
Rosenberg, B. "Extra-Market Components of Covariance in Security Markets."Journal of Financial 
and Quantitative Analysis, March 1974, pp. 263–274.
Rosenberg, B., and V. Marathe. "The Prediction of Investment Risk: Systematic and Residual Risk." 
Proceedings of the Seminar on the Analysis of Security Prices, (Chicago: University of Chicago 
Press), November 1975, pp. 85–224.
Rudd, Andrew, and Henry K. Clasing, Jr. Modern Portfolio Theory (Orinda, Calif.: Andrew Rudd, 
1988), Chaps. 2 and 3.
Sharpe, William F. "A Simplified Model for Portfolio Analysis." Management Science, vol. 9, no. 
1, January 1963, pp. 277–293.
Sheikh, Aamir. "BARRA's Risk Models." BARRA Research Insights (Berkeley, Calif.: BARRA, 
1996).
Technical Appendix
We define the risk model in two parts. First, we model returns as
where r is an N vector of excess returns, X is an N by K matrix of factor exposures, b is a K vector 
of factor returns, and u is an N vector of specific returns.
We assume that
A1. The specific returns u are uncorrelated with the factor returns b; i.e., Cov{un,bk} = 0 for all n and 
k.
A2. The covariance of stock n's specific return un with stock m's specific return um is zero if m 
 n; 
i.e. Cov{un,um} = 0 ifm 
 n.
With these assumptions, we can complete the definition of the risk model by expressing the N by N 
covariance matrix V of stock returns as
where F is the K by K covariance matrix of the factor returns and Δ is the N by N diagonal matrix of 
specific variance.
Model Estimation
Given exposures to the industry and risk index factors, we estimate factor returns via multiple 
regressions, using the Fama-MacBeth procedure (1973). The model is linear, and Eq. (3A.1) has the 
form


---


### Page 82


Page 73
of a multiple regression. We regress stock excess returns against factor exposures, choosing factor 
returns which minimize the (possibly weighted) sum of squared specific returns. In the United 
States, for example, BARRA uses a universe of 1500 of the largest companies, calculates their 
exposures from fundamental data, and runs one regression per month to estimate 65 factor returns 
from about 1500 observations. The R2 statistic, which measures the explanatory power of the model, 
tends to average between 30 and 40 percent for models of monthly equity returns with roughly 1000 
assets and 50 factors. Larger R2 statistics tend to occur in months with larger market moves.
In this cross-sectional regression, which BARRA performs every period, the industry factors play 
the role of an intercept. The market as a whole has an exposure of 1 to the industries, and industry 
factor returns tend to pick up the market return. They are the more volatile factors in the model. The 
market has close to zero exposure to the risk indices, and risk index factor returns pick up extramarket returns. They are the less volatile factors in the market.
To efficiently estimate factor returns, we run generalized least squares (GLS) regressions, weighting 
each observed return by the inverse of its specific variance. In some models, we instead weight each 
observation by the square root of its market capitalization, which acts as a proxy for the inverse of 
its specific variance.11
While these cross-sectional regressions can involve more than 50 factors, the models do not suffer 
from multicollinearity. Most of the factors are industries (52 out of 65 in BARRA's U.S. Equity risk 
model in 1998), which are orthogonal. In addition, tests of variance inflation factors, which measure 
the inflation in estimate errors caused by multicollinearity, lie far below serious danger levels.
Factor Portfolios
This regression approach to estimating factor returns leads to an insightful interpretation of the 
factors. Weighted regression gym11Our research has shown that the square root is the appropriate power of market capitalization to mimic 
inverse specific variance. Larger companies have lower specific variance, and as company size doubles, 
specific variance shrinks by a factor of 0.7.


---


### Page 83


Page 74
nastics lead to the following matrix expression for the estimated factor returns:
where X is the exposure matrix, Δ-1 is the diagonal matrix of GLS regression weights, and r is the 
vector of excess returns. For each particular factor return, this is simply a weighted sum of excess 
returns:
In this form, we can interpret each factor return bk as the return to a portfolio, with portfolio weights 
ck,n. So factor returns are the returns to factor portfolios. The factor portfolio holdings are known a 
priori. The factor portfolio holdings ensure that the portfolio has unit exposure to the particular 
factor, zero exposure to every other factor, and minimum risk given those constraints.12
Factor portfolios resemble the characteristic portfolios introduced in the technical appendix to Chap. 
2, except that they are multiple-factor in nature. That is, characteristic portfolios have unit exposure 
to their characteristic, but not necessarily zero exposure to a set of other factors.
There are two different interpretations of these portfolios. They are sometimes interpreted as factormimicking portfolios, because they mimic the behavior of some underlying basic factor. We 
interpret them more simply as portfolios that capture the specific effect we have defined through our 
exposures.
Factor portfolios typically contain both long and short positions. For example, the factor portfolio 
for the earnings-to-price factor in the U.S. market will have an earnings-to-price ratio one standard 
deviation above the market, while having zero exposure to all other factors. Zero exposure to an 
industry implies that the portfolio will hold some industry stocks long and others short,
12The only factor risk in a factor portfolio arises from the unit exposure to its factor, since all other factor 
exposures are zero. Hence the minimum-risk condition implies minimizing specific risk. The GLS weights in 
the regression ensure this.


---


### Page 84


Page 75
with longs and shorts balancing. Factor portfolios are not investible portfolios, since, among other 
properties, these portfolios contain every single asset with some weight.
Factor Covariance Matrix
Once we have estimates of factor returns each period, we can estimate a factor covariance matrix: an 
estimate of all the factor variances and covariances. To effectively operate as a risk model, this 
factor covariance matrix should comprise our best forecast of future factor variances and 
covariances, over the investor's time horizon.
Forecasting covariance from a past history of factor returns is a subject worthy of a book in itself, 
and the details are beyond the scope of this effort. Basic techniques rely on weights over the past 
history and bayesian priors on covariance. More advanced techniques include forecasting variance 
conditional on recent events, as first suggested by Engle (1982). Such techniques assume that 
variance is constant only conditional on other variables. For a review of these ideas, see Bollerslev 
et al. (1992).
Specific Risk
To generate an asset-by-asset covariance matrix, we need not only the factor covariance matrix F, 
but also the specific risk matrix Δ. Now, by definition, the model cannot explain a stock's specific 
return un. So the multiple-factor model can provide no insight into stock specific returns. However, 
for specific risk, we need to model specific return variance 
 (assuming that mean specific return 
is zero).
In general, we model specific risk as13
13To minimize the influence of outliers, we often model |un| and not 
. We then must correct for a systematic 
bias in modeling absolute deviation when we want to forecast standard deviation.


---


### Page 85


Page 76
with
So S(t) measures the average specific variance across the universe of stocks, and vn captures the 
cross-sectional variation in specific variance.
To forecast specific risk, we use a time series model for S(t) and a linear multiple-factor model for vn
(t). Models for vn(t) typically include some risk index factors, plus factors measuring recent squared 
specific returns. The time dependence in the model of vn(t) is captured by time variation in the 
exposures. We estimate model coefficients via one pooled regression over assets and time periods, 
with outliers trimmed.
Risk Analysis
A portfolio P is described by an N-element vector hP that gives the portfolio's holdings of the N 
risky assets. The factor exposures of portfolio P are given by
The variance of portfolio P is given by
A similar formula lets us calculate ψP, the active risk or tracking error. If hB is the benchmark 
holdings vector, then we can define


---


### Page 86


Page 77
and
Notice that we have separated both total and active risk into common-factor and specific 
components. This works because factor risks and specific risks are uncorrelated.
The decomposition of risk is more difficult if we want to separate market risk from residual risk. We 
must define beta first.
The N vector of stock betas relative to the benchmark hB is defined by the equation
If we define b and d as
then we can write beta as
So each asset's beta contains a factor contribution and a specific contribution. The specific 
contribution is zero for any asset not in the benchmark. In most cases, the industry factor 
contribution dominates beta.
The portfolio beta is
A similar calculation yields the active beta.
The systematic and residual risk are then given respectively by the two terms
where 
 is given by Eq. (3A.9) and βP by Eq. (3A.17). It is possible to construct a residual 
covariance matrix


---


### Page 87


Page 78
Attribution of Risk
In some cases, it is possible to attribute a portion of risk to a single cause. We can separate market 
risk from residual risk, and we can separate common-factor risk from specific risk. In both cases, the 
two risk components are uncorrelated. When two sources of risk are correlated, then the covariance 
between them makes it difficult to allocate the risk. We will describe one approach, which first 
requires the introduction of marginal contributions to risk.
Marginal Contribution
Although total allocation of risk is difficult, we can examine the marginal effects of a change in the 
portfolio. This type of sensitivity analysis allows us to see what factors and assets have the largest 
impact on risk. The marginal impact on risk is measured by the partial derivative of the risk with 
respect to the asset holding. We will see in the technical appendix to Chap. 5 that marginal 
contributions to residual risk are directly proportional to alphas, with the constant of proportionality 
dependent on the information ratio.
We can compute marginal contributions for total risk, residual risk, and active risk. The N vector of 
marginal contributions to total risk is
The MCTR(n) is the partial derivative of σP with respect to hP(n). We can think of it as the 
approximate change in portfolio risk given a 1 percent increase in the holding of asset n, financed by 
decreasing the cash account by 1 percent. Recall that the cash holding hP(0) is given by hP(0) = 1 – 
eP. To first order,
In a similar way, we can define the marginal contribution to residual risk as
where hPR = hP – βP · hB is the residual holdings vector for portfolio P.


---


### Page 88


Page 79
Finally, the marginal contribution to active risk is given by
We can further decompose this marginal contribution to active risk into a market and a residual 
component.
We see that 0 ≤ k2 ≤ 1, and k2 = 1 when βPA = 0 and k1 = 0.
Factor Marginal Contributions
Sometimes we wish to calculate sensitivities with respect to factor exposures instead of asset 
holdings. Let's think about what this means.
At the asset level, the marginal contributions capture the change in risk if we change the holding of 
just one asset, leaving all other assets unchanged.
At the factor level, the marginal contributions should capture the change in risk if we change the 
exposure to only one factor, leaving other factor exposures unchanged. To increase the portfolio's 
exposure to only factor k, we want to add a portfolio with exposure to factor k, and zero exposure to 
the other factors. A reasonable and well-defined choice is a factor portfolio. The factor portfolio has 
the proper exposures, and minimum risk given those exposures, so it is as close as we can come:
where [(XT · Δ-1 · X)-1 · XT · Δ-1] is the K by N vector of factor portfolios, and δk is a K by 1 vector 
containing zeros except in thekth row, where it contains δk.


---


### Page 89


Page 80
To find the effect on risk of adding this portfolio, we need only multiply the changes in each asset 
holding times the marginal contributions at the asset level. We present here only the calculation for 
marginal contribution to active risk:
We can simplify this result by using the factor decomposition of the covariance matrix. The result is
The first term above captures the change in factor risk due to changing the factor exposure. It 
resembles the form of the marginal contribution to active risk at the asset level [Eq. (3A.23)]. It 
would be the complete answer if we could change factor exposures while leaving asset holdings 
unchanged. The second term captures the change in specific risk due to changing the factor 
exposures using the actual factor portfolio. Remember that the factor portfolios have minimum 
specific risk among all portfolios with unit exposure to one factor and zero exposure to all other 
factors. Empirically, we find that the second term is much smaller than the first term.14 Hence we 
typically make the reasonable approximation
Sector Marginal Contributions
Having broached the subject of factor marginal contributions, we should also briefly mention sector 
marginal contributions. The idea is that we typically group industry factors into sectors. The sectors 
play no role in risk model estimation or risk calculation, but they
14The exception to this finding occurs with thin industry factors, i.e., industry factors with fewer than about 10 
members. Thin industries suffer from large estimation errors. This is yet another reason to avoid them.


---


### Page 90


Page 81
are convenient and intuitive constructs. So once we have determined how increases in industry 
exposures might affect risk, we may also want to know how an increase in sector exposure might 
affect risk.
This is a reasonable question. Unfortunately, its answer is ambiguous. When we calculated factor 
marginal contributions, we used a linear contribution of asset-level marginal contributions and relied 
on the relative unambiguousness of the factor portfolios. At the sector level, we want to calculate a 
linear combination of the industry factor marginal contributions, but the weights are less ambiguous 
now. We could increase the exposure to a sector by increasing only one particular industry in the 
section, increasing each industry the same amount, increasing each industry based on the portfolio 
industry weights, or increasing each industry based on the benchmark industry weights. One 
reasonable choice is to use the total (as opposed to active) industry weights from the portfolio. For 
example, consider a computer sector comprising two industries: software and hardware. If the 
portfolio contains only computer hardware manufacturers, then calculate computer sector marginal 
contributions based only on the hardware industry. If the portfolio's exposure to computers is 70 
percent software and 30 percent hardware, use the 70/30 weights to calculate sector marginal 
contributions. In other words, assume that the investor would increase (or decrease) the exposure to 
computers in exactly the current proportions.
Clearly, the most important point about sector marginal contributions is to understand what 
calculation you need and what calculation you are receiving.
Attribution of Risk
We can use the marginal contributions to define a decomposition of risk. For concreteness, we will 
focus on a decomposition of active risk, but the ideas apply equally well to total or residual risk. 
First note the mathematical relationship
But Eq. (3A.31) implies an attribution of active risk. The amount


---


### Page 91


Page 82
of active risk ψP which we can attribute to asset n is 
. We can furthermore divide 
Equation (3A.31) by ψP, to give a percentage breakdown of active risk:
We can use Eq. (3A.32) to attribute to asset n a fraction 
 of the overall active 
risk.
How can we interpret this attribution scheme? In fact, the attributed returns are relative marginal 
contributions to active risk. Here is what we mean. As before, if we increase the holding in asset n,
But we can rewrite this as
So the change in active risk depends on the relative change in the active holding of asset n, ΔhPA
(n)/hPA(n), times the amount of active risk attributed to asset n. Hence we can interpret this amount 
of risk attributed to asset n as a relative marginal contribution, RMCAR(n):
If we changed asset n's active holding from 1 percent to 1.01 percent, we could estimate the change 
in active risk as 0.01 times the RMCAR for asset n.15
15There is another, more algebraic interpretation of these risk attributions. The difficult issue in attributing risk 
is how to handle the covariance terms. But covariances always arise in pairs (e.g., 2 · Cov{a,b}). This risk 
attribution scheme simply parcels one covariance term to each element (e.g., 1 · Cov{a,b} to the risk of a and 1 
· Cov{a,b} to the risk of b).


---


### Page 92


Page 83
Attribution to Factors
This is a straightforward extension of the previous ideas. Using the factor risk model, we have
We can therefore define the factor marginal contributions, FMCAR, as
But note that
Hence, we can attribute active risk ψ to the factors and specific sources. We attribute 
 · 
FMCAR(j) to factor j, and 
 overall to specific sources. Once again, we can interpret 
these attributions as relative marginal contributions.
Correlations and Market Volatility
As a final topic, we can illustrate one use of the simple one-factor model to understand the observed 
relationship between asset correlations and market volatility: Typically asset correlations increase as 
market volatility increases.
According to this simple model, the correlation between assets n and m is
The only contribution of the model is the simple form of the covariance in the numerator of Eq. 
(3A.40). But now let's assume that both assets have betas of 1, and identical residual risk. Then Eq. 
(3A.40) becomes
We can now see that if residual risk is independent of market


---


### Page 93


Page 84
volatility, as market volatility increases, asset correlations increase. In periods of low market 
volatility, asset correlations will be relatively low.
Exercises
1. Show that:
2. Verify Eq. (3A.24).
3. Show that
4. Using the single-factor model, assuming that every stock has equal residual risk ω0, and 
considering equal-weighted portfolios to track the equal-weighted S&P 500, show that the residual 
risk of the N-stock portfolio will be
What estimate does this provide of how well a 50-stock portfolio could track the S&P 500? Assume 
ω0 = 25 percent.
5. This is for prime-time players. Show that the inverse of V is given by
V–1 = Δ–1 – Δ–1 · X · {XT · Δ–1 · X + F–1}–1 · XT · Δ–1
As we will see in later chapters, portfolio construction problems typically involve inverting the 
covariance matrix. This useful relationship facilitates that computation by replacing the inversion of 
an N by N matrix with the inversion of K by K matrices, where K < < N. Note that the inversion of N
by N diagonal matrices is trivial.


---


### Page 94


Page 85
Applications Problems
1. Calculate the average correlation between MMI assets. First, calculate the average volatility of 
each asset. Second, calculate the volatility of the equal-weighted portfolio of the assets. Use Eq. 
(3.4) to estimate the average correlation.
2. What are the average total risk, residual risk, and beta of the MMI assets (relative to the 
CAPMMI)?
3. Using MMI assets, construct a 20-stock portfolio to track the S&P 500. Compare the resulting 
tracking error to the answer to Exercise 4, where ω0 is the average residual risk for MMI assets.


---


### Page 95


Page 87
Chapter 4— 
Exceptional Return, Benchmarks, and Value Added
Introduction
The CAPM provides consensus expected returns. A multiple-factor model can help to control risk. 
Consensus forecasts and risk control are available to all active managers. We need one more crucial 
ingredient in order to be effective: accurate forecasts of expected return. This chapter will discuss 
those forecasts of expected return and outline a procedure to transform those forecasts into 
portfolios.
The chapter is a gradual migration from theory to practice. In theory, we consider an all-embracing 
market consisting of all assets; in practice, there is a great degree of specialization, so we consider a 
benchmark with a limited number of assets. In theory, the investor is an individual concerned for his 
or her own needs; in practice, investment decisions are made by professionals who are one or more 
levels removed from the eventual beneficiary of those decisions. In theory, active management is a 
dubious undertaking; in practice, we must provide guidelines for the attempt. This chapter shows 
how theory is adapted to these institutional realities and the needs of the active manager.
The results of this chapter are as follows:
• The components of expected return are defined. Exceptional expected return is the difference 
between our forecasts and the consensus.
• Benchmark portfolios are a standard for the active manager.
• Active management value-added is expected exceptional return less a penalty for active variance.


---


### Page 96


Page 88
• Management of total risk and return is distinct from management of active risk and return.
• Benchmark timing decisions are distinct from stock selection decisions.
This chapter sets out the ground rules used throughout the book. Those who don't like benchmarks 
should find some comfort in the notion that choosing the risk-free portfolio F as a benchmark puts 
one back in the traditional position of balancing expected return against total risk.
There are two things that this chapter does not do:
• Set up criteria for the proper choice of a benchmark for a specialist manager.
• Set a target for strategic asset allocation.
Strategic asset allocation establishes a benchmark for an entire pension fund. Strategic asset 
allocation is a vital question for the fund, for consultants, and for balanced managers. We don't 
address that important question in this book.
Benchmarks
In many practical situations, an active manager will be asked to out-perform a benchmark portfolio 
that cannot, in good conscience, be called ''the market." Some would argue that this is always the 
case. Even that old standby, the S&P 500, represents only a fraction of the world's traded equities. If 
we toss in debt and real property, the S&P 500 will not look like a representative slice of the 
universe available to the institutional investor. For that reason, we are going to phase out the word 
market and shift to the word benchmark. The benchmark portfolio is also known by the aliases 
bogey and normal portfolio.
A benchmark portfolio is a consequence of institutional investment management. A trustee or 
sponsor generally hires several managers to invest the funds. These managers will typically 
specialize. So included among the managers will be a bond manager, an equity manager, an 
international manager, etc. The specialization can be-


---


### Page 97


Page 89
come finer.1 The managers may specialize in passive equity strategies, growth stocks, value stocks, 
small-capitalization stocks, etc.
The sponsor should give all managers clear instructions regarding their responsibilities and any 
limitations on their actions. One of the best ways for an owner of funds to communicate those 
responsibilities is to specify a benchmark portfolio. For example, the benchmark for a U.S. 
international equity manager may be the Morgan Stanley Capital International EAFE index or the 
Financial Times EUROPAC index. The benchmark for a smaller-capitalization manager in the 
United States may be the Frank Russell 2000 index. The benchmark for an Australian manager of 
resource stocks may be a special index containing only the stocks in the Australian resource sector.
The manager's performance is judged relative to the performance of the benchmark. The manager's 
active return is the difference between the return on the manager's portfolio and the return on the 
benchmark portfolio.
The reader may feel that this practice has theoretical limitations. It undoubtedly does. However, it 
also has undeniable practical benefits. First, it allows investment managers to specialize and 
concentrate their expertise on a smaller collection of assets. The sponsors take charge of asset 
allocation. Second, it focuses the manager's attention on performance relative to the benchmark.
What guidelines can we provide for an institutional manager whose performance is judged relative 
to a benchmark? The manager's attention is directed toward the difference between the managed 
portfolio's returns and the benchmark portfolio's returns. The market portfolio is not specified and 
plays no direct role.
New Terminology
We have thrown out the market portfolio and are willing to work with a more ad hoc benchmark 
portfolio. At the same time, we don't want to abandon all the useful scaffolding that we had built up 
around the market.
1This specialization can be and has been carried to extremes. Each manager has a vested interest in creating a 
separate niche to avoid direct comparisons with other managers. This has led to a constant spawning of new 
styles.


---


### Page 98


Page 90
The most important item to salvage is beta. As discussed in previous chapters, we can define beta 
outside of the CAPM context. If rB is the excess return on the benchmark portfolio and rn is the 
excess return on stock n, then we can define βn as
We have robbed beta of its universal definition. Beta is no longer an absolute term. It is not beta 
with respect to the market, but beta with respect to a benchmark. Our notion of residual risk will 
also become relative. It is no longer residual to the market but residual to a benchmark.
The active position is the difference between the portfolio holdings and the benchmark holdings. 
The active holding in the risky assets is given by hPA,
and the active cash holding is
The active variance is the variance of the active position. If we let ψP be the active risk, we have
If we use our notion of beta relative to the benchmark and residual return θP relative to the 
benchmark, then we can write the active variance as
where βP is the active beta (i.e., βP – 1) and ωP is the residual risk:
Our definition of a benchmark will assist us in separating expected return into its component parts.
Components of Expected Return
We can decompose expected return forecasts into four parts: a risk-free component (the time 
premium), a benchmark component (the


---


### Page 99


Page 91
risk premium), a benchmark timing component (exceptional benchmark return), and an alpha 
(expected residual return). If Rn is the total return on asset n, then we write
We will now discuss each component and various combinations.
The Time Premium iF
This is the return an investor receives for parting with the investment stake for a year. It is referred 
to as the time premium, i.e., the compensation for time. Since we know the return on a risk-free 
asset in advance, we can assign the time premium in advance.
The Risk Premium βn · µB
We are borrowing from the CAPM here. The expected excess return on the benchmark, µB, is 
usually estimated by analysts as a very long run (70+ years) average (although other estimation 
methods are common). A number between 3 and 7 percent per annum is reasonable for most equity 
markets. Notice that low-beta assets will have lower risk premiums and high-beta assets will have 
greater risk premiums.
Exceptional Benchmark Return βn · ΔfB
The expected excess return on the benchmark µB cited above is based on very long run 
considerations. If you believe that the next year (or quarter, or month) will be quite different, then 
ΔfB is your measure of that difference between the expected excess return on the benchmark in the 
near future and the long-run expected excess return.
Alpha αn
Alpha is the expected residual return, αn = E{θn}.
Consider this breakdown of the –0.60% total return for the MMI portfolio over the month of 
December 1992, using the S&P 500 as a benchmark. Over this month, the forecast beta of the 
portfolio versus the S&P 500 was 0.96. Over this same month, the risk-free return was 26 basis 
points and the S&P 500 return was


---


### Page 100


Page 92
131 basis points; we will assume an expected long-run excess S&P 500 return of 50 basis points, so 
there was a benchmark surprise of 55 basis points. Given this information, we can break down the 
realized portfolio return as in Table 4.1.
We can combine these components of expected returns in various ways.
Consensus expected excess return βn · µB. The consensus expected excess return is the expected 
excess return obtained if one accepts the benchmark as an ex ante efficient portfolio with expected 
excess return µB. This set of expected excess returns will cause us to choose our portfolio to exactly 
match the benchmark portfolio.
Feeding these expected returns into an optimizer will lead to combinations of the benchmark 
portfolio and cash, with the cash fraction dependent on µB.
Expected excess return fn = βn · µB + βn · ΔfB + αn. The expected excess return, denoted fn, is made up 
of the risk premium, the response to an exceptional benchmark forecast, and the alpha.
Exceptional expected return βn · ΔfB + αn. The exceptional expected return is the key to active 
management. The first component, βn · ΔfB, measures benchmark timing,2 and the second 
component, αn, measures stock selection.
TABLE 4.1 
MMI Return Breakdown: 12/92
Risk-free return
0.26%
Risk premium
0.48%
Exceptional benchmark return
0.53%
Alpha
–1.87%
Total return
–0.60%
2Note that the expected return βn · ΔfB will generate a single bet for or against the benchmark. The term 
benchmark timing more generally refers to this strategy over time. By construction, E{βn · ΔfB} = 0 over time, 
so ΔfB will sometimes be positive and sometimes be negative.


---

