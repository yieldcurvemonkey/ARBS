# Grinold-Kahn Active Portfolio Management

## Pages 61-80


### Page 61


Page 54
market and residual risk and gives a conservative estimate, namely 0, of the residual covariance 
between stocks.
The second elementary risk model requires an estimate of each stock's risk σn and an average 
correlation ρ between stocks. That means that each covariance between any two stocks is
This second model has the virtue of simplicity and can be helpful in some "quick and dirty" 
applications. It ignores the subtle linkage between stocks in similar industries and firms with 
common attributes.
The third elementary model relies on historical variances and covariances. This procedure is neither 
robust nor reasonable. Historical models rely on data from T periods to estimate the N by N 
covariance matrix. If T is less than or equal to N, we can find active positions7 that will appear 
riskless! So the historical approach requires T > N. For a monthly historical covariance matrix of 
S&P 500 stocks, this would require more than 40 years of data. And, even when T exceeds N, this 
historical procedure still has several problems:
• Circumventing the T > N restriction requires short time periods, one day or one week, while the 
forecast horizon of the manager is generally one quarter or one year.
• Historical risk cannot deal with the changing nature of a company. Mergers and spinoffs cause 
problems.
• There is selection bias, as takeovers, LBOs, and failed companies are omitted.
• Sample bias will lead to some gross misestimates of covariance. A 500-asset covariance matrix 
contains 125,250 independent numbers. If 5 percent of these are poor estimates, we have 6262 poor 
estimates.
The reader will note limited enthusiasm for historical models of risk. We now turn to more 
structured models of stock risk.
7Mathematically, an N by N covariance matrix made up from T periods of returns will have rank equal to the 
minimum of N and T – 1. More intuitively, we can see the problem by comparing the number of observations to
the number of quantities we wish to estimate. An N by N covariance matrix contains N(N + 1)/2 independent 
estimates. With N assets and T periods, we have NT observations. Requiring an absolute minimum of two 
observations per estimate (after all, we require at least two observations to estimate one standard deviation) 
implies that T ≥ N + 1.


---


### Page 62


Page 55
Structural Risk Models8
In the previous section, we considered elementary risk models and found them either wanting or 
oversimplified. In this section, we look at structural multifactor risk models and trumpet their 
virtues.
The multiple-factor risk model is based on the notion that the return of a stock can be explained by a 
collection of common factors plus an idiosyncratic element that pertains to that particular stock. We 
can think of the common factors as forces that affect a group of stocks. These might be all the stocks 
in the banking industry, all stocks that are highly leveraged, all the smaller-capitalization stocks, etc. 
Below, we discuss possible types of factors in detail.
By identifying important factors, we can reduce the size of the problem. Instead of dealing with 
6000 stocks (and 18,003,000 independent variances and covariances), we deal with 68 factors. The 
stocks change, the factors do not. The situation is much simpler when we focus on the smaller 
number of factors and allow the stocks to change their exposures to those factors.
A structural risk model begins by analyzing returns according to a simple linear structure with four 
components: the stock's excess returns, the stock's exposure to the factors, the attributed factor 
returns, and the specific returns. The structure is
where rn(t) =
excess return (return above the risk-free return) 
on stock n during the period from time t to time 
t + 1
Xn,k(t) =
exposure of asset n to factor k, estimated at time 
t. Exposures are frequently called factor 
loadings. For industry factors, the exposures are 
either 0 or 1, indicating whether the stock 
belongs to that industry or not.9 For the other 
common factors, the exposures are standardized 
so that the average
8The authors have a history of interest in structural risk models, through their long association with BARRA.
9With adequate data, one can split large conglomerates into their components.


---


### Page 63


Page 56

