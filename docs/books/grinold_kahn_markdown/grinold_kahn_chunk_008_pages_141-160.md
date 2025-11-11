# Grinold-Kahn Active Portfolio Management

## Pages 141-160


### Page 141


Page 133
We calculate (as of January 1995) that
Portfolio
β with Respect to B
β with Respect to Q
σ
B
1.000
0.965
15.50%
Q
1.004
1.000
15.82%
C
0.865
0.831
14.42%
where portfolio C is the minimum-variance (fully invested) portfolio. For each portfolio (Q, B, and 
C), calculate f, α, ω, SR, and IR.
4. You have a residual risk aversion of λR = 0.12 and an information ratio of IR = 0.60. What is your 
optimal level of residual risk? What is your optimal value added?
5. Oops. In fact, your information ratio is really only IR = 0.30. How much value added have you 
lost by setting your residual risk level according to Problem 4 instead of at its correct optimal level?
6. You are an active manager with an information ratio of IR = 0.50 (top quartile) and a target level 
of residual risk of 4 percent. What residual risk aversion should lead to that level of risk?
References
Ambachtsheer, Keith. ''Where are the Customer's Alphas?" Journal of Portfolio Management, vol. 
4, no. 1, Fall 1977, pp. 52–56.
Goodwin, Thomas H. "The Information Ratio." Financial Analysts Journal, vol. 54, no. 4, 
July/August 1998, pp. 34–43.
Kahn, Ronald N. "Bond Managers Need to Take More Risk." Journal of Portfolio Management, 
vol. 24, no. 3, Spring 1998, pp. 70–76.
Kahn, Ronald N., and Andrew Rudd. "Does Historical Performance Predict Future Performance?" 
Financial Analysts Journal, vol. 51, no. 6, November/December 1995, pp. 43–52.
———. "The Persistence of Equity Style Performance: Evidence from Mutual Fund Data." In The 
Handbook of Equity Style Management, 2d ed., edited by Daniel T. Coggin, Frank J. Fabozzi, and 
Robert Arnott (New Hope, PA: Frank J. Fabozzi Associates), 1997, pp. 257–267.
———. "The Persistence of Fixed Income Style Performance: Evidence from Mutual Fund Data." 
In Managing Fixed Income Portfolios, edited by Frank J. Fabozzi (New Hope, PA: Frank J. Fabozzi 
Associates), 1997, pp. 299–307.


---


### Page 142


Page 134
Roll, Richard. "A Mean/Variance Analysis of Tracking Error." Journal of Portfolio Management, 
vol. 18, no. 4, Summer 1992, pp. 13–23.
Rosenberg, Barr. "Security Appraisal and Unsystematic Risk in Institutional 
Investment."Proceedings of the Seminar on the Analysis of Security Prices (Chicago: University of 
Chicago Press), November 1976, pp. 171–237.
Rudd, Andrew, and Henry K. Clasing, Jr. Modern Portfolio Theory, 2d ed.. (Orinda, Calif.: Andrew 
Rudd, 1988).
Sharpe, William F. "The Sharpe Ratio." Journal of Portfolio Management, vol. 21, no. 1, Fall 1994, 
pp. 49–59.
Treynor, Jack, and Fischer Black. "How to Use Security Analysis to Improve Portfolio Selection." 
Journal of Business, vol. 46, no. 1, January 1973, pp. 66–86.
Technical Appendix
The Characteristic Portfolio of Alpha
Our basic input is a vector of asset alphas: α = {α1, α2, . . . , αN}. The alpha for asset n is a forecast 
of asset n's expected residual return, where we define residual relative to the benchmark portfolio. 
Since the alphas are forecasts of residual return, both the benchmark and the risk-free asset will have 
alphas of zero; i.e., αB = αF = 0.
The characteristic portfolio of the alphas (see the appendix to Chap. 2) will exploit the information 
as efficiently as possible. Call portfolio A the characteristic portfolio of the alphas:
Portfolio A has an alpha of 
, and it has minimum risk among all portfolios with that 
property. The variance of portfolioA is
In addition, we can define alpha in terms of Portfolio A:


