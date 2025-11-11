# Grinold-Kahn Active Portfolio Management

## Pages 321-340


### Page 321


Page 316
of signals. Backtesting then takes those signals that have been identified as containing information 
and develops investable strategies. Backtesting looks not only at information content, but also at 
turnover, tradability, and transactions costs.
This chapter will focus very explicitly on information analysis. It will present a unified treatment of 
information analysis, with both theoretical discussions and concrete examples. Information analysis 
is a broad subject. This chapter will cover the general approach, but will also recommend a specific 
approach to best analyze investment information. The key insights in the chapter are as follows:
• Information analysis is a two-step process.
• Step 1 is to turn information into portfolios.
• Step 2 is to analyze the performance of those portfolios.
• Event studies provide analysis when information arrives episodically.
The chapter will describe how and where information appears in the active management process, 
and then introduce and discuss in detail the two-step process of information analysis. We will 
include some discussion of performance analysis, but a more indepth treatment of that subject will 
appear in Chap. 17. We will treat event studies of episodic information as a special topic. The 
chapter will end by describing the pitfalls of information analysis. Information analysis is a tool, 
and, as with a hammer, one must distinguish between thumb and nail.
Information and Active Management
Where and how does information arise in active management? Active managers, as opposed to 
passive managers, apply information to achieve superior returns relative to a benchmark. Passive 
managers simply try to replicate the performance of the benchmark. They have no information.
Active managers use information to predict the future exceptional return on a group of stocks. The 
emphasis is on predicting alpha, or residual return: beta-adjusted return relative to a benchmark. We 
want to know what stocks will do better than average and what stocks will do worse, on a riskadjusted basis.


---


### Page 322


Page 317
So, when we talk about information in the context of active management, we are really talking about 
alpha predictors. For any set of data pertaining to stocks, we can ask: Do these data help predict 
alphas? We will even call this set of data a predictor.
In general, any predictor is made up of signal plus noise. The signal is linked with future stock 
returns. The noise masks the signal and makes the task of information analysis both difficult and 
exciting. Random numbers contain no signal, only noise. Information analysis is an effort to find the 
signal-to-noise ratio.
A predictor will cover a number of time periods and a number of stocks in each time period. The 
information at the beginning of period t is a data item for each stock. The data item can be as simple 
as +1 for all stocks on a recommended buy list and –1 for all stocks on a sell list. On the other hand, 
the data item can be a precise alpha: 2.15 percent for one stock, –3.72 percent for another, etc. Other 
predictors might be scores. Crude scores can be a grouping of stocks into categories, a more refined 
version of the buy and sell idea. Other scores might be a ranking of the stocks along some 
dimension. Notice that it is possible to start with alphas and produce a ranking. It is also possible to 
start with a ranking and produce other scores, such as 4 for the stocks in the highest quartile, down 
to 1 for the stocks in the lowest quartile.
The predictors can be publicly available information, such as consensus earnings forecasts, or they 
can be derived data, such as a change in consensus earnings forecasts. Predictors are limited only by 
availability and imagination.
We can classify information along the following dimensions:
• Primary or processed
• Judgmental or impartial
• Ordinal or cardinal
• Historical, contemporary, or forecast
Primary information is information in its most basic form. Usually information is processed to some 
extent. An example would be a firm's short-term liabilities as a primary piece of information, and 
the ratio of those liabilities to short-term assets as a processed piece of information. Just because 
information is processed doesn't mean that it is necessarily better. It may be a poorer predictor of 
returns.


---


### Page 323


