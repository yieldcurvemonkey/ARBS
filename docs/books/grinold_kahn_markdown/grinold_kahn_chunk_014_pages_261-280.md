# Grinold-Kahn Active Portfolio Management

## Pages 261-280


### Page 261


Page 255
Fama, Eugene F., and Kenneth R. French. "Taxes, Financing Decisions, and Firm Value." Journal 
of Finance, vol. 53, no. 3, 1998, pp. 819–843.
Fouse, William. "Risk and Liquidity: The Keys to Stock Price Behavior." Financial Analysts 
Journal, vol. 32, no. 3, 1976, pp. 35–45.
———. "Risk and Liquidity Revisited." Financial Analysts Journal, vol. 33, no. 1, 1977, pp. 40–
45.
Gordon, Myron J. The Investment, Financing, and Valuation of the Corporation (Homewood, Ill.: 
Richard D. Irwin, 1962).
Gordon, Myron J., and E. Shapiro. "Capital Equipment Analysis: The Required Rate of Profit." 
Management Science, vol. 3, October 1956, pp. 102–110.
Grant, James L. "Foundations of EVA for Investment Managers." Journal of Portfolio 
Management, vol. 23, no. 1, 1996, pp. 41–48.
Jacobs, Bruce I., and Kenneth N. Levy. "Disentangling Equity Return Opportunities: New Insights 
and Investment Opportunities." Financial Analysts Journal, vol. 44, no. 3, 1988, pp. 18–44.
———. "Forecasting the Size Effect." Financial Analysts Journal, vol 45, no. 3, 1989, pp. 38–54.
Lev, Baruch, and S. Ramu Thiagarajan. "Fundamental Information Analysis."Journal of Accounting 
Research, vol. 31, no. 2, 1993, pp. 190–215.
Modigliani, Franco, and Merton H. Miller. "Dividend Policy, Growth, and the Valuation of Shares." 
Journal of Business, vol 34, no. 4, 1961, pp. 411–433.
Ohlson, James A. "Accounting Earnings, Book Value, and Dividends: The Theory of the Clean 
Surplus Equation (Part I)." Columbia University working paper, January 1989.
Ou, Jane, and Stephen Penman. "Financial Statement Analysis and the Prediction of Stock Returns." 
Journal of Accounting and Economics, vol. 11, no. 4, November 1989, pp. 295–329.
Rosenberg, Barr, Kenneth Reid, and Ronald Lanstein. "Persuasive Evidence of Market 
Inefficiency." Journal of Portfolio Management, vol. 11, no. 3, 1985, pp. 9–17.
Rozeff, Michael S. "The Three-Phase Dividend Discount Model and the ROPE Model." Journal of 
Portfolio Management, vol. 16, no. 2, 1989, pp. 36–42.
Sharpe, William F., and Gordon J. Alexander. Investments (Englewood Cliffs, N.J.: Prentice-Hall, 
1990).
Wilcox, Jarrod W. "The P/B-ROE Valuation Model." Financial Analysts Journal, vol. 40, no. 1, 
1984, pp. 58–66.
Williams, John Burr. The Theory of Investment Value (Amsterdam: North-Holland Publishing 
Company, 1964).
Technical Appendix
This technical appendix will discuss how to handle nonlinear models and fractiles in the (linear) 
returns-based framework. The idea will be to capture the nonlinearities in the exposures to linearly


---


### Page 263


