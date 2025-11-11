# Grinold-Kahn Active Portfolio Management

## Pages 201-220


### Page 201


Page 195
• The specific returns u are uncorrelated with the factor returns b.
• The factor exposures X are known with certainty at the start of the period.
With these assumptions, the N by N asset covariance matrix is
where F is the K by K covariance of the factors and Δ is an N byN matrix that gives the covariance 
of the specific returns. We usually assume that Δ is a diagonal matrix, although that is not necessary.
We refer to the factor model as (X, F, Δ). We say that a factor model explains expected excess 
returns f if we can express the vector of expected excess returns f as a linear combination of the 
factor exposures X. The model (X, F, Δ) explains expected excess returns if there is a K-element 
vector of factor forecasts m such that
Equation (7A.4) gives us an expression for f. In the appendix to Chap. 2, we derived another 
expression for f involving portfolioQ. Let's look for the link between these two expressions.
The N-element vector of stock covariances with respect to portfolio Q is
From Eq. (2A.36) (Proposition 3 in the technical appendix to Chap. 2), we know that the expected 
excess returns are
Compare Eqs. (7A.4) and (7A.6). We are getting perilously close to the APT result. As an initial 
stab, we could write m* = κQ · F · XT · hQ. Then
One alternative is to ignore the second term and live with


---


### Page 202


Page 196
a little imperfection. To attain perfection, however, we need one additional assumption. We show 
below that this assumption works and that we need to make it; i.e., this assumption is both necessary 
and sufficient. First a definition: A portfolio P is diversified with respect to the factor model (X, F, 
Δ) if portfolio P has minimal risk among all portfolios that have the same factor exposures as 
portfolio P; i.e., of all portfolios h with XT · hP = xP, portfolio P has the least risk.
Our assumption is that portfolio Q is diversified with respect to the factor model (X, F, Δ).
Proposition 1 (APT)
The factor model (X, F, Δ) explains expected excess returns if and only if portfolio Q is diversified 
with respect to (X, F, Δ).
Proof
Suppose first that portfolio Q is diversified with respect to (X, F, Δ). Now we can find the portfolio 
with exposures xQ that has minimal risk by solving
The first-order conditions for this problem are satisfied by the optimal solution h* and a K-element 
vector of Lagrange multipliers π that satisfy
Since portfolio Q is diversified with respect to (X, F, Δ), then hQ =h* is the optimal solution. 
Therefore
Combining Eq. (7A.12) with Eqs. (7A.6), (7A.7), and (7A.4) leads to
and the factor model (X, F, Δ) explains the expected excess returns.
For the converse, suppose that the factor model (X, F, Δ) explains the expected excess returns and 
that portfolio Q is not diversified with respect to (X, F, Δ). Then there exists a portfolio P with


---


### Page 203


Page 197
the same exposures as portfolio Q, i.e., xP = XT · hP = xQ, and less risk than portfolio Q, i.e., 
. However, we have fP = fQ, since the factor exposures determine the expected returns, and 
portfolios P and Q have identical factor exposures. So 
.
Portfolio P cannot be all cash, since the expected excess return on cash is zero. Therefore portfolio 
P is a mixture of cash and a nonzero fraction of some fully invested portfolio P*. It must be that 
fP/σP = fP*/σP*. Recall, however, that portfolio Q is the fully invested portfolio with the largest 
possible ratio of expected excess return to risk. This contradiction establishes the point: Portfolio Q 
must be diversified with respect to (X, F, Δ).
Exercises
1. A factor model contains an intercept if some weighted combination of the columns of X is equal 
to a vector of 1s. This will, of course, be true if one of the columns of X is a column of 1s. It will 
also be true if X contains a classification of stocks by industry or economic sector. The technical 
requirement for a model to have an intercept is that there exists a K-element vector g such that e = X
· g. Assume that the model contains an intercept, and demonstrate that we can then determine the 
fraction of the portfolio invested in risky assets by looking only at the portfolio's factor exposures.
2. Show that a model that does not contain an intercept is indeed strange. In particular, show there 
will be a fully invested portfolio with zero exposures to all the factors—a portfolio P with 
(fully invested) and xP = XT · hP = 0 (zero exposure to each factor).
Applications Exercises
1. What is the percentage of unexplained variance in the CAPMMI portfolio? Does this portfolio 
qualify as highly diversified? How much would it be possible to lower the risk of the CAPMMI in a 
portfolio with identical factor exposures?


