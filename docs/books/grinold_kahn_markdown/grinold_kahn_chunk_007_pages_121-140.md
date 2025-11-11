# Grinold-Kahn Active Portfolio Management

## Pages 121-140


### Page 121


Page 113
The Ex Ante Information Ratio:
A Measure of Opportunity
Now we look to the future. The information ratio is the expected level of annual residual return per 
unit of annual residual risk. There is an implication that information is being used efficiently. Thus, 
the more precise definition of the information ratio is the highest ratio of annual residual return to 
residual risk that the manager can obtain.
Let's begin with the analysis for a start-up investment manager with no track record. We will then 
compare results with some empirical observations.
We first need a plausible value for the information ratio. Recall that this is an assumed can opener. 
Don't get carried away—we are making this number up; we don't need to be terribly precise.
This new manager must develop target expectations for residual risk and return. The risk target is 
less controversial. We will assume that the manager is aiming for the 5 to 6 percent residual risk 
range. We will use 5.5 percent for concreteness.
Now what about the expected residual return target? The answer here involves a struggle between 
those two titans: hope and humility. A truly humble (no better than average) active manager would 
say zero. That's not good enough. You can't be an active manager with that much humility. A very 
hopeful manager, indeed a dreamer, might say 10 percent. This quixotic manager is confusing what 
is possible with what can be expected.
In the end, the manager must confront both hope and humility. Let's say the manager is assuming 
between 3 and 4 percent, or 3.5 percent, to pick a number.
Our ex ante information ratio is 3.5/5.5 = 0.64. We have found our way to a sensible number. This 
analysis is intentionally vague. We don't care if the answer came out 0.63 or 0.65. This is not the 
time for spurious precision. Our analysis produced residual risk in the 5 to 6 percent range and 
expected (hoped-for) residual returns in the 3 to 4 percent range. In the extreme cases, we could 
have obtained an answer between 0.8 = 4/5 and 0.5 = 3/6.
So far, we have not revealed any empirically observed information ratios. The empirical results will 
vary somewhat by time period, by asset class, and by fee level. But overall, before-fee information 
ratios typically fall close to the distribution in Table 5.1.


---


### Page 122


Page 114
TABLE 5.1
Percentile
Information Ratio
90
1.0
75
0.5
50
0.0
25
–0.5
10
–1.0
A top-quartile manager has an information ratio of one-half. That's a good number to remember. Ex 
ante, investment managers should aspire to top-quartile status. Our analysis of a start-up investment 
manager's information ratio, which we estimated at 0.64, provided a reasonable ballpark estimate, 
consistent with Table 5.1.
Table 5.1 displays a symmetric distribution of information ratios, centered on zero. This is 
consistent with our fundamental understanding of active management as a zero-sum game.
Table 5.1 also implies that if IR = 0.5 is good, then IR = 1.0 is exceptional. We will further define 
IR = 0.75 as very good and use that simple classification scheme throughout the book. Later in this 
chapter, we will provide more details on empirical observations of information ratios, as well as on 
active returns and active risk.
We will now define the information ratio in a more formal manner. Given an alpha for each stock, 
any (random) portfolio P will have a portfolio alpha αP and a portfolio residual risk ωP. The 
information ratio for portfolio P is
Our personal "information ratio" is the maximum information ratio that we can attain over all 
possible portfolios:
So we measure our information ratio based on portfolios optimized to our alphas.


---


### Page 123


