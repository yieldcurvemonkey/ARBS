# Grinold-Kahn Active Portfolio Management

## Pages 421-440


### Page 421


Page 416
of ψ relative to a composite portfolio. Assuming that active returns rPA relative to the composite are 
independent and normally distributed with mean 0 and standard deviation ψ, the probability of 
observing an active return less than some rPA,max is
The probability of observing N independent active returns, each less than rPA,max, is
We can therefore solve for the expected (median) rPA,max as
Assuming symmetry, we will find a similar result for the expected minimum. Hence
as reported in the main text.
Exercises
1. Show that the minimum-risk portfolio with factor exposures xp is given by hP = HT · xP, where H 
is defined in Eq. (14A.4). Recall that a portfolio is diversified with respect to the factor model 
(X,F,Δ), diversified for short, if it has minimum risk among all portfolios with the same factor 
exposures. This result says that all diversified portfolios are made up of a weighted combination of 
the factor portfolios.
2. Show that the optimal specific asset holdings hSP, defined in Eq. (14A.6), have zero exposure to 
all the factors, i.e., XT · hSP = 0.


---


### Page 422


Page 417
3. Establish the following: If the benchmark portfolio is diversified and the alphas are benchmarkneutral, then both αCF and αSP are benchmark-neutral.
4. Establish the identities
Hint: Recall Exercise 5 in the technical appendix of Chap. 3.
5. Establish the identity
6. Show that the common-factor component of alpha leads to the common-factor holdings, i.e., 2 · 
λA · V · hCF = αCF, and that the specific component of alpha leads to the specific holdings, i.e., 2 · λA · 
V · hSP = αSP. This implies the identities
7. This exercise invokes regression to separate the components of alpha. Show that we can calculate 
the factor alphas αF using a weighted regression, α = X · αF + ∈, with weights inversely 
proportional to specific variance. The residual of this regression, i.e., ∈, will equal αSP.
8. Suppose we wish to constrain the common-factor exposures to satisfy Q · x = p, where Q is a J 
by K matrix of rank J. This could constrain some factor exposures and leave others unconstrained. 
Let p* be the result using the original alpha and an unconstrained optimization, i.e., 
. 
Show that the revised alpha
will result in a portfolio that satisfies the constraints.


---


### Page 423


Page 418
9. Consider the optimization
Maximize {hT · α – λA · hT · V · h}
subject to the inequality constraints
b ≤ A · h ≤ d
Show that any modified α+, where α+ satisfies
2 · λA · b ≤ A · V-1 · α+ ≤ 2 · λA · d
will produce a portfolio that satisfies the inequality constraints. How would you choose α+?
10. Input alphas are cash-neutral if they lead to an active cash position of zero. Show that alphas are 
cash-neutral if and only if 
, where hC is the fully invested portfolio with minimum risk.
11. To make the alphas both benchmark- and cash-neutral, modify them as follows:
α+ = α – CB · V · hB – CC · V · hC
Choose the constants CB and CC to ensure benchmark neutrality, 
, and cash neutrality, 
. Why?
Applications Exercises
For these exercises, you will need alphas from a dividend discount model for all MMI stocks. 
(Alternatively, you could use alphas from some other valuation model, but it would be useful to 
have some intuition for these sources of alphas.)
1. Generate the unconstrained optimal portfolio using moderate active risk aversion of λA = 0.10 and 
the CAPMMI as benchmark. What is the optimal portfolio beta? What are the factor exposures of 
the optimal portfolio? Discuss any concerns over these factor exposures.
2. Now industry-neutralize the alphas and reoptimize. What are the new factor exposures? Compare 
the benefits of this portfolio to the previous optimal portfolio. How would you justify an argument 
that the first portfolio should outperform the second?


---


### Page 424


