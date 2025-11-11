# Grinold-Kahn Active Portfolio Management

## Pages 161-180


### Page 161


Page 154
Equation (6.6) provides some further intuition into the information coefficient. For example, we saw 
that an information coefficient of 0.0577 can lead to an information ratio above 1.0 (top decile, 
according to Chap. 5). Using Eq. (6.6), an IC = 0.0577 corresponds to correctly forecasting direction 
only 52.885 percent of the time—a small edge indeed.
These examples not only show the formula at work, but also show how little information one needs 
in order to be highly successful. In fact, an information coefficient of 0.02 between forecasted stock 
return and realized return over 200 stocks each quarter [with an implied accuracy of only 51 percent 
according to Eq. (6.6)] will produce a highly respectable information ratio of 0.56.
Additivity
The fundamental law is additive in the squared information ratios. Suppose there are two classes of 
stocks. In class 1 you have BR1 stocks and a skill level of IC1. Class 2 has BR2 stocks and a skill 
level IC2. The information ratio for the aggregate will be
assuming optimal implementation of the alphas across the combined set of stocks.5 Notice that this 
is the sum of the squared information ratios for the first class and second class combined. Suppose 
the manager currently follows 200 stocks with semiannual forecasts; the breadth is 400. The 
information coefficient for these forecasts is 0.04. The information ratio will be 
. 
How would the information ratio and value added increase if the manager was to follow an 
additional 100 stocks (again with two forecasts per year) with information coefficient 0.03? The 
manager's value added will be proportional to 0.64 + (0.03)2 · 200 = 0.64 + 0.18 = 0.82. There will 
be a 28 percent increase in the manager's ability to add value. The information ratio will increase 
from 0.8 to 
.
5For example, if you index the second set of stocks, the combined information ratio will be only IR1.


---


### Page 162


Page 155
The additivity works along other dimensions as well. Suppose a manager follows 400 equities and 
takes a position on these on the average of once per year. The manager's information coefficient is 
0.03. This yields an information ratio of 
. In addition, the manager makes a 
quarterly forecast on the market. The information coefficient for the market forecasts is 0.1. The 
information ratio for the market timing is 
. The overall information ratio will be the 
square root of the sum of the squared information ratios for stock selection and market timing: 0.63.
We can even carry this notion to an international portfolio. Figure 6.2 shows the breakdown of 
return on an international portfolio. The active return comes from three main sources: active 
currency positions, active allocations across countries, and active allocations within country 
markets.
Figure 6.2


---


### Page 163


Page 156
Assume that we are based in London, and that we invest in four countries: the United States, Japan, 
Germany, and the United Kingdom. There are three currency bets available to us;6 we revise our 
currency position each quarter, and so we make 12 independent bets per year. We also make active 
bets across countries. These bet on the local elements of market return (separated from the currency 
component). We revise these market allocations each quarter. In addition we select stocks in each of 
the markets. We follow 400 stocks in the United States, 300 in Japan, 200 in the United Kingdom, 
and 100 in Germany. We revise our forecasts on these stocks once a year. Suppose our skill levels 
are ICC for currency, ICM for market allocation, and ICUS, ICJ, ICUK, and ICG for the national stocks. 
The overall information ratio will be
To make things simple, suppose that ICUS = ICJ = ICUK = ICG = 0.02. Then the squared information 
ratio contribution from the stocks will be 0.40 = 1000 · (0.02)2. For the timing component to 
contribute equally, we would need ICC = ICM = 0.129, since 0.40 = 24 · (0.129)2. Consider a more 
realistic (although still optimistic) information coefficient of 0.075 for the currency and market 
allocation decisions. That would make the contribution from currency and market allocation 0.135. 
The total squared information ratio would be 0.535 = 0.40 + 0.135. The total information ratio is 
.
The additivity holds across managers. In this case, we must assume that the allocation across the 
managers is optimal. Suppose a sponsor hires three equity managers with information ratios 0.75,
6With only one country, we would have no currency bet. Two countries would allow one currency bet, etc. The 
total active currency position must be zero.


---


### Page 164


