# Grinold-Kahn Active Portfolio Management

## Pages 281-300


### Page 281


Page 275
this case, the forecast frequency (how often the forecasts arrive) is 1 month and the forecast horizon 
(the horizon over which the forecasts have predictive power) is 2 months. How do we operate in this 
situation? As we will show in Chap. 13, the answer is to treat the old forecast as a separate source of 
information and apply the basic forecasting formula.
Forecasting and Risk
Suppose the correlation between the S&P 500 and the MIDCAP has been 0.95 over the past 10 
years, but new information leads to a forecast that the S&P 500 will do poorly in the next quarter 
and the MIDCAP will do well. The temptation is to replace the historical correlation, 0.95, with a 
negative correlation, since we believe that S&P 500 and MIDCAP returns will move in opposite 
directions.
This temptation is incorrect. This line of thought confounds the notion of conditional means (i.e., the
expected return on the S&P 500 taking into consideration the research) and the notion of conditional 
covariance (i.e., how the research should influence forecasts of variance and covariance).
It is surprising to note that forecasts of returns have negligible effect on forecasts of volatility and 
correlation. It is even more surprising to note that what little effect there is has nothing to do with 
the forecast and everything to do with the skill of the forecaster. Thus, in our example, we would 
adjust the risk forecast in the same way even if the forecast were for the S&P 500 to do well and the 
MIDCAP to do poorly! This welcome news makes life easier. We can concentrate on the expected 
return part of the problem and not worry about the risk part.
This result arises because risk measures uncertainty in the return. A skillful forecaster can reduce 
the amount of uncertainty in the return, and a perfect forecaster reduces the uncertainty to zero (the 
returns can still vary from month to month, but only exactly according to forecast). For any 
forecaster, however, the size of the remaining uncertainty in the return stays the same, independent 
of any particular forecast. And, given typical skill levels, the reduction in risk due to the skill of the 
forecaster is minimal.


---


### Page 282


Page 276
TABLE 10.4
IC
σPOST
0.00
18.00
0.05
17.98
0.10
17.91
0.15
17.80
0.25
17.43
0.95
5.62
1.00
0.00
Let σPRIOR and σPOST be estimates of volatility without forecast information and with forecast 
information. The formula4 relating these is
Table 10.4 shows how a preforecast volatility of σPRIOR = 18 percent (annual) would change 
depending on the IC of the researcher. Reasonable levels of the IC (from 0 to 0.15) have very little 
effect on the volatility forecasts.
So much for the volatility forecasts. What about the correlations? The calculation is more 
complicated, but the general result will be the same. Consider the simplest case of two assets and 
two forecasts. We now have four balls in the air. We will call the assets S&P 500 (L for large) and 
MIDCAP (M for medium). The task is to determine how the correlation between the medium and 
large stock returns will be changed by our research. This will require some notation. Suppose that 
the correlation between the medium and large stock returns is ρML (in our example, ρML = 0.95). The 
term ICM captures the correlation between the forecasts for the MIDCAP and the subsequent 
MIDCAP returns. A typical (optimis4The basic variance forecasting formula is
Var{r|g} = Var{r} – Cov{r,g} · Var–1{g} · Cov{g,r}
This leads to Eq. (10.30). This formula is discussed in Proposition 2 of the technical appendix.


---


### Page 283


Page 277
tic) number is 0.1. The term ICL is the correlation between the large stock (S&P 500) forecasts and 
the subsequent S&P 500 returns—again, typically 0.1 or smaller.
We will assume that the correlation between the forecasts is also ρML. We also have to specify the 
cross-correlations between the MIDCAP forecasts and the S&P 500 return and between the S&P 
500 forecasts and the MIDCAP return. For simplicity, we will assume that these are zero.5
Under those reasonable assumptions, we find the following formula for the revised correlation:
At first, this appears to be a formidable equation. However, if ICM = ICL, then the naïve correlation 
forecast is unchanged. A little analysis will show that the correlation changes very little when the 
information coefficients are in the 0 to 0.15 range. Once again, the revised correlation depends only 
on our skill at forecasting and not on the forecast.
What can we conclude? The researcher who tries to forecast returns over the near horizon should 
ignore the slight impact of those forecasts on the volatility and correlation estimates for the assets. 
Asset allocators in particular should take note of this. Many asset allocators are seduced by the 
possibility of forecasting volatility and correlation along with returns. They believe that the market 
has changed and is obeying a new reality. The same force responsible for the exceptional returns is 
also changing the covariance structure. This is easier to imagine than to establish. There is some 
evidence of "regime changes" in short-run currency volatilities and correlations, however, in general 
there is more stability than instability in asset volatilities and correlations.
5It might be slightly more clever to say that the MIDCAP forecast gives us some insight (through ICM) into 
future MIDCAP returns, and that future MIDCAP returns give us insight (through ρML) into future S&P 500 
returns. That would lead us to correlations of ICM · ρML between the MIDCAP forecast and the S&P 500 return, 
and of ICL · ρML between the S&P 500 forecast and the MIDCAP return.


