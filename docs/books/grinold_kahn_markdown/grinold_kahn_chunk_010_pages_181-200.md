# Grinold-Kahn Active Portfolio Management

## Pages 181-200


### Page 181


Page 176
Figure 7.1
the alphas significantly different from zero, they were perversely related to the portfolio betas. The 
results are shown in the scatter diagram in Fig. 7.2.
Remember that we already checked our predictions of beta and found that they were quite accurate. 
The explanation for this event must lie elsewhere. Something, most likely changes in interest rates 
and changes in inflationary expectations, was making higher-beta stocks have negative residual 
returns and lower-beta stocks have higher residual returns.1 This pattern was common throughout 
the early 1980s.
There are periods in which CAPM predictions of expected excess returns appear to have systematic defects.
This episodic evidence is meant to be suggestive, not to dash the CAPM once and for all. In fact, 
financial statisticians have
1This points out the hazards of benchmark timing by tilting the portfolio toward higher-beta stocks. The market 
was up considerably over this period; however, higher-beta stocks had relatively bad results. Benchmark timing 
with futures would have been much more effective, since it did not entail a residual bet on the high-beta stocks.


---


### Page 182


Page 177
Figure 7.2
thrown considerable empirical sophistication into attempts to prove or disprove the validity of the 
CAPM, without coming to any hard-and-fast conclusions.2 Those efforts should be enough to 
convince the investor to value the notion that the market plays a central—indeed, the most 
important—role in the formation of expected returns. However, the example should be enough to 
convince you that it is worthwhile to look for further explanations.
The APT
The APT postulates a multiple-factor model of excess returns. It assumes that there are K factors 
such that the excess returns can be expressed as
2Most recently, Fama and French (1992) have attempted to discredit the CAPM, with considerable publicity. 
However, as described in Black (1993) and Grinold (1993), these results require careful scrutiny.


---


### Page 183


Page 178
where Xn,k =
the exposure of stock n to factor k. The exposures are 
frequently called factor loadings. For practical 
purposes, we will assume that the exposures are 
known before the returns are observed.
bk =
the factor return for factor k. These factor returns are 
either attributed to the factors at the end of the period 
or observed during the period.
un =
stock n's specific return, the return that cannot be 
explained by the factors. It is sometimes called the 
idiosyncratic return to the stock.
We impose very little structure3 on the model. The astute reader will note that the APT model, Eq. 
(7.1), is identical in structure to the structural risk model, Eq. (3.16). However, the focus is now on 
expected returns, not risk.
The APT is about expected excess returns. The main result is that we can express expected excess 
returns in terms of the model's factor exposures. The APT formula for expected excess return is
where mk is the factor forecast for factor k. The theory says that a correct factor forecast will exist. It 
doesn't say how to find it.
The APT maintains that the expected excess return on any stock is determined by that stock's factor exposures 
and the factor forecasts associated with those factors.
Examples
We can breathe some life into this formula by considering a few examples. The CAPM is the first 
example. For the CAPM, we have one factor, K = 1. The stock's exposure to that factor is the stock's 
beta; i.e., Xn,1 = βn. The expected return associated with the factor is m1 = E{rM} = fM, the expected 
excess return on the market.
3We assume that the specific returns u(n) are uncorrelated with the factor returns b(k); i.e., Cov{b(k),u(n)} = 0. 
In most practical applications, we assume that the specific returns are uncorrelated with each other; i.e., Cov{u
(n),u(m)} = 0 if m 
 n; however, we do not need this second assumption for the theory to hold.


---


### Page 184