Page 256
estimated factors. We can even make these exposures benchmark-neutral.
Let's start with an example. Suppose you think that the relationship between earnings yield and 
return is not linear. Here is one approach to testing that hypothesis. Divide the assets into three 
categories, high earnings yield, low earnings yield, and average earnings yield,13 and consider two 
earnings yield variables, high yield and average yield. So the model is
The high-earnings-yield assets have Xn,high = 1 and Xn,ave = 0. The average-earnings-yield assets have 
Xn,high = 0 and Xn,ave = 1. We can determine the exposures of the low-yield assets by imposing 
benchmark neutrality. Assuming that each group has equal capitalization, the condition θB = 0 leads 
to
So for the low-yield assets, we must have Xn,high = – 1 and Xn,ave = – 1.
Once we estimate the factor returns, we can determine whether there exist any nonlinearities. For 
example, one sign of a nonlinear effect would be the return to the high-yield assets relative to the 
average assets differing significantly from the return of the low-yield assets relative to the average 
assets.
We can clearly extend this approach to quartiles, quintiles, or deciles. In fact, this returns-based 
fractile analysis has the advantage of allowing for controls. We can make sure that each fractile 
portfolio is sector- and/or benchmark-neutral, and perhaps neutral on some other dimension that we 
believe may be confounding the effect.
Other methods for analyzing nonlinear effects also exist. Let's start with an attribute Xn,1 that is 
benchmark-neutral: 
 We wish to analyze nonlinearities while still ensuring
13The choice of three categories is arbitrary, and mainly done for ease of explanation. If we considered four 
categories, this would be quartile analysis. As in quartile analysis, we also have a choice in how to form the 
group: equal number in each group or equal capitalization in each group.


---


### Page 264