---


### Page 204


Page 198
2. Assume an excess return forecast of 5 percent per year for a value factor, excess return of –1 
percent per year for a size factor, and excess return forecasts of zero for all other factors. Using the 
CAPMMI as a benchmark, what MMI asset has the highest alpha? What is its value?


---


### Page 205


Page 199
Chapter 8— 
Valuation in Theory
Introduction
Valuation is the central concept of active management. Active managers must believe that their 
assessment of value is better than the market or consensus assessment. In this chapter, we describe a 
basic theory of valuation. The following chapters will illustrate practical valuation procedures and 
any links that these might have with theory.
This chapter contains three important messages:
• The modern theory of valuation connects stock values to risk-adjusted expected cash flows.
• The theory is closely related to the theory of option pricing, and is consistent with the CAPM and 
the APT.
• Valuation (and misvaluation) is connected to expected returns.
The Modern Theory of Valuation
The modern theory of asset valuation is general, esoteric, and worth studying. The theory provides a 
framework for judging more ad hoc and practical valuation methods.
We start with the important premise that a stock's value is derived from the cash flows an investor 
can obtain from owning the stock. These cash flows arise as dividends or as the future value


---


### Page 206


Page 200
of the stock realized by selling the stock.1 The key to the theory will be discounting these uncertain 
cash flows back to the present. This is the same task required for option pricing, and readers familiar 
with option pricing theory will recognize the similarities (which we will make more explicit in the 
technical appendix).
Certain Cash Flows
In the simplest case, the investor will obtain a certain cash flow cf(t) at future time t. To make it 
even simpler, we assume a constant risk-free interest rate that applies over all maturities. Let iF be 
the (annual) return on a risk-free investment. When interest rates are 6 percent annually, then iF = 
0.06. The present value of a promised $1.00 in 1 year is 1/(1 + iF). The promise of $1.00 in t years is 
1/(1 + iF)t and the present value of cf(t) dollars in t years is
Equation (8.1) is the basis for valuing fixed-income instruments with certain cash flows. Given a 
stream of cash flows, e.g., cf(1) in 1 year, cf(2) in 2 years, etc., the valuation formula becomes
For example, if we have a promise of 6 dollars in 1 year and 10 dollars in 3 years and iF = 0.06, we 
find
Uncertain Cash Flows
Equation (8.1) fails when the cash flows are uncertain. Uncertainty means that there is more than 
one possible value for the future
1If the stock is fairly valued, it doesn't matter whether we consider a sale in five years or six months. In 
practice, it may matter, since the key to using the valuation scheme is to find some future time when the stock 
will be fairly valued, and work backward toward a current fair value.


---


### Page 207


Page 201
cash flows. We need a way to describe those possibilities. We do this by listing the possible 
outcomes at time t and determining the probability of each outcome. This is easier said than done in 
practice, but remember, this is the theory chapter. Let's push on bravely and ask what we would do 
next if we could define both the possible future cash flows and the probability of each outcome.
We can index the possible outcomes at time t by s (for states). Let π(t,s) be the probability of 
outcome s at time t, and let cf(t,s) be the uncertain cash flow at time t in state s. The probabilities are 
nonnegative and sum to 1; i.e., 
for every t.
As an example, consider a 1-month period, t = 1/12, and a stock currently valued at 50. In 1 month 
its value (sale price plus any dividend paid in the month) will be either cf(t,1) = 49 or cf(t,2) = 53. 
The outcomes are equally likely; π(t,1) = π(t,2) = 0.5. The risk-free interest over the year is 6 
percent. The expected cash flow is 51, and the standard deviation is 2.
Given this information, how should we value these uncertain cash flows? The simplest and most 
tempting way is to generalize Eq. (8.1), replacing certain cash flows with expected cash flows:
Unfortunately, this doesn't work. Expectations generally overestimate the stock's value. When the 
cash flows are uncertain, we usually find
In our example, the discounted expected cash flows lead to a value of 50.75, but the current price is 
50. The problem is that expected cash flows do not take account of risk. An instrument with an 
expected but uncertain cash flow of 51 should not have the same price as an instrument with a 
certain cash flow of 51. The two have the same expected cash flows, but one is certain and one is 
not. We must dig deeper to find a valuation formula.