Page 179
The second example is more substantial. We first classify stocks by their industry membership, then 
look at four other attributes of the companies. These attributes are chosen for the purpose of 
example only. (Why these attributes, and why defined in just this way? That question reinforces the 
notion that the APT model will be in the eye of the model builder. It will be as much a matter of 
taste as anything else.) The four attributes selected are
• A forecast of earnings growth based on the IBES consensus forecast and past realized earnings 
growth
• Bond beta: the response of the stock to returns on an index of government bonds
• Size: the natural logarithm of equity capitalization
• Return on equity (ROE): earnings divided by book
The four attributes include a forecast (earnings growth), a macroeconomic characteristic (bond 
beta), a firm characteristic (size), and a fundamental data item (return on equity).
It is easier to make comparisons across factors if they are all expressed in the same fashion. One 
way to do this is to standardize the exposure by subtracting the market average from each attribute 
and dividing by the standard deviation. In that way, the average exposure will equal zero, roughly 
66 percent of the stocks will have exposures running from –1 up to +1, and only 5 percent of the 
stocks will have exposures above +2 or below –2. Table 7.1 displays the primary industry, 
standardized exposures to these four factors, and predicted beta for the 20 stocks in the Major 
Market Index as of December 1992. Note that these exposures are standardized across a broad 
universe of over 1000 stocks, so, for example, the size factor exposures for the Major Market Index 
stocks are all positive.
The APT forecast is based on the factor forecasts for the four factors and a forecast for the chemical 
industry. The factor forecasts are 2.0 percent for growth, 2.5 percent for bond beta, –1.5 percent for 
size, and 0.0 percent for return on equity. (These forecasts are for illustration only.) We think that 
growth firms will do well, interest-rate-sensitive stocks (which are usually highly leveraged firms) 
will do well, smaller stocks will do well, and return on equity will be irrelevant. In addition, we 
forecast 8 percent for the chemical industry, and 6 percent for all other industries.


---


### Page 185


TABLE 7.1
Stock
Industry
Growth
Bond β
Size
ROE
American Express
Financial services
0.17
–0.05
0.19
–0.28
AT&T
Telephones
–0.16
0.74
1.47
–0.59
Chevron
Energy reserves and production
–0.53
–0.24
0.83
–0.72
Coca-Cola
Food and beverage
–0.02
0.30
1.41
1.48
Disney
Entertainment
0.13
–0.86
0.71
0.42
Dow Chemical
Chemical
–0.64
–0.92
0.48
0.22
DuPont
Chemical
–0.10
–0.74
1.05
–0.41
Eastman Kodak
Leisure
–0.19
–0.30
0.39
–0.55
Exxon
Energy reserves and production
–0.67
0.03
1.67
–0.27
General Electric
Heavy electrical
–0.24
0.13
1.56
0.15
General Motors
Motor vehicles
2.74
–1.80
0.73
–1.24
IBM
Computer hardware
0.51
–0.62
1.16
–0.62
International Paper
Forest products and paper
–0.23
–1.08
0.01
–0.49
Johnson & Johnson
Medical products
–0.12
0.68
1.06
0.78
McDonalds
Restaurant
–0.16
0.28
0.55
0.24
Merck
Drugs
–0.04
0.46
1.37
2.28
3M
Chemical
–0.22
–0.69
0.78
0.20
Philip Morris
Tobacco
–0.01
0.30
1.60
1.22
Procter & Gamble
Home products
–0.32
0.80
1.12
0.41
Sears
Department stores
–0.34
–1.29
0.45
–0.69


---


### Page 186


Page 181
TABLE 7.2
Stock
Industry
APT
CAPM
APTCAPM
American Express
Finance services
5.93%
6.96%
–1.03%
AT&T
Telephones
5.33%
5.04%
0.29%
Chevron
Energy reserves and 
production
3.10%
4.20%
–1.11%
Coca-Cola
Food and beverage
4.60%
6.36%
–1.77%
Disney
Entertainment
3.05%
6.78%
–3.74%
Dow Chemical
Chemical
3.70%
6.78%
–3.08%
DuPont
Chemical
4.38%
5.58%
–1.21%
Eastman Kodak
Leisure
4.29%
5.64%
–1.36%
Exxon
Energy reserves and 
production
2.23%
4.26%
–2.03%
General Electric
Heavy electrical
3.51%
6.60%
–3.10%
General Motors
Motor vehicles
5.89%
7.50%
–1.62%
IBM
Computer hardware
3.73%
6.66%
–2.93%
International Paper
Forest products and paper
2.83%
6.48%
–3.66%
Johnson & Johnson
Medical products
5.87%
6.42%
–0.55%
McDonalds
Restaurant
5.56%
6.36%
–0.81%
Merck
Drugs
5.02%
6.60%
–1.59%
3M
Chemical
4.67%
5.46%
–0.80%
Philip Morris
Tobacco
4.33%
6.12%
–1.79%
Procter & Gamble
Home products
5.68%
6.30%
–0.62%
Sears
Department stores
1.42%
6.60%
–5.18%
The CAPM forecast is for 6 percent expected market excess return.
We display the final stock forecasts in Table 7.2. Here we display the APT forecast, the CAPM 
forecast, and the residual APT forecast (the APT forecast less the CAPM forecast).
We can see from this example that whatever the use of an APT model in forecasting expected 
returns, it can make a great talking point. By putting in different expectations for the various factors, 
we could automatically generate mountains of research.
The APT Rationale
The APT result follows from an arbitrage argument. What would happen if we had a returns model 
like Eq. (7.1), and the APT


