# Grinold-Kahn Active Portfolio Management

## Pages 301-320


### Page 301


Page 296
Multiple Assets
The standard situation for an institutional manager involves multiple assets: choosing a portfolio 
that will outperform the benchmark. The chapters in Part 1, ''Foundations," discussed exactly this 
case.
First, we must point out that the basic forecasting formula, Eq. (10.1), applies in the case of multiple 
assets and multiple signals:
In Eq. (11.1), we can treat both r and g as vectors of length N and K, respectively, where K/N 
measures the number of signals per asset. In the case of one signal per asset, the technical appendix 
will show that the forecasting rule of thumb still applies for each asset n:
We are assuming that the signal has the same information coefficient across all assets.
We have also introduced the subscript "TS" to explicitly label the score as a time series score. The 
time series of scores for asset n, zTS,n, has mean 0 and standard deviation 1. This is the definition of 
score that we discussed in Chap. 10. We will contrast these scores with cross-sectional scores, zCS,n.
Unfortunately, Eq. (11.2) doesn't describe the typical situation facing a manager: a numerical 
forecast for each stock at a given time. We do not have N time series scores; rather, we can calculate 
one set of cross-sectional scores. Cross-sectional scores have mean 0 and standard deviation 1 
across N stocks at one time. We want time series scores. We have cross-sectional scores. How do 
we proceed?
Cross-Sectional Scores
The time series score zTS,n depends not only on the current signal, gn(t), but also on the time series 
average and the standard deviation of gn:
But if we can calculate only a cross-sectional set of {gn} (i.e., gn


---


### Page 302


Page 297
for n = 1, 2, . . . N at one time t), we can calculate only cross-sectional scores:
How can we move from the cross-sectional scores we can easily observe to the time series scores 
required for Eq. (11.2)?
For simplicity, let's assume that the mean forecast over time is 0 for each stock, and that the IC for 
each stock is the same and that forecasts are uncorrected across stocks. We will then analyze two 
cases. In Case 1, the time series standard deviation of the signal is the same for each asset. In Case 
2, the time series standard deviations of the signals are proportional to stock volatility. For example, 
if stock A is twice as volatile as stock B, its raw signal gA(t) will be twice as volatile as gB(t).
Case 1: 
Identical Time Series Signal Volatilities
In case 1, we are assuming that
where c1 is independent of n. In this case, we can estimate c1 via time series or cross-sectional 
analysis. We can estimate c1 from a time series of scores chosen from a distribution with standard 
deviation c1. Alternatively, we can estimate c1 by choosing cross-sectionally from a set of 
distributions, each with mean 0 and standard deviation c1. In other words, if the time series standard 
deviations are identical, then time series scores equal cross-sectional scores:
Case 2: 
Time Series Signal Volatilities Proportional to Asset Volatilities
In case 2, we assume that time series standard deviations depend on asset volatilities:


---


### Page 303


Page 298
Once again, we assume that all time series means are 0. But starting with Eq. (11.8), we can 
estimate the constant c2 by observing that
By assumption, the coefficient c2 is independent of n. But in that case, we can equivalently estimate 
it from time series or cross-sectional data, assuming forecasts are uncorrelated across assets:
With this cross-sectional estimate of c2 and with Eq. (11.8), we can restate the basic result, Eq. 
(11.2), as
To rewrite this explicitly in terms of cross-sectional scores,
But the second term on the right-hand side of Eq. (11.13) is just a number, independent of n. We 
will call it cg. Hence
So if the time series signal volatilities are proportional to asset volatilities, then the refined forecasts 
are proportional to cross-sectional scores and independent of volatility. In case 2, forecasts still 
equal volatility · IC · score, but this is proportional to IC · cross-sectional score. The constant of 
proportionality cg, can vary by signal.


---


### Page 304


