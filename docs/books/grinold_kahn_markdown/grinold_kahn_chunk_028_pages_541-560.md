# Grinold-Kahn Active Portfolio Management

## Pages 541-560


### Page 541


Page 535
3. Suppose a U.K. investor observes a BHP return of 3.5 percent, but the pound depreciates relative 
to the dollar by 3.5 percent over the period (e.g., from $1.50 to $1.4475). Does a U.S. investor 
observe a net BHP return of zero? Why or why not?
4. Evidently (from examining Table 18.3), the sample data have produced a Q(GER) for Germany 
that has a high correlation with currencies and a Q(JPN) for Japan that has a low correlation with 
currencies. How would you explain the lack of symmetry between the Japanese relationship with 
other currencies and the German relationship with other currencies?
References
Ambachtscheer, Keith P. ''Pension Fund Asset Allocation: In Defense of a 60/40 Equity/Debt Asset 
Mix." Financial Analysts Journal, vol. 43, no. 5, 1987, pp. 14–24.
Black, Fischer. "Capital Market Equilibrium with Restricted Borrowing." Journal of Business, vol. 
45, 1972, pp. 444–455.
———. "Universal Hedging: Optimizing Currency Risk and Reward in International Equity 
Portfolios." Financial Analysts Journal, vol. 45, no. 4, 1989, pp. 16–22.
———. "Equilibrium Exchange Rate Hedging." Journal of Finance, vol. 65, no. 3, 1990, pp. 899–
907.
Black, Fischer, and Robert Litterman. "Asset Allocation: Combining Investor Views with Market 
Equilibrium." Goldman Sachs Fixed Income Research Publication, September 1990.
———. "Global Asset Allocation with Equities, Bonds, and Currencies." Goldman Sachs Fixed 
Income Research Publication, October 1991.
Emanuelli, Joseph F., and Randal G. Pearson. "Using Earnings Estimates for Global Asset 
Allocation." Financial Analysts Journal, vol. 50, no. 2, 1994, pp. 60–72.
Ferson, Wayne E., and Campbell R. Harvey. "The Risk and Predictability of International Equity 
Returns," Review of Financial Studies, vol. 6, no. 3, 1992, pp. 527–566.
Grinold, Richard C. "Alpha Is Volatility Times IC Times Score." Journal of Portfolio Management, 
vol. 20, no. 4, 1994, pp. 9–16.
———. "Domestic Grapes from Imported Wine." Journal of Portfolio Management, Special Issue 
December 1996, pp. 29–40.
Kahn, Ronald N., Jacques Roulet, and Shahram Tajbakhsh. "Three Steps to Global Asset 
Allocation." Journal of Portfolio Management, vol. 23, no. 1, 1996, pp. 23–32.
Sharpe, William F. "Capital Asset Prices: A Theory of Market Equilibrium under Conditions of 
Risk." Journal of Finance, vol. 19, no. 3, 1964, pp. 425–442.


---


### Page 542


Page 536
———. "Integrated Asset Allocation." Financial Analysts Journal, vol. 43, no. 5, 1987, pp. 25–32.
Singer, Brian D., Kevin Terhaar, and John Zerolis. "Maintaining Consistent Global Asset Views 
(with a Little Help from Euclid)." Financial Analysts Journal, vol. 54, no. 1, 1998, pp. 63–71.
Solnik, Bruno. "The Performance of International Asset Allocation Strategies Using Conditioning 
Information." Journal of Empirical Finance, vol. 1, 1993a, pp. 33–55.
Solnik, Bruno. Predictable Time-Varying Components of International Asset Returns. 
(Charlottesville, Va.: Research Foundation of Institute of Chartered Financial Analysts, 1993b).
Technical Appendix
In this appendix, we will derive the link between excess returns from different perspectives [Eq. 
(18.6)], and also the transformation of portfolio Q from the COM perspective to other perspectives.
To derive the result connecting excess returns from different perspectives, we will continue the 
tradition of this chapter and focus on BHP from the U.K. and U.S. perspectives. The generalization 
of the approach is obvious, and by using a specific example, we avoid having to remember which 
subscript or superscript refers to numeraire versus local market, etc. Let's begin this treatment with 
Eq. (18.5) from the main text:
Just to understand the logic of this starting point, imagine taking $1 at time 0 and converting it to 
U.K. pounds. You will have 1/[($/£)(0)] pounds. Invest that amount in BHP from t = 0 to t. You 
then have 1/[($/£)(0)] · RBHP(U.K.|0,t) pounds. Converting back to dollars leads to Eq. (18A.1).
To account for the multiplicative relationship between local returns and currency returns, we will 
use a slightly unusual definition of cumulative excess return:
where R$(U.S.|0,t) is the value at time t of a U.S. money market account starting with $1 at t = 0. We 
can similarly define excess