---


### Page 187


Page 182
relationship [Eq. (7.2)] failed to hold? We could find an active position with zero exposure to all of 
the factors4 and expected excess return of 1 percent. Since the active position has zero factor 
exposure, it has almost no risk, and so we can achieve 1 percent expected excess return at low risk 
levels. We can therefore also add this active position to any portfolio P and improve our 
performance by increasing expected excess return with little additional risk.
Arbitrage means a certain gain at zero expense. In the case described above, we have a nearly 
certain gain, since the expected return is positive and the risk is very, very small. There is no 
expense, since it is an active portfolio (zero net investment). We call this second situation a quasiarbitrage opportunity. If we rule out these quasi-arbitrage opportunities, then the APT must hold.
How do we find the factor model that will do this wonderful trick? The APT is silent on that 
question. However, a little old-fashioned mean/standard deviation analysis can provide some clues.
Portfolio Q and the APT
The APT is marvelously flexible. We can concentrate on any desired group of stocks.5 Among any 
group of N stocks, there will be an efficient frontier for portfolios made up of the N risky stocks. 
Figure 7.3 shows a typical frontier.
With each portfolio we can associate a risk, as measured by the standard deviation of its returns, and 
a reward, as measured by the expected excess return. Portfolio Q in Fig. 7.3 has the highest rewardto-risk ratio (Sharpe ratio).
Knowledge of portfolio Q is sufficient to calculate all expected returns.6 Portfolio Q plays the same 
role as the market portfolio does in the CAPM; in fact, the CAPM is another way of saying that 
portfolio Q is the market portfolio.7
4This will typically imply net zero investment, unless the factor model does not have an intercept. Even then, 
we have built a portfolio with almost no risk and 1 percent expected excess return. We can combine this with 
the risk-free asset for a net zero investment with an expected excess return and almost no risk.
5Contrast this with the CAPM, where coverage should, in theory, be universal.
6And vice versa. See Chap. 2 for more details.
7See the technical appendix to Chap. 2.


---


### Page 188


Page 183
Figure 7.3
The expected excess return on any stock will be proportional to that stock's beta with respect to 
portfolio Q. We might assume that we can stop here. We cannot, since we don't know portfolio Q. 
However, all is not lost. We can learn something from portfolio Q.
We need to separate two issues at this point. The first is defining a qualified model, and the second 
is finding the correct set of factor forecasts. A multiple-factor model [as in Eq. (7.1)] is qualified if it 
is possible to find factor forecasts m(k) such that Eq. (7.2) holds.


---


### Page 189