---


### Page 143


Page 135
Information Ratios
For any portfolio P with ωP > 0, define IRP as
If ωP = 0, we set IRP = 0. We call IRP the information ratio of portfolio P. We define the information 
ratio IR as the largest possible value of IRP given alphas {αn}, i.e.,
In the technical appendix to Chap. 2, we identified portfolio Q as the fully invested portfolio with 
the maximum Sharpe ratio, the ratio of expected excess return per unit of risk. Portfolio Q 
maximizesfP/σP over all portfolios P. In this appendix, we will establish a link between portfolio Q, 
portfolio A, and the information ratio.
Portfolio A has the following list of interesting properties.
Proposition 1
1. Portfolio A has a zero beta; βA = βT · hA = 0. It therefore typically has long and short positions.
2. Portfolio A has the maximum information ratio:
3. Portfolio A has total and residual risk equal to 1 divided by IR:
4. Any portfolio P that can be written as
has IRP = IR.


---


### Page 144


Page 136
5. Portfolio Q is a mixture of the benchmark and portfolio A:
Therefore IRQ = IR. The information ratio of portfolio Q equals that of portfolio A.
6. Total holdings in risky assets for Portfolio A are
7. Let θP be the residual return on any portfolio P. The information ratio of portfolio P is
8. The (maximum) information ratio is related to portfolio Q's (maximum) Sharpe ratio:
9. We can represent alpha as
Equation (5A.15) is an important result. It directly relates alphas to marginal contributions to 
residual risk, with the information ratio as the constant of proportionality. Thus, active managers 
should always check the marginal contributions to residual risk within their portfolios. For example, 
if they have an information ratio of 0.5, then half the marginal contributions should equal their 
alphas. This is a very useful check, especially on portfolios constructed by hand (as opposed to 
using an optimizer).


---


### Page 145


Page 137
10. The Sharpe ratio of the benchmark is related to the maximal information ratio and Sharpe ratio:
Proof
We verify the properties directly.
For item 1, recall from the appendix to Chap. 2 that since hB is the characteristic portfolio of beta 
and hA is the characteristic portfolio of alpha, we have 
. Thus αB = 0 implies 
βA = 0. It isn't surprising that αB = 0. The characteristic portfolio for beta has minimum risk given β 
= 1. It has zero residual risk, and hence zero alpha. Portfolio A has minimum risk given α = 1. Since 
it bets on residual returns, we would expect it to have minimum systematic risk, i.e., β = 0.
For item 2, consider any portfolio L with holdings hL. For any βP and scalar κ > 0, we can construct 
another portfolio P with holdings
The residual holdings of P and L are proportional. Thus αP = κ · αL and ωP = κ · ωL and IRL = IRP. 
When looking for a portfolio with a maximum information ratio, we might as well restrict ourselves 
to portfolios with beta of 0 and alpha of 1. Portfolio A has minimum risk among all such portfolios; 
therefore A has the maximum information ratio.
We can verify item 3 using Eq. (5A.2) and (5A.6), and the fact that βA = 0.
We can verify item 4 using Eq. (5A.17), with L equal to A and κ = αP > 0.
For item 5, write the expected excess returns as


---


### Page 146