exposure over all stocks is 0, and the standard 
deviation across stocks is 1.
bk(t) =
factor return to factor k during the period from 
time t to time t + 1.
un(t) =
stock n's specific return during the period from 
time t to time t + 1. This is the return that cannot 
be explained by the factors. It is sometimes 
called the idiosyncratic return to the stock: the 
return not explained by the model. However, the 
risk model will account for specific risk. Thus 
our risk predictions will explicitly consider the 
risk of un.
We have been very careful to define the time structure in this model. The exposures are known at 
time t, the beginning of the period. The asset returns, factor returns, and specific returns span the 
period from time t to time t + 1. In the rest of this chapter, we will suppress the explicit time 
variables.
We do not mean to convey any sense of causality in this model structure. The factors may or may 
not be the basic driving forces for security returns. In our view, they are merely dimensions along 
which to analyze risk.
We will now assume that the specific returns are not correlated with the factor returns and are not 
correlated with each other. With these assumptions and the return structure of Eq. (3.16), the risk 
structure is
where Vn,m =
covariance of asset n with asset m. If n = m, this gives 
the variance of asset n
Xn,k1 =
exposure of asset n to factor k1, as defined above.
Fk1,k2 =
covariance of factor k1 with factor k2. If k1 = k2, this 
gives the variance of factor k1.
Δn,m =
specific covariance of asset n with asset m. We 
assume that all specific return correlations are zero, 
and so this term is zero unless n = m. In that case, this 
gives the specific variance of asset n.


---


### Page 64


Page 57
Choosing the Factors
The art of building multiple-factor risk models involves choosing appropriate factors. This search 
for factors is limited by only one key constraint: All factors must be a priori factors. That is, even 
though the factor returns are uncertain, the factor exposures must be known a priori, i.e. at the 
beginning of the period.
Within the constraint that the factors be a priori factors, a wide variety of factors are possible. We 
will attempt a rough classification scheme. To start, we can divide factors into three categories: 
responses to external influences, cross-sectional comparisons of asset attributes, and purely internal 
or statistical factors.10 We will consider these in turn.
Responses to External Influences
One of the prevalent themes in the academic literature of financial economics is that there should be 
a demonstrable link between outside economic forces and the equity markets. The response factors 
are an attempt to capture that link. These factors include responses to return in the bond market 
(sometimes called bond beta), unexpected changes in inflation (inflation surprise), changes in oil 
prices, changes in exchange rates, changes in industrial production, and so on. These factors are 
sometimes called macrofactors. These measures can be powerful, but they suffer from three serious 
defects. The first is that we must estimate the response coefficient through regression analysis or 
some similar technique. A model with nine macrofactors covering 1000 stocks would require 1000 
time series regressions each month, with each regression estimating nine response coefficients from 
perhaps 60 months of data. This leads to errors in the estimates, commonly called an error in 
variables problem.
The second drawback is that we base the estimate on behavior over a past period of generally 5 
years. Even if this estimate is
10This classification scheme does not imply that investors can choose only one category of factors. For 
example, we have observed that factors based on responses to external influences do not add explanatory power 
to models built from factors based on cross-sectional comparisons of asset attributes. At least implicitly, the 
cross-sectional factors contain the response factors.


---


### Page 65


Page 58
accurate in the statistical sense of capturing the true situation in the past, it may not be an accurate 
description of the current situation. In short, these response coefficients can be nonstationary. For 
example, the company may have changed its business practice by trying to control foreign exchange 
exposure.
Third, several of the macroeconomic data items are of poor quality, gathered by the government 
rather than observed in the market. This leads to inaccurate, delayed, and relatively infrequent 
observations.
Cross-Sectional Comparisons
These factors compare attributes of the stocks, with no link to the remainder of the economy. Crosssectional attributes generally fall into two groups: fundamental and market. Fundamental attributes 
include ratios such as dividend yield and earnings yield, plus analysts' forecasts of future earnings 
per share. Market attributes include volatility over a past period, return over a past period, option 
implied volatility, share turnover, etc. To some extent, market attributes such as volatility and 
momentum may have the same difficulties (errors in variables, nonstationarity) that we described in 
the section above on the external response factors. Here, however, the factor interpretation is 
somewhat different. Take, for example, a momentum factor. Let's say this measures the price 
performance of the stock over the past 12 months. This factor is not intended as a forecast of 
continued success or of some mean reversion. It is merely a recognition that stocks that have been 
relatively successful (unsuccessful) over the past year will quite frequently behave in a common 
fashion. Sometimes the momentum will be reinforced, at other times it will be reversed, and at yet 
other times it will be irrelevant. We are accounting for the fact that in 5 or 6 months of the year, 
controlling for other attributes, previously successful stocks behave in a manner that is very 
different from that of previously unsuccessful stocks. We could say the same for stocks with high 
historical volatility, or other such factors. In our experience, these cross-sectional comparisons are 
quite powerful factors.
Statistical Factors
It is possible to amass returns data on a large number of stocks, turn the crank of a statistical meat 
grinder, and admire the factors