---


### Page 284


Page 278
Advanced Techniques
Up to this point, we have concentrated on simple techniques like counting in the binary model or 
linear regression. There are a host of more sophisticated forecasting procedures. As a general rule, 
increasing levels of sophistication carry both additional power and a larger chance that you may lose 
control of the process: The investment insights become submerged, the technique takes over, and 
you lose sight of the statistical significance of the results. If the technique is in control of you rather 
than the other way around, then you should probably look for more basic and more stable tools.
A guiding principle is to move from the simple to the more complicated; master the simple cases, 
understand the shortcomings, and then move to more complicated situations and techniques. Also, 
when using sophisticated techniques, always run two specific tests to make sure they are working 
correctly. First, see how they work when you feed in random data. Successful predictions from 
random data indicate a problem. Second, feed in simulated data where you know the underlying 
relationship. Does the sophisticated technique find it? Many sophisticated techniques do not come 
with associated statistical tests. Fortunately, modern computers, combined with the bootstrapping 
methodology, allow you to run your own statistical tests.
Here we will present several specific advanced techniques. In the next chapter, "Advanced 
Forecasting," we come back to the basic methodology, but apply it to more complex, real-world 
situations.
Time Series Analysis
This is a world unto itself, with its own jargon and notation. The textbook of Box and Jenkins 
(1976) is standard, as is the more recent treatment by Lütkepohl (1991). The litany of models is:
AR(q). Autoregressive: The time t value of a variable, r(t), depends on a weighted sum of the 
varible's past q values {r(t-1), r(t-2), . . . , r(t-q)} plus some random input, e(t):
r(t) = a0 + a1 · r(t – 1) + . . . + aq · r(t – q) + e(t)
MA(p). Moving average: The time t value of a variable is


---


### Page 285


Page 279
the weighted average of a sum of p + 1 random (independent) inputs e(t), e(t – 1), . . . , e(t – p):
r(t) = e(t) + c1 · e(t – 1) + . . . + cp · e(t – p) + c0
ARMA(q,p). Autoregressive moving average. You guessed it, a combination of AR(q) and MA(p).
ARIMA. ARMA applied to first differences; i.e., instead of looking at returns, look at the changes in 
returns.
VARMA. ARMA applied to more than one variable at a time: vector ARMA. The method predicts 
K returns using J possible explanatory variables along with their lagged values.
Arch, Garch, etc.
ARCH stands for autoregressive conditional heteroskedasticity, and GARCH for Generalized 
ARCH. Typically, the goal of these models is to forecast volatility (and sometimes correlations). 
Robert Engle developed this technique. For a review of applications in finance, see the article by 
Bollerslev, Chou, and Kroner (1992).
The ARCH and GARCH methods apply when volatility changes in some predictable fashion; e.g., 
periods of high volatility tend to follow large negative or positive returns. The standard GARCH 
model of volatility posits the following structure: Three factors influence current volatility. First, 
even changing volatility exhibits a long-run average. Second, mean reversion will tend to move 
current volatility toward that long-run average. Third, recent returns can shock volatility away from 
the long-run average. These are basic time series concepts applied to volatility instead of return.
More advanced GARCH models allow for the differing influence of large negative and large 
positive recent returns. We often observe that stock market volatility increases on downturns, but 
decreases as the market rises.
ARCH and related nonlinear techniques are most useful when a limited number of returns are under 
consideration; i.e., they are more appropriate for asset allocation than for stock selection. In risk 
models, these techniques can enhance the forecast covariance matrix by improving the forecast of 
market or systematic risk. The


---


### Page 286