Page 299
Empirical Evidence
It appears that the question of how to refine cross-sectional signals depends critically on how time 
series signal volatilities vary from stock to stock. In the previous section, we analyzed two extremes: 
independent of stock volatility and proportional to stock volatility.
Here we will examine several specific signals along two particular dimensions. First, we will simply 
observe how the time series signal volatilities depend on asset volatilities. Second, we will compare 
the performance of the alphas refined according to Eqs. (11.7) and (11.14). We hope to find 
empirical results consistent with our analysis. (For another approach to empirically testing alpha 
scaling, see the technical appendix.)
We will examine six U.S. equity signals commercially available from BARRA:
Dividend discount model (DDM)
Estimate change
Estimate revision
Relative strength
Residual reversal
Sector momentum
The dividend discount model provides internal rates of return from a three-stage model, as outlined 
in Chap. 9. The estimate change signal is the 1-month change in consensus estimated annual 
earnings,1 divided by current price. The estimate revision signal combines the 1-month change in 
consensus estimated annual earnings with the 1-month stock return (to help account for stocks 
whose prices have already reacted to the change in consensus). The relative strength signal 
combines each stock's return over the past 13 months with its return over the past month [i.e., it 
attempts to capture momentum over roughly the past year, and it controls for short-term (1-month) 
reversal effects]. The residual reversal signal uses 1-month returns, residual to industry and risk 
index
1This is based on a weighted combination of estimated earnings in fiscal years 1 and 2. The weights depend on 
where the current date stands in the fiscal year. At the beginning of fiscal year 1, all the weight is on fiscal year 
1. As the year progresses, the model places more and more weight on fiscal year 2.


---


### Page 305


Page 300
effects. The sector momentum signal is the 1-month return to capitalization-weighted sector 
portfolios. Each stock in the sector receives the same signal.
BARRA provides these signals as monthly cross-sectional scores. The sector momentum signal 
stands out in this group as the only signal on which many assets receive the same score.
In the first empirical test, we simply calculated 60-month time series signal volatilities for roughly 
the largest 1200 U.S. stocks (the BARRA HICAP universe) as of December 1994. We then ran the 
following cross-sectional regression:
This regression will test whether the time series signal volatilities vary from stock to stock by 
residual volatility. Most importantly, we want to know the R2 statistic for the regression, and also 
the t statistic for the estimated coefficient b. We find the results given in Table 11.1.
For all the signals except sector momentum, we see a very strong positive linear relationship 
between time series signal volatilities and asset residual volatilities. This implies that we need not 
rescale these cross-sectional scores by volatility when estimating expected exceptional return.
We tested this idea by calculating expected exceptional returns using both Eq. 11.7 and Eq. 11.14. 
We will describe the test methodology in detail in Chap. 12. For each method, we built optimal 
portfoTABLE 11.1
Model
R2
t statistic (b)
DDM
0.37
19.3
Estimate change
0.34
18.0
Estimate revision
0.31
17.0
Relative strength
0.72
54.3
Residual reversal
0.77
62.2
Sector momentum
0.01
–3.8


---


### Page 306


Page 301
TABLE 11.2
 
Information Ratio
Model
IC · zcs
ωn · IC · zcs
R2
DDM
1.31
1.19
0.37
Estimate change
1.92
1.87
0.34
Estimate revision
3.55
3.32
0.31
Relative strength
1.93
1.93
0.72
Residual reversal
2.51
2.18
0.77
Sector momentum
1.91
2.10
0.01
lios based on the refined signal, and looked at information ratios from backtests.2 Table 11.2 
contains the results.
The evidence in Table 11.2 is completely consistent with the evidence from Table 11.1. Five of the 
models (all but sector momentum) exhibit a strong relationship between signal volatility and asset 
residual volatility. And in each case, the cross-sectional scores [the correct refined signals according 
to Eq. (11.14)] match or outperform those scores multiplied by residual volatility.
In the one case in which signal volatilities did not vary with asset volatilities, sector momentum, the 
cross-sectional scores multiplied by volatility [the correct refined signals according to Eq. (11.7)] 
outperformed the cross-sectional scores alone.
The empirical evidence supports the previous analysis. Given cross-sectional scores, the critical 
question is whether signal volatilities vary with asset volatilities. The refining process always 
multiplies time series scores by volatility. This does not always imply multiplying cross-sectional 
scores by volatility.
Forecasts have the form volatility · IC · score. Sometimes this is simply proportional to IC · cross-sectional 
score.
2In this test, we industry-neutralized all but the sector momentum signal. Hence each signal is defined relative 
to its industry. Industry-neutralizing sector momentum would set it to zero.


