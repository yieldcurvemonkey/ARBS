# Grinold-Kahn Active Portfolio Management

## Pages 21-40


### Page 21


Page 14
are total returns less the total return on a risk-free asset over the same time period. We define3 the 
beta of portfolio P as
Beta is proportional to the covariance between the portfolio's return and the market's return. It is a 
forecast of the future. Notice that the market portfolio has a beta of 1 and risk-free assets have a beta 
of 0.
Although beta is a forward-looking concept, the notion of beta—and indeed the name—comes from 
the simple linear regression of portfolio excess returns rP(t) in periods t = 1, 2, . . . , T on market 
excess returns rM(t) in those same periods. The regression is
We call the estimates of βP and αP obtained from the regression the realized or historical beta and 
alpha in order to distinguish them from their forward-looking counterparts. The estimate shows how 
the portfolios have interacted in the past. Historical beta is a reasonable forecast of the betas that 
will be realized in the future, although it is possible to do better.4
As an example, Table 2.1 shows 60-month historical betas and forward-looking betas predicted by 
BARRA, relative to the S&P 500, for the constituents of the Major Market Index5 through 
December 1992:
Beta is a way of separating risk and return into two parts. If we know a portfolio's beta, we can 
break the excess return
3For a discussion of variance, covariance, and other statistical and mathematical concepts, please refer to 
Appendix C at the end of the book.
4See Rosenberg (1985) for the empirical evidence. There is a tendency for betas to regress toward the mean. A 
stock with a high historical beta in one period will most likely have a lower (but still higher than 1.0) beta in the 
subsequent period. Similarly, a stock with a low beta in one period will most likely have a higher (but less than 1.0) 
beta in the following period. In addition, forecasts of betas based on the fundamental attributes of the company, 
rather than its returns over the past, say, 60 months, turn out to be much better forecasts of future betas.
5The Major Market Index consists effectively of 100 shares of each of 20 major U.S. stocks. As such, it is not 
capitalization-weighted, but rather share-price-weighted.


---


### Page 22


Page 15
TABLE 2.1 
Betas for Major Market Index Constituents
Stock
Historical Beta
BARRA Predicted Beta
American Express
1.21
1.14
AT & T
0.96
0.69
Chevron
0.46
0.66
Coca Cola
0.96
1.03
Disney
1.23
1.13
Dow
1.13
1.05
Dupont
1.09
0.90
Eastman Kodak
0.60
0.93
Exxon
0.46
0.69
General Electric
1.30
1.08
General Motors
0.90
1.15
IBM
0.64
1.30
International Paper
1.18
1.07
Johnson & Johnson
1.13
1.09
McDonalds
1.06
1.03
Merck
1.06
1.11
MMM
0.74
0.97
Philip Morris
0.94
1.00
Procter & Gamble
1.00
1.01
Sears
1.05
1.05
on that portfolio into a market component and a residual component:
In addition, the residual return θP will be uncorrelated with the market return rM, and so the variance 
of portfolio P is
where 
 is the residual variance of portfolio P, i.e., the variance of θP.
Beta allows us to separate the excess returns of any portfolio into two uncorrelated components, a market return 
and a residual return.


---


### Page 23


Page 16
So far, no CAPM. Absolutely no theory or assumptions are needed to get to this point. We can 
always separate a portfolio's return into a component that is perfectly correlated with the market and 
a component that is uncorrelated with the market. It isn't even necessary to have the market portfolio 
M play any special role. The CAPM focuses on the market and says something special about the 
returns that are residual to the market.
The CAPM
The CAPM states that the expected residual return on all stocks and any portfolio is equal to zero, 
i.e., that E{θP} = 0. This means that the expected excess return on the portfolio, E{rP} = µP, is 
determined entirely by the expected excess return on the market, E{rM} = µM, and the portfolio's 
beta, βP. The relationship is simple:
Under the CAPM, the expected residual return on any stock or portfolio is zero. Expected excess returns are 
proportional to the stock's (or portfolio's) beta.
Implicit here is the CAPM assumption that all investors have the same expectations, and differ only 
in their tolerance for risk.
Notice that the CAPM result must hold for the market portfolio. If we sum (on a value-weighted 
basis) the returns of all the stocks, we get the market return, and so the value-weighted sum of the 
residual returns has to be exactly zero. However, the CAPM goes much further and says that the 
expected residual return of each stock is zero.
The CAPM is Sensible
The logic behind the CAPM's assertion is fairly simple. The idea is that investors are compensated 
for taking necessary risks, but not for taking unnecessary risks. The risk in the market portfolio is 
necessary: Market risk is inescapable. The market is the ''hot potato" of risk that must be borne by 
investors in aggregate. Residual risk, on the other hand, is self-imposed. All investors can avoid 
residual risk.