Page 280
idea is to extract the most important single factor, and then apply this advanced technique to that 
one time series. ARCH techniques are most pronounced when the investment horizon is short—days 
rather than the longer investment horizon of months or years. Finally, ARCH techniques can be 
extremely useful in strategies that have a strong option component, because better volatility 
forecasts lead directly to better option prices.
Kalman Filters
Kalman filters are closely linked to Bayesian analysis. Our fundamental forecasting law is a simple 
example. We start with a prior mean and variance for the returns and then adapt that mean and 
variance conditional on some new information. Kalman filters work in the same manner, although 
their working is often obscured by electrical engineering/optimal control jargon. See Bryson and Ho 
(1969), chap. 12, for an introduction to Kalman filters and an exploration of the links with Bayesian 
analysis when the random variables are normally distributed. See the paper of Diderrich (1985) for a 
link between Kalman filters and Goldberger-Theil estimators in regression analysis.
Chaos
Chaos theory concerns unstable and nonlinear phenomena. In the investment context, it has come to 
mean the discovery and use of nonlinear models of return and volatility. We would like to 
distinguish between random phenomena and predictable phenomena that are generated in a 
deterministic but highly nonlinear way. These can appear to be the same thing.
A typical example is the random-number generator. Computers generate random numbers in a 
totally reproducible way, but the numbers appear to be random. The forecaster using chaos theory 
starts with the output of the random-number generator and tries to reverse-engineer the nonlinear 
rules that are used to produce its outputs. This is not an easy task.
Another example of chaos is the tent map. Given an initial number x(0) between 0 and 1, we 
generate the next number with


---


### Page 287


Page 281
Figure 10.1
If x(t) gets stuck on 0, choose x(t+1) at random. This rule will produce a sequence of numbers that 
looks very much like a sequence of randomly distributed numbers between 0 and 1. However, if we 
look in two dimensions at the pairs {x(t-1),x(t)}, we see that they all lie on the tent-shaped line in 
Fig. 10.1. For a true sequence of random numbers, the pairs {x(t-1),x(t)} would fill up the entire 
square in two dimensions.
To apply chaos theory to forecasting, take the residuals from the forecasting rules and look at these 
two-, three-, and higher-dimension pictures for evidence of a nonlinear relationship like the tent 
map. If there is such evidence, strengthen the model by trying to capture that relationship. See the 
paper by Hsieh (1995) for an excellent application of this idea and some interesting modeling 
techniques.
Neural Nets6
In the past few years, application of neural nets to various problems across the spectrum of the 
investment world has gained wide pub6Hertz, Krogh, and Palmer (1991) is a standard reference.


---


### Page 288


Page 282
Figure 10.2
licity. Hornik, Stinchcombe, and White (1988) have shown that neural nets can approximate almost 
any conceivable function. In problems involving high signal-to-noise ratios, neural nets have proved 
to be a powerful analytic tool. In problems involving low signal-to-noise ratios, in particular 
forecasting exceptional returns, the applicability of neural nets is far from certain.7
Neural nets are a model of computation inspired by biological neural circuitry (see Fig. 10.2). Each 
artificial neuron weights several input signals to determine its output signal nonlinearly. Typically, 
as the weighted input signal exceeds some threshold T, the output quickly varies from 0 to 1. A 
neural network is an assembly of these artificial neurons, with, for example, a layer of input neurons 
feeding into an inner (hidden) layer of neurons that feeds into an output layer (Fig. 10.3).
Neural nets can solve very general problems, but they are not very intuitive. Unlike more standard 
computer programs, neural nets do not have the problem solution built into them from the
7See Kahn and Basu (1994).


---


### Page 289


Page 283
Figure 10.3
ground up. Instead, they are taught how to solve the problem by training them with a particular set 
of data. The neural net is trained (its internal coefficients estimated) to optimally match inputs with 
desired outputs. Therefore, neural nets are very dependent on the data used for training.
Neural nets have been applied to many areas of research and finance. All of these fall into two 
general categories, which we can illustrate by example. We characterize the first category by the 
problem of modeling bond ratings. Here we wish to apply neural net technology to predict bond 
ratings from underlying company financial data. Effectively, we are reverse-engineering the process 
implemented by Moody's and S&P. We can characterize this problem by its nonlinear relation 
between the financial data and the ratings, its relative stability over time, and its high signal-to-noise 
ratio. We can illustrate the second general category by the application of neural nets to forecasting 
returns. Here we wish to use neural nets to predict asset returns from underlying financial and 
economic data and past returns. We can characterize this problem by its nonlinear relation between 
explanatory variables and observed returns, its relative instability over time, and its low signal-tonoise ratio.
Neural nets have worked well for the first type of problem, characterized by nonlinearities, stable 
relationships, and high signal-to-noise ratios. As for the second type of problem, many financial 
researchers have applied neural nets here, with many claims of success. However, definitive and 
statistically significant proof of success is still lacking.