---


### Page 543


Page 537
returns to BHP from the U.K. perspective, and excess returns to U.K. pounds from the U.S. 
perspective. In fact,
Now we want to look at instantaneous excess returns r:
The calculation of this from Eq. (18A.3) is complicated by the ratio of two stochastic terms. We can 
apply Ito's lemma, to show that, in general, for
Ito's lemma effectively tells us to expand dF in a Taylor series and keep all terms up to second 
order. Applying this to Eq. (18A.3), we find
We will need one more step to derive the result in the main text. In general, for any asset n,
If we set n = U.K. pounds, we can simplify this because the excess return to U.K. pounds from the 
U.K. perspective is zero:


---


### Page 544


Page 538
Substituting this into Eq. (18A.7) leads to
This is Eq. (18.6) in the main text.
Transforming Portfolio Q
We saw in the main text that
We also saw that
Here we are using Q to refer to the efficient portfolio from the COM perspective. We are seeking a 
portfolio we will call QU.S.. If we apply standard (not international) CAPM analysis to this portfolio 
from the U.S. perspective, we will find the same consensus expected excess returns as if we had 
used Q in the full international context.
First, we will use Eq. (18A.8) to convert the necessary covariances from Eqs. (18A.12) and 
(18A.11) to the U.S. perspective:
Substituting Eqs. (18A.12), (18A.14), and (18A.15) into Eq. (18A.11) leads to


---


### Page 545


Page 539
If we define QU.S. such that
Hence, we can define QU.S. as
We can freely add or subtract h$ without influencing the covariances. We have used this property to 
preserve the investment level (e.g., fully invested) of Q. Note that the only adjustment in moving 
from Q to QU.S. involves a shift in currency exposure. We are lowering our exposure to the currency 
basket, i.e., hedging our international currency exposure.


---


### Page 546


Page 541
Chapter 19— 
Benchmark Timing
Introduction
In Chap. 4 we separated active management into benchmark timing and stock selection and 
postponed consideration of benchmark timing until a later chapter. We can postpone it no longer. In 
this chapter we will explore benchmark timing as another avenue for adding value.
The main conclusions of this chapter are as follows:
• Successful benchmark timing is hard. The potential to add value is small, although it rises with the 
number of independent bets per year.
• Exceptional or unanticipated benchmark return is the key to the benchmark timing problem. 
Forecasts of exceptional benchmark return lead to active beta positions.
• We can generate active betas using futures or stocks with betas different from 1. There is a cost—
measured in unavoidable residual risk and transactions costs—associated with relying on stocks for 
benchmark timing.
• Performance measurement schemes exist to evaluate benchmark timing skill.
We'll start with the definitions.
Defining Benchmark Timing
As discussed in Chap. 4, benchmark timing is an active management decision to vary the managed 
portfolio's beta with respect


---


### Page 547