---


### Page 307


Page 302
Why Not Forecast Cross-Sectional Alphas Directly?
We built up our entire forecasting methodology in Chap.10 from time series analysis. We have now 
spent considerable effort adapting that methodology to the more standard application involving 
cross-sectional scores. Why don't we just apply the forecasting methodology directly to the crosssectional information? Can't we simply discard all the time series machinery and focus directly on 
cross-sectional behavior?
In the simple case where we have N asset returns and N signals, all at one time, Eq. (11.1) reduces to
where Stdcs{θn} is the cross-sectional volatility of the residual returns. For any given time t, it is just 
a constant. For all practical purposes, Eq. (11.16) is equivalent to Eq. (11.14).
That result may be reassuring, but the analysis is overly simplistic. Estimating expected exceptional 
returns from only one cross-sectional panel of data is fraught with problems. In one month, 
industries will probably explain much of the cross-sectional variation in returns. The next month, 
the same will be true, but the industries will be different. This month, Internet stocks. Next month, 
health care. The following month, banks. The refining process must, of necessity, analyze both time 
series and cross-sectional information. We need to know what we can consistently forecast over 
time.
In general, we must use both time series and cross-sectional data in Eq. (11.1). We have chosen to 
attack the time series problem first, and then add the complexity of cross-sectional data. As we will 
see, the fully general case is too complex to handle exactly. We must apply structure to tackle it.
Multiple Forecasts for Each of N Stocks
In Chap. 10, we explicitly handled the case of two forecasts for one asset, and also described 
mathematically how to handle multiple forecasts for an asset.


---


### Page 308


Page 303
With some simplifying assumptions, the results from Chap. 10 apply in the case of multiple assets, 
asset by asset. The simplifying assumptions are fairly restrictive. Each information source j has an 
information coefficient vector ICj. The elements of ICj describe the information coefficient asset by 
asset. For each information source, a correlation matrix ρj describes the signal correlations across 
assets. The simplifying assumptions state that
Information source j exhibits the same information coefficient for all assets, and the correlation of 
its signal across assets matches the correlation of every other information source's signal across 
assets. Furthermore, we must assume that the correlation between every gin and gjn is just ρij, a 
constant describing the correlation between signals i and j. With these simplifying assumptions, we 
can apply the results of Chap. 10, asset by asset. We still must remember that the Chap. 10 results 
depend on time series scores and not cross-sectional scores.
The technical appendix provides some further insight into handling the general case of multiple 
forecasts for multiple assets. If we are unwilling to accept the assumptions above, we need to supply 
an alternative structure.
Factor Forecasts
One standard way to apply structure to the case of multiple assets is through a factor model. In 
particular, the arbitrage pricing theory (APT) states that all return forecasts must assume the form
Typically, the problem of forecasting hundreds, if not thousands, of asset returns reduces to a 
problem of forecasting a handful of


---


### Page 309


Page 304
factor returns. Many institutional managers apply just such methods, as we saw in Chap 7.
In the typical case, some of the APT factors immediately suggest factor forecasts. For example, 
some factors may generate consistent returns month after month. We always want portfolios that tilt 
toward these factors. Other factors may require timing, i.e., their returns vary from positive to 
negative, with no implied tilt direction.
We have observed many investment managers, therefore, face the following problem: They can 
forecast one or a few factors, but they have no information (in their opinion) about the other factors. 
Should they set the other factor forecasts to zero?
We can apply the basic forecasting formula to solve this problem. Let's assume that we have a signal 
g1 to forecast b1. We know how to refine g1 to forecast b1. What should we expect for the other 
factors?
Using the basic forecasting formula,
How do we calculate the covariance and correlation of bj and g1? Let's begin by assuming that g1 
contains some information about b1, plus noise:
where Z has mean 0 and standard deviation 1 and is uncorrelated with b1 (and all other bj). Using 
Eq. (11.22), we can calculate
Substituting this back into Eq. (11.22), and assuming that E{bj} = 0, we find
According to Eq. (11.25), if we forecast E{b11g1} 
 0, we should not set E{bj1g1} = 0.


---


### Page 310