---


### Page 290


Page 284
Genetic Algorithms8
Genetic algorithms are a heuristic optimization method motivated by a loose analogy to the process 
of biological evolution. Species evolve through survival of the fittest; each generation begets the 
next through a mixture of mating, mutation, and training. The overall population thus evolves in a 
semirandom manner toward greater fitness.
The computational analogy is optimizing a function of several variables, where each combination of 
the variables defines an ''individual" and the function to be maximized is the "fitness" criterion.
We choose a random initial "population" and evaluate the fitness of each individual member; then 
we create each successive generation by combining the fittest members of its prior generation. We 
repeat this last step until we converge to a best solution. A strong element of randomness in the 
"evolution" step allows wide exploration of possible solutions. For instance, we can randomly 
combine elements of the fitter solutions or randomly alter some elements of a fit solution—we label 
these "mating" and "mutation," respectively.
One area where we have applied genetic algorithms is the paring problem, e.g., find the best 50stock portfolio to track the S&P 500. A standard quadratic optimizer can find the optimal portfolio 
weights for a given list of 50 stocks to track the S&P 500. The tricky part is to search through the 
possible lists of 50 names. The combinatorics involved guarantee that we can't exactly solve this 
problem.
BARRA and others have developed heuristic approaches to this problem. After considerable 
research efforts (~6 person-months), they have developed methods which quickly (a few seconds on 
a 1998 PC) find reasonable answers. As an alternative, they coded a genetic algorithm in a weekend; 
it found similarly good answers to this problem after about 48 hours of CPU time on a similarly 
powered machine. So for this type of problem, genetic algorithms are quite attractive as one-time 
solutions. They are perhaps less attractive for use in industrial-strength commercial software.
8Holland (1975) is a standard reference.


---


### Page 291


Page 285
In the realm of forecasting, we often search for the signal with maximum information ratio. Imagine 
instead a "population" of possible signals, initially chosen at random, which we then "evolve" using 
the criterion of maximum information ratio.
Since genetic algorithms are effectively able (in successful applications) to "learn" the 
characteristics of the fittest solutions, they require less coding than analytic techniques, and they run 
faster than an explicit examination of all possible solutions.
Summary
Active management is forecasting. We can use a basic forecasting formula to adjust forecast returns 
away from the consensus, based on how far the raw forecasts differ from the consensus and on the 
information content of the raw forecasts. We capture this basic result in the forecasting rule of 
thumb: The exceptional return forecast takes on the form volatility · IC · score. The chapter has 
applied these relationships in several specific examples.
The next chapter will move on to some more complicated situations, especially those involving 
multiple assets and cross-sectional forecasts.
Problems
1. Assume that residual returns are uncorrelated, and that we will use an optimizer to maximize riskadjusted residual return. Using the data in Table 10.3, what asset will the optimizer choose as the 
largest positive active holding? How would that change if we had assigned α = 1 for buys and α = –
1 for sells? Hint: At optimality, assuming uncorrelated residual returns, the optimal active holdings 
are
2. For the situation described in Problem 1, show that using the forecasting rule of thumb, we 
assume equal risk for each asset. What happens if we just use α = 1 for buys and α = –1 for sells?


---


### Page 292