Page 542
to the benchmark. If we believe that the benchmark will do better than usual, then beta is increased. 
If we believe the benchmark will do worse than usual, then beta should be decreased. Notice the 
relative nature of our expectations—better than usual and worse than usual. We will need some 
feeling for what we should expect in the usual circumstances.
In its purest sense, we should think of benchmark timing as choosing the correct mixture of the 
benchmark portfolio and cash. This is a one-dimensional problem, and variations along that 
dimension should not cause any active residual bets in the portfolio; i.e., all the active risk will come 
from the active beta. This type of benchmark timing is akin to buying or selling futures contracts1 on 
the benchmark.
Benchmark timing is not asset allocation. As we saw in Chap. 18, asset allocation focuses on 
aggregate asset classes rather than specific individual stocks, bonds, etc. In the simplest case, the 
aggregates may be domestic equity, domestic bonds and cash. In more complicated cases, the asset 
allocation may include several kinds of equity and bonds as well as international equities and bonds, 
real property, and precious metals. International managers betting on several country indices are 
engaged in global asset allocation, not benchmark timing. The motivation for asset allocation is to 
simplify an extremely complicated problem.
While tactical asset allocation involves 5 to 20 assets, benchmark timing involves only 1. This 
makes adding value through benchmark timing very difficult, as we can see from the fundamental 
law of active management. Remember that the information ratio for benchmark timing arises from a 
combination of forecasting skill, the benchmark timing information coefficient ICBT, and breadth 
BR, the number of independent bets per year:
An independent benchmark timing forecast every quarter leads to a breadth of only 4. Then, 
according to Eq. (19.1), to generate a
1A forward contract is equivalent to being long the benchmark and short cash, i.e., borrowing to buy the 
benchmark. A futures contract is very similar to a forward contract.


---


### Page 548


Page 543
benchmark timing information ratio of 0.5 requires an information coefficient of 0.25—extremely 
high! The fundamental law of active management captures exactly why most institutional managers 
focus on stock selection.
Stock selection strategies can diversify bets cross-sectionally across many stocks. Benchmark 
timing strategies can diversify only serially, through frequent bets per year. The fundamental law 
quantifies this. Significant benchmark timing value added can arise only with multiple bets per year. 
To keep this point clear, this chapter will monitor the forecast frequency: first once per year and 
later multiple times per year.
Futures versus Stocks
Benchmark timing is choosing an active beta. We can implement benchmark timing with futures. 
We can also implement an active beta without modifying the cash/benchmark mix. For example, if 
we think the benchmark will be exceptionally strong this month, then we might overemphasize the 
higher-beta stocks in our portfolio. However, this has three drawbacks. First, we have to take on 
residual risk as a result of emphasizing one group of stocks over another. Second, we must have 
faith that we have identified the betas of the stocks correctly. Even the best forecasts of beta are 
subject to error. There is no error in the pure cash/benchmark trade-off. The beta of cash is exactly 
0, and the beta of the benchmark is exactly 1. Third, the transactions costs involved in trading many 
individual securities are generally much greater than for a forward or futures contract.
We can push the residual risk problem a bit further with the following analysis. Let's build the 
minimum-risk, fully invested portfolio with beta constrained to be βP. Given the beta constraint, the 
portfolio which minimizes total risk will also minimize residual risk. As shown in the technical 
appendix, the optimal portfolio is a weighted combination of the benchmark and portfolio C. Its 
residual variance—the lowest possible residual variance for a fully invested portfolio with specified 
active beta βPA = βP – 1—is


---


### Page 549


Page 544
Assuming a benchmark risk of 18 percent and a portfolio C risk of 12 percent, and remembering 
that the beta of portfolio C is:
an active beta of 0.1 leads to a residual risk of at least 1.6 percent. With a moderate level of residual 
risk aversion (λR = 0.1), this corresponds to a penalty of about 0.25 percent.
This analysis of the benefits of using futures rather than stocks to implement benchmark timing 
strategies has clear implications for situations where the benchmark has no closely associated 
futures contract. In that case, the potential for adding value through benchmark timing is very small.
Value Added
In Chap. 4 we derived an expression for the value added by benchmark timing. The key ingredients 
in this formula are
βPA =
the portfolio's active beta with respect to the 
benchmark. This is the decision variable.
ΔfB =
the forecast of exceptional benchmark return. 
This is the departure, positive or negative, from 
the usual level of benchmark return. If µB is the 
usual annual expected excess return on the 
benchmark and fB is our refined forecast of the 
expected excess return on the benchmark over 
the next year, then ΔfB = fB – µB is the exceptional 
benchmark return in the next year.
σB =
the volatility of the benchmark portfolio.
λBT =
a measure of aversion to the risk of benchmark 
timing.
We will start with the simple case in which we only make one benchmark timing decision per year. 
In Chap. 4 we determined that the value added by benchmark timing is


