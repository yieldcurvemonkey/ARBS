# Grinold-Kahn Active Portfolio Management

## Pages 41-60


### Page 41


Page 34
. However, αB = 0 by construction, and so portfolios A and B are uncorrelated, 
and βA = 0.
In many cases, we will find it convenient to assume that there is a fully invested portfolio that 
explains expected excess returns. That will be the case if the expected excess return on portfolio C is 
positive. This is not an unreasonable assumption, and we will use it throughout the book. The next 
proposition details some of its consequences.
Proposition 3
Assume that fC > 0.
1. Portfolio q is net long:
Let portfolio Q be the characteristic portfolio of eqf. PortfolioQ is fully invested, with holdings hQ = 
hq/eq. In addition, SRQ = SRq, and for any portfolio P with a correlation ρP,Q with portfolio Q, we 
have
Note that Eq. (2A.36) specifies exactly how portfolio Q "explains" expected returns.
4. If the benchmark is fully invested, eB = 1, then
Proof
For part 1, note that 
 and fC > 0 imply eq > 0. From part 5 of proposition 1,


---


### Page 42


Page 35
The holdings in portfolio Q are a positive multiple of the holdings in q, and so their Sharpe ratios 
and correlations with other portfolios are the same.
For item 2, start with 
 and use 
. This yields 
. If we 
multiply this by hQ, we get 
.
For item 3, premultiply Eq. (2A.27) by hB. This yields
which gives 3.
For item 4, note that eB = 1 and 
 imply that 
. When this is combined 
with 
, we get 4.
Partial List of Characteristic Portfolios
Characteristic
Portfolio
f
hq
eqf
hQ (if fC > 0)
β
hB
e
hC
α = f – βfB
hA
We have built portfolios capturing the important characteristics for portfolio management. These 
portfolios will play significant roles as we further develop the theory. For example, if we want to 
build a portfolio based on our alphas, but with a beta of 1, full investment, and conforming to our 
preferences for risk and return, we will build a linear combination of portfolios A, B, and C.


---


### Page 43


Page 36
The Efficient Frontier
Now focus on two characteristic fully invested portfolios: portfolioC and portfolio Q. At this point 
we would like to introduce a set of distinctive portfolios called the efficient frontier. Portfolio C and 
portfolio Q are both elements of this set. In fact, we will see that all efficient-frontier portfolios are 
weighted combinations of portfolioC and portfolio Q, so each element of the efficient-frontier is a 
characteristic portfolio. The return and risk characteristics of efficient frontier portfolios are simply 
parameterized in terms of the return and risk characteristics of portfolio C and portfolio Q.
A fully invested portfolio is efficient if it has minimum risk among all portfolios with the same 
expected return. Efficient frontier portfolios solve the minimization problem
subject to the full investment and expected excess return constraints (but not a long-only constraint):
We can solve this minimization problem to find:
where we have used the definitions of hC and hQ and have assumed that f 
 e. So efficient frontier 
portfolios are weighted combinations of portfolio C and portfolio Q.
Remember that the correspondence between characteristics and portfolios is one-to-one. We can 
therefore solve for the characteristicaP that underlies each efficient portfolio, using Eq. (2A.45) and 
(2A.5). In each case, the characteristic is a linear combination of e and eqf, the characteristics 
underlying portfolios C and Q, respectively:


---


### Page 44


Page 37
Figure 2A.1 
The efficient frontier.
We can now use Eq. (2A.45) to solve for the variance of the efficient-frontier portfolios. We find
We depict this relationship in Fig. 2A.1. In this figure, portfolio Q has a volatility of 20 percent and 
an expected excess return of 7 percent. Portfolio C has a volatility of 12 percent and, therefore, an 
expected excess return of 2.52 percent. The risk-free asset appears at the origin.
The Capital Asset Pricing Model
We establish the CAPM in two steps. We have already accomplished step 1, showing in Eq. (2A.36) 
that the vector of asset expected excess returns is proportional to the vector of asset betas with 
respect to portfolio Q. In step 2, we show that certain assumptions


---


### Page 45