Page 184
Once we have a qualified model, we still must come up with the correct factor forecasts m(k). We 
argue in the next section that it should not be hard to find a qualified model. However, in the section 
following that, we argue that the ability to make correct factor forecasts requires both considerable 
skill and a model linked to investment intuition.
The Easy Part: 
Finding a Qualified Model
This section describes the technical properties required for a multiple-factor model to qualify for 
successful APT implementation. The details are in the technical appendix. More significantly, we 
argue by example that we can fairly easily find qualified models. Let's start with the technical result.
A factor model of the type described in Eq. (7.1) is qualified, i.e., Eq. (7.2), will hold for some 
factor forecasts mk, if and only if portfolio Q is diversified with respect to that factor model. 
Diversified with respect to the factor model means that among all portfolios with the same factor 
exposures as portfolio Q, portfolio Q has minimum risk. No other portfolio with the same factor 
exposures is less risky than portfolio Q. How do we translate this technical rule into practice?
A frontier portfolio like Q should be highly diversified in the conventional sense of the word. 
Portfolio Q will contain all the stocks, with no exceptionally large holdings. We want portfolio Q to 
be diversified with respect to the multiple-factor model. Common sense would say that any 
multiple-factor model that captures the important differential movements in the stocks will qualify. 
The arbitrary aspect of the APT can be a benefit as well as a drawback! It's a drawback in that we 
don't know exactly what to do; it's a benefit in that it suggests that there are reasonable steps that 
will possibly succeed.
We can check this idea by devising some surrogates for portfolioQ and seeing if they are diversified 
with respect to the BARRA U.S. Equity model. The BARRA model was constructed to help 
portfolio managers control risk, not to explain expected returns. However, it does attempt to capture 
those aspects of the market that cause some groups of stocks to behave differently from others.


---


### Page 190


Page 185
TABLE 7.3
Portfolio
Number of Assets
Unexplained Variance (%)
MMI
20
2.51
OEX
100
0.99
S&P 500
500
0.30
FR1000
1000
0.21
FR3000
3000
0.18
ALLUS
~6000
0.17
We find that well over 99 percent of the variance of highly diversified portfolios is captured by the 
factor component. Table 7.3 shows the percentage of total risk that is not explained by the model for 
several major U.S. equity indices as of December 1992. The ALLUS portfolio includes 
approximately the 6000 largest U.S. companies, which are followed by BARRA.
Table 7.3 indicates that portfolios are highly diversified with respect to the BARRA model. It may 
be possible to find a portfolio that has the same factor exposures as the Frank Russell 3000 index 
and less risk. However, the two portfolios would have the same factor risk (recall that they have the 
same factor exposures), and so they can differ only in their specific risk. Since 99.82 percent of the 
risk is explained by the factor component of return, there is very little margin for improvement. We 
cannot find portfolios that have the same factor exposures and substantially less risk, since the 
amount of nonfactor risk is already negligible.
Any factor model that is good at explaining the risk of a diversified portfolio should be (nearly) qualified as an 
APT model.
The exact specification of the factor model may not be important in qualifying a model. What is 
important is that the model contain sufficient factors to capture movement in the important 
dimensions.
The Hard Part: 
Factor Forecasts
We have settled one part of the implementation question. Any reasonably robust risk model in the 
form of Eq. (7.1) should qualify.


---


### Page 191


Page 186
The next step is to find the amount of expected excess return, mk in Eq. (7.2), to associate with each 
factor.
Forecasting the mk is not easy just because we may have 1000 stocks and only 10 factors. If it were 
true that ''fewer is better," then we could just concentrate on forecasting the returns to the bond 
market and the stock market. In fact, as the fundamental law of active management states, it is better 
to make more forecasts than fewer for a given level of skill. If we can forecast expected returns on 
1000 stocks or 10 factors, then to retain the same value added, we need ten times more skill in 
forecasting the factor returns than in forecasting the stock returns.
The simplest approach to forecasting mk is to calculate a history of factor returns and take their 
average. This is the forecast that would have worked best in the past—i.e., a backcast rather than a 
forecast. If we hope that the past average helps in the future, we are implicitly assuming an element 
of stationarity in the market. The APT does not provide any guarantees here. However, there is 
hope. One of the non-APT reasons to focus on factors is the knowledge that the factor relationship is 
more stable than the stock relationship. For example, it is probably more valuable to know how 
growth stocks have done in the past than to know the past returns of a particular stock that is 
currently classified as a growth stock. The problem is that the stock may not have been classified as 
a growth stock over the earlier period; the stock may have changed its stripes. However, the factor 
returns will give us some information on how it may perform in its current set of stripes!
Haugen and Baker (1996) have proposed an APT model whose factor forecasts rely simply on 
historical factor returns. Their factors roughly resemble the BARRA model, except that they replace 
more than 50 industries with 10 sectors, and they replace 13 risk indices with 40 descriptors.8 Each 
factor forecast is then simply the trailing 12-month average of the factor returns. So they forecast the 
finance sector return, the IBES estimated earnings-to-price factor return, etc., as their past 12-month 
averages.
Model structure can be very helpful in developing good forecasts. As we'll see in the next section, 
APT models can be either purely statistical or structural. The factors have some meaning in
8This leads to collinearity, which the BARRA model attempts to avoid.


