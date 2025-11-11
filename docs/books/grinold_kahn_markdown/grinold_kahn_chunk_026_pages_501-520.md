# Grinold-Kahn Active Portfolio Management

## Pages 501-520


### Page 501


Page 497
portfolio that is long small-capitalization stocks and short large-capitalization stocks, with long and 
short sides having roughly equal book-to-price ratios.
Similarly, they define HML(t) as the difference between the average of S/H and B/H and the 
average of S/L and B/L. Once again, this is the return on a net zero investment portfolio that is long 
high-book-to-price stocks and short low-book-to-price stocks, with long and short sides having 
roughly equal market capitalizations.
Carhart (1997) has extended this approach by also controlling for past 1-year momentum.
Portfolio-based Performance Analysis
Returns-based analysis is a top-down approach to attributing returns to components, ex post, and 
statistically analyzing the manager's added value. At its simplest, the attribution is between 
systematic and residual returns, with managers given credit only for achieved residual returns. Style 
analysis is similar in approach, attributing returns to several style classes and giving managers credit 
only for the remaining selection returns. Returns-based performance analysis schemes typically 
allocate part of the returns to systematic or style components and give managers credit only for the 
remainder.
Portfolio-based performance analysis is a bottom-up approach, attributing returns to many 
components based on the ex ante portfolio holdings and then giving managers credit for returns 
along many of these components. This allows the analysis not only of whether the manager has 
added value, but of whether he or she has added value along dimensions agreed upon ex ante. Is he a 
skillful value manager? Does her value added arise from stock selection, beyond any bets on 
factors? Portfolio-based performance analysis can reveal this. In contrast to returns-based 
performance analysis, performance-based analysis schemes can attribute returns to several 
components of possible manager skill.
The returns-only analysis works without the full information available for performance analysis. We 
can say much more if we look at the actual portfolios held by the managers. In fact, two


---


### Page 502


Page 498
additional items of information can help in the analysis of performance:
• The portfolio holdings over time
• The goals and strategy of the manager
The analysis proceeds in two steps: performance attribution and performance analysis. Performance 
attribution focuses on a single period, attributing the return to several components. Performance 
analysis then focuses on the time series of returns attributed to each component. Based on statistical 
analysis, where (if anywhere) does the manager exhibit skill and add value?
Performance Attribution
Performance attribution looks at portfolio returns over a single period and attributes them to factors. 
The underlying principle is the multiple-factor model, first discussed in Chap. 3:
Examining returns ex post, we know the portfolio's exposures xPj(t) at the beginning of the period, as 
well as the portfolio's realized return γp(t) and the estimated factor returns over the period. The 
return attributed to factor j is
The portfolio's specific return is uP(t).
We are free to choose factors as described in Chap. 3, and in fact we typically run performance 
attribution using the same risk-model factors. However, we are not in principle limited to the same 
factors as are in our risk model. In general, just as in the returns-based analysis, we want to choose 
some factors for risk control and others as sources of return. The risk control factors are typically 
industry or market factors, although later we can analyze skill in picking industries.
The return factors can include typical investment themes such as value or momentum. In building 
risk models, we always use ex ante factors: that is, those based on information known at the 
beginning of the period. For return attribution, we could also con-


---


### Page 503


Page 499
sider ex post factors: that is, those based on information known only at the end of the period. For 
example, we could use a factor based on IBES earnings forecasts available at the end of the period. 
We could interpret returns attributed to this factor as evidence of the manager's skill in forecasting 
IBES earnings projections.
Beyond the manager's returns attributed to factors will remain the specific return to the portfolio. A 
manager's ability to pick individual stocks, after controlling for the factors, will appear in this term. 
We call this term specific asset selection.
We typically think of the specific return as the component of return which cross-sectional factors 
cannot explain. That view suggests that we simply lump the portfolio's specific return all together. 
But for an individual strategy, some attributions of specific return may also make sense. If our 
strategy depends on analyst information, we may want to group specific returns by analyst. We 
think our auto industry analyst adds value. If this is true, we should see a positive contribution from 
auto-stock specific asset selection. Similarly, the specific returns can tell us if our strategy works 
better in some sectors than in others. This term doesn't tell us whether we have successfully picked 
one sector over another, it tells us whether we can pick stocks more accurately in one sector than in 
another.
Note that we have many choices as to how to attribute returns. We can choose the factors for 
attribution. We can attribute specific returns. We can even attribute part of our returns to the 
constraints in our portfolio construction process (e.g., we lost 32 basis points of performance last 
year as a result of our optimizer constraints).8 Performance attribution is not a uniquely defined 
process. Commercially available performance analysis products choose widely applicable 
attribution schemes. Customized systems have no such limitations.
8For example, with linear equality constraints, hT · A = 0, and Lagrange multipliers –π, the first-order 
conditions are
α = 2 · λA · V · hPA + π · A = 0
This effectively partitions the alpha between the portfolio and the constraints. For more details, see Grinold and 
Easton (1998).