---


### Page 208


Page 202
The Valuation Formula
Before we present a valuation formula, we can list the properties that a reasonable formula should 
display. There are several.2
1. If all future cash flows are nonnegative, the value is nonnegative.
2. If we double (or triple or halve) the cash flows, the value should change in the same proportion.
3. If we add two sets of cash flows, the value of the total cash flow should be the sum of the values 
of each separately.
4. The valuation formula should reduce to Eq. (8.1) in the case of certain cash flows.
5. The formula should agree with the market value of securities.
Property 1 is certainly sensible; if we can't lose and we might gain, the opportunity should be worth 
something. Property 2 says that the price of six shares is six times the price of one share. Property 3 
combined with property 2 says that our valuation rule works for portfolios. We can value each stock 
in the portfolio and know that the portfolio's value is simply the weighted sum of the values for each 
stock separately. Property 3 not only lets us combine stocks into portfolios, but also allows us to 
value each cash flow in a stream of cash flows separately. Thus we could value next quarter's 
dividend separately from the dividend the quarter following. The cash flows for the 3-month and 6month dividends may be highly correlated, but that doesn't matter; the valuation formula should still 
get each right.
Property 3 also lets us see the flexibility of this valuation notion. Suppose we have a stock that pays 
a quarterly dividend and the next dividend occurs in 3 months. Rather than consider an indefinite 
sequence of dividends, we can always consider the stock as the promise of the next four dividends 
plus the price of
2We omit from this list the technical stipulation that if π(t,s*) = 0 for some state s* and cf(t,s*) = 1, but cf(t,s) = 
0 for s 
 s*, the value of the cash flow must be zero. We attach no value to promised cash flows for outcomes 
that can't happen, e.g., a put option with an exercise price of –10.


---


### Page 209


Page 203
the stock in 1 year. The price in 1 year is the final cash flow that we receive. The 1 year was 
arbitrary. We could have used the price in 1 month, before the first dividend, or in 2 years, after 
eight dividends. The valuation formula should give us the same answer no matter how we represent 
the cash flows!
Property 4 says that we can value a certain cash flow of any maturity. This is clearly a prerequisite 
to valuing uncertain cash flows of any maturity. Equation (8.1) is based on a constant interest rate. 
We can easily generalize it to allow for risk-free rates that depend on maturity.
Property 5 says that the valuation formula works. This is where the active manager and the 
economist part company. The active manager is interested in using the concept to find stocks for 
which the formula is not working. In practice, property 5 can be used to say that the valuation is 
correct on average or within certain groups. The active manager is free to look within those groups 
for under- and overpriced stocks.
We know the properties that we want. How do we get them?
Risk-Adjusted Expectations
There are two ways to modify the right side of Eq. (8.5) in order to get a straightforward 
relationship like Eq. (8.1). One possibility is to introduce a risk-adjusted interest rate. Then we could 
discount the expected cash flows at the higher (one presumes) rate of interest and therefore lower 
their value. This seems like a good idea, and, as we'll see in the next chapter, it is used in practice. It 
is just a straightforward extension of the CAPM and the APT, which state
where cf(t) is the stock value in 1 year, and so
Here the risk-adjusted interest rate is based on the asset's beta and


---


### Page 210


Page 204
the expected excess return to portfolio Q. The term iF + β · fQ is sometimes called the equity cost of 
capital.
While this risk-adjusted interest rate is simple and easy to understand, this valuation approach can 
break down. In particular, imagine a coin-toss security worth $100,000 (if heads) or –$100,000 (if 
tails). The expected cash flow is zero. Any attempt to value this by adjusting the discount rate will 
still get zero.3
The modern theory of valuation employs the alternative modification of Eq. (8.5): risk-adjusted 
expectations E*{cf(t)}. As we will see, this approach will go far beyond Eq. (8.7) in providing 
insight into valuation and unifying concepts from the CAPM, the APT, and options pricing. By 
introducing a unique risk-adjusted probability distribution, we will be able to consistently discount 
all adjusted expected cash flows at the same risk-free rate.
We obtain the risk adjustment by introducing value multiples4 υ(t,s), so the modified expectation 
can be written as
where υ(t,s) is
• Positive
• With expected value 1
• A function of the return to portfolio Q and proportional to the total return on a portfolio S, the 
portfolio with minimum second moment of total return (see appendix)
In the technical appendix, we will show that these valuation multiples exist as long as there are no 
arbitrage opportunities in the valuation scheme. Arbitrage can occur if we can start with a 
nonpositive amount of money at t = 0 and have all outcomes nonnegative with at least one outcome 
positive.
3In Eq. (8.7), this situation leads to both the numerator and the denominator approaching zero. See Problem 3 
for more details.
4Technically, υ(t,s) is a Radon-Nikodyn derivative, and π*(t,s) = υ(t,s) · π(t,s) is a Martingale equivalent measure.