---


### Page 24


Page 17
We can see the role of residual risk by considering the story of three investors, A, B, and C. Investor 
A bears residual risk because he is overweighting some stocks and underweighting others, relative 
to the market. Investor A can think of the other participants in the market as being an investor B 
with an equal amount invested who has residual positions exactly opposite to A's and a very large 
investor C who holds the market portfolio. Investor B is "the other side" for investor A. If the 
expected residual returns for A are positive, then the expected residual returns for B must be 
negative! Any theory that assigns positive expected returns to one investor's residual returns smacks 
of a "greater fool" theory; i.e., there is a group of individuals who hold portfolios with negative 
expected residual returns.
An immediate consequence of this line of reasoning is that investors who don't think they have 
superior information should hold the market portfolio. If you are a "greater fool" and you know it, 
then you can protect yourself by not playing! This type of reasoning, and lower costs, has led to the 
growth in passive investment.
Under the CAPM, an individual whose portfolio differs from the market is playing a zero-sum game. The 
player has additional risk and no additional expected return. This logic leads to passive investing; i.e., buy and 
hold the market portfolio.
Since this book is about active management, we will not follow this line of reasoning. The logic 
conflicts with a basic human trait: Very few people want to admit that they are the "greater fools."6
The CAPM and Efficient Markets Theory
The CAPM isn't the same as efficient markets theory, although the two are consistent. Efficient 
markets theory comes in three strengths: weak, semistrong, and strong. The weak form states that 
investors cannot outperform the market using only historical price
6As part of a class exercise at the Harvard Business School, students were polled about their salary expectations 
and the average salary people in the class would receive. About 80 percent of the students thought they would 
do better than average! This pattern of response has obtained in each year the questions have been asked.


---


### Page 25


Page 18
and volume data. The semistrong form states that investors cannot outperform the market using only 
publicly available information: historical prices plus fundamental data, analysts' published 
recommendations, etc. The strong form of the efficient markets hypothesis states that investors can 
never outperform the market: Market prices contain all relevant information.
The CAPM makes similar statements, although perhaps from a slightly different perspective. For 
any investor whose portfolio doesn't match the market, there must (effectively) be another investor 
with exactly the opposite deviations from the market. So, as long as there are no "greater fools," we 
shouldn't expect either of those investors to outperform the market. Efficient markets theory argues 
that there are no "greater fools" because market prices reflect all useful information.
Expected Returns and Portfolios
We have just described the CAPM's assumption that expected residual returns are zero, and its 
implication that passive investing is optimal. As the technical appendix will treat in detail, in the 
context of mean/variance analysis, we can more generally exactly connect expected returns and 
portfolios. If we input expected returns from the CAPM into an optimizer—which optimally trades 
off portfolio expected return against portfolio variance—the result is the market portfolio.7 Going in 
the other direction, if we start with the market portfolio and assume that it is optimal, we can back 
out the expected returns consistent with that: exactly the CAPM expected returns. In fact, given any 
portfolio defined as optimal, the expected returns to all other portfolios will be proportional to their 
betas with respect to that optimal portfolio.
For this reason, we call the CAPM expected returns the consensus expected returns. They are 
exactly the returns we back out by assuming that the market—the consensus portfolio—is optimal.
Throughout this book, we will find the one-to-one relationship between expected returns and 
portfolios quite useful. An active
7Depending on an individual investor's trade-off between return and risk, the resulting portfolio is actually a 
combination of the market and cash, or of the market and the minimum variance portfolio under the constraint 
of full investment.


