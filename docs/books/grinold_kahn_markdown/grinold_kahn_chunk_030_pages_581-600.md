# Grinold-Kahn Active Portfolio Management

## Pages 581-600


### Page 581


Page 576
rules, multiple tax rates dependent on holding periods, and even calendar date dependencies. We 
should respond differently to a set of alphas we receive in January from the way we respond to one 
we receive in December. We will never solve this problem exactly.
The current approaches to after-tax investing are reasonable but simplistic. Most analyze the oneperiod problem, placing a penalty on net realized capital gains each period. There are two open 
questions here: How good are these simple approaches, and how much better can we do?
Behavioral Finance
Our final question touches on a topic related to valuation, but from a very broad perspective.
Traditional finance theories assume perfectly rational investor behavior. Underneath that assumption 
is perhaps the idea that while investors aren't perfectly rational, their departures from rationality are 
unique and random and should wash out across the marketplace.
Investment psychologists have now demonstrated, however, that investors are irrational in 
systematic and predictable ways. They have even named and cataloged these systematic effects.
So far, behavioral finance has mainly served as an argument for why some anomalies (e.g., residual 
reversal) continue to work over time. It has helped explain several known market phenomena.
The open question for behavioral finance is whether it has predictive ability. Can first principles of 
psychology lead to new investment strategies?
Summary
We have presented several open questions concerning the process of active management. Many of 
them involve the interaction of several separately solvable phenomena (e.g., changing alphas and 
transactions costs), often dynamically over time. Others involve the potential application of new 
methodologies to finance. Some of these open questions are technical. All have important 
implications. The process of active portfolio management is still a vibrant area of research.


---


### Page 582


Page 577
Chapter 22—
Summary
In Active Portfolio Management, we have attempted to provide a comprehensive treatment of the 
process of active management, covering both basic principles and many practical details. In 
summary, we will review what we have covered, the major themes of the book, and what is now left 
for the active manager to do.
What We Have Covered
The book began by covering the foundations: the appropriate framework for active management, 
and the basic portfolio theory required to navigate in that framework. The active management 
framework begins with a benchmark portfolio and defines exceptional returns relative to that 
benchmark. Active managers seek exceptional returns, at the cost of assuming risk. Active managers 
trade off their forecasts of exceptional return against this additional risk. We measure value added as 
the risk-adjusted exceptional return. The key characteristic measuring a manager's ability to add 
value is the information ratio, the amount of additional exceptional return he or she can generate for 
each additional unit of risk. The information ratio is both a figure of merit and a budget constraint. 
A manager's ability to add value is constrained by her or his information ratio.
Given this framework, portfolio theory connects exceptional return forecasts—return forecasts 
which differ from consensus ex-


---


### Page 583


Page 578
pected returns—with portfolios that differ from the benchmark. If a manager's forecasts agree with 
the consensus, that manager will hold the benchmark. To the extent that a manager's forecasts differ 
from the consensus, and to the extent that his or her information ratio is positive, that manager will 
hold a portfolio that differs from the consensus.
The information ratio arises repeatedly as the variable governing active management, and the 
fundamental law of active management provides insight into its components. High information 
ratios require both skill and breadth. Skill is captured by information coefficients—correlations 
between a manager's forecasts of exceptional return and their subsequent realization. Breadth 
measures the manager's available number of independent forecasts per year. Breadth allows the 
manager to diversify his or her imperfect forecasts of the future. High information ratios may 
combine low skill with large breadth, high skill with small breadth, or something in between.
With the framework, basic theory, and insights in place, the book went on to cover the process of 
active management. Day-to-day active management begins with the processing of raw signals into 
exceptional return forecasts and moves on to implementation: portfolio construction, trading, and 
subsequent performance analysis. The forecasting process may depend on a factor model (like APT) 
or on individual stock valuation models. Forecasting includes the processing of raw information into 
refined alpha forecasts. Active management also requires research in order to find valuable 
information. Once again, a process exists for analyzing the information content of potential signals 
and refining them for use in active management.
Themes
We hope that several themes have strongly emerged from the text and the equations. First, active 
management is a process. Active management begins with raw information, refines it into forecasts, 
and then optimally and efficiently constructs portfolios balancing those forecasts of return against 
risk. Active management should consist of more than merely buying a few stocks you think will go 
up. The raw information may be the list of stocks you think will


