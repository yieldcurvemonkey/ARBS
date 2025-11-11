# Grinold-Kahn Active Portfolio Management

## Pages 461-480


### Page 461


Page 457
indicates a decreasing marginal return for each additional amount of turnover that we allow.
A Lower Bound
As the technical appendix will show in detail, when we assume that CS is defined by linear equality 
constraints (e.g., constraining the level of cash or the portfolio beta to equal specific targets) and 
includes portfolio I, we can obtain a quadratic lower bound on potential value added:
Underlying this result is a very simple strategy, prorating a fraction TO/TOQ of each trade needed to 
move from the initial portfolio I to the optimal portfolio Q. This strategy leads to a portfolio that is 
in CS, has turnover equal to TO, and meets the lower bound in Eq. (16.10).
We can express the sentiment of Eq. (16.10) in the value added/turnover rule of thumb:
You can achieve at least 75 percent of the (incremental) value added with 50 percent of the turnover.
This result sounds even better in terms of an effective information ratio, since the value added is 
proportional to the square of the information ratio (at optimality). It implies that a strategy can retain 
at least 87 percent of its information ratio with half the turnover.10
The Value of Scheduling Trades
We can exceed the lower bound in Eq. (16.10) by judicious scheduling of trades, executing the most 
attractive opportunities first. For example, suppose there are only four assets. As we move from 
portfolio I to portfolio Q, we purchase 10 percent in assets 1 and
10The implication is loose for two reasons. First, we derived the relationship between value added and 
information ratio at optimality, assuming no constraints (e.g., on turnover). Second, in this chapter we have 
derived a relationship between turnover and incremental value added.


---


### Page 462


Page 458
Figure 16.3
2 and sell 10 percent of our holdings in assets 3 and 4. Turnover is 20 percent. Suppose the alphas 
for the four assets are 5 percent, 3 percent, –3 percent, and –5 percent, respectively. Then buying 1 
and selling 4 has a bigger impact on alpha than swapping 2 for 3. If we have restricted turnover to 
10 percent, we could make an 8 percent trade of stock 1 for stock 4 and a 2 percent trade of 2 for 3 
rather than doing 5 percent in each trade.
Figure 16.3 illustrates the situation. The solid line shows the frontier; the dotted line shows the 
lower bound. The maximum opportunity for exceeding the bound occurs for turnover somewhere 
between 0 and 100 percent of TOQ.
Transactions Costs
The simplest assumption we can make about transactions costs is that round-trip costs are the same 
for all assets. Let TC be that level of costs. We wish to choose a portfolio P in CS that will 
maximize
Figure 16.4 illustrates the solution to this problem. Let SLOPE(TO) represent the slope of the valueadded/turnover frontier when the


---


### Page 463


Page 459
Figure 16.4
level of turnover is TO. Since the frontier is increasing and concave, SLOPE(TO) is positive and 
decreasing. The incremental gain from each additional amount of turnover is decreasing, so the 
slope of the frontier SLOPE(TO) will decrease to zero as TO increases to TOQ. SLOPE(TO) 
represents the marginal gain in value added from additional transactions, and TC represents the 
marginal cost of additional transactions. The optimal level of turnover will occur where marginal 
cost equals marginal value added, i.e, where SLOPE(TO*) = TC.
As long as the transactions cost is positive and less than SLOPE(0), we can find a level of turnover 
TO* such that SLOPE(TO*) = TC. If TC > SLOPE(0), it is not worthwhile to transact at all, and the 
best solution is to stick with portfolio I.
Implied Transactions Costs
The slope of the value-added/turnover frontier can be interpreted as a transactions cost. We can 
reverse the logic and link any level


---


### Page 464