Page 157
0.50, and 0.30. Then the information ratio that the sponsor can obtain is 0.95,7 since (0.95)2 = (0.75)
2 + (0.50)2 + (0.30)2.
There are other applications of the law. Most notable is its use in scaling alphas; i.e., making sure 
that forecasts of exceptional stock returns are consistent with the manager's information ratio. That 
point will be discussed in Chap. 14, ''Portfolio Construction."
Assumptions
The law, like everything else, is based on assumptions that are not quite true. We'll discuss some of 
those assumptions later. However, the basic insight we can gain from the law is clear: It is important 
to play often (high BR) and to play well (high IC).
The forecasts should be independent. This means that forecast 2 should not be based on a source of 
information that is correlated
7Suppose manager n has information ratio IRn and active risk ωn. The sponsor's utility is
assuming independent active risks and a sponsor's active risk aversion of λSA. The optimal allocation to manager n 
is
The overall alpha will be
The active variance will be
and so the ratio of the alpha to the standard deviation will be


---


### Page 165


Page 158
with the sources of forecast 1. For example, suppose that our first forecast is based on an assumption 
that growth stocks will do poorly, and our second is based on an assumption that high-yield stocks 
will do well. These pieces of information are not independent; growth stocks tend to have very low 
yields, and not many high-yield stocks would be called growth stocks. We've just picked out two 
ways to measure the same phenomenon. An example of independent forecasts is a quarterly 
adjustment of the portfolio's beta from 1.00 to either 1.05 or 0.95 as a market timing decision based 
on new information each quarter.
In a situation where analysts provide recommendations on a firm-by-firm basis, it is possible to 
check the level of dependence among these forecasts by first quantifying the recommendations and 
then regressing them against attributes of the firms. Analysts may like all the firms in a particular 
industry: Their stock picks are actually a single industry bet. All recommended stocks may have a 
high earnings yield: The analysts have made a single bet on earnings-to-price ratios. Finally, 
analysts may like all firms that have performed well in the last year; instead of a firm-by-firm bet, 
we have a single bet on the concept of momentum. More significantly, the residuals of the 
regression will actually be independent forecasts of individual stock return. Thus the regression 
analysis gives us the opportunity both to uncover consistent patterns in our recommendations and to 
remove them if we choose.
The same masking of dependence can occur over time. If you reassess your industry bets on the 
basis of new information each year, but rebalance your portfolios monthly, you shouldn't think that 
you make 12 industry bets per year. You just make the same bet 12 times.
We can see how dependence in the information sources will lower our overall skill level with a 
simple example. Consider the case where there are two sources of information. Separately, each has 
a level of skill IC; that is, the forecasts have a correlation of IC with the eventual returns. However, 
if the two information sources are dependent, then the information derived from the second source is 
not entirely new. Part of the second source's information will just reinforce what we knew from the 
first source, and part will be new or incremental information. We have to discover the value of the 
incremental information. As one can imagine, the greater


---


### Page 166


Page 159
the dependence between the two information sources, the lower the value of the incremental 
information. If γ is the correlation between the two information sources, then the skill level of the 
combined sources, IC(com), will be
If there is no correlation between sources (γ = 0), then IC2(com) = 2 · IC2—the two sources will add 
in their ability to add value. As γ increases toward 1, the value of the second source diminishes.
For example, recall the case earlier in this chapter where the residual return θn on stock n was made 
up of 300 nuggets of return θn,j for j = 1,2, . . . , 300. Suppose we have two information sources on 
the stocks. Source 1 knows θn,1 and θn,2 and source 2 knows θn,2 and θn,3. The information coefficient 
of each source is 0.0816. In this situation, the information coefficient of the combined sources will 
be 0.0942, since the information supplied by source 2 is correlated with that supplied by source 1; γ 
= 0.5. The formula gives 
, which you can confirm by a direct calculation.
The law is based on the assumption that each of the BR active bets has the same level of skill. In 
fact, the manager will have greater skills in one area than another. We can see from the additivity 
principle, Eq. (6.7), that the square of the information ratio is the sum of the squares of the 
information ratios for the particular sources. Figure 6.3 demonstrates this phenomenon. If we order 
the information sources from highest skill level to lowest, then the total value added is just the area 
under the "skill" curve. Notice that the law assumes that the skill curve is horizontal; i.e., we replace 
the sum of the skill levels by an average skill level.
The strongest assumption behind the law is that the manager will accurately gauge the value of 
information and build portfolios that use that information in an optimal way. This requires insight 
and humility, a desirable combination that is not usually found in one individual.