Page 286
3. Use the basic forecasting formula [Eq. (10.1)] to derive Eq. (10.20), the refined forecast in the 
case of one asset and two forecasts.
4. In the case of two forecasts [Eq. (10.20)], what is the variance of the combined forecast? What is 
its covariance with the return? Verify explicitly that the combination ofg and g' in the example leads 
to an IC of 0.1090. Compare this to the result from Eq. (10.23).
5. You are using a neural net to forecast returns to one stock. The net inputs include fundamental 
accounting data, analysts' forecasts, and past returns. The net combines these nonlinearly. How 
would the forecasting rule of thumb change under these circumstances?
References
Bickel, P. J., and K. A. Doksum. Mathematical Statistics (San Francisco: Holden Day, 1977), pp. 
127–129.
Black, Fisher, and Robert Litterman, "Global Asset Allocation with Equities, Bonds, and 
Currencies." Fixed Income Research, Goldman, Sachs & Co., New York, October 1991.
Bollerslev, T., R. Y. Chou, and K. F. Kroner. "ARCH Modeling in Finance." Journal of 
Econometrics, vol. 52, no. 1, April 1992, pp. 5–59.
Box, George E. P., and Gwilym M. Jenkins. Time Series Analysis: Forecasting and Control (San 
Francisco: Holden-Day, 1976).
Bryson, A. E., and Y. C. Ho. Applied Optimal Control. (Waltham, MA: Blaisdell, 1969).
Chopra, Vijay Kumar, and Patricia Lin. "Improving Financial Forecasting: Combining Data with 
Intuition." Journal of Portfolio Management, vol. 22, no. 3, 1996, pp. 97–105.
Diderrich, G. T. "The Kalman Filter from the Perspective of Goldberger-Theil Estimators." The 
American Statistician, vol. 39, no. 3, 1985, pp. 193–198.
Grinold, Richard C. "Alpha Is Volatility Times IC Times Score, or Real Alphas Don't Get Eaten." 
Journal of Portfolio Management, vol. 20, no. 4, 1994, pp. 9–16.
Hertz, J., A. Krogh, and Richard G. Palmer. Introduction to the Theory of Neural Computation 
(Redwood City, Calif.: Addison-Wesley, 1991).
Holland, John H. Adaptation in Natural and Artificial Systems (Ann Arbor: University of Michigan 
Press, 1975).
Hornik, K., M. Stinchcombe, and H. White. "Multi-layer Feedforward Networks Are Universal 
Approximators." Working paper, University of California, San Diego, June 1988.
Hsieh, D. A. "Chaos and Nonlinear Dynamics: Application to Financial Markets. "Journal of 
Finance, vol. 46, no. 5, 1991, pp. 1839–1877.


---


### Page 293


Page 287
———. "Nonlinear Dynamics in Financial Markets: Evidence and Implications. "Financial 
Analysts Journal, vol. 51, no. 4, 1995, pp. 55–62.
Johnson, N. L., and S. Kotz. Distributions in Statistics: Continuous Multivariate Distributions (New 
York: John Wiley & Sons, 1972), pp. 40–41.
Kahn, Ronald N., and Archan Basu. "Neural Nets and Fixed Income Strategies. "BARRA 
Newsletter, Fall 1994.
Lütkepohl, H. Introduction to Multiple Time Series Analysis (New York: Springer-Verlag, 1991).
Rao, C. R. Linear Statistical Inference and Its Application, 2d ed. (New York: John Wiley & Sons, 
1973), pp. 314–333.
Searle, S. R. Linear Models (New York: John Wiley & Sons, 1971), pp. 88–89.
Theil, Henri. Principles of Econometrics (New York: John Wiley & Sons, 1971), pp. 122–123.
Technical Appendix
This appendix will cover two technical topics: deriving the basic forecasting formula, along with 
some related technical results, and analyzing specific examples from the main text of the chapter.
The Basic Forecasting Formula
We will now show that the basic forecasting formula provides the linear unbiased estimate with 
minimum mean squared error. Most statistics books discuss this topic under the name of either 
minimum variance unbiased estimates (m.v.u.e.) or best linear unbiased estimates (b.l.u.e.),9 and 
deal with the case where Var{g}, E{g}, and Cov{r,g} are unknown.
Let's start with the estimate:
Proposition 1
 is
1. An unbiased estimate of r
2. The estimate of r that has the smallest mean squared error among all linear estimates of r
9See Bickel and Doksum (1977), pp. 127–129; Theil (1977), pp. 122–123; and Rao (1973), pp. 314–333.


---


### Page 294


Page 288
Proof
A general linear estimate can be written as
The estimation error is q = r – r(g;b,A), and the mean squared error is
To minimize the mean squared error, we take the derivative of MSE{b,A} with respect to each of 
the N elements of b and each of the N · K elements of A and set them equal to 0.
Setting the derivative with respect to bn equal to 0 yields
This result, along with Eq. (10A.2), demonstrates that the expected error is 0, i.e., the linear estimate 
that minimizes mean squared error is unbiased. We can therefore restrict our attention to linear 
estimates of the form
For convenience, let us introduce the notation s = g – E{g} and p = r – E {r}. With this notation, we 
have q = p – A · s, and so E{g} = 0 and
Taking the derivative of the mean squared error with respect to the element An,k leads to
According to Eq. (10A.7), the errors in our estimate are uncorrelated


---


### Page 295


Page 289
with the raw forecasts. If q and s are correlated, we are leaving some information on the table; we 
should exploit any correlation to further reduce the mean squared error.
In matrix notation, Eq. (10A.7) becomes
Equations (10A.9) and (10A.5) now demonstrate that 
 is the linear estimate with minimum mean 