---


### Page 211


Page 205
With this definition of the risk-adjusted expectations, we obtain our valuation formula:
All modern valuation theories, including option theory, the CAPM, and the APT, use valuation 
formulas that have the form of Eq. (8.9). The technical appendix will discuss this in more detail.
Let's check that Eq. (8.9) has the required valuation properties. Since υ(t) is positive, property 1 will 
hold: Nonnegative cash flows will lead to nonnegative risk-adjusted expectations E*{cf(t)} and, by 
Eq. (8.9), nonnegative values.
The valuation rule is linear, so properties 2 and 3 have to hold. That means that Eq. (8.9) has the 
portfolio property. If stock n has uncertain cash flows cfn(t), and the weight of stock n in portfolio P 
is hP,n, then the portfolio's cash flow is 
, and the value of portfolio P is
is the value of stock n valued in isolation.
If the cash flow cf(t) is certain, then
The first equality follows from the definition of E*, the second equality because cf(t) is certain, and 
the third equality because υ(t) has expected value of 1. This means that property 4 is true: Eq. (8.9) 
will agree with Eq. (8.1) when the cash flows are certain.
We hope that property 5 holds, at least on average. If property 5 held for all stocks, the active 
manager would not find any opportunities in the marketplace.


---


### Page 212


Page 206
Interpretations
The value multiples υ(t,s) help define a new set of probabilities π*(t,s) = π(t,s) · υ(t,s). The riskadjusted expectation E* uses the modified set of probabilities.
In the simple example used previously, the outcomes cf(t,1) = 49 and cf(t,2) = 53 are equally likely, 
π(t,1) = π(t,2) = 0.5, and the risk-free interest over the year is 6 percent, iF = 0.06. We find (see the 
appendix) that υ(t,1) = 1.38 and υ(t,2) = 0.62. This is consistent with properties 1 through 5. The 
altered probabilities are π*(t,1) = 0.5 · 1.38 = 0.69 and π*(t,2) = 0.5 · 0.62 = 0.31. The valuation for 
the risky stock works out correctly:
The Role of Covariance
The definition of covariance and the fact that E{υ(t)} = 1, can be used to link the true and riskadjusted expectations of cf(t):
Equations (8.5) and (8.9) imply that the covariance term will, in general, be negative; in our 
example, we have E*{cf(t)} = 50.24 and E{cf(t)} = 51, and so the covariance term is –0.76. This is 
the explicit penalty for the risk. Its present value is –0.756.
An alternative interpretation of the valuation formula is that the value multiples modify the cash 
flows. The value multiples υ(t,s) change the cash flows by amplifying some, if υ(t,s) > 1, and 
reducing others, if υ(t,s) < 1. Since the value multiples have expected value equal to 1, they are on 
average unbiased. For our example, the rescaled cash flows are 67.62 = 1.38 · 49 and 32.86 = 0.62 · 
53.
Suppose that cfM(t) is proportional to the total return on the market portfolio. Then, the negative 
covariance indicates that υ(t,s) will tend to be less than 1 when the market is doing better than its 
average (good times) and υ(t,s) will tend to be larger than 1.0 when the market is below its average. 
The expectations E* makes the risk adjustment by placing a lower value on good-time cash flows as 
compared to bad-time cash flows. There is no great surprise


---


### Page 213


