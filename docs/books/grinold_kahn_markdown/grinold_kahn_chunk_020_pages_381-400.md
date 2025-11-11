# Grinold-Kahn Active Portfolio Management

## Pages 381-400


### Page 381


Page 377
Chapter 14— 
Portfolio Construction
Introduction
Implementation is the efficient translation of research into portfolios. Implementation is not 
glamorous, but it is important. Good implementation can't help poor research, but poor 
implementation can foil good research. A manager with excellent information and faulty 
implementation can snatch defeat from the jaws of victory.
Implementation includes both portfolio construction, the subject of this chapter (and to some extent 
the next chapter), and trading, a subject of Chap. 16. This chapter will take a manager's investment 
constraints (e.g., no short sales) as given and build the best possible portfolio subject to those 
limitations. It will assume the standard objective: maximizing active returns minus an active risk 
penalty. The next chapter will focus specifically on the very standard no short sales constraint and 
its surprisingly significant impact. This chapter will also take transactions costs as just an input to 
the portfolio construction problem. Chapter 16 will focus more on how to estimate transactions costs 
and methods for reducing them.
Portfolio construction requires several inputs: the current portfolio, alphas, covariance estimates, 
transactions cost estimates, and an active risk aversion. Of these inputs, we can measure only the 
current portfolio with near certainty. The alphas, covariances, and transactions cost estimates are all 
subject to error. The alphas are often unreasonable and subject to hidden biases. The covariances 
and transactions costs are noisy estimates; we hope that they are


---


### Page 382


Page 378
unbiased, but we know that they are not measured with certainty. Even risk aversion is not certain. 
Most active managers will have a target level of active risk that we must make consistent with an 
active risk aversion.
Implementation schemes must address two questions. First, what portfolio would we choose given 
inputs (alpha, covariance, active risk aversion, and transactions costs) known without error? Second, 
what procedures can we use to make the portfolio construction process robust in the presence of 
unreasonable and noisy inputs? How do you handle perfect data, and how do you handle less than 
perfect data?
How to handle perfect data is the easier dilemna. With no transactions costs, the goal is to maximize 
value added within any limitations on the manager's behavior imposed by the client. Transactions 
costs make the problem more difficult. We must be careful to compare transactions costs incurred at 
a point in time with returns and risk realized over a period of time.
This chapter will mainly focus on the second question, how to handle less than perfect data. Many 
of the procedures used in portfolio construction are, in fact, indirect methods of coping with noisy 
data. With that point of view, we hope to make portfolio construction more efficient by directly 
attacking the problem of imperfect or ''noisy" inputs.
Several points emerge in this chapter:
• Implementation schemes are, in part, safeguards against poor research.
• With alpha analysis, the alphas can be adjusted so that they are in line with the manager's desires 
for risk control and anticipated sources of value added.
• Portfolio construction techniques include screening, stratified sampling, linear programming, and 
quadratic programming. Given sufficiently accurate risk estimates, the quadratic programming 
technique most consistently achieves high value added.
• For most active institutional portfolio managers, building portfolios using alternative risk 
measures greatly increases the effort (and the chance of error) without greatly affecting the result.


---


### Page 383


Page 379
• Managers running separate accounts for multiple clients can control dispersion, but cannot 
eliminate it.
Let's start with the relationship between the most important input, alpha, and the output, the revised 
portfolio.
Alphas and Portfolio Construction
Active management should be easy with the right alphas. Sometimes it isn't. Most active managers 
construct portfolios subject to certain constraints, agreed upon with the client. For example, most 
institutional portfolio managers do not take short positions and limit the amount of cash in the 
portfolio. Others may restrict asset coverage because of requirements concerning liquidity, selfdealing, and so on. These limits can make the portfolio less efficient, but they are hard to avoid.
Managers often add their own restrictions to the process. A manager may require that the portfolio 
be neutral across economic sectors or industries. The manager may limit individual stock positions 
to ensure diversification of the active bets. The manager may want to avoid any position based on a 
forecast of the benchmark portfolio's performance. Managers often use such restrictions to make 
portfolio construction more robust.
There is another way to reach the same final portfolio: simply adjust the inputs. We can always 
replace a very sophisticated (i.e., complicated) portfolio construction procedure that leads to active 
holdings 
, active risk 
, and an ex ante information ratio IR with a direct unconstrained 
mean/variance optimization using a modified set of alphas and the appropriate level of risk 
aversion.1 The modified alphas are
1The simple procedure maximizes 
. The first-order conditions for this problem are 
. Equations (14.1) and (14.2) ensure that hPA will satisfy the first-order conditions. Note that 
we are explicitly focusing portfolio construction on active return and risk, instead of residual return and risk. 
Without benchmark timing, these perspectives are identical.