---


### Page 167


Page 160
Figure 6.3
Not the Law of Large Numbers
A few investment professionals interpret the fundamental law of active management as a version of 
the statistical law of large numbers. This is a misinterpretation of one law or both. The law of large 
numbers says that sample averages for large samples will be very close to the true mean, and that 
our approximation of the true mean gets better and better as the sample gets larger.
The fundamental law says that more breadth is better if you can maintain the skill level. However, 
the law is just as valid with a breadth of 10 as with a breadth of 1000. The information ratio is still 
This confusion stems from the role of breadth. More breadth at the same skill level lets us diversify 
the residual risk. This is analogous to the role of large sample sizes in the law of large numbers, 
where the large sample size allows us to diversify the sampling error.
Tests
The fundamental law is a guideline, not an operational tool. It is desirable that we have some faith in 
the law's ability to make


---


### Page 168


Page 161
reasonable predictions. We have conducted some tests of the law and found it to be excellent in its 
predictions.
The tests took the following form: Each year we supply alphas for BR stocks. The alphas are a 
mixture of the residual return on the stock over the next year and some random noise. The mixture 
can be set8 so that the correlation of the forecasts with the residuals will be IC. That gives us a 
prediction of the information ratio that we should realize with these alphas.
The realized information ratios for optimal portfolios based on these forecasts are statistically 
indistinguishable from the forecasts of the fundamental law. When we then impose institutional 
constraints limiting short sales, the realized information ratios drop somewhat.
Investment Style
The law encourages managers to have an eclectic style. If a manager can find some independent 
source of information that will be of use, then he or she should exploit that information. It is the 
manager's need to present a clear picture of his or her style to clients that inhibits the manager from 
adopting an eclectic style. At the same time, the sponsor who hires a stable of managers has an 
incentive to diversify their styles in order to ensure that their bets are independent. The way 
investment management is currently organized in the United States, the managers prepare the 
distinct ingredients and the sponsor makes the stew.
Summary
We have shown how the information ratio of an active manager can be explained by two 
components: the skill (IC) of the investment manager and the breadth (BR) of the strategy. These 
are related to the value added by the strategy by a simple formula [Eq. (6.3)].
8The forecast is
where z is a random number with mean 0 and variance 1. We see that Var{α} = IC2 · Var{θ} and Cov{α,θ} = IC2 · 
Var{θ}, and so Corr{α,θ} = IC.


---


### Page 169


Page 162
Three main assumptions underlie this result. First and foremost, we assumed that the manager has 
an accurate measure of his or her own skills and exploits information in an optimal way. Second, we 
assumed that the sources of information are independent; i.e., the manager doesn't bet twice on a 
repackaged form of the same information. Third, we assumed that the skill involved in forecasting 
each component, IC, is the same. The first assumption, call it competence or hypercompetence, is 
the most crucial. Investment managers need a precise idea of what they know and, more 
significantly, what they don't know. Moreover, they need to know how to turn their ideas into 
portfolios and gain the benefits of their insights. The second two assumptions are merely 
simplifying approximations and can be mitigated by some of the devices mentioned above.
The message is clear: you must play often and play well to win at the investment management 
game. It takes only a modest amount of skill to win as long as that skill is deployed frequently and 
across a large number of stocks.
Problems
1. Manager A is a stock picker. He follows 250 companies, making new forecasts each quarter. His 
forecasts are 2 percent correlated with subsequent residual returns. Manager B engages in tactical 
asset allocation, timing four equity styles (value, growth, large, small) every quarter. What must 
Manager B's skill level be to match Manager A's information ratio? What information ratio could a 
sponsor achieve by employing both managers, assuming that Manager B has a skill level of 8 
percent?
2. A stock picker follows 500 stocks and updates his alphas every month. He has an IC = 0.05 and 
an IR = 1.0. How many bets does he make per year? How many independent bets does he make per 
year? What does this tell you about his alphas?
3. In the example involving residual returns θn composed of 300 elements θn,j, an investment 
manager much choose between three research programs:


---


### Page 170