Page 460
of turnover to a transactions cost; e.g., a turnover level of 20 percent corresponds to a round-trip 
transactions cost of 2.46 percent.
Transactions costs contain observable components, such as commissions and spreads, as well as the 
unobservable market impact. Because managers cannot be sure that they have a precise measure of 
transactions costs, they will often seek to control those costs by establishing an ad hoc policy such 
as ''no more than 20 percent turnover per quarter." The insight that relates the slope of the valueadded/turnover frontier to the level of transactions costs provides an opportunity to analyze that cost 
control policy. One can fix the level of turnover at the required level TOR and then find the slope, 
SLOPE(TOR), of the frontier at TOR. Our ad hoc policy is consistent with an assumption that the 
general level of round-trip transactions costs is equal to SLOPE(TOR). If we have a notion that 
round-trip costs are around 2 percent, and we find that SLOPE(TOR) is about 4.5 percent, then 
something is awry. We can make three possible adjustments to get things back into harmony. One, 
we can increase our estimate of the round-trip costs from 2 percent. Two, we can increase the 
allowed level of turnover TOR, since we are giving up more marginal value added (4.5 percent) than 
it is costing us to trade (2.0 percent). Three, we can reduce our estimates of our ability to add value 
by scaling our alphas back toward zero. A combination of these adjustments—a little give from all 
sides—would be fine as well. This type of analysis serves as a reality check on our policy and the 
overall investment process.
An Example
Consider the following example, using the S&P 100 stocks as a starting universe and the S&P 100 
as the benchmark. We generated alphas11 for the 100 stocks, centering and scaling so that they were 
benchmark-neutral, and also so that portfolio Q would have an alpha of 3.2 percent and an active 
risk of 4 percent when we used λA = 0.1. The initial portfolio contained 20 randomly chosen stocks, 
equal-weighted, with an alpha of 0.07 percent and an active risk of 5.29 percent, typical of a 
situation when a manager takes over an existing account.
11We produced 100 samples from the standard normal distribution.


---


### Page 465


Page 461
TABLE 16.1
 
Value Added

Percentage of 
TOQ
Lower 
Bound
Excess
Total
Percentage of 
VAQ
Implied 
Transactions 
Cost
0.0
–2.73
0.00
–2.73
0.0%  
10.0
–1.91
0.87
–1.03
39.2%
8.66%
20.0
–1.17
1.00
–0.18
59.0%
5.12%
30.0
–0.52
0.88
0.36
71.4%
3.40%
40.0
0.04
0.70
0.74
80.2%
2.50%
50.0
0.52
0.51
1.03
86.8%
1.90%
60.0
0.91
0.34
1.24
91.8%
1.43%
70.0
1.21
0.19
1.40
95.5%
1.02%
80.0
1.43
0.09
1.51
98.0%
0.67%
90.0
1.56
0.02
1.58
99.5%
0.33%
100.0
1.60
0.00
1.60
100.0%
0.00%
Table 16.1 displays the results, including the value added separated into two parts: the lower bound 
and the excess above the bound. The excess is the benefit we get from scheduling the best trades 
first. Table 16.1 also displays the implied transactions costs. We see that reasonable levels of roundtrip costs (about 2 percent) do not call for large amounts of turnover, and that very low or high 
restrictions on turnover correspond to unrealistic levels of transactions costs.
Note that the value of being able to pick off the best trades (the difference between the lower bound 
and the actual fraction of value added) is largest when turnover is 20 percent of the level required to 
move to portfolio Q. In this case, the rule of thumb is conservative: We achieve 87 percent of the 
value-added for 50 percent of the turnover.12
12It is possible to make up a two-stock example where the lower bound on the frontier would be exact. 
Common sense indicates that with more stocks and a reasonable distribution of alphas, there is considerable 
room to add value by plucking the best opportunities.


---


### Page 466