---


### Page 192


Page 187
the structural model; they don't in a purely statistical model. In statistical models, we have very little 
latitude in forecasting the factor returns. In a structural model, with factors that are linked to 
specified characteristics of the stocks, factor forecasts can be interpreted as forecasts for stocks that 
share a similar characteristic. We can apply both common sense and alternative statistical 
procedures to check those forecasts.
Factor forecasts are easier if there is some explicit link between the factors and our intuition. 
Consider, for example, a "bond market beta" factor. This factor will show how the stock will react 
as bond prices (i.e., interest rates) change. A forecast for this factor is in fact a forecast for the bond 
market. This doesn't mean that forecasting future interest rates is easy. It means that the knowledge 
that you are, in fact, forecasting interest rates should make the task clearer.
A similar result would hold for a factor defined in terms of a stock's fundamentals. Consider a 
"growth" factor, with consensus growth expectations as the factor exposures. Now our forecast is an 
expression of our outlook for growth stocks. Once again, we haven't guaranteed that we can forecast 
the outlook for growth stocks correctly. We have simply made the task more explicit, and thus given 
ourselves a greater chance for success.
This suggests an opportunistic approach to building an APT model. We should take advantage of 
our conclusion that we can easily build qualified APT models. We should use factors that we have 
some ability to forecast. Suppose we are reasonably good at forecasting returns to gold, oil, bonds, 
yen, etc., and we have some skill at predicting economic fluctuations. We should work from our 
strengths and build an APT model based on those factors, then round out the model with some 
others (industry variables) to capture the bulk of the risk. There is no use building the world's 
greatest (most qualified) APT model if we cannot come up with the factor forecasts.
Factor forecasts are difficult. Structure should help.
The next section describes some approaches to building an APT model.
Applications
We have tried to emphasize the flexible nature of the APT. There are many ways to build APT 
models. The arbitrary nature of the


---


### Page 193


Page 188
APT leaves enormous room for creativity in implementation. Two equally well-informed scholars 
working independently will not come up with similar implementations. We've given six illustrations 
here. They fall into two catagories, structural and statistical.
Structural models postulate some relationships between specific variables. The variables can be 
macroeconomic (unanticipated inflation, change in interest rates, etc.), fundamental (growth in 
earnings, return on equity, market share), or market-related (beta, industry membership). All types 
of variables can be used in one model. Practitioners tend to prefer the structural models, since these 
models allow them to connect the factors with specific variables and therefore link their investment 
experience and intuition to the model.
Statistical models line up the returns data and turn a crank. Academics build APT models to test 
various hypotheses about market efficiency, the efficacy of the CAPM, etc. Academics tend to 
prefer the purely statistical models, since they can avoid putting their prejudgments into the model 
in that way.
There are a great many ways to build an APT model.
Structural Model 1: 
Given Exposures, Estimate Factor Returns
The BARRA model, described in detail in Chap. 3, "Risk," can function as an APT model. As we 
saw above, it qualifies with ease, and it is just as easy (i.e., not very) to forecast returns to the 
BARRA factors as to any others. The BARRA model takes the factor exposures as given based on 
current characteristics of the stocks, such as their earnings yield and relative size. The factor returns 
are estimates.
Structural Model 2: 
Given Factor Returns, Estimate Exposures
In this model, the factor returns are given. For example, take the factor returns as the return on the 
value-weighted NYSE, gold, a government bond index, a basket of foreign currencies, and a basket 
of traded commodities. Set the exposure of each stock to the NYSE equal to 1. For the other factors, 
determine the past exposure of