Page 318
Judgmental information comes with significant human input. It is, by its nature, irreproducible. 
Expectations data from a single expert or a panel of experts is an example.
With ordinal data, assets are classified into groups and some indication of the order of preference of 
one group over the other is provided. The buy, sell, hold classification is an example of ordinal data. 
With cardinal information, a number is associated with each asset, with some importance associated 
with the numerical values.
We can categorize information as historical, contemporary, or forecast. Average earnings over the 
past three years is historical information; the most recent earnings is current information; and 
forecast future earnings is forecast information.
In this chapter, we will use the example of book-to-price data in the United States to generate return 
predictors according to various standard schemes. For instance, we can generate a buy list and a sell 
list by ranking all stocks according to book-to-price ratios and placing the top half on the buy list 
and the bottom half on the sell list. The purpose of this and other examples is not to suggest novel 
new strategies, but simply to illustrate information analysis techniques.
Underlying the book-to-price examples will be the hypothesis that book-to-price ratios contain 
information concerning future stock returns, and, in particular, that high-book-to-price stocks will 
outperform low-book-to-price stocks. Is this hypothesis true? How much information is contained in 
book-to-price ratios? We will apply information analysis and find out.
Information Analysis
Information analysis is a two-step process:
Step 1: Turn predictions into portfolios.
Step 2: Evaluate the performance of those portfolios.
In step 1, the information is transformed into a concrete object: a portfolio. In step 2, the 
performance of the portfolio is then analyzed.
Information analysis is flexible. There are a great many ways to turn predictions into portfolios and 
a great many ways to evaluate performance. We will explore many of these alternatives below.


---


### Page 324


Page 319
Step 1: 
Information into Portfolios
Let's start with step 1, turning predictions into portfolios. Since we have predictions for each time 
period, we will generate portfolios for each time period.1 There are a great many ways to generate 
portfolios from predictions, and the procedure selected could depend on the type of prediction. Here 
are six possibilities. For each case, we have listed the general idea, and then discussed how to apply 
this to data concerning book-to-price ratios. Later we will analyze the performance of these 
portfolios.
• Procedure 1. With buy and sell recommendations, we could equal- (or value-) weight the buy 
group and the sell group.
Using book-to-price ratios, we can generate the buy and sell lists, as described above, by first 
ranking stocks by book-to-price and then putting the top half on the buy list and the bottom half on 
the sell list.
• Procedure 2. With scores, we can build a portfolio for each score by equal- (or value-) weighting 
within each score category.
We can generate scores from book-to-price ratios by ranking stocks by book-to-price ratio, as 
before, and then, for example, giving the top fifth of the list (by number or capitalization) a score of 
5, the next fifth a score of 4, down to the bottom fifth, with a score of 1. This is simply dividing 
stocks into quintiles by book-to-price.
• Procedure 3. With straight alphas, we can split the stocks into two groups, one group with higher 
than average alphas and one group with lower than average alphas. Then we can weight the stocks 
in each group by how far their alpha exceeds (or lies below) the average. This is an elaboration of 
procedure 1.
One way to generate alphas from book-to-price ratios is to assume that they are linearly related to 
the book-to-price ratios. So
1The choice of time period may affect information analysis. As a general comment, the investment time period 
should match the information time period. Portfolios based on daily information—information that changes 
daily and influences daily returns—should be regenerated each day. Portfolios based on quarterly 
information—information that changes quarterly and influences quarterly returns—should be regenerated each 
quarter. Chapter 13, ''The Information Horizon," will treat this topic in detail.


---


### Page 325


