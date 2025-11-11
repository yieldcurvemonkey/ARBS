# Grinold-Kahn Active Portfolio Management

## Pages 341-360


### Page 341


Page 336
Brett, the Kansas City third baseman, hit his third home run in the third game of the playoffs, to tie 
the score 3–3, could not be a coincidence—it must prove the existence of God. In the investment 
arena, he argued that the Dow's 13 crossings of the 1000 line in 1976 mirrored the 13 colonies 
which united in 1776—which also could not be a coincidence. (He pointed out, too, that the 12th 
crossing occurred on his birthday, deftly combining message and messenger.) He never took into 
account the enormous volume of data—in fact, the entire New York Public Library's worth—he 
searched through to find these coincidences. His focus was narrow, not broad.
With Bloom's passing, the title of world's greatest living data miner has been left open. Recently, 
however, Michael Drosnin, author of The Bible Code, seems to have filled it.5
The importance of perspective for understanding the statistics of coincidence was perhaps best 
summarized by, of all people, Marcel Proust—who often showed keen mathematical intuition:
The number of pawns on the human chessboard being less than the number of combinations that they are 
capable of forming, in a theater from which all the people we know and might have expected to find are absent, 
there turns up one whom we never imagined that we should see again and who appears so opportunely that the 
coincidence seems to us providential, although, no doubt, some other coincidence would have occurred in its 
stead had we not been in that place but in some other, where other desires would have been born and another 
old acquaintance forthcoming to help us satisfy them.6
Investment Research
Investment research involves exactly the same statistics and the same issues of perspective. The 
typical investment data mining example involves t statistics gathered from backtesting strategies.
5For a review of The Bible Code, see Kahn (1998).
6The Guermantes Way, Cities of the Plain, vol. 2 of Remembrance of Things Past C.K. Scott Moncrieff and 
Terance Kilmartin, translators, (New York: Vintage Books, 1982), p. 178.


---


### Page 342


Page 337
The narrow perspective says, "After 19 false starts, this 20th investment strategy finally works. It 
has a t statistic of 2."
But the broad perspective on this situation is quite different. In fact, given 20 informationless 
strategies, the probability of finding at least one with a t statistic of 2 is 64 percent. The narrow 
perspective substantially inflates our confidence in the results. When the situation is viewed from 
the proper perspective, confidence in the results decreases accordingly.7
Fortunately, four guidelines can help keep information analysis from turning into data mining: 
intuition, restraint, sensibleness, and out-of-sample testing.
First, intuition must guide the search for information before the backtest begins. Intuition should not 
be driven strictly by data. Ideally, it should arise from a general understanding of the forces 
governing investment returns and the economy as a whole. The book-to-price strategy satisfies the 
criterion of intuition. The information tells us which stocks provide book value cheaply. Of course, 
intuition is a necessary but not a sufficient criterion for finding valuable information. Some 
information is already widely known by market participants and fairly priced in the market. On the 
other hand, nonintuitive information that appears valuable in this analysis usually fails upon 
implementation. Sunspots, skirt lengths, and Super Bowl victories can appear valuable over 
carefully chosen historical periods, but are completely nonintuitive. Data mining can easily find 
such accidental correlations. They do not translate into successful implementations.
Second, restraint should govern the backtesting process. Statistical analysis shows that, given 
enough trials of valueless information, one incarnation (usually the last one analyzed) will look 
good. After 20 tests of worthless information, 1 should look significant at the 95 percent confidence 
level. In principle, researchers should map out possible information variations before the testing 
begins. There are many possible variations of the book-to-price information. We can use current 
price or price contemporaneous with the book value accounting information. We can try stock 
sectors, to find where the relationship works best. With each variation, the
7For a detailed analysis of these pitfalls, see Kahn (1990).


---


### Page 343