---


### Page 504


Page 500
We can apply performance attribution to total returns, active returns, and even active residual 
returns. For active returns, the analysis is exactly the same, but we work with active portfolio 
holdings and returns:
To break down active returns into systematic and residual, remember that we can define residual 
exposures as
where we simply subtract the active beta times the benchmark's exposure from the active exposure, 
and residual holdings similarly as
Substituting these into Eq. (17.20), and remembering that 
 we find
Equation (17.23) will allow a very detailed analysis of the sources of active returns relative to the 
benchmark.
As an example of performance attribution, consider the analysis of the Major Market Index portfolio 
versus an S&P 500 benchmark over the period January 1988 through December 1992. For now, 
focus on the returns over January 1988. Using the BARRA U.S. Equity model (version 2), the factor 
exposures are shown in Table 17.2.
Table 17.2 illustrates the attributed active return. Table 17.3 summarizes the attribution between 
systematic and residual this month. The active beta of the Major Market Index versus the S&P 500 
is only 0.02, and so the active residual component is very


---


### Page 505


Page 501
TABLE 17.2
Factor
Active Exposure
Attributed Return
Variability in markets
–0.10
–0.02%
Success
0.14
–0.47%
Size
0.69
0.10%
Trading activity
0.04
0.02%
Growth
–0.14
–0.10%
Earnings-to-price ratio
–0.07
–0.04%
Book-to-price ratio
–0.11
–0.06%
Earnings variability
–0.23
0.10%
Financial leverage
–0.04
–0.03%
Foreign income
0.62
–0.02%
Labor intensity
0.06
0.02%
Yield
0.00
0.00%
Low capitalization
0.00
0.00%
Aluminum
–0.57%
0.02%
Iron and steel
0.13%
0.01%
Precious metals
–0.31%
0.04%
Miscellaneous mining and metals
–0.61%
–0.03%
Coal and uranium
0.32%
–0.03%
International oil
2.53%
0.24%
Domestic petroleum reserves
0.92%
0.08%
Foreign petroleum reserves
0.00%
0.00%
Oil refining and distribution
–0.54%
–0.04%
Oil services
–0.91%
–0.09%
Forest products
0.42%
–0.01%
Paper
2.64%
–0.18%
Agriculture and food
–1.76%
–0.08%
Beverages
1.66%
–0.05%
Liquor
–0.52%
–0.01%
Tobacco
2.86%
0.19%
Construction
–0.01%
0.00%
Chemicals
5.59%
0.11%
Tire and rubber
–0.22%
0.00%
Containers
–0.22%
0.01%


---


### Page 506


Producer goods
–2.32%
–0.08%
Pollution control
–0.78%
–0.02%
(table continued on next page)


---


### Page 507


Page 502
(continued)
TABLE 17.2
Factor
Active Exposure
Attributed Return
Electronics
–1.52%
0.04%
Aerospace
–1.96%
–0.08%
Business machines
1.59%
–0.01%
Soaps and housewares
4.19%
0.25%
Cosmetics
–0.55%
–0.03%
Apparel, textiles
–0.32%
–0.01%
Photographic, optical
2.76%
–0.12%
Consumer durables
–0.44%
–0.02%
Motor vehicles
1.70%
0.06%
Leisure, luxury
–0.37%
–0.01%
Health care
3.14%
0.11%
Drugs and medicine
10.45%
1.01%
Publishing
–2.21%
–0.01%
Media
–1.29%
–0.08%
Hotels and restaurants
–1.86%
–0.09%
Trucking, freight
–0.21%
–0.01%
Railroads, transit
–1.30%
–0.07%
Air transport
–0.69%
–0.01%
Transport by water
–0.06%
0.00%
Retail food
–0.72%
–0.03%
Other retail
–2.95%
–0.26%
Telephone, telegraph
–5.24%
–0.43%
Electric utilities
–4.39%
–0.34%
Gas utilities
–1.04%
–0.05%
Banks
–1.96%
–0.14%
Thrift institutions
–0.09%
–0.01%
Miscellaneous finance
1.19%
0.06%
Life insurance
–0.82%
–0.06%
Other insurance
–1.11%
–0.06%
Real property
–0.22%
0.00%
Mortgage financing
0.00%
0.00%
Services
–2.09%
–0.04%