Page 207
here. This means that the marginal amount of cash flow is worth more when cash flow in general is 
scarce.
Market-Dependent Valuation
According to the modern theory of valuation, the key elements of Eq. (8.9), both the risk-free rate of 
interest and the value multipliers υ(t,s), are market-dependent and not stock-dependent. The only 
stock information needed is the potential cash flows cf(t,s). We use the same υ(t,s) and the same iF 
for all instruments: for IBM stock, for GM puts, or for the S&P 500 portfolio. This critical property 
arises in all modern asset valuation theories, including the CAPM and the APT, which assert that 
only systematic risks are priced.
The APT frames this issue in the context of arbitrage-free pricing: that assets with identical 
exposures to nondiversifiable risks should have identical returns. This notion of arbitrage-free 
pricing is critical to proving that the value multiples cannot depend on individual stock returns, but 
only on portfolio Q returns.
We have discovered a simple formula for the value of a stock providing a sequence of uncertain 
cash flows. The formula uses adjusted expectations of the cash flows and discounts those adjusted 
expectations at market rates of interest to obtain a present value for the stock. In some cases, such as 
option valuation and variants of the CAPM, explicit formulas allow us to calculate the modified 
cash flows. In other cases, such as the APT, these modified expectations exist, although we don't 
have specific information for calculating them.5 The appendix includes examples of these 
applications.
Value and Expected Return
We can now link formulas for expected return, i.e., the CAPM and the APT, and the valuation 
formula just described. Consider a stock currently priced at p(0), paying a dividend d at the end of 1 
year, and with an uncertain price p(1) at the end of the year. Assume
5If we knew the true APT factors, so that we could calculate portfolio Q or portfolio S, then we could calculate 
the modified cash flows.


---


### Page 214


Page 208
that the stock is fairly valued now and will be fairly valued at the end of the year. If we sell the stock 
at the end of the year, the cash flow will be the dividend plus the sale price: cf(1) = d + p(1). The 
valuation formula over one period is
If p(0) 
 0, then we can convert Eq. (8.15) to an expected return equation. Define total return R = [d
+ p(1)]/p(0). Divide Eq. (8.15) by p(0), and multiply by 1 + iF. Then recall that E{υ(1)} = 1. The net 
result is
Equation (8.16) says that the expected excess return on all stocks is determined by their covariance 
with υ. This result is suspiciously close to the CAPM and the APT results, that the expected excess 
return on every stock is determined by its covariance with portfolioQ (which for the CAPM is the 
market). The technical appendix will show, in fact, that υ is a function of the return to portfolio Q 
and proportional to the return to a portfolio S, which is a combination of the risk-free asset and 
portfolio Q. So we will relate Eq. (8.16) to the CAPM and the APT. And, not only can we derive 
Eq. (8.16) from Eq. (8.15), we can also derive Eq. (8.15) from Eq. (8.16). Our previously derived 
expected return formulas imply valuation as in Eq. (8.15).
Equation (8.17) also demonstrates that under the modified probabilities, the expected return on the 
risky investment is equal to the return on the risk-free investment. In fact, under the modified 
expectations, all stocks have (modified) expected returns equal to the risk-free return.
What if the market price and the model price don't agree? Suppose we start with an asset that has a 
market value p(0,mkt) that is not equal to zero and is not properly valued:


---


### Page 215


Page 209
Define κ and γ such that
The parameter k measures the extent of misvaluation of the stock; it is the percentage difference 
between the fitted and market prices at time 0. The parameter γ measures the persistence of the 
misvaluation: how long it will take for the market to learn what we know. Presumably 0 ≤ γ ≤ 1. If 
this is a ''slow idea," then γ will be close to 1.0; much of the mispricing will remain. If this is a "fast 
idea," then γ will be close to 0. We can think of –0.69/In{γ} as the halflife of the misvaluation, the 
number of years it will take for half the misvaluation to disappear.
Equations (8.16), (8.19), and (8.20) yield6
Equation (8.22) breaks the expected return into what we would expect if the stock were fairly valued 
and a second term that corrects for the market's incorrect valuation of the stock. Notice that α = 0 if 
either k = 0 or γ = 1; it is no good if the world never learns that this stock is improperly valued. 
Also, if γ = 0, then α = (1 + iF) · k; we realize the full benefit, plus interest, over the period.
Table 8.1 shows the alphas we get for different levels of k and γ. It assumes a 6 percent annual 
interest rate.
6Define R* as the return to the fairly priced asset, and show that R is proportional to R*. Equation (8.21) then 
follows directly from Eq. (8.16).