Page 419
Chapter 15— 
Long/Short Investing
Introduction
U.S. institutions have invested using long/short strategies since at least the late 1980s. These 
strategies have generated controversy, and, over time, increasing acceptance as a worthwhile 
innovation. Long/short strategies offer a distinct advantage over long-only strategies: the potential 
for more efficient use of information, particularly but not exclusively downside information.
This chapter will analyze several important aspects of long/short strategies and, by implication, 
some important and poorly understood aspects of long-only strategies. We will define long/short 
strategies and briefly introduce their advantages and the controversies surrounding these advantages. 
We will then analyze in detail the increased efficiency offered by long/short strategies and the subtle 
but pervasive effects of the long-only constraint. This analysis is therefore important to all 
managers—not just those offering long/short strategies. We will later discuss the appeal of 
long/short strategies and some empirical observations. The chapter ends with the usual notes, 
references, and technical appendix.
The main results of this chapter include the following:
• The benefits of long/short investing arise from the loosening of the (surprisingly important) longonly constraint.
• Long/short implementations offer the most improvement over long-only implementations when 
the universe of assets is large, the assets' volatility is low, and the strategy has high active risk.


---


### Page 425


Page 420
• The long-only constraint tends to induce biases, particularly toward small stocks. Surprisingly, it 
can limit the ability to completely act on upside information, by not allowing short positions that 
could finance long positions.
In this chapter, we will define long/short strategies specifically as equity market–neutral strategies. 
These strategies have betas of 0 and equal long and short positions. Some databases group these 
strategies in the more general category of ''hedge fund." However the hedge fund category can 
include almost any strategy that allows short positions. We will focus much more specifically on 
equity strategies managed according to the principles of this book, and with zero beta and zero net 
investment.
Long/short investing refers to a method for implementing active management ideas. We can 
implement any strategy as long/short or long-only. Long/short investing is general. It does not refer 
to a particular source of information.
Now, every long-only portfolio has an associated active portfolio with zero net investment and often 
zero beta. Therefore, every long-only portfolio has an associated long/short portfolio. But the longonly constraint has a significant impact on this associated long/short portfolio. Long/short strategies 
provide for more opportunities—particularly in the size of short positions in smaller stocks 
(assuming a capitalization-weighted benchmark).
Long/short strategies are becoming increasingly popular. According to Pensions and Investments 
(May 18, 1998), 30 investment management firms offer market-neutral strategies, up from the 21 
investment management firms one year earlier.
Market-neutral strategies are something of a "phantom" strategy. The Pensions and Investments list 
does not include many large investment management firms that offer market-neutral strategies. It 
also appears to underreport the assets invested for some of the firms listed. Market-neutral strategies 
short stocks, a strategy frowned upon by some owners of funds. This apparently leads to enhanced 
discretion by the managers. But this is only part of the controversy.


---


### Page 426


Page 421
The Controversy
Proponents of long/short investing offer several arguments in its favor. One simple argument 
depends on diversification. A long/short implementation includes effectively a long portfolio and a 
short portfolio. If each of these portfolios separately has an information ratio of IR, and the two 
portfolios are uncorrelated, then the combined strategy, just through diversification, should exhibit 
an information ratio of IR · √2. The problem with this argument is that it applies just as well to the 
active portfolio associated with any long-only portfolio. So this argument can't be the justification 
for long/short investing.
A second argument for long/short investing claims that the complete dominance of long-only 
investing has preserved short-side inefficiencies, and hence the short side may offer higher alphas 
than the long side.
The third and most important argument for long/short investing is the enhanced efficiency that 
results from the loosening of the long-only constraint. The critical issue for long/short investing isn't 
diversification, but rather constraints.
These arguments in favor of long/short investing have generated considerable controversy. The first 
argument, based on diversification, is misleading if not simply incorrect. Not surprisingly, it has 
attracted considerable attack. The second argument is difficult to prove and brings up the issue of 
the high implementation costs associated with shorting stocks. The third argument is the critical 
issue, with implications for both long/short and long-only investors.
The Surprising Impact of the Long-Only Constraint
We are interested in the costs imposed by the most widespread institutional constraint—the 
restriction on short sales—or, equivalently, the benefits of easing that constraint. We will ignore 
transactions costs and all other constraints, and focus our attention on how this constraint affects the 
active frontier: the trade-off between exceptional return α and risk ω.
Let's start with a simple market that has N assets and an equal-weighted benchmark. We presume in 
addition that all assets have