Page 320
we can weight each asset in our buy and sell list by how far its book-to-price ratio lies above or 
below the average.
• Procedure 4. With straight alphas, we can rank the assets according to alpha, then group the assets 
into quintiles (or deciles or quartiles or halves) and equal- (or value-) weight within each group. 
This is an elaboration of procedure 2.
For alphas linearly related to book-to-price ratios, this is a straightforward extension of procedure 3.
• Procedure 5. With any numerical score, we can build a factor portfolio that bets on the prediction 
and does not make a market bet. The factor portfolio consists of a long portfolio and a short 
portfolio. The long and short portfolios have equal value and equal beta, but the long portfolio will 
have a unit bet on the prediction, relative to the short portfolio. Given these constraints, the long 
portfolio will track the short portfolio as closely as possible.
For book-to-price data, we can build long and short portfolios with equal value and beta, with the 
long portfolio exhibiting a book-to-price ratio one standard deviation above that of the short 
portfolio, and designed so that the long portfolio will track the short portfolio as closely as possible.
• Procedure 6. With any numerical score, we can build a factor portfolio, consisting of a long and a 
short portfolio, designed so that the long and short portfolios are matched on a set of prespecified 
control variables. For example, we could make sure the long and short portfolios match on industry, 
sector, or small-capitalization stock exposures. This is a more elaborate form of procedure 5, where 
we controlled only for beta (as a measure of exposure to market risk). Using the book-to-price data, 
this is an extension of procedure 5.
The general idea should be clear. We are trying to establish some sort of relative performance. In 
each case, we will produce two or more portfolios. In the first, third, fifth and sixth procedures, we 
will have a long and a short portfolio. The long bets on the information; the short bets against it. In 
procedure 2, we have a portfolio for each score, and in procedure 4, we have a portfolio for each 
quintile.
Procedures 5 and 6 are more elaborate and "quantitative" than the first four procedures. They require 
more sophisticated technology, which we describe in detail in the technical appendix. However, the 
basic inputs—the information being analyzed—


---


### Page 326


Page 321
needn't be based on a quantitative strategy. Numerical scores derived by any method will work.
While procedures 5 and 6 are more elaborate, they also isolate the information contained in the data 
more precisely. These procedures build portfolios based solely on new information in the data, 
controlling for other important factors in the market.
Because they set up a controlled experiment, we recommend procedure 5 or procedure 6 as the best 
approach for analyzing the information contained in any numerical scores.
To be explicit about step 1, let's apply some of these procedures in two separate examples based on 
book-to-price ratios from January 1988 through December 1992.
For Example A, we will build portfolios according to procedure 2. Every month we will rank assets 
in the S&P 500 by book-to-price ratio, and then divide them into quintiles, defined so that each 
quintile has equal capitalization. We will turn these quintiles into portfolios by capitalizationweighting the assets in each quintile.
For Example B, we will build portfolios according to procedure 5. Every month we will build two 
portfolios, a long portfolio and a short portfolio. The two portfolios will have equal value and beta. 
The long portfolio will exhibit a book-to-price ratio one standard deviation above that of the short 
portfolio. And given these constraints, the long portfolio will track the short portfolio as closely as 
possible. What can these examples tell us about the investment information contained in book-toprice ratios?
Step 2: 
Performance Evaluation
We have turned the data into two or more portfolios. Now we must evaluate the performance of 
those portfolios.2 The general topic of performance analysis is a complicated one, and we will 
discuss it in detail in Chap. 17. Here we will simply present several approaches and summary 
statistics, including the information ratio and information coefficient.
2This step, performance analysis, is very sensitive to errors in asset prices. A mistake in the price one month 
can appear (mistakenly) to be an opportunity. If the data error is fixed in the following month, it will appear as 
if the pricing error corrected itself over the month: an opportunity realized.


---


### Page 327


Page 322
The simplest form of performance analysis is just to calculate the cumulative returns on the 
portfolios and the benchmark, and plot them. Some summary statistics, like the means and standard 
deviations of the returns, can augment this analysis.
Figure 12.1 illustrates this basic analysis for Example A. It shows the cumulative active return on 
each of the five quintile portfolios. These results are interesting. From January 1988 through the 
beginning of 1989, the portfolios perform approximately in ranked order. The highest-book-toprice-quintile portfolio has the highest cumulative return, and the lowest-book-to-price-quintile 
portfolio has almost the lowest cumulative return. However, the situation changed dramatically in 
1989 through 1990. Book-to-price ratios are standard "value" measures, and value stocks 
underperformed growth stocks in this period. And, over the entire five-year analysis period, the 
lowest-book-to-price-quintile portfolio has the highest cumulative return, with the highest-quintile 
portfolio in a distant second place. Still, we constructed the quintile portfolios based only on bookto-price ratios, without controlling for other factors. The quintiles may contain incidental bets that 
muddy the analysis.
Figure 12.2 shows the cumulative returns for the long, short, and net (long minus short) portfolios 
for Example B. It tells a slightly different story from Fig. 12.1. Here too the long portfolio, which 
bets on book-to-price, is the best performer over the early period, but the short portfolio, which bets 
against book-to-price, catches up by 1990. However, unlike the bottom-quintile portfolio from 
Example A, the short portfolio is not ultimately the best performer.
The net portfolio has a forecast beta of zero, and we can see that its returns appear uncorrelated with 
the market. The net bet on book-to-price works well until early 1989, and then disappears through 
1990 and 1991. It begins to work again in 1992. Comparing Figs. 12.1 and 12.2, different 
approaches for constructing portfolios from the same basic information lead to different observed 
performance and different estimates of information content.
t Statistics, Information Ratios, and Information Coefficients
So far, we have discussed only the simplest form of performance analysis: looking at the returns. 
More sophisticated analyses go