---


### Page 384


Page 380
and the appropriate active risk aversion is
Table 14.1 illustrates this for Major Market Index stocks as of December 1992. We assign each 
stock an alpha (chosen randomly in this example), and first run an unconstrained optimization of 
risk-adjusted active return (relative to the Major Market Index) using an active risk aversion of 
0.0833. Table 14.1 shows the result. The unconstrained optimization sells American Express and 
Coca-Cola short, and invests almost 18 percent of the portfolio in 3M. We then add constraints; we 
disallow short sales and require that portfolio holdings cannot exceed benchmark holdings by more 
than
TABLE 14.1
Stock
Index 
Weight
Alpha
Optimal 
Holding
Constrained 
Optimal 
Holding
Modified 
Alpha
American Express
2.28%
–3.44%
–0.54%
0.00%
–1.14%
AT&T
4.68%
1.38%
6.39%
6.18%
0.30%
Chevron
6.37%
0.56%
7.41%
7.05%
0.11%
Coca-Cola
3.84%
–2.93%
–2.22%
0.00%
–0.78%
Disney
3.94%
1.77%
5.79%
5.85%
0.60%
Dow Chemical
5.25%
0.36%
5.78%
6.07%
0.22%
DuPont
4.32%
–1.50%
1.54%
1.67%
–0.65%
Eastman Kodak
3.72%
0.81%
4.07%
4.22%
0.14%
Exxon
5.60%
–0.10%
4.57%
4.39%
–0.19%
General Electric
7.84%
–2.80%
0.53%
0.92%
–1.10%
General Motors
2.96%
–2.50%
1.93%
1.96%
–0.52%
IBM
4.62%
–2.44%
3.24%
3.54%
–0.51%
International Paper
6.11%
–0.37%
5.73%
6.15%
0.01%
Johnson & Johnson
4.63%
2.34%
7.67%
7.71%
0.66%
McDonalds
4.47%
0.86%
5.07%
4.98%
0.14%
Merck
3.98%
0.80%
4.72%
4.78%
0.20%
3M
9.23%
3.98%
17.95%
14.23%
0.91%
Philip Morris
7.07%
0.71%
7.82%
7.81%
0.12%
Procter & Gamble
4.92%
1.83%
6.99%
6.96%
0.44%
Sears
4.17%
0.69%
5.57%
5.54%
0.35%


---


### Page 385


Page 381
5 percent. This result is also displayed in Table 14.1. The optimal portfolio no longer holds 
American Express or Coca-Cola at all, and the holding of 3M moves to exactly 5 percent above the 
benchmark holding. The other positions also adjust.
This constrained optimization corresponds to an unconstrained optimization using the same active 
risk aversion of 0.0833 and the modified alphas displayed in the last column of Table 14.1. We 
derive these using Eqs. (14.1) and (14.2). These modified alphas are pulled in toward zero relative 
to the original alphas, as we would expect, since the constraints moved the optimal portfolio closer 
to the benchmark. The original alphas have a standard deviation of 2.00 percent, while the modified 
alphas have a standard deviation of 0.57 percent.
We can replace any portfolio construction process, regardless of its sophistication, by a process that 
first refines the alphas and then uses a simple unconstrained mean/variance optimization to 
determine the active positions.
This is not an argument against complicated implementation schemes. It simply focuses our 
attention on a reason for the complexity. If the implementation scheme is, in part, a safeguard 
against unrealistic or unreasonable inputs, perhaps we can, more fruitfully, address this problem 
directly. A direct attack calls for either refining the alphas (preprocessing) or designing 
implementation procedures that explicitly recognize the procedure's role as an "input moderator." 
The next section discusses preprocessing of alphas.
Alpha Analysis
We can greatly simplify the implementation procedure if we ensure that our alphas are consistent 
with our beliefs and goals. Here we will outline some procedures for refining alphas that can 
simplify the implementation procedure, and explicitly link our refinement in the alphas to the 
desired properties of the resulting portfolios. We begin with the standard data screening procedures 
of scaling and trimming.2
2Because of their simplicity, we treat scaling and trimming first. However, when we implement alpha analysis, 
we impose scaling and trimming as the final step in the process.