---


### Page 584


Page 579
go up, and it certainly need not be derived from a quantitative model. But starting with this 
information, active management is a disciplined approach to acting on that information, based on a 
rigorous analysis of its content.
A second theme of the book is that active management is forecasting, and a key to active manager 
performance is superior information. In fact, most of this book describes the machinery for 
processing this superior information into portfolios. If your forecasts match the consensus, or if your 
forecasts differ from the consensus but contain no information, this machinery will lead you back to 
the benchmark. Only as you develop superior information will your portfolio deviate from the 
benchmark.
The third strong theme of the book is that active managers should forecast as often as possible. The 
fundamental law shows that the information ratio depends on both skill and breadth, the number of 
independent forecasts or bets per year. Given the realities (and difficulties) of active management, 
the best hope for a large information ratio is to develop a small edge and bet very often—e.g., 
forecast returns to 500 stocks every quarter. In this search for breadth, we also advocate using 
multiple sources of information—the more the better. In line with this theme of breadth, the reader 
should also notice that we are not strong proponents of benchmark timing. The fundamental law 
shows that benchmark timing is seldom fruitful.
A fourth, and to some readers surprising, theme that we hope has emerged is that mathematics 
cannot overcome ignorance. If your raw information is valueless, no mathematical transformation 
will help. In this book, we have presented the mathematics for investing efficiently based on 
superior information from any source. We have tried to avoid wherever possible the use of 
mathematics to obscure lack of information.
What's Left?
We have described the process and machinery of active management, starting from superior 
information. Much of this machinery is available from vendors, or available to implement on your 
own, if you wish. But clearly, the focus of the active manager, and what


---


### Page 585


Page 580
this book ultimately can't help with, is the search for superior information.
Seeking superior information in this zero-sum game is lonely. Jack Treynor once described the 
process this way: If he identifies a stock he thinks will go up, he talks to his wife about it. If she is 
enthusiastic, he asks his barber. From there, he discusses the idea with his accountant and his 
lawyer. If they all agree it's a great idea—he doesn't buy the stock. If everyone agrees with him, the 
price must already reflect his insight.
We have covered where to look for superior information, we have discussed forecasting factor 
returns and forecasting asset specific returns, and we have described particular information sources 
that have proven valuable in the past. These may still be valuable now, but over time they must 
begin to inform the consensus expected returns. New, clever ideas will always help the active 
manager.
Once you have found superior information, this book provides the best path to success with active 
management.


---


### Page 586


Page 581
APPENDIX A— 
STANDARD NOTATION
This appendix covers standard notation used repeatedly throughout the book. It does not cover 
notation introduced and used only in one particular section.
In general, we represent vectors in lowercase bold letters and matrices in uppercase bold letters. To 
refer to an element of a vector or matrix, we use subscripts and do not use bold, e.g., rn, the excess 
return to asset n, is the nth element of r, the vector of asset excess returns.
Realized Returns
R
total returns [(Pnew + dividend) / Pold)
iF
risk-free rate of return
RF
risk-free total return
r
excess returns
θ
residual returns
b
factor returns
u
specific returns
Expected Returns
f
expected excess returns
µ
long-term expected excess returns
α
expected residual returns
φ
expected exceptional returns
m
expected factor returns
Risk
σ
total risk
ω
residual risk
ψ
active risk
β
asset betas
βP
portfolio beta (exposure to benchmark 
risk)


---


### Page 587


βPA
active portfolio beta


---


### Page 588