Page 38
lead us to the conclusion that portfolio Q is the market portfolio M, i.e., that the market portfolio M 
is indeed the portfolio with the highest ratio of expected excess return to risk among all fully 
invested portfolios.
Theorem
If
• All investors have mean/variance preferences.
• All assets are included in the analysis.
• All investors know the expected excess returns.
• All investors agree on asset variances and covariances.
• There are no transactions costs or taxes.
then portfolio Q is equal to portfolio M, and
Proof
If all investors are free of transactions costs, have the same information, and choose portfolios in a 
mean/variance-efficient way, then each investor will choose a portfolio that is a mixture of Q and 
the risk-free portfolio F. That would place each investor somewhere along the line FQF' in Fig. 
2A.1. Portfolios from F to Q combine the risk-free portfolio (lending) and portfolio Q. Portfolios 
from Q to F' represent a levered position (borrowing) in portfolio Q.
When we aggregate (add up, weighted by value invested) the portfolios of all investors, they must 
equal the market portfolio M, since the net supply of borrowing and lending must equal zero. The 
only way that the portfolios along FQF' can aggregate to a fully invested portfolio is to have that 
aggregate equal Q. The aggregate must equal M, and the aggregate must equal Q. ThereforeM = Q.
Exercises
1. Show that 
. Since portfolio C is the minimum-variance portfolio, this relationship 
implies that βC ≤ 1, with βC = 1 only if the market is the minimum-variance portfolio.
2. Show that 
.


---


### Page 46


Page 39
3. What is the ''characteristic" associated with the MMI portfolio? How would you find it?
4. Prove that the fully invested portfolio that maximizes 
 has expected excess return f* = fC 
+ 1/(2λκ).
5. Prove that portfolio Q is the optimal solution in Exercise 4 if 
.
6. Suppose portfolio T is on the fully invested efficient frontier. Prove Eq. (2A.45), i.e., that there 
exists a wT such that hT = wThC + (1 – wT)hQ.
7. If T is fully invested and efficient and T 
 C, prove that there exists a fully invested efficient 
portfolio T* such that Cov{rT,rT*} = 0.
8. For any T 
 C on the efficient frontier and any fully invested portfolio P, show that we can write
where T* is the fully invested efficient portfolio that is uncorrelated with T.
9. If P is any fully invested portfolio, and T is the efficient fully invested efficient portfolio with the 
same expected returns as P, µP = µT, we can always write the returns to P as rP = rC + {rT – rC} + {rP 
– rT}. Prove that these three components of return are uncorrelated. We can interpret the risks 
associated with these three components as the cost of full investment, Var{rC}; the cost of the extra 
expected return µP – µC, Var{rT – rC}; and the diversifiable cost, Var{rP – rT}.
Applications Exercises10
For ease of calculation, focus on just MMI assets when considering these application exercises. The 
MMI is a share-weighted 20-stock
10Applications exercises will appear on occasion throughout the book. These are exercises that require access 
to applications tools, e.g., a risk model and an optimizer. Applications exercises often aim to demonstrate 
results in the book, not through mathematical proof, but through software "experiments."


---


### Page 47


Page 40
index (you can consider it a portfolio with 100 shares of each stock). Also define the market as the 
capitalization-weighted MMI, or CAPMMI for short.
1. Restricting attention to MMI stocks, build the minimum-variance fully invested portfolio 
(portfolio C). What are the betas of the constituent stocks with respect to this portfolio? Verify Eq. 
(2A.16).
2. Build an efficient, fully invested portfolio with CAPM expected returns (proportional to betas 
with respect to the CAPMMI, which has an assumed expected excess return of 6 percent). Use a risk 
aversion of 
 where 
 is the risk of the CAPMMI.
a. What are the beta and expected return to the portfolio?
b. Compare this portfolio to the linear combination of portfolios C and B described in Eq. (2A.45). 
In this case, portfolio B is the CAPMMI.


---


### Page 48


Page 41
Chapter 3—
Risk
Introduction
In the previous chapter we presented the CAPM as a model of consensus expected return. Expected 
return is the protagonist in the drama of active management. Risk is the antagonist.
This section will present the definition of risk that is used throughout the book. The important 
lessons are:
• Risk is the standard deviation of return.
• Risks don't add.
• Many institutional investors care more about active and residual risk than about total risk.
• Active risk depends primarily on the size of the active position, not the size of the benchmark 
position.
• The cost of risk is proportional to variance.
• Risk models identify the important sources of risk and separate risk into components.
We start with our definition of risk.
Defining Risk
Risk is an abstract concept. An economist considers risk to be expressed in a person's preferences. 
What one individual perceives as risky may not be perceived as risky by another.1
1There is a vast literature on this subject. The books of Arrow, Raiffa, and Borch are a good introduction. See 
also Bernstein (1996) for a compelling argument that the understanding of risk was one of the key 
developments of modern civilization.


---


### Page 49