---


### Page 26


Page 19
manager, by definition, does not hold the market or consensus portfolio. Hence, this manager's 
expected returns will not match the consensus expected returns.
Ex Post and Ex Ante
The CAPM is about expectations. If we plot the CAPM-derived expected return on any collection of 
stocks or portfolios against the betas of those stocks and portfolios, we find that they lie on a straight
line with an intercept equal to the risk-free rate of interest iF and a slope equal to the expected excess 
return on the market µM. That line, illustrated in Fig. 2.1, is called the security market line.
The picture is drawn for a risk-free interest rate of 5 percent and an expected excess return on the 
market of 7 percent. The four points on the line include the market portfolio M and three portfolios 
P1, P2, and P3 with betas of 0.8, 1.15, and 1.3, respectively.
If we look at the ex post or after the fact returns (these are called realizations), we see a scatter 
diagram of actual excess return against portfolio beta. Figure 2.2 shows a rather small scatter of 
three portfolios along with the market portfolio and the risk-free asset. We can always draw a line 
connecting the risk-free return and the realized market return. This ex post line might be dubbed an 
"insecurity" market line. The ex post line gives the component of return that the CAPM would have 
forecast if we had known
Figure 2.1 
The security market line.


---


### Page 27


Page 20
Figure 2.2 
An ex-post market line.
how the market portfolio was going to perform. In particular, the line will slope downward in 
periods in which the market return is less than the risk-free return.
Notice that we have put P1′, P2′, and P3′, along the line. The actual returns for the portfolios were P1, 
P2, and P3. The differences P1 – P1′, P2 – P2′, and P3 – P3′, are the residual returns on the three 
portfolios. The value-weighted deviations of all stocks from the line will be zero. Portfolio P3 did 
better than its CAPM expectation, so its manager added value in this particular period. Portfolios P1 
and P2, on the other hand, lie below the ex post market line. They did worse than their CAPM 
expectation.
An Example
As an example of CAPM analysis, consider the behavior of one constituent of the Major Market 
Index, American Express, versus the S&P 500 over the 60-month period from January 1988 through 
December 1992. Figure 2.3 plots monthly American Express excess returns against the monthly 
excess returns to the S&P 500.


---


### Page 28


Page 21
Figure 2.3 
Realized excess returns.
Using regression analysis [Eq. (2.2)], we can determine the portfolio historical beta to be 1.21 with a 
standard error of 0.24. The CAPM predicts a residual return of zero. In fact, over this historical 
period, the realized residual return was-78 basis points per month with a standard error of 96 basis 
points: not significant at the 95 percent confidence level. The standard deviation of the monthly 
residual return was 7.05 percent. For this example, the regression coefficient R2 was 0.31.
How Well Does the CAPM Work?
The ability to decompose return and risk into market and residual components depends on our 
ability to forecast betas. The CAPM goes one step further and says that the expected residual return


---


### Page 29


Page 22
on every stock (and therefore every portfolio) is zero. That last step is controversial. A great deal of 
theory and statistical sophistication have been thrown at this question of whether the predictions of 
the CAPM are indeed observed.8 An extensive examination would carry us far from our topic of 
active management. "Chapter Notes" contains references on CAPM tests.
Basically, the CAPM looks good compared to naïve hypotheses, e.g., the expected returns on all 
stocks are the same. It does well, although less well, against abstract statistical tests of the 
hypothesis in Eq. (2.5), where the alternatives are "reject hypothesis" and "cannot reject 
hypothesis." The survival of the CAPM for more than twenty-five years indicates that it is a robust 
and rugged concept that is very difficult to topple.
The true question for the active manager is: How can I use the concepts behind the CAPM to my 
advantage? As we show in the next section, a true believer in the CAPM would have to be 
schizophrenic (or very cynical) to be an active manager.
Relevance for Active Managers
The active manager's goal is to beat the market. The CAPM states that every asset's expected return 
is just proportional to its beta, with expected residual returns equal to zero. Thus, the CAPM appears 
to be gloomy news for the active manager. A CAPM disciple would give successful active 
management only a 50-50 chance. A CAPM disciple would not be an active manager or, more 
significantly, would not hire an active manager.
The CAPM can help the active manager. The CAPM is a theory, and like any theory in the social 
sciences, it is based on assumptions that are not quite accurate. In particular, market players have 
differential information and thus different expectations. Superior information offers managers 
superior opportunities. We need not despair. There is an opportunity to succeed, and the CAPM 
provides some help.
8Most recently, Fama and French (1992) have generated significant publicity by claiming to refute the CAPM. 
But for an alternative interpretation of their results, and a discussion of the remaining uses of CAPM 
machinery, see Black (1993) and Grinold (1993).