Page 138
since Q is proportional to the characteristic portfolio of f. Equating Eqs. (5A.18) and (5A.19) and 
multiplying by V-1, leads to
Premultiplying by 
, and recalling that σA = ωA, leads to
This verifies Eqs. (5A.9) through (5A.11), and item 4 tells us that IRQ = IR.
We can verify item 6 by using the fact that portfolio C is the characteristic portfolio of e, the vector 
of all ones. Hence we have 
.
To verify item 7, for any portfolio P, we can write
Since portfolio A has a beta of 0, we can write
where θP and θA are the residual returns on portfolios P and A. If we divide Eq. (5A.22) by the 
residual risk of portfolio P, ωP, we find
Notice that θQ = αQ · θA, so the residual returns on portfolios A and Q are perfectly correlated, and 
thus Corr{θP,θA} = Corr{θP,θQ}.
For item 8, start with Eq. (5A.11) and divide both sides by αQ. Then use the facts that ωQ = αQ · ωA, 
SR = fQ/σQ, and IR = 1/ωA.
We can prove the first part of item 9 by using Eq. (5A.3) and the fact that IR = 1/ωA. The marginal 
contribution to residual risk of asset n in portfolio Q is Cov{θQ,θn}/ωQ. However, the residual 
holdings of portfolio Q are αQ · hA, and the residual risk of portfolio Q is ωQ = αQ · ωA. Thus, V · 
hA/ωA = MCRRQ.
To prove item 10, recall that SR2 = fT · V-1 · f and f = β · ·fB + α. Then use βT · V-1 · α = 0, which is 
just βA = 0, IR2 = αT ·


---


### Page 147


Page 139
V-1 · α, and 
. The last relationship follows since the benchmark is 
the characteristic portfolio of beta (see the appendix to Chap. 2).
Optimal Policy and Optimal Value Added
Portfolio A is key to the problem of finding an optimal residual position. Consider the problem
Proposition 2
The optimal solutions to Eqs. (5A.25) are given by
where βP is arbitrary.
The value added by the optimal solution is
and the residual volatility of the optimal solution is
Proof
The first-order conditions for the problem in Eq. (5A.25) are
A solution is optimal if and only if hP solves Eq. (5A.29). Let βP = βT · hP. This yields
Now substitute for alpha using Eq. (5A.3) and for 
 with V · hB. The result is
Multiply Eq. (5A.31) by V-1, and divide by 2 · λR. This yields Eq.


---


### Page 148


Page 140
(5A.26). Equation (5A.28) follows, since hA/ωA has residual volatility equal to 1. For Eq. (5A.27), 
substitute the optimal solution, Eq. (5A.26), in the objective and gather terms.
Notice that hP will have beta equal to βP, so we are consistent. It should be obvious that beta is 
irrelevant for the problem in Eq. (5A.26). The alphas are benchmark-neutral, so the alpha part of the 
objective in Eq. (5A.26) does not change as the portfolio's beta changes. Also, the residual risk is 
independent of the portfolio beta, and so ωP will be independent of βP as well.
The β = 1 Active Frontier
Our analysis to this point will let us specify the set of efficient portfolios that are constrained to have 
beta equal to 1, a fixed level of expected return, and minimal risk. These are interesting portfolios 
for institutional active managers. (There is a reason that we have relegated benchmark timing to the 
end of the book.) Since we will require beta equal to 1, the risk and expected return will be given by
The benchmark is the minimum-variance portfolio with beta equal to 1. The benchmark is the hinge 
in the β = 1 frontier in the same way that portfolio C is the hinge for the frontier of fully invested 
portfolios. To be on the β = 1 frontier, a portfolio must have a beta equal to 1 and a minimal amount 
of residual risk per unit of alpha. These will be portfolios on the alpha/residual risk efficient frontier, 
with ratios of alpha to residual risk equal to the information ratio. The residual variance is given by
When we combine these last three equations, we have the equation for the β = 1 frontier:


---


### Page 149