Page 338
information drifts further from intuition, pushed along by the particular historical data.
Third, performance should be sensible. The information that deserves most scrutiny is that which 
appears to perform too well. Only about 10 percent of observed realized information ratios lie above 
1. Carefully and skeptically examine information ratios above 2 that arise in information analysis. 
The book-to-price data in our example are straightforward, publicly available information. In the 
fairly efficient U.S. market, an information ratio above 2 for such information should not be 
believed. Information ratios far above 2 signal mistakes in the analysis, not phenomenal insight.
Fourth, out-of-sample testing can serve as a quantitative check on data mining. Valueless 
information honed to perfection on one set of historical data should reveal its true nature when 
tested on a second set of historical data. Book-to-price ratios tuned using 1980 to 1985 monthly 
returns must also outperform in 1986. Book-to-price ratios tuned using January, March, May, July, 
September, and November monthly returns must also outperform in February, April, June, August, 
October, and December. Out-of-sample testing helps ensure that the information not only describes 
historical returns, but predicts future returns.
Summary
This chapter has presented a thorough discussion of information analysis. Information analysis 
proceeds in two steps. First, information is transformed into investment portfolios. Second, the 
performance of those portfolios is analyzed. To quantify that performance—and the value of the 
information being analyzed—the information ratio most succinctly measures the potential 
investment value added contained in the information.
Problems
1. What problems can arise in using scores instead of alphas in information analysis? Where in the 
analysis would these problems show up?
2. What do you conclude from the information analysis presented concerning book-to-price ratios in 
the United States?


---


### Page 344


Page 339
3. Why might we see misleading results if we looked only at the relative performance of top- and 
bottom-quintile portfolios instead of looking at factor portfolio performance?
4. The probability of observing a |t statistic| > 2, using random data, is only 5 percent. Hence our 
confidence in the estimate is 95 percent. Show that the probability of observing at least one |t 
statistic| > 2 with 20 regressions on independent sets of random data is 64 percent.
5. Show that the standard error of the information ratio is approximately 
, where T is the 
number of years of observation. Assume that you can measure the standard deviation of returns with 
perfect accuracy, so that all the error is in the estimate of the mean. Remember that the standard 
error of an estimated mean is 
, where N is the number of observations.
6. You wish to analyze the value of corporate insider stock transactions. Should you analyze these 
using the standard cross-sectional methodology or an event study? If you use an event study, what 
conditioning variables will you consider?
7. Haugen and Baker (1996) have proposed an APT model in which expected factor returns are 
simply based on past 12-month moving averages. Applying this idea to the BARRA U.S. Equity 
model from January 1974 through March 1996 leads to an information ratio of 1.79. Applying this 
idea only to the risk indices in the model (using consensus expected returns for industries) leads to 
an information ratio of 1.26. What information ratio would you expect to find from applying this 
model to industries only? If the full application exhibits an information coefficient of 0.05, what is 
the implied breadth of the strategy?
8. A current get-rich-quick Web site guarantees that over the next 3 months, at least three stocks 
mentioned on the site will exhibit annualized returns of at least 300 percent. Assuming that all stock 
returns are independent, normally distributed, and with expected annual returns


---


### Page 345


Page 340
of 12 percent and risk of 35 percent, (a) what is the probability that over one quarter at least 3 stocks 
out of 500 exhibit annualized returns of at least 300%? (b) How many stocks must the Web site 
include for this probability to be 50 percent? (c) Identify at least two real-world deviations from the 
above assumptions, and discuss how they would affect the calculated probabilities.
Notes
The science of information analysis began in the 1970s with work by Treynor and Black (1973), 
Hodges and Brealey (1973), Ambachtsheer (1974), Rosenberg (1976), and Ambachtsheer and 
Farrell (1979). These authors all investigated the role of active management in investing: Its ability 
to add value and measures for determining this. Treynor and Black and Hodges and Brealey were 
the first to examine the role of security analysis and active management within the context of the 
capital asset pricing model. They investigated what is required if active management is to 
outperform the market, and identified the importance of correlations between return forecasts and 
outcomes among these requirements. Ambachtsheer, alone and with Farrell, provided further 
insights into the active management process and turning information into investments. He also 
coined the term ''information coefficient," or IC, to describe this correlation between forecasts of 
residual returns (alphas) and subsequent realizations. Rosenberg investigated the active management 
process and measures of its performance as part of his analysis of the optimal amount of active 
management for institutional investors.
References
Ambachtsheer, Keith P. "Profit Potential in an 'Almost Efficient' Market." Journal of Portfolio 
Management, vol. 1, no. 1, 1974, pp. 84–87.
———. "Where Are the Customers' Alphas?" Journal of Portfolio Management, vol. 4, no. 1, 1977, 
pp. 52–56.
Ambachtsheer, Keith P., and James L. Farrell Jr. "Can Active Management Add Value?" Financial 
Analysts Journal, vol. 35, no. 6, 1979, pp. 39–47.
Drosnin, Michael. The Bible Code (New York: Simon & Schuster, 1997).
Frankfurter, George M., and Elton G. McGoun. "The Event Study: Is It Either? "Journal of 
Investing, vol. 4, no. 2, 1995, pp. 8–16.