Page 582
V
asset-by-asset covariance matrix
F
factor covariance matrix
Δ
specific variance matrix
Portfolios and Assets
hP
portfolio holdings
hPR
residual portfolio holdings
hPA
active portfolio holdings
X
matrix of all assets' exposures to factors
xP
vector of portfolio P's exposure to factors
Performance and Value Added
λT
total risk aversion
λBT
benchmark timing risk aversion
λR
residual risk aversion
λA
active risk aversion
λS
short-term risk aversion
SR
Sharpe ratio
IR
information ratio
IC
information coefficient
BR
breadth
Portfolio Names
B
benchmark portfolio
M
market portfolio
Q
fully invested portfolio with maximum 
Sharpe ratio
C
fully invested portfolio with minimum risk
q
minimum-risk portfolio with expected 
return = 1
A
minimum-risk portfolio with α = 1


---


### Page 589


S
portfolio with minimum expected 
Other
e
vector of 1s


---


### Page 590


Page 583
APPENDIX B—
GLOSSARY
This glossary defines some of the most commonly used terms in the book.
A
Active management—The pursuit of investment returns in excess of a specified benchmark.
Active return—Return relative to a benchmark. If a portfolio's return is 5 percent, and the 
benchmark's return is 3 percent, then the portfolio's active return is 2 percent.
Active risk—The risk (annualized standard deviation) of the active return. This is also called the 
tracking error.
Alpha—The expected residual return. Outside the pages of this book, alpha is sometimes defined as 
the expected exceptional return and sometimes as the realized residual or exceptional return.
Arbitrage—To profit because a set of cash flows has different prices in different markets.
B
Benchmark—A reference portfolio for active management. The goal of the active manager is to 
exceed the benchmark return.
Beta—The sensitivity of a portfolio (or asset) to a benchmark. For every 1 percent return to the 
benchmark, we expect a β percent return to the portfolio.
Breadth—The number of independent forecasts available per year. A stock picker forecasting 
returns to 100 stocks every quarter exhibits a breadth of 400 if each forecast is independent (based 
on separate information).
C
Certainty equivalent return—The certain (zero-risk) return an investor would trade for a given 
(larger) return with an associated risk. For example, a particular investor might trade an expected 3 
percent active return with 4 percent risk for a certain active return of 1.4 percent.
Characteristic portfolio—A portfolio which efficiently represents a particular asset characteristic. 
For a given characteristic, it is the minimum-risk portfolio with the portfolio characteristic equal to 
1. For example, the characteristic portfolio of asset betas is the benchmark. It is the minimum-risk β
= 1 portfolio.
Common factor—An element of return that influences many assets. According to multiple-factor 
risk models, the common factors determine correlations between asset returns. Common factors 
include industries and risk indices.


---


### Page 591


Page 584
D
Descriptor—A variable describing assets, used as an element of a risk index. For example, a 
volatility risk index, distinguishing high-volatility assets from low-volatility assets, could consist of 
several descriptors based on short-term volatility, long-term volatility, systematic and residual 
volatility, etc.
Dividend discount model—A model of asset pricing, based on discounting the future expected 
dividends.
Dividend yield—The dividend per share divided by the price per share. Also known as the yield.
E
Earnings yield—The earnings per share divided by the price per share.
Efficient frontier—A set of portfolios, one for each level of expected return, with minimum risk. 
We sometimes distinguish different efficient frontiers based on additional constraints, e.g., the fully 
invested efficient frontier.
Exceptional return—Residual return plus benchmark timing return. For a given asset with β = 1, if 
the residual return is 2 percent and the benchmark portfolio exceeds its consensus expected returns 
by 1 percent, then the asset's exceptional return is 3 percent.
Excess return—Return relative to the risk-free return. If an asset's return is 3 percent and the riskfree return is 0.5 percent, then the asset's excess return is 2.5 percent.
F
Factor portfolio—The minimum-risk portfolio with unit exposure to the factor and zero exposure 
to all other factors. The excess return to the factor portfolio is the factor return.
Factor return—The return attributable to a particular common factor. We decompose asset returns 
into a common factor component, based on the asset's exposures to common factors times the factor 
returns, and a specific return.
I
Information coefficient—The correlation of forecast returns with their subsequent realizations. A 
measure of skill.
Information ratio—The ratio of annualized expected residual return to residual risk, a central 
measurement for active management. Value added is proportional to the square of the information 
ratio.
M
Market—The portfolio of all assets. We typically replace this abstract construct with a more 
concrete benchmark portfolio.
N
Normal—A benchmark portfolio.