---


### Page 508


Miscellaneous
0.14%
0.01%
Total attributed active return
 
–0.84%


---


### Page 509


Page 503
TABLE 17.3
Component
Attributed Return
Active systematic
 
0.06%
Active residual
 
–4.88%
Common factor
–0.75%
 
Specific
–4.13%
 
Active total
 
–4.82%
close to the active component. Comparing Tables 17.2 and 17.3, the active common-factor 
component is –0.84 percent and the active residual common-factor component is –0.75 percent.
Performance Analysis
Performance analysis begins with the attributed returns each period, and looks at the statistical 
significance and value added of the attributed return series. As before, this analysis will rely on t 
statistics and information ratios to determine statistical significance and value added.
For concreteness, consider the attribution defined in Eq. (17.23), with active returns separated into 
systematic and residual, and active residual returns further attributed to common factors and specific 
returns.
Start with the time series of active systematic returns. Most straightforward is a simple analysis of 
the mean return and its t statistic. However, according to the CAPM, we expect a positive return 
here if the active beta is positive on average. Hence, we will go one additional step and separate this 
time series into three components: one arising from the average active beta and the expected 
benchmark return, one arising from the average active beta and the deviation of realized benchmark 
return from its expectation, and the third from benchmark timing—deviations of the active beta 
from its mean. The first component, based on the average active beta and the expected benchmark 
return, is not a component of active management.


---


### Page 510


Page 504
The total active systematic return over time is
In Eqs. (17.24) through (17.27), 
 is the average active beta, 
 is the average benchmark excess 
return over the period, and µB is the long-run expected benchmark excess return.
The analysis of the time series of attributed factor returns and specific returns is more 
straightforward.9 We can examine each series for its mean, t statistic, and information ratio. For 
these, we need not only the mean returns, but also the risk for each factor. We can base risk on the 
realized standard deviation of the time series or on the ex ante forecast risk. The technical appendix 
describes an innovative approach which combines the two risk estimates, weighting realized risk 
more heavily the more observations there are in the analysis period.
Performance analysis, just like performance attribution, is not uniquely defined. The scheme 
outlined here is simply a reasonable approach to distinguishing the various sources of typical 
strategy returns. It will sometimes prove useful to customize a performance
9Of course, we can apply the same time series analysis to the factor returns that we applied to the systematic 
returns. In particular, we can separate each attributed factor return into two components, one based on the 
average active exposure and the other based on the timing of that exposure about its average.


---


### Page 511


Page 505
TABLE 17.4
 
Annualized Active Contributions
Elements of Active Management
Return
Risk
IR
t statistic
Systematic active returns

Active beta surprise
0.02%
0.16%
0.23
0.51
Active benchmark timing
0.03%
0.19%
0.13
0.28
Total
0.06%
0.25%
0.24
0.54
Residual active returns

Industry factors
0.27%
1.88%
0.12
0.26
Risk index factors
–0.97%
2.25%
–0.36
–0.81
Specific
0.12%
3.23%
0.01
0.02
Total
–0.58%
4.21%
–0.14
–0.30
Total active returns
–0.52%
4.22%
–0.12
–0.27
analysis scheme to a particular strategy, in order to isolate more precisely its sources of value added.
Table 17.4 summarizes this analysis for the example of the Major Market Index portfolio versus the 
S&P 500 benchmark.10 Not surprisingly, given this example, Table 17.4 exhibits no strong 
demonstrations of skill or value added.
Now that we have analyzed each source of risk in turn, we can identify the best and worst policies 
followed by the manager: those time series which have achieved the highest and lowest returns on 
average. Here is where the manager's predefined goals and strategies should shine through. Stock 
pickers should see specific asset selection as one of their best strategies. Value managers should see 
value factors as their best strategies. Ex ante strategies that are inconsistent with best policy analysis 
can signal to the owner of the funds that the active manager has deviated in strategy and can signal 
to the manager that the strategy isn't doing what he or she expects it to do.
Table 17.5 displays the best and worst policies for the example Major Market Index portfolio versus 
the S&P 500 benchmark. Previ10The technical appendix includes a discussion of how we calculate annualized active contributions—in 
particular, how we deal with the issue of cumulating attributed returns.