---


### Page 346


Page 341
Grinold, Richard C. "The Fundamental Law of Active Management." Journal of Portfolio 
Management, vol. 15, no. 3, 1989, pp. 30–37.
Grinold, Richard C., and Ronald N. Kahn. "Information Analysis." Journal of Portfolio 
Management, vol. 18, no. 3, 1992, pp. 14–21.
Haugen, Robert A., and Nardin L. Baker. "Commonality in the Determinants of Expected Stock 
Returns." Journal of Financial Economics, vol. 41, no. 3, 1996, pp. 401–439.
Hodges, S. D., and R. A. Brealey. "Portfolio Selection in a Dynamic and Uncertain World." 
Financial Analysts Journal, vol. 29, no. 2, 1973, pp. 50–65.
Kahn, Ronald N. "What Practitioners Need to Know about Backtesting." Financial Analysts 
Journal, vol. 46, no. 4, 1990, pp. 17–20.
———. "Three Classic Errors in Statistics from Baseball to Investment Research."Financial 
Analysts Journal, vol. 53, no. 5, 1997, pp. 6–8.
———. "Book Review: The Bible Code." Horizon: The BARRA Newsletter, Winter 1998.
Kritzman, Mark P. "What Practitioners Need to Know about Event Studies. "Financial Analysts 
Journal, vol. 50, no. 6, 1994, pp. 17–20.
Proust, Marcel. The Guermantes Way, Cities of the Plain, vol. 2 of Remembrance of Things Past, 
translated by C.K. Scott Moncrieff and Terence Kilmartin (New York: Vintage Books, 1982), p. 
178.
Rosenberg, Barr. "Security Appraisal and Unsystematic Risk in Institutional Investment. 
"Proceedings of the Seminar on the Analysis of Security Prices (Chicago: University of Chicago 
Press, 1976), pp. 171–237.
Salinger, Michael. "Standard Errors in Event Studies." Journal of Financial and Quantitative 
Analysis, vol. 27, no. 1, 1992, pp. 39–53.
Treynor, Jack, and Fischer Black. "How to Use Security Analysis to Improve Portfolio Selection." 
Journal of Business, vol. 46, no. 1, 1973, pp. 68–86.
Technical Appendix
This technical appendix will discuss mathematically the more controlled quantitative approaches to 
constructing portfolios to efficiently bet on a particular information item a, while controlling for 
risk. It will also detail the model used to connect event studies to cross-sectional studies.
Information-Efficient Portfolios
Basically, this is just an optimization problem. We want to choose the minimum-risk portfolio ha 
subject to a set of constraints:


---


### Page 348


Page 342
If we ignore the constraints, z, in Eq. (12A.3), then the solution to this problem is the characteristic 
portfolio for a. Constraints we could add include
• hT · β = 0 (zero beta)
• hT · e = 0 (zero net investment)
• hT · X = 0 (zero exposure to risk model factors)
Long and Short Portfolios
The portfolio ha will include long and short positions:
where haL and haS are defined such that their holdings are all non-negative:
If we add the net zero investment constraint, then the long and short portfolios will exactly balance.
We see from Eq. (12A.4) that Var{ha} is identical to Var{haL – haS}, and so minimizing the variance 
of ha subject to constraints is the same as minimizing the tracking of haL versus haS subject to the 
same constraints.
We can separately monitor the performance of haL and haS to observe whether a contains upside 
and/or downside information, respectively.
Relation to Regression
This factor portfolio approach is related to the regression approach to estimating factor returns. 
Given excess returns r, information a, and exposures X, we can estimate factor returns:
where Y is an N × (J + 1) matrix whose first J columns contain X


---


### Page 349