Page 141
The Active Position Y: 
No Active Cash and No Active Beta
Portfolio A is the minimum-variance portfolio that has a unit exposure to alpha. However, it may 
turn out that portfolio A has a large positive or negative cash exposure. In active management, we 
often wish to move away from our benchmark and toward an efficient implementation of our alphas, 
while assuming no active cash position or active beta. But from item 6 of Proposition 1, we see that 
eA = 0 if and only if αC = 0. Here we will introduce a new portfolio, portfolio Y, and discuss its 
properties. In the next section we will show that portfolio Y is the solution to the problem of 
optimizing our alphas subject to active cash and beta constraints.
To begin, define the residual holdings of portfolio C as
Portfolio Y is a combination of portfolio A and portfolio CR:
Proposition 3
Portfolio Y has the following properties:
1. Portfolio Y has a zero beta; βY = 0.
2. Portfolio Y has total and residual variance
3. Portfolio Y has an alpha given by
4. Portfolio Y has a zero cash position: eY = 0. Note that Y is an active position. Property 4 
guarantees that its long risky holdings exactly match its short risky holdings, and hence its cash 
position must be zero.


---


### Page 150


Page 142
5. Portfolio Y has an information ratio
Proof
Item 1 follows because hY is a linear combination of two portfolios, each with zero beta.
To show item 2, calculate the variance of hY using Eq. (5A.37). To calculate the covariance of hA 
and hCR, note that 
 and that the covariance between hCR and hA is the same as 
the covariance between hC and hA since portfolio A is pure residual.
Item 3 follows by direct calculation starting with Eq. (5A.37).
To prove item 4, use eT · hCR = 1 – βC · eB and 
. (1 – βC · eB).
Item 5 is a direct result of items 2 and 3.
The Optimal No Active Beta and No Active Cash Portfolio
Portfolio Y is linked to the problem of finding an optimal residual position under the restrictions of 
no active beta and no active cash. The problem is
subject to βT · hP = 1 and eT · hP = eB.
Proposition 4
The optimal solution of Eq. (5A.41) is
Proof
The constraints dictate that the optimal solution to the problem must be of the form hP = hB + hPR, 
where hPR is a residual position with no active cash, i.e., eT · hPR = 0. We will associate the rather 
strange Lagrange multipliers


---


### Page 151


Page 143
with the beta and holdings constraints, respectively. The first-order conditions are the two 
constraints, plus
In Eq. (5A.43), we can write α as 
. If we make 
those substitutions, multiply by V-1, and divide by 2 · λR, we find
The constraints on beta and total holdings along with 
 allow us to solve for φ 
and π. The solutions are
When we combine these results, we find hPR = (IR/2 · λR) · hY, the desired result.
Thus far in this technical appendix, we have described key portfolios involved in managing residual 
risk and return, and have discussed how these affect our understanding of the information ratio. At 
this point, we turn to two more mundane properties of the information ratio: how it scales with 
investment time period and with the scale of the alphas.
Proposition 5
Consider a time period of length T years. If the residual return in any time interval is independent of 
the residual returns in other time intervals, and the residual returns have the same mean and standard 
deviation in all time intervals, then the ratio of the residual return over the period [0,T] to the 
residual risk over the period [0,T] will grow with the square root of T.
Proof
Divide the period [0,T] into K intervals of length Δt = T/K. Let k = 1,2, . . . , K index the intervals; 
interval k runs from time (k – 1) · Δt to k · Δt. Let θ(k) be the residual return in interval k,


---


### Page 152


Page 144
and let 
 be the residual return over [0,T]. The expected value of θ(k) is the same for all 
k—say, α = E{θ(k)}—and so
The θ(k) have a constant variance, Var{θ(k)} = ω2. Since the θ(k) are independent, we have
which is the promised result. Note that the annual information ratio is 
Proposition 6
The information ratio is linear in the input alphas.
Proof
Rescale α by a factor π in Eq.(5A.6). The resulting information ratio is π · IR.
We find this obvious result quite useful. One difficulty that arises in practice is the use of alphas that 
are so optimistic that they overwhelm any reasonable constraints on risk. The alphas usually need to 
be scaled down. Given a set of alphas, one could calculate (there are programs that do this) 
 Suppose we find IR0 = 2.46. We know from our common-sense discussion in 