---


### Page 427


Page 422
identical residual risk ω and that residual returns are uncorrelated. This model opens a small 
window and allows us to view the workings of the long-only constraint.
Let αn be the expected residual return on asset n and λR the residual risk aversion. In this setup, 
assuming that we want zero active beta, the active position for asset n is
The overall residual (and active) risk ψP is
We know from Chap. 10 that alphas have the form 
, where zn is a score with 
mean 0 and standard deviation 1, and we have invoked the fundamental law of active management 
to write the information coefficient in terms of the information ratio and the number of assets. 
Hence, the active positions and portfolio active risk become
We can use Eqs. (15.3) and (15.4) to link the active position with the desired level of active risk ψP, 
the stock's residual risk ω, and the square root of the number of assets 
The limitation on short sales becomes binding when the active position plus the benchmark holding 
is negative. For an equal-weighted benchmark, this occurs when
Figure 15.1 shows this information boundary as a function of the number of stocks for different 
levels of active risk.


---


### Page 428


Page 423
Figure 15.1 
Sensitivity to portfolio active risk.


---


### Page 429


Page 424
Information is wasted if the z score falls below the minimum level. The higher the minimum level, 
the more information we are likely to leave on the table. As an example, if we consider a strategy 
with 500 stocks, active risk of 5 percent, and typical residual risk of 25 percent, we will waste 
information whenever our score falls below –0.22. This will happen 41 percent of the time, 
assuming normally distributed scores.
This rough analysis indicates that an aggressive strategy involving a large number of lowervolatility assets should reap the largest benefits from easing the restriction on short sales. The more 
aggressive the strategy, the more likely it is to hit bounds. The lower the asset volatility, the larger 
the active positions we take. The more assets in the benchmark, the lower the average benchmark 
holding, and the more likely it is that we will hit the boundary.
Indirect Effects
In a long-only optimization, the restriction against short selling has both a direct and an indirect 
effect. The direct effect, studied above, is to preclude exploiting the most negative alphas. The 
indirect effect grows out of the desire to stay fully invested. In that case, we must finance positive 
active positions with negative active positions. Hence, a scarcity of negative active positions can 
affect the long side as well: Overweights require underweights.
Put another way, without the long-only constraint we could take larger underweights relative to our 
benchmark. But since underweights and overweights balance, without the long-only constraint we 
will take larger overweights as well.
We can illustrate this "knock-on" effect with a simple case. We start with an equal-weighted 
benchmark and generate random alphas for each of the 1000 assets. Then we construct optimal 
portfolios in the long-only and long/short cases. Figure 15.2 displays the active positions in the 
long/short and long-only cases, with assets ordered by their alphas from highest to lowest.
In the long/short case, there is a rough symmetry between the positive and negative active positions. 
The long-only case essentially assigns all assets after the first 300 the same negative alpha. We 
expected that the long-only portfolio would less efficiently handle neg-


---


### Page 430


Page 425
Figure 15.2 
Long/short and long-only active positions: equal weighted benchmark.


---


### Page 431


