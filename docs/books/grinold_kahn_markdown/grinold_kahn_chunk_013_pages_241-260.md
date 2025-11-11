# Grinold-Kahn Active Portfolio Management

## Pages 241-260


### Page 241


Page 236
TABLE 9.1
Stock
Yield
Beta
Implied Growth Rate
American Express
4.00%
1.21
6.36%
AT&T
2.60%
0.96
6.26%
Chevron
4.70%
0.45
1.10%
Coca-Cola
1.30%
1.00
7.80%
Disney
0.50%
1.24
10.04%
Dow Chemical
4.50%
1.11
5.26%
DuPont
3.70%
1.09
5.94%
Eastman Kodak
4.90%
0.60
1.80%
Exxon
4.70%
0.47
1.22%
General Electric
2.90%
1.31
8.06%
General Motors
2.50%
0.90
6.00%
IBM
9.60%
0.64
–2.66%
International Paper
2.50%
1.16
7.56%
Johnson & Johnson
1.80%
1.15
8.20%
McDonalds
0.80%
1.07
8.72%
Merck
2.30%
1.09
7.34%
3M
3.20%
0.74
4.34%
Philip Morris
3.40%
0.97
5.52%
Procter & Gamble
2.10%
1.01
7.06%
Sears
4.40%
1.04
4.94%
We can see that reasonable growth rates average about 5.5 percent and that the standard deviation of 
growth rates in the Major Market Index is 3.1 percent. One of the difficulties in using a dividend 
discount model is implicit in the Golden Rule: The growth inputs can be wildly unrealistic. They 
tend to be too large in general, since Wall Street research (which drives the consensus) is interested 
in selling stocks, and positive bullish outlooks help to sell stocks.
Dealing with Unrealistic Growth Rates
We can treat this problem of unrealistic growth estimates in three ways. The first is a direct 
approach:
1. Group stocks into sectors.


---


### Page 242


Page 237
2. Calculate the implied growth rate for each stock in the sector.
3. Modify the growth forecasts so that they have the same mean and standard deviation as the 
implied growth rates in each sector.
This approach linearly transforms the growth estimate gn to
where we choose a and b to match the mean and standard deviation of the implied growth rates 
 
The result is
where we calculate the mean and standard deviation cross-sectionally over stocks in the sector. The 
revised growth estimates are the sector average implied growth rate plus a term proportional to the 
difference between the initial growth estimates and that sector average implied growth rate.
Table 9.2 shows the results of this approach for the stocks in the Major Market Index, using the 5year historical earnings-per-share growth rates (as of December 1992) as inputs. In this table, we 
have treated all these stocks as one sector. Table 9.2 also shows the alphas from Eq. (9.19), based on 
the modified growth inputs.
One possible difficulty with this approach is that it may delete valuable sector timing information. 
Remember that the implied growth rates assume zero alphas, so this scheme will move the sector 
alphas toward zero.3 If you have no sector timing ability, then this is not a problem, but if you are 
trying to time sectors, you must account for sector alphas when generating target mean growth rates 
for each sector.
The second approach to dealing with unrealistic growth estimates is a variant of the first approach 
which can, in principle,
3Issues of coverage and capitalization weighting keep the sector alphas from exactly equaling zero after this 
procedure.


---


### Page 243