Page 115
The notation IR hides the fact that the information ratio depends on the alphas. Indeed, one of the 
uses of the information ratio concept is to scale the alphas so that a reasonable value of IR is 
obtained through Eq. (5.6).
Our definition of the information ratio says that a manager who can get an expected residual return 
of 2 percent with 4 percent residual risk can also get an expected residual return of 3 percent with 6 
percent residual risk. The ratio of risk to return stays constant and equal to the information ratio 
even as the level of risk changes. A small example will indicate that this is indeed the case.
We consider four stocks, cash, and a benchmark portfolio that is 25 percent in each of the stocks. 
Table 5.2 summarizes the situation. The alphas for both the benchmark portfolio (the weighted sum 
of the stock alphas) and cash are, of course, equal to zero. This is no accident.
The last four columns describe two possible portfolios, P and L. For each portfolio, we have shown 
the portfolio's total and active holdings. The active holdings are simply the portfolio holdings less 
the benchmark holdings. In portfolio P, we have positive active positions for the two stocks with 
positive alphas, and negative active positions for the stocks with negative alphas. Since the alpha for 
the benchmark is zero, we can calculate the alpha
TABLE 5.2
Stock
Alpha
Benchmark 
Weight
Portfolio P
Total 
Weight
Portfolio P
Active 
Weight
Portfolio L
Total 
Weight
Portfolio L 
Active 
Weight
1
1.50%
25.00%
35.00%
10.00%
40.00%
15.00%
2
–2.00%
25.00%
10.00%
–15.00%
2.50%
–22.50%
3
1.75%
25.00%
40.00%
15.00%
47.50%
22.50%
4
–1.25%
25.00%
15.00%
–10.00%
10.00%
–15.00%
Benchmark
0.00%  

Cash
0.00%


---


### Page 124


Page 116
for the portfolio using only the active holdings.2 The alpha for portfolio P is
The risk of this active position is 2.04 percent.3
Notice that portfolio L is just a more aggressive version of portfolio P. This isn't clear when we look 
at the holdings in portfolio L, but it is obvious when we look at the active holdings. The active 
holdings of portfolio L are 50 percent greater than the active holdings of portfolio P. For stock 1, 
our active position goes from +10 percent to +15 percent. For stock 2, our active position goes from 
–15 percent to –22.5 percent. In both cases, the active position increases by 50 percent. This means 
that the alpha for portfolio L must be 50 percent larger as well, and that the active risk is also 50 
percent higher.4 If both the portfolio alpha and the residual risk increase by 50 percent, the ratio of 
the two will remain the same.
The information ratio is independent of the manager's level of aggressiveness.
We will consistently assume that the information ratio is independent of the level of risk. This 
relationship eventually breaks down in real-world applications, because of constraints. So in Table 
5.2, if there is a constraint on short selling, we have little additional room to bet against stock 2 
beyond portfolio L. Chapter 15, "Long/Short Investing," expands on this idea, estimating a cost for 
the no short selling constraint based on the effective reduction in information ratio.
Although the information ratio is independent of the level of aggressiveness, it does depend on the 
time horizon. In order to
2The portfolio holdings are hP = hB + hPA, where hB and hPA are benchmark and active holdings. If α is a vector 
of alphas, then αT · hB = 0 implies αT · hP = αT · hPA.
3Table 5.2 doesn't contain the information necessary to calculate this. But see Chap. 4 for the definition of active 
risk and the procedure for calculating active risk. If V is the covariance matrix, and hP and hB are the holdings in 
the managed and benchmark portfolios, respectively, then hPA = hP – hB contains the active holdings and 
 is the active variance.
4If the active holdings change from hPA to φ · hPA, then the active risk changes from ψP 
to


---


### Page 125


Page 117
avoid confusion, we standardize by using a 1-year horizon. The reason is that expected returns and 
variances both tend to grow with the length of the horizon. Therefore risk, standard deviation, will 
grow as the square root of the horizon, and the ratio of expected return (growing with time) to risk 
(growing as the square root of time) will increase with the square root of time. That means that the 
quarterly information ratio is half as large as the annual information ratio. The monthly information 
ratio would be 
 the size of the annual information ratio.
The Residual Frontier: 
The Manager's Opportunity Set
The choices available to the active manager are easier to see if we look at the alpha versus residual 
risk trade-offs. The residual frontier will describe the opportunities available to the active manager. 
The ex ante information ratio determines the manager's residual frontier.
In Fig. 5.1 we have the residual frontier for an exceptional manager with an information ratio of 1. 
This residual frontier plots expected residual return αP, against residual risk ωP. The residual frontier 
is a straight line through the origin. Notice that portfolio Q is on the frontier. Portfolio Q is a 
solution to Eq. (5.6); i.e., IR = IRQ. Portfolio Q is not alone on the residual frontier. The
Figure 5.1 
The residual frontier.