Page 462
Generalizing the Result
We made three assumptions in deriving these results: (1) the initial portfolio was in CS, (2) CS was 
described by linear equalities, and (3) all round-trip transactions costs are the same. We will 
reconsider these in turn.
If portfolio I is not in the choice set, then we can think of the portfolio construction problem as 
being a two-step process. In step 1, we find the portfolio J in the choice set such that the turnover in 
moving from portfolio I to portfolio J is minimal. The value added in moving13 from portfolio I to 
portfolio J is not a consideration, so we may have VAI ≥ VAJ or VAI < VAJ. The turnover required 
to move from I to J is TOJ. The lower bound in Eq. (16.10) will still apply, although we start from 
portfolio J rather than portfolio I.
This situation can demonstrate the costs of adding constraints. What if portfolio I were not in CS, 
and we were limiting turnover to 10 percent per month? If the first 4 percent of the turnover is 
required to move the portfolio back into the choice set, then we have only 6 percent to take 
advantage of our new alphas.
If the choice set CS is described by inequality constraints, such as a restriction on short selling and 
upper limits on the individual asset holdings, then the analysis becomes more complicated. 
However, the value-added/turnover frontier VA(TO) will have the same increasing and concave 
slope that we see in Fig. 16.2. There will be a quadratic lower bound on VA(TO); however, that 
lower bound14 is not as strong as the lower bound we obtain in the case with only equality 
constraints. You are not guaranteed three-quarters of the value added for one-half the turnover. 
Nevertheless, in our experience, 75 percent is still a reasonable lower bound.
So far, we have made the assumption that all round-trip transactions costs are the same. It is good 
news for the portfolio manager if the transactions costs differ (and she or he can forecast the 
difference). Recall that the difference between the lower bound and the value-added/turnover 
frontier stemmed from our ability to
13In a formal sense we are defining 
 if P ∈ CS and VAp = –∞ if P ∈ CS. This means that VA
(TO) = –∞ if TO < TOJ.
14See the appendix for justification.


---


### Page 467


Page 463
adroitly schedule the most value-enhancing trades first. Our ability to discriminate adds value. 
Differences in transactions costs further enhance our ability to discriminate.
We have analyzed this effect in our example. We began with the implied transactions costs at 1.90 
percent for 50 percent of TOQ. We then set the transactions costs to 75 percent of that, or 1.42 
percent, for half of the stocks, and raised the transactions costs for the other stocks to 2.26 percent, 
so that transactions costs remained constant at 50 percent of TOQ. Taking into account these 
differing costs when optimizing barely affected portfolio alphas or risk, but did reduce transactions 
costs by about 30 percent.
Accurate forecasts of the cost of trading can generate significant savings when used as part of the portfolio 
rebalancing process.
The better our model of transactions costs, the better our ability to discriminate among stocks. In the 
example above, we distinguished stocks by their linear costs. More elaborate models can distinguish 
them on the basis of more accurate, dynamic, and nonlinear costs.
Clearly we have seen promise in the approach of lowering transactions costs by lowering turnover 
while retaining much of the value added. Naïve versions of this can preserve 75 percent of the value 
added with 50 percent of the turnover, and clever versions, utilizing differences in asset alphas and 
asset transactions costs, can well exceed the naïve result. We now move on to a second approach to 
reducing transactions costs: optimal trading.
Trading as a Portfolio Optimization Problem
Trading is a portfolio optimization problem, but not the portfolio construction problem we have 
discussed at length. Imagine that you have already completed the portfolio construction (or 
rebalancing) problem. You own a current portfolio, and you desire the output from the portfolio 
construction problem. You trade to move from your current portfolio to your desired portfolio. 
Scheduling these trades—what stock to trade first, second, etc.—over an allowed


---


### Page 468


Page 464
trading period is a portfolio optimization problem. The goal is to maximize trading utility:
defined as short-term alpha minus a short-term risk adjustment, minus market impact. This trading 
utility function swaps reduced market impact for increased short-term risk. We distinguish shortterm alphas and risk from investment-horizon alphas and risk (discussed elsewhere in this book), 
because stock returns over hourly or daily horizons often behave quite differently from stock returns 
over monthly or quarterly horizons.
In portfolio construction, the goal is a target portfolio. In trading, the goal is a set of intermediate 
portfolios held at different times, starting with the current portfolio now, and ending with the target 
portfolio a short time later.
The benchmark for trading is immediate execution, and we measure return and risk relative to that 
benchmark in Eq. (16.12). The problem with quick execution, as discussed earlier, is that it 
increases market impact. Market impact costs increase with trade volume and speed.
What's the intuition about how risk, market impact, and alphas will affect trade scheduling? Risk 
considerations should keep the trade schedule close to the benchmark, i.e., push for quick execution. 
Market-impact considerations will tend to lead to even spacing of trades. Alphas will push for early 
or late execution.
An Example
The details of how to implement this optimal trading process—for example, how to model market 
impact as a function of how fast you trade—are beyond both the scope of this book and the state of 
the art of the investment management industry. However, it's useful to present a very simple 
example of the idea. Even this simple example, though, involves sophisticated mathematics that is 
relegated to the technical appendix.
Consider the trading process at its most basic: You have cash, and you want to buy one stock. You 
think the stock will go up. You want to buy soon, before the stock rises. But to avoid market