Page 238
TABLE 9.2
Stock
Growth Forecast
Modified Forecast
Alpha
American Express
–3.20%
4.90%
–1.46%
AT&T
–19.21%
2.21%
–4.05%
Chevron
3.18%
4.91%
3.81%
Coca-Cola
19.31%
8.68%
0.88%
Disney
12.18%
7.49%
–2.55%
Dow Chemicals
–23.22%
1.54%
–3.72%
DuPont
–7.46%
4.19%
–1.75%
Eastman Kodak
–37.51%
–0.86%
–2.66%
Exxon
3.32%
6.00%
4.78%
General Electric
16.14%
8.15%
0.09%
General Motors
4.72%
6.23%
0.23%
IBM
–32.53%
–0.03%
2.63%
International Paper
–10.86%
3.62%
–3.94%
Johnson & Johnson
15.27%
8.01%
–0.19%
McDonalds
12.09%
7.47%
–1.25%
Merck
22.95%
9.30%
1.96%
3M
4.48%
6.19%
1.85%
Philip Morris
22.92%
9.29%
3.77%
Procter & Gamble
23.30%
9.35%
2.29%
Sears
–7.96%
4.10%
–0.84%
Mean
0.58%
5.54%
-0.01%
Standard deviation
18.40%
3.09%
2.70%
account for the investor's skill in predicting growth. As we will discover in Chap. 10, a basic linear 
forecasting result is
Unlike in Eq. (9.22), we start with the stock's implied growth rate, not the sector average, and shift 
away from it based on comparing the initial growth forecast to the stock's implied growth rate.
Furthermore, as we will learn in Chap. 10, the constant c depends in part on the investor's skill in 
predicting growth, where we measure skill using the correlation between forecast and realized


---


### Page 244


Page 239
growth rates. With no skill, we set c to zero. We leave the details to Chap. 10.
A third, more conventional and more elaborate, approach to getting realistic growth inputs is the 
three-stage dividend discount model.
The Three-Stage Dividend Discount Model
The three-stage dividend discount model is built on the premise that we may have some insights 
about a company's prospects over the short run (1 to 4 years), but we have little long-range 
information. Therefore, we should use something like the implied growth rate for the company (or 
the sector) as the long-run value, and interpolate between the long and the short.
The idea stems from the initial dividend discount formula [Eq. (9.3)], which would naturally lead 
one to distinguish between long-range and short-range growth rates.
The three-stage dividend discount model is complicated. The reader who is uninterested in the 
details can skip to the next subsection, where we comment (negatively) on the net effect of the 
three-stage approach.
There are several ways to build a three-stage dividend discount model. What follows is typical, and 
we don't believe that different model structures give materially different results. The required inputs 
include the following:
T1, T2 =
times which define the stages—stage 1 runs 
from 0 to T1, stage 2 from T1 to T2, and stage 3 
from T2 onward
gIN =
the short-term (0 to T1) forecast growth in 
earnings per share
gEQ =
the long-range or equilibrium (T2 onward) 
forecast growth in earnings per share
κ0 =
the current (0 to T1) payout ratio
κEQ =
the long-run (T2 onwards) payout ratio
EPS(1) =
the forecast of next year's earnings per share
yEQ =
the equilibrium expected rate of return, iF + β · 
fB


---


### Page 245


Page 240
We input the short-term and long-term growth forecasts. For the growth during the intermediate 
period, we linearly interpolate:
for T1 ≤ t ≤ T2. We similarly interpolate the payout ratios κ(t). Then the earnings per share and 
dividend paths will be
We now proceed by first finding a time T2 value of the company, and then focusing on the current 
value of the company. At timeT2, we can value the company using the equilibrium growth and 
dividend discount rates:
Then we can solve for the dividend discount rate y that discounts to the current price p(0):
The Three-Stage Dividend Discount Model Evaluated
The entire three-stage dividend discount procedure is motivated by the tension between a short-run 
growth rate gIN and a long-run rate gEQ. In spirit, it is just another approach to adjusting gIN toward 
gEQ and applying Eq. (9.3). A cynical view would even be that this is an elaborate (and confusing) 
way to smooth the growth inputs. It is important to remember that the three-stage dividend discount


---


### Page 246