---


### Page 328


Page 
Figure 12.1 
Book-to-price quintile analysis.


---


### Page 329


Figure 12.2 
Factor portfolio analysis.


---


### Page 330


Page 325
beyond this to investigate statistical significance, value added, and skill, as measured by t statistics, 
information ratios, and information coefficients. All are related.
We start with regression analysis on the portfolio returns, regressing the excess portfolio returns 
against the excess benchmark returns, to separate the portfolio return into two components, one 
benchmark-related and the other non-benchmark-related:
This regression will estimate the portfolio's alpha and beta, and will evaluate, via the t statistic, 
whether the alpha is significantly different from zero.
The t statistic for the portfolio's alpha is
simply the ratio of the estimated alpha to the standard error of the estimate. This statistic measures 
whether the alpha differs significantly from zero. Assuming that alphas are normally distributed, if 
the t statistic exceeds 2, then the probability that simple luck generated these returns is less than 5 
percent.
Applying regression analysis to Example A, we find the results shown in Table 12.1. This analysis 
corroborates the visual results from Fig. 12.1. Only the highest- and lowest-quintile portfolios 
outperformed the S&P 500, and only they exhibit positive alphas. Unfortunately, none of the alphas 
are significant at the 95 percent confidence level, according to the t statistics. The analysis of beta
TABLE 12.1
Quintile
Alpha
t Alpha
Beta
t Beta
Highest
0.03%
0.14
1.02
16.05
High
–0.06%
–0.05
0.92
28.14
Mid
–0.14%
–0.97
0.92
24.76
Low
–0.15%
–1.10
1.04
28.86
Lowest
0.31%
1.15
1.12
16.35


---


### Page 331


Page 326
TABLE 12.2
Portfolio
Alpha
t Alpha
Beta
t Beta
Long
–0.02%
–0.10
1.08
18.43
Short
–0.11%
–0.76
1.08
29.94
Net
0.08%
0.59
0.00
0.04
shows that the quintiles differed significantly in their exposure to the market.
Applying regression analysis to Example B, we find the results shown in Table 12.2. This analysis is
consistent with Fig. 12.2.* The alphas for both long and short portfolios are negative, with the net 
portfolio exhibiting zero beta and net positive alpha. None of the alphas are significant at the 95 
percent confidence level.
So far, this analysis has focused only on t statistics. What about information ratios? As we have 
discussed in previous chapters, the information ratio is the best single statistic for capturing the 
potential for value added from active management. In Examples A and B, we observe the 
information ratios shown in Table 12.3.
TABLE 12.3
Portfolio
Information Ratio
Example A
Highest quintile
0.06
High quintile
–0.21
Mid quintile
–0.45
Low quintile
–0.51
Lowest quintile
0.53
Example B
Long portfolio
–0.05
Short portfolio
–0.35
Net portfolio
0.27
*Note that Fig. 12.2 contains cumulative excess returns for the Long, Short, and Net portfolios, but cumulative 
total returns for the S&P 500. Cumulative excess returns for the S&P 500 would look more consistent with the 
estimated alphas and betas in Table 12.2.