---


### Page 469


Page 465
impact, you are willing to be patient and assume some risk of missing the stock rise. What is your 
optimal trading strategy?
Here are the details. Start with cash amount M. After T days, you want to be fully invested in stock 
S, with expected return f and risk σ. The benchmark is immediate execution.
We need to quantify the return, risk, and transactions costs for the implemented portfolio relative to 
the benchmark. For this simple example, we can completely characterize the implemented portfolio 
at time t by the fractional holding of the stock h(t). Assume that you can trade at any time and at any 
speed, so long as you are fully invested by day T. We then seek the optimal h(t) at each time over 
the next T days. The cash position of the implemented portfolio is simply 1 – h(t). The active 
portfolio stock position relative to the benchmark is h(t) – 1, since the benchmark is fully invested. 
The implemented portfolio will have h(0) = 0 andh(T) = 1. Initially the portfolio is entirely cash, and 
at the end ofT days the portfolio is fully invested in stock S.
Over the next T days, the cumulative portfolio active return will be
This integrates (or sums up) the active return over each small period dt to calculate the total active 
return over the period of T days.
Similarly, the cumulative active risk of the implemented portfolio will be
Once again, this cumulative active risk integrates (or sums up) active risk contributions over each 
period dt of the full T-day trading period. This active risk involves the active portfolio position and 
the stock return risk.
Finally, we must treat cumulative transactions costs. For the example, we will focus specifically on 
market impact, the only


---


### Page 470


Page 466
interesting transactions costs in terms of influence on trading strategy.15 We will model the 
cumulative active market impact as
Equation (16.15) models market impact as simply proportional to the square of the stock 
accumulation rate. The faster the portfolio holding changes, the larger the market impact.
This simple model ignores any memory effects—a big assumption, but only if trades are a 
significant fraction of daily volume. According to this, the market doesn't remember what you 
traded yesterday, it just sees what you are trading this instant. Still, the total market impact over the 
T-day trading period is the integral (or sum) of the market impact over each subperiod dt.
The technical appendix describes how to analytically solve for the h(t) which maximizes Eq. 
(16.12). Here we will illustrate a graphical solution for different parameter choices. Three different 
elements influence the solution: return, risk, and market impact. We are looking at short horizons, 
and typically the risk and market impact components will dominate the expected returns 
components.16 Assuming that the expected return is small, we still have two distinct cases: risk 
aversion dominates market impact, and market impact dominates risk. Figure 16.5 illustrates these 
two cases, using T = 5 days. When market impact dominates risk aversion, the optimal schedule is 
to evenly space trades, even though the benchmark is immediate execution. When risk dominates 
market impact, the optimal schedule will closely track the immediate execution benchmark. Within 
two days (40 percent of the period), the portfolio's stock position reaches 75 percent of its target.
15We can include other transactions costs (commissions and taxes) in our forecasts of stock returns, but they 
will not influence our trade schedule, since they are the same, no matter what the schedule.
16Risk scales with the square root of time, while expected return scales linearly with time. As the period shrinks, 
risk will increasingly dominate return.


---


### Page 471


Page 467
Figure 16.5
Trade Implementation
After devising a trading strategy, either through the optimization described above or through some 
more ad hoc approach, the next step is actual trading. You can implement trades as market orders or 
as limit orders.17
Market orders are orders to trade a certain volume at the current market's best price. Limit orders are 
orders to trade a certain volume at a certain price. Limit orders trade off price impact against 
certainty of execution. Market orders can significantly move prices, but they will execute. Limit 
orders will execute at the limit price, if they execute (they may not).
17The choices for trade implementation are actually much more numerous. They include crossing networks, 
alternative stock exchanges, and principal bid transactions. Treatment of these alternatives lies beyond the 
scope of this book.