this chapter that numbers like 0.75 are more reasonable. If we multiply the alphas by π = 0.75/2.46, 
then the information ratio for the scaled alphas will be 0.75. We could put these scaled alphas into 
an optimization program with a reasonable level of active risk aversion (λ = 0.10) and expect 
plausible results.


---


### Page 153


Page 145
Exercises
1. Demonstrate that
2. Demonstrate that
Note that βC = (σC/σB)2. In the absence of benchmark timing, i.e., if fB = µB, the alpha of portfolio C 
is the key to determining the beta of portfolio Q.
Applications Exercises
For these exercises, assume that
Portfolio B = CAPMMI
Portfolio Q = MMI
fQ = 6 percent
Applications Exercises 1, 2, and 3 are closely related to Problem 3 at the end of the main body of 
this chapter. The difference is that here you need to supply all the numbers.
1. What are the expected excess returns and residual returns for portfolios B, Q, and C?
2. What are the total and residual risks for portfolios B, Q, and C?
3. What are the Sharpe ratios and information ratios for portfolios B, Q, and C?
4. Demonstrate Eq. (5A.16).
5. Demonstrate the relationship shown in Exercise 2 above.


---


### Page 154


Page 147
Chapter 6— 
The Fundamental Law of Active Management
Introduction
In Chap. 5, the information ratio played the role of the ''assumed can opener" for our investigation of 
active strategies. In this chapter, we will give that can opener more substance by finding the 
attributes of an investment strategy that will determine the information ratio.
The insights that we gain will be useful in guiding a research program and in enhancing the quality 
of an investment strategy. Major points in this chapter are:
• A strategy's breadth is the number of independent, active decisions available per year.
• The manager's skill, measured by the information coefficient, is the correlation between forecasts 
and results.
• The fundamental law of active management explains the information ratio in terms of breadth and 
skill.
• The additivity of the fundamental law allows for an attribution of value added to different 
components of a strategy.
The Fundamental Law
The information ratio is a measure of a manager's opportunities. If we assume that the manager 
exploits those opportunities in a


---


### Page 155


Page 148
way that is mean/variance-efficient, then the value added by the manager will be proportional to the 
information ratio squared. As we saw in Chap. 5, all investors seek the strategies and managers with 
the highest information ratios. In this chapter, we investigate how to achieve high information ratios.
A simple and surprisingly general formula called the fundamental law of active management gives 
an approximation to the information ratio. We derive the result in the technical appendix. The law is 
based on two attributes of a strategy, breadth and skill. The breadth of a strategy is the number of 
independent investment decisions that are made each year, and the skill, represented by the 
information coefficient, measures the quality of those investment decisions. The formal definitions 
are as follows:
BR is the strategy's breadth. Breadth is defined as the number of independent forecasts of 
exceptional return we make per year.
IC is the manager's information coefficient. This measure of skill is the correlation of each forecast 
with the actual outcomes. We have assumed for convenience that IC is the same for all forecasts.
The law connects breadth and skill to the information ratio through the (approximately true) 
formula:
The approximation underlying Eq. (6.1) ignores the benefits of reducing risk that our forecasts 
provide. For relatively low values of IC (below 0.1), this reduction in risk is extremely small. We 
consider the assumptions behind the law in detail in a later section.
To increase the information ratio from 0.5 to 1.0, we need to either double our skill, increase our 
breadth by a factor of 4, or do some combination of the above.
In Chap. 5, we established a relationship [Eq. (5.10)] between the level of residual risk and the 
information ratio. With the aid of the fundamental law, we can express that relationship in terms of 
skill and breadth:


---


### Page 156