---


### Page 66


Page 59
produced by the machine: factor ex machina. This can be accomplished in an amazingly large 
number of ways: principal component analysis, maximum likelihood analysis, expectations 
maximization analysis. One can use a two-step approach by getting first the factors and then the 
exposures, simultaneously estimate both factors and exposures, or turn the problem on its head in 
the imaginative approach taken by Connor and Korajczyk (1988). We usually avoid statistical 
factors, because they are very difficult to interpret, and because the statistical estimation procedure 
is prone to discovering spurious correlations. These models also cannot capture factors whose 
exposures change over time. The statistical estimation machinery assumes and relies on each asset's 
constant exposure to each factor over the estimation period. For example, statistical models cannot 
capture momentum factors.
Given the many possible factors, we choose those which satisfy three criteria: They are incisive, 
intuitive, and interesting. Incisive factors distinguish returns. For example, if we look along the 
volatility axis, we will find that low-volatility stocks perform differently from high-volatility stocks 
at least three times per year. If we don't monitor our overall volatility exposure, then our returns can 
be upset with disturbing frequency.
Intuitive factors relate to interpretable and recognizable dimensions of the market. Credible stories 
define these factors. For example, size distinguishes the big companies at one end from the small 
companies at the other. Momentum separates the firms that have performed well from the firms that 
have done relatively poorly. Intuitive factors arise from recognizable investment themes. Factors in 
the U.S. equity market include industries, plus size, yield, value, success, volatility, growth, 
leverage, liquidity, and foreign currency sensitivity.
Interesting factors explain some part of performance. We can attribute a certain amount of return to 
each factor in each period. That factor might help explain exceptional return or beta or volatility. 
For example, stocks of large companies did well over a particular period. Or, high-volatility stocks 
are high-beta stocks.
Research leading to the appropriate factors, then, depends on both statistical techniques and 
investment intuition. Statistical techniques can identify the most incisive and interesting factors.


---


### Page 67


Page 60
Investment intuition can help identify intuitive factors. Factors can have statistical significance or 
investment significance or both. Model research must take both forms of significance into account.
Given the above general discussion on choosing appropriate factors for a multiple-factor risk model, 
what typical factors do we choose? They fall into two broad categories: industry factors and risk 
indices. Industry factors measure the differing behavior of stocks in different industries. Risk indices 
measure the differing behavior of stocks across other, nonindustry dimensions.
Industry Factors
Industry groupings partition stocks into nonoverlapping classes. Industry groupings should satisfy 
several criteria:
• There should be a reasonable number of companies in each industry.
• There should be a reasonable fraction of capitalization in each industry.
• They should be in reasonable accord with the conventions and mindset of investors in that market.
For example, Table 3.2 shows the breakdown of a broad universe of over 11,000 U.S. stocks by 
BARRA industry group as of the end of August 1998.
Industry exposures are usually 0/1 variables: Stocks either are or are not in an industry. The market 
itself has unit exposure in total to the industries. Since large corporations can do business in several 
industries, we can extend the industry factors to account for membership in multiple industries. For 
example, for September 1998, BARRA's U.S. Equity risk model classified GE as 58 percent 
financial services, 20 percent heavy electrical equipment, 8 percent media, 7 percent medical 
products, and 7 percent property & casualty insurance.
Risk Indices
Industries are not the only sources of stock risk. Risk indices measure the movements of stocks 
exposed to common investment


