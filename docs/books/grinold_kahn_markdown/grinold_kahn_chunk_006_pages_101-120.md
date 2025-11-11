# Grinold-Kahn Active Portfolio Management

## Pages 101-120


### Page 101


Page 93
Starting with a list of expected returns E{Rn}, asset betas βn, the weight of each asset in the 
benchmark hB(n), a risk-free rate iF, and a long-run expected excess return on the benchmark µB, we 
can separate the expected returns into their component parts. The recipe is a simple and interesting 
spreadsheet exercise.
Step 1. Calculate the expected excess return on the benchmark.
Step 2. The exceptional benchmark return is
Table 4.2 presents expected returns for MMI stocks in the United States, assuming a risk-free rate of 
3.16 percent, an S&P 500 benchmark with an expected excess return of 6 percent, and historical 
alphas and betas over the 60-month period ending December 1992. The expected returns vary 
widely from stock to stock, much more than the betas vary. This happens because we are using 
historical alphas (which vary widely) to calculate expected returns.
Note that we have included cash and a benchmark composite in the list. Cash is the one asset that 
we are sure we can get right. The benchmark composite will have zero alpha, since there is by 
definition no residual return for the benchmark.
Management of Total Risk and Return
The traditional (Markowitz-Sharpe) approach to modern portfolio theory is to consider the 
risk/expected return trade-offs available to the manager. In this section, we will follow that path. In 
the following sections, we will expand the risk/expected return framework to distinguish between 
benchmark and active risk.
The return/risk choices available with the consensus forecast are presented in Fig. 4.1. The 
horizontal axis measures portfolio risk and the vertical axis expected excess returns using the 
consensus forecast µ, which is β · µB. The hyperbola describes the combinations of expected excess 
return and risk that we can obtain with fully


---


### Page 102


Page 94
TABLE 4.2 
Expected Returns for MMI Stocks
Stock
Alpha
Beta
Expected Return
American Express
–7.91%
1.21
2.53%
AT&T
3.47%
0.96
12.38%
Chevron
7.47%
0.45
13.32%
Coca-Cola
20.03%
1.00
29.19%
Disney
7.46%
1.24
18.05%
Dow Chemicals
–10.09%
1.11
–0.28%
DuPont
–0.43%
1.09
9.25%
Eastman Kodak
–9.04%
0.60
–2.29%
Exxon
4.51%
0.47
10.48%
General Electric
0.17%
1.31
11.20%
General Motors
–4.53%
0.90
4.01%
IBM
–19.04%
0.64
–12.04%
International Paper
–0.57%
1.16
9.46%
Johnson & Johnson
7.32%
1.15
17.40%
McDonalds
3.18%
1.07
12.77%
Merck
6.04%
1.09
15.73%
3M
0.47%
0.74
8.07%
Philip Morris
17.41%
0.97
26.38%
Procter & Gamble
8.05%
1.01
17.27%
Sears
–2.07%
1.04
7.32%
Cash
0.00%
0.00
3.16%
S&P 500
0.00%
1.00
9.16%
invested portfolios. The fully invested portfolio with the highest ratio of expected excess return to 
risk is the benchmark, B. There is no surprise here; consensus in implies consensus out.
Active management starts when the manager's forecasts differ from the consensus. If the manager 
has forecasts f of expected excess returns, then we have the risk/return choices shown in Fig. 4.2.
In Fig. 4.2, the benchmark is not on the efficient frontier. A fully invested portfolio Q that differs 
from B has the maximum ratio of fP to σP. There are possibilities for doing better than B!


---


### Page 103


Page 95
Figure 4.1
Figure 4.2


---


### Page 104


Page 96
We can express the forecast of expected excess return for stock n as
where fB is the forecast of expected excess return for the benchmark, βn is stock n's beta, and αn is 
stock n's forecast alpha. These forecasts will differ from consensus forecasts to the extent that fB 
differs from the consensus estimate µB and αn differs from zero.
The Total Return/Total Risk Trade-Off
The portfolio we select will depend on our objective. The traditional approach uses a mean/variance 
criterion for portfolio choice.3 We will call that criterion our expected utility, denote it as U[P], and 
define it as
where fP is the expected excess return and 
 is a penalty for risk. The parameter λT measures 