Page 149
We see that the desired level of aggressiveness will increase directly with the skill level and as the 
square root of the breadth. The breadth allows for diversification among the active bets so that the 
overall level of aggressiveness ω* can increase. The skill increases the possibility of success; thus, 
we are willing to incur more risk, since the gains appear to be larger.
The value a manager can add depends on the information ratio [Eq. (5.12)]. If we express the 
manager's ability to add value in terms of skill and breadth, we see
The value added by a strategy (the risk-adjusted return) will increase with the breadth and with the 
square of the skill level.
The fundamental law is designed to give us insight into active management. It isn't an operational 
tool. A manager needs to know the trade-offs between increasing the breadth of the strategy BR—
by either covering more stocks or shortening the time horizons of the forecasts—and improving skill 
IC. Thus we can see that a 50 percent increase in the strategy breadth (with no diminution in skill) is 
equivalent to a 22 percent increase in skill (maintaining the same breadth). A quick calculation of 
this sort may be quite valuable before launching a major research project. Operationally, it will 
prove difficult in particular to estimate BR accurately, because of the requirement that the forecasts 
be independent.
Figure 6.1 shows the trade-offs between breadth and skill for two levels of the information ratio.
We can see the power of the law by making an assessment of three strategies. In each strategy, we 
want an information ratio of 0.50. Start with a market timer who has independent information about 
market returns each quarter. The market timer needs an information coefficient of 0.25, since 
. As an alternative, consider a stock selecter who follows 100 companies and 
revises the assessments each quarter. The stock selecter makes 400 bets per year; he needs an 
information coefficient of 0.025, since 
. As a third example, consider a 
specialist who follows two companies and revises her bets on each 200 times per year. The 
specialist will make 400 bets per year and require a skill level of 0.025. The stock selecter achieves 
breadth by looking


---


### Page 157


Page 150
Figure 6.1
at a large number of companies intermittently, and the specialist achieves it by examining a small 
group of companies constantly. We can see from these examples that strategies with similar 
information ratios can differ radically in the requirements they place on the investor.
Examples
We can give three very straightforward examples of the law in action. First, consider a gambling 
example. Since we want to be successful active managers, we will play the role of the casino. Let's 
take a roulette game where bettors choose either red or black. The roulette wheel has 18 red spots, 
18 black spots, and 1 green spot. Each of the 37 spots has probability 1/37 of being selected at each 
turn of the wheel. The green spot is our advantage.
If the bettor chooses black, the casino wins if the wheel stops on green or red. If the bettor chooses 
red, the casino wins if the wheel stops on green or black. Consider a $1.00 bet. The casino


---


### Page 158


Page 151
puts up a matching $1.00; that's the casino's investment. The casino will end up with $2.00 (a plus 
100 percent return) with probability 19/37, and with zero (a minus 100 percent return) with 
probability 18/37. The casino's expected percentage return per $1.00 bet is
The standard deviation of the return on that single bet is 99.9634%.1 If there is one bet of $1.00 in a 
year, the information ratio for the casino will be 0.027038 = 2.7027/99.9634. In this case, our skill is 
1/37 and our breadth is one. The formula predicts an information ratio of 0.027027. That's pretty 
close.
We can see the dramatic effect breadth has by operating like a real casino and having 1 million bets 
of $1.00 in a year. Then the expected return will remain at 2.7027 percent, but the standard 
deviation drops to 0.09996 percent. This gives us an information ratio of 27.038. The formula 
predicts 
.
We could (American casinos do) add another green spot on the wheel and increase our advantage to 
2/38. Then our expected return per bet will be 5.263 percent, and the standard deviation will be 
99.861 percent. For 1 million plays per year, the expected return stays at 5.263 percent, and the 
standard deviation drops to 0.09986 percent. The information ratio is 52.70. The formula with IC = 
2/38, and BR = 1,000,000 leads to an information ratio of 52.63. Owning a casino beats investment 
management hands down.
As a second example, consider the problem of forecasting semiannual residual returns on a 
collection of 200 stocks. We will designate the residual returns as θn. To make the calculations 
easier, we assume that
• The residual returns are independent across stocks.
• The residual returns have an expected value of zero.
• The standard deviation of the semiannual residual return is 17.32 percent—that's 24.49 percent 
annual for each stock.
1The variance is (19/37) · (100% – 100%/37)2 + (18/37) · (–100% – 100%/37)2 = 9992.696%2, and therefore 
the standard deviation is 99.9634.


