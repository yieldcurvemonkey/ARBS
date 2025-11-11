# Grinold-Kahn Active Portfolio Management

## Pages 401-420


### Page 401


Page 397
This fear is warranted. A lack of precision in the estimate of correlations is an inconvenience in the 
ordinary estimation of portfolio risk. For the most part, the estimation errors will cancel out. It is an 
obstacle in optimization. In optimization, the portfolio is selected to, among other things, have a low 
level of active risk. Because the optimizer tries to lower active risk, it will take advantage of 
opportunities that appear in the noisy estimates of covariance but are not present in reality.
An example can illustrate the point. Suppose we consider a simple cash versus market trade-off. Let 
ζ be the actual volatility of the market and σ our perceived volatility. If VA* is the optimal value 
added that we can obtain with the correct risk estimate ζ, then the loss12 we obtain with the estimate 
σ is
Figure 14.2 shows the percentage loss, Loss/VA*, as a function of the estimated market risk, 
assuming that the true market risk is 17
Figure 14.2 
Estimated market volatility.
12The technical appendix derives a more general version of this result.


---


### Page 402


Page 398
percent. In this example, market volatility estimates within 1 percent of the true market volatility 
will not hurt value added very much, but as estimation error begin to exceed 3 percent, the effect on 
value added becomes significant, especially if the error is an underestimate of volatility. In fact, an 
underestimate of 12 percent market volatility (5 percent below the ''true" volatility) leads to a 
negative value added.
There are two lessons here. The first is that errors in the estimates of covariance lead to inefficient 
implementation. The second, which is more positive and, indeed, more important, is that it is vital to 
have good estimates of covariance. Rather than abandon the attempt, try to do a good job.
Tests of Portfolio Construction Methods
We can test the effectiveness of these portfolio construction procedures by putting them on an equal 
footing and judging the performance of their outputs. In this case, we will input identical alphas to 
four procedures, described below, and ignore transactions costs.13
The alphas are great. They include the actual returns to the 500 stocks in the S&P 500 over the next 
year plus noise, combined so that the correlation of the alphas with the returns (the information 
coefficient) is 0.1. The fundamental law of active management therefore predicts14 an information 
ratio of 2.24. So not only will we feed the same alphas into each portfolio construction method, but 
we know what the final result should be.
The four portfolio construction techniques are
Screen I. Take the N stocks with the highest alphas and equal-weight them. Use N = 50, 100, and 
150 for low, medium, and high risk aversion, respectively.
Screen II. Take the N stocks with the highest alphas and capitalization-weight them. Use N = 50, 
100, and 150 for low, medium, and high risk aversion, respectively.
13For more details, see Muller (1993). We ignore transactions costs to simplify the test.
14The information coefficient of 0.1 and the breadth of 500 leads to 
.


---


### Page 403


Page 399
Strat. Take the J stocks with the highest alphas in each of the BARRA 55 industry categories. Use J 
= 1, 2, and 3 for low, medium, and high risk aversion portfolios, which will have 55, 110, and 165 
stocks, respectively.
QP. Choose portfolios which maximize value added, assuming low, medium, and high risk aversion 
parameters. Use full investment and no short sales constraints, and constrain each position to 
constitute no more than 10 percent of the entire portfolio.
Portfolios were constructed in January 1984 and rebalanced in January 1985, January 1986, and 
May 1987, with portfolio performance tracked over the subsequent year. Table 14.3 contains the 
results.
Table 14.3 displays each portfolio's ex post information ratio. In this test, the quadratic 
programming approach clearly led to consistently the highest ex post information ratios. On 
average,
TABLE 14.3
Date
Risk 
Aversion
Screen I
Screen II
Strat
QP
 
High
1.10
1.30
0.63
2.16
January 1984
Medium
0.95
2.24
0.64
1.89
 
Low
0.73
1.31
0.69
1.75
 
High
0.78
1.47
1.98
0.98
January 1985
Medium
0.74
–0.53
1.29
1.68
 
Low
0.50
–0.15
0.83
1.49
 
High
1.17
0.91
0.69
2.08
January 1986
Medium
0.69
0.98
0.33
2.29
 
Low
0.60
0.99
0.51
2.51
 
High
1.43
2.04
2.82
2.14
May 1987
Medium
1.01
1.48
2.60
1.76
 
Low
0.66
1.17
2.17
1.82
Average
 
0.86
1.10
1.27
1.88
Standard deviation
 
0.27
0.79
0.89
0.40
Maximum
 
1.43
2.24
2.82
2.51
Minimum
 
0.50
–0.53
0.33
0.98
Source: Peter Muller, "Empirical Tests of Biases in Equity Portfolio Optimization," in 
Financial Optimization, edited by Stavros A. Zenios (Cambridge: Cambridge University 
Press, 1993), Table 4-4.


---


### Page 404


Page 400
it surpassed all the other techniques, and it exhibited consistent performance around that average. A 
stratified portfolio had the single highest ex post information ratio, but no consistency over time. 
The screening methods in general do not methodically control for risk, and Table 14.3 shows that 
one of the screened portfolios even experienced negative returns during one period.
Recall that the ex ante target for the information ratio was 2.24. None of the methods achieved that 
target, although the quadratic program came closest on average. Part of the reason for the shortfall is 
the constraints imposed on the optimizer. We calculated the target information ratio ignoring 
constraints. As we have seen, constraints can effectively reduce the information coefficient and 
hence the information ratio.
Alternatives to Mean/Variance Optimization
In Chap. 3, we discussed alternatives to standard deviation as risk measurements. These included 
semivariance, downside risk, and shortfall probability. We reviewed the alternatives and chose 
standard deviation as the best overall risk measure. We return to the issue again here, since our 
portfolio construction objective expresses our utility, which may in fact depend on alternative 
measures of risk. But as two research efforts show, even if your personal preferences depend on 
alternative risk measures, mean/variance analysis will produce equivalent or better portfolios. We 
present the research conclusions here, and cite the works in the bibliography.
Kahn and Stefek (1996) focus on the forward-looking nature of portfolio construction. The utility 
function includes forecasts of future risk. Mean/variance analysis, as typically applied in asset 
selection, relies on sophisticated modeling techniques to accurately forecast risk. Chapter 3 
discusses in detail both the advantages of structural risk models and their superior performance.
Forecasting of alternative risk measures must rely on historical returns–based analysis. Kahn and 
Stefek show that higher moments of asset and asset class return distributions exhibit very little 
predictability, especially where it is important for portfolio construction. Return kurtosis is 
predictable, in the sense that most return distributions exhibit positive kurtosis ("fat tails") most of 
the time.


---


### Page 405


Page 401
The ranking of assets or asset classes by kurtosis exhibits very little predictability. The only 
exception is options, where return asymmetries are engineered into the payoff pattern.
The empirical result is that most alternative risk forecasts reduce to a standard deviation forecast 
plus noise, with even the standard deviation forecast based only on history. According to this 
research, even investors with preferences defined by alternative risk measures are better served by 
mean/variance analysis.15
Grinold (1999) takes a different approach to the same problem, in the specific case of asset 
allocation. First, he adjusts returns-based analysis to the institutional context: benchmark-aware 
investing with typical portfolios close to the benchmark. This is the same approach we have applied 
to mean/variance analysis in this book. Then he compares mean/variance and returns-based analysis, 
assuming that the benchmark holds no options and that all options are fairly priced.
The result is that portfolios constructed using returns-based analysis are very close to mean/variance 
portfolios, although they require much more effort to construct. Furthermore, managers using this 
approach very seldom buy options. If options are fairly priced relative to the underlying asset class, 
then optimization will pursue the alphas directly through the asset class, not indirectly through the 
options.
So Kahn and Stefek argue the asset selection case for mean/variance, and Grinold argues the asset 
allocation case for mean/variance. Furthermore, Grinold shows why institutional investors, with 
their aversion to benchmark risk, will seldom purchase options—the only type of asset requiring 
analysis beyond mean/variance.
As a final observation, though, some active institutional investors do buy options. We argue that 
they do so typically to evade restrictions on leverage or short selling, or because of liquidity
15The case of investors in options and dynamic strategies like portfolio insurance is a bit trickier, but also 
handled in the paper. There the conclusion is to apply mean/variance analysis to the active asset selection 
strategy, and to overlay an options-based strategy based on alternative risk measures. But see Grinold (1999), 
who shows that under reasonable assumptions, even with alternative risk measures, most institutional investors 
will not use such strategies.


---


### Page 406


Page 402
concerns. Only in the case of currency options do we see much evidence of investors choosing 
options explicitly for their distributions. Many managers have a great aversion to currency losses, 
and options can provide downside protection. We still advocate using mean/variance analysis 
generally and, if necessary, treating currency options as a special case.
Dispersion
Dispersion plagues every manager running separate accounts for multiple clients. Each account sees 
the same alphas, benchmark, and investment process. The cash flows and history differ, however, 
and the portfolios are not identical. Hence, portfolio returns are not identical.
We will define dispersion as the difference between the maximum return and minimum return for 
these separate account portfolios. If the holdings in each account are identical, dispersion will 
disappear. If transactions costs were zero, dispersion would disappear. Dispersion is a measure of 
how an individual client's portfolio may differ from the manager's reported composite returns. 
Dispersion is, at the least, a client support problem for investment managers.
In practice, dispersion can be enormous. We once observed five investors in a particular manager's 
strategy, in separate accounts, incur dispersion of 23 percent over a year. The manager's overall 
dispersion may have been even larger. This was just the dispersion involving these five clients. In 
another case, with another manager, one client outperformed the S&P 500 by 15 percent while 
another underperformed by 9 percent, in the same year. At that level, dispersion is much more than 
a client support problem.
We can classify dispersion by its various sources. The first type of dispersion is client-driven. 
Portfolios differ because individual clients impose different constraints. One pension fund may 
restrict investment in its company stock. Another may not allow the use of futures contracts. These 
client-initiated constraints lead to dispersion, but they are completely beyond the manager's control.
But managers can control other forms of dispersion. Often, dispersion arises through a lack of 
attention. Separate accounts


---


### Page 407


Page 403
exhibit different betas and different factor exposures through lack of attention. Managers should 
control this form of dispersion.
On the other hand, separate accounts with the same factor exposures and betas can still exhibit 
dispersion because of owning different assets. Often the cost of holding exactly the same assets in 
each account will exceed any benefit from reducing dispersion.
In fact, because of transactions costs, some dispersion is optimal. If transactions costs were zero, 
rebalancing all the separate accounts so that they hold exactly the same assets in the same 
proportions would have no cost. Dispersion would disappear, at no cost to investors. With 
transactions costs, however, managers can achieve zero dispersion only with increased transactions 
costs. Managers should reduce dispersion only until further reduction would substantially lower 
returns on average because much higher transactions costs would be incurred.
Example
To understand dispersion better, let's look at a concrete example. In this example, the manager runs 
an existing portfolio and receives cash to form a new portfolio investing in the same strategy. So at 
one point in time, the manager is both rebalancing the existing portfolio and constructing the new 
portfolio. The rebalanced portfolio holdings will reflect both new and old information. With zero 
transactions costs, the manager would rebalance to the new optimum. Given an existing portfolio, 
though, he rebalances only where the new information more than overcomes the transactions costs, 
as in Eq. (14.9).
This trade-off does not affect the new portfolio in the same way. The manager starts from cash, and 
while he would still like to minimize transactions costs, he assumes a fairly high transactions cost 
for the initial portfolio construction. For this example, we'll assume that the new portfolio he builds 
is optimal and reflects entirely the manager's new information.
Clearly there will be dispersion between the existing portfolio and the new portfolio. There are two 
methods by which the manager could reduce dispersion to zero. He could invest the new portfolio in 
the rebalanced existing portfolio. This sacrifices returns, since the new portfolio will reflect both 
new and old information


---


### Page 408


Page 404
instead of just new information. The other choice is to invest the composite in the new optimum. 
But this would require paying excess transactions costs. By treating the existing portfolio and the 
new portfolio separately, the manager accepts some level of dispersion in order to achieve higher 
average returns. Furthermore, he can hope that this dispersion will decrease over time.
Characterizing Dispersion
We will now perform some static analysis to understand the causes of dispersion. First, consider 
dispersion caused by different betas or factor exposures. If the separate account betas range from 0.9 
to 1.1 and the market return is 35 percent one year, then the dispersion would be 7 percent based just 
on the differing betas. This range of betas is quite large for an efficient, quantitatively run optimal 
process, and yet it doesn't come close to explaining some of the extreme war stories.
Now let's consider static analysis of managed dispersion—where the manager has matched factor 
exposures but not assets across all accounts—to try to understand the magnitude of the effect. In this 
simple model, we will consider N portfolios, all equally weighted with identical factor exposures. 
Each portfolio contains 100 stocks, and out of that 100 stocks, M stocks appear in all the portfolios 
and 100 – M stocks are unique to the particular portfolio. Furthermore, every stock has identical 
specific risk of 20 percent. Figure 14.3 displays the results, assuming normal distributions.
We can use the model to show that dispersion will depend on the number of stocks the portfolios 
have in common, the overall levels of specific risk, and the overall number of portfolios under 
management.
Managing Dispersion
We have seen how some level of dispersion is optimal and have discussed why dispersion arises. 
The next question is whether dispersion decreases over time: Do dispersed portfolios converge, and 
how fast? In general, convergence will depend on the type


---


### Page 409


Page 405
Figure 14.3 
Dispersion: 100 stock portfolios.
of alphas in the strategy, the transactions costs, and possibly the portfolio construction methodology.
If alphas and risk stay absolutely constant over time, then dispersion will never disappear. There 
will always be a transactions cost barrier. An exact matching of portfolios will never pay. 
Furthermore, we can show (see the technical appendix) that the remaining tracking error is bounded 
based on the transactions costs and the manager's risk aversion:
where TC measures the cost of trading from the initial portfolio to the zero transactions cost optimal 
portfolio (which we will refer to as portfolio Q), and we are measuring tracking error and risk 
aversion relative to portfolio Q. With very high risk aversion, all portfolios must be close to one 
another. But the higher the transactions costs, the more tracking error there is. Given intermediate 
risk aversion of λA = 0.10 and round-trip transactions costs of 2 percent, and assuming that moving 
from the initial portfolio to portfolio Q in-


---


### Page 410


Page 406
volves 10 percent turnover, Eq. (14.12) implies tracking error of 1 percent.
Since tracking error is bounded, dispersion is also bounded. Dispersion is proportional to tracking 
error, with the constant of proportionality dependent on the number of portfolios being managed:
where this constant of proportionality involves the inverse of the cumulative normal distribution 
function Φ, and ψ is the tracking error of each portfolio relative to the composite (see the technical 
appendix for details). Figure 14.3 displays this function. For a given tracking error, more portfolios 
lead to more dispersion because more portfolios will further probe the extremes of the return 
distribution.
If the alphas and risk vary over time—the usual case—then convergence will occur. We can show 
that with changing alphas and risk each period, the portfolios will either maintain or, more typically, 
decrease the amount of dispersion. Over time, the process inexorably leads to convergence, because 
each separate account portfolio is chasing the same moving target. These general arguments do not, 
however, imply any particular time scale.
As an empirical example, we looked at five U.S. equity portfolios in a strategy with alphas based on 
book-to-price ratios and stock-specific alphas. Roughly two-thirds of the strategy's value came from 
the book-to-price factor tilt, with one-third arising from the stock-specific alphas. We started these 
five portfolios in January 1992 with 100 names in each portfolio, but not the same 100 names in 
each portfolio. Each portfolio had roughly 3 percent tracking error relative to the S&P 500. We 
analyzed the initial level of dispersion and then looked at how that changed over time. We used a 
consistent alpha generation process and standard mean/variance optimization with uniform 
transactions costs. To understand convergence and transactions costs, we looked at behavior as we 
changed the overall level of transactions costs.
What we found was a steady decrease in average tracking error (relative to the composite) and 
dispersion, with the smallest dispersion exhibited when we assumed the lowest transactions costs. 
Figure 14.4 displays the results. So even though our starting portfolios


---


### Page 411


Page 407
Figure 14.4 
Convergence. (Courtesy of BARRA.)


---


### Page 412


Page 408
differed, they steadily converged over a roughly 5-year period. In real-life situations, client-initiated 
constraints and client-specific cash flows will act to keep separate accounts from converging.
One final question is whether we can increase convergence by changing our portfolio construction 
technology. In particular, what if we used dual-benchmark optimization? Instead of penalizing only 
active risk relative to the benchmark, we would also penalize active risk relative to either the 
composite portfolio or the optimum calculated ignoring transactions costs.
Dual-benchmark optimization can clearly reduce dispersion, but only at an undesirable price. Dualbenchmark optimization simply introduces the trade-off we analyzed earlier: dispersion versus 
return. Unless you are willing to give up return in order to lower dispersion, do not implement the 
dual-benchmark optimization approach to managing dispersion.
Summary
The theme of this chapter has been portfolio construction in a less than perfect world. We have 
taken the goals of the portfolio manager as given. The manager wants the highest possible after-cost 
value added. The before-cost value added is the portfolio's alpha less a penalty for active variance. 
The costs are for the transactions needed to maintain the portfolio's alpha.
Understanding and achieving this goal requires data on alphas, covariances between stock returns, 
and estimates of transactions costs. Alpha inputs are often unrealistic and biased. Covariances and 
transactions costs are measured imperfectly.
In this less than perfect environment, the standard reaction is to compensate for flawed inputs by 
regulating the outputs of the portfolio construction process: placing limits on active stock positions, 
limiting turnover, and constraining holdings in certain categories of stocks to match the benchmark 
holdings.
These are valid approaches, as long as we recognize that their purpose is to compensate for faulty 
inputs. We prefer a direct attack on the causes. Treat flaws in the alpha inputs with alpha analysis: 
Remove biases, trim outlandish values, and scale alphas in line with expectations for value added. 
This strengthens the link between research and portfolio construction. Then seek out the best 
possible


---


### Page 413


Page 409
estimates of risk and transactions costs. As appropriate, use a powerful portfolio construction tool 
with as few added constraints as possible.
Near the end of the chapter, we returned to the topic of alternative risk measures and alternatives to 
mean/variance optimization. For most active institutional managers (especially those who do not 
invest in options and optionlike dynamic strategies such as portfolio insurance), alternatives to 
mean/variance analysis greatly complicate portfolio construction without improving results. At the 
stock selection level, results may be much worse.
Finally, we analyzed the very practical issue of dispersion among separately managed accounts. We 
saw that managers can control dispersion—especially that driven by differing factor exposures—but 
should not reduce it to zero.
Problems
1. Table 14.1 shows both alphas used in a constrained optimization and the modified alphas which, 
in an unconstrained optimization, lead to the same holdings. Comparing these two sets of alphas can 
help in estimating the loss in value added caused by the constraints. How? What is that loss in this 
example? The next chapter will discuss this in more detail.
2. Discuss how restrictions on short sales are both a barrier to a manager's effective use of 
information and a safeguard against poor information.
3. Lisa is a value manager who chooses stocks based on their price/earnings ratios. What biases 
would you expect to see in her alphas? How should she construct portfolios based on these alphas, 
in order to bet only on specific asset returns?
4. You are a benchmark timer who in backtests can add 50 basis points of risk-adjusted value added. 
You forecast 14 percent benchmark volatility, the recent average, but unfortunately benchmark 
volatility turns out to be 17 percent. How much value can you add, given this misestimation of 
benchmark volatility?


---


### Page 414


Page 410
5. You manage 20 separate accounts using the same investment process. Each portfolio holds about 
100 names, with 90 names appearing in all the accounts and 10 names unique to the particular 
account. Roughly how much dispersion should you expect to see?
References
Chopra, Vijay K., and William T. Ziemba. ''The Effects of Errors in Means, Variances, and 
Covariances on Optimal Portfolio Choice." Journal of Portfolio Management, vol. 19, no. 2, 1993, 
pp. 6–11.
Connor, Gregory, and Hayne Leland. "Cash Management for Index Tracking."Financial Analysts 
Journal, vol. 51, no. 6, 1995, pp. 75–80.
Grinold, Richard C. "The Information Horizon." Journal of Portfolio Management, vol. 24, no. 1, 
1997, pp. 57–67.
———. "Mean-Variance and Scenario-Based Approaches to Portfolio Selection." Journal of 
Portfolio Management, vol. 25, no. 2, Winter 1999, pp. 10–22.
Jorion, Philippe. "Portfolio Optimization in Practice." Financial Analysts Journal, vol. 48, no. 1, 
1992, pp. 68–74.
Kahn, Ronald N. "Managing Dispersion." BARRA Equity Research Seminar, Pebble Beach, Calif., 
June 1997.
Kahn, Ronald N., and Daniel Stefek. "Heat, Light, and Downside Risk." BARRA Preprint, 
December 1996.
Leland, Hayne. Optimal Asset Rebalancing in the Presence of Transactions Costs. University of 
California Research Program in Finance, Publication 261, October 1996.
Michaud, Richard. "The Markowitz Optimization Enigma: Is 'Optimized' Optimal?" Financial 
Analysts Journal, vol. 45, no. 1, 1989, pp. 31–42.
Muller, Peter. "Empirical Tests of Biases in Equity Portfolio Optimization." In Financial 
Optimization, edited by Stavros A. Zenios (Cambridge: Cambridge University Press, 1993), pp. 80–
98.
Rohweder, Herold C. "Implementing Stock Selection Ideas: Does Tracking Error Optimization Do 
Any Good?" Journal of Portfolio Management, vol. 24, no. 3, 1998, pp. 49–59.
Rudd, Andrew. "Optimal Selection of Passive Portfolios." Financial Management, vol. 9, no. 1, 
1980, pp. 57–66.
Rudd, Andrew, and Barr Rosenberg. "Realistic Portfolio Optimization." TIMS Study in the 
Management Sciences, vol. 11, 1979, pp. 21–46.
Stevens, Guy V.G. "On the Inverse of the Covariance Matrix in Portfolio Analysis." Journal of 
Finance, vol. 53, no. 5, 1998, pp. 1821–1827.
Technical Appendix
This appendix covers three topics: alpha analysis, in particular how to neutralize alphas against 
various factor biases; the loss of value


---


### Page 416


Page 411
added due to errors in the estimated covariance matrix; and dispersion.
Alpha Analysis
Our goal in this section is to separate alphas into common-factor components and specific 
components, and correspondingly to define active portfolio positions arising from these distinct 
components. This will involve considerable algebra, but the result will allow us to carefully control 
our alphas: to neutralize particular factor alphas and even to input factor alphas designed to achieve 
target active factor exposures.
We will analyze stock alphas in the context of a multiple-factor model with N stocks and K factors:
We make the usual assumptions that b and u are uncorrelated, and that the components of u are 
uncorrelated. The model has the covariance structure
The unconstrained portfolio construction procedure leads to an active position 
 determined by 
the first-order conditions:
where 
 is the active factor position.
We now want to separate α into a common-factor component αCF and a specific component αSP, and 
similarly separate 
 into common-factor holdings hCF and specific holdings hSP. We will 
eventually see that each component will separately satisfy Eq. (14A.3), with the common-factor 
alpha component leading to the common-factor active positions and the specific alpha component 
leading to the specific active positions and containing zero active factor positions.
Equation (14A.3) uniquely determines the optimal active holdings 
 and optimal active factor 
exposures 
. However, it does not uniquely determine a separation of 
 into hCF and hSP: There 
are an infinite number of portfolios with active factor exposures


---


### Page 417


Page 412
. We can uniquely define the separation if we stipulate that hCF is the minimum-risk portfolio 
with factor exposures 
.
Let H be the K by N matrix with factor portfolios as rows. The matrix H is
Note that H · X = I; each factor portfolio has unit exposure to its factor and zero exposure to all the 
other factors. Also remember that each factor portfolio has minimum risk, given its factor 
exposures.
Then, starting with the uniquely defined 
 and our definition of hCF as the minimum-risk portfolio 
with these factor exposures, we find
Knowing that hCF and hSP add up to 
 and applying additional algebra, we find that
Exercise 1 at the end of this appendix asks the reader to demonstrate Eq. (14A.5), i.e., that, as 
defined, hCF does lead to the minimum-risk portfolio with factor exposures 
. Exercise 2 asks the 
reader to demonstrate that hSP does not contain any common-factor exposures, i.e., that XT · hSP = 0.
The separation of the optimal holdings into common-factor and specific holdings has been the hard 
part of our task. With this behind us, the easier part is to separate α into a common-factor 
component αCF and a specific component αSP. These are
Notice that H · α is the alpha of each of the K factor portfolios. Call αF = H · α the factor alphas. 
Then X · αF maps those factor alphas back onto the assets.
So we have separated both the optimal active holdings and the alphas into common-factor and 
specific pieces. We can also


---


### Page 418


Page 413
check the correspondence between common-factor alphas and common-factor holdings, and 
between specific alphas and specific holdings. According to Eq. (14A.3), the optimal active 
common-factor exposures are
Exercises 4, 5, and 6 help to show that just using αCF will lead to active holdings hCF and commonfactor exposures 
 and that αSP will lead to active holdings hSP and common-factor exposures of 
zero.
How can we use this glut of algebra? Suppose we believe that our alphas contain valuable 
information only for specific stock selection. Instead of relying on any factor forecasts inadvertently 
contained in our alphas, we have defined a target active position 
 for the common factors. To 
achieve this target, we can replace the original alpha α with α', where
The first term on the right-hand side of Eq. (14A.10) replaces αCF and will result in an active 
common-factor exposure of 
. The second term on the right-hand side of Eq. (14A.10) does not 
affect the common-factor positions and preserves the pure stock selection information from the 
original set of alphas.
The columns of the N by K matrix V · HT are of particular interest. Column k of V · HT leads to an 
active factor position that is positive for factor k and zero for all other factors. This insight can 
provide us with pinpoint control over the factors. Let's say we partition the factors so that x = {y,z}, 
where we are willing to take an active position on the y factors and no active position on the z 
factors. Then we could set
where 
 is the y component of 
. This would result in no active position on the z factors. If we 
wanted no active positions on any of the factors, we could set xPAT = 0.


---


### Page 419


Page 414
Optimization and Data Errors
We now turn to the second topic of this technical appendix: the erosion in value added due to 
inaccuracies in our estimated covariance matrix.
Consider a situation where the true covariance matrix is V, but the manager uses a covariance 
matrix U 
 V. To simplify matters, assume that the manager imposes no constraints. Using Eq. 
(14A.3), the manager then will choose optimal active positions
Using V and 
, the value added (risk-adjusted return) for the manager will be 
If the manager had known the true covariance matrix, the active position would have been
with value added 
The loss in value added is just the difference between 
 and 
. Using Eqs. (14A.12) and 
(14A.14), this becomes
where we have defined the loss as a positive quantity (i.e., the amount lost). You can see that if U = 
V, this term becomes zero.
Dispersion
Here we derive two results stated in the main text. First, we derive a bound on tracking error in the 
presence of transactions costs. Start with initial portfolio I and zero transactions cost optimal 
portfolio Q, which we will treat as a benchmark. To find an optimal


---


### Page 420


Page 415
solution, portfolio P, we will trade off tracking error relative to portfolio Q against the transactions 
costs of moving from portfolio I to portfolio P:
where PC is a vector of purchase costs, SC is a vector of sell costs, the inner maximum functions 
look element by element to determine whether we are purchasing or selling, and we have defined 
the active portfolio relative to portfolio Q. This optimization includes alphas implicitly, in portfolio 
Q.
At optimality,
where the elements of PC' match those of PC only if at optimality hPA(n) > hIA(n) and are zero 
otherwise. We similarly define the elements of SC' based on whether we are selling the asset.
If we multiply Eq. (14A.18) by 
, we find
Now focus on an asset n that we purchased, hP(n) > hI(n). For this asset, we expect hQ(n) ≥ hP(n), i.e., 
if it were not for transactions costs, we would have purchased even more and moved all the way 
from hI(n) to hQ(n). Therefore,
and, once again for purchased assets,
Similar arguments hold for sold assets. If we define
then Eqs. (14A.20), (14A.21), and (14A.19) imply
This is the result in the main text.
The other dispersion result we want to derive here concerns the expected dispersion for N portfolios, 
each with tracking error


---