Page 241
Figure 9.3 
Three stage dividend discount model. Alpha versus short term growth forecast.
model is not magic. It cannot transform bad growth forecasts into good growth forecasts. The 
golden rule still applies.
To understand this better, consider the following example. We will set up a typical three-stage 
dividend discount model4 and use it to estimate internal rates of return and alphas (by subtracting iF 
+ β · fB). Figure 9.3 illustrates the almost linear relationship between gIN and alpha. In this case, the 
implied growth rate is 12.62 percent, and each additional 1 percent of growth adds 0.54 percent to 
the alpha. The golden rule has been modified slightly, to say ''g in, 0.54 · (g – 12.62 percent) out."
We can apply the same analysis to observe the sensitivity of alpha to the initial earnings per share 
forecast. Figure 9.4 illustrates the result. The relationship between the initial earnings per share 
forecast and the alpha is slightly nonlinear; however, 30 basis points of alpha for each $0.20 of 
earnings per share is a reasonable guide.
4The parameters are 5 and 15 years for the stage times, 0.0 for the short-run payout, and 0.3 for the long-run 
payout. The long-run expected market excess return was 5.5 percent, the stock's beta was 1.2, and the risk-free 
rate was 4 percent. This means that the stock's long-run fair expected return was 10.60 percent. The first year's 
EPS number was $4.80, and the market price was $50.00.


---


### Page 247


Page 242
Figure 9.4 
Three stage dividend discount model. Alpha versus initial earnings per share forecast.
Dividend Discount Models and Returns
To use a dividend discount model in the context of active portfolio management, the information in 
the model must be converted into forecasts of exceptional return. There are two standard 
approaches, based on calculating either internal rates of return or net present values. These 
approaches differ in their assumption of the horizon over which any misvaluation will disappear.
In the internal rate of return mode, we use the stream of dividends and the current market price as 
inputs, and solve for the internal rate of return y which matches the dividends to the market price. 
We then obtain asset alphas in two steps: first aggregate the rates of returns yn to estimate the 
predicted benchmark excess return fB,
and then convert the internal rates of return to expected residual returns:
The underlying assumption is that the misvaluation of the asset will persist; i.e., after 1 year, the 
proper discount rate will still be


---


### Page 248


Page 243
yn and not the "fair" rate iF + βn · fB. To see this, we can verify, using Eq. (9.3), that the expected total 
rate of return for the asset will be yn, if we assume that yn remains constant. Mathematically,
The expected price in 1 year is simply the dividend stream from year 2 on, discounted at the same 
internal rate of return yn. The alphas from Eq. (9.27) presume that the mispricing will persist 
indefinitely, and that one will continue to reap the benefits.
In the net present value mode, we take the stream of dividends and a fair discount rate yn = iF + βn · fB
as inputs, and solve for the fair market price as we would for a net present value calculation. We 
then compare this price to the current market price, to determine the degree of overvaluation or 
under-valuation. To convert these "pricing errors" into alphas, we could use the following two-step 
process. First we adjust fB (and hence yn) so that the aggregate fair market value of all the assets 
equals the aggregate current market value of the assets. Second, assuming that the pricing error 
disappears after 1 year, we define alpha as
or approximately as5
The alpha forecast in Eq. (9.33) presumes that all of the misvaluation
5For monthly alpha forecasts, Eqs. (9.33) and (9.34) differ by about a factor of 1.01.


---


### Page 249


Page 244
will disappear in 1 year. In fact, we derive Eq. (9.33) by defining alpha using
and assuming
i.e., the end-of-year price is the net present value of the future stream of dividends, discounted at the 
fair rate iF + βn · fB.
Beneficial Side Effects of Dividend Discount Models
Beyond their possible value in forecasting exceptional returns, dividend discount models also have 
some beneficial institutional side effects. The dividend discount model is a process. Used properly, 
it entails keeping records and viewing all assets on an equal footing. Hence, it can identify the 
judgmental input to a portfolio. We can compare the portfolio that the dividend discount model 
would have purchased with the actual portfolio, and attribute the difference to judgmental overrides 
and implementation costs (trading, etc.). In the longer run, this process can lead to evaluation and 
improvement of the inputs.
On the downside, total devotion to the dividend discount model as the only appoach to valuation is a 
form of tunnel vision. In the remainder of this chapter we will consider some other practical 
approaches to valuation.
Comparative Valuation
The theoretical valuation formula of Chap. 8 and the dividend discount model look to future 
dividends as the source of value. There is an alternative, which involves looking at the current 
characteristics of a company and asking if that company is fairly valued relative to other companies 
with similar characteristics. The most obvious and simple example compares companies solely on 
the basis of current