Page 163
a. Follow 200 stocks each quarter and accurately forecast θn,12 and θn,15.
b. Follow 200 stocks each quarter and accurately forecast θn,5 and θn,105.
c. Follow 100 stocks each quarter and accurately forecast θn,5, θn,12, and θn,105.
Compare the three programs, all assumed to be equally costly. Which would be most effective 
(highest value added)?
References
Divecha, Arjun, and Richard C. Grinold. "Normal Portfolios: Issues for Sponsors, Managers and 
Consultants." Financial Analysts Journal, vol. 45, no. 2, 1989, pp. 7–13.
Ferguson, Robert. "Active Portfolio Management." Financial Analysts Journal, vol. 31, no. 3, 1975, 
pp. 63–72.
———. "The Trouble with Performance Measurement." Journal of Portfolio Management, vol. 12, 
no. 3, 1986.
Fisher, Lawrence. "Using Modern Portfolio Theory to Maintain an Efficiently Diversified 
Portfolio." Financial Analysts Journal, vol. 31, no. 3, 1975, pp. 73–85.
Grinold, Richard. "The Fundamental Law of Active Management." Journal of Portfolio 
Management, vol. 15, no. 3, 1989, pp. 30–37.
Jacobs, Bruce I., and Kenneth N. Levy. "The Law of One Alpha." Journal of Portfolio 
Management, vol. 21, no. 4, 1995, pp. 78–79.
Rosenberg, Barr. "Security Appraisal and Unsystematic Risk in Institutional Investment." 
Proceedings of the Seminar on the Analysis of Security Prices (Chicago: University of Chicago 
Press, November 1976), pp. 171–237.
Rudd, Andrew. "Business Risk and Investment Risk." Investment Management Review, NovemberDecember 1987, pp. 19–27.
Sharpe, William F. "Mutual Fund Performance." Journal of Business, vol. 39, no. 1, January 1966, 
pp. 66–86.
Treynor, Jack, and Fischer Black. "How to Use Security Analysis to Improve Portfolio Selection." 
Journal of Business, vol. 46, no. 1, 1973, pp. 66–86.
Technical Appendix
In this appendix we derive the fundamental law. The derivation includes three steps:
• Measuring the impact of the information on the means and variances of the returns


---


### Page 171


Page 164
• Solution for the optimal policy
• Calculation and approximation of the information ratio
To facilitate the analysis, we will introduce orthogonal bases for both the residual returns and the 
information signals. We require these independent bases in order to isolate the independent bets 
driving the policy.
The Information Model
We can express the excess returns on the universe of N securities as
where β =
the asset's betas with respect to the benchmark
θ =
the residual returns
rB =
the excess return on the benchmark
We will model the residual returns θ as
where x
=
a vector of N uncorrelated standardized random 
variables, each with mean 0 and standard 
deviation 1
A =
an N by N matrix equal to the square root of the 
residual covariance matrix of r; i.e., 
Note that A has rank N – 1, since the benchmark holdings hB will satisfy AT · hB = 0.
If the residual returns are uncorrelated, then A is simply a diagonal matrix of residual risks. More 
generally, A linearly translates between the correlated residual returns and a set of uncorrelated 
movements.
Our information arrives as BR signals z. With very little loss of generality, we can assume that these 
signals z have a joint normal distribution with mean 0 and standard deviation equal to 1. We write z 
as


---


### Page 173


Page 165
where y =
a vector of BR uncorrelated random variables, 
each with mean 0 and standard deviation equal 
to 1
E =
the square root of the covariance matrix of z; 
i.e., Var{z} = E · ET
J =
the inverse of E
So our signals may be correlated. The matrix E, like the matrix A, translates to an equivalent set of 
uncorrelated signals. At one extreme, our signals may contain stock-specific information. Then E is 
the identity matrix. But for industry momentum signals, for example, E may separate industryspecific information from sector and marketwide information.
Let Q = Cov{θ,z} be the N by BR covariance matrix between the residual returns θ and signals z, 
and let P = Corr{x,y} be the N by BR correlation matrix between the vectors x and y. It follows that 
Q = A · P · ET. The items of interest to the active manager are the mean and variance of θ 
conditional on the signal z. These are9
Note:
• The unconditional expectation of α(z) is 0.
• The conditional variance of the residual returns is independent of the value of z.
• The unconditional variance of the alphas is Var{α(z)} =A · P · PT · AT.
The Objective
The active manager's objective is to maximize the value added through stock selection, as derived in 
Chap. 4. We are ignoring the benchmark timing component, although that will reappear in a later 
chapter devoted to benchmark timing.
9 We will develop these ideas more fully in Chap. 10. For now, we simply note that Eqs. (6A.4) and (6A.5) are 
based on best linear unbiased estimators. Equation (6A.4) is closely related to the regression result. If we 
regress θ against z, i.e., θn = a + b · zn + ∈n, then E{θn | zn} = a + b · zn. The regression coefficient b is Cov{θ,z} 
· Var-1{z}. Assuming a = 0 leads to Eq. (6A.4).