---


### Page 30


Page 23
The CAPM in particular and the theory of efficient markets in general help active managers by 
focusing their attention on how they expect to add value. The burden of proof has shifted to the 
active manager. A manager must be able to defend why her or his insights should produce superior 
returns in a somewhat efficient market. While bearing the burden of proof may not be pleasant, it 
does force the manager to dig deeper and think more clearly in developing and marketing active 
strategy ideas. The active manager is thus on the defensive, and should be less likely to confuse luck 
with skill and more likely to eliminate some nonproductive ideas, since they cannot pass scrutiny in 
a market with a modicum of efficiency.
The CAPM has shifted the burden of proof to the active manager.
The CAPM also helps active managers by distinguishing between the market and the residual 
component of return. Recall that this decomposition of return does not require any theory. It requires 
only good forecasts of beta. This can assist the manager's effort to control market risk; many active 
managers feel that they cannot accurately time the market and would prefer to maintain a portfolio 
beta close to 1. The decomposition of risk allows these managers to avoid taking active market 
positions.
The separation of return into market and residual components can help the active manager's 
research. There is no need to forecast the expected excess market return µM if you control beta. The 
manager can focus research on forecasting residual returns. The consensus expectations for the 
residual returns are zero; that's a convenient starting point. The CAPM provides consensus expected 
returns against which the manager can contrast his or her ideas.
The ideas behind the CAPM help the active manager to avoid the risk of market timing and to focus research 
on residual returns that have a consensus expectation of zero.
Forecasts of Beta and Expected Market Returns
The CAPM forecasts of expected return will be only as good as the forecasts of beta. There are a 
multitude of procedures for forecasting beta. The simplest involves using historical beta derived 
from


---


### Page 31


Page 24
an analysis of past returns. A slightly more complicated procedure invokes a bayesian adjustment to 
these historical betas. In Chap. 3, "Risk," we will discuss a more adaptive and forward-looking 
approach to forecasting risk in general and beta in particular.
We can estimate the expected excess market return µM from an analysis of historical returns. Notice 
that any beta-neutral policy would not require an accurate estimate of µM. With a portfolio beta 
equal to 1.0, the market excess return will not contribute to active return.
Summary
This chapter has presented the capital asset pricing model (CAPM) and discussed its motivation, its 
implications, and its relevance for active managers. In a later chapter, we will discuss some of the 
theoretical shortcomings of the CAPM along with an alternative model of expected asset returns 
called the APT.
Problems
1. In December 1992, Sears had a predicted beta of 1.05 with respect to the S&P 500 index. If the 
S&P 500 index subsequently underperformed Treasury bills by 5.0 percent, what would be the 
expected excess return to Sears?
2. If the long-term expected excess return to the S&P 500 index is 7 percent per year, what is the 
expected excess return to Sears?
3. Assume that residual returns are uncorrelated across stocks. Stock A has a beta of 1.15 and a 
volatility of 35 percent. Stock B has a beta of 0.95 and a volatility of 33 percent. If the market 
volatility is 20 percent, what is the correlation of stock A with stock B? Which stock has higher 
residual volatility?
4. What set of expected returns would lead us to invest 100 percent in GE stock?


---


### Page 32