---


### Page 593


Page 585
P
Passive management—Managing a portfolio to match (not exceed) the return of a benchmark.
Payout ratio—The ratio of dividends to earnings. The fraction of earnings paid out as dividends.
R
Regression—A data analysis technique which optimally fits a model based on the squared 
differences between data points and model fitted points. Typically, regression chooses model 
coefficients to minimize the (possibly weighted) sum of these squared differences.
Residual return—Return independent of the benchmark. The residual return is the return relative 
to beta times the benchmark return. To be exact, an asset's residual return equals its excess return 
minus beta times the benchmark excess return.
Residual risk—The risk (annualized standard deviation) of the residual return.
Risk-free return—The return achievable with absolute certainty. In the U.S. market, short-maturity 
Treasury bills exhibit effectively risk-free returns. The risk-free return is sometimes called the time 
premium, as distinct from the risk premium.
Risk index—A common factor typically defined by some continuous measure, as opposed to a 
common industry membership factor defined as 0 or 1. Risk index factors include size, volatility, 
value, and momentum.
Risk premium—The expected excess return to the benchmark.
R squared—A statistic usually associated with regression analysis, where it describes the fraction 
of observed variation in data captured by the model. It varies between 0 and 1.
S
Score—A normalized asset return forecast. An average score is 0, with roughly two-thirds of the 
scores between –1 and 1. Only one-sixth of the scores lie above 1.
Security market line—The linear relationship between asset returns and betas posited by the 
capital asset pricing model.
Sharpe ratio—The ratio of annualized excess returns to total risk.
Skill—The ability to accurately forecast returns. We measure skill using the information coefficient.
Specific Return—The part of the excess return not explained by common factors. The specific 
return is independent of (uncorrelated with) the common factors and the specific returns to other 
assets. It is also called the idiosyncratic return.
Specific risk—The risk (annualized standard deviation) of the specific return.
Standard error—The standard deviation of the error in an estimate; a measure of the statistical 
confidence in the estimate.
Systematic return—The part of the return dependent on the benchmark return. We can break 
excess returns into two components: systematic and residual. The systematic return is the beta times 
the benchmark excess return.


---


### Page 595


Page 586
Systematic risk—The risk (annualized standard deviation) of the systematic return.
T
t statistic—The ratio of an estimate to its standard error. The t statistic can help test the hypothesis 
that the estimate differs from zero. With some standard statistical assumptions, the probability that a 
variable with a true value of zero would exhibit a t statistic greater than 2 in magnitude is less than 5 
percent.
Tracking error—See active risk.
V
Value added—In the context of this book, the utility, or risk-adjusted return, generated by an 
investment strategy: the return minus a risk aversion constant times the variance. The value added 
depends on the performance of the manager and the preferences of the owner of the funds.
Volatility—A loosely defined term for risk. In this book, we define volatility as the annualized 
standard deviation of return.
Y
Yield—See dividend yield.


---


### Page 596


Page 587
APPENDIX C— 
RETURN AND STATISTICS BASICS
This appendix will very briefly cover the basics of returns, statistics, and simple linear regression. 
We provide a list of basic references at the end.
Returns
We define returns over a period t, of length Δt, which runs fromt to t + Δt. If the asset's price at t is P
(t) and at t + Δt is P(t + Δt), and the distributions1 over the period total d(t), then the asset's total 
return is
The asset's total rate of return is
We can also calculate a total return RF and total rate of return iF for the risk-free asset (e.g., a 
Treasury bill of maturity Δt). Then we define the asset's excess return as
Throughout this book, we focus mainly on excess returns and decompositions of excess returns. We 
occasionally use total returns, and never explicitly use total rates of return.
Return calculations become more difficult where they involve stock splits, stock dividends, and 
other corporate actions. We will not explicitly treat those critical details here.
1We label the distributions over the period d(t). If the period Δt is relatively long and a cash distribution occurs 
in midperiod, we could assume reinvestment of the distribution over the rest of the period at either the risk-free 
rate of return or the asset rate of return.