Page 305
TABLE 11.3
Strategy
IR
A
3.26
B
3.42
C
1.57
We have empirically tested Eq. (11.25) in the following case. We used the BARRA U.S. Equity 
model (version 2), and assumed that we had explicit information only for the book-to-price (B/P) 
factor. We then looked at three variants of a B/P strategy:
A. Bet only on B/P.
B. Use the information about B/P to also bet on other risk indices.
C. Use B/P information to bet only on other factors.
Case C is rather perverse, but an interesting empirical test of the idea. Using data for the 5-year 
period from May 1990 through April 1995, we found the results in Table 11.3.
We can observe from Table 11.3 that using the information about b1 to bet on bj improves the 
performance of the signal. We can also observe that even perverse strategy C, using information 
about b1 to bet on factors other than b1, exhibits a high information ratio. We would also expect the 
squared information ratio for strategy B to roughly match the sum of the squared information ratios 
for strategies A and C. This is true.
Uncertain Information Coefficients
This and the previous chapter have discussed how to refine raw signals based on expectations, 
volatility, and skill, with skill measured by the information coefficient. We have also discussed how 
to combine signals with differing information coefficients.
A common practical problem, however, involves uncertainty in the information coefficients 
themselves, and how this should influence the refined signals. For example, how should we combine 
two signals with equal estimated IC if one has much higher estima-


---


### Page 311


Page 306
tion errors? We would expect to weight the signal with the more certain IC more heavily. None of 
our machinery so far implies that answer, however. In fact, it isn't obvious how to account for IC 
estimation errors in our framework.
This is because our methodology so far has explicitly ignored this problem. Achieving algebraic 
results requires assuming that we know something. In our analysis so far, we have assumed that we 
know the ICs.
Fortunately, some modest tweaking of our Bayesian methodology can handle the case of uncertain 
ICs. We will explicitly handle the case of one signal, but will discuss the more general result.
We will use regression methodology to analyze the problem. We are attempting to forecast residual 
returns θ(t) with signalg (t). We will refine the signal via regression:
For this analysis, we will assume that θ(t) and g(t) both have mean 0. Hence
We will handle uncertainty in the estimated IC by adding a prior, 
, to the regression, Eq. (11.26). 
We now have
where we will weight the observations of θ(t) by 
, and the prior by 
, where ωθ is the 
standard deviation of ∈θ(t) and ωb is the standard deviation of ∈b.
Equation (11.29) displays a useful mathematical trick. We can


---


### Page 312


Page 307
add a prior as an additional ''observation" in the standard regression. With the above weights, this 
corresponds to a maximum likelihood analysis, with the likelihood of each residual return 
observation being combined with the likelihood of the observed coefficient, given the prior.
Solving this regression for the adjusted coefficient b' leads to
We will use a prior of 
. The technical appendix will show [following Connor (1997)] that Eq. 
(11.30) then reduces to
which involves the expected R2 statistic from the (no prior) regression. Since this R2 statistic should 
equal IC2, and hence be quite small, we can approximate Eq. (11.31) as
Equation (11.32) describes a shrinkage of the original estimate b to account for uncertainty. With a 
large number of observations T or a high information coefficient, we remain close to the naïve 
estimate b. But with fewer periods, or with lower information coefficients, we shrink closer to zero. 
Table 11.4 shows the shrinkage as a function of IC and months of observation T. The shrinkage is 
quite significant even for very good signals observed over long periods of time. For poor signals, the 
adjusted coefficient shrinks to zero (the prior).
Note that Eq (11.31) applies the Bayesian shrinkage to the regression coefficient b, not directly to 
the IC. As we will show in the technical appendix, uncertainty in the IC will typically dominate 
overall uncertainty in the regression coefficient.


---


### Page 313


Page 308
TABLE 11.4
 