---


### Page 216


Page 210
TABLE 8.1
 
γ
κ
0.0
0.2
0.4
0.6
0.8
1%
1.06%
0.85%
0.63%
0.42%
0.21%
5%
5.30%
4.20%
3.12%
2.06%
1.02%
10%
10.60%
8.31%
6.12%
4.00%
1.96%
25%
26.50%
20.19%
14.45%
9.22%
4.42%
50%
53.00%
38.55%
26.50%
16.31%
7.57%
Summary
The modern theory of valuation prices uncertain future cash flows by risk-adjusting the expected 
cash flows and discounting them to the present using the risk-free rate. This theory is consistent with 
the CAPM and APT models, which forecast expected returns; and in fact the risk-adjusting 
procedure is related to portfolio Q.
If the market doesn't currently price the asset fairly, then the asset's expected return comprises two 
components: the return expected if the asset were fairly priced, and a correction term based on the 
market price's approaching fair value.
Problems
1. In the simple stock example described in the text, value a European call option on the stock with a 
strike price of 50, maturing at the end of the 1-month period. The option cash flows at the end of the 
period are Max{0,p(t,s) – 50}, where p(t,s) is the stock price at time t in state s.
2. Compare Eq. (8.16) to the CAPM result for expected returns, to relate υ to rQ. Impose the 
requirement that E{υ} = 1 to determine υ exactly as a function of rQ.
3. Using the simple stock example in the text, price an instrument which pays $1 in state 1 [cf(t,1) = 
1] and $–1 in state 2 [cf(t,2) = –1]. What is the expected return to


---


### Page 217


Page 211
this asset? What is its beta with respect to the stock? How does this relate to the breakdown of Eq. 
(8.7)?
4. You believe that stock X is 25 percent undervalued, and that it will take 3.1 years for half of this 
misvaluation to disappear. What is your forecast for the alpha of stock X over the next year?
References
Arrow, Kenneth J. Essays in the Theory of Risk-Bearing (Chicago: Markham Publishing Company, 
1971).
Bar-Yosef, Sasson, and Hayne Leland. Risk Adjusted Discounting. University of California, 
Berkeley Research Program in Finance working paper #134, December 1982.
Black, Fischer, and Myron Scholes. "The Pricing of Options and Corporate Liabilities."Journal of 
Political Economy, vol. 81, no. 3, 1973, pp. 637–654.
Chamberlain, Gary, and M. Rothschild. "Arbitrage, Factor Structure and Mean-Variance Analysis 
on Large Asset Markets." Econometrica, vol 51, no. 5, 1983, pp. 1281–1304.
Cox, John C., and Mark Rubinstein. Options Markets (Englewood Cliffs, N.J.: Prentice-Hall, 1985).
Debreu, Gerard. Theory of Value (New York: John Wiley & Sons, 1959).
Garman, Mark B. "A General Theory of Asset Valuation under Diffusion State Processes." 
University of California, Berkeley Research Program in Finance working paper #50, 1976.
Garman, Mark B. "Towards a Semigroup Pricing Theory." Journal of Finance, vol. 40, no. 3, 1985, 
pp. 847–861.
Grinold, Richard C. "The Valuation of Dependent Securities in a Diffusion Process," University of 
California, Berkeley Research Program in Finance working paper #59, April 1977.
———. "Market Value Maximization and Markov Dynamic Programming." Management Science, 
vol. 29 no. 5, 1983, pp. 583–594.
———. "Ex-Ante Characterization of an Efficient Portfolio." University of California, Berkeley 
Research Program in Finance working paper #59, September 1987.
Harrison, Michael J., and David M. Kreps. "Martingales and Arbitrage in Multiperiod Securities 
Markets." Journal of Economic Theory, vol 20, 1979, pp. 381–408.
Hull, John. Options, Futures, and Other Derivative Securities (Englewood Cliffs, N.J.: PrenticeHall, 1989).
Ohlson, James A. "A Synthesis of Security Valuation Theory and the Role of Dividends, Cash 
Flows, and Earnings." Columbia University working paper, April 1989.
Ross, Stephen. "Return, Risk, and Arbitrage." In Risk and Return in Finance, edited by I. Friend and 
J. Bicksler (Cambridge, Mass.: Ballinger, 1976).


---