---


### Page 597


Page 588
Statistics
Here we will briefly define how to calculate means, standard deviations, variances, covariances, and 
correlations, and briefly discuss their standard errors. Let's start with a set (a sample) of observed 
excess returns to stock n, rn(t), where t = 1, . . . , T. So we have observed stock n for T months. The 
mean return over the period (the sample mean) is 
The sample variance is
and the sample standard deviation is
Note the use of T – 1 in the denominator of Eq. (C.6). We use T – 1 instead of T to calculate an 
unbiased estimate of the variance, on the assumption that we are estimating both the sample mean 
and the sample variance. If we knew the mean with certainty, independent of the sample mean, we 
would use T in the denominator of Eq. (C.6). We recommend limited use of statistics in very-smallsample situations, where using T versus T – 1 can lead to very different results.
To complete our discussion of basic statistical calculations, consider the excess returns to another 
asset m, rm(t), t = 1, . . . , T. The covariance of returns to assets n and m is


---


### Page 598


Page 589
Finally, the correlation of returns to assets n and m is
Standard Errors
The standard error of an estimate is the standard deviation of the errors in its estimation, a basic 
measure of its accuracy. Assuming that the errors in the estimate are normally distributed, the 
standard error for the estimated mean is
The standard error of the estimated standard deviation is approximately
and the standard error of the estimated variance is approximately
These approximations become more exact in the limit of large sample size, i.e., very large T.
Simple Linear Regression
Throughout the book, we make extensive use of regression analysis. The simplest type of regression 
in the book estimates betas by regressing excess returns against market returns:
Simple linear regression (OLS, or ordinarily least squares) estimates αn and βn by minimizing the 
sum of squared errors (ESS):


---


### Page 599


Page 590
The estimate of βn is
These results use sample estimates of means, variances, and covariances. In the book, we generally 
define betas using Eq. (C.17), but with variances and covariances forecast using a covariance 
matrix.
The R2 of the regression is defined as
Another useful result of basic regression is that the errors ∈n(t) are uncorrelated with the excess 
returns rn(t):
More general regression analysis can involve more independent variables and use weighted sums of 
squares, but the basic idea is the same. The procedure estimates model parameters by minimizing 
the (possibly weighted) sum of squared errors. The resulting errors are uncorrelated with the returns. 
The definition of R2 remains the same. For a thorough introduction to regression analysis, see the 
texts of Hoel, Port, and Stone; Hogg and Craig; and Neter and Wasserman.
References
Hoel, Paul G., Sidney C. Port, and Charles J. Stone. Introduction to Probability Theory (Boston: 
Houghton Mifflin, 1971).
———. Introduction to Statistical Theory (Boston: Houghton Mifflin, 1971).
Hogg, Robert V., and Allen T Craig. Introduction to Mathematical Statistics (New York: 
Macmillan, 1970).
Neter, John, and William Wasserman. Applied Linear Statistical Models (Homewood Ill.: Richard 
D. Irwin, 1974).
Pindyck, Robert S., and Daniel L. Rubinfeld. Econometric Models & Economic Forecasts, 3d ed. 
(New York: McGraw-Hill, 1991).


---


### Page 600


Page 591
INDEX
A
Achievement, information ratio as measure of, 112
Active management, 1–2
as dynamic problem, 574
as forecasting, 261
and information, 316–318
information ratio as key to, 125
objective of, 119–121
as process, 578–579
Active returns, 89, 102–103
Active risk, 50
After-tax investing, 575–576
Allocation (see Asset allocation)
Alpha(s), 91–92
benchmark-neutral, 384–385
characteristic portfolio of, 134
definition of, 111–112
and event studies, 331–332
extreme values, trimming, 382–383
and information horizon, 357–359
and information ratio, 127–129
and portfolio construction, 379–385, 411–413
risk-factor-neutral, 385
scaling, 311–312, 382
American Express, 20–21, 67
Arbitrage pricing theory (APT), 13, 26, 173–192


---