Page 25
5. According to the CAPM, what is the expected residual return of an active manager?
Chapter Notes
The CAPM was developed by Sharpe (1964). Treynor (1961), Lintner (1965), and Mossin (1966) 
were on roughly the same track in the same era.
There is no controversy over the logic that links the premises of the CAPM to its conclusions. There 
is, however, some discussion of the validity of the predictions that the CAPM gives us. General 
discussions of this point can be found in Mullins (1982) or in Sharpe and Alexander's text (1990). 
The recent publicity concerning the validity of the CAPM focused on the results of Fama and 
French (1992). For a discussion of their results, see Black (1993) and Grinold (1993). A more 
advanced treatment of the econometric issues involved in this issue can be found in Litzenberger 
and Huang (1988).
The technical appendix assumes some familiarity with efficient set theory. This can be found in the 
appendix to Roll (1977), Merton (1972), Ingersoll (1987), or Litzenberger and Huang (1988). The 
technical appendix also explores connections between expected returns and portfolios, a topic first 
investigated by Black (1972).
References
Black, Fischer. "Capital Market Equilibrium with Restricted Borrowing." Journal of Business, vol. 
45, July 1972, pp. 444–455.
———. "Estimating Expected Returns." Financial Analysts Journal, vol. 49, September/October 
1993, pp. 36–38.
Fama, Eugene F., and Kenneth R. French. "The Cross-Section of Expected Stock Returns." Journal 
of Finance, vol. 47, no. 2, June 1992, pp. 427–465.
Grauer, R., and N. Hakansson. "Higher Return, Lower Risk: Historical Returns on Long-Run 
Actually Managed Portfolios of Stocks, Bonds, and Bills."Financial Analysts Journal, vol. 38, no. 
2, March/April 1982, pp. 2–16.
Grinold, Richard C. "Is Beta Dead Again?" Financial Analysts Journal, vol. 49, July/August 1993, 
pp. 28–34.
Ingersoll, Jonathan E., Jr. Theory of Financial Decision Making (Savage, Md.: Rowman & 
Littlefield Publishers, Inc., 1987).
Lintner, John. "The Valuation of Risk Assets and the Selection of Risky Investments in Stock 
Portfolios and Capital Budgets." Review of Economics and Statistics, vol. 47, no. 1, February 1965, 
pp. 13–37.


---


### Page 33


Page 26
———. ''Security Prices, Risk, and Maximal Gains from Diversification." Journal of Finance, vol. 
20, no. 4, December 1965, pp. 587–615.
Litzenberger, Robert H., and Chi-Fu Huang. Foundations for Financial Economics (New York: 
North-Holland, 1988).
Markowitz, H. M. Portfolio Selection: Efficient Diversification of Investment. Cowles Foundation 
Monograph 16 (New Haven, Conn.: Yale University Press, 1959).
Merton, Robert C. "An Analytical Derivation of the Efficient Portfolio." Journal of Financial and 
Quantitative Analysis, vol. 7, September 1972, pp. 1851–1872.
Mossin, Jan. "Equilibrium in a Capital Asset Market." Econometrica, vol. 34, no. 4, October 1966, 
pp. 768–783.
Mullins, D. W., Jr. "Does the Capital Asset Pricing Model Work?" Harvard Business Review, 
January–February 1982, pp. 105–114.
Roll, Richard. "A Critique of the Asset Pricing Theory's Tests." Journal of Financial Economics, 
March 1977, pp. 129–176.
Rosenberg, Barr. "Prediction of Common Stock Betas." Journal of Portfolio Management, vol. 12, 
no. 2, Winter 1985, pp. 5–14.
Rudd, Andrew, and Henry K. Clasing, Jr. Modern Portfolio Theory, 2d ed. (Orinda, Calif.: Andrew 
Rudd, 1988).
Sharpe, William F. "Capital Asset Prices: A Theory of Market Equilibrium under Conditions of 
Risk." Journal of Finance, vol. 19, no. 3, September 1964, pp. 425–442.
———. "The Sharpe Ratio." Journal of Portfolio Management, vol. 21, no. 1, Fall 1994, pp. 49–58.
Sharpe, William F., and Gordon J. Alexander. Investments (Englewood Cliffs, N.J.: Prentice-Hall, 
1990).
Treynor, J. L. "Toward a Theory of the Market Value of Risky Assets." Unpublished manuscript, 
1961.
Technical Appendix
This appendix details results of mean/variance analysis that are fundamental to the CAPM and, to a 
certain extent, the APT. It begins with mathematical notation and preliminary assumptions. It then 
introduces the machinery of "characteristic portfolios" defined by distinctive risk and return 
properties. This machinery will suffice to derive the results of CAPM, and will prove useful in later 
chapters as well.
Particular characteristic portfolios include portfolio C, the minimum-variance portfolio, and 
portfolio Q, the portfolio with the highest ratio of expected return to standard deviation of return 
(highest Sharpe ratio). The efficient frontier describes a set of characteristic portfolios, defined by 
minimum variance for each achievable