squared error.
The linear estimate 
 has additional properties if r and g have a joint normal distribution.
Proposition 2
If {r,g} have a normal distribution, then
1. 
 is the maximum likelihood estimate of r given g.
2. 
 = E{r|g} is the conditional expectation of r given g.
3. Var{r|g} = Var{r} – Cov{r,g} · Var–1{g} · Cov{g,r} is the conditional variance of r given g.
4. 
 has minimum mean squared error among all unbiased estimates, whether they are linear or not.
Proof
The covariance of r and g is
and the inverse covariance matrix is
Given an observation {p,s} and the normal distribution assumption, the likelihood of that 
observation is


---


### Page 296


Page 290
Maximizing the log likelihood function is therefore equivalent to minimizing
If we fix s and choose p to minimize Eq. (10A.13), the optimal p* is
However, since Q is the inverse of V, we can use Eqs. (10A.10) and (10A.11) to show that
Equations (10A.14) and (10A.15) establish item 1.
Items 2 and 3 are standard properties of the multinormal distribution.10 Note that
Item 4 involves some statistical theory. There is a covariance matrix, called the Cramer-Rao lower 
bound, such that the covariance of any unbiased estimate of r will be greater than or equal to the 
Cramer-Rao lower bound.11 In the case of normal random variables, one can show that Var{r|g} 
equals the Cramer-Rao lower bound, and thus it is the minimum-variance unbiased estimate without 
adding the restriction that the estimate must be linear.
Technical Treatment of Examples
We have now proved the basic forecasting formula and discussed some further technical results. The 
remainder of the appendix will discuss some specific examples from the main text concerning 
multiple forecasts for an asset.
Let's consider the case of one asset with K forecasts:
10See Johnson and Kotz (1972), pp. 40–41.
11See Rao (1973) or Searle (1971).


---


### Page 297


Page 291
Now the covariance matrix between the return and these K signals will involve K information 
coefficients:
We can now substitute Eqs. (10A.18) and (10A.19) into the basic forecasting formula [Eq. (10.2)], 
to find
Using our definition of scores, z, we can simplify this to
Furthermore, we can use Eq. (10A.21) to calculate the variance


---


### Page 298


Page 292
of the combined signal, its covariance with the return, and hence its combined information 
coefficient:
Equations (10A.21) and (10A.23) are the general results. If K = 1, then ρg = 1, and these reduce to 
the standard volatility · IC · score. If K = 2, then
which is basically Eq. (10.20) in the main text. We can similarly show that Eq. (10A.23) reduces to 
Eq. (10.23) when K = 2.
If K = 3, we need to invert:
For any number of forecasts, the key is to invert the matrix ρg. Note that for any number of 
forecasts, Eq. (10A.21) always leads to refined forecasts of the form
The refined forecast is always a linear combination of the scores. The goal of this methodology is 
simply to determine the weights (the adjusted information coefficients) in that linear combination.


---


### Page 299


Page 293
Exercise
1. Using Eq. (10A.21), what is the variance of the combined forecast? What is its covariance with 
the return? Remember that the combined forecast is simply a linear combination of signals. We 
know the volatilities and correlations of all the signals, and we know the correlation of each signal 
with the return.
Verify Eq. (10A.23) for the IC of the combined forecast. Demonstrate that when K = 2, it reduces to 
Eq. (10.27) in the main text of the chapter.


---


### Page 300


Page 295
Chapter 11— 
Advanced Forecasting
Introduction
Chapter 10 covered forecasting basics, especially the insight that refined alphas control for 
volatility, skill, and expectations. In the context of a single asset, Chapter 10 also examined how to 
combine multiple signals, and even briefly presented some choices of advanced and nonlinear 
methodologies.
Chapter 10 has provided much of the insight into forecasting. But it hasn't covered the standard case 
facing institutional managers: multiple assets. This chapter will mainly focus on that important 
practical topic. It will also cover the particular case of factor forecasts, and some ideas about dealing 
with uncertain information coefficients.
Highlights will include the following:
• The single-asset methodology also applies to multiple assets.
• A complication occurs when we have cross-sectional and not time series scores. In many cases, we 
need not multiply cross-sectional scores by volatility.
• If you have information and you forecast some factor returns, do not set other factor forecasts to 
zero.
• Uncertainty in the IC will lead to shrinkage in the alpha.
We begin with the discussion of multiple assets.


---