---


### Page 68


Page 61
TABLE 3.2 
U.S. Equity Market Industry Breakdown: August 1998
Industry
Number of Firms
Percent of Market 
Capitalization
Mining & metals
216
0.77
Gold
122
0.25
Forest products and paper
112
1.04
Chemicals
288
2.99
Energy reserves & production
348
4.07
Oil refining
69
0.78
Oil services
84
1.04
Food & beverages
246
4.42
Alcohol
32
0.21
Tobacco
13
0.82
Home products
108
2.42
Grocery stores
53
0.66
Consumer durables
124
0.38
Motor vehicles & parts
141
1.79
Apparel & textiles
207
0.51
Clothing stores
72
0.59
Specialty retail
301
1.94
Department stores
33
2.24
Construction & real property
480
1.65
Publishing
142
0.91
Media
121
2.05
Hotels
89
0.38
Restaurants
182
0.69
Entertainment
139
1.28
Leisure
267
0.69
Environmental services
125
0.41
Heavy electrical equipment
98
0.70
Heavy machinery
50
0.42
Industrial parts
380
1.25
Electric utilities
100
2.62
Gas & water utilities
81
0.61
Railroads
33
0.63


---


### Page 69


Airlines
47
0.51
Trucking, shipping, air freight
116
0.34
Continued


---


### Page 70


Page 62
(continued)
TABLE 3.2
Industry
Number of Firms
Percent of Market 
Capitalization
Medical providers & services
263
1.22
Medical products
442
2.91
Drugs
409
6.70
Electronic equipment
699
3.22
Semiconductors
196
1.94
Computer hardware, office equipment
388
4.62
Computer software
574
4.17
Defense & aerospace
95
1.55
Telephones
102
5.18
Wireless telecommunications
57
0.57
Information services
576
2.57
Industrial services
251
0.94
Life & health insurance
75
1.55
Property & casualty insurance
148
4.22
Banks
702
8.47
Thrifts
299
0.71
Securies & asset management
188
1.63
Financial services
534
5.80
Total
11,017
100.00
themes. Risk indices we have identified in the United States and other equity markets fall into these 
broad categories:
Volatility. Distinguishes stocks by their volatility. Assets that rank high in this dimension have been 
and are expected to be more volatile than average.
Momentum. Distinguishes stocks by recent performance.
Size. Distinguishes large stocks from small stocks.
Liquidity. Distinguishes stocks by how much their shares trade.
Growth. Distinguishes stocks by past and anticipated earnings growth.


---


### Page 71


Page 63
Value. Distinguishes stocks by their fundamentals, in particular, ratios of earnings, dividends, cash 
flows, book value, sales, etc., to price: cheap versus expensive, relative to fundamentals.
Earnings volatility. Distinguishes stocks by their earnings volatility.
Financial leverage. Distinguishes firms by debt-to-equity ratio and exposure to interest-rate risk.
Any particular equity market can contain fewer or more risk indices, depending on its own 
idiosyncrasies.
Each broad category can typically contain several specific measurements of the category. We call 
these specific measurementsdescriptors. For instance, volatility measures might include recent daily 
return volatility, option-implied volatility, recent price range, and beta. Though descriptors in a 
category are typically correlated, each descriptor captures one aspect of the risk index. We construct 
risk index exposures by weighting the exposures of the descriptors within the risk index. We choose 
weights that maximize the explanatory and predictive power of the model. Relying on several 
different descriptors can also improve model robustness.
How do we quantify exposures to descriptors and risk indices? After all, the various categories 
involve different sets of natural units and ranges. To handle this, we rescale all raw exposure data:
where 
 is the raw exposure value mean and Std[xraw] is the raw exposure value standard 