---


### Page 34


Page 27
level of return. The CAPM reduces to the proposition that portfolioQ is the market portfolio.
Mathematical Notation
For clarity, we will represent scalars in plain text, vectors as bold lowercase letters, and matrices as 
bold uppercase letters.
h = the vector of risky asset holdings, i.e., a portfolio's 
percentage weights in each asset
f = the vector of expected excess returns
µ = the vector of expected excess returns under the CAPM; 
i.e., the CAPM holds when f = µ.
V = the covariance matrix of excess returns for the risky 
assets (assumed nonsingular)
β = the vector of asset betas
e = the vector of ones (i.e., en = 1)
We define "risk" as the annual standard deviation of excess return.
Assumptions
We consider a single period with no rebalancing of the portfolio within the period. The underlying 
assumptions are:
A1 A risk-free asset exists.
A2 All first and second moments exist.
A3 It is not possible to build a fully invested portfolio that 
has zero risk.
A4 The expected excess return on portfolio C, the fully 
invested portfolio with minimum risk, is positive.
We are keeping score in nominal terms, so for a reasonably short period there should be an 
instrument whose return is certain (a U.S. Treasury bill, for example).
In later chapters we will dispense with requirement A4, that the fully invested minimum-risk 
portfolio has a positive expected excess return. This certainly holds for any reasonable set of 
numbers; however, it is not strictly necessary for many of the results that appear in these technical 
appendixes. See the technical appendix of Chapter 7 for more on that topic.


---


### Page 35


Page 28
Characteristic Portfolios
Assets have a multitude of attributes, such as betas, expected returns, earnings-to-price (E/P) ratios, 
capitalization, membership in an economic sector, and the like. In this appendix, we will associate a 
characteristic portfolio with each asset attribute.
The characteristic portfolio will uniquely capture the defining attribute. The characteristic portfolio 
machinery will allow us to connect attributes and portfolios, and to identify a portfolio's exposure to 
the attribute in terms of its covariance with the characteristic portfolio.
This process is reversible. We can start with a portfolio and find the attribute that this portfolio 
expresses most effectively.
Once we have established the relationship between the attributes and the portfolios, the CAPM 
becomes an economically motivated statement about the characteristic portfolio of the expected 
excess returns.
Let aT = {a1, a2, . . . , aN} be any vector of asset attributes or characteristics. The exposure of 
portfolio hP to attribute a is simply 
Proposition 1
1. For any attribute a 
 0 there is a unique portfolio ha that has minimum risk and unit exposure to 
a. The holdings of the characteristic portfolio ha, are
Characteristic portfolios are not necessarily fully invested. They can include long and short 
positions and have significant leverage. Take the characteristic portfolio for earnings-to-price ratios. 
Since typical earnings-to-price ratios range roughly from 0.15 to 0, the characteristic portfolio will 
require leverage to generate a portfolio earnings-to-price ratio of 1. This leverage does not cause us 
problems, for two reasons. First, we typically analyze return per unit of risk, accounting for the 
leverage. Second, when it comes to building investable portfolios, we can always combine the 
bench-


---


### Page 36


Page 29
mark with a small amount of the characteristic portfolio, effectively deleveraging it.
2. The variance of the characteristic portfolio ha is given by
3. The beta of all assets with respect to portfolio ha is equal to a:
4. Consider two attributes a and d with characteristic portfolios ha and hd. Let ad and da be, 
respectively, the exposure of portfolio hd to characteristic a and the exposure of portfolio ha to 
characteristic d. The covariance of the characteristic portfolios satisfies
5. If κ is a positive scalar, then the characteristic portfolio of κa is ha/κ. Because characteristic 
portfolios have unit exposure to the attribute, if we multiply the attribute by κ, we will need to 
divide the characteristic portfolio by κ to preserve unit exposure.
6. If characteristic a is a weighted combination of characteristics d and f, then the characteristic 
portfolio ofa is a weighted combination of the characteristic portfolios of d and f; in particular, if a = 
κdd + κff, then
Proof
We derive the holdings of the characteristic portfolio by solving the defining optimization problem. 
The portfolio is minimum risk, given the constraint that its exposure to characteristic a