---


### Page 386


Page 382
Scale the Alphas
Alphas have a natural structure, as we discussed in the forecasting rule of thumb in Chap. 10: α = 
volatility · IC · score. This structure includes a natural scale for the alphas. We expect the 
information coefficient (IC) and residual risk (volatility) for a set of alphas to be approximately 
constant, with the score having mean 0 and standard deviation 1 across the set. Hence the alphas 
should have mean 0 and standard deviation, or scale, of Std{α} ~ volatility · IC.3 An information 
coefficient of 0.05 and a typical residual risk of 30 percent would lead to an alpha scale of 1.5 
percent. In this case, the mean alpha would be 0, with roughly two-thirds of the stocks having alphas 
between –1.5 percent and +1.5 percent and roughly 5 percent of the stocks having alphas larger than 
+3.0 percent or less than –3.0 percent. In Table 14.1, the original alphas have a standard deviation of 
2.00 percent and the modified alphas have a standard deviation of 0.57 percent. This implies that the 
constraints in that example effectively shrank the IC by 62 percent, a significant reduction. There is 
value in noting this explicitly, rather than hiding it under a rug of optimizer constraints.
The scale of the alphas will depend on the information coefficient of the manager. If the alphas 
input to portfolio construction do not have the proper scale, then rescale them.
Trim Alpha Outliers
The second refinement of the alphas is to trim extreme values. Very large positive or negative 
alphas can have undue influence. Closely examine all stocks with alphas greater in magnitude than, 
say, three times the scale of the alphas. A detailed analysis may show that some of these alphas 
depend upon questionable data and should
3There is a related approach to determining the correct scale that uses the information ratio instead of the 
information coefficient. This approach calculates the information ratio implied by the alphas and scales them, if 
necessary, to match the manager's ex ante information ratio. The information ratio implied by the alphas is 
 We can calculate this quickly by running an optimization with unrestricted cash holdings, no 
constraints, no limitations on asset holdings, and an active risk aversion of 0.5. The optimal active portfolio is 
 and the optimal portfolio alpha is (IR0)2. If IR is the desired ex ante information ratio, we can 
rescale the alphas by a factor (IR/IR0).


---


### Page 387


Page 383
be ignored (set to zero), while others may appear genuine. Pull in these remaining genuine alphas to 
three times scale in magnitude.
A second and more extreme approach to trimming alphas is to force4 them into a normal distribution 
with benchmark alpha equal to 0 and the required scale factor. Such an approach is extreme because 
it typically utilizes only the ranking information in the alphas and ignores the size of the alphas. 
After such a transformation, you must recheck benchmark neutrality and scaling.
Neutralization
Beyond scaling and trimming, we can remove biases or undesirable bets from our alphas. We call 
this process neutralization. It has implications, not surprisingly, in terms of both alphas and 
portfolios.
Benchmark neutralization means that the benchmark has 0 alpha. If our initial alphas imply an alpha 
for the benchmark, the neutralization process recenters the alphas to remove the benchmark alpha. 
From the portfolio perspective, benchmark neutralization means that the optimal portfolio will have 
a beta of 1, i.e., the portfolio will not make any bet on the benchmark.
Neutralization is a sophisticated procedure, but it isn't uniquely defined. As the technical appendix 
will demonstrate, we can achieve even benchmark neutrality in more than one way. This is easy to 
see from the portfolio perspective: We can choose many different portfolios to hedge out any active 
beta.
As a general principle, we should consider a priori how to neutralize our alphas. The choices will 
include benchmark, cash, industry, and factor neutralization. Do our alphas contain any information 
distinguishing one industry from another? If not, then industry-neutralize. The a priori approach 
works better than simply trying all possibilities and choosing the best performer.
4Suppose that hB,n is the benchmark weight for asset n. Assume for convenience that the assets are ordered so 
that α1 ≤ α2 ≤ α3, etc. Then define p1 = 0.5 · hB,1 and for n ≥ 2, pn = pn – 1 + 0.5 · (hB,n – 1 + hB,n). We have 0 < p1 < 
p2 < · · · < pN – 1 < pN < 1. Find the normal variate zn that satisfies pn = Φ{zn}, where Φ is the cumulative normal 
distribution. We can use the z variables as alphas, after adjustments for location and scale.


---


### Page 388