Information Coefficient
Months
0.00
0.05
0.10
36
0.00
0.08
0.26
60
0.00
0.13
0.38
90
0.00
0.18
0.47
120
0.00
0.23
0.55
240
0.00
0.38
0.71
What about the case of multiple signals? The same Bayesian shrinkage applies, but with the 
marginal R2 statistics replacing the total R2 statistic in Eq. (11.31). With multiple signals, these 
marginal R2 statistics attribute the total R2 to the signals. Each signal's marginal R2 equals the total 
R2 minus the R2 achieved with that coefficient set to zero. These marginal R2 statistics sum to the 
total R2 statistic. This methodology places a premium on parsimony. A new signal with small 
marginal explanatory power will experience substantial shrinkage.
Summary
This chapter began with the foundations built in Chap. 10—how to refine forecasts for one asset—
and grappled with the typical and more complicated cases of multiple assets and uncertainties in 
estimated ICs. The basic forecasting formula applies to multiple assets, but typically requires so 
many separate estimates that it demands additional structure. Investment managers often rely on 
cross-sectional scores. In many cases, refined exceptional returns are directly proportional to crosssectional scores.
When forecasting factor returns (e.g., in APT models), use your available information to forecast all 
the factors.
The greater the uncertainty in our estimated IC, the more we will shrink the IC toward zero.


---


### Page 314


Page 309
Problems
1. Signal 1 and signal 2 have equal IC, and both exhibit signal volatilities proportional to asset 
volatilities. Do the two signals receive equal weight in the forecast exceptional return?
2. What IR would you naïvely expect if you combined strategies A and C in Table 11.3? Why might 
the observed answer differ from the naïve result?
3. How much should you shrink coefficient b, connecting raw signals and realized returns, estimated 
with R2 = 0.05 after 120 months?
References
Black, Fisher, and Robert Litterman. "Global Asset Allocation with Equities, Bonds, and 
Currencies." Fixed Income Research, Goldman, Sachs & Co., New York, October 1991.
Connor, Gregory. "Sensible Return Forecasting for Portfolio Management." Financial Analysts 
Journal, vol. 53, no. 5, 1997, pp. 44–51.
Grinold, Richard C. "Alpha Is Volatility Times IC Times Score, or Real Alphas Don't Get Eaten." 
Journal of Portfolio Management, vol. 20, no. 4, 1994, pp. 9–16.
Kahn, Ronald. "Alpha Analytics." BARRA Equity Research Seminar, Pebble Beach, Calif., June 
1995.
Technical Appendix
In this appendix, we examine in more detail the analysis of forecasts for multiple assets, discuss an 
alternative method for testing volatility scaling, and treat in more detail the case of uncertain 
information coefficients.
One Forecast for Each of N Assets
Consider the case with K = N forecasts, one forecast gn for each asset return rn. We will make the 
assumption that the IC is the same for each forecast:


---


### Page 315


Page 310
What about the covariance of rn with gm? We will assume that rn is correlated with gm only through 
gn, i.e.,
where ρnm measures the correlation of gn and gm. In matrix notation,
where ω and Std are diagonal matrices with {ωn} and {Std[gn]}, respectively, on the diagonal. 
Substituting this into the basic forecasting formula [Eq. (11.1)], we find
Hence, each forecast takes on the form
Two Forecasts for Each of N Assets
Next, consider the case where K = 2N. Now g = {g1,g2}, with two raw forecasts for each stock. We 
will make the simplifying assumptions
Thus the correlation matrix for the g1 is identical to the correlation matrix for the g2. The correlation 
between every g1n and g2n is described by the scalar constant ρ12. The correlation between every g1n 
and rn is described by the scalar constant IC1, and the correlation between every g2n and rn is 
described by the scalar constant IC2.
We can substitute Eqs. (11A.7) and (11A.8) into the basic forecasting formula, to find


---


### Page 316


Page 311
Once again the refined exceptional forecast takes on the form volatility · IC · score. In this case, we 
adjust the information coefficients based on the correlation between the forecasts g1 and g2.
Multiple Forecasts for Each of N Assets
The general case is easier to understand if we transform the raw forecasts g into a set of uncorrelated 
(orthogonal) forecasts y. We can always write
where the y are standardized and uncorrelated raw forecasts: E{y} = 0, Var{y} = I. We can also 
show that
Thus the general result, that the refined forecast has the form volatility · IC · score, still holds, 
although in the general case it involves transformed scores y and an IC matrix Corr{r,y}. To go 
beyond this result, we need to impose more structure on this correlation matrix.3
Testing Alpha Scaling
A separate approach to testing whether we have appropriately scaled alphas by volatility is to look 
at the amount of risk we take per asset. Assuming uncorrrelated residual risks,
3Here is an alternative empirical procedure for combining K forecasts for each of N assets. First estimate K 
factor portfolio returns, one for each forecast for the N assets. Each factor portfolio should control exposure to 
the other K – 1 factors. Then choose an optimal set of K weights to maximize the information ratio of the 
portfolio of factor portfolios. Use these to determine the weights on the K forecasts for each of the N assets.