---


### Page 174


Page 166
The objective is: Given z, choose a residual position (i.e., β = 0) h*(z) to solve the optimization 
problem
This is the standard optimization, here conditional on particular information z. We will not impose 
the full investment condition, but rather the residual condition of zero beta.
The Optimal Active Position
The first-order conditions for the maximization problem, Eq. (6A.6), are
or, using Eqs. (6A.4) and (6A.5),
The additional restriction that h*(z) is a residual position, i.e., βT ·h*(z) = 0, will uniquely determine 
h*(z).
With some manipulation, we find
We have derived the optimal holdings, conditional on z. From here, we will need to calculate the 
information ratio conditional on z, and then take the expectation over the distribution of possible 
values of z.
Calculation and Approximation of the Information Ratio
The optimal portfolio's alpha is


---


### Page 175


Page 167
while the optimal portfolio's residual variance is
where the matrix calculations in Eqs. (6A.11) and (6A.12) are identical. Therefore, the squared 
information ratio conditional on the knowledge z, will be
The unconditional squared information ratio is
where Tr{•} is the trace (sum of the diagonal elements) and we have taken the expectation of the 
uncorrelated N[0,1] random variables y. (Note that E{y2} = 1.)
We complete our analysis by approximating Tr{PT · D · P}. We can write D as
With typical correlations being extremely close to zero, and the most optimistic being close to 0.1, 
we can safely ignore all but the first term in Eq. (6A.16). In effect, we are ignoring the reduction in 
variance due to knowledge of z. The trace of PT · P is therefore
where we are summing the correlations between orthonormal basis elements x of the residual 
returns and independent signals y over all assets and signals.
To achieve the form of the fundamental law requires two more steps. First, sum the correlation of 
each signal with the basis elements, over the basis elements:


---


### Page 176


Page 168
We then have that
which already exhibits the additivity of the fundamental law. Finally, by assuming that all the 
signals have equal value,
we find the desired result:
Exercises
For the following exercises, consider the following model of a stock picker's forecast monthly 
alphas:
where αn is the forecast residual return, θn is the subsequent realized residual return, and zn is a 
random variable with mean 0 and standard deviation 1, uncorrelated with θn and with zm (m 
 n).
1. Given that a = IC2, what coefficient b will ensure that
2. What is the manager's information coefficient in this model?
3. Assume that the model applies to the 500 stocks in the S&P 500, with a = 0.0001 and ωn = 20 
percent. What is the information ratio of the model, according to the fundamental law?
4. Distinguish this model of alpha from the binary model introduced in the main part of the chapter.
Applications Exercises
Consider the performance of the MMI versus the S&P 500 over the past 5 years.


---


### Page 177


Page 169
1. What are the active return and active risk of the MMI portfolio over this period? What is its 
information ratio (based on active risk and return)?
2. What is the t-statistic of the active return? How does it compare to the information ratio? 
Distinguish what the IR measures from what the t-statistic measures.


---


### Page 178


Page 173
Chapter 7— 
Expected Returns and the Arbitrage Pricing Theory
Introduction
We have now completed our treatment of fundamentals. The next three chapters cover expected 
returns and valuation.
The arbitrage pricing theory (APT) is an interesting and powerful alternative to the CAPM for 
forecasting expected returns. This chapter describes the APT and emphasizes its implications for 
active managers. The conclusions are:
• The APT is a model of expected returns.
• Application of the APT is an art, not a science.
• The APT points the quantitative manager toward the relationship between factors and expected 
returns.
• APT factors can be defined in a multitude of ways. These may be fundamental, technical, or 
macro factors.
• The flexibility of the APT makes it inappropriate as a model for consensus expected returns, but 
an appropriate model for a manager's expected returns.
• The APT is a source of information to the active manager. It should be flexible. If all active 
managers shared the same information, it would be worthless.
The APT requires less stringent assumptions than the CAPM and produces similar results. This 
makes it sound as if the APT is a dominant theory. The difficulty is that the APT says that it 
ispossible to forecast expected stock returns but it doesn't tell you