---


### Page 250


Page 245
price-earnings ratios. The Wall Street Journal provides these numbers every day. A second example 
is the rules of thumb quoted by investment bankers: "Consulting firms sell for two times revenues," 
"Asset management firms sell for 5 percent of assets," etc.
These examples are familiar, unidimensional (and possibly static) approaches to valuation based on 
current attributes. Comparative valuation, as we will describe it, is a more systematic and 
sophisticated (multidimensional) application of this idea: pricing by comparison with analogous 
companies, or as a function of sales and/or earnings multiples. We will motivate6 this approach 
using the dividend discount model as a starting point.
The "clean surplus" equation of accounting7 connects a company's dividends, earnings, and book 
value according to
where we measure the book values b(t – 1) and b(t) at the beginning and end of period t (running 
from t – 1 to time t), the earning se(t) accrue during period t, and the company pays the dividend d(t) 
at the end.
We can use the dividend discount rate y to split earnings into two parts: required and exceptional:
Anticipating that these exceptional earnings e*(t) will die out gradually leads to
where δ < 1. Now combine Eqs. (9.37), (9.38), and (9.39) to estimate the expected dividend, which 
is what the dividend discount model requires:
6In this case, "motivate" will involve a set of assumptions and logic leading to a formula, rather than any 
rigorous derivation. We will then use the formula in an empirical way.
7See Ohlson (1989) for an in-depth discussion.


---


### Page 251


Page 246
Now substitute this expected dividend stream into the dividend discount model [Eq. (9.3)] to find 
(after some manipulation)
Equation (9.41) expresses the current price as a linear combination of anticipated earnings e(1) and 
current book value b(0). The coefficients are company-specific and depend on the dividend discount 
rate and the persistence of exceptional earnings.
This particular derivation is motivation for a more general application. In the general case, we 
would like to explain today's price p(0) in terms of several characteristics: earnings, book, 
anticipated earnings, cash flow, dividends, sales, debt, etc. The idea is to use a cross-sectional 
comparison of similar companies and thus isolate those that are overpriced or underpriced.
For example, suppose we wished to apply the ideas contained in Eq. (9.41) to a group of similar 
medium-sized electrical utilities. We are looking for coefficients c1 and c2 to fit
Starting from Eq. (9.41), the idea is that for these similar companies, the coefficients should be 
identical, and so the pricing error ∈n will identify misvaluations. The exact procedure for 
implementing Eq. (9.42) could vary, from an ordinary least-squares (OLS) regression, to a 
generalized least squares (GLS) regression that takes into account company prices, to a pooled 
cross-sectional and longitudinal regression that looks at the relationship across time and across 
assets.
In general, the goal of comparative valuation is to estimate a relationship


---


### Page 252