deviation, across the universe of assets. The result is that each risk index exposure has mean 0 and 
standard deviation 1. This standardization also facilitates the handling of outliers.
As an example of how this works, BARRA's U.S. Equity model assigns General Electric a size 
exposure of 1.90 for September 1998. This implies that, not surprisingly, General Electric lies 
significantly above average on the size dimension. For the same date, the model assigns Netscape a 
size exposure of – 1.57. Netscape lies significantly below average on this dimension.


---


### Page 72


Page 64
Structural Risk Model Covariance
The technical appendix discusses in detail how Eq. (3.16); the structural return equation, together 
with observed asset returns, leads to estimates of factor returns and specific returns. It also describes 
how those returns, estimated historically, lead to forecasts of the factor covariance matrix and the 
specific covariance matrix of Eq. (3.17). Here, we will assume that we have these covariance 
matrices and focus on the uses of a risk model.
The Uses of a Risk Model
A model of risk has three broad uses. They involve the present, the future, and the past. We will 
describe them in turn, mainly focusing here on uses concerning the present. We will treat future and 
past risk in more detail in later chapters.
The Present: 
Current Portfolio Risk Analysis
The multiple-factor risk model analyzes current portfolio risk. It measures overall risk. More 
significantly, it decomposes that risk in several ways. This decomposition of risk identifies the 
important sources of risk in the portfolio and links those sources with aspirations for active return.
One way to divide the risk is to identify the market and residual components. An alternative is to 
look at risk relative to a benchmark and identify the active risk. A third way to divide the risk is 
between the model risk and the specific risk. The risk model can also perform marginal analysis: 
What assets are most and least diversifying in the portfolio, at the margin?
Risk analysis is important for both passive management and active management. Passive managers 
attempt to match the returns to a particular benchmark. Passive managers run index funds. However, 
depending on the benchmark, the manager's portfolio may not include all the stocks in the 
benchmark. For example, for a passive small-stock manager, transactions costs of holding the 
thousands of assets in a broad small-stock benchmark might be prohibitive. Current portfolio risk 
analysis can tell a passive manager the risk of his or her portfolio relative to the benchmark. This is 
the active risk, or tracking error. It is the volatility of the difference in


---


### Page 73


Page 65
return between the portfolio and the benchmark. Passive managers want minimum tracking error.
Of course, the focus of this book is active management. The goal of active managers is not to track 
their benchmarks as closely as possible, but rather to outperform those benchmarks. Still, risk 
analysis is important in active management, to focus active strategies. Active managers want to take 
on risk only along those dimensions where they believe they can outperform.
By suitably decomposing current portfolio risk, active managers can better understand the 
positioning of their portfolios. Risk analysis can tell active managers not only what their active risk 
is, but why and how to change it. Risk analysis can classify active bets into inherent bets, intentional 
bets, and incidental bets:
Inherent. An active manager who is trying to outperform a benchmark (or market) must bear the 
benchmark risk, i.e., the volatility of the benchmark itself. This risk is a constant part of the task, not 
under the portfolio manager's control.
Intentional. An active portfolio manager has identified stocks that she or he believes will do well 
and stocks that she or he believes will do poorly. In fact, the stocks with the highest expected returns 
should provide the highest marginal contributions to risk. This is welcome news; it tells the portfolio 
manager that the portfolio is consistent with his or her beliefs.
Incidental. These are unintentional side effects of the manager's active position. The manager has 
inadvertently created an active position on some factor that contributes significantly to marginal 
active risk. For example, a manager who builds a portfolio by screening on yield will have a large 
incidental bet on industries that have higher than average yields. Are these industry bets intentional 
or incidental? Incidental bets often arise through incremental portfolio management, where a 
sequence of stock-by-stock decisions, each plausible in isolation, leads to an accumulated incidental 
risk.
To understand portfolio risk characterization more concretely, consider the following example. 
Using the Major Market Index (MMI) as an investment portfolio, analyze its risk relative to the