Page 426
ative alphas than the long/short portfolio. More surprisingly, Fig. 15.2 shows that it also less 
efficiently handles the positive alphas.
The Importance of the Benchmark Distribution
This knock-on effect is more dramatic if the benchmark is not equal-weighted. We can illustrate this 
with an extreme case where the benchmark consists of 101 stocks. Stock 1 is 99 percent of the 
benchmark, and stocks 2 through 101 are each 0.01 percent: Gulliver and 100 Lilliputians. To make 
this even simpler, suppose that 50 of the Lilliputians have positive alphas of 3.73 percent and 50 
have negative alphas of the same magnitude. We consider two cases: Gulliver has a positive alpha, 
again 3.73 percent, and Gulliver has a negative alpha, –3.73 percent.
In the long/short world, the capitalization of the stocks is irrelevant. Table 15.1 displays the active 
positions of the stocks, along with some portfolio characteristics:
Gulliver does not merit special consideration in the long/short world. Gulliver, Ltd., receives the 
same active position as a Lilliputian company with a similar alpha. Note that since all of the active 
positions are smaller than 
, the no-short-sale restriction would not be binding if the benchmark 
assets were equal-weighted.
We encounter significant difficulty with the highly imbalanced benchmark when we disallow short 
sales. In that case, it makes a
TABLE 15.1 
Long/Short Results
Characteristic
α (Gulliver)
Positive
Negative
Gulliver active position
0.79%
–0.79%
Positive stock active 
position
0.79%
0.80%
Negative stock active 
position
–0.80%
–0.79%
Portfolio alpha
3.00%
3.00%
Portfolio active risk
2.00%
2.00%


---


### Page 432


Page 427
TABLE 15.2 
Long-Only Results
Characteristic
α (Gulliver)
Positive
Negative
Gulliver active position
0.01%
–1.55%
Positive stock active 
position
0.01%
0.04%
Negative stock active 
position
–0.01%
–0.01%
Portfolio alpha
0.04%
0.15%
Portfolio active risk
0.02%
0.39%
great deal of difference whether Gulliver's alpha is positive or negative. With a negative alpha, we 
assume a very large negative active position (–1.55 percent) that allows us to finance the overweightings of the Lilliputians with positive alphas.1 But when Gulliver has a positive alpha, we can 
achieve only tiny active positions, both long and short. Table 15.2 displays the results.
The Gulliver example illustrates another problem: the potential for a significant size imbalance. The 
shortage of negative active positions causes relatively larger underweighting decisions on the 
higher-capitalization stocks. If the alpha on Gulliver had a 50/50 chance of being a positive or 
negative 3.73 percent, the average active holding of Gulliver would be –0.77 percent.
Capitalization-Weighted Benchmarks
The Gulliver example shows that the distribution of capitalization in the benchmark is an important 
determinant of the potential for
1There is an alternative approach:
• Relax the condition that the net overweight must equal the net underweight.
• Use a short cash position (leverage!) to finance the overweights.
• Sell the benchmark forward to cover the added benchmark exposure.
In the Gulliver model, this procedure allows us to achieve an alpha of 1.53 percent with an active risk of 1.42 
percent. The negative cash position is 39 percent of the portfolio's unlevered value.


---


### Page 433


Page 428
adding value in a long-only strategy. To calculate the benefits of long/short investing in realistic 
environments, we will need a model of the capitalization distribution. This requires a short detour.
We will use Lorenz curves to measure distributions of capitalization. To construct them, we must
• Calculate benchmark weight as a fraction of total capitalization.
• Order the assets from highest to lowest weight.
• Calculate the cumulative weight of the first n assets, as n moves from largest to smallest.
The Lorenz curve plots the series of cumulative weights. It starts at 0 and increases in a concave 
fashion until it reaches 1. If all assets have the same capitalization, it is a straight line.
Figure 15.3 shows Lorenz curves for the Frank Russell 1000 index, an equal-weighted portfolio, and 
a model portfolio designed (as we will describe below) to resemble the Frank Russell 1000 index.
One summary statistic for the Lorenz curve is the Gini coefficient, which is twice the area under the 
curve less the area under the equal-weighted curve. Gini coefficients must range between 0 (for 
equal-weighted benchmarks) and 1 (for single-asset benchmarks). So we can draw Lorenz curves 
for benchmarks with any arbitrary distribution of capitalization, and summarize any distribution 
with a Gini coefficient. To progress further, we must assume a specific form for the distribution of 
capitalization.
A Capitalization Model
We will assume that the distribution of capitalization is log-normal. Here is a one-parameter model 
that will produce such a distribution.
First, we order the N assets by capitalization, from largest (n = 1) to smallest (n = N). Define
These values look like probabilities. They start close to 1 and move toward 0 as the capitalization 
decreases. Next, we calculate a nor-