---


### Page 472


Page 468
There is a current debate over the value of using limit orders in trading. Many argue that placing 
limit orders provides free options to the marketplace. For example, placing a limit order to buy at a 
price P constitutes offering to buy the stock at P, even if the stock is rapidly moving to 80 percent of 
P. Your only protection is the ability to cancel the order as the price begins to move.
Trading portfolios of limit orders has additional problems. For example, in a large market move, all 
the sell limit orders may execute while none of the buy orders execute. This will add market risk to 
the portfolio.
Given these concerns about limit orders, plus the typical portfolio manager's eagerness to complete 
the trades (implement the new alphas), the general rule is to use limit orders sparingly, mainly for 
the stocks with the highest anticipated market impact, and with limit prices set very close to the 
existing market prices.
The opposite side of the debate is that limit orders let value managers sell liquidity and earn the 
liquidity provider's profit. The appropriate order type may depend on the manager's style.
Summary
We have discussed transactions costs, turnover, and trading, with a strategic focus on reducing the 
impact of transactions costs on performance. After discussing the origins of transactions costs and 
how they rise with trade volume and urgency, we focused on the question of analyzing and 
estimating transactions costs. This is difficult because measuring transactions costs is difficult, but it 
can significantly affect realized value added, as the rest of the chapter discussed. The most accurate 
analysis of transactions costs uses the implementation shortfall: comparing the actual portfolio with 
a paper portfolio implemented with no transactions costs.
We discussed the inventory risk approach to modeling market impact. This leads to behavior 
matching market observations, especially the dependence of price impact on the square root of 
volume traded. It also leads to practical forecasts of market impact, ranging from the fairly simple to 
the more complex structural market impact models.
One approach to reducing transactions costs is to reduce turnover while retaining value added. We 
developed a lower bound


---


### Page 473


Page 469
on value added as a function of turnover, and verified the rule of thumb that restricting turnover to 
one-half the level of turnover if there is no restriction on turnover will result in at least threequarters of the value added. We can exceed that bound through our ability to skim off the most 
valuable trades first, and by accounting for differences in transactions costs between stocks. We also 
saw that the slope of the value-added/turnover frontier implies a level of round-trip transactions 
costs.
We then looked at the trading process directly, to see that trading itself is a portfolio optimization 
problem, distinct from portfolio construction. Optimal trading can reduce transactions costs, trading 
reduced market impact for additional short-term risk. Choices for trade implementation include 
market orders and limit orders. The disadvantages of limit orders make them most appropriate for 
the highest market impact stocks, with limit prices close to market prices.
Problems
1. Imagine that you are a stock trader, and that a portfolio manager plans to measure your trading 
prowess by comparing your execution prices with volume-weighted average prices. How would you 
attempt to look as good as possible by this measure? Would this always coincide with the best 
interests of the manager?
2. Why is it more difficult to beat the bound in Eq. (16.10) with a portfolio of only 2 stocks than 
with a portfolio of 100 stocks?
3. A strategy can achieve 200 basis points of value added with 200 percent annual turnover. How 
much value-added should it achieve with 100 percent annual turnover? How much turnover is 
required in order to achieve 100 basis points of value added?
4. How would the presence of memory effects in market impact change the trade optimization 
results displayed in Fig. 16.5?
5. In Fig. 16.5, why does high risk aversion lead to quick trading?


---


### Page 474