---


### Page 74


Page 66
S&P 500 as of the end of December 1992. The portfolio is shown in Table 3.3.
Comparing risk factor exposures versus the benchmark, this portfolio contains larger, less volatile 
stocks, with higher leverage and foreign income, and lower earnings variability: what you might 
expect from a portfolio of large stocks relative to a broader index. The portfolio also contains 
several industry bets.
The multiple-factor risk model forecasts 20.5 percent volatility for the portfolio and 20.1 percent 
volatility for the index. The portfolio tracking error is 4.2 percent. Assuming that active returns are 
normally distributed, the portfolio annual return will lie within 4.2 percentage points of the index 
annual return roughly two-thirds of the time. The model can forecast the portfolio's beta. Beta meaTABLE 3.3

Stock
Shares
Percent Weight
Marginal Contribution 
to Active Risk
American Express
100
2.28
0.006
AT&T
100
4.68
–0.009
Chevron
100
6.37
0.040
Coca-Cola
100
3.84
0.029
Disney
100
3.94
0.018
Dow Chemicals
100
5.25
0.063
DuPont
100
4.32
0.041
Eastman Kodak
100
3.71
0.055
Exxon
100
5.61
0.047
General Electric
100
7.84
0.042
General Motors
100
2.96
0.046
IBM
100
4.62
0.074
International Paper
100
6.11
0.063
Johnson & Johnson
100
4.63
0.038
McDonalds
100
4.47
0.042
Merck
100
3.98
0.030
3M
100
9.23
0.057
Philip Morris
100
7.07
0.038
Procter & Gamble
100
4.92
0.040
Sears
100
4.17
0.010


---


### Page 75


Page 67
sures the portfolio's inherent risk: its exposure to movements of the index. The MMI portfolio beta 
is 0.96. This implies that if the S&P 500 excess return were 100 basis points, we would expect the 
portfolio return to be 96 basis points.
As all economists know, life is led at the margin. The risk model will let us know the marginal 
impact on total, residual, or active risk of changes in portfolio exposures to factors or changes in 
stock holdings. The technical appendix provides mathematical details.
As an example, Table 3.3 also displays each asset's marginal contribution to active risk, the change 
in active risk given a 1 percent increase in the holdings of each stock. According to Table 3.3, 
increasing the holdings of American Express from 2.28 to 3.28 percent should increase the active 
risk by 0.6 basis point. Table 3.3 also shows AT&T—with the smallest (and in fact negative) 
marginal contribution to active risk—to be the most diversifying asset in the portfolio, and IBM—
with the largest marginal contribution to active risk—to be the most concentrating asset in the 
portfolio.
The Future
A risk model helps in the design of future portfolios. Risk is one of the important design parameters 
in portfolio construction, which trades off expected return and risk. Chapter 14, ''Portfolio 
Construction," will discuss this use of the risk model in some detail.
The Past
A risk model helps in evaluating the past performance of the portfolio. The risk model offers a 
decomposition of active return and allows for an attribution of risk to each category of return. Thus, 
the risks undertaken by the manager and the outcomes from taking those active positions will be 
clear. This allows the manager to determine which active bets have been rewarded and which have 
been penalized. There will be more on this topic in Chap. 17, "Performance Analysis."
How Well Do Risk Models Work?
We have chosen standard deviation as the definition of risk in part to facilitate aggregating risk from 
assets into portfolios. We have


---


### Page 76