---


### Page 126


Page 118
portfolios P1, P2, up to P6 are also on the residual frontier. The manager can attain any expected 
residual return and residual risk combination below the frontier line. Portfolios P1 through P6 have 
(respectively) 1 percent to 6 percent expected residual return and residual risk.
The origin, designated B, represents the benchmark portfolio. The benchmark, by definition, has no 
residual return, and thus both αB and ωB are equal to zero. Likewise, the risk-free asset will reside at 
the origin, since the risk-free asset also has a zero residual return.
In Fig. 5.2 we show the residual frontiers of three different managers. The good manager has an 
information ratio of 0.5, the very good manager has an information ratio of 0.75, and the exceptional 
manager has an information ratio of 1.00.
We can see from Fig. 5.2 that the information ratio indicates opportunity. The manager with an 
information ratio of 0.75 has choices—portfolio P1, for example—that are not available to the 
manager with an information ratio of 0.5. Similarly, the exceptional manager has opportunities—at 
point P2, for example—that are not available to the very good manager. This doesn't mean that the 
very good manager cannot hold the stocks in portfolio P2. It does mean that this very good 
manager's information will not lead him or her to that portfolio; it will, instead, lead this manager to 
a portfolio like P1 that is on his or her residual frontier.
Figure 5.2 
Opportunities.


---


### Page 127


Page 119
Effectively, the information ratio defines a "budget constraint" for the active manager, as depicted 
graphically by the residual frontier:
At best (i.e., along the frontier), the manager can increase the expected residual return only through 
a corresponding increase in residual risk.
The appendix contains a wealth of technical detail about information ratios. We now turn our 
attention from the manager's opportunities to her or his objectives.
The Active Management Objective
The objective of active management (derived in Chap. 4) is to maximize the value added from 
residual return, where value added is measured as5
This objective awards a credit for the expected residual return and a debit for residual risk. The 
parameter λR measures the aversion to residual risk; it transforms residual variance into a loss in 
alpha. In Fig. 5.3 we show the loss in alpha for different levels of residual risk. The three curves 
show high (λR = 0.15), moderate (λR = 0.10), and low (λR = 0.05) levels of residual risk aversion. In 
each case, the loss increases with the square of the residual risk ωP. For a residual risk of ωP = 5%, 
the losses are 3.75 percent, 2.5 percent, and 1.25 percent, respectively, for the high, moderate, and 
low levels of residual risk aversion.
The lines of equal value added, plotted as functions of expected residual return αP and residual risk 
ωP, are parabolas. In Fig. 5.4 we have plotted three such parabolas for value added of 2.5 percent, 
1.4 percent, and 0.625 percent. These curves are of the form 
, 
and 
. The figure shows the situation when we have a moderate level of residual
5We are ignoring benchmark timing, so active return equals residual return and active risk equals residual risk.


---


### Page 128


Page 120
Figure 5.3 
Loss in alpha.
risk aversion λR = 0.10. The three parabolas are parallel and increasing to the right. Every point 
along the top curve has a value added of 2.5 percent. The point {α = 2.5 percent, ω = 0 percent} and 
the point {α = 4.1 percent, ω = 4 percent} are on this curve. At the first point, with zero residual risk 
and an alpha of 2.5 percent, we have a value added of 2.5 percent. At the second point, the value 
added is still 2.5 percent, although we have risk. Thus, with ω = 4 percent and α = 4.1 percent, we 
have VA = 2.5 = 4.1 – (0.1) · 42.
Figure 5.4 
Constant value added lines.


---


### Page 129


Page 121
We sometimes refer to the value added as the certainty equivalent return. Given a risk aversion λR, 
the investor will equate return αP and risk ωP with a certain return 
 to a (residual) riskfree investment.