---


### Page 179


Page 174
how to do so. It has been called the ''arbitrary" pricing theory for just this reason. The CAPM, in 
contrast, comes with a user's manual.
The APT states that each stock's expected excess return is determined by the stock's factor 
exposures. The link between the expected excess return and the stock factor exposures is described 
in Eq. (7.2). For each factor, there is a weight (called a factor forecast) such that the stock's expected 
excess return is the sum over all the factors of the stock's factor exposures times the factor forecasts.
The theory doesn't say what the factors are, how to calculate a stock's exposure to the factors, or 
what the weights should be in the linear combination. This is where science steps out and art steps 
in.
In discussing the APT, one should be careful to distinguish among
• Stories that motivate the APT. These usually involve basic economic forces that alter the relative 
valuation of stocks. The motivating stories may mislead some people into thinking that it is 
necessary for the APT to be based on exogenous macroeconomic factors. The applications described 
in this chapter indicate that this is not the case.
• Attempts to implement the APT. The APT is by nature arbitrary. Different individuals' attempts to 
implement it will take different forms. One should not confuse a particular implementation with the 
theory.
• The theory. The technical theory has evolved since its origins in the mid- to late 1970s. This 
chapter will provide an idiosyncratic view of the theory. Other ways to look at the APT are cited in 
the chapter notes.
This chapter will first detail some weaknesses of the CAPM that the APT was designed to correct. It 
will then describe the APT and its evolution as a theory. The final sections of this chapter will deal 
with the problem of implementation and give some examples of ways in which people either have 
tried or could try to implement APT models.
Trouble with the CAPM
The CAPM is based on the notion that the market portfolio is not only mean/variance-efficient but, 
in fact, the fully invested


---


### Page 180


Page 175
portfolio with the highest ratio of expected excess return to volatility. In practice, the theory has 
been applied to say that common, broad-based stock indices are efficient: the S&P 500 in the United 
States, the FTA in the United Kingdom, and the TSE1 in Japan.
If we consider a broader notion of the market, including all bonds, international investments, and 
other assets such as precious metals, real property, etc., then we can see that the market consists of 
more than the local stock index. Even if the CAPM is true in some broader context of a worldwide 
portfolio, it cannot be valid in the restricted single-market world in which it is ordinarily applied. 
All of the other assumptions underlying the CAPM (mean/ variance preferences, identical 
expectations of mean and variance, no taxes or transactions costs, no restrictions on stock positions, 
etc.) can be challenged, adding additional wounds. The most grievous of these is the CAPM 
requirement that all participants know every stock's expected excess return. This assumption should 
be viewed in the context of our quest to get a handle on the expected excess returns in the first 
place! Thus we would suspect that the CAPM can be only approximately true. It provides a 
guideline that should be neither ignored nor taken as gospel.
One dramatic episode that points out the weakness of the CAPM occurred for U.S. equities in 1983 
and 1984, during a period characterized by a considerable drop in interest rates. The equities most 
adversely affected had high betas, and the equities most beneficially affected had low betas.
We can illustrate this episode by a simple experiment. In December 1982, take the stocks in the 
S&P 500, order them according to their predicted beta, and form ten portfolios, each with an equal 
amount of capitalization. Portfolio 1 has the lowest-beta stocks, portfolio 2 the next lowest group, 
and so on, with portfolio 10 holding the highest-beta stocks. Then follow the capitalization-weighted 
returns on these portfolios for the next 24 months. It turns out that over the out-of-sample period, the 
predicted betas were excellent forecasts of the realized betas. No problem here. In Fig. 7.1, we see 
the scatter diagram of predicted versus realized beta.
The regression line in Fig. 7.1 has a slope of 0.93, and the R2 of this regression was 0.89. The 
prediction of beta was quite accurate.
The CAPM would say that the alpha of each portfolio should be zero. It didn't turn out that way. Not 
only were several of


---