Page 247
where the fitted price depends upon a variety of company characteristics. Equation (9.43) leads to an 
exceptional return forecast of
presuming that the fitted price is more accurate than the market price, and that the asset will move to 
the fitted price over the horizon of the alpha.
We can provide an arbitrage interpretation of this comparative analysis. Suppose we split the 
companies into two groups: the overvalued companies (with market price exceeding fitted price) 
and the undervalued companies (with market price less than fitted price). We can then construct a 
portfolio of the overvalued companies and a portfolio of the undervalued companies with identical 
attributes: e.g., the same sales, the same debt, and the same earnings. This creates two 
megacompanies—call them OV and UV, respectively—that are alike in all important attributes. 
However, we can purchase megacompany UV more cheaply than megacompany OV. Two 
"identical" companies selling for different prices is an arbitrage opportunity.
This comparative valuation procedure requires only current and forecast information, e.g., current 
book value and anticipated earnings, and thus is independent of the past. It is not an extrapolation of 
historical data. It also is a high-tech way of mimicking the investment banking valuation procedures, 
which are typically grounded on multiples of sales and earnings. The hope is that the set of 
characteristics in the model completely determines company valuations.
If the model omits some important attribute, the valuation may be misleading: The pricing errors 
may measure just the missing component, not an actual misvaluation. One example of a missing 
factor might be brand value. If we ignored brand name value and applied comparative valuation to a 
consumer goods sector, we might find some companies that were overvalued on average over


---


### Page 253


Page 248
time. This might not be an opportunity to sell, but rather the appearance of brand value. One way to 
account for this would be to compare current overvaluation or undervaluation to historical average 
valuations.
Comparative valuation is quite flexible in practice. We can build separate valuation models for 
banks, mining and extraction companies, industrials, electric utilities, etc. This can help us focus on 
comparability within groups of similar companies.
Returns-based Analysis
The linear valuation model described above can serve as a useful introduction to returns-based 
analysis. The valuation model made a link between a purported percentage pricing error (the 
difference between the fitted and the current price divided by the current price) and the future 
residual return. Why not attack the problem directly and try to fit the price in a way that best 
forecasts residual returns? Suppose company n has attributes (earnings, dividends, book, sales, etc.) 
An,k(t) at time t. We might try the following model to directly explain residual returns using these 
attributes:
Equation (9.45) is one example of returns-based analysis. A more typical returns-based analysis 
works with excess returns rn(t) rather than the residual returns θn(t), and uses risk control factors to 
separate residual and benchmark returns. Its basic form is similar to Eq. (9.45):
but here the company exposures Xn,k(t) include both the attributes An,k(t) and the risk control factors.
Equation (9.46) has the form of an APT model, as discussed in Chap. 7. At the same time, Eq. 
(9.46) may be somewhat more


---


### Page 254


Page 249
flexible. According to Chap. 7, we can fairly easily find qualified APT models—any factor model 
that can explain the returns to a diversified portfolio should probably do. But Eq. (9.46) could 
include all the APT model factors as risk factors, plus a new signal to forecast specific returns from 
that APT model. The APT theory doesn't allow forecasting of specific returns. But we are now in 
the ad hoc, empirical, nonefficient world of active management. We have the flexibility to forecast 
specific returns [although in Eq. (9.46) we express that forecast as another factor].
There are three important points to note concerning the use of the linear model [Eq. (9.46)] to 
forecast returns. First, in a true GLS regression, the factor return bk(t) is the return on a factor 
portfolio with unit exposure to factor k, zero exposure to the other factors, and minimum risk. If we 
know the exposures Xn,k(t) at the start of the period, even without knowing the returns rn(t), we can 
determine the holdings in the factor portfolio at the start of the period necessary to achieve the factor 
return bk(t).
Second, the equations aggregate. In particular, looking at the benchmark return,
We will utilize this linear aggregation property to help separate residual from benchmark returns.
Third, when estimated using least-squares regression, the linear model [Eq. (9.46)] can be unduly 
influenced by outliers. One rule of thumb is to pull in all outliers in the Xn,k(t) to ±3 standard 
deviations about the mean. This will help avoid having all the explanatory power arise out of only 
one or two (possibly suspect) observations.
The simplest approach to separating residual from benchmark returns is to model the residual 
returns directly, as in Eq. (9.45).


---


### Page 255