---


### Page 550


Page 545
TABLE 19.1 
Active Beta
 
Aversion to Timing Risk λBT
Exceptional Forecast ΔfB
High, 0.14
Medium 0.09
Low, 0.06
4.00%
0.05
0.08
0.12
2.00%
0.02
0.04
0.06
0.00%
0.00
0.00
0.00
–2.00%
–0.02
–0.04
–0.06
–4.00%
–0.05
–0.08
–0.12
The optimal level of active beta, 
, is determined by setting the derivative of Eq. (19.4) with 
respect to beta equal to zero. We find
Table 19.1 shows how 
, will vary with changes in the exceptional forecast ΔfB and the aversion 
to benchmark timing risk λBT. Table 19.1 assumes a 17 percent annual volatility for the benchmark.
The value added at the optimal beta 
is
Table 19.2 displays this value added, assuming a benchmark volatility of 17 percent. Given only one 
active decision per year, this corresponds to basis points per year.
We can take this analysis a step further by looking in depth at the forecast deviation ΔfB and the risk 
aversion λBT. In particular, we want to reformulate this analysis to
• Avoid the need to forecast the usual expected excess return on the market µB
• Make it easier to build up a forecast of exceptional return ΔfB
• Avoid having to determine the risk aversion parameter λBT


---


### Page 551


Page 546
TABLE 19.2 
Value Added
 
Aversion to Timing Risk λBT
Exceptional Forecast ΔfB
High, 0.14
Medium 0.09
Low, 0.06
4.00%
9.9
15.4
23.1
2.00%
2.5
3.8
5.8
0.00%
0.0
0.0
0.0
–2.00%
2.5
3.8
5.8
–4.00%
9.9
15.4
23.1
To begin with, we can see from Eq. (19.5) that the difference ΔfB between the forecast fB and the 
usual µB drives the optimal active beta. Hence, we can greatly simplify matters by not worrying 
about either µB or fB and forecasting the exceptional return ΔfB directly. However, we must adjust our 
thinking from an absolute framework (e.g., fB) to a relative framework (e.g., ΔfB).
This view is completely consistent with the approach to forecasting discussed in Chap. 10. Recall 
that the refined forecast of exceptional benchmark return is
where IC = the information coefficient, the correlation between our 
forecasts and subsequent exceptional benchmark returns. 
It's a measure of skill.
S= score, a normalized signal with mean 0 and standard 
deviation equal to 1 over time.
What is an appropriate level of benchmark timing skill? With sufficient data on past forecasts, you 
can calculate the IC directly. Without those data, or if you think that the past is not an accurate guide 
to the future, then reasonable IC estimates are 0.05, 0.1, or 0.15 depending on whether you are good, 
very good, or terrific. This is where humility should enter the game. Benchmark timing skill is rare. 
If you assume that you have this skill that most others lack, you may be misleading yourself. As a 
crude test, consider your ability to forecast whether the benchmark will do better than


---


### Page 552


Page 547
TABLE 19.3 
Scores for Benchmark Timing
View
Probability
Score
Very positive
0.11
1.73
Positive
0.22
0.87
No view
0.33
0.00
Negative
0.22
–0.87
Very negative
0.11
–1.73
average.2 With a correlation of IC = 0.1, you would expect to be correct 55 percent of the time.
Table 19.3 shows one way to translate qualitative views into quantitative scores. The scores in Table 
19.3 have an average of 0 and a standard deviation of 1. The probability column indicates that we 
should be, on average, very positive one time in nine.
Using ΔfB = σB · IC · S, we can calculate the optimal active beta and value added as a function of the 
score:
Table 19.4 displays these relationships, assuming an IC of 0.10, a 17 percent benchmark volatility, 
and a risk aversion of 0.06.
To make the benchmark timing process more transparent, we would like to ignore the risk-aversion 
parameter and find a more direct way to determine aggressiveness. We can do this using κ, defined 
in Eq. (19.8). Assuming that the score is normally distributed, a κ of 0.06 implies that the portfolio's 
beta will lie between 0.94 and 1.06 two-thirds of the time, falling above 1.06 one time in six and 
below 0.94 one time in six. If that seems too aggressive, then decrease κ. This implies an increase in 
risk aversion and/or a decrease in information coefficient, but we can also deal with κ
2This does not mean better than the risk-free rate.