Page 257
benchmark neutrality. A simple approach is to include a new variable:
The squared exposure has the disadvantage of placing undue emphasis on outliers. Other 
alternatives would include using the absolute value of Xn,1, the square root of the absolute value of 
Xn,1, or the Max{0, Xn,1}, in each case benchmark-neutralized as in Eq. (9A.3). Each of these would 
reduce the nonlinear effect for the more extreme positive and negative values of Xn,1.
Exercise
1. You forecast an alpha of 2 percent for stocks that have E/P above the benchmark average and 
IBES growth above the benchmark average. On average, what must your alpha forecasts be for 
stocks that do not satisfy these two criteria? If you assume an alpha of zero for stocks which have 
either above-average E/P or above-average IBES growth, but not both, what is your average alpha 
for stocks with E/P and IBES growth both below average?
Applications Exercise
1. Use appropriate software (e.g. BARRA's Aegis and Alphabuilder products) to determine the 
current dividend-to-price ratio, dividend growth, and beta (with respect to the CAPMMI) for GE 
and Coke. Using these data, a risk-free rate of 6 percent, and expected benchmark excess return of 6 
percent, what are the prices implied by the constant-growth DDM? What is the dividend discount 
rate? Estimate alphas for GE and Coke using both methods described in the section "Dividend 
Discount Models and Returns."


---


### Page 265


Page 259
PART THREE— 
INFORMATION PROCESSING


---


### Page 266


Page 261
Chapter 10— 
Forecasting Basics
Introduction
We have completed our discussion of expected returns and valuation. We now move on to the third 
major section of the book: information processing. We now assume some source of alpha 
information. In this section, we tackle a critical problem: how to efficiently analyze and process that 
information. We will spend two chapters looking forward: describing how to turn information into 
alphas. We will then look backward, with a chapter on information analysis. The last chapter in this 
section will look forward and backward, covering the information horizon.
Active management is forecasting. The consensus forecasts of expected returns, efficiently 
implemented, lead to the market or benchmark portfolio. Active managers earn their title by 
investing in portfolios that differ from their benchmark. As long as they claim to be efficiently 
investing based on their information, they are at least implicitly forecasting expected returns.
Forecasting is too large a topic to deal with adequately in this book. Instead, we will give the reader 
some insight into how forecasting techniques can refine raw information and turn it into alphas and 
forecasts of exceptional return. Earnings estimates, measures of price momentum, and brokers' buy 
recommendations are pieces of raw information. This chapter and the next will discuss how to turn 
such raw information into forecasts of exceptional return.
These two chapters on forecasting and the following chapters on information analysis and the 
information horizon are all closely


---


### Page 267


Page 262
linked. In this chapter, we will try to deal with terminology and gather some insights. In the next 
chapter, "Advanced Forecasting," we will apply those insights to some standard real-world issues 
faced by most active institutional investment managers. In Chap. 12, "Information Analysis," we 
will show how we can evaluate the ability of a variable or a combination of variables to predict 
returns. In Chap. 13, "The Information Horizon,'' we will focus specifically on the critical time 
component of information, using the tools developed in the previous chapters.
The main insights gained in this chapter are the following:
• Active management is forecasting.
• The unconditional or naïve forecast is the consensus expected return. The conditional or informed 
forecast is dependent on the information source. Historical averages make poor unconditional 
forecasts.
• A basic forecasting formula connects the naïve and informed forecasts, and handles single and 
multiple sources of information.
• The refined forecast has the form volatility · IC · score.
• Forecasts of return have negligible effect on forecasts of risk.
Naïve, Raw, and Refined Forecasts
Here we will introduce several types of forecasts, and establish a link between our forecasts and 
returns via the basic forecasting formula. The naïve forecast is the consensus expected return. It is 
the informationless (or uninformed) forecast. The naïve forecast leads to the benchmark holdings.
The raw forecast contains the active manager's information in raw form: an earnings estimate, a buy 
or sell recommendation, etc. The raw forecast can come in a variety of units and scales, and is not 
directly a forecast of exceptional return.
The basic forecasting formula transforms raw forecasts into refined forecasts. The outputs of the 
formula are forecasts in the form (and units) of exceptional returns, adjusted for the information


---


### Page 268


Page 263
content of the raw forecast. The formula (which we derive in the appendix) is1
where r = excess return vector (N assets)
g = raw forecast vector (K forecasts)
E{r} = naïve (consensus) forecast
E{g} = expected forecast
E{r | g} = informed expected return: the expected return 
conditional on g
At its core, Eq. (10.1) relates forecasts that differ from their expected levels to forecasts of returns 
that differ from their expected levels. In fact, we will define the refined forecast as the change in 
expected return due to observing g:
This is the exceptional return referred to in previous chapters. It can include both residual return 
forecasts and benchmark timing. And, given a benchmark portfolio B, the naïve (consensus) forecast 
is
where we define betas relative to the benchmark and µB is the consensus expected excess return of 
the benchmark. Historical average returns are a poor alternative to these consensus expected returns 
for the active manager. As discussed in Chap. 2, historical average returns have very large sample 
errors, and are inappropriate for new or changing stocks. More importantly, Eq. (10.3) provides 
consensus returns leading to the benchmark.
An equivalent way to think about the basic forecasting formula is to apply it directly to the residual 
returns θ. Then, instead of Eq. (10.3), we have the equivalent result
1We are using the notation for conditional expectation E{r|g} somewhat loosely.


---


### Page 269


Page 264
the consensus expected residual returns are 0, and
In the next sections we will explore the meaning and use of the basic forecasting formula.
Refining Raw Information: 
One Asset and One Forecast
Let's start with the simplest case—one asset and one forecast—and look at it in two ways. First, we 
will use the pedagogical tool of the binary model, which we introduced in Chap. 6. Here we will see 
exactly the processes generating returns and forecasts. Second, we will use regression analysis, 
where we will not see the underlying processes. Fortunately, these two approaches to the same 
problem lead us to roughly the same conclusion. This mutual confirmation will reinforce our trust in 
the formula for refining information. As a side benefit, we will extract a forecasting rule of thumb 
that will prove useful in countless situations.
In the binary model, we presume that we understand the processes generating returns and forecasts. 
Suppose we are forecasting return over one quarter; the expected excess return over the quarter is E
{r} = 1.5 percent, and the quarterly volatility is 9 percent. That is equivalent to an annual expected 
excess return of 6 percent and an annual volatility of 18 percent.
We can write the return we are forecasting as
where 1.5 is the certain expected return, and the 81 random elements θi capture the uncertain 
component of the return. The θi are independent and equally likely to achieve +1 or – 1; thus, each 
θi has expectation 0 and variance 1. The variance of r is 81, corresponding to the desired 9 percent 
per quarter volatility. We can think of the variables θ1 through θ81 as unit bundles of uncertainty. The 
random component in the return is the sum of these 81 simple components. We cannot observe the 
values of the individual θi; we can only observe the sum, r.
We observe the return at the end of an investment period, but we must forecast at the beginning of 
the period. In our example,


---


### Page 270


Page 265
the forecast, g, has an expected value of 2 percent and a standard deviation of 4 percent. We can 
model the forecast in a manner similar to the return:
The variables θ1 through θ3 are elements of the return r. The forecaster actually knows something 
about part of the return, and knows it at the beginning of the period. The components η1 through η13 
are additional bundles of uncertainty in the forecast. They have nothing to do with the return. The 
forecast is a combination of useful and useless information. The ηj are independent of each other 
and independent of the θi. Each ηj can achieve +1 or – 1 with equal probability. We can think of the 
θi as bits of signal and the ηj as bits of noise. The forecaster gets 16 unit bundles of information; 3 
are signal, 13 are noise. Alas, the forecaster sees only the sum and cannot sort out the signal from 
the noise.
The covariance of g and r is simply the number of elements of return that they have in common. In 
this case, Cov{r,g} = 3 (θ1 through θ3). The correlation between g and r is the skill level or IC:
We obtain the best linear estimate of the return conditional on knowledge of g by using Eq. (10.1). 
Focusing now on the refined forecast, for the case of a single asset and a single forecast, we can 
express this as
In this particular case, we have
The Forecasting Rule of Thumb
In the case of one asset and one forecast, we refine the forecast by
• Standardizing the raw forecast by subtracting the expected forecast and dividing by the standard 
deviation


---


### Page 271


Page 266
of the forecasts. We call that standardized version of the raw forecast a score or z score.
• Scaling the score to account for the skill level of the forecaster (the IC) and the volatility of the 
return we are attempting to forecast.
Equation (10.9) leads to the forecasting rule of thumb:
With this rule of thumb, we can gain insight into the forecasting process and derive refined forecasts 
in unstructured situations. In our example, we have a (quarterly) volatility of 9 percent and an IC of 
0.0833. The refined forecast will be 0.75 = 0.0833 · 9 times the score (the standardized raw 
forecast). If the scores are normally distributed, then our refined forecast will be between –0.75 and 
+0.75 percent two quarters out of three. The refined forecast will be outside the range {–1.50 
percent, +1.50 percent} one quarter in twenty.
The forecasting rule of thumb [Eq. (10.11)] also shows the correct behavior in the limiting case of 
no forecasting skill. If the IC = 0, then the refined forecasts are all zero, as they should be in this 
case.
We will find the same rule of thumb if we use regression analysis instead of the binary model. In the 
binary model, we presumed that we knew the structure generating the returns and the forecasts. In 
reality, we are in the dark and must make inferences from available data, or guess based on 
experience and intuition. Given the data, we will refine the raw forecasts using regression analysis.
Consider a time series of forecasts g(t) and subsequent returns r(t) over a sample of T periods. Let 
mr and mg be the sample averages for r and g, and let Var{r}, Var{g}, and Cov{r,g} be the sample 
variances and covariances. We will use the time series regression
as our refining tool. The least-squares estimates of c1 and c0 are


---


### Page 272


Page 267
Defining the score as
and using the regression results and the definition of refined forecast, we find
This is identical to the result in the binary model, except that we are now using the sample history to 
estimate the IC and the volatility ofr and to standardize the raw forecast.2
So both the binary model and the regression analysis lead to the same forecasting rule of thumb: The 
refined forecast of exceptional return has the form volatility · IC · score. For a given signal, the 
volatility and IC components will be constant, and the score will distinguish this forecast for the 
asset from previous forecasts for the asset.
Forecasts have the form volatility · IC · score.
Intuition
This refinement process—converting raw forecasts into refined forecasts—controls for three factors: 
expectations, skill, and volatility. The score calculation controls for expectations by the subtraction 
of the unconditional expected raw forecast. We can illustrate the intuition here with an example: 
earnings surprise. An earnings surprise model forecasts alphas based on how reported earnings 
compare to prior expectations. When earnings just match expectations, the stock price doesn't move. 
More generally, we expect exceptional price movement only when the raw information doesn't 
match consensus expectations.
2As we have noted earlier, our estimates of the means of the returns mr generally contain a great deal of sample 
error. The sample errors affect the parameter c0 =mr – c1 · mg. If we have a strong prior reason to believe that 
the unconditional expected return is equal to m, then we can replace the estimate of the coefficient c0 by 
. A Bayesian analysis would start with a prior that the mean is m ± d and then mix in the sample 
evidence.


---


### Page 273


Page 268
The refinement process controls for skill through the IC term. If IC = 0, the raw forecast contains no 
useful information, and we set the refined forecast of exceptional return to zero.
Finally, the refinement process controls for volatility. Note first that in the volatility · IC · score 
construction, the IC and score terms are dimensionless. The volatility term provides the dimensions 
of return. Also note that given a skill level and two stocks with the same score, the higher-volatility 
stock receives the higher alpha. Perhaps a utility stock and an Internet stock both appear on a 
broker's buy list. We expect both stocks to rise. The Internet stock (presumably the more volatile) 
should rise more.
As we will discuss in the next chapter, the forecasting rule of thumb can also hold for a crosssectional forecast of exceptional returns, so the score is what distinguishes one stock from another. 
The average and standard deviation of the time series of scores for a particular stock over time 
should be close to 0 and 1, respectively. The average and standard deviation of the scores over many 
stocks at one point in time should also be close to 0 and 1, respectively.
Table 10.1 illustrates the rule of thumb for the Major Market Index as of December 1992. We have 
used an IC level of 0.09 and used a random number generator to sample the scores from a standard 
normal distribution.
Refining Forecasts: 
One Asset and Two Forecasts
Let's go back to the binary model and assume we are forecasting the same excess return r with the 
forecast g from before and a new raw forecast g':
Forecasts g and g' share one element of signal (θ3) and four elements of noise (η10, η11, η12, and η13). 
Forecast g' has 25 units of uncertainty; thus Var{g'} = 25. Forecast g' contains four elements of 
signal (θ3, θ4, θ5, θ6); thus Cov {r,g'} = 4. The correlation of r and g' (IC,g) is Corr{r,g'} = 4/(9 · 5) = 
0.089. Forecast g' has five bits of information in common with forecast g (θ3, η10, η11, η12, and η13), 
and thus Cov{g,g'} = 5.


---


### Page 274


Page 269
TABLE 10.1
MMI Stock
Residual Volatility
Score
Alpha
American Express
23.26%
0.35
0.73%
AT&T
15.89%
0.71
1.01%
Chevron
20.44%
–0.25
–0.45%
Coca-Cola
18.92%
–0.48
–0.82%
Disney
19.17%
0.36
0.62%
Dow Chemical
16.93%
–0.77
–1.17%
DuPont
17.29%
1.58
2.47%
Exxon
21.13%
0.00
–0.01%
General Electric
14.42%
0.77
1.01%
General Motors
23.46%
1.98
4.17%
IBM
30.32%
–0.67
–1.84%
International Paper
19.83%
–0.03
–0.05%
Johnson & Johnson
18.97%
–1.77
–3.02%
Kodak
19.20%
–0.06
–0.10%
McDonalds
20.54%
–0.45
–0.82%
Merck
20.43%
0.74
1.36%
3M
13.41%
0.35
0.42%
Procter & Gamble
16.29%
–2.32
–3.40%
Philip Morris
20.17%
–0.89
–1.62%
Sears
22.33%
0.85
1.70%
We now have enough information to use Eq. (10.1). If we were using only g' in this example, we 
would find
but combining g and g', we find
with an IC for the refined combined forecast of 0.1090.
In the case of one asset and two forecasts, we can actually calculate an explicit general result (and 
rule of thumb):


---


### Page 275


The revised skill levels 
 take into account the correlation


---


### Page 276


Page 270
between the forecasts. If ρg,g' is the correlation between forecasts g and g', then:
If the forecasts are uncorrelated, the combined forecast reduces to the sum of the refined forecasts 
for g and g'. If the forecasts are completely correlated (ρg,g' = 1), then Eqs. (10.21) and (10.22) break 
down (remember that ICg = ICg' in that case). The second forecast adds nothing.
We could equivalently repackage the scores instead of the ICs. The idea would be to create 
orthogonal linear combinations of the original scores. In the two-signal example here,
They would exhibit revised ICs
Since the repackaged scores are uncorrelated, combining them reduces to simple addition.
We can also show that in the two-signal case the IC of the combined forecast is
If the forecasts are uncorrelated, the square of the combined IC is the sum of the squares of the two 
component ICs.


---


### Page 277


Page 271
We can repeat the two-forecast, one-asset example with regression analysis. The time series 
regression is now
and our refined forecast will be
In our example, with a sufficiently long history (T is very large), we would estimate c1 close to 
0.1467 and c2 close to 0.1307.
The case of one asset and more than two signals involves more complicated algebra (see the 
appendix for details). But we can provide some suggestion of what the refinement process does in 
those cases. Imagine, for example, three signals, each with the same IC. What if the first two signals 
are highly correlated, but are uncorrelated with the third signal? If all three signals were 
uncorrelated, we would equal-weight them (simply add the separately refined forecasts). But the 
refinement process will account for the correlations by halving the ICs of the two correlated signals. 
Effectively, we will count the uncorrelated signal equally with the sum of the two correlated signals. 
The general mathematical result captures this intuitive idea, while accounting for all possible 
intercorrelations.
Refining Forecasts: 
Multiple Assets and Multiple Forecasts
With multiple assets and multiple forecasts, it is more difficult to apply the basic forecast rule. This 
is because we lack sufficient data and insight to uncover the required structure. With two forecastsg 
and g' on each of 500 stocks, the covariance matrix of g and g' is 1000 by 1000, and the covariance 
of the returns and g and g' is a 500 by 1000 matrix. We will treat this topic in the next chapter, 
although this chapter includes some simple examples.
Examples
Now we will consider several practical and less structured examples that rely heavily on our 
volatility · IC · score rule of thumb for producing a refined forecast of exceptional return. We are 
assum-


---


### Page 278


Page 272
ing that estimates of residual volatility are available. In the absence of sufficient historical 
information to decide on the IC of the raw forecasts, use these vague but tested guidelines: A good 
forecaster has IC = 0.05, a great forecaster has IC = 0.10, and a world-class forecaster has IC = 0.15. 
An IC higher than 0.20 usually signals a faulty backtest or imminent investigation for insider 
dealing.
A Tip
Consider that most ad hoc of all situations, the stock tip.3 Let's say the stock in question has typical 
residual volatility of 20 percent. To change the subjective stock tip into a forecast of residual return, 
we need the IC and the score. For the IC, look to the track record of the source: If the source is 
great, set IC = 0.1; if the source is good, IC = 0.05; and if the source is a waste of time, then IC = 0. 
For the score, we can give a run-of-the-mill tip (very positive) a 1.0 and a very, very positive tip a 
2.0. Table 10.2 shows the spectrum of possibilities and the ability to transform some unstructured 
qualitative information into a more useful quantitative form.
Up/Down Forecast
In a major investment firm, the most notorious and accurate forecaster was a fellow named Charlie. 
For years, as portfolio managers filed into work, Charlie greeted them with the enthusiastic words: 
''Market's going up today!" Charlie was right two-thirds of the
TABLE 10.2
IC
Very Positive (Score = 1)
Very, Very Positive 
(Score = 2)
Great 0.10
2.0%
4.0%
Good 0.05
1.0%
2.0%
No information 0.00
0.0%
0.0%
3Andrew Rudd suggested this example.


---


### Page 279


Page 273
time. Of course, Charlie's forecasts weren't very valuable, since the market should on average go up, 
and two-thirds is about the historical average. The value in the forecast comes from separating up 
days from down days.
Suppose the expected annual market return is 6 percent with annual risk of 18 percent, 
corresponding to an expected monthly return of 0.50 percent with a monthly standard deviation of 
5.20 percent. We can represent monthly up/down forecasts as Raw(t) = +1 for up and Raw(t) = –1 
for down. If the raw forecasts are consistent with the returns, i.e., two-thirds are +1, then the mean 
and standard deviation of the raw scores will be 1/3 and 0.9428, respectively. The standardized 
scores are 0.707 and –1.414. Given an IC (correlating the forecasts with the returns), we find that 
Refined = 0.50 + (5.20) · IC · (0.707) for an up forecast and Refined = 0.50 – (5.20) · IC · (1.414) 
for a down forecast. With moderate skill (IC = 0.075), the forecasts are 0.78 percent for an up 
market and –0.05 percent for a down market. The asymmetry follows because, in the absence of any 
information, we expect an up market with a 0.50 percent return.
Buy and Sell Recommendations
A more structured example involves a buy and sell list. In this case, we give a score of +1.0 to the 
buys and a score of –1.0 to the sells. If we apply this to the Major Market Index stocks, with a 
random choice of buy and sell and an IC of 0.09, we see the alphas shown in Table 10.3. The rule 
gives higher alphas to the more volatile stocks. If we ignored the rule and gave an alpha of +1 
percent to the buy stocks and an alpha of –1 percent to the sell stocks, then an optimizer would 
select those buy stocks with the lowest residual risk.
Fractiles
Some managers group their assets into deciles or quintiles or quartiles. This is a refinement of the 
buy/sell idea, which partitions the assets into two groups. If assets have a raw score of 1 through 10 
depending on their decile membership, we can turn these into standardized scores by subtracting the 
average (perhaps value-


---


### Page 280


Page 274
TABLE 10.3
MMI Stock
Residual 
Volatility
View
Score
Alpha
American Express
23.26%
Sell
–1
–2.09%
AT&T
15.89%
Buy
1
1.43%
Chevron
20.44%
Buy
1
1.84%
Coca-Cola
18.92%
Sell
–1
–1.70%
Disney
19.17%
Sell
–1
–1.73%
Dow Chemical
16.93%
Buy
1
1.52%
DuPont
17.92%
Buy
1
1.56%
Exxon
21.13%
Sell
–1
–1.90%
General Electric
14.42%
Sell
–1
–1.30%
General Motors
23.46%
Buy
1
2.11%
IBM
30.32%
Buy
1
2.73%
International Paper
19.83%
Sell
–1
–1.78%
Johnson & Johnson
18.97%
Buy
1
1.71%
Kodak
19.20%
Buy
1
1.73%
McDonalds
20.54%
Buy
1
1.85%
Merck
20.43%
Sell
–1
–1.84%
3M
13.41%
Sell
–1
–1.21%
Procter & Gamble
16.29%
Sell
–1
–1.47%
Philip Morris
20.17%
Buy
1
1.82%
Sears
22.33%
Sell
–1
–2.01%
weighted) raw score and dividing by the standard deviation of the raw scores.
Rankings
A ranking is similar to a fractile grouping except that there is only one asset in each group. We can 
look at the rankings, say 1 through 762, as raw scores. First, check to see if the asset ranked 1 is the 
best or the worst! Then we can, using various degrees of sophistication, transform those rankings 
into standardized scores.
The Forecast Horizon: 
New and Old Forecasts
Suppose that we generate a raw forecast each month and that these forecasts are useful in predicting 
returns for the next 2 months. In


---