Page 384
Benchmark- and Cash-Neutral Alphas
The first and simplest neutralization is to make the alphas benchmark-neutral. By definition, the 
benchmark portfolio has 0 alpha, although the benchmark may experience exceptional return. 
Setting the benchmark alpha to 0 ensures that the alphas are benchmark-neutral and avoids 
benchmark timing.
In the same spirit, we may also want to make the alphas cash-neutral; i.e., the alphas will not lead to 
any active cash position. It is possible (see Exercise 11 in the technical appendix) to make the alphas 
both cash- and benchmark-neutral.
Table 14.2 displays the modified alphas from Table 14.1 and shows how they change when we 
make them benchmark-neutral. In this example, the benchmark alpha is only 1.6 basis points, so
TABLE 14.2
Stock
Beta
Modified Alpha
Modified BenchmarkNeutral Alpha
American Express
1.21
–1.14%
–1.16%
AT&T
0.96
0.30%
0.29%
Chevron
0.46
0.11%
0.10%
Coca Cola
0.96
–0.78%
–0.79%
Disney
1.23
0.60%
0.58%
Dow Chemical
1.13
0.22%
0.20%
DuPont
1.09
–0.65%
–0.67%
Eastman Kodak
0.60
0.14%
0.13%
Exxon
0.46
–0.19%
–0.20%
General Electric
1.30
–1.10%
–1.12%
General Motors
0.90
–0.52%
–0.53%
IBM
0.64
–0.51%
–0.52%
International Paper
1.18
0.01%
–0.01%
Johnson & Johnson
1.13
0.66%
0.64%
McDonalds
1.06
0.14%
0.12%
Merck
1.06
0.20%
0.18%
3M
0.74
0.91%
0.90%
Philip Morris
0.94
0.12%
0.10%
Procter & Gamble
1.00
0.44%
0.42%
Sears
1.05
0.35%
0.33%


---


### Page 389


Page 385
subtracting βn · αB from each modified alpha does not change the alpha very much. We have shifted 
the alpha of the benchmark Major Market Index from 1.6 basis points to 0. This small change in 
alpha is consistent with the observation that the optimal portfolio before benchmark neutralizing had 
a beta very close to 1.
Risk-Factor-Neutral Alphas
The multiple-factor approach to portfolio analysis separates return along several dimensions. A 
manager can identify each of those dimensions as either a source of risk or a source of value added. 
By this definition, the manager does not have any ability to forecast the risk factors. Therefore, he or 
she should neutralize the alphas against the risk factors. The neutralized alphas will include only 
information on the factors the manager can forecast, along with specific asset information. Once 
neutralized, the alphas of the risk factors will be 0.
For example, a manager can ensure that her portfolios contain no active bets on industries or on a 
size factor. Here is one simple approach to making alphas industry-neutral: Calculate the 
(capitalization-weighted) alpha for each industry, then subtract the industry average alpha from each 
alpha in that industry.
The technical appendix presents a more detailed account of alpha analysis in the context of a 
multiple-factor model. We can modify the alphas to achieve desired active common-factor positions 
and to isolate the part of the alpha that does not influence the common-factor positions.
Transactions Costs
Up to this point, the struggle has been between alpha and active risk. Any klutz can juggle two 
rubber chickens. The juggling becomes complicated when the third chicken enters the performance. 
In portfolio construction, that third rubber chicken is transactions costs, the cost of moving from 
one portfolio to another. It has been said that accurate estimation of transactions costs is just as 
important as accurate forecasts of exceptional return. That is an over-


---


### Page 390