---


### Page 553


Page 548
TABLE 19.4
View
Probability
Score
Forecast
Active 
Beta
Value 
Added
Very positive
0.11
1.73
2.94%
0.09
0.12%
Positive
0.22
0.87
1.47%
0.04
0.03%
No view
0.33
0.00
0.00%
0.00
0.00%
Negative
0.22
–0.87
–1.47%
–0.04
0.03%
Very negative
0.11
–1.73
–2.94%
–0.09
0.12%
directly. Table 19.5 shows how κ depends on risk aversion and information coefficient.
Using κ, we can also examine value added in more detail. Equation (19.9) writes the value added 
conditional on the score S. The unconditional value added then is
using the condition that the scores have mean 0 and standard deviation 1. A very good forecaster, 
with an IC = 0.10, given a benchmark volatility of 17 percent and a κ of 0.05, can produce a not 
very impressive expected value added of 4.2 basis points.3 And
TABLE 19.5 
κ

Aversion to Timing Risk
Skill Level
IC
High, 0.14
Medium, 0.09
Low, 0.06
Good
0.05
0.01
0.02
0.02
Very good
0.10
0.02
0.03
0.05
World class
0.15
0.03
0.05
0.07
3The situation is even worse if the forecaster implements the timing bet using stock selection as opposed to 
futures. The technical appendix will show that even a low aversion to the unavoidable residual risk of that 
approach will shave 2.9 basis points off that 4.2 basis points.


---


### Page 554


Page 549
with only one forecast per year, this is 4.2 basis points per year. However, we shouldn't give up yet. 
The way to add more value with benchmark timing is to make high-quality forecasts more 
frequently.
Forecasting Frequency
The analysis to this point has assumed a 1-year investment horizon. That 1-year horizon is mainly 
responsible for the vanishing contribution of benchmark timing to value added. The strategy's 
information ratio and value added depend on skill and breadth, according to the fundamental law of 
active management, and benchmark timing once per year sets the lower positive bound on breadth 
(1 bet per year). To add more value, we must forecast more frequently.4
Assume that we can make T forecasts per year. Divide the year into T periods, indexed by t = 1, 
2, . . . , T, with each period of length 1/T years. For quarterly forecasts, T = 4; for monthly forecasts, 
T = 12; for weekly forecasts, T = 52; and for daily forecasts, T = 250 trading days. The volatility of 
the benchmark over any period t will be
Period by period, the forecasting rule of thumb still applies:
Now the IC is the correlation of the forecast and return over the period of length 1/T.
Since we ultimately keep score on an annual basis, we must analyze the annual value added 
generated by these higher4Consider the plight of a gambler who has a 65 percent chance to ''beat the spread" on the Super Bowl (once 
per year) compared to another gambler who has a 55 percent chance to beat the spread on each of the 480 (as of 
1999) regular season and playoff games.


---


### Page 555


Page 550
frequency forecasts. It is the sum of the value added for each period. So, appropriately extending 
Eq. (19.4), we find
Using Eq. (19.12), this becomes
and therefore the optimal active beta in period t becomes
If we forecast once per year, this reduces to Eq. (19.8). If we forecast more frequently, we can be 
more aggressive. So, according to Eq. (19.15), other things being equal, our active betas will double 
if we forecast quarterly instead of annually. However, we will also see later that the IC may shrink 
as we move to shorter time periods.
Given the optimal active betas in each period, the annual value added conditional on the sequence of 
scores {S(1), S(2), . . . , S(T)} is
and the unconditional expected annual value added is
This is a form of the fundamental law of active management: The optimal value added is 
proportional to the breadth T of the strategy. Table 19.6 shows this potential for value added for 
various numbers of forecasts per year and various IC levels. We have assumed a medium aversion 
to risk of λBT = 0.09.
These results assume that each forecast is based on new information. The forecasts must be 
independent. If you make one yearly forecast, then divide it by 4 and use that for the four quarterly 
forecasts, you have added no new information. It still counts as only one forecast per year.