Preferences Meet Opportunities
It is a basic tenet of economics that people prefer more to less. Our choices are limited by our 
opportunities. We have to choose in a manner that is consistent with our opportunities. The 
information ratio describes the opportunities open to the active manager. The active manager should 
explore those opportunities and choose the portfolio that maximizes value added.
Figure 5.5 shows the situation. The residual frontier corresponds to an information ratio of 0.75 and 
a residual risk aversion of λR = 0.1. Preferences are shown by the three preference curves, with riskadjusted returns of 0.625 percent, 1.40 percent, and 2.5 percent, respectively.
We would like to have a risk-adjusted return of 2.5 percent. We can't do that well. The VA = 2.5 
percent curve lies above the residual frontier. Life is a bit like that. We can achieve a risk-adjusted
Figure 5.5


---


### Page 130


Page 122
return of 0.625 percent. A value added of 0.625 percent is consistent with our opportunities; 
however, we can do better. Portfolio P0 is in the opportunity set and is better than 0.625 percent.
The 1.40 percent curve is just right. The 1.4 percent value added curve is tangent to the residual 
frontier at portfolio P*. We can't do any better, since every higher-value added line is outside the 
opportunity set. Therefore, portfolio P* is our optimal choice.
Aggressiveness, Opportunity, and Residual Risk Aversion
The manager's information ratio and residual risk aversion determine a simple rule that links those 
concepts with the manager's optimal level of residual risk or aggressiveness. We can discover the 
rule through a more formal examination of the graphical analysis carried out in the last section.
The manager will want to choose a portfolio6 on the residual frontier. The only question is the 
manager's level of aggressiveness. Using the ''budget constraint" [Eq. (5.7)] in the manager's 
objective, Eq. (5.8), we find
Now we have completely parameterized the problem in terms of risk. As we increase risk, we 
increase expected return and we increase the penalty for risk. Figure 5.6 shows the situation, 
representing the median case with IR = 0.75 and λR = 0.10.
The optimal level of residual risk, ω*, which maximizes VA [ωP] is
This is certainly a sensible result. Our desired level of residual risk will increase with our 
opportunities and decrease with our residual risk aversion. Doubling the information ratio will 
double the opti6The formal problem is to maximize α – λ · ω2, subject to the constraint α/ω ≤ IR. Since we know that the 
constraint will be binding at the optimal solution, we can use it to eliminate α from the objective.


---


### Page 131


Page 123
Figure 5.6
mal risk level. Doubling the risk aversion will halve the optimal risk level.
Table 5.3 shows how the residual risk will vary for reasonable values of the information ratio and 
residual risk aversion. The information ratio has three possible levels: 0.50 (good), 0.75 (very good), 
and 1.0 (exceptional). The residual risk aversion also has three possible levels: 0.05 (aggressive), 0.1 
(moderate), and 0.15 (restrained).
The highest level of aggressiveness is 10 percent, corresponding to the low residual risk aversion (λR
= 0.05) and the high information ratio (IR = 1.00). At the other corner, with fewer opporTABLE 5.3 
Residual Risk
IR
Risk Aversion λ
Aggressive (0.05)
Moderate 
(0.10)
Restrained 
(0.15)
Exceptional 
(1.00)
10.00%
5.00%
3.33%
Very good (0.75)
7.50%
3.75%
2.50%
Good (0.50)
5.00%
2.50%
1.67%


---


### Page 132