---


### Page 194


Page 189
the stock to the factor returns by regressing the difference between the stock return and the NYSE 
return on the returns of the other factors.
The factor forecasts are forecasts of the future values of the factor returns. Note that we hope that 
the estimated factor exposures are stable over time.
Structural Model 3: 
Combine Structural Models 1 and 2
This model is the inevitable hybrid of structural models 1 and 2: Start with some primitive factor 
definitions, estimate the stock's factor exposure as in structural model 2, then attribute returns to the 
factors as in structural model 1.
Statistical Model 1: 
Principal Components Analysis
Look at the returns of a collection of stocks, or portfolios of stocks, over many months—say 50 
stocks over 200 months. Calculate the 50 by 50 matrix of realized covariance between these stocks 
over the 200 months. Do a principal components analysis of the 50 by 50 covariance matrix. 
Typically, one will find that the first 20 components will explain 90 percent or more of the risk. Call 
these 20 principal component returns the factors. These factors are purely statistical constructs. We 
might as well call them Dick, Jane, Spot, . . . or red, green, blue. . . .
The analysis will tell us the exposures of the 50 stocks to the factors. It will also give us the returns 
on those factors over the 200 months. The factor returns will be uncorrelated. We can determine the 
exposures to the factors of stocks that were not included in the original group by regressing the 
returns of the new stocks on the returns to the factors. The regression coefficients will measure the 
exposures to the factors; the fact that the factor returns are uncorrelated is useful at this stage. To 
implement this model, we need a forecast of the mk. The obvious forecast is the historical average of 
the factor returns. It may be the only possible forecast: Since the factors are by construction abstract, 
it would be hard to justify a forecast that differed from the historical average.


---


### Page 195


Page 190
Statistical Model 2: 
Maximum Likelihood Factor Analysis
Here we perform a massive maximum likelihood estimation, looking at Eq. (7.1) over 60 months. 
To make this possible, we assume that the stock's exposures Xn,k are constant over the 5-year period. 
If we applied this to 500 stocks over 60 months and looked for 10 factors, we would be using 500 · 
60 = 30,000 returns to estimate 500 · 10 = 5000 exposures and 60 · 10 = 600 factor returns.
Statistical Model 3: 
The Dual of Statistical Model 2
This is quite imaginative. A detailed description is difficult, but see Connor and Korajczyk (1988). 
When N stocks are observed over T time periods, N is usually much greater than T. Instead of 
analyzing the principal components of the N by N historical covariance matrix, we look at the T by T
matrix of covariances. This analysis reverses the role of factor exposure and factor return!
Summary
We have described the APT and talked about its relevance for active management. The APT is a 
powerful theory, but difficult to apply. The APT does not in any way relieve the active manager of 
the need for insight and skill. It is a framework that can help skilled and insightful active managers 
harness their abilities.
Problems
1. According to the APT, what are the expected values of the un in Eq. (7.1)? What is the 
corresponding relationship for the CAPM?
2. Work by Fama and French, and others, over the past decade has identified size and book-to-price 
ratios as two critical factors determining expected returns. How would you build an APT model 
based on those two factors? Would the model require additional factors?


---


### Page 196


Page 191
3. In the example shown in Table 7.2, most of the CAPM forecasts exceed the APT forecasts. Why? 
Are APT forecasts required to match CAPM forecasts on average?
4. In an earnings-to-price tilt fund, the portfolio holdings consist (approximately) of the benchmark 
plus a multiplec times the earnings-to-price factor portfolio (which has unit exposure to earnings-toprice and zero exposure to all other factors). Thus, the tilt fund manager has an active exposure c to 
earnings-to-price. If the manager uses a constant multiple c over time, what does that imply about 
the manager's factor forecasts for earnings-to-price?
5. You have built an APT model based on industry, growth, bond beta, size, and return on equity 
(ROE). This month your factor forecasts are
Heavy electrical industry
6.0%
Growth
2.0%
Bond beta
–1.0%
Size
–0.5%
ROE
1.0%
These forecasts lead to a benchmark expected excess return of 6.0 percent. Given the following data 
for GE,
Industry
Heavy electrical
Growth
–0.24
Bond beta
0.13
Size
1.56
ROE
0.15
Beta
1.10
what is its alpha according to your model?
Notes
In the early 1970s, Sharpe (1977) (the paper was written in 1973), Merton (1973), and Rosenberg 
(1974) advocated multiple-factor approaches to the CAPM. Their arguments were based on 
reasoning similar to that underlying the CAPM. The results were a multiple-