Page 42
We need an operational and therefore universal and impersonal definition of risk. Institutional 
money managers are agents of pension fund trustees, who are themselves agents of the corporation 
and the beneficiaries of the fund. In that setting, we cannot hope to have a personal view of risk. For 
this reason, the risk measure we seek is what an economist might call a measure of uncertainty 
rather than of risk.
We need a symmetric view of risk. Institutional money managers are judged relative to a benchmark 
or relative to their peers. The money manager who does not hold a stock that goes up suffers as 
much as one who holds a larger than average amount of a stock that goes down.
We need a flexible definition of risk. Our definition of risk should apply both to individual stocks 
and to portfolios. We should be able to talk about realized risk in the past and to forecast risk over 
any future horizon.
We want to limit ourselves to a measure of risk that we can accurately forecast. Partly for this 
reason, we want a measure of risk that we can build up from assets to portfolios. We need not only 
the risk for each asset, but also the risk for every possible combination of assets into portfolios.
So our definition of risk must meet several criteria. At the same time, we have a choice of several 
potential risk measures. Let's review them.
To begin with, all definitions of risk arise fundamentally from the probability distributions of 
possible returns. This distribution describes the probability that the return will be between 1 and 
1.01 percent, the probability of a return between 1.01 and 1.02 percent, etc. For example, Fig. 3.1 
displays the empirical distribution of monthly returns for the Fidelity Magellan Fund, based on its 
performance from January 1973 to September 1994. According to this distribution, 26 percent of the 
Magellan Fund monthly returns fell between 2.5 and 7.5 percent.
The distribution of returns describes the probabilities of all possible outcomes. As a result, it is 
complicated and full of detail. It can answer all questions about returns and probabilities. It can be a 
forecast or a summary of realized returns. Conceptually, it applies to every fund type: equity, bond, 
or other. Unfortunately, the distribution of returns is too complicated and detailed in its


---


### Page 50


Page 43
Figure 3.1 
Magellan Fund. January 1973–September 1994.
entirety. Hence all our risk measure choices will attempt to capture in a single number the essentials 
of risk that are more fully described in the complete distribution. Because of this simplification, 
each definition of risk will have at least some shortcomings. Different measures may also have 
shortcomings based on difficulties of accurate estimation. As we will discuss later, by assuming a 
normal distribution, we can calculate all these risk measures as mathematical translations of the 
mean and standard deviation. But first we will discuss these alternatives without that assumption.
The standard deviation measures the spread of the distribution about its mean. Investors commonly 
refer to the standard deviation as the volatility. The variance is the square of the standard deviation. 
For our Magellan Fund example, the standard deviation of the monthly returns was 6.3 percent and 
the mean was 1.6 percent. If these returns were normally distributed, then two-thirds of the returns 
would lie within 6.3 percentage points of the mean, i.e., in the band between –4.7 and 7.9 percent. In 
fact, 73 percent of the


---


### Page 51


Page 44
Magellan Fund returns were in that band, reasonably close to the normal distribution result. The 
Magellan Fund's annual mean and standard deviation were 19.2 percent and 21.8 percent, 
respectively. Roughly two-thirds of the fund's annual returns were in a band from –2.6% to 41 
percent.
As the standard deviation decreases, the band within which most returns will fall narrows. The 
standard deviation measures the uncertainty of the returns.
Standard deviation was Harry Markowitz's definition of risk, and it has been the standard in the 
institutional investment community ever since. We will adopt it for this book. It is a very well 
understood and unambiguous statistic. It is particularly applicable to existing tools for building 
portfolios. Knowing just asset standard deviations and correlations, we can calculate portfolio 
standard deviations. Standard deviations tend to be relatively stable over time (especially compared 
to mean returns and other moments of the distribution), and financial economists have developed 
very powerful tools for accurately forecasting standard deviations.
But before we discuss the standard deviation in more detail, we will discuss some alternative 
definitions. Critics of the standard deviation point out that it measures the possibility of returns both 
above and below the mean. Most investors would define risk as involving small or negative returns 
(although short sellers have the opposite view). This has generated an alternative risk measure: 
semivariance, or downside risk.
Semivariance is defined in analogy to variance, but using only returns below the mean. If the returns 
are symmetric—i.e., the return is equally likely to be x percent above or x percent below the mean—
then the semivariance is exactly one-half the variance. Authors differ in defining downside risk. One 
approach defines downside risk as the square root of the semivariance, in analogy to the relation 
between standard deviation and variance.
From January 1973 to September 1994, the Magellan Fund had a realized semivariance of 21.6, 
which was 55 percent of its variance of 39.5. According to Fig. 3.1, the distribution extended 
slightly farther to the left (negative returns) than to the right (positive returns), and so the 
semivariance was slightly more than half the variance.