aversion to total risk, where total risk includes systematic risk (driven by the benchmark) and 
residual risk (from asset selection). Note that some authors have equivalently defined utility in terms 
of a risk acceptance parameter τ instead of a risk aversion parameter λ, where τ = 1/λ. Still other 
authors have, for later mathematical convenience, used λ/2 instead of λ in Eq. (4.11).
Figure 4.3 shows the lines of constant expected utility U[P]. The trick is to find an eligible portfolio 
with the highest possible expected utility.
We can get a reasonable feel for the total risk aversion λT by trying some typical numbers. Consider 
a portfolio with a risk of 20 percent. If we think that the penalty for risk is on the order of one-half 
the expected excess return on the portfolio, then we anticipate a penalty of 3 or 4 percent. To get 3 
percent, we would
3We can justify this in three ways: Returns are normally distributed, the investor has a quadratic utility 
function, or we are looking at the market over a relatively short period of time. The first two are in the 
Markowitz-Sharpe tradition. The third stems from the work of Merton on the approximation of general utility 
functions with quadratic utility functions over a short period of time.


---


### Page 105


Page 97
Figure 4.3 
Constant expected utility lines.
use λT = 0.0075, since 3 = 0.0075 · 400. To get 4 percent, we would use λT = 0.01, since 4 = 0.01 · 
400. As discussed in Chap. 3, λT is not dimensionless. In particular, it depends on whether we 
represent risk and return in percent or decimal, and whether we annualize.
There is a more scientific way to get a reasonable value for λT. Consider the case where we have no 
information, i.e., f = µ, our forecasts are equal to the consensus. The expected benchmark excess 
return is µB, and the benchmark risk is σB. The level of total risk aversion that would lead4 us to 
choose the benchmark portfolio is
If µB = 6 percent and σB = 20 percent, then we find λT = 0.0075.
If µB = 8 percent and σB = 16 percent, we find λT = 0.0156.
4Consider the simple problem of mixing the benchmark portfolio B with the risk-free portfolio F. The expected 
excess return will be βP · µB, where βP is the fraction in the benchmark portfolio. The risk will be 
. The 
objective is
The first-order conditions are
The optimal solution will be βP = 1 when Eq. (4.12) holds.


---


### Page 106


Page 98
Figure 4.4
If we are willing to have cash in our portfolio, then we have the situation shown in Fig. 4.4. The 
efficient frontier consists of all the portfolios on the line from F through Q. The optimal portfolio, 
call it P, is the portfolio on the frontier with the highest risk-adjusted return.5 Portfolio P will be a 
mixture of Q and F. The beta of P is
Using Eq. (4.12), and defining ΔfB ≡ fB – µB to be the forecast of exceptional benchmark return, the 
beta of portfolio P becomes
The active beta βPA, the difference between βP and 1, is the ratio of our forecast for benchmark 
exceptional return ΔfB to the consensus expected excess return on the benchmark µB.
5The holdings in P are given by
where the information ratio IR measures the ratio of expected residual return to residual risk. Chapter 5 discusses it 
in detail. The technical appendix of Chap. 5 covers the characteristic portfolio of the alphas, portfolio A.


---


### Page 107


Page 99
TABLE 4.3
fP
27.29%
σP
25.20%
βP
1.05
αP
20.99%
ωP
13.78%
We will argue that this expected utility criterion will typically lead to portfolios that are too 
aggressive for institutional investment managers.6
Consider, for example, our expected return forecasts for the MMI stocks. Table 4.3 shows the 
attributes of the portfolio that we obtain using these stocks with a typical level of risk aversion (λ = 
0.0075).
These portfolios are far too risky for the institutional manager. This is not due to the extravagant 
nature of the expected returns. The problem is not the total portfolio risk σP, it is the residual risk ωP.
In total risk/return analysis, small levels of information lead to very high levels of residual risk.
In order to develop an objective that gives results that are more in line with institutional practice, we 
need to focus on the active component of return, and look at active risk/return trade-offs.
Focus on Value-Added
In the previous section, we discovered that portfolio selection using an expected utility objective 
leads to levels of residual risk that are
6The optimal level of residual risk depends on the perceived quality of the manager's information. This is 
measured by the information ratio IR, a concept discussed in great detail in the next chapter. Optimistic 
estimates of the information ratio generally range from 0.5 to 1.0. The optimal level of residual risk is
A hopeful manager with an information ratio of 0.75 and total risk aversion of 0.01 would have 37.5 percent 
residual risk.