Page 386
statement,5 but it does point out the crucial role transactions costs play.
In addition to complicating the portfolio construction problem, transactions costs have their own 
inherent difficulties. We will see that transactions costs force greater precision on our estimates of 
alpha. We will also confront the complication of comparing transactions costs at a point in time with 
returns and risk which occur over an investment horizon. The more difficult issues of what 
determines transactions costs, how to measure them, and how to avoid them, we postpone until 
Chap. 16.
When we consider only alphas and active risk in the portfolio construction process, we can offset 
any problem in setting the scale of the alphas by increasing or decreasing the active risk aversion. 
Finding the correct trade-off between alpha and active risk is a one-dimensional problem. By 
turning a single knob, we can find the right balance. Transactions costs make this a two-dimensional 
problem. The trade-off between alpha and active risk remains, but now there is a new trade-off 
between the alpha and the transactions costs. We therefore must be precise in our choice of scale, to 
correctly trade off between the hypothetical alphas and the inevitable transactions costs.
The objective in portfolio construction is to maximize risk-adjusted annual active return. 
Rebalancing incurs transactions costs at that point in time. To contrast transactions costs incurred at 
that time with alphas and active risk expected over the next year requires a rule to allocate the 
transactions costs over the one-year period. We must amortize the transactions costs to compare 
them to the annual rate of gain from the alpha and the annual rate of loss from the active risk. The 
rate of amortization will depend on the anticipated holding period.
An example will illustrate this point. We will assume perfect certainty and a risk free rate of zero; 
and we will start and end invested in cash. Stock 1's current price is $100. The price of stock 1 will 
increase to $102 in the next 6 months and then remain at
5Perfect information regarding returns is much more valuable than perfect information regarding transactions 
costs. The returns are much less certain than the transactions costs. Accurate estimation of returns reduces 
uncertainty much more than accurate estimation of transactions costs.


---


### Page 391


Page 387
$102. Stock 2's current price is also $100. The price of stock 2 will increase to $108 over the next 24 
months and then remain at $108. The cost of buying and selling each stock is $0.75. The annual 
alpha for both stock 1 and stock 2 is 4 percent. To contrast the two situations more clearly, let's 
assume that in 6 months, and again in 12 months and in 18 months, we can find another stock like 
stock 1.
The sequence of 6-month purchases of stock 1 and its successors will each net a $2.00 profit before 
transactions costs. There will be transactions costs (recall that we start and end with cash) of $0.75, 
$1.50, $1.50, $1.50, and $0.75 at 0, 6, 12, 18, and 24 months, respectively. The total trading cost is 
$6, the gain on the shares is $8, the profit over 2 years is $2, and the annual percentage return is 1 
percent.
With stock 2, over the 2-year period we will incur costs of $0.75 at 0 and 24 months. The total cost 
is $1.50, the gain is $8, the profit is $6.50, and the annual percentage return is 3.25 percent.
With the series of stock 1 trades, we realize an annual alpha of 4 percent and an annualized 
transactions cost of 3 percent. With the single deal in stock 2, we realize an annual alpha of 4 
percent and an annualized transactions cost of 0.75 percent. For a 6-month holding period, we 
double the round-trip transactions cost to get the annual transactions cost, and for a 24-month 
holding period, we halve the round-trip transactions cost to get the annual transactions cost. There's 
a general rule here:
The annualized transactions cost is the round-trip cost divided by the holding period in years.
Chapter 16, "Transactions Costs, Turnover, and Trading," will deal with the issues concerning the 
estimation and control of transactions costs. For the remainder of this chapter, we will assume that 
we know the cost for each anticipated trade.
Practical Details
Before proceeding further in our analysis of portfolio construction, we should review some practical 
details concerning this process. First, how do we choose a risk aversion parameter?
We briefly discussed this problem in Chap. 5. There we found an optimality relationship between 
the information ratio, the risk


---


### Page 392


Page 388
aversion, and the optimal active risk. Repeating that result here, translated from residual to active 
return and risk,
The point is that we have more intuition about our information ratio and our desired amount of 
active risk. Hence, we can use Eq. (14.3) to back out an appropriate risk aversion. If our information 
ratio is 0.5, and we desire 5 percent active risk, we should choose an active risk aversion of 0.05. 
Note that we must be careful to verify that our optimizer is using percents and not decimals.
A second practical matter concerns aversion to specific as opposed to common-factor risk. Several 
commercial optimizers utilize this decomposition of risk to allow differing aversions to these 
different sources of risk:
An obvious reaction here is, ''Risk is risk, why would I want to avoid one source of risk more than 
another?" This is a useful sentiment to keep in mind, but there are at least two reasons to consider 
implementing a higher aversion to specific risk. First, since specific risk arises from bets on specific 
assets, a high aversion to specific risk reduces bets on any one stock. In particular, this will reduce 
the size of your bets on the (to be determined) biggest losers. Second, for managers of multiple 
portfolios, aversion to specific risk can help reduce dispersion. This will push all those portfolios 
toward holding the same names.
The final practical details we will cover here concern alpha coverage. First, what happens if we 
forecast returns on stocks that are not in the benchmark? We can always handle that by expanding 
the benchmark to include those stocks, albeit with zero weight. This keeps stock n in the benchmark, 
but with no weight in determining the benchmark return or risk. Any position in stock n will be an 
active position, with active risk correctly handled.
What about the related problem, a lack of forecast returns for stocks in the benchmark? Chapter 11 
provided a sophisticated approach to inferring alphas for some factors, based on the alphas for other 
factors. We could apply the same approach in this case. For stock-specific alphas, we can use the 
following approach.