---


### Page 52


Page 45
A variant of this definition is target semivariance, a generalization of semivariance that focuses on 
returns below a target, instead of just below the mean.
Downside risk clearly answers the critics of standard deviation by focusing entirely on the 
undesirable returns. However, there are several problems with downside risk. First, its definition is 
not as unambiguous as that of standard deviation or variance, nor are its statistical properties as well 
known. Second, it is computationally challenging for large portfolio construction problems. 
Aggregating semivariance from assets to portfolios is extremely difficult to do well.2
Third, to the extent that investment returns are reasonably symmetric, most definitions of downside 
risk are simply proportional to standard deviation or variance and so contain no additional 
information. Active returns (relative to a benchmark) should be symmetric by construction.
To the extent that investment returns may not be symmetric, there are problems in forecasting 
downside risk. Return asymmetries are not stable over time, and so are very difficult to forecast.3 
Realized downside risk may not be a good forecast of future downside risk.
Moreover, we estimate downside risk with only half of the data, and so we lose statistical accuracy. 
This problem is accentuated for target semivariance, which often focuses even more on events in the 
"tail" of the distribution.
Shortfall probability is another risk definition, and one that is perhaps closely related to an intuitive 
conception of what risk is. The shortfall probability is the probability that the return will lie below 
some target amount. For example, the probability of a Magellan Fund monthly loss in excess of 10 
percent was 3.4 percent.
Shortfall probability has the advantage of closely corresponding to an intuitive definition of risk. 
However, it faces the same problems as downside risk: ambiguity, poor statistical understand2The evidence cited in the section "How Do Risk Models Work?" asserts that it is impossible to do this well.
3The exception is for options or dynamic strategies like portfolio insurance, which have been engineered to exhibit 
asymmetries.


---


### Page 53


Page 46
ing, difficulty of forecasting, and dependence on individual investor preferences.
Forecasting is a particularly thorny problem, and it is accentuated as the shortfall target becomes 
lower. At the extreme, probability forecasts for very large shortfalls are influenced by perhaps only 
one or two observations.
Value at risk is similar to shortfall probability. Where shortfall probability takes a target return and 
calculates the probability of returns falling below that, value at risk takes a target probability, e.g., 
the 1 percent or 5 percent lowest returns, and converts that probability to an associated return. For 
the Magellan Fund, the worst 1 percent of all returns exceeded a 20.8 percent loss. For a $1000 
investment in the Magellan Fund, the value at risk was $208.
Value at risk is closely related to shortfall probability, and shares the same advantages and 
disadvantages.
Where does the normal distribution fit into this discussion of risk statistics? The normal distribution 
is a standard assumption in academic investment research and is a standard distribution throughout 
statistics. It is completely defined by its mean and standard deviation. Much research has shown that 
investment returns do not exactly follow normal distributions, but instead have wider distributions; 
i.e., the probability of extreme events is larger for real investments than a normal distribution would 
imply.
The above definitions of risk all attempt to capture the risk inherent in the "true" return distribution. 
An alternative approach would be to assume that returns are normally distributed. Then the mean 
and standard deviation immediately fix the other statistics: downside risk, semivariance, shortfall 
probability, and value at risk. Such an approach might robustly estimate the quantities that are of 
most interest to individual investors, using the most accurate estimates and a few reasonable 
assumptions.
More generally, this points out that the choice of how to define risk is separate from the choice of 
how to report risk. But any approach relying on the normal distribution would strongly motivate us 
to focus on standard deviation at the asset level, which we can aggregate to the portfolio level. 
Reporting a final number then as standard deviation or as some mathematical transformation of 
standard deviation is a matter of personal taste, rather than an influence on our choice of portfolio.


---


### Page 54