Page 470
References
Angel, James J., Gary L. Gastineau, and Clifford J. Webber. ''Reducing the Market Impact of Large 
Stock Trades." Journal of Portfolio Management, vol. 24, no. 1, 1997, pp. 69–76.
Atkins, Allen B., and Edward A. Dyl. "Transactions Costs and Holding Periods for Common 
Stocks." Journal of Finance, vol. 52, no. 1, 1997, pp. 309–325.
BARRA, Market Impact Model Handbook (Berkeley, Calif.: BARRA, 1997).
Chan, Louis K. C., and Josef Lakonishok. "The Behavior of Stock Prices around Institutional 
Trades." Journal of Finance, vol. 50, no. 4, 1995, pp. 1147–1174.
———. "Institutional Equity Trading Costs: NYSE versus NASDAQ." Journal of Finance, vol. 52, 
no. 2, 1997, pp. 713–735.
Ellis, Charles D. "The Loser's Game." Financial Analysts Journal, vol. 31, no. 4, 1975, pp. 19–26.
Grinold, Richard C., and Mark Stuckelman. "The Value-Added/Turnover Frontier." Journal of 
Portfolio Management, vol. 19, no. 4, 1993, pp. 8–17.
Handa, Puneet, and Robert A. Schwartz. "Limit Order Trading." Journal of Finance, vol. 51, no. 5, 
1996, pp. 1835–1861.
Kahn, Ronald N. "How the Execution of Trades Is Best Operationalized." In Execution Techniques, 
True Trading Costs, and the Microstructure of Markets, edited by Katrina F. Sherrerd 
(Charlottesville, Va.: AIMR 1993).
Keim, Donald B., and Ananth Madhavan. "The Cost of Institutional Equity Trades." Financial 
Analysts Journal, vol. 54, no. 4, 1998, pp. 50–69.
Lakonishok, Josef, Andre Shleifer, and Robert W. Vishny. "Study of U.S. Equity Money Manager 
Performance." Brookings Institute Study, 1992.
Loeb, Thomas F. "Trading Costs: The Critical Link between Investment Information and Results." 
Financial Analysts Journal, vol. 39, no. 3, 1983, pp. 39–44.
Malkiel, Burton. "Returns from Investing in Equity Mutual Funds 1971 to 1991." Journal of 
Finance, vol. 50, no. 2, 1995, pp. 549–572.
Modest, David. "What Have We Learned about Trading Costs? An Empirical Retrospective." 
Berkeley Program in Finance Seminar, March 1993.
Perold, Andre. "The Implementation Shortfall: Paper versus Reality." Journal of Portfolio 
Management, vol 14, no. 3, 1988, pp. 4–9.
Pogue, G. A. "An Extension of the Markowitz Portfolio Selection Model to Include Variable 
Transactions Costs, Short Sales, Leverage Policies and Taxes." Journal of Finance, vol. 45, no. 5, 
1970, pp. 1005–1027.
Rudd, Andrew, and Barr Rosenberg.. "Realistic Portfolio Optimization." In Portfolio Theory—
Studies in Management Science, vol. 11, edited by E. J. Elton and M. J. Gruber (Amsterdam: North 
Holland Press, 1979).
Schreiner, J. "Portfolio Revision: A Turnover-Constrained Approach." Financial Management, vol.


---


### Page 475


9, no. 1, 1980, pp. 67–75.
Treynor, Jack L. "The Only Game in Town." Financial Analysts Journal, vol. 27, no. 2, 1971, pp. 
12–22.
———. "Types and Motivations of Market Participants." In Execution Techniques, True Trading 
Costs, and the Microstructure of Markets, edited by Katrina F. Sherrerd (Charlottesville, Va.: 
AIMR, 1993).


---


### Page 476


Page 471
———. "The Invisible Costs of Trading." Journal of Portfolio Management, vol. 21, no. 1, 1994, 
pp. 71–78.
Wagner, Wayne H. (Ed.). A Complete Guide to Securities Transactions: Controlling Costs and 
Enhancing Performance (New York: Wiley, 1988).
———. "Defining and Measuring Trading Costs." In Execution Techniques, True Trading Costs, 
and the Microstructure of Markets, edited by Katrina F. Sherrerd (Charlottesville, Va.: AIMR, 
1993).
Wagner, Wayne H., and Michael Banks. "Increasing Portfolio Effectiveness via Transaction Cost 
Management." Journal of Portfolio Management, vol. 19, no. 1, 1992, pp. 6–11.
Wagner, Wayne H., and Evan Schulman. "Passive Trading: Point and Counter-point." Journal of 
Portfolio Management, vol. 20, no. 3, 1994, pp. 25–29.
Technical Appendix
This technical appendix will cover two topics: the bound on value added versus turnover, and the 
solution to the example trading optimization problem.
We begin by proving the bound on value added versus turnover for the cases of linear inequality and 
equality constraints. Eq. (16.10) corresponds exactly to the case of linear equality constraints.
Inequality Case, CS = {h|A · h ≤ b}
Portfolio Q is optimal for the problem Max{VAP|hP ∈ CS}. This means that we can find 
nonnegative Lagrange multipliers π ≥ 0 such that
Since hI ∈ CS, we have b – A · hI ≥ 0 and π ≥ 0, so
If we premultiply Eq. (16A.1) by (hI – hQ) and use Eqs. (16A.2) and (16A.3), we find that