---


### Page 108


Page 100
much higher than those observed among institutional portfolio managers. The root cause is our 
even-handed treatment of benchmark and active risk. There is actually a double standard—
investment managers and pension plan sponsors are much more averse to the risk of deviation from 
the benchmark than they are averse to the risk of the benchmark.
Why are institutional money managers willing to accept the benchmark portfolio with 20 percent 
risk and loath to take on a portfolio with 21.00 percent risk if it contains 20 percent benchmark risk 
and 6.40 percent residual risk? The variance in the first case will be 400, and that in the second case 
will be 441 = (21%)2. The difference in risk between 20 percent and 21 percent seems small.
Business Risk and Investment Risk
The explanation lies in the allocation of that risk. The owner of the funds, a pension fund or an 
endowment, bears the benchmark component of the risk. The owner of the funds assumed that risk 
when invested in that particular benchmark. The active manager, on the other hand, bears the 
responsibility for the residual risk.7
Let's say the benchmark is the S&P 500. Hundreds of managers are compared to the S&P 500. All 
of these managers will experience the same benchmark return. The S&P 500 is the tide that raises or 
lowers all boats. The managers cannot influence the tide. They will be separated by the residual 
returns. A high level of residual risk means that there is a large chance of being among the worst 
managers and a resulting possibility of termination. This is not a happy prospect, and so managers 
reduce their residual risk in order to avoid the business risk inherent in placing low in the table.
Fortunately, our view of risk and return allows us to accommodate this double standard for 
benchmark and residual risk.
In the technical appendix to this chapter, we will more rigorously derive the objective for the active 
manager, which splits risk and return into three parts, as described below.
7The active manager is, in fact, responsible for active risk. In the typical case of βP = 1, residual risk equals 
active risk. If βP 
 1, the manager is responsible for both residual risk and active systematic risk.


---


### Page 109


Page 101
Intrinsic, 
. This component arises from the risk and return of the benchmark. It is not 
under the manager's control. Note that we have used λT as aversion to total risk.
Timing, 
. This is the contribution from timing the benchmark. It is governed 
by the manager's active beta. Note the risk aversion λBT to the risk caused by benchmark timing.
Residual, 
. This is due to the manager's residual position. Here we have an aversion λR 
to the residual risk.
The last two parts of the objective measure the manager's ability to add value. The amount of value 
added is
The two components of the value-added objective are similar to the mean/variance utility objective 
that we considered in Eq. (4.11). In each component, there is an expected return term and a variance 
term. The risk aversion—λBT for benchmark timing and λR for residual risk—transforms the variance 
into a penalty deducted from the amount of expected returns. The value added is a risk-adjusted 
expected return that ignores any contribution of the benchmark to the risk and expected return.
The objective [Eq. (4.15)] splits the value added into value added by benchmark timing and value 
added by stock selection. We consider benchmark timing briefly in the section below, and in more 
detail in Chap. 19. We will consider stock selection in the next chapter.
Benchmark Timing
Benchmark timing is the choice of an appropriate active beta, period by period. The bulk of this 
book will concentrate on the management of residual return. The exceptions are Chap. 18, ''Asset 
Allocation," and Chap. 19, "Benchmark Timing."
We take this approach for four reasons:
• A majority of U.S. institutional managers and a growing minority of non-U.S. institutional 
managers do not use benchmark timing.


---


### Page 110