---


### Page 317


Page 312
Using the forecasting rule of thumb,
and the portfolio risk becomes
Equation (11A.16) implies that we expect equal risk contributions from each asset, since E{z2} = 1 
for each asset. So, for example, we could define buckets of equal numbers of assets, based on 
volatility, and calculate the contribution to residual variance from each bucket. Each bucket should 
contain a sufficient number of assets to control the sampling error around E{z2}.
If different buckets exhibit different contributions to risk, then either the volatility scaling is 
incorrect or we have imposed different information coefficients for different buckets.
This method also applies to buckets defined on the basis of other attributes.
Uncertain ICs
The main text of the chapter analyzed how to shrink estimated ICs based on their estimation error. 
The technique actually focused on the regression coefficient b:
and not directly on the IC. However, we will show that the estimation error in the IC dominates the 
overall estimation error in b. Hence it is reasonable to assume that we are applying the Bayesian 
shrinkage to the IC.


---


### Page 318


Page 313
Given Eq. (11A.18), how do estimation errors influence our estimate of b? Using Δ to denote 
uncertainties in the variables,
We can analyze Eq. (11A.21) in more detail if we assume that
1. The errors are uncorrelated (so the covariance terms disappear).
2. We have large sample sizes.
3. All errors are normally distributed.
We can then use the results for standard error variances for sample standard deviations and 
correlations:
Substituting these results in Eq. (11A.21), assuming IC < < 1, and simplifying leads to
where T measures the number of months of observations. The first term on the right-hand side of 
Eq. (11A.24) is the contribution from uncertainty in the IC. The second term is the contribution 
from uncertainty in ω and Std{g}. Since IC << 1, the error in the IC dominates the error in the 
regression coefficient.


---


### Page 319


Page 314
Exercises
1. We are following N assets but have a forecast only for asset 1 (N assets, K = 1). Should we set all 
other forecasts equal to their consensus values (φn = 0, n = 2, . . . , N)? How should the N forecasts 
differ from their consensus values based on this one forecast?
2. Compare the result from Exercise 1 to the CAPM result for a forecast of exceptional market 
return. Black and Litterman have pursued these ideas in the context of international asset allocation 
in their international CAPM model.
3. How could you connect the best linear unbiased estimate combining K forecasts for each of N 
assets to an approach estimating factor portfolios for each of the K forecasts and then optimally 
combining those factor portfolios to maximize the overall information ratio?
Application Exercise
1. Compute the coefficient cg for at least two signals. This requires a cross-sectional set of signals 
and residual volatilities. If the signals had equal ICs, what does this imply about their relative 
weighting?


---


### Page 320


Page 315
Chapter 12— 
Information Analysis
Introduction
Information is the vital input into any active management strategy. Information separates active 
management from passive management. Information, properly applied, allows active managers to 
outperform their informationless benchmarks.
Information analysis is the science of evaluating information content and refining information to 
build portfolios. Information analysis works for managers who have a nonquantitative process and 
for managers who have a quantitative investment process—the only requirement is that there is a 
process.
Information is a rather fuzzy concept. Information analysis begins by transforming information into 
something concrete: investment portfolios. Then it analyzes the performance of those portfolios to 
determine the value of the information. Information analysis can work with something as simple as 
an analyst's buy and sell recommendations. Or it can work with alpha forecasts for a broad universe 
of stocks. Information analysis is not concerned with the intuition or process used to generate stock 
recommendations, only with the recommendations themselves.
Information analysis can be precise. It can determine whether information is valuable on the upside, 
the downside, or both. It can determine whether information is valuable over short horizons or long 
horizons. It can determine whether information is adding value to your investment process.
Information analysis occurs before backtesting in the investment process. Information analysis looks 
at the unfettered value


---