---


### Page 332


Page 327
The highest information ratio appears for the lowest-quintile portfolio. The next best information 
ratio appears for the net portfolio, which explicitly hedges out any market bets.
The t statistic and the information ratio are closely related. The t statistic is the ratio of alpha to its 
standard error. The information ratio is the ratio of annual alpha to its annual risk. If we observe 
returns over a period of T years, the information ratio is approximately the t statistic divided by the 
square root of the number of years of observation:
This relationship becomes more exact as the number of observations increases.
Do not let this close mathematical relationship obscure the fundamental distinction between the two 
ratios. The t statistic measures the statistical significance of the return; the information ratio captures 
the risk-reward trade-off of the strategy and the manager's value added. An information ratio of 0.5 
observed over 5 years may be statistically more significant than an information ratio of 0.5 observed 
over 1 year, but their value added will be equal.3 The distinction between the t statistic and the 
information ratio arises because we define value added based on risk over a particular horizon, in 
this case 1 year.
The third statistic of interest is the information coefficient. This correlation between forecast and 
realized alphas is a critical component in determining the information ratio, according to the 
fundamental law of active management, and is a critical input for refining alphas and combining 
signals, as described in Chaps. 10 and 11.
In the context of information analysis, the information coefficient is the correlation between our data 
and realized alphas. If the data item is all noise and no signal, the information coefficient is
3In fact, the standard error of the information ratio is (approximately) inversely related to the number of years 
over which we observe the returns:
For more details, see Chap. 17.


---


### Page 333


Page 328
0. If the data item is all signal and no noise, the information coefficient is 1. If there is a perverse 
relationship between the data item and the subsequent alpha, the information coefficient can be 
negative. The information coefficient must lie between +1 and –1.
Going back to our example, the information coefficient of the book-to-price signals over the period 
January 1988 through December 1992 is 0.01.
As we saw in Chap. 6, the information coefficient is related to the information ratio by the 
fundamental law of active management:
where BR measures the breadth of the information, the number of independent bets per year which 
the information will allow. In our example, given an information ratio of 0.27 and an information 
coefficient of 0.01, we can back out that the book-to-price information allows a little over 700 
independent bets per year. Since the information covers 500 assets 12 times per year, it generates 
6000 information items per year. Evidently not all are independent. As a practical matter, the 
parameter BR is more difficult to measure than either the information ratio or the information 
coefficient.
Advanced Topics in Performance Analysis
The subject of performance analysis is quite broad, and we will cover it in detail in Chap. 17. Still, it 
is worth briefly mentioning some advanced topics that pertain to analyzing information.
The first topic concerns portfolio turnover. Our two-step process has been to turn information into 
portfolios and then analyze the performance of those portfolios. Since we have the portfolios, we 
can also investigate their turnover. In fact, given transactions costs, turnover will directly affect 
performance. Turnover becomes important as we move from information analysis to backtesting and 
development of investable strategies.
Other topics concern more detailed levels of analysis that our approach allows. For instance, when 
we build long and short portfolios to bet for and against the information, we can also observe 
whether our information better predicts upside or downside alphas.


---


### Page 334