Page 343
and whose last column contains a. Estimating b with weights W (stored as a diagonal N × N matrix) 
leads to
the estimates which minimize ∈T · W · ∈. These estimates are linear combinations of the asset 
returns; hence, we can rewrite this as
is the (J + 1) × N matrix of factor portfolio holdings. Note that
so each factor portfolio has unit exposure to its particular factor and zero exposure to all other 
factors.
The portfolio hJ + 1, the last column of the matrix H, has return ba, the estimated return in Eq. (12A.9) 
corresponding to information a. Where ha is the minimum-risk portfolio with hT · a = 1 and subject 
to various constraints, hj + 1 is the portfolio with minimum ∈T · W · ∈ with hT · a = 1 and subject to 
various constraints.
Event Studies and Cross-Sectional Studies
The main text stated results [Eqs. (12.10) and (12.11)] connecting information coefficients from 
event studies, along with event rates and information horizons, to cross-sectional information ratios. 
We derive those results here.
First we derive the annual information coefficient IC(J), given the one-day information coefficient 
IC(1). (We assume J trading days in the year.) The one-day information coefficient states that the 
correlation between our signal and the one-day residual return is IC(1):
With no loss of generality, we can assume that our signal has standard deviation 1. Hence, the 
covariance of the signal with the one-day residual return is


---


### Page 350


Page 344
We have assumed that our information coefficient decays with decay constant γ. Hence, the 
covariance of our signal with the residual return on day J is
To derive the annual information coefficient, we first need the covariance of our signal with the 
annual residual return, which is the sum of the J daily residual returns:
We can sum this geometric series to find
The annual information coefficient is simply the correlation associated with this covariance. We 
need only divide by the annual residual volatility:
This is Eq. (12.10) from the main text.
Next we need to derive the result for the information ratio. The annualized alpha, assuming that the 
event has just occured, is
But if the information arrived j days ago, the alpha is
The information ratio for a given set of alphas is simply 
 [See, for example, Eq. 
(5A.6).] We will calculate the square of the information ratio by taking the expectation of the square 
of this result over the distribution of possible signals z. We will assume uncorrelated residual 
returns. We must account for


---


### Page 351


Page 345
the fact that, cross-sectionally, different assets will have different event delays. So we must calculate
We can simplify this somewhat, to
We must make further assumptions to estimate the expectation in Eq. (12A.21). First, we assume the 
same expectation for each asset n:
Second, we assume that we can separate the two terms in the expectation. So effectively, for any 
value of j, we will take the expectation of z2, since the score shouldn't depend on the value of j:
We must calculate one last expectation. Here we know the distribution of event arrival times. Hence
We can once again apply results concerning the summation of geometric series. We find
Combining Eqs. (12A.21) through (12A.23) and (12A.25) leads to the final result:
This is Eq. (12.11) from the main text.


---


### Page 352


Page 347
Chapter 13— 
The Information Horizon
Introduction
There is a time dimension to information. Information arrives at different rates and is valuable over 
longer or shorter periods. For most signals, the arrival rate is fixed. The shelf life (or information 
horizon) is the main focus of interest. Is this a fast signal that fades in 3 or 4 days, or is it a slow 
signal that retains its value over the next year? The latest is not necessarily the greatest. In some 
cases, a mix of old and new information is more valuable than just the latest information.
Chapters 10 and 11 developed a methodology for processing information and described how to 
optimally combine sources of information. Chapter 12 presented an approach to analyzing the 
information content of signals. Chapter 13 will rely on both methodologies to tackle the special 
topic of the information horizon.
We will begin by applying information analysis at the "macro" level: looking at returns to multiasset 
strategies. These may be based on one or several sources of information, possibly but not 
necessarily optimally combined. The goal is to determine the information horizon, and whether the 
strategy is effectively using the information in a temporal sense, i.e., whether any time average or 
time difference of the information could improve performance. This analysis has the advantage of 
requiring only the returns, not a detailed knowledge of the inner workings of the strategy.
At the "micro" level, we will apply the methodology of Chap. 10 to the special case of optimal 
mixing of old and new signals.


---


### Page 353