Page 250
Even then, we should be careful. The aggregate equation for the benchmark is
Since θB(t) ≡ 0, we should adjust8 the variables An,k(t) so that aB,k(t) = 0.
In the more typical situation where we are modeling excess returns, to separate benchmark from 
residual returns, we must include one or more variables that will pick up the benchmark return. The 
simplest approach is to include predicted beta as a risk control factor, and make sure that all other 
characteristics have a benchmark-weighted average of zero. The factor return associated with 
predicted beta will tend to pick up the benchmark return, leaving the other factors to describe 
residual returns. A more complicated procedure is to include a group of industry or sector variables 
as risk control factors. The factor returns associated with these industry or sector variables will pick 
up the benchmark effect.9 These industry or sector assignments add up to an intercept term in the 
regression. To separate bench8If Zn,k(t) is the raw description of the exposure of asset n to attribute k at time t, and
is the benchmark exposure to attribute k at time t, then replace Zn,k(t) with
If the beta of asset n is βn(t), then a slight variant is to replace Zn,k(t) with
9The remaining factor portfolio returns may still be correlated with the benchmark, even if the benchmark's 
exposure to the factor is zero. For example, factors associated with volatility (even after adjusting for market 
neutrality) tend to exhibit strong positive correlation with the market.


---


### Page 256


Page 251
mark from residual returns, the choice10 is between a beta and an intercept term.
Using Returns-based Analysis
Once set up, returns-based analysis examines past returns and attributes those returns to firm 
characteristics. The active manager starts the process by searching for appropriate characteristics. 
Some characteristics might directly explain residual returns—for example, alpha forecasts from 
dividend discount models or comparative valuation models. Other characteristics include reversal 
effects (e.g., last month's realized residual returns), momentum effects (e.g., the past 12 months' 
realized returns), earnings surprise effects, or particular accounting variables possibly connected 
with exceptional returns.11 In this case, the hope is that the factor returns bk(t) associated with these 
characteristics exhibit consistent positive returns.
Alternatively, the manager could choose characteristics associated with investment themes, 
sometimes in favor and sometimes not—for example, growth forecasts or company size. Then the 
associated factor returns bk(t) would not consistently exhibit positive returns, but the manager would 
hope to forecast the sign and magnitude of these returns. For example, how will growth stocks or 
small-capitalization stocks perform relative to the market as a
10A word of caution if you try to include both betas and an intercept (or sectors or industries). There will be no 
problem with the factor portfolios that have benchmark-neutral attributes. Those factor portfolios will have 
both a zero beta and zero net investment. The difficulty is that the benchmark return will be spread between the 
beta factor and the intercept. We can avoid this confusion by introducing an equivalent regression. Suppose Zn,k
(t) is the allocation of company n to sector k and:
 is the benchmark exposure to sector k at time t. If we substitute