Page 47
Standard Deviation
The definition of risk that meets our criteria of being universal, symmetric, flexible, and accurately 
forecastable is the standard deviation of return.4 If RP is a portfolio's total return (i.e., a number like 
1.10 if the portfolio returned 10 percent), then the portfolio's standard deviation of return is denoted 
by σP ≡ Std{RP}. A portfolio's excess return rP differs from the total return RP by RF (a number like 
1.04 if Treasury bills return 4 percent), which we know at the beginning of the period. Hence the 
risk of the excess return is equal to the risk of the total return. We will typically quote this risk, or 
standard deviation of return, on a percent per year basis.
The standard deviation has some interesting characteristics. In particular, it does not have the 
portfolio property. The standard deviation of a portfolio is not the weighted average of the standard 
deviations of the constituents. Suppose the correlation between the returns of stocks 1 and 2 is ρ12. If 
we have a portfolio of 50 percent stock 1 and 50 percent stock 2, then
with the equality in Eq. (3.2) holding only if the two stocks are perfectly correlated (ρ12 = 1). For 
risk, the whole is less than the sum of its parts. This is the key to portfolio diversification. Figure 3.2 
shows a simple example.
The risk of a portfolio made up of IBM and General Electric is plotted against the fraction of GE 
stock in the portfolio. The curved line represents the risk of the portfolio; the straight line represents 
the risk that we would obtain if the returns on IBM and GE were perfectly correlated. As of 
December 1992, the risk of GE was 27.4 percent/year, the risk of IBM was 29.7 percent/year, and 
the two returns were 62.9 percent correlated. The difference between
4For active investors in options and dynamic strategies such as portfolio insurance, the standard deviation is not 
the perfect risk definition. Yet even in that case, the standard deviation plays an important role [see Kahn and 
Stefek (1996)].


---


### Page 55


Page 48
Figure 3.2 
Fully invested GE/IBM portfolio.
the two lines is an indication of the benefit of diversification in reducing risk.
We can see the power of diversification in another example. Given a portfolio of N stocks, each with 
risk σ and uncorrelated returns, the risk of an equal-weighted portfolio of these stocks will be
Note that the average risk is σ, while the portfolio risk is 
.
For a more useful insight into diversification, now let us assume that the correlation between the 
returns of all pairs of stocks is equal to ρ. Then the risk of an equally weighted portfolio is
In the limit that the portfolio contains a very large number of correlated stocks, this becomes
To get a feel for this, consider the example of an equal-weighted


---


### Page 56


Page 49
portfolio of the 20 Major Market Index constituent stocks. In December 1992, these stocks had an 
average risk of 27.8 percent, while the equal-weighted portfolio has a risk of 20.4 percent. Equation 
(3.4) then implies an average correlation between these stocks of 0.52.
Risks don't add across stocks, and risks don't add across time. However, variance will add across 
time if the returns in one interval of time are uncorrelated with the returns in other intervals of time. 
The assumption is that returns are uncorrelated from period to period. The correlation of returns 
across time (called autocorrelation) is close to zero for most asset classes. This means that variances 
will grow with the length of the forecast horizon and the risk will grow with the square root of the 
forecast horizon. Thus a 5 percent annual active risk is equivalent to a 2.5 percent active risk over 
the first quarter or a 10 percent active risk over four years. Notice that the variance over the quarter, 
year, and four-year horizon (6.25, 25, and 100) remains proportional to the length of the horizon.
We use this relationship every time we ''annualize" risk (i.e., standardize our risk numbers to an 
annual period). If we examine monthly returns to a stock and observe a monthly return standard 
deviation of σmonthly, we convert this to annual risk through
Relative risk is important. If an investment manager is being compared to a performance 
benchmark, then the difference between the manager's portfolio's return rP and the benchmark's 
return rB is of crucial importance. We call this difference the active returnrPA. Correspondingly, we 
define the active risk ψP as the standard deviation of active return:
We sometimes call this active risk the tracking error of the portfolio, since it describes how well the 
portfolio can track the benchmark.
In Fig. 3.3, we consider a simple example. Suppose our benchmark is 40 percent IBM and 60 
percent GE. The figure shows the active risk as a function of the holding of GE when the remainder


---


### Page 57


Page 50
Figure 3.3 
Fully invested GE/IBM portfolio.
of the portfolio is invested in IBM. The active position moves from +60 percent IBM and –60 
percent GE at the left to –40 percent IBM and +40 percent GE at the right. Notice that the active 
holdings always add to zero.
There is a notion among investors that active risk is proportional to the capitalization of the asset. 
Thus, if the market weight for IBM is 4 percent, investors may set position limits of 2 percent on the 
low side and 6 percent on the high side, with the idea that this is a 50 percent over-weighting and a 
50 percent underweighting. For another stock that is 0.6 percent of the benchmark, they may set 
position limits of 0.3 percent and 0.9 percent. So they limit the active exposure of IBM to ±2.0 
percent, and that of the other stock to ±0.3 percent. But active risk depends on active exposure and 
stock risk. It does not depend on the benchmark holding of the stock. So while there may be cost 
and liquidity reasons for emphasizing larger stocks, it is not necessarily true that an active position 
of 1 percent in a large stock is less risky than an active position of 1 percent in a small stock.
Besides active risk, another relative measure of risk, residual risk, is also important. Residual risk is 
the risk of the return orthogonal to the systematic return. The residual risk of portfolio P relative to 
portfolio B is denoted by ωP and defined by