---


### Page 477


Page 472
Now consider the family of solutions as we move directly from portfolio I to portfolio Q:
where we have introduced the trade portfolio hT. These solutions are all in CS as long as 0 ≤ δ ≤ 1. 
The solutions have value added
where σT is the risk of hT. If we use Eq. (16A.4), then Eq. (16A.6) simplifies to
Since VA(0) = VAI, VA(1) = VAQ, and ΔVAQ = VAQ – VAI, we have
Thus Eq. (16A.7) simplifies further to
The slope of VA(δ), Eq. (16A.9), is 2 · ΔVAQ · (a – b · δ), which is positive for 0 ≤ δ < 1 and 
decreases to κ as δ approaches 1.
Equality Case, CS = {h|A · h = b}
The analysis is as before, except that π in Eq. (16A.1) is unrestricted in sign. Therefore κ = 0 and, 
from Eq. (16A.8), 
. Thus Eq. (16A.9) simplifies to


---


### Page 478


Page 473
Trade Optimization
We will now describe how to solve analytically for the trading strategy h(t) which maximizes utility 
in the simple example
Schematically, we can represent the utility as
At the optimal solution, the variation of this utility will be zero:
Integrating the second term by parts (and remembering that the variation is zero at the fixed 
endpoints of the integral),
Thus we can maximize U by choosing h(t) which satisfies
Applying this to the particular utility function [Eq. (16A.13)], the portfolio holding must satisfy the 
second-order ordinary differential equation
plus the boundary conditions h(0) = 0 and h(T) = 1. Defining relative parameters


---


### Page 479


Page 474
and rearranging terms, Eq. (16A.18) becomes
Applying standard mathematical techniques to Eq. (16A.21), we find that the optimal solution h(t) is
We can characterize various regimes for the solution h(t) by looking at some dimensionless 
quantities which enter into the optimal h(t):
R1. (g · T)2 >> 1. Risk aversion dominates over market impact.
R2. (g · T)2 << 1. Market impact dominates over risk aversion.
R3. s · T2 >> 1. Alpha is positive and dominant over market impact.
R4. s · T2 << –1. Alpha is negative and dominant over market impact.
R5. |s/g2| >> 1. Alpha (positive or negative) dominates risk aversion.
R6. |s/g2| << 1. Risk aversion dominates over alpha.
If we assume that the alpha is zero, so that the coefficient s = 0 above, then it's interesting to see the 
limiting behavior of Eq. (16A.22) in regimes R1 and R2. When market impact dominates


---


### Page 480


Page 475
over risk, h(t) follows a straight-line path from 0 to 1. The result is uniform trading. If, on the other 
hand, risk dominates over market impact, h(t) exponentially approaches 1:
Exercise
1. Assuming zero alpha, derive the limit of Eq. (16A.22) when market impact dominates over risk. 
Also show that in the limit that risk dominates over market impact, the optimal trade schedule 
reduces to an exponential, as in Eq. (16A.26).
Applications Exercises
Use alphas from a residual reversal model to build an optimal portfolio of MMI stocks. The initial 
portfolio is the MMI, and the benchmark is the CAPMMI. Use a risk aversion of 0.075 and the 
typical institutional constraints: full investment, no short sales.
1. What is the value added of the MMI? What is the value added of the optimal portfolio? What is 
the incremental value added?
2. What is the turnover in moving from the MMI to the optimal portfolio?
3. Now build a portfolio exactly halfway between the MMI and the optimal portfolio:
What is the turnover in moving from the MMI to this intermediate portfolio? What is its value 
added? Compare the incremental value added of this portfolio over the MMI to that of the optimal 
portfolio over the MMI. Verify Eq. (16.10).


---