---


### Page 556


Page 551
TABLE 19.6 
Value Added
 
Number of Forecasts per Year
IC
1
4
12
52
0.1
2.78
11.11
33.33
144.44
0.05
0.69
2.78
8.33
36.11
0.02
0.11
0.44
1.33
5.78
0.01
0.03
0.11
0.33
1.44
To see this concretely, let us represent the benchmark's exceptional return over the year using a 
binary model:
where the θj are independent and equally likely to be +1 or –1. We will further specify this model in 
the following particular way: Of those 400 components, the first 100 occur in the first quarter, the 
second 400 occur in the second quarter, etc.5 According to this model, the benchmark exceptional 
return has annual variance of 400 and annual risk of 20 percent, with quarterly variance of 100 and 
quarterly risk of 10 percent.
First assume that we make only one forecast g per year:
where g includes elements of signal, the θk; and elements of noise, the ηj, which are independent of 
the θk and of each other. Each ηj is equally likely to equal +1 or –1. The variance of this raw forecast 
is 16; its standard deviation is 4 percent. Using Eq. (19.19), we can calculate both an annual and a 
quarterly information coefficient
5Alternatively, we could label these binary elements as θij, with i = 1, . . . , 4 and j = 1, . . . 100. The label i 
would denote the quarter. We prefer the notation in the text because it emphasizes that without additional 
information, we will not know which binary element influences which quarter.


---


### Page 557


Page 552
by correlating the forecast g with the annual and quarterly return, respectively. We find
We can substitute these results into Eq. (19.17) and see that the value added is identical whether we 
consider the forecast g annually or quarterly.
In contrast, suppose that we receive the same information, but in parcels each quarter. The quarterly 
forecasts are
The IC in each quarter is
and we get the full benefit of the four separate forecasts, according to Eq. (19.17). We can also 
observe that breaking the annual forecastg into four appropriate quarterly forecasts g1 through g4 
requires information on precisely which components of our signal apply to which quarters. The 
signal g in Eq. (19.19) contains only the sum over all the quarterly information.
Performance Analysis
We have already discussed performance analysis generally in Chap. 17, where we even presented 
approaches to benchmark timing performance analysis. If we are limited to returns-based 
performance analysis, Chap. 17 showed how to estimate benchmark timing skill by distinguishing 
up-market betas from down-market betas.


---


### Page 558


Page 553
For portfolio-based performance analysis (or for benchmark timing so long as we have ex ante 
estimates of portfolio betas), we can separate the achieved active systematic return into three 
components: expected active beta return, active beta surprise, and active benchmark timing return. 
To do this, we require two parameters: the expected benchmark return µB and the average active 
beta.
The ex ante analysis takes µB as given and assumes that the average active beta is 0. In an ideal 
world, these parameters would be part of the prior agreement between the manager and the client. 
With these two parameters, we can attribute the systematic active return, βPA(t), · γB(t), over the time 
interval {t, t + Δt} as
We can interpret these components as
1. The expected active return βPA(t) · µB · Δt
2. Benchmark timing βPA(t) · [γB(t) – µB · Δt]
The benchmark timing component measures whether the portfolio's active beta is positive (negative) 
when the benchmark's excess return is greater (less) than µB · Δt. This benchmark timing term is the 
realization of exactly what we are hoping for in the benchmark timing utility, Eq. (19.4).
The ex post approach to portfolio-based performance attribution is very similar, except that it 
establishes the average market return and beta target ex post. Let
Then we separate the active systematic return as follows:


---


### Page 559