---


### Page 197


Page 192
beta form of the CAPM, identical in form to Eq. (7.2). In fact, an active money management product 
called a "yield tilt fund" was launched based on the notion that higher-yielding stocks had higher 
expected returns.
In the mid-1970s, Ross (1976) proposed a different way of looking at expected stock returns. Ross 
used the notion of arbitrage, which was the foundation of Black and Scholes's work on the valuation 
of options. In certain cases the mere ruling out of arbitrage opportunities is sufficient to produce an 
explicit formula for a stock's value. Later other authors, notably Connor (1984) and Huberman 
(1982), added additional assumptions and structure to produce the exact form of Eq. (7.2). Modern 
theoretical treatments of the APT reserve a role for the market portfolio. See Connor (1986) for a 
discussion.
Bower, Bower, and Logue (1984); Roll and Ross (1984); and Sharpe (1984) have expositions of the 
APT aimed at professionals. See also Rosenberg (1981) and Rudd and Rosenberg (1980) for a 
discussion of the CAPM and APT. The text by Sharpe and Alexander (1990) has an excellent 
discussion.
Applications of the APT are described in Roll and Ross (1979), Chen, Roll, and Ross (1986), 
Lehmann and Modest (1988), and Connor and Korajczyk (1986).
For a discussion of some of the econometric and statistical issues surrounding the APT, see Shanken 
(1982), Shanken (1985), and the articles cited in those papers.
Actual implementations of APT models are described by Roll and Ross; Chen, Roll, and Ross; 
Lehmann and Modest; Connor and Korajczyk, etc.
References
Black, Fischer. "Estimating Expected Returns." Financial Analysts Journal, vol. 49, no. 5, 1993, pp. 
36–38.
Bower, D. H., R. S. Bower, and D. E. Logue. "A Primer on Arbitrage Pricing Theory." The Midland 
Journal of Corporate Finance, vol. 2, no. 3, 1984, pp. 31-40.
Chamberlain, G., and M. Rothschild. "Arbitrage, Factor Structure, and Mean-Variance Analysis on 
Large Asset Markets." Econometrica vol. 51, no. 5, 1983, pp. 1281–1304.
Chen, N., R. Roll, and S. Ross. "Economic Forces and the Stock Market." Journal of Business, vol. 
59, no. 3, 1986, pp. 383–404.


---


### Page 198