Page 124
tunities (IR = 0.50) and more restraint (λR = 0.15), we have an annual residual risk of 1.67 percent. 
Table 5.3 is quite useful; it allows a manager to link two alien concepts, the information ratio and 
residual risk aversion, to the more specific notion of the amount of residual risk in the portfolio. We 
see that the greater our opportunities, the higher the level of aggressiveness, and the lower the 
residual risk aversion, the greater the level of aggressiveness. The table also helps us calibrate our 
sensibilities as to reasonable levels of IR and λR. Equation (5.10) will tell us if any suggested levels 
of IR and λR are reasonable.
It is possible to turn the question around and use Eq. (5.10) to determine a reasonable level of 
residual risk aversion. Recall the information ratio analysis earlier in the chapter. We determined 
that the manager wanted 5.5 percent residual risk and had an information ratio of 0.64. We can 
rearrange Eq. (5.10) and extract an implied level of residual risk aversion:
For our example, we have 0.64/ (2 · 5.5) = 0.058. The manager is aggressive, with risk aversion at 
the lower end of the spectrum.
Value Added: 
Risk-Adjusted Residual Return
We have located the optimal portfolio P* at the point where the residual frontier is tangent to a 
preference line, and we have found a simple expression for the level of residual risk for the optimal 
portfolio. In this section, we will go one step further and determine the risk-adjusted residual return 
of the optimal portfolio P*.
If we substitute the optimal level of residual risk [Eq. (5.10)] into Eq. (5.9), we find the relationship 
between the value added as measured by utility and the manager's opportunity as measured by the 
information ratio IR:
This says that the ability of the manager to add value increases as the square of the information ratio 
and decreases as the manager


---


### Page 133


Page 125
becomes more risk-averse. So a manager's information ratio determines his or her potential to add 
value.
Equation (5.12) states a critical result. Imagine we are riskverse investors, with high λR. According 
to Equation (5.12), given our λR, we will maximize our value added by choosing the investment 
strategy (or manager) with the highest IR. But a very risk-tolerant investor will make exactly the 
same calculation. In fact, every investor seeks the strategy or manager with the highest information 
ratio. Different investors will differ only in how aggressively they implement the strategy.
The Information Ratio is the Key to Active Management
Table 5.4 shows the value added for the same three choices of information ratio and residual risk 
aversion used in Table 5.3. In our best case, the value added is 5.00 percent per year. That is 
probably more than one could expect. In the worst case, the value added is 42 basis points per year. 
A good manager (IR = 0.50) with a conservative implementation (λR = 0.15, so ω* = 1.66) will 
probably not add enough value to justify an active fee.
In our initial analysis of a manager's information ratio, we found IR = 0.64 and λR = 0.058, and so 
the value added is 1.77 percent per year.
The β = 1 Frontier
How do our residual risk/ return choices look in the total risk/ total return picture? The portfolios we 
will select (in the absence
TABLE 5.4 
Value Added
IR
Risk Aversion λR
Aggressive (0.05)
Moderate 
(0.10)
Restrained 
(0.15)
Exceptional 
(1.00)
5.00%
2.50%
1.67%
Very good (0.75)
2.81%
1.41%
0.94%
Good (0.50)
1.25%
0.63%
0.42%


---


### Page 134


Page 126
of any benchmark timing) will lie along the β = 1 frontier. This is the set of all portfolios with beta 
equal to 1 that are efficient; i.e., they have the minimum risk for a specified level of expected return. 
They are not necessarily fully invested. We develop this concept more fully in the technical 
appendix.
Figure 5.7 compares different efficient frontiers. The efficient frontier is the straight line through F 
and Q. The efficient frontier for fully invested portfolios starts at C and runs through Q. The 
efficient frontier for portfolios with beta equal to 1 starts at the benchmark, B, and runs through P.
The benchmark is the minimum-risk portfolio with β = 1, since it has zero residual risk. All other β 
= 1 portfolios have the same systematic risk, but more residual risk.
A glance at Fig. 5.7 may make us rethink our value added objective. There are obviously portfolios 
that dominate the β = 1 frontier. However, these portfolios have a large amount of active risk, and 
therefore expose the manager to the business risk of poorrelative performance.
Figure 5.7


---


### Page 135