Page 68
chosen the structural risk model methodology in order to accurately and efficiently forecast the 
required covariance matrix. Here we will describe some evidence that this methodology does 
perform as desired.
We will consider evidence from two studies. First, we will discuss a comparison of alternative 
forecasts of standard deviations: portfolio-based versus historical. The portfolio-based approach, 
aggregating from assets into portfolios, utilized structural risk models. Second, we will describe a 
comparison of historical forecasts of different risk measures: standard deviation versus alternatives. 
These alternative measures—e.g., downside risk—must forecast entirely on the basis of historical 
risk. These two levels of tests imply that we can forecast only standard deviations from historical 
data, and that portfolio-based forecasts of standard deviation surpass those historical estimates. We 
will not discuss comparisons of alternative structural risk models, but for more information, see 
Connor (1995) or Sheikh (1996).
The first study [Kahn (1997)] looked at 29 equity and bond mutual funds. For each fund, at a 
historical analysis date, the study generated two alternative forecasts of standard deviation: 
portfolio-based, using structural risk models, and historical, using the prior three-year standard 
deviation (from monthly returns). The study then analyzed each fund's performance over the 
subsequent year. The analysis period was 1993/1994. The study obviously was not exhaustive, as it 
analyzed only 29 funds, chosen based on the criteria of size, investor interest, and return patterns. 
The difficulty of obtaining fund holdings makes a comprehensive study of this type quite difficult.
The study analyzed how many funds experienced returns more than two standard deviations from 
the mean. With accurate risk forecasts, such returns should occur only about 5 percent of the time.
Using structural risk models and portfolio holdings to predict standard deviations, the study found 
zero three-sigma events and one two-sigma outcome (3 percent of observations); 76 percent of the 
observations were less than one sigma in magnitude. The historical risk results were not nearly as 
encouraging: there were one three-sigma outcome (3 percent of observations) and five two-


---


### Page 77


Page 69
sigma outcomes (17 percent of observations), and then 72 percent of the outcomes were less than 
one sigma in magnitude.
Of course, the portfolio-based forecasts could have outperformed the historical forecasts in this test 
by consistently overpredicting risk. Accurate risk forecasts should lead to few surprises, not zero 
surprises. However, subsequent analysis found no statistically significant evidence that either 
method over- or underpredicted risk on average.
A final test compared the two alternative forecasts to the standard deviation of the excess returns 
over the following year: the realized risk. The result: There was a much stronger relationship 
between portfolio-based forecasts and subsequent risk than between historical risk and subsequent 
risk.
The second study [Kahn and Stefek (1996)] compared the persistence of alternative risk measures 
(standard deviation, semivariance, target semivariance, shortfall probability) for 290 domestic 
equity mutual funds, 185 domestic bond mutual funds, and 1160 individual U.S. equities. In each 
case, the study looked at two consecutive five-year periods: January 1986 through December 1990 
and January 1991 through December 1995 for the mutual funds; and September 1986 through 
August 1991 and September 1991 through August 1996 for the individual equity returns.
Because the alternative risk measures are in large part a function of the variance—for example, the 
semivariance is to first order just half the variance—the study explicitly examined the persistence of 
the information beyond that implied by the variance. So, for instance, it investigated the persistence 
of abnormal semivariance: semivariance minus half the variance. After all, the only reason to 
choose an alternative risk measure is for the information beyond variance that it contains.
The tests for persistence within each group of funds or assets simply regressed the risk measure in 
period 2 against the risk measure in period 1. Evidence of persistence includes high R2 statistics for 
the regression and significant positive t statistics. The study tests whether higher- (lower-) risk 
portfolios in period 1 are also higher- (lower-) risk portfolios in period 2. We can use historical risk 
to forecast a future risk measure only if that risk measure persists.
To summarize the study results, standard deviation and variance exhibit very high persistence. The 
alternative risk measures


---


### Page 78