---


### Page 159


Page 152
Our information advantage is an ability to forecast the residual returns. The correlation between our 
forecasts and the subsequent residual returns is 0.0577. One way to picture our situation is to 
imagine the residual return itself as the sum of 300 independent terms for each stock, θn,j for j = 1, 
2, . . . , 300:
where each θn,j is equally likely to be +1.00 percent or –1.00 percent. Each θn,j will have a mean of 0 
and standard deviation of 1.00 percent. The standard deviation of 300 of these added together will 
be 
.
Our forecasting procedure tells us θn,1 and leaves us in the dark about θn,2 through θn,300. The 
correlation of θn,1 with θn will be 0.0577.2 There are 300 equally important things that we might 
know about each stock, and we know only 1 of them. We don't know very much.
Since we are following 200 stocks, we will have 200 pieces of information twice a year, for a total 
of 400 per year. Our information coefficient, the correlation of θn,1 and θn, is 0.0577. According to 
the fundamental law, the information ratio should be 
.
Can we fashion an investment strategy that will achieve an information ratio that high? In order to 
describe a portfolio strategy to exploit this information and calculate its attributes easily, we need a 
simplifying assumption. Assume that the benchmark portfolio is an equal-weighted portfolio of the 
200 stocks (0.50 percent each). In each 6-month period, we expect to have about 100 stocks with a 
forecasted residual return for the quarter of +1.00 percent and 100 stocks with a forecasted residual 
return of –1.00 percent. This is akin to a buy list and a sell list. We will equal-weight the buy list (at 
1.00 percent each), and not hold the sell list.
2The covariance of θn,1 with θn is 1, since θn,1 is uncorrelated with θn,j for j ≥ 2. Since the standard deviations of 
θn,1 and θn are 1.0 and 17.32, respectively, their correlation is 0.0577. (The correlation is the covariance divided 
by the two standard deviations. See Appendix C.)


---


### Page 160


Page 153
The expected active return will be 1.00 percent per 6 months with an active standard deviation of 
1.2227 percent per 6 months.3 The 6-month information ratio is 0.8179. To calculate an annual 
information ratio, we multiply the 6-month information ratio by the square root of 2, to find 
. This is slightly greater than the 1.154 predicted by the formula, since the 
formula does not consider the slight reduction in uncertainty resulting from the knowledge of θn,1.4
We can also consider a third example, to put the information coefficient in further context. Suppose 
we want to forecast the direction of the market each quarter. In this simple example, we care only 
about forecasting direction. We will model the market direction as a variable x(t) = ±1, where x has 
mean 0 and standard deviation 1. Our forecast is y(t) = ±1, also with mean 0 and standard deviation 
1. Then the information coefficient—the correlation of x(t) and y(t)—depends on the covariance of x
(t) and y(t):
where we observe N bets on market direction.
If we correctly forecast market direction (x = y) N1 times, and incorrectly forecast market direction 
(x = –y) N – N1 times, then the information coefficient is
3The active holdings are 1/200 for 100 stocks and –1/200 for another 100 stocks. The expected active return is 
100 · (1/200) · (1%) + 100 · (–1/200) · (–1%) = 1%. The residual variance of each asset (conditional on 
knowing θn,1) is 299. The active variance of our position is 
.
4We can go one step further with this example. In each half year, about 50 of the stocks will move from the buy list 
to the sell list, and another 50 will move from the sell list to the buy list. To implement the change will require 
about 50 percent turnover per 6 months, or 100 percent turnover per year. If round-trip transactions costs are 0.80 
percent, then we lose 0.80 percent per year in transactions costs. The information ratio drops to 0.70, since the 
annual alpha net of costs is 1.21 percent and the annual residual risk stays at 1.729 percent.


---