Page 348
The in-depth analysis of simple cases provides insight into the phenomena we observe in more 
complicated and realistic cases. These micro results echo the macro results.
Insights in this chapter include the following:
• The information horizon should be defined as the half-life of the information's forecasting ability.
• A strategy's horizon is an intrinsic property. Time averages or time differences can change 
performance, but they will not change the horizon.
• Lagged signals or scores and past returns can improve investment performance.
Macroanalysis of the Information Horizon
A natural definition of the information horizon, or shelf life, of a strategy is the decay rate of the 
information ratio. What does it cost us if a procrastinating investment committee forces a 1-month 
delay in implementing the recommendations? We use the May 1 portfolio in June, the June 1 
portfolio in July, and so forth. What if there is a 2-month delay? Or a 6-month delay? In general, 
delays will lead to a reduction in the strategy's potential as measured by its information ratio. A 
reasonable measure of the decay rate is the half-life, the time it takes for the information ratio to 
drop to one-half of its value when implemented with immediacy. In practice, this means that we 
approximate the decay in the information ratio as an exponential where a certain fraction of the 
information is lost in each period.
The half-life is a remarkably robust characteristic of the strategy. Attempts to improve the signal 
using its temporal dimensions may improve performance, but they will have little or no effect on the 
strategy's half-life!
In Fig. 13.1, we see a gradual decay in the strategy's realized information ratio as we delay 
implementation for more and more months. The half-life is 1.2 years.
The ability to add value is proportional to the square of the information ratio. Thus the half-life for 
adding value is one-half that of the information ratio. In the case illustrated in Fig. 13.1, we


---


### Page 354


Page 349
Figure 13.1
have a half-life of 0.6 year for value added as opposed to 1.2 years for the information ratio. This is 
a long-horizon strategy. We can delay implementation of the recommended trades for more than 6 
months and still realize 50 percent of the value added.
Figure 13.2 shows a strategy with a very short half-life.
The interplay of information and time is as subtle as the interplay of food and time. "Fresh is best" is 
a good rule but not universally accurate: Vegetables and baked goods are best when fresh, fruit 
needs to ripen; wine and cheese improve with age, and sherry is best as a blend of several vintages. 
Is the information sherry, vegetables, or wine?
We can see if there is any value in the old information with a thought experiment. Suppose there are 
two investment managers, Manager Now and Manager Later. Manager Now employs an excellent 
strategy, with an information ratio of 1.5. Manager Later's research consists of sifting through 
Manager Now's trash to find a listing of last month's portfolio. Thus Manager Later follows the 
same strategy as Manager Now, but with the portfolios 1 month behind. Manager Later has an 
information ratio of 1.20. Both managers have an active risk level of 4 percent.
Should we hire Manager Now, Manager Later, or a mix of Now and Later? This decision hinges on 
the correlation of the active


---


### Page 355


Page 350
Figure 13.2
returns. If the correlation between Manager Now's and Manager Later's active returns is less than 
0.80 = 1.2/1.5, the decay rate of the information ratio, then we can add value by hiring both Now 
and Later. If the correlation is more than 0.80, we want to hedge Manager Now's performance by 
going short manager Later. Figure 13.3 shows the mix of Now and Later that we would want as a 
function of the correlation between their active returns. At a correlation of 0.7 between the active 
returns of Managers Now and Later, the best mix is 18.5 percent to Manager Later and 81.5 percent 
to Manager Now. If we presume a correlation of 0.85 in the active returns of Managers Now and 
Later, then the optimal mix is a 118.5 percent long position with Manager Now offset by an 18.5 
percent short position with Manager Later.
We will show in the technical appendix that given a decay rate of γ and a correlation of ρ, the 
optimal weight on Now is


---


### Page 356


Page 351
Figure 13.3
Figure 13.4 shows the change in the overall information ratio that results from combining Managers 
Now and Later. We see that there is no gain if the active return correlation is 0.8 and that there are 
modest gains if the active return correlation strays above or below that key level. The algebraic 
result here is
We will show more generally in the technical appendix that the optimal combination of past 
portfolios mixes them so that the correlation between the time t and the time t – 1 portfolios equals 
the decay rate of the information ratio. For example, if the l-period lagged information ratio is IRl = 
γl · IR0 and the portfolios at each time t are denoted h(t), h(t – 1), . . . , h(t – l), . . . , then the 
combination with the best information ratio will be


---


### Page 357


Page 352
Figure 13.4
The correlation of active returns for the holdings h*(t) and h*(t – 1) will be γ. Note that h* is a 
weighted average of innovations, with h(t – l) – ρ · h(t – l – 1) capturing the new information in h(t 
– l).1
This application of information analysis can quickly help a manager determine if she or he is 
leaving any information on the table, since a real manager can easily combine managers Now and 
Later merely by combining the most recently recommended portfolio with the portfolio 
recommended in the previous period. For example, if the active return correlation is 0.5, then a mix 
of 33 percent of the lagged portfolio and 67 percent of the current portfolio would produce an 
information ratio of 1.59. Combining the portfolios is combining the outputs of the investment 
management process. If there is a process where it is possible to link inputs with outputs, then we 
could also proceed by mixing the lagged inputs and the current inputs in the same 33 percent and 67 
percent ratios.
1If you regress θ(t – l) on θ(t – l – 1), the coefficient on θ(t – l – 1) should be ρ, since ω(t – l) = ω(t – l – 1). 
Hence Eq. (13.4) effectively represents the residuals from such a regression.