Page 329
Beyond upside and downside information, we can also investigate whether the data contain 
information pertaining to up markets or down markets. How well do the portfolios perform in 
periods when the market is rising and in periods when the market is falling?
Finally, some advanced topics involve the connection between performance analysis and the step of 
turning information into portfolios. We can investigate the importance of controlling for other 
variables: industries, size, etc. We can construct portfolios with different controls, and analyze the 
performance in each case.
Event Studies
So far, our analysis of information has assumed that our information arrives regularly—e.g., every 
month for every asset in our investment universe. This facilitates building monthly portfolios and 
then observing their performance. Some information doesn't arrive in neat cross-sectional packages. 
Some information-laden events occur at different times for different assets. We need a methodology 
for analyzing these sources of information: the event study.
Where cross-sectional information analysis looks at all the information arriving at a date, event 
studies look at information arriving with a type of event. Only our imagination and the existence of 
relevant data will limit possible event studies. Examples of events we could analyze include
• An earnings announcement
• A new CEO
• A change in dividend
• A stock split
Three types of variables play a role in event studies: a description of the event, asset returns after the 
event, and conditioning variables from before the event. Often, the description of the event is a 0/1 
variable: The event happened or it didn't. This is the case, for example, if a company hires a new 
CEO. Other events warrant a more complicated description. For example, studies of earnings 
announcements use the ''earnings surprise" as the relevant variable. This is the announced earnings 
less consensus forecasts, divided by the dispersion of analysts' forecasts or some other measure of


---


### Page 335


Page 330
the uncertainty in earnings. As a second example, we could use the change in yield to describe a 
dividend change event.
Next, we need the asset's return after the event. This requires special care, because event studies 
analyze events at different times. They must avoid confounding calendar time with the time 
measured relative to the event, by extracting the distortions that arise because the events occurred at 
separate calendar times. For example, stock ABC increased dividends from $1.65 to $1.70 on 
August 6, 1999, and stock XYZ reduced dividends from $0.95 to $0.80 on September 5, 1996. In 
both cases, we want to look at the performance of the stock in the month, quarter, and year 
subsequent to the event. But the market after September 5, 1996, might have differed radically from 
the market after August 6, 1999. Hence, event studies typically use asset residual returns after the 
event.4
Finally, we may wish to use additional conditioning variables characterizing the firm at the time of 
the event. Starting with the above list of example events, here are some possible characterizations:
• An earnings announcement 
-Surprise in the previous quarter
• A new CEO 
-From the inside or outside 
-Predecessor's fate: retired, fired or departed?
• A change in dividend
-Company leverage
• A stock split 
-Percent of institutional ownership 
-Has there been a change in leadership?
How to Do an Event Study
In the generic case, we start with n = 1, 2, . . . , N events; residual returns cumulated from period 1 
to period j following each event, θn(1,,j); the residual risk estimate over the period, ωn(1,,j); and 
condi4For even more control over market conditions, we could use asset-specific returns (net of the market and other 
common factors).


---


### Page 336


Page 331
tioning variables Xnk, where k = 1, 2, . . . , K indexes the different conditioning variables for each 
event n.
Once we have compiled and organized all this information, the event study takes the form of a 
regression:
Once we have implemented the event study as a regression, we can apply the usual statistical 
analysis. We obviously care about the significance of the explanatory variables.
We will also be interested in how the coefficients change with distance from the event, even 
separating the future returns into segments. If we are counting trading days, we could look at 
performance by week: θn(1,5), θn(6,10), etc. To analyze performance in, e.g., the second week, run 
the regression
Note that in these event study regressions, the dependent variable (the left-hand side of the equation) 
has ex ante mean 0 and standard deviation 1, and the in-sample estimate of the IC of the signal is 
 from the regression.
From Event Study to Alpha
Given the analysis above and an event that just occurred, the forecast alpha over the next j periods is
If the event occurred j1 periods earlier, the forecast alpha is
Equations (12.7) and (12.8) are consistent with the volatility · IC · score rule of thumb. The first 
term, ωn(1,,j), is the volatility. The


---


### Page 337