---


### Page 393


Page 389
Let N1 represent the collection of stocks with forecasts, and N0 the stocks without forecasts. The 
value-weighted fraction of stocks with forecasts is
The average alpha for group N1 is
To round out the set of forecasts, set 
 for stocks in N1 and 
 for stocks in N0. 
These alphas are benchmark-neutral. Moreover, the stocks we did not cover will have a zero, and 
therefore neutral, forecast.
Portfolio Revisions
How often should you revise your portfolio? Whenever you receive new information. That's the 
short answer. If a manager knows how to make the correct trade-off between expected active return, 
active risk, and transactions costs, frequent revision will not present a problem. If the manager has 
human failings, and is not sure of his or her ability to correctly specify the alphas, the active risk, 
and the transactions costs, then the manager may resort to less frequent revision as a safeguard.
Consider the unfortunate manager who underestimates transactions costs, makes large changes in 
alpha estimates very frequently, and revises his portfolio daily. This manager will churn the 
portfolio and suffer higher than expected transactions costs and lower than expected alpha. A crude 
but effective cure is to revise the portfolio less frequently.
More generally, even with accurate transactions costs estimates, as the horizon of the forecast alphas 
decreases, we expect them to contain larger amounts of noise. The returns themselves become 
noisier with shorter horizons. Rebalancing for very short horizons would involve frequent reactions 
to noise, not signal. But the transactions costs stay the same, whether we are reacting to signal or 
noise.


---


### Page 394


Page 390
This trade-off between alpha, risk, and costs is difficult to analyze because of the inherent 
importance of the horizon. We expect to realize the alpha over some horizon. We must therefore 
amortize the transactions costs over that horizon.
We can capture the impact of new information, and decide whether to trade, by comparing the 
marginal contribution to value added for stock n, MCVAn, to the transactions costs. The marginal 
contribution to value added shows how value added, as measured by risk-adjusted alpha, changes as 
the holding of the stock is increases, with an offsetting decrease in the cash position. As our holding 
in stock n increases, αn measures the effect on portfolio alpha. The change in value added also 
depends upon the impact (at the margin) on active risk of adding more of stock n. The stock's 
marginal contribution to active risk, MCARn, measures the rate at which active risk changes as we 
add more of stock n. The loss in value added due to changes in the level of active risk will be 
proportional to MCARn. Stock n's marginal contribution to value added depends on its alpha and 
marginal contribution to active risk, in particular:
Let PCn be the purchase cost and SCn the sales cost for stock n. For purposes of illustration, we take 
PCn = 0.50 percent and SCn = 0.75 percent. If the current portfolio is optimal,6 then the marginal 
contribution to value added for stock n should be less than the purchase cost. If it exceeded the 
purchase cost, say at 0.80 percent, then a purchase of stock n would yield a net benefit of 0.80 
percent – 0.50 percent = 0.30 percent. Similarly the marginal contribution to value added must be 
greater than the negative of the sales cost. If it were – 1.30 percent, then we could decrease our 
holding of stock n and save 1.30 percent at the margin. The cost would be the 0.75 percent 
transactions cost, for a net benefit of 1.30 percent – 0.75 percent = 0.55 percent.
6Assuming no limitations on holdings, no limitations on the cash position, and no additional constraints. 
Aficionados will realize that this analysis becomes more complicated, but not essentially different, if we 
include these additional constraints.


---


### Page 395