Page 127
Figure 5.8
These two frontiers cross at the point along the fully invested frontier with β = 1. This crossing point 
will typically involve high levels of residual risk.
If we require our portfolios to satisfy a no active cash condition, then we have the situation shown in 
Fig. 5.8. The β = 1 no active cash frontier is the parabola centered on the benchmark portfolioB and 
passing through the portfolio Y. This efficient frontier combines the restriction to full investment 
(assuming that the benchmark is fully invested) with the β = 1 restriction. The opportunities without 
the no active cash restriction dominate those with the restriction. A constraint reduces our 
opportunities.
Forecast Alphas Directly!
We have decided to manage relative to a benchmark and (at least until Chap. 19) to forgo 
benchmark timing. We have a need for alphas. We will discuss this topic at great length in the 
remainder of the book. However, we would like to show at this early stage that it isn't very hard to 
produce a rudimentary set of alphas with


---


### Page 136


Page 128
a small amount of work. One way to get these alphas is to start with expected returns and then go 
through the complicated procedure described in Chap. 4. An alternative is to skip the intermediate 
steps and forecast the alphas directly. In fact, one of the goals of developing the active management 
machinery is to avoid having to forecast several quantities (like the expected return to the 
benchmark) which probably will not ultimately influence our portfolio. Here, then, is a reasonable 
example of what we mean, converting a simple ranking of stocks into alpha forecasts. To start, sort 
the assets into five bins: strong buy, buy, hold, sell, and strong sell. Assign them respective alphas 
of 2.00 percent, 1.00 percent, 0.00 percent, –1.00 percent, and –2.00 percent. Then find the 
benchmark average alpha. If it is zero, we are finished. If it isn't zero (and there is no guarantee that 
it will be), modify the alphas by subtracting the benchmark average times the stock's beta from each 
original alpha.
These alphas will be benchmark-neutral. In the absence of constraints, they should lead7 the 
manager to hold a portfolio with a beta of 1.00. One can imagine more and more elaborate 
variations on this theme. For example, we could classify stocks into economic sectors and then sort 
them into strong buy, buy, hold, sell, and strong sell bins.
This example illustrates two points. First, we need not forecast alphas with laserlike precision. We 
will see in Chap. 6, "The Fundamental Law of Active Management," that the accuracy of a 
successful forecaster of alphas is apt to be fairly low. Any procedure that keeps the process simple 
and moving in the correct direction will probably compensate for losses in accuracy in the second 
and third
7The manager's objective is to maximize 
. In the absence of constraints, the optimal 
solution, call it 
 will satisfy 
 If we multiply these first-order conditions by the 
benchmark weights hB, and recall that 
, and αB = 0, we find


---


### Page 137


Page 129
decimal places. Second, although it may be difficult to forecast alphas correctly, it is not difficult to 
forecast alphas directly.
Empirical Observations
This section looks in more detail at the empirical results concerning active manager information 
ratios and risk.
Earlier, we described the "generic" distribution of before-fee information ratios. This generic 
distribution seems to apply across many different asset classes, stocks to bonds to international. 
Here we will present some of the empirical observations underlying the generic result.
These results were produced and partly described in Kahn and Rudd (1995, 1997). They arise from 
analysis of active U.S. domestic equity and bond mutual funds and institutional portfolios. These 
empirical studies utilized style analysis, which we describe in Chap. 17, "Performance Analysis." 
Suffice it to say that this analysis allows us to estimate several empirical distributions of interest 
here. Table 5.5 briefly describes the data underlying the results that follow. The time periods 
involved are admittedly short, in part because style analysis requires an extensive in-sample period 
to determine a custom benchmark for each fund. The good news is that these are out-of-sample 
results. The bad news is that they do not cover an extensive time period.
The short time period will not bias the median estimates, but the large sample errors associated with 
the short time period will
TABLE 5.5
Study
Number of 
Funds
Calculation Time Period
U.S. active equity mutual funds
300
January 1991–December 1993
U.S. active equity institutional 
portfolios
367
October 1995–December 1996
U.S. active bond mutual funds
195
April 1993–September 1994
U.S. active bond institutional 
portfolios
215
October 1995–December 1996


---


### Page 138