Page 554
This ex post approach is similar in spirit to the ex ante approach. The two approaches would be 
identical if we had specified ex ante an average return of 
and an average beta of 
.
Over the entire period, the first term averages to 
. The second term averages to zero. The 
third term, the benchmark timing contribution, when averaged, captures the in-sample covariance 
between the active beta and the benchmark returns.
We can also invent hybrid approaches, with one of the parameters set ex ante and the other ex post.
As a final, general comment, the forecasting frequency can also affect this ex post component of 
benchmark timing. A one-forecast-per-year strategy will exhibit not only a low information ratio 
and value added, but also a low t statistic. It may require many years of observations to prove with 
statistical confidence the existence of any benchmark timing skill.
Summary
Benchmark timing strategies adjust active portfolio betas based on forecasts of exceptional 
benchmark returns. Benchmark timing is a one-dimensional problem, so whereas stock selection 
strategies can benefit from diversifying bets cross-sectionally across stocks, benchmark timing 
strategies can diversify bets only serially, by frequent forecasts per year. Benchmark timing can 
realistically generate significant value added only through such frequent forecasts per year. The 
most efficient approach to implementing benchmark timing is through the use of futures, as opposed 
to the use of stocks with betas different from 1. Performance analysis techniques exist that can 
measure benchmark timing contributions.
Problems
1. Given a risk aversion to benchmark timing of 0.09, an exceptional market return forecast of 5 
percent, and market risk of 17 percent, what is the optimal portfolio beta?
2. Bob is a benchmark timer. His IC is 0.05, he bets once per year, and he has a low aversion to 
benchmark timing risk λBT = 0.06. What is his value added? What is his optimal level of active risk?


---


### Page 560


Page 555
3. How many years of active returns would you require in order to determine that Bob has 
statistically significant (95 percent confidence level) benchmark timing skill?
4. How would the answers to problems 1 and 2 change if Bob bet 12 times per year?
References
Ambachtsheer, Keith P. "Pension Fund Asset Allocation in Defense of a 60/40 Equity/Debt Asset 
Mix." Financial Analysts Journal, vol. 43, no. 5, 1987, pp. 14–24.
Brocato, Joe, and P. R. Chandy. "Does Market Timing Really Work in the Real World?" Journal of 
Portfolio Management, vol. 20, no. 2, 1994, pp. 39–44.
———. "Market Timing Can Work in the Real World: A Comment." Journal of Portfolio 
Management, vol. 21, no. 3, 1995, pp. 39–44.
Cumby, Robert E., and David M. Modest. "Testing for Market Timing Ability." Journal of 
Financial Economics, vol. 19, no. I, 1987, pp. 169–189.
Gennotte, Gerard, and Terry A. Marsh. "Variations in Economic Uncertainty and Risk Premiums on 
Capital Assets." Berkeley Research Program in Finance Working Paper 210, May 1991.
Henriksson, Roy D., and Robert C. Merton. "On Market Timing and Investment Performance II. 
Statistical Procedures for Evaluating Forecasting Skills." Journal of Business, vol. 54, no. 4, 1981, 
pp. 513–533.
Larsen, Glen A., Jr. and Gregory D. Wozniak. "Market Timing Can Work in the Real World." 
Journal of Portfolio Management, vol. 21, no. 3, 1995.
Modest, David. "Mean Reversion and Changing Risk Premium in the U.S. Stock Market: A Survey 
of Recent Evidence." Presentation at the Berkeley Program Finance Seminar, April 3, 1989.
Rudd, Andrew, and Henry K. Clasing, Jr. Modern Portfolio Theory, 2d ed. (Orinda, Calif.: Andrew 
Rudd 1988).
Sharpe, William F. "Likely Gains from Market Timing." Financial Analysts Journal, vol. 43, no. 2, 
1975, pp. 2–11.
———. "Integrated Asset Allocation." Financial Analysts Journal, vol. 43, no. 5, 1987, pp. 25–32.
Wagner, Jerry, Steve Shellans, and Richard Paul. "Market Timing Works Where It Matters Most . . . 
in the Real World." Journal of Portfolio Management, vol. 18, no. 4, 1992, pp. 86–92.
Technical Appendix
This technical appendix will investigate how to implement a benchmark timing strategy using stocks 
instead of futures. It will show that such an approach leads to unavoidable residual risk.
Consider the problem of constructing a fully invested portfolio with beta βBT and minimum residual 
risk.


---