Page 391
This observation allows us to put a band around the alpha for each stock. As long as the alpha stays 
within that band, the portfolio will remain optimal, and we should not react to new information. The 
bandwidth is the total of the sale plus purchase costs, 0.50 percent + 0.75 percent = 1.25 percent in 
our example. If we just purchased a stock, its marginal contribution to value added will equal its 
purchase cost. We are at the upper end of the band. Any increase in alpha would lead to further 
purchases. The alpha would have to decrease by 1.25 percent before we would consider selling the 
stock. The situation before new information arrives is
or, using Eq. (14.7),
This analysis has simplified the problem by subsuming the amortization horizon into the costs SC 
and PC. To fully treat the issue of when to rebalance requires analyzing the dynamic problem 
involving alphas, risks, and costs over time. There are some useful results from this general 
treatment, in the very simple case of one or two assets.
Leland (1996) solves the asset allocation problem of rebalancing around an optimal stock/bond 
allocation. Let's assume that the optimal allocation is 60/40. Assuming linear transactions costs and 
a utility function penalizing active variance (relative to the optimal allocation) and transactions costs 
over time, Leland shows that the optimal strategy involves a no-trade region around the 60/40 
allocation. If the portfolio moves outside that region, the optimal strategy is to trade back to the 
boundary. Trading only to the boundary, not to the target allocation, cuts the turnover and 
transactions costs roughly in half, with effectively no change in risk over time. The size of the notrade region depends on the transactions costs, the risk aversion, and the expected return and risk of 
stocks and bonds. Obviously, changing the size of the notrade region will change the turnover for 
the strategy.
This result concerns a problem that is much simpler than our general active portfolio management 
problem: The solved problem


---


### Page 396


Page 392
Figure 14.1 
After-cost information ratio for various half-lives.
is one-dimensional and does not involve the flow of information (the target allocation is static). Still, 
it is useful in motivating rebalancing rules driven not purely by the passage of time (e.g., monthly or 
quarterly rebalancing), but rather by the portfolio's falling outside certain boundaries.
Another approach to the dynamic problem utilizes information horizon analysis, introduced in Chap. 
13. Here we apply trading rules like Eq. (14.9) in the dynamic case of trading one position only, 
over an indefinite future,7 with information characterized by an information horizon. Figure 14.1 
shows how the after-cost information ratio declines as a function of both the (one-way) cost and the 
half-life of the signals. Two effects are at work. First, when we trade, we pay the costs. Second, and 
more subtle, the transactions costs makes us less eager; we lose by intimidation.
Techniques for Portfolio Construction
There are as many techniques for portfolio construction as there are managers. Each manager adds a 
special twist. Despite this personalized nature of portfolio construction techniques, there are
7There is a pleasant symmetry in this approach. Conventional portfolio optimization considers lots of assets in 
a one-period framework; we are considering one-asset (position) in a multiple-period framework.


---


### Page 397


Page 393
four generic classes of procedures that cover the vast majority of institutional portfolio management 
applications:8
• Screens
• Stratification
• Linear programming
• Quadratic programming
Before we examine these procedures in depth, we should recall our criteria. We are interested in 
high alpha, low active risk, and low transactions costs. Our figure of merit is value added less 
transactions costs:
We will see how each of these procedures deals with these three aspects of portfolio construction.
Screens
Screens are simple. Here is a screen recipe for building a portfolio from scratch:
1. Rank the stocks by alpha.
2. Choose the first 50 stocks (for example).
3. Equal-weight (or capitalization-weight) the stocks.
We can also use screens for rebalancing. Suppose we have alphas on 200 stocks (the followed list). 
Divide the stocks into three categories: the top 40, the next 60, and the remaining 100. Put any stock 
in the top 40 on the buy list, any stock in the bottom 100 on the sell list, and any stock in the middle 
60 on the hold list. Starting with the current 50-stock portfolio, buy any stocks that are on the buy 
list but not in the portfolio. Then sell any assets that are in
8The techniques we review successfully handle monthly or quarterly rebalancing of portfolios of up to 1000 
assets and asset universes that can exceed 10,000 for international investing. Later, we will discuss nonlinear 
programming and stochastic optimization, whose applications are generally limited to asset allocation schemes 
involving few (less than 25) asset classes and long planning horizons.


---


### Page 398