---


### Page 434


Page 429
Figure 15.3 
Lorenz curves: 1000 assets.


---


### Page 435


Page 430
TABLE 15.3
Country
Index
Assets
Gini
Constant c
U.S.
Frank Russell 1000
1000
0.71
1.55
U.S.
MSCI
381
0.66
1.38
U.K.
MSCI
135
0.63
1.30
Japan
MSCI
308
0.65
1.35
The Netherlands
MSCI
23
0.64
1.38
Freedonia
Equal weight
101
0.00
0.00
Freedonia
Cap weight
101
0.98
11.15
mally distributed quantity yn such that the probability of observing yn is pn:
where Φ{ } is the cumulative normal distribution.
So far, we have converted linear ranks to normally distributed quantities yn. To generate 
capitalizations, we use
We can choose the constant c to match the desired Gini coefficient or to match the Lorenz curve of 
the market.2
We used this model to match the Frank Russell 1000 Index in Fig. 15.3. Table 15.3 contains similar 
results for several markets covered by Morgan Stanley Capital International (MSCI) Indexes as of 
September 1998. The equal-weighted and Gulliver examples reside in the hypothetical land of 
Freedonia.3
The constant c ranges from 1.30 to 1.60 in a large number of countries. To analyze the loss in 
efficiency due to the long-only
2As an alternative, set the constant c to the standard deviation of the log of the capitalization of all the stocks. 
The two criteria mentioned in the text place greater emphasis on fitting the larger-capitalization stocks.
3Freedonia appeared in the 1933 Marx Brothers movie Duck Soup. During a 1994 Balkan eruption, when asked if 
the United States should intervene in Freedonia, several U.S. congressmen laughed, several stated that it would 
require further study, and several more were in favor of intervention if Freedonia continued its policy of ethnic 
cleansing.


---


### Page 436


Page 431
constraint, we will use the value 1.55. This stems from a feeling that the MSCI indices necessarily 
trim out a great many of the smaller stocks in a market. The Freedonia rows show an equal and a 
very unequal benchmark for comparison purposes.
Armed with this one-parameter model of the distribution of capitalization, we are ready to derive 
our rough estimates of the potential benefits of long/short investing.
An Estimate of the Benefits of Long/Short Investing
We cannot derive any analytical expression for the loss in efficiency due to the long-only constraint, 
since the problem contains an inequality constraint. But we can obtain a rough estimate of the 
magnitude of the impact with a computer simulation. As our previous simple analysis showed, the 
important variables in the simulation include the number of assets and the desired level of active 
risk. We considered 50, 100, 250, 500, and 1000 assets, with desired risk levels* from 1 to 8 percent 
by 1 percent increments, and from there to 20 percent by 2 percent increments.
For each of the 5 levels of assets and the 14 desired risk levels, we solved 900 randomly generated 
long-only optimizations. For each case, we assumed uncorrelated residual returns, identical residual 
risks of 25 percent, a full investment constraint, and an information ratio of 1.5. We ignored 
transactions costs and all other constraints. We generated alphas using
Figure 15.4 shows the active efficient frontier: the alpha per unit of active risk.
We can roughly estimate the efficient frontiers in Fig. 15.4 as
4We used Eq. (15.4) to convert desired risk levels to risk aversions. We required extremely high levels of 
desired risk, since the long-only constraint severely hampers our ability to take risks.


---