Page 193
Connor, Gregory. "A Unified Beta Pricing Theory." Journal of Economic Theory, vol. 34, no. 1, 
1984, pp. 13–31.
———. "Notes on the Arbitrage Pricing Theory." In Frontiers of Financial Theory, edited by G. 
Constantinides and S. Bhattacharya (Boston: Rowman and Littlefield, 1986).
Connor, Gregory, and Robert A. Korajczyk. "Performance Measurement with the Arbitrage Pricing 
Theory." Northwestern University working paper, 1986.
———. "Risk and Return in an Equilibrium APT: Application of a New Test Methodology." 
Journal of Financial Economics vol. 21, no. 2, 1988, pp. 255–290.
Fama, Eugene F., and Kenneth R. French. "The Cross-Section of Expected Stock Returns." Journal 
of Finance, vol 67, no. 2, 1992, pp. 427–465.
Grinold, R. "Is Beta Dead Again?" Financial Analysts Journal, vol 49, no. 4, 1993, pp. 28–34.
Haugen, Robert A., and Nardin L. Baker. "Commonality in the Determinants of Expected Stock 
Returns." Journal of Financial Economics, vol. 41, no. 3, 1996, pp. 401–439.
Huberman, G. "A Simple Approach to Arbitrage Pricing Theory." Journal of Economic Theory, vol. 
28, 1982, pp. 183–191.
Lehmann, Bruce N., and David Modest. "The Empirical Foundations of the Arbitrage Pricing 
Theory." Journal of Financial Economics, vol. 21, no. 2, 1988, pp. 213–254.
Mayers, D., and E. M. Rice. "Measuring Portfolio Performance and the Empirical Content of Asset 
Pricing Models." Journal of Financial Economics, vol. 7, no. 2, 1979, pp. 3–28.
Merton, R. C. "An Intertemporal Capital Asset Pricing Model." Econometrica, vol. 41, no. 1, 1973, 
pp. 867–887.
Pfleiderer, P. "A Short Note on the Similarities and the Differences between the Capital Asset 
Pricing Model and the Arbitrage Pricing Theory." Stanford University Graduate School of Business 
working paper, 1983.
Roll, Richard. "A Critique of the Asset Pricing Theory's Tests." Journal of Financial Economics, 
vol. 4, no. 2, 1977, pp. 129–176.
Roll, Richard, and Stephen A. Ross. "An Empirical Investigation of the Arbitrage Pricing Theory." 
Journal of Finance, vol. 35, no. 5, 1979, pp. 1073–1103.
———. "The Arbitrage Pricing Theory Approach to Strategic Portfolio Planning."Financial 
Analysts Journal, vol. 40, no. 3, 1984, pp. 14–26.
Rosenberg, Barr. "Extra-Market Components of Covariance in Security Returns."Journal of 
Financial and Quantitative Analysis, vol. 9, no. 2, 1974, pp. 263–274.
———. "The Capital Asset Pricing Model and the Market Model." Journal of Portfolio 
Management, vol. 7, no. 2, 1981, pp. 5–16.
Ross, Stephen A. "The Arbitrage Theory of Capital Asset Pricing." Journal of Economic Theory, 
vol. 13, 1976, pp. 341–360.
Rudd, Andrew, and Henry K. Clasing, Jr. Modern Portfolio Theory, 2d ed. (Orinda, Calif.: Andrew


---


### Page 199


Rudd, 1988).
Rudd, Andrew, and Barr Rosenberg. "The 'Market Model' in Investment Management."Journal of 
Finance, vol. 35, no. 2, 1980, pp. 597–607.


---


### Page 200


Page 194
Shanken, J. "The Arbitrage Pricing Theory: Is It Testable?" Journal of Finance, vol. 37, no. 5, 1982, 
pp. 1129–1140.
———. "Multi-Beta CAPM or Equilibrium APT? A Reply to Dybvig and Ross."Journal of 
Finance, vol. 40, no. 4, 1985, pp. 1189–1196.
———. "The Current State of the Arbitrage Pricing Theory." Journal of Finance, vol. 47, no. 4, 
1992, pp. 1569–1574.
Sharpe, William F. "Factor Models, CAPMs, and the APT." Journal of Portfolio Management, vol. 
11, no. 1, 1984, pp. 21–25.
Sharpe, William F. "The Capital Asset Pricing Model: A 'Multi-Beta' Interpretation." In Financial 
Decision Making under Uncertainty, edited by Haim Levy and Marshall Sarant (New York: 
Academic Press, 1977).
Sharpe, William F., and Gordon J. Alexander. Investments (Englewood Cliffs, N.J.: Prentice-Hall, 
1990).
Technical Appendix
This appendix contains
• A description of factor models of stock return
• A derivation of the APT in terms of factor models
Factor Models
A factor model represents excess returns as
where X is the N by K matrix of stock exposures to the factors, b is the vector of K factor returns, 
and u is the specific return vector.
For any portfolio P with holdings hP of the risky assets, the portfolio's factor exposures are
Recall that portfolio C is the fully invested portfolio with minimum variance and that portfolio Q is 
the fully invested portfolio that has the highest ratio of expected excess return to risk. In the 
technical appendix to Chap. 2, we established that the expected excess return on each asset is 
proportional to that asset's beta with respect to portfolio Q.
We assume that
• fc > 0, and thus portfolio Q exists and fQ > 0.


---