Page 102
• It greatly simplifies the discussion. This will help the reader who accepts this premise or is at least 
willing to temporarily suspend disbelief.
• We may succeed. Recall the Russian proverb, "The man who chases two rabbits will catch 
neither."
• A more subtle reason, suggested in Chap. 6, "The Fundamental Law of Active Management," is 
that there is less chance of deriving substantial8 value added through benchmark timing.
This separation of benchmark timing and stock selection is evident in Eq. (4.15). We can choose 
beta to maximize the first term in that equation. The optimal level of active beta will be
Very high levels of aversion to benchmark timing risk λBT will keep βPA (and hence benchmark 
timing) close to zero. No benchmark forecast, i.e., ΔfB = 0, will also keep active beta equal to zero.
Active versus Residual Returns
Our active management framework is quickly moving toward a focus on residual return and residual 
risk. How does this connect with the manager's goal of significant active return?
The residual return and risk are
while the active return and risk are
8The reader is free to protest at this point. However, protests based on a single data point, such as "I knew a 
fellow who was in puts in October 1987" will not be allowed. To hint at the underlying argument, benchmark 
timing can clearly generate very large active returns in one particular period, just by luck. But this isn't the 
same as generating substantial risk-adjusted value added.


---


### Page 111


Page 103
As long as the manager avoids benchmark timing and sets βP = 1, active and residual returns (and 
risks) are identical. This is the case for most institutional equity managers, and for good reasons, 
which we will cover in Chap. 6. If the manager does engage in benchmark timing, then, as we can 
see in Eq. (4.19), the active return is the sum of the residual return and the benchmark timing return.
Summary
Previous chapters have discussed consensus expected returns and risk. This chapter turns to the 
heart of active management: exceptional returns. In particular, it has focused on the components of 
exceptional returns and introduced the notion of a benchmark portfolio. The benchmark is 
determined by institutional considerations and can differ considerably from what is commonly 
considered the market portfolio.
We have looked at possible criteria for the active manager. The traditional criterion of maximizing 
expected utility does not appear to give results that are consistent with investment practice. The 
main reason for this is that the expected utility function approach fails to distinguish between 
sources of risk. But the client bears the benchmark risk, and the active manager bears the active risk 
of deviating from the benchmark.
In the appendix, we derive an objective that separates active risk into two components: active risk 
that is correlated with the benchmark, resulting from a choice of active beta (benchmark timing), 
and active residual risk that is uncorrelated with the benchmark and based on forecasts of residual 
return (alpha). A reader who has difficulty with this approach should realize that it is a 
generalization of the usual risk/expected return approach. If we take the risk-free asset, portfolio F, 
as the benchmark, then all return is residual return. If we equate the risk aversions for total risk, 
benchmark timing, and residual risk, i.e., λT = λBT = λR, then we are back in the traditional 
risk/expected return framework.
We turn to the management of residual return in the next chapter.


---


### Page 112


Page 104
Problems
1. Assume a risk-free rate of 6 percent, a benchmark expected excess return of 6.5 percent, and a 
long-run benchmark expected excess return of 6 percent. Given that McDonald's has a beta of 1.07 
and an expected total return of 15 percent, separate its expected return into
Time premium
Risk premium
Exceptional benchmark return
Alpha
Consensus expected return
Expected excess return
Exceptional expected return
What is the sum of the consensus expected return and the exceptional expected return?
2. Suppose the benchmark is not the market, and the CAPM holds. How will the CAPM expected 
returns split into the categories suggested in this chapter?
3. Given a benchmark risk of 20 percent and a portfolio risk of 21 percent, and assuming a portfolio 
beta of 1, what is the portfolio's residual risk? What is its active risk? How does this compare to the 
difference between the portfolio risk and the benchmark risk?
4. Investor A manages total return and risk 
, with risk aversion λT = 0.0075. Investor B 
manages residual risk and return 
, with risk aversion λR = 0.075 (moderate to 
aggressive). They each can choose between two portfolios:
f1 = 10%
σ1 = 20.22%
f2 = 16%
σ2 = 25%
Both portfolios have β = 1. Furthermore,
fB = 6%
σB = 20%


---


### Page 113