---


### Page 512


Page 506
TABLE 17.5
Policy
Annualized Active Return
Five best policies
 
Foreign income
0.44%
International oil
0.36%
Drugs, medicine
0.33%
Tobacco
0.22%
Health care (nondrug)
0.18%
Five worst policies
 
Size
–1.24%
Photographic, optical
–0.48%
Business machines
–0.40%
Paper
–0.37%
Telephone, telegraph
–0.32%
ous analysis showed that the example included no demonstration of skill or value added, and 
comparing Table 17.5 to Table 17.2, we can see that the best and worst policies simply correspond 
to the largest-magnitude active exposures.
Summary
The goal of performance analysis is to separate skill from luck. The more information available, the 
better the analysis. Using a simple cross section of returns to differentiate managers is insufficient. 
A time series of returns to managers and benchmarks can separate skill from luck. The most 
accurate performance analysis utilizes information on portfolio holdings and returns over time, to 
not only separate skill from luck, but also identify where the manager has skill.
Notes
The science of performance analysis began in the 1960s with the seminal academic work of Sharpe 
(1966, 1970), Jensen (1968), and Treynor (1965). They used the CAPM as a starting point for 
developing the returns-based methodology described in this chapter. Their goal was to test market 
efficiency and analyze manager performance, a topic we will cover in Chap. 20.


---


### Page 513


Page 507
Since then, many other academics have developed performance analysis methodologies, often 
motivated by the desire to further test market efficiency and manager performance. Some advances 
have come from application of clever statistical insights to the CAPM framework. Other 
refinements have followed new developments in finance theory. For example, Fama and French 
(1993) have proposed a new scheme which explicitly controls for size and book-to-market effects.
Most often, the academic treatments have focused on returns-based analysis, although Daniel, 
Grinblatt, Titman, and Wermers (1997) control for size, book-to-price, and momentum at the asset 
level (using quintile portfolios) and then aggregate specific returns up to the portfolio level.
Most of these new academic developments are contained within the practitioner-developed 
portfolio-based analysis methodology described in this chapter.
References
Beckers, Stan. ''Manager Skill and Investment Performance: How Strong Is the Link?" Journal of 
Portfolio Management, vol. 23, no. 4, 1997, pp. 9–23.
Carhart, Mark M. "On Persistence in Mutual Fund Performance." Journal of Finance, vol. 52, no. 1, 
1997, pp. 57–82.
Christopherson, Jon A., and Frank C. Sabin. "How Effective Is the Effective Mix?" Journal of 
Investment Consulting, vol. 1, no. 1, 1998, pp. 39–50.
Daniel, Kent, Mark Grinblatt, Sheridan Titman, and Russ Wermers. "Measuring Mutual Fund 
Performance with Characteristic-based Benchmarks." Journal of Finance, vol. 52, no. 3, 1997, pp. 
1035–1058.
DeBartolomeo, Dan, and Erik Witkowski. "Mutual Fund Misclassification: Evidence Based on 
Style Analysis." Financial Analysts Journal, vol. 53, no. 5, 1997, pp. 32–43.
Dybvig, Philip H., and Stephen A. Ross. "The Analytics of Performance Measurement Using a 
Security Market Line." Journal of Finance, vol 40, no. 2, 1985, pp. 401–416.
Fama, Eugene F., and Kenneth R. French. "Common Risk Factors in the Returns on Stocks and 
Bonds." Journal of Financial Economics, vol. 33, no. 1, 1993, pp. 3–56.
Ferson, Wayne E., and Rudi W. Schadt. "Measuring Fund Strategy and Performance in Changing 
Economic Conditions." Journal of Finance, vol. 51, no. 2, 1996, pp. 425–461.
Ferson, Wayne E., and Vincent A. Warther. "Evaluating Fund Performance in a Dynamic Market." 
Financial Analysts Journal, vol. 52, no. 6, 1996, pp. 20–28.