Xn,k(t) = Zn,k(t) – βn(t) · zB,k(t)
for Zn,k(t), we can interpret the factor portfolio returns as the residual (the factor portfolio's beta will be zero) return 
on sector k when we control for the other variables. The returns to the benchmark-neutral factors will not change.
11For examples, see Ou and Penman (1989) and Lev and Thiagarajan (1993).


---


### Page 257


Page 252
whole? These forecasts might rely on extrapolations of past factor returns, e.g., using moving 
averages. More sophisticated forecasting might use economic indicators such as long and short 
interest rates, changes in interest rates, corporate bond spreads, or average dividend yields versus 
interest rates.
Sometimes the manager may wish to forecast factor returns even for characteristics that generally 
exhibit consistent positive factor returns. For example, the BARRA Success factor in the United 
States, a momentum factor, generally exhibits positive returns. However, these returns are often 
negative in the month of January.12 Managers who wish to bet on momentum should take into 
account (forecast) this January effect.
Managers can of course combine these different types of signals, forecasting factor returns for 
investment themes as well as using company-level valuation models. The relative emphasis will 
depend on the information ratios associated with these various efforts. Chapter 12, ''Information 
Analysis," and Chap. 17, "Performance Analysis," describe this research and evaluation effort in 
more detail. Chapters 10 and 11, which cover forecasting, will greatly expand on the technical 
issues surrounding forecasting of returns. The notes section of this chapter includes a list of popular 
investment signals.
Summary
This chapter began with a discussion of corporate finance, to motivate the development of valuation 
models based on appropriate corporate attributes. It then discussed dividend discount models in 
considerable detail, especially the critical issues of dealing with growth and expected future 
dividend payments, and converting information from the dividend discount model into exceptional 
return forecasts. The chapter went on to empirically expand the dividend discount concept with 
comparative valuation models, less rigorous in principle but more flexible in practice. The chapter 
ended with a discussion of returns-based analysis—which focuses
12We attribute this to investors' tendency to "window dress" portfolios by keeping winners for the year-end and 
selling losers in December, and to accelerate capital losses (take them in December) and postpone capital gains 
(take them in January).


---


### Page 258


Page 253
directly on forecasts of exceptional return—and alternative empirical approaches that are available.
Notes
Given the nature of active management, we can't provide recipes for finding superior information. 
Hence, this chapter has focused on structure and methodology. But we can provide some indication 
of what types of information U.S. equity investors have found useful in the past. According to an 
annual survey of institutional investors conducted by Merrill Lynch, these factors, attributes, and 
models include
• EPS variability
• Return on equity
• Foreign exposure
• Beta
• Price/earnings ratios
• Price/sales ratios
• Size
• Earnings estimate revisions
• Neglect
• Rating revision
• Dividend yield
• EPS momentum
• Projected growth
• Low price
• Duration
• Relative strength
• EPS torpedo
• Earnings estimation dispersion
• Debt/equity ratio
• EPS surprise
• DDM
• Price/cash flow ratios


---


### Page 259


• Price/book ratios


---


### Page 260


Page 254
Most investors responding to the survey relied on five to seven of these factors. See Bernstein 
(1998) for details.
Problems
1. According to Modigliani and Miller (and ignoring tax effects), how would the value of a firm 
change if it borrowed money to repurchase outstanding common stock, greatly increasing its 
leverage? What if it changed its payout ratio?
2. Discuss the problem of growth forecasts in the context of the constant-growth dividend discount 
model [Eq. (9.5)]. How would you reconcile the growth forecasts with the implied growth forecasts 
for AT&T in Tables 9.1 and 9.2?
3. Stock X has a beta of 1.20 and pays no dividend. If the risk-free rate is 6 percent and the expected 
excess market return is 6 percent, what is stock X's implied growth rate?
4. You are a manager who believes that book-to-price (B/P), earnings-to-price (E/P), and beta are 
the three variables that determine stock value. Given monthly B/P, E/P, and beta values for 500 
stocks, how could you implement your strategy (a) using comparative valuation? (b) using returnsbased analysis?
5. A stock trading with a P/E ratio of 15 has a payout ratio of 0.5 and an expected return of 12 
percent. What is its growth rate, according to the constant-growth DDM?
References
Bernstein, Peter L. "Off the Average." Journal of Portfolio Management, vol. 24, no. 1, 1997, p. 3.
Bernstein, Richard. "Quantitative Viewpoint: 1998 Institutional Factor Survey."Merrill Lynch 
Quantitative Publication, Nov. 25, 1998.
Brennan, Michael J. "Stripping the S&P 500 Index." Financial Analysts Journal, vol. 54, no. 1, 
1998, pp. 12–22.
Chugh, Lal C., and Joseph W. Meador. "The Stock Valuation Process: The Analyst's View." 
Financial Analysts Journal, vol. 40, no. 6, 1984, pp. 41–48.
Durand, David. "Afterthoughts on a Controversy with Modigliani and Miller, plus Thoughts on 
Growth and the Cost of Capital." Financial Management, vol. 18, no. 2, 1989, pp. 12–18.


---