Page 105
Which portfolio will A prefer? Which portfolio will B prefer? (Hint: First calculate expected 
residual return and residual risk for the two portfolios.)
5. Assume that you are a mean/variance investor with total risk aversion of 0.0075. If a portfolio has 
an expected excess return of 6 percent and risk of 20 percent, what is your certainty equivalent 
return, the certain expected excess return that you would fairly trade for this portfolio?
References
Jacobs, Bruce I., and Kenneth N. Levy. "Residual Risk: How Much Is Too Much?"Journal of 
Portfolio Management, vol. 22, no. 3, Spring 1996, pp. 10–16.
Markowitz, H. M. Portfolio Selection: Efficient Diversification of Investment. Cowles Foundation 
Monograph 16 (New Haven, Conn.: Yale University Press, 1959).
Merton, Robert C. "An Analytical Derivation of the Efficient Portfolio." Journal of Financial and 
Quantitative Analysis, vol. 7, September 1972, pp. 1851–1872.
Messmore, Tom. "Variance Drain." Journal of Portfolio Management, vol. 21, no. 4, Summer 1995, 
pp. 104–110.
Roll, Richard. "A Mean/Variance Analysis of Tracking Error." Journal of Portfolio Management, 
vol. 18, no. 4, Summer 1992, pp. 13–22.
Rosenberg, Barr. "How Active Should a Portfolio Be? The Risk-Reward Tradeoff."Financial 
Analysts Journal, vol. 35, no. 1, January/February 1979, pp. 49–62.
———. "Security Appraisal and Unsystematic Risk in Institutional Investment." Proceedings of the 
Seminar on the Analysis of Security Prices, (Chicago: University of Chicago Press), November 
1976, pp. 171–237.
Rudd, Andrew. "Business Risk and Investment Risk." Investment Management Review, 
November/December 1987, pp. 19–27.
Rudd, Andrew, and Henry K. Clasing, Jr. Modern Portfolio Theory, 2d (Orinda, Calif.: Andrew 
Rudd, 1988).
Sharpe, William F. "Capital Asset Prices: A Theory of Market Equilibrium under Conditions of 
Risk." Journal of Finance, vol. 19, no. 3, September 1964, pp. 425–442.
Technical Appendix
In this appendix, we derive the objective for value-added management that we use throughout the 
book. The value-added objective looks at two sources of exceptional return and active risk. The 
sources are residual risk and benchmark timing.


---


### Page 114


Page 106
An Objective for Value-Added Management
We begin by separating three items—a forecast of excess returns f, the portfolio holdings hP, and the 
portfolio variance 
—into a benchmark and a residual (to the benchmark) component. Let hPR 
represent portfolio P's residual holdings in the risky stocks. We have
where the beta, βP, is Cov{rP,rB}/Var{rB}, i.e., beta with respect to the benchmark.
We can decompose the expected excess return on portfolio P,,fP, into the sum of several items. If we 
recall that ΔfB = fB – µB is the difference between our forecast of the benchmark's excess return and 
the long-run consensus, and that the portfolio beta βP = 1 + βPA, where βPA is the active beta, Eq. 
(4A.2) leads to
These expected excess return items are
1. fB, expected benchmark excess return
2. βPA · µB, return due to active beta and consensus forecast
3. βPA · ΔfB, return due to active beta and exceptional forecast
4. αP, return due to stock alphas and stock selection
We can't do anything about item 1. Items 3 and 4 link our exceptional forecasts, ΔfB and α, with our 
active positions βPA and hPR. Item 2 is curious. This is the effect on expected return of varying beta. 
Notice that item 2 contains no forecast information.
Starting with Eq. (4A.3), we can also split the portfolio's variance into several parts:
These variance items are, in turn,


---


### Page 115


Page 107
5. 
 benchmark variance
6. 
 covariance due to active beta
7. 
 variance due to active beta
8. 
 variance due to stock selection