---


### Page 358


Page 353
This optimal mix of Now and Later will improve performance although it will not change the 
horizon. If we make an optimal mixture of the old portfolios, the information ratio will increase, but 
the horizon (half-life) of the resulting strategy will be exactly the same as the horizon of the original 
strategy.
Microanalysis of the Information Horizon
We will now apply our information processing methodology to analyzing the information horizon at 
the micro level. We will focus on the case of one asset, or, more precisely, one time series.2 This 
asset has return r(0,Δt) over a period between time 0 and time Δt. For convenience, we assume that 
the expected return is 0. The volatility of the return is σ times the square root of Δt. We assume, in 
general, that the asset returns are uncorrelated.
Information arrives periodically, in bundles that we'll call scores, at time intervals of length Δt—
perhaps an hour, a day, a week, a month, a quarter, or a year. These scores have mean 0 and 
standard deviation 1, as described in Chap. 10.
The special information contained in the scores may allow us to predict the return r(0,Δt). This 
prediction, or alpha, depends on the arrival rate and shelf life of that information.
In the simplest case, ''just-in-time" signals, the signal is of value in forecasting return during the 
interval until the next one arrives, but it is of no value in forecasting the return in subsequent 
periods. For example, a signal that arrives on April 30 helps in forecasting the May return but is of 
no use for June, July, etc. The next signal, which arrives May 31, helps with the June return.
Let IC(Δt) be the correlation of the score with the return over the period {0,Δt}. Given a score s(0), 
the standardized signal at time 0, the conditional expectation of r(0,Δt) is
2The point is that our results apply to a single asset, or a factor return, or a portfolio long stocks and short 
bonds.


---


### Page 359


Page 354
The information coefficient IC(Δt) is a measure of forecast accuracy over the period. The first goal 
is to determine the value of the information. Here we will use the information ratio. We can use the 
fundamental law of active management to determine the information ratio as a function of the 
forecast interval:
where we measure the breadth BR as simply the inverse of the period, i.e., 1/Δt. For example, a 
signal that arrives once per month has a breadth of 12. We can see immediately that there is a tradeoff between the arrival rate, captured by Δt, and the accuracy, captured by IC(Δt).
Two-Period Shelf Life
In the simplest case described above, we had "just-in-time" information. The interarrival time Δt 
matched the shelf life Δt. Now we'll consider cases where the interarrival time is shorter than the 
shelf life.3 In particular, we receive scores each period, and a score's shelf life is two periods long. 
The April 30 score predicts the returns for May and June. The May 31 score predicts the returns for 
June and July. We can measure the IC of the score on a period-by-period basis. The term IC1 
measures the correlation between the score and the first period's return, and the term IC2 measures 
the correlation between the score and the second period's return. The information coefficient IC1&2 is 
the correlation between the score and the two-period return. The relation between these information 
coefficients is
3It is possible, although less interesting, to have the interarrival time exceed the shelf life. An example is 
earnings surprise for international companies; the information arrives once a year, and its value has generally 
expired long before the next year's earnings announcement.


---


### Page 360


Page 355
For example, a correlation of IC1 = 0.15 for the first period's return and IC2 = 0.075 for the second 
period's return would imply a correlation of 
 for the two periods. 
We are blessed with a longer shelf life. It remains to see how we handle this blessing.
We want to make a one-period forecast based on the most recent score, s(0), and the previous score, 
s(–Δt). In the monthly example, we combine the April 30 score and the May 31 score to produce a 
forecast for June. The critical variable in producing a best forecast will be the correlation ρ between 
s(0) and s(–Δt).
In Chap. 10, we derived how to optimally combine two separate signals. That result applies here as 
well, with the second signal being simply the lag of the first signal:
The modified information coefficients 
correct for the correlation between the signals:
The IC of the combined signal is
Figure 13.5 shows how the modified information coefficients change as the correlation between the 
signals varies, assuming IC1 = 0.15 and IC2 = 0.075.
The combined forecast dominates using either the first or the second score in isolation. Figure 13.6 
demonstrates this for our example.


---