---


### Page 58


Page 51
where
To provide a more intuitive understanding of total risk, residual risk, and beta at the asset level, we 
have calculated these numbers for large U.S. equities (the BARRA HICAP universe of roughly the 
largest 1200 stocks) using 60-month windows as of three widely varying dates: June 1980, June 
1990, and December 1998. Table 3.1 presents a distribution of these numbers, where we have 
averaged over the distributions at the three dates.
So we can see that asset typical total risk numbers are 25 to 40 percent, typical residual risk numbers 
are 20 to 35 percent, and typical betas range from 0.80 to 1.35. For the risk numbers, the 
distributions varied very little from 1980 through 1998, with the exception of the 90th percentile 
(which increased for 1998). The betas varied a bit more over time, decreasing from 1980 through 
1998. Note that the median beta need not equal 1. Only the capitalization-weighted beta will equal 
1.
Variance is the square of standard deviation. In this book we will consistently use variance to 
measure the cost of risk. The cost of risk equates risk to an equivalent loss in expected return. In the 
context of active management, we will generally associate this cost with either active or residual 
risk. Figure 3.4 shows the cost of active risk based upon an active risk aversion of 0.1. With that 
level
TABLE 3.1 
Empirical Distribution of Risk Measures
Percentile
Total Risk (Percent)
Residual Risk 
(Percent)
Beta
90
50.8
45.0
1.67
75
40.1
34.3
1.36
50
30.6
25.1
1.08
25
24.6
19.6
0.79
10
20.4
16.4
0.52


---


### Page 59


Page 52
Figure 3.4 
The cost of risk.
of active risk aversion, a 4 percent active risk translates into a 0.1 · (4 percent)2 = 1.6 percent loss in 
expected return.
Now we turn our attention to models of stock risk.
Elementary Risk Models
The last section hinted at a significant problem in determining portfolio risk. With two stocks in a 
portfolio, we need the volatility of each, plus their correlation [see Eq. (3.1)]. For a 100-stock 
portfolio, we need 100 volatility estimates, plus the correlation of each stock with every other stock 
(4950 correlations). More generally, as the number of stocks N increases, the required number of 
correlations increases as N(N – 1)/2.
We can summarize all the required estimates by examining the covariance matrix V:
where we denote the covariance of ri and rj by σij, and σji = σij. The covariance matrix contains all 
the asset-level risk information required to calculate portfolio-level risk. The goal of a risk model is 
to accurately and efficiently forecast the covariance matrix. The


---


### Page 60


Page 53
challenge arises because the covariance matrix contains so many independent quantities.
In this section, we consider three elementary stock risk models. The first is the single-factor 
diagonal model, which assigns each stock two components of risk: market risk and residual risk. 
The second is a model that assumes that all pairs of stocks have the same correlation. The third is a 
full covariance model based on historical returns.
The single-factor model of risk was an intellectual precursor to the CAPM, although the two models 
are distinct.5 This model starts by analyzing returns as
where βn is stock n's beta and θn is stock n's residual return. The single-factor risk model assumes 
that the residual returns θn are uncorrelated, and hence
Of course, residual returns are correlated. In fact, the market-weighted average of the residual 
returns is exactly zero:
Therefore, the residual correlation between stocks must be in general negative,6 although we might 
expect a positive residual correlation among stocks in the same industry, e.g., large oil companies. 
Nevertheless this simple model of risk is attractive, since it isolates
5The CAPM is a model of expected returns. It assumes equilibrium, but not that all residual returns are 
uncorrelated. The single-factor risk model is not a model of expected returns. It assumes that all residual 
returns are uncorrelated, but not equilibrium. Sharpe described the single-factor model in his Ph.D. dissertation. 
He later developed the CAPM without requiring the assumptions of the single-factor model.
6We can see this most easily in a world of only two stocks with equal market capitalization. Equation (3.14) implies 
that θ2 = –θa, the two residual returns are 100 percent negatively correlated. With hundreds of stocks in a market, 
the average negative correlation implied by Equation (3.14) is small.


---