Now consider a utility function which trades off exceptional return against risk. We start with a 
general utility function of the form u = f – λ · σ2 and apply the breakdowns of expected return and 
risk shown in items 1 through 8. Grouping together related return and risk items (1 and 5, 2 and 6, 3 
and 7, 4 and 8), we generalize the usual approach by allowing three types of risk aversion, λT, λBT 
and λR for total, benchmark timing, and residual risk aversion. Items 5 and 6 contribute to total risk, 
item 7 to benchmark timing, and 8 to residual risk. The idea is to distinguish the inherent risk from 
owning the benchmark portfolio and the active risks the manager takes in trying to outperform by 
either benchmark timing or taking on residual risk.
We need to keep in mind why we are defining a utility function. It will lead us to choose a portfolio 
that maximizes that utility. So we will analyze terms based on their influence over our optimal 
portfolio.
The result of these manipulations is an overall utility function comprising the following elements:
9. 
 the benchmark component; it combines items 1 and 5. It is all forecast and no action 
(i.e., it has no influence on the optimal portfolio).
10. 
 cross effects; it combines items 2 and 6. It includes action, but no 
forecast.
11. 
 benchmark timing; it combines items 3 and 7. It includes both forecast 
and action.
12. 
 stock selection; it combines items 4 and 8. It includes both forecast and action.
The first term, 9, is a constant and does not influence the active decision. It has no influence on our 
choice of optimal portfolio.
We will argue that the second term, 10, is zero regardless of the choice of βPA. Item 10 does not 
depend on any forecast information; it is a permanent part of the objective that is not influenced by 
our investment insights. In addition, Eq. (4.12) implies that the expres-


---


### Page 116


Page 108 
sion in the curly brackets in 10 should be zero. Finally, imagine what would happen if our 
forecasts agreed with the consensus; i.e., if f = µ. In that case, we would have ΔfB = 0 and α 
= 0. The portfolio construction procedure should lead us to hold the benchmark; i.e., βPA = 
0, and ωP = 0. That will happen only if 
After ignoring the constant term 9 and the zero term 10, we are left with the value-added 
objective: 
The objective of active management is to maximize this value added. 
Exercise 
1. Derive the benchmark timing result: 
Applications Exercises 
1. Using a performance analysis software package, analyze the return on the MMI portfolio 
relative to an S&P 500 benchmark. Assume an expected excess return to the benchmark of 
6 percent. What was the 
Time premium 
Realized risk premium


---


### Page 117


Page 109
Chapter 5— 
Residual Risk and Return:
The Information Ratio
Introduction
The theory of investments is based on the premise that assets are fairly valued. This is reassuring for 
the financial economist and frustrating to the active manager. The active manager needs theoretical 
support. In the next four chapters we will provide a structure, if not a theory, for the active manager.
This chapter starts the process by building a strategic context for management of residual risk and 
return. Within that context, we will develop some concepts and rules of thumb that we find valuable 
in the evaluation and implementation of active strategies.
The reader is urged to rise above the details. Do not worry about transactions costs, restrictions on 
holdings, liquidity, short sales, or the source of the alphas. We will deal with those questions in later 
chapters. At this point, we should free ourselves from the clutter and look at active management 
from a strategic perspective. Later chapters on implementation will focus on the details and indicate 
how we might adjust our conclusions to take these important practical matters into consideration.
There is no prior theory. We must pull ourselves up by our bootstraps. Economists are good at this. 
Recall the parable of the engineer, the philosopher, and the economist stranded on a South Sea 
island with no tools, very little to eat on the island, and a large quantity of canned food. The 
engineer devises schemes for opening the cans by boiling them, dropping them on the rocks, etc. 
The philosopher ponders the trifling nature of food and the ultimate


---


### Page 118