---


### Page 514


Page 508
Grinold, Richard C., and Kelly K. Easton. "Attribution of Performance and Holdings." In 
Worldwide Asset and Liability Modeling, edited by William T. Ziemba and John M. Mulvey 
(Cambridge, England: Cambridge University Press, 1998), pp. 87–113.
Henriksson, Roy D., and Robert C. Merton. "On Market Timing and Investment Performance II. 
Statistical Procedures for Evaluating Forecasting Skills." Journal of Business, vol 54, no. 4, 1981, 
pp. 513–533.
Ippolito, Richard A. "On Studies of Mutual Fund Performance 1962–1991," Financial Analysts 
Journal, vol. 49, no. 1, 1993, pp. 42–50.
Jensen, Michael C. "The Performance of Mutual Funds in the Period 1945–1964." Journal of 
Finance, vol. 23, no. 2, 1968, pp. 389–416.
Jones, Frank J., and Ronald N. Kahn. "Stock Portfolio Attribution Analysis." In The Handbook of 
Portfolio Management, edited by Frank J. Fabozzi (New Hope, PA: Frank J. Fabozzi Associates, 
1998), pp. 695–707.
Lehmann, B., and D. Modest. "Mutual Fund Performance Evaluation: A Comparison of 
Benchmarks and Benchmark Comparisons." Journal of Finance, vol. 42, no. 2, 1987, pp. 233–265.
Lobosco, Angelo, and Dan DiBartolomeo. "Approximating the Confidence Intervals for Sharpe 
Style Weights." Financial Analysts Journal, vol. 53, no. 4, 1997, pp. 80–85.
Modigliani, Franco, and Leah Modigliani. "Risk-Adjusted Performance." Journal of Portfolio 
Management, vol. 23, no. 2, 1997, pp. 45–54.
Rudd, Andrew, and Henry K. Clasing, Jr. Modern Portfolio Theory, 2nd ed. (Orinda, Calif.: 
Andrew Rudd, 1988).
Sharpe, William F. "Mutual Fund Performance." Journal of Business, vol 39, no. 1, 1966, pp. 119–
138.
———. Portfolio Theory and Capital Markets (New York: McGraw-Hill, 1970).
———. "Asset Allocation: Management Style and Performance Measurement." Journal of 
Portfolio Management, vol. 18, no. 2, 1992, pp. 7–19.
Treynor, Jack L. "How to Rate Management of Investment Funds." Harvard Business Review, vol. 
43, no. 1, January–February 1965, pp. 63–75.
Treynor, Jack L., and Fischer Black. "Portfolio Selection Using Spectal Information under the 
Assumptions of the Diagonal Model with Mean Variance Portfolio Objectives and Without 
Constraints." In Mathematical Models in Investment and Finance edited by G. P. Szego and K. 
Shell (Amsterdam: North-Holland 1972).
Vasicek, Oldrich A. "A Note on Using Cross-Sectional Information in Bayesian Estimation of 
Security Betas." Journal of Finance, vol. 28, no. 5, 1973, pp. 1233–1239.
Problems
1. Joe has been managing a portfolio over the past year. Performance analysis shows that he has 
realized an


---


### Page 516


Page 509
information ratio of 1 and a t statistic of 1 over this period. He argues that information ratios are 
what matter for value added, and so who cares about t statistics? Is he correct? What can you say 
about Joe's performance?
2. Jane has managed a portfolio for the past 25 years, realizing a t statistic of 2 and an information 
ratio of 0.4. She argues that her t statistic proves her skill. Compare her skill and added value to 
Joe's.
3. Prove the more exact result for the standard error of the information ratio,
Assume that errors in the mean and standard deviation of the residual returns are uncorrelated, and 
use the normal distribution result:
for a sample standard deviation from N observations.
4. Show that changing the information ratio from an annualized to a monthly statistic does not 
improve our ability to measure investment performance. It will still require a 16-year track record to 
demonstrate top-quartile performance with 95 percent confidence. First calculate the standard error 
of a monthly IR. Second, convert a top-quartile IR of 0.5 to its monthly equivalent. Finally, 
calculate the required time period to achieve a t statistic of 2.
5. Using Table 17.2, identify the largest active risk index and industry exposures and the largest risk 
index and industry attributed returns for the Major Market Index versus the S&P 500 from January 
1988 to December 1992. Must the largest attributed returns always correspond to the largest active 
exposures?