Page 70
exhibited no persistence beyond that implied by just the persistence of variance. It appears that we 
cannot forecast risk information beyond variance. Many other studies have shown that asset returns 
exhibit wide distributions, implying that we should be able to forecast something beyond variance 
(e.g., kurtosis). But this study investigates a different question; whether a portfolio with a wider 
distribution than average persists in exhibiting a wider distribution than average. This is the 
important question for portfolio selection, and the answer appears to be no.
Overall, these two studies confirm the important roles played by standard deviation and structural 
risk models in active management.
Summary
Active management centers on the trade-off between expected returns and risk. This chapter has 
focused on risk. We have quantified risk as the standard deviation of annual returns, and the cost of 
risk as the variance of annual returns. Active managers care mainly about active and residual risk. 
Risk models, and structural risk models in particular, can provide insightful analysis by 
decomposing risk into total and active risk, market (or benchmark) and residual risk, model and 
specific risk; and by identifying inherent, intentional, and incidental bets. Risk models can analyze 
the present risks and bets in a portfolio, forecast future risk as part of the portfolio construction 
process, and analyze past risks to facilitate performance analysis. The evidence shows that structural 
risk models perform as desired.
Problems
1. If GE has an annual risk of 27.4 percent, what is the volatility of monthly GE returns?
2. Stock A has 25 percent risk, stock B has 50 percent risk, and their returns are 50 percent 
correlated. What fully invested portfolio of A and B has minimum total risk? (Hint: Try solving this 
graphically (e.g. in Excel), if you cannot determine the answer mathematically.)


---


### Page 79


Page 71
3. What is the risk of an equal-weighted portfolio consisting of five stocks, each with 35 percent 
volatility and a 50 percent correlation with all other stocks? How does that decrease as the portfolio 
increases to 20 stocks or 100 stocks?
4. How do structural risk models help in estimating asset betas? How do these betas differ from 
those estimated from a 60-month beta regression?
References
Arrow, Kenneth J. Essays in the Theory of Risk-Bearing. (Chicago: Markham Publishing Company, 
1971).
Bernstein, Peter L. Against the Gods: The Remarkable Story of Risk. (New York: John Wiley & 
Sons, 1996).
Bollerslev, Tim, Ray Y. Chou, and Kenneth F. Kroner. "ARCH Modeling in Finance."Journal of 
Econometrics, vol. 52, 1992, pp. 5–59.
Borch, Karl H. The Economics of Uncertainty. (Princeton, N.J.: Princeton University Press, 1972).
Connor, Gregory. "The Three Types of Factor Models: A Comparison of Their Explanatory Power." 
Financial Analysts Journal, vol. 51, no. 3, May/June 1995, pp. 42–46.
Connor, Gregory, and Robert A. Korajczyk. "Risk and Return in an Equilibrium APT: Application 
of a New Test Methodology." Journal of Financial Economics, vol 21, no. 2, September 1988, pp. 
255–289.
Engle, Robert F. "Autoregressive Conditional Heteroskedasticity with Estimates of the Variance of 
U.K. Inflation." Econometrica, vol. 50, 1982, pp. 987–1008.
Fama, Eugene, and James MacBeth. "Risk, Return, and Equilibrium: Empirical Tests." Journal of 
Political Economy, vol. 81, May–June 1973, pp. 607–636.
Grinold, Richard C., and Ronald N. Kahn. "Multiple Factor Models for Portfolio Risk." In A 
Practitioner's Guide to Factor Models, edited by John W. Peavy III. (Charlottesville, Va.: AIMR, 
1994).
Jeffery, R. H. "A New Paradigm for Portfolio Risk." Journal of Portfolio Management, vol. 10, no. 
1, Fall 1984, pp. 33–40.
Kahn, Ronald N. "Mutual Fund Risk." BARRA Research Insights (Berkeley, Calif.: BARRA, 1997).
Kahn, Ronald N., and Daniel Stefek. "Heat, Light, and Downside Risk." BARRA manuscript, 1996.
Kosmicke, R. "The Limited Relevance of Volatility to Risk." Journal of Portfolio Management, vol. 
12, no. 1, Fall 1986, pp. 18–21.
Litterman, Robert. "Hot Spots and Hedges." Journal of Portfolio Management, December 1996, pp. 
52–75.
Markowitz, H. M. Portfolio Selection: Efficient Diversification of Investment. Cowles Foundation 
Monograph 16 (New Haven, Conn.: Yale University Press, 1959).


---