Page 394
the portfolio and on the sell list. We can adjust the numbers 40, 60, and 100 to regulate turnover.
Screens have several attractive features. There is beauty in simplicity. The screen is easy to 
understand, with a clear link between cause (membership on a buy, sell, or hold list) and effect 
(membership in the portfolio). The screen is easy to computerize; it might be that mythical computer 
project that can be completed in two days! The screen is robust. Notice that it depends solely on 
ranking. Wild estimates of positive or negative alphas will not alter the result.
The screen enhances alphas by concentrating the portfolio in the high-alpha stocks. It strives for risk 
control by including a sufficient number of stocks (50 in the example) and by weighting them to 
avoid concentration in any single stock. Transactions costs are limited by controlling turnover 
through judicious choice of the size of the buy, sell, and hold lists.
Screens also have several shortcomings. They ignore all information in the alphas apart from the 
rankings. They do not protect against biases in the alphas. If all the utility stocks happen to be low in
the alpha rankings, the portfolio will not include any utility stocks. Risk control is fragmentary at 
best. In our consulting experience, we have come across portfolios produced by screens that were 
considerably more risky than their managers had imagined. In spite of these significant 
shortcomings, screens are a very popular portfolio construction technique.
Stratification
Stratification is glorified screening. The term stratification comes from statistics. In statistics, 
stratification guards against sample bias by making sure that the sample population is representative 
of the total population as it is broken down into distinct subpopulations. The term is used very 
loosely in portfolio construction. When a portfolio manager says he uses stratified sampling, he 
wants the listener to (1) be impressed and (2) ask no further questions.
The key to stratification is splitting the list of followed stocks into categories. These categories are 
generally exclusive. The idea is to obtain risk control by making sure that the portfolio has a 
representative holding in each category. As a typical example, let's


---


### Page 399


Page 395
suppose that we classify stocks into 10 economic sectors and also classify the stocks in each sector 
by size: big, medium, and small. Thus, we classify all stocks into 30 categories based on economic 
sector and size. We also know the benchmark weight in each of the 30 categories.
To construct a portfolio, we mimic the screening exercise within each category. We rank the stocks 
by alpha and place them into buy, hold, and sell groups within each category in a way that will keep 
the turnover reasonable. We then weight the stocks so that the portfolio's weight in each category 
matches the benchmark's weight in that category. Stratification ensures that the portfolio matches 
the benchmark along these important dimensions.
The stratification scheme has the same benefits as screening, plus some. It is robust. Improving 
upon screening, it ignores any biases in the alphas across categories. It is somewhat transparent and 
easy to code. It has the same mechanism as screening for controlling turnover.
Stratification retains some of the shortcomings of a screen. It ignores some information, and does 
not consider slightly over-weighting one category and underweighting another. Often, little 
substantive research underlies the selection of the categories, and so risk control is rudimentary. 
Chosen well, the categories can lead to reasonable risk control. If some important risk dimensions 
are excluded, risk control will fail.
Linear Programming
A linear program (LP) is space-age stratification. The linear programming approach9 characterizes 
stocks along dimensions of risk, e.g., industry, size, volatility, and beta. The linear program does not 
require that these dimensions distinctly and exclusively partition the stocks. We can characterize 
stocks along all of these dimensions. The linear program will then attempt to build portfolios that 
are reasonably close to the benchmark portfolio in all of the dimensions used for risk control.
9A linear program is a useful tool for a variety of portfolio management applications. The application described 
here is but one of those applications.


---


### Page 400


Page 396
It is also possible to set up a linear program with explicit transactions costs, a limit on turnover, and 
upper and lower position limits on each stock. The objective of the linear program is to maximize 
the portfolio's alpha less transactions costs, while remaining close to the benchmark portfolio in the 
risk control dimensions.
The linear program takes all the information about alpha into account and controls risk by keeping 
the characteristics of the portfolio close to the characteristics of the benchmark. However, the linear 
program has difficulty producing portfolios with a prespecified number of stocks. Also, the riskcontrol characteristics should not work at cross purposes with the alphas. For example, if the alphas 
tell you to shade the portfolio toward smaller stocks at some times and toward larger stocks at other 
times, you should not control risk on the size dimension.
Quadratic Programming
Quadratic programming (QP) is the ultimate10 in portfolio construction. The quadratic program 
explicitly considers each of the three elements in our figure of merit: alpha, risk, and transactions 
costs. In addition, since a quadratic program includes a linear program as a special case, it can 
include all the constraints and limitations one finds in a linear program. This should be the best of 
all worlds. Alas, nothing is perfect.
One of the main themes of this chapter is dealing with less than perfect data. The quadratic program 
requires a great many more inputs than the other portfolio construction techniques. More inputs 
mean more noise. Does the benefit of explicitly considering risk outweigh the cost of introducing 
additional noise? A universe of 500 stocks will require 500 volatility estimates and 124,750 
correlation estimates.11 There are ample opportunities to make mistakes. It is a fear of garbage in, 
garbage out that deters managers from using a quadratic program.
10Given our criterion of portfolio alpha minus a penalty for active risk and less transactions costs.
11Chapter 3 discusses how to accurately approach this problem.


---