### Page 437


Page 432
Figure 15.4


---


### Page 438


Page 433
and, as elsewhere in the book, we measure α and ω in percent.
As anticipated, with the information ratio held constant, long-only implementations become less and 
less effective, the greater the number of assets. We can also see that higher desired active risk 
lowers efficiency. In fact, we can define an information ratio (and information coefficient) 
shrinkage factor as
Figure 15.5 illustrates the dependence of shrinkage on risk and the number of assets. For typical 
U.S. equity strategies—500 assets and 4.5 percent risk—the shrinkage is 49 percent according to 
Eq. (15.13),
Figure 15.5


---


### Page 439


Page 434
which agrees with Fig. 15.5. The long-only constraint has enormous impact: It cuts information 
ratios for typical strategies in half!
Equation (15.13) also allows us to quantify the appeal of enhanced indexing strategies, i.e., lowactive-risk strategies. The shrinkage factor is 71 percent for a long-only strategy following 500 
assets with only 2 percent active risk. At this lower level of risk, we lose only 29 percent of our 
original information ratio.
At high levels of active risk, long/short implementations can have a significant advantage over longonly implementations. At low levels of active risk, this advantage disappears. And, given the higher 
implementation costs of long/short strategies (e.g. the uptick rule, costs of borrowing), at very low 
levels of active risk, long-only implementations may offer an advantage.
With a large number of assets and the long-only constraint, it is difficult to achieve higher levels of 
active risk. Using Eq. (15.11), we can derive an empirical analog of Eq. (15.4):
See the technical appendix for details.
Figures 15.4 and 15.5 illustrate efficient frontiers under several assumptions: an inherent 
information ratio of 1.5, a log-normal size distribution constant c = 1.55, and identical and 
uncorrelated residual risks of 25 percent. We have analyzed the sensitivities of the empirical results 
to these assumptions.
Changing the inherent information ratio does not affect our conclusions at all. As Eq. (15.11) 
implies, the efficient frontier simply scales with the information ratio.
Changing the log-normal size distribution constant through the range from 1.2 to 1.6, a wider range 
than we observed in examining several markets, has a very minor impact. Lower coefficients are 
closer to equal weighting, so the long-only constraint is less restrictive. At 4.5 percent active risk 
and 500 assets, though, as we vary this coefficient, the shrinkage factor ranges only from 0.49 to 
0.51.
Figure 15.6 shows how our results change with asset residual risk. Our base-case assumption of 25 
percent is very close to the median U.S. equity residual risk. But we may be focusing on a more 
narrow universe. As asset residual risk increases, we can achieve more risk with smaller active 
positions, making the long-


---


### Page 440


Page 435
Figure 15.6 
Sensitivity to asset residual risk.
only constraint less binding. At the extremely low level of 15 percent, the long-only constraint has 
very high impact. In the more reasonable range of 20 to 35 percent, the shrinkage factor at 4.5 
percent risk and 250 assets ranges from 65 to 54 percent.
We can also analyze the assumption that every asset has equal residual risk. Given an average 
residual risk of 25 percent, and assuming 500 assets, we analyzed possible correlations between size 
(as measured by the log of capitalization) and the log of residual risk. We expect a negative 
correlation: Larger stocks tend to exhibit lower residual risk. Looking at large U.S. equities (the 
BARRA HICAP universe of roughly the largest 1200 stocks), this correlation has varied from 
roughly –0.51 to –0.57 over the past 25 years.
Figure 15.7 shows the frontier as we vary that correlation from 0 to –0.6. With a correlation of 0, we 
found a shrinkage factor of 49 percent at 4.5 percent active risk. With a correlation of –0.6, the 
situation improves, to a shrinkage factor of 0.63.
Finally, Fig. 15.8 displays the size bias that we anticipated. Figure 15.8 shows the result for various 
correlations between size and the log of residual risk, though the correlation does not signifi-


---