---


### Page 37


Page 30
equals 1. The first-order conditions for minimizing hTVh subject to the constraint hTa = 1 are
where θ is the Lagrange multiplier. Equation (2A.8) implies that h is proportional to V–1a, with 
proportionality constant θ. We can then use Eq. (2A.7) to solve for θ. The results are
This proves item 1.
We can verify item 2 using Eq. (2A.9) and the definition of portfolio variance. We can verify item 3 
similarly, using the definition of β with respect to portfolio P as 
For item (4), note that
Items 5 and 6 simply follow from substituting the result in 3 and clearing up the debris.
Examples
Portfolio C
Suppose


---


### Page 38


Page 31
is the attribute. Every portfolio's exposure to e, 
 measures the extent of its investment. If 
ep = 1, then the portfolio is fully invested. Portfolio C, the characteristic portfolio for attribute e, is 
the minimum-risk fully invested portfolio:
Equation (2A.16) demonstrates that every asset has a beta of 1 with respect to C.9 In addition, for 
any portfolio P, we have
the covariance of any fully invested portfolio (ep = 1) with portfolioC is 
.
Portfolio B
Suppose β is the attribute, where beta is defined by some benchmark portfolio B:
Then the benchmark is the characteristic portfolio of beta, i.e.,
9Here is some intuition behind this result. As we will learn in Chapter 3, each asset's marginal contribution to 
portfolio risk is proportional to its beta with respect to the portfolio. Since portfolio C is the minimum-risk 
portfolio, each asset must have identical marginal contribution to risk. Otherwise we could trade assets to 
reduce portfolio risk. So each asset has identical marginal contribution to risk, and hence identical beta. Since 
the beta of the portfolio with respect to itself must be 1, the value of those identical asset betas must be 1.


---


### Page 39


Page 32
and
So the benchmark is the minimum-risk portfolio with a beta of 1. This makes sense intuitively. All β
= 1 portfolios have the same systematic risk. Since the benchmark has zero residual risk, it has the 
minimum total risk of all β = 1 portfolios.
Using item 4 of the proposition, we see that the relationship between portfolios B and C is
Portfolio q
The expected excess returns f have portfolio q (discussed below) as their characteristic portfolio.
Sharpe Ratio
For any risky portfolio P (σP > 0), the Sharpe ratio is defined as the expected excess return on 
portfolio P, fP, divided by the risk of portfolio P:
Proposition 2: 
Portfolio with the Maximum Sharpe Ratio
Let q be the characteristic portfolio of the expected excess returns f:


---


### Page 40


Page 33
4. If ρP,q is the correlation between portfolios P and q, then
5. The fraction of q invested in risky assets is given by
Proof
For any portfolio hP, the Sharpe ratio is SRP = fP/σP. For any positive constant κ the portfolio with 
holdings κhP will also have a Sharpe ratio equal to SRP. Thus, in looking for the maximum Sharpe 
ratio, we can set the expected excess return to 1 and minimize risk. We then minimize hTVh subject 
to the constraint that hTf = 1. This is just the problem we solved to get hq, the characteristic portfolio 
of f.
Items 2 and 3 are just properties of the characteristic portfolio. For 4, premultiply 3 by hP and divide 
by σP. This yields
Part 5 follows from Eq. (2A.4):
Portfolio A
Define alpha as α = f – β fB. Let hA be the characteristic portfolio for alpha, the minimum-risk 
portfolio with alpha of 100 percent. (Portfolio A will involve significant leverage.) According to Eq. 
(2A.5), we can express hA in terms of hB and hq. From Eq. (2A.4), we see that the relationship 
between alpha and beta is


---