Page 130
TABLE 5.6 
Information Ratios, U.S. Active Equity Investments
Percentile
Mutual Funds
Institutional Portfolios
Before Fees
After Fees
Before Fees
After Fees
90
1.33
1.08
1.25
1.01
75
0.78
0.58
0.63
0.48
50
0.32
0.12
–0.01
–0.15
25
–0.08
–0.33
–0.56
–0.72
10
–0.47
–0.72
–1.03
–1.25
broaden the distributions.8 The problem is more severe for institutional portfolios, where we have 
only quarterly return data, and hence a smaller number of observations.
Tables 5.6 and 5.7 display empirical distributions of information ratios for equity and bond 
investors, respectively. These tables generally support the generic distribution of Table 5.1, 
especially considering that all empirical results will depend on time period, analysis methodology, 
etc.
TABLE 5.7 
Information Ratios, U.S. Active Bond Investments
 
Mutual Funds
Institutional Portfolios
Percentile
Before Fees
After Fees
Before Fees
After Fees
90
1.14
0.50
1.81
1.29
75
0.50
–0.22
0.89
0.38
50
–0.11
–0.86
0.01
–0.57
25
–0.61
–1.50
–0.62
–1.37
10
–1.22
–2.21
–1.50
–2.41
8In the extreme, imagine a sample of 300 funds, each with true IR = 0. We will observe a distribution of sample 
information ratios. It may well center on IR = 0, but that distribution will shrink toward zero only as we 
increase our observation period.


---


### Page 139


Page 131
For equity investors, the empirical data show that top-quartile investors achieve information ratios 
of 0.63 to 0.78 before fees and 0.58 to 0.48 after fees. Given the standard errors for these results of 
roughly 0.05, and the fact that estimation errors tend to broaden the distribution, these empirical 
results are roughly consistent with Table 5.1.
The before-fee data on bond managers look roughly similar to the equity results, with top-quartile 
information ratios ranging from 0.50 to 0.89. The after-fee results differ strikingly from the equity 
manager results. For more on this phenomenon, see Kahn (1998).
Overall, given these empirical results, Table 5.1 appears to be a very good ex ante distribution of 
information ratios, before fees.
We can also look at distributions of active risk. Tables 5.8 and 5.9 show the distributions. Active 
managers should find this risk information useful: It helps define manager aggressiveness relative to 
the broad universe of active managers.
For equity managers, median active risk falls between 4 and 5 percent. Mutual fund risk resembles 
institutional portfolio risk, except at the low-risk end of the spectrum, where institutional managers 
offer lower-risk products.
For active domestic bond managers, the risk distributions vary between mutual funds and 
institutional portfolios, although both are well below the active equity risk distribution. Median 
active risk is 1.33 percent for bond mutual funds and only 0.61 percent for institutional bond 
portfolios.
TABLE 5.8 
Annual Active Risk, U.S. Active Equity Investments
Percentile
Mutual Funds
Institutional Portfolios
90
9.87%
9.49%
75
7.00%
6.47%
50
4.76%
4.39%
25
3.66%
2.85%
10
2.90%
1.93%


---


### Page 140


Page 132
TABLE 5.9 
Annual Active Risk, U.S. Active Bond Investments
Percentile
Mutual Funds
Institutional Portfolios
90
3.44%
1.89%
75
2.01%
0.98%
50
1.33%
0.61%
25
0.96%
0.41%
10
0.74%
0.26%
Summary
We have built a simple framework for the management of residual risk and return. There are two 
key constructs in this framework:
• The information ratio as a measure of our opportunities
• The residual risk aversion as a measure of our willingness to exploit those opportunities
These two constructs determine our desired level of residual risk [Eq. (5.10)] and our ability to add 
value [Equation (5.12)]. In the next chapter, we will push this analysis further to uncover some of 
the structure that leads to the information ratio.
Problems
1. What is the information ratio of a passive manager?
2. What is the information ratio required to add a risk-adjusted return of 2.5 percent with a moderate 
risk aversion level of 0.10? What level of active risk would that require?
3. Starting with the universe of MMI stocks, we make the assumptions
Q = MMI portfolio
fQ = 6%
B = capitalization-weighted MMI portfolio


---