Page 110
futility of life. The economist just sits and gazes out to sea. Suddenly, he jumps up and shouts, "I've 
got it! Assume you have a can opener."
The active manager's can opener is the assumption of success. The notion of success is captured and 
quantified by the information ratio. The information ratio says how good you think you are. The 
assumption of future success is used to open up other questions. If our insights are superior to those 
of other investors, then how we should use those insights?
We proceed with can opener and analysis. The results are insights, rules of thumb, and a formal 
procedure for managing residual risk and return. Some of the highlights are:
• The information ratio measures achievement ex post (looking backward) and connotes 
opportunity ex ante (looking forward).
• The information ratio defines the residual frontier, the opportunities available to the active 
manager.
• Each manager's information ratio and residual risk aversion determine his or her level of 
aggressiveness (residual risk).
• Intuition can lead to reasonable values for the information ratio and residual risk aversion.
• Value added depends on the manager's opportunities and aggressiveness.
The chapter starts with the definition of the information ratio, which is one of the book's central 
characters. In this chapter we use the information ratio in its ex ante (hope springs eternal) form. 
The ex ante information ratio is an indication of the opportunities available to the active manager; it 
determines the residual frontier. In Chap. 4 we defined an objective for the active manager that 
considers both risk and return. The main results of this chapter flow from the interaction of our 
opportunities (information ratio) with our objectives.
In Chap. 4 we showed that a manager could add value through either benchmark timing or stock 
selection. We postpone the discussion of benchmark timing to Chap. 19 and will concentrate on 
stock selection until that point. This means that we are concerned about


---


### Page 119


Page 111
the trade-off between residual risk and alpha. Recall that when portfolio beta is equal to 1, residual 
risk and active risk coincide.
A technical appendix considers the information ratio in merciless detail.
The Definition of Alpha
Looking forward (ex ante), alpha is a forecast of residual return. Looking backward (ex post), alpha 
is the average of the realized residual returns.
The term alpha, like the term beta, arises from the use of linear regression to break the return on a 
portfolio into a component that is perfectly correlated with the benchmark and an uncorrelated or 
residual component. If rP(t) are portfolio excess returns in periodst = 1,2, . . . T and rB(t) are 
benchmark excess returns over those same periods, then the regression is
The estimates of βP and αP obtained from the regression are the realized or historical beta and alpha. 
The residual returns for portfolio P are
where αP is the average residual return and ∈P(t) is the mean zero random component of residual 
return.
This chapter concentrates on forecast alphas. In Chap. 12, ''Information Analysis," we'll learn how 
to evaluate the quality of the alpha forecasts. We'll consider realized alphas in Chap. 17, 
"Performance Analysis." Realized alphas are for keeping score. The job of the active manager is to 
score. To do that, we need good forecast alphas.
When we are looking to the future, alpha is a forecast of residual return. Let θn be the residual return 
on stock n. We have
Alpha has the portfolio property, since both residual returns and expectations have the portfolio 
property. Consider a simple case with two stocks whose alphas are α1 and α2. If we have a two-stock


---


### Page 120


Page 112
portfolio with holdings hP(1) in stock 1 and hP(2) in stock 2, then the alpha of the portfolio will be
This is consistent with the notion that αP is the forecast of expected residual return on the portfolio.
By definition, the benchmark portfolio will always have a residual return equal to 0; i.e., θB = 0 with 
certainty. Therefore, the alpha of the benchmark portfolio must be 0; αB = 0. The requirement that 
αB = 0 is the restriction that the alphas be benchmark-neutral.
Recall that the risk-free portfolio also has a zero residual return, and so the alpha for cash αF is 
always equal to 0. Thus any portfolio made up of a mixture of the benchmark and cash will have a 
zero alpha.
The Ex Post Information Ratio:
A Measure of Achievement
An information ratio,1 denoted IR, is a ratio of (annualized) residual return to (annualized) residual 
risk. If we consider the information ratio for some realized residual return (ex post), we have 
realized residual return divided by the residual risk taken to obtain that return. Thus we may have an 
average of 2.3 percent residual return per year with residual risk of 3.45 percent. That is an 
information ratio of 2.3/3.45 = 0.67.
A realized information ratio can (and frequently will) be negative. Don't forget that the information 
ratio of the benchmark must be exactly zero. If our residual return has averaged a poor –1.7 percent 
per year with the same residual risk level of 3.45 percent, then the realized information ratio is (–
1.7)/3.45 = –0.49.
We will say more about ex post information ratios at the end of this chapter and in Chap. 17, 
"Performance Analysis." We offer one teaser: The ex-post information ratio is related to the t 
statistic one obtains for the alpha in the regression [Eq. (5.1)]. If the data in the regression cover Y 
years, then the information ratio is approximately the alpha's t statistic divided by the square root of 
Y.
1Treynor and Black (1973) refer to this quantity as the appraisal ratio.


---