### Page 218


Page 212
Rubinstein, Mark. "The Valuation of Uncertain Income Streams and the Pricing of Options." Bell 
Journal of Economics, vol 7, 1976, pp. 407–425.
Sharpe, William F. "Capital Asset Prices: A Theory of Market Equilibrium under Conditions of 
Risk." Journal of Finance, vol. 19, no. 3, 1964, pp. 425–442.
Williams, John Burr. The Theory of Investment Value (Amsterdam: North-Holland Publishing 
Company, 1964).
Technical Appendix
This appendix derives some of the results used in the text. In particular,
• We derive the basic valuation result in the case of a finite number of outcomes.
• We illustrate the basic valuation result using option pricing.
• We apply the CAPM (or really mean/variance theory) to valuation.
• We introduce portfolio S as a more general portfolio approach to valuation.
Theory of Valuation
Consider a finite number of assets indexed by n = 0, 1, . . . , N over a finite number of periods T. 
Start at time t = 0, and observe the prices of the assets at times t = 1, 2, . . . , T. The prices evolve 
along paths. The collection of paths determines the possible outcomes. At timet = T, we will know 
what path we have followed. At time t = 0, we know only the set of possible paths. At intermediate 
times, 0 < t <T, we have partial knowledge of the eventual path we will follow.
Specifying the state of knowledge at each intermediate point in time determines the system. 
Knowledge is refined through time, as the collection of possible paths shrinks. At time t, we can be 
in one of S(t) states, where a state indicates a collection of possible paths we might be following. As 
time moves on, this set of possible paths is reduced, until at time T we know what path we have 
been following. Figure 8A.1 illustrates a case in which there are 3 time periods and 11 possible 
paths.
We can make this more precise. At time t ≥ 1 in state s, we will know the unique time t – 1 state that 
preceded state s; the


---


### Page 219


Page 213
Figure 8A.1
predecessor is denoted φ(s,t). We will also know the possible successors to (s,t) at time t + 1. That 
collection of possible successors is denoted Ω(s,t). For every possible successor z ∈ Ω(s,t), we must 
have (s,t) as a predecessor; i.e., if z ∈ Ω(s,t), then φ(z,t+1) = s. Similarly, if z ∉ Ω(s,t), then φ(z,t+1) 
 s. The set of all possible states at time t is denoted Φ(t).
We have probabilities π{s,t} of being in state s at time t. We require only that these probabilities be 
positive.
Asset prices are given by pn(s,t), the price of asset n if state s occurs at time t. Since there is only one 
state at time t = 0, we have pn(1,0) as the initial prices.
One of the assets, call it asset n = 0, is risk-free. At time t in state s, a positive risk-free rate of 
interest iF(s,t) will prevail from time t until time t + 1. We start with p0(1,0) = 1. At time t + 1, we 
have
for every z ∈ Ω(s,t). This assumption allows future rates of interest to be uncertain, although we will 
always know what rate of interest obtains over the next period.
To make life simple, we will ignore dividends. This means that we can assume either that all 
dividends are paid at time T or that pn(s,t) includes accumulated dividends.


---


### Page 220


Page 214
An investment strategy is determined by the N + 1–element vector NS(s,t) = {NS0(s,t),NS1(s,t), . . . , 
NSN(s,t)} for each state, time, and asset. It describes the number of shares of that asset in the 
portfolio at that state and held from time t to time t + 1. The value of the portfolio at time t in state s 
using strategy NS is denoted W(s,t). The value W(s,t) is
To conserve value, we impose a self-financing condition: The value of the portfolio at the end of 
period t-1 must exactly match the value of the portfolio at the start of period t. Mathematically, for t 
≥ 1 and s ∈Φ(t),
The value of the portfolio before it is revised is the same as the value of the portfolio after it is 
revised.
An arbitrage opportunity is available if we can find an investment strategy that starts with a 
nonpositive amount of money, W(1,0) ≤ 0; is guaranteed not to lose money, W(s,t) ≥ 0 for s∈Φ(T); 
and makes money in at least one outcome
Proposition 1
If there are no arbitrage opportunities, we can find positive valuation multiples υ(s,t) > 0 such that 
for any asset n = 0, 1, 2, .., N and any time t = 1, 2, .., T,
Proof
Consider the following linear program:


---