---


### Page 517


Page 510
6. Given portfolio returns of {5 percent, 10 percent, –10 percent} and benchmark returns of {1 
percent, 5 percent, 10 percent}, what is the cumulative active return over this period? What are the 
cumulative returns to the portfolio and benchmark?
7. Why should portfolio-based performance analysis be more accurate than returns-based 
performance analysis?
8. How much statistical confidence would you have in an information ratio of 1 measured over 1 
year? How many years of performance data would you need in order to measure an information 
ratio of 1 with 95 percent confidence?
9. Show that a portfolio Sharpe ratio above the benchmark Sharpe ratio implies a positive alpha for 
the portfolio, but that a positive alpha does not necessarily imply a Sharpe ratio above the 
benchmark Sharpe ratio.
Technical Appendix
We will discuss three technical topics in this appendix: how to cumulate attributed returns, how to 
combine forecast and realized risk numbers for performance analysis, and a valuation-based 
approach to performance analysis.
Cumulating Attributed Returns
We will investigate two issues here: cumulating active returns and cumulating more generally 
attributed returns. Let RP(t) be the portfolio's total return in period t, and let RB(t) and RF(t) be the 
total return on the benchmark and the risk-free asset. The compound total return on portfolio P over 
periods 1 through T, RP(1,T), is the product


---


### Page 518


Page 511
Similarly, we calculate the cumulative benchmark return as
Hence the active cumulative return must be
Note that we do not calculate active cumulative returns by somehow cumulating the period-byperiod active returns. For example,
Now consider the more general problem of cumulating attributed returns, and just focus on the 
problem of cumulating the portfolio returns (not active returns). For each period t,
Equation (17A.6) contains many cross-product terms. We would like to write this as
attributing the cumulative return linearly to factors plus a cross-product correction δCP. There are 
two straightforward approaches to defining the cumulative attributed returns, one based on a 
bottom-up view and the other based on a top-down view. The bottom-up view cumulates each 
attributed return in isolation:
The top-down view attributes cumulative returns by deleting each


---


### Page 519


Page 512
factor in turn from the cumulative total return and observing the effect:
We recommend the top-down approach [Equation (17A.9)], which often leads to smaller crossproduct correction terms δCP in Eq. (17A.7). Given that the cross-product term is usually small, and 
that intuition for it is limited, we often attribute the cross-product term back to the factors, 
proportional to either the factor risk or the factor return.
Risk Estimates for Performance Analysis
We observe returns over T periods t = 1, . . . , T and wish to analyze performance. Prior to the 
period, the estimated risk of these returns was σprior(0). The realized risk for the returns is σreal. Both 
risk numbers are sample estimates of the "true" risk. What is the best overall estimate of risk, given 
these two estimates?
According to Bayes, if we have two estimates, x1 with standard error σ1 and x2 with standard error 
σ2, and the estimation errors are uncorrelated, then the best linear unbiased estimate, given these two 
estimates, is
Equation (17A.10) provides the overall estimate with minimum standard error σ.
We also know that the standard error of a sampled variance is approximately
where T is the number of observations in the sample and we assume that the distribution of the 
underlying variable is normal.


---


### Page 520


Page 513
Combining Eqs. (17A.10) and (17A.11), our best risk estimate is
where T0 measures the number of observations11 used for the estimate of σprior(0).
Valuation-based Approach to Performance Analysis
The theory of valuation (Chap. 8) defined valuation multiples υ such that
where p(0) is the current value of the asset based on its possible future values cf(T) at time T. 
Defining total returns as
One aspect of the valuation multiples, which is shown by Eq. (17A.15), is that they fairly price all 
assets. Within the context of the CAPM and APT, all returns are fairly priced with respect to 
portfolio Q. A manifestation of this is that under this adjusted measure, they all have the same value. 
Equation (17A.15) states that the set of possible returns R should be worth $1.00 using the valuation 
multiples υ.
In the valuation-based approach to performance analysis, the benchmark plays the role of portfolio 
Q. We determine the valuation multiples by the requirement that they fairly price the benchmark 
and the risk-free asset. The observed set of benchmark returns and
11We can define T0 implicitly using 
 if we have an estimate of the standard error of 
.


---