Page 332
fitted part of the regression, 
, will be of the order of IC · score, since we made 
the dependent variable have ex ante mean 0 and standard deviation 1.
Relationship to Cross-Sectional Studies
The results from an event study do not translate directly into an ex ante information ratio, as crosssectional results do. We could, of course, calculate both an ex ante and an ex post information ratio 
using the alphas described above.
But we can also use a simple model to derive some insight into the relationship between our event 
study results and information ratios. Three factors are important to this relationship: the rate at 
which events occur, the ability to forecast future returns, and the decay rate of that forecasting 
ability.
Our simple model will first assume that the number of trading days between events has a geometric 
distribution. The probability that an event will occur in any given day is p. The probability that the 
next event occurs in j days is p · (1 – p)j – 1. This just accounts for the probability that the event 
doesn't occur for j – 1 days, and then occurs 1 day. The expected number of days between events is 
1/p.
The model will then account for forecasting ability with the information coefficient. The 
information coefficient for the first day after the event is IC(1).
Finally, the model will account for the decay in forecasting ability as we move away from the event. 
This is the information horizon, which we treat in depth in Chap. 13. For now, we will simply 
assume that the information coefficient decays exponentially over time. For j days after the event,
Sometimes we have a better sense of a half-life than of a decay constant. We can easily convert 
from one to the other. The half-life in days is simply log{0.5} /log{γ}.
With this information, and assuming J trading days per year


---


### Page 338


Page 333
and an investment universe of N roughly similar assets, the model estimates the annual information 
coefficient,
and the information ratio,
The technical appendix provides the details. Note that combining Eq. (12.11) with the fundamental 
law of active management implies a measure of the breadth of the event information. Effectively, 
we are receiving fresh information on N* assets, where
Equation (12.12) captures the essence of the process. If p is large (close to 1), events happen every 
day and N* ≈ N. But what if p is small? If our event is the appointment of a new CEO, which might 
occur every 7 years or so, then p = 0.00056. For such rare events, the effective breadth is
Assuming an annual information coefficient of 0.04 and 1000 assets, Fig. 12.3 shows how the 
information ratio depends on the number of events per year and the half-life of the information.
The Pitfalls of Information Analysis
Information analysis is a powerful tool. If we can use information analysis to evaluate the 
investment value of a set of raw data, we can also use it to refine those data. If this is done correctly, 
we are separating wheat from chaff. If it is done incorrectly, we are data mining.
Data mining can fool an analyst into believing that information exists when it does not. Data mining 
can lead managers to bet on


---


### Page 339


Page 334
Figure 12.3 
Sensitivity of information ratio to signal half-life.


---


### Page 340


Page 335
information that doesn't exist. Data mining is the bane of information analysis.
Data Mining is Easy
Why is it that so many ideas look great in backtests and disappoint upon implementation? 
Backtesters always have 95 percent confidence in their results, so why are investors disappointed far 
more than 5 percent of the time? It turns out to be surprisingly easy to search through historical data 
and find patterns that don't really exist.
To understand why data mining is easy, we must first understand the statistics of coincidence. Let's 
begin with some noninvestment examples. Then we will move on to investment research.
Several years ago, Evelyn Adams won the New Jersey state lottery twice in 4 months. Newspapers 
put the odds of that happening at 17 trillion to 1, an incredibly improbable event. A few months 
later, two Harvard statisticians, Percy Diaconis and Frederick Mosteller, showed that a double win 
in the lottery is not a particularly improbable event. They estimated the odds at 30 to 1. What 
explains the enormous discrepancy in these two probabilities?
It turns out that the odds of Evelyn Adams's winning the lottery twice are in fact 17 trillion to 1. But 
that result is presumably of interest only to her immediate family. The odds of someone, 
somewhere, winning two lotteries—given the millions of people entering lotteries every day—are 
only 30 to 1. If it wasn't Evelyn Adams, it could have been someone else.
Coincidences appear improbable only when viewed from a narrow perspective. When viewed from 
the correct (broad) perspective, coincidences are no longer so improbable. Let's consider another 
noninvestment example: Norman Bloom, arguably the world's greatest data miner.
Norman Bloom died a few years ago in the midst of his quest to prove the existence of God through 
baseball statistics and the Dow Jones average. He argued that "BOTH INSTRUMENTS are in effect 
GREAT LABORATORY EXPERIMENTS wherein GREAT AMOUNTS OF RECORDED DATA 
ARE COLLECTED, AND PUBLISHED" (capitalization Bloom's). As but one example of his 
thousands of analyses of baseball, he argued that the fact that George


---

