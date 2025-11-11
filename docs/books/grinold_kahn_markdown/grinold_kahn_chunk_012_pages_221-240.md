# Grinold-Kahn Active Portfolio Management

## Pages 221-240


### Page 221


Page 215
subject to
for s∈Φ(T).
The linear program maximizes the sum of the end-period wealths across the possible states, subject 
to the constraints of initial wealth nonpositive [Eq. (8A.6)], self-financing strategies [Eq. (8A.7)], 
end-period wealth definition [Eq. (8A.8)], and nonnegative end-period wealth in each possible state 
[Eq. (8A.9)].
Given the constraints of initial wealth nonpositive and final wealth nonnegative, this linear program 
has a feasible solution: NSn(s,t) = 0 for all n, s, and t. By the no-arbitrage condition, this is an 
optimal solution as well; i.e., no solution will exhibit positive value for the objective.
The duality theorem of linear programming then implies that there will be an optimal solution q(s,t) 
to the dual problem. The dual problem is


---


### Page 222


Page 216
for all n = 0, . . . , N; 0 ≤ t < T; s∈Φ(t), and
for all s∈Φ(T).
Let q(s,t) be an optimal dual solution. Equation (8A.13) guarantees that q(s,T) are positive, and in 
fact greater than 1. We can further show, by successive applications of Eq. (8A.11), that eachq(s,t) 
is positive, using the risk-free asset:
Define the conditional probabilities π*(z,t + 1 | s,t) by
This definition, along with Eq. (8A.11), leads to the intertemporal valuation formula
This formula requires probabilities in states (z,t+1) conditional on predecessor states (s,t). We would 
like to rewrite these in terms of unconditional probabilities, which we can derive starting with π*
(1,0) = 1. Then, using the laws of probability and the fact that state s at time t+1 has a unique 
predecessor φ(s,t+1) at time t,
The valuation multipliers are then


---


### Page 223


Page 217
Repeated application of Eqs. (8A.16) through (8A.18) will demonstrate Proposition 1, Eq. (8A.4).7,8
Options Pricing
The most familiar context for the modern theory of valuation is in options pricing. Here is an 
example, which we also used in the main text of the chapter. Consider a single stock and a single 1month period with two equally likely outcomes. The stock can go either up, the UP event, or down, 
the DN event. The risk-free asset increases in value from 1.00 to RF = (1 + iF)1/12 = 1.00487, 
corresponding to an annual interest rate of 6 percent. The stock's initial price is p = 50, and its final 
value is equally likely to be
7This proof demonstrates the existence but not the uniqueness of the valuation mulipliers. Only if we have a 
complete market will we have unique valuation multipliers. In a complete market, for any t, we will be able to 
devise a self-financing strategy that pays off 1 in state s and 0 in states u∈S(t), u 
 s. Not only that, we will be 
able to determine the minimum initial input, V*(s,t), into a self-financing strategy necessary to produce W(s,t) = 
1, W(u,t) = 0 for u∈S(t), u
 s. The term V*(s,t) will be positive because of the no-arbitrage condition, and
8Proposition 1 required the absence of arbitrage opportunities. In practice, e.g., if we generate prices via Monte 
Carlo, the process may not be exactly arbitrage-free. However, we can trick the process into being arbitrage-free by 
assuming that the original probabilities are the Martingale probabilities and adjusting the original prices 
appropriately. To be exact, define δn(s,t) and adjusted prices 
for z∈Ω(s,t).
With these adjusted prices, Eq. (8A.16) will hold using the original probabilities. Variations of this idea are used 
sometimes in options pricing theory.


---


### Page 224


Page 218
pUP = 53 or pDN = 49. The outcomes UP and DN are equally likely: πUP = πDN = 0.5.
Now let's calculate the valuation measure in the UP and DN states. Following Eq. (8A.11), the dual 
linear program in this simple case is
with q0 ≥ 0 and qUP, qDN ≥ 1. Solving for 
, we find 0.62 and 1.38, 
respectively.
We can check that these valuation multiples correctly value both the risk-free asset and the stock. 
These multiples will be nonnegative9 as long as 
, and their expected value 
will always be 1.0.
Of course, options pricing theory was developed to price options, and given these valuation 
multiples, we can price any claim contingent on the stock price. For this simple case in particular, 
we can price options maturing at the end of the period, with payouts dependent on the ending stock 
value. The payout for a call option would have the form Max[0, S(T) – K], where K is the strike 
price.
We can easily expand this framework to multiple periods. For a more substantial treatment, see the 
texts by Cox and Rubinstein and by Hull.
Connection with the CAPM and APT
The main body of the chapter discussed the connection between valuation and expected returns. We 
revisit that topic here. Let pn be the initial value of stock n, dn the dividends paid on the stock (at the 
end of the month), and 
 the final value. Let Rn, RF, and RQ be the total returns on the stock, the 
risk-free asset, and portfolio Q. The excess returns are rn and rQ. In the CAPM, portfolio Q is the 
market.
9If these conditions do not hold, then arbitrage opportunities exist.


---


### Page 225


Page 219
Proposition 2
The valuation function υ depends only on the return to portfolio Q, according to
Proof
Define the return on asset n with outcome s as
Since portfolio Q defines expected excess returns,
The definition of covariance implies
Now, Eq. (8A.25), in combination with Eqs. (8A.24) and (8A.21), leads to
This is the desired result.
Notice that υ depends only on portfolio Q's return. The expected value of υ is 1 and, since κ > 0, υ 
decreases as the market return increases. Reasonable estimates of κ are between 1.5 and 2.00; as an 
example, we'll choose 1.75. Hence υ is negative if rQ > fQ + 0.57. If the expected annual excess 
return to the market was approximately 6 percent, this would be a 63 percent excess market return: 
more than a three standard deviation event. In fact, the largest two annual S&P 500 returns since 
1926 have been a 54 percent return in 1933 and a 53 percent return in 1954.
Proposition 2 relates the valuation multipliers υ to the excess return to portfolio Q. Alternatively, we 
can introduce a new portfolio, portfolio S, which also explains excess returns and whose total


---


### Page 226


Page 220
returns are directly proportional to the valuation multipliers. For the purpose of this technical 
appendix, portfolio S provides simply another view of excess returns and valuation. We introduce 
portfolio S because (although we will not make use of this property) it is also a more robust 
approach to excess returns and valuation than portfolio Q. We require very few assumptions to 
determine that portfolio S exists and explains excess returns. For example, while we require that the 
expected excess return to portfolio C be positive for the existence of portfolio Q, portfolio S exists 
and explains expected excess returns even without that assumption.
Portfolio S
We define a portfolio S as the portfolio containing both risky and riskless assets with the minimum 
second moment of total return. We will investigate the properties of portfolio S, including its 
relation to excess returns, portfolio Q, and the valuation multipliers.
The total return for any portfolio P is given by RP = 1 + iF + rP. Portfolio S solves the problem
where portfolio P contains both risky and risk-free assets. The risk-free portfolio would give us 
second moment 
. Portfolio S has even less.
Proposition 310
For any portfolio P, we have
10This proposition is actually true much more generally. We can let Rs and RP be the returns to strategies 
involving rebalancing, option replication, etc. Given a stochastic risk-free rate, and RF the return to the strategy 
that rolls over the risk-free investment, we find
as in the main text of the appendix.


---


### Page 227


Page 221
where
Proof
Consider a portfolio P(w) with fraction (1 – w) invested in portfolio S and fraction w invested in 
portfolio P. The total return on this mixture will be
Define gP(w) as the expected second moment of the return on the mixture:
Since Rs is the portfolio that has minimum second moment, the derivative of gP(w) at w = 0 must be 
zero. Hence
for any portfolio P. We can expand this to
Equation (8A.33) holds for any portfolio P, including the risk-free portfolio F, and so
Combining Eqs. (8A.33) and (8A.34) leads to Proposition 3, Eq. (8A.28).
Proposition 3 demonstrated the connection between portfolioS and expected returns. We also know 
the connection between portfolio Q and expected returns. And so, there is a link between portfolio S 
and portfolio Q.
Proposition 4
If
• Portfolio S solves Eq. (8A.27)


---


### Page 228


Page 222
• Portfolio Q is the fully invested portfolio with maximum Sharpe ratio11
then portfolio S is a mixture of portfolio F and portfolio Q:
Proof
Given an arbitrary starting fully invested portfolio P, consider a portfolio P(w) composed of a 
fraction w invested in portfolio P and a fraction (1 – w) invested in portfolio F. Its total return is
Now choose w to minimize the expected second moment, 
, of the return. The optimal w is
with associated optimal expected second moment
As long as SRP is not zero, we can do better than just the risk-free portfolio. In fact, the larger SRP is 
in absolute value, the better we can do. We achieve the minimum second moment over all portfolios 
(risky plus risk-free) by choosing the fully invested portfolio P that maximizes 
 portfolio Q. 
This proves Proposition 4, Eq. (8A.35).
Our final task is to express the valuation multiples in terms of portfolio S.
11We are making the familiar assumption that portfolio C has positive expected excess return, and so portfolio 
Q—the fully invested portfolio that explains expected excess returns—exists.


---


### Page 229


Page 223
Proposition 5
The valuation multiples are
Proof
Combining Proposition 3 [Eq. (8A.28)], which explains expected excess returns using portfolio S, 
and Proposition 2 [Eq. (8A.21)], which expresses the valuation multiples in terms of portfolio Q, we 
can derive
Since φ = –1/E{RS}, this simplifies to Proposition 5, Eq. (8A.40).
Exercises
1. Using the definitions from the technical appendix to Chap. 2, what is the characteristic associated 
with portfolio S?
2. Show that the portfolio S holdings in risky assets satisfy
V · hS = –E{RS} · f
3. Show that portfolio S exists even if fC < 0, and that if fC = 0, then portfolio S will consist of 100 
percent cash plus offsetting long and short positions in risky assets.
4. Prove the portfolio S analog of Proposition 1 in the technical appendix of Chap. 7, i.e., that the 
factor model (X, F, Δ) explains expected excess returns if and only if portfolio S is diversified with 
respect to (X, F, Δ).
Applications Exercises
1. If portfolio Q is the MMI and µQ = 6 percent, what is portfolio S? Use Proposition 4 of the 
technical appendix, which expresses portfolio S in terms of portfolio Q.


---


### Page 230


Page 224
2. Using the result from the first applications exercise, what is the valuation multiple in the state 
defined by rQ = 5 percent? Use Proposition 5 of the technical appendix. If interest rates are 6 
percent, what is the value of an option which pays $1 in 1 year only in the state defined by rQ = 5 
percent? Assume that the probability of that state occurring is 50 percent.


---


### Page 231


Page 225
Chapter 9— 
Valuation in Practice
Introduction
The previous chapter investigated the theory of valuation. That theory has proved useful in valuing 
options, futures, and other derivative instruments, but has yet to be used for the valuation of 
equities. In this chapter, we will look at some of the quantitative methods that have been used for 
equity valuation. These will be ad hoc, although they will have some vague connection with theory. 
The reader should not be surprised that the chapter does not describe a ''right" way to value stocks. 
We described the theoretically correct approach in the previous chapter. This chapter is evidence of 
our inability to make the theoretically correct scheme operational. We have to turn to more ad hoc 
schemes.
The reader should keep the humility principle in mind: The marketplace may be right and you may 
be wrong. The reader should also keep the fundamental law of active management in mind: You 
don't have to be right much more than 50 percent of the time to add value! With these modest goals 
in mind we shall commence.
Insights included in this chapter are:
• The basic theory of corporate finance provides ground rules for acceptable valuation models.
• The standard valuation model is the dividend discount model, which focuses on dividends, 
earnings, and growth. Dividend discount models are only as good as their growth forecasts.


---


### Page 232


Page 226
• Comparative valuation models price attributes of a firm.
• Returns-based analysis focuses directly on the ultimate goal of valuation models: forecasting 
exceptional returns. Returns-based analysis is related to APT models.
The goal is to find assets that are unfairly valued by the market, hoping that the market will 
eventually correct itself. This requires some insight. Quantitative methods can help to focus that 
insight and use it efficiently, but they are not a substitute for insight.
Corporate Finance
The modern theory of corporate finance is based on the notion of market efficiency. Modigliani and 
Miller showed the power of market efficiency in their classic studies demonstrating that
• Dividend policy influences only the scheduling of cash flows received by the shareholder. It is a 
"pay you now or pay you later" arrangement. Dividend policy doesn't affect the total value of the 
payments.
• A firm's financing policy does not affect the total value of the firm. Financing policy will keep the 
total value of the firm's liabilities constant.
These ideas were extremely controversial at first, but they have stood up for decades and are at least 
partially responsible for the authors' Nobel prizes. Active managers with market inefficiency in their 
veins can read these two precepts as: "Dividend and financing policy aren't very important." Any 
valuation method that hinges on some magic associated with dividends or debt financing may be 
dangerous.
The economic value of a firm comes from its profitable activities. If the firm can transform inputs it 
buys for $1.00 into outputs it sells 3 months later for $1.45, then the firm can profit. If the firm can 
find additional projects that create value, then the firm can grow. This ability to generate profits and 
to make those profits grow is at the heart of attempts at valuing the firm. Much of the confusion 
about the Modigliani and Miller results arises from two issues: taxes and a failure to separate the 
operations of the firm from its financing activities.


---


### Page 233


Page 227
Let's ignore taxes for the moment. The failure to separate operations from financial decisions is 
quite natural. A firm borrows because it has capital expenditures that are needed to support future 
growth. A firm increases its dividend because its operations have been successful and future success 
is anticipated. We want to separate the operational considerations (the new plant, the successful 
product, etc.) from the financial. The new plant could have been financed from either retained 
earnings (reduced dividends), sale of new equity, or issuance of new debt. The benefits of the 
successful product launch could be used to retire debt, kept as retained earnings, or distributed as 
dividends. With the aid of the Modigliani and Miller principles, we can consider the firm's equity 
value as stemming from two sources: operational value and financial value:
In a simple context, the financial value is the difference between the firm's capital surplus and its 
debt. The capital surplus is any money left after we have paid dividends and interest (if any) and 
paid for new investments that are needed in order to grow or sustain the operational side of the 
business.
The operational value is derived from the revenue from operations (excluding interest), less the cost 
of those operations (labor, materials, and support, but not interest expense), and less the capital costs 
of maintaining and augmenting the capital stock (plant, machines, research, etc.).
As an example, think of two firms operating side by side. The widget side of the business builds 
widgets, sells widgets, and invests in new and better widget-making equipment. The financing side 
of the business pays interest, pays dividends, retains earnings, issues (or repurchases) shares, and 
issues (or repurchases) bonds. If the financial side of the business is net long (retained earnings plus 
paid-in capital exceeds debt), then it invests the balance at the risk-free rate. If the financing side is 
net short, then it pays interest on the difference between the equity account and the bond account.
As Modigliani and Miller point out, value is created on the widget side of the business. The 
financial side of the business moves money through time and allocates shares of the operational 
value between stock- and bondholders. A debt incurred today implies a


---


### Page 234


Page 228
sequence of interest payments in the future. The present value of those interest payments is equal to 
the present value of the debt.
Figure 9.1 shows the flows into and out of our prototype firm. On the first level, we have the 
operating company. We call its output the cash flow. The cash flow is an input to the financial 
company. As we can see, the financial company pays dividends, pays interest if there is a debt 
position, collects interest on the capital surplus (if any), and either issues or repurchases dept and 
equity.
Figure 9.1 might be called the world according to Modigliani and Miller. It is a conceptually useful 
way to look at the firm. Unfortunately, accountants don't share this view. Accounting information is 
based on the aggregate of the operational and financial sides of the firm. By adjusting dividend and 
debt policy, it is possible to manipulate not only dividends and debt/equity ratios, but earnings per 
share (EPS), the growth in EPS, earnings-to-price ratios, and book-to-price ratios.
The reader should keep these Modigliani and Miller principles in mind in conjuring up and 
evaluating valuation schemes. Most of those schemes start with the notion of dividends. We'll start 
there too.
Figure 9.1


---


### Page 235


Page 229
The Dividend Discount Model
John Burr Williams, in his classic Theory of Investment Value, anticipated much of modern financial 
theory. In particular, Williams stressed the role of dividends as a determinant of value in an early 
version of the dividend discount model. An investor is paid for an investment either through 
dividends or through the sale of the asset. The sale price is based on the market's assessment of the 
firm's ability to pay future dividends.
Other variables such as earnings may be important in valuing a firm, but their importance is derived 
from their ability to predict the future flow of dividends to the investor. So high current earnings 
may signal the firm's ability to increase dividends, and low current earnings signal a possible future 
decrease in dividends, or at least delays in future increases.
This emphasis on dividends appears to clash with the Modigliani and Miller principle on dividend 
policy. This is not really the case. You can read the Modigliani and Miller principle as "pay me now 
or pay me later." What Modigliani and Miller say is that the firm is free to schedule the payment of 
the dividends to the investor in any way it likes. The scheduling will not (or should not) affect the 
market's perception of the value of the firm.
The emphasis on dividends may also appear jarring to today's U.S. equity investors, conditioned to 
focus almost exclusively on price appreciation, almost to the point of disdaining current dividends. 
This wasn't always the case. In the 1950s and earlier, dividend yields exceeded bond yields. Equities 
are riskier than bonds, so investors required added incentives to purchase equities, according to the 
logic then. Even now, high-yield bonds follow this trend.
Certainty
If p(0) is the price of the firm at time 0, iF is the per-period interest rate, and d(t) is the certain 
dividend to be paid at time t, then both Williams and our theoretical valuation formula would say 
that


---


### Page 236


Page 231
The Constant-Growth Dividend Discount Model
The constant-growth, or Gordon-Shapiro, dividend discount model assumes that dividends grow at a 
constant rate g. In other words,
Substituting Eq. (9.4) into Eq. (9.3) and applying some algebra, we find the simplified formula
This is the fundamental result of the constant-growth dividend discount model. Given a dividend d
(1) and a growth rate g, the stock price increases as the dividend discount rate decreases, and vice 
versa. Low prices imply high dividend discount rates, and high prices imply low dividend discount 
rates or high growth rates.
We will now consider another approach that leads to the same destination and provides further 
insight into Eq. (9.5). We can split the return on a stock into two parts, the dividend yield and the 
capital appreciation:
where p
=
the price of the stock at the beginning of the 
period
 
=
the price of the stock at the end of the period
d
=
the dividend paid in the period (assumed to be 
paid at the end)
iF =
the risk-free rate of interest
r
=
the excess return
ξ =
the uncertain amount of capital appreciation
Let g = E{ξ} be the expected rate of capital appreciation, f = E{r} be the expected excess return, and 
y = iF + f be the expected total rate of return. Taking expected values, Eq. (9.6) becomes
We are assuming that the dividend is known or that d represents the expected dividend. We are also 
assuming that the expected total rate of return over the period, iF + f, equals the internal rate of


---


### Page 237


Page 232
return y, which is the (constant) average return calculated over the entire future stream of dividends.
Solving Eq. (9.7) for the price leads back to the constant-growth dividend discount model result:
Equations (9.5) and (9.8) imply that the expected rate of capital appreciation is identical to the 
expected rate of dividend growth. So far, this is something of a tautology, since we have, in fact, 
defined g to make this work. But we will next introduce a model for growth g, to show that we can 
equate it to the expected rate of capital appreciation.
Modeling Growth
We can use a simple model to show that the expected rate of capital appreciation equals the growth 
in the company's earnings per share and the growth in the company's dividends. Let
e(t) =
earnings in period t
d(t) =
dividends paid out at the end of period t
κ =
company's payout ratio
I(t) =
amount reinvested
ρ =
return on reinvested earnings
and assume that the payout ratio κ and reinvestment rate of return ρ remain constant. In particular, 
assume that $1 of investment produces an expected perpetual stream of ρ dollars per period. Then, 
earnings either flow into dividends or are reinvested:
The dividends constitute a fraction κ of the earnings:
The reinvested earnings constitute the remaining fraction (1 – κ) of the earnings:


---


### Page 238


Page 233
And, since reinvestment produces returns ρ, we can determine e(t + 1) based on e(t) and the fraction 
reinvested:
Equation (9.12) simply states that next year's earnings equal this year's earnings plus an increase due 
to the return on the portion of this year's earnings that was reinvested (the increase in equity).
Of course, e(t) and e(t + 1) lead to the growth rate:
The payout ratio is constant, and hence dividends are proportional to earnings. Therefore, the 
dividend growth rate [in Eq. (9.15)] is also the earnings growth rate [in Eq. (9.13)]. Moreover, this 
growth rate is determined by both the reinvestment rate 1 – κ (a measure of opportunity) and the 
average return on reinvested capital ρ [from Eq. (9.14)]. This average return on invested capital is, 
in turn, linked to the return on equity. Suppose b(t) is the book value at time t, and we start with e(1) 
= ρ · b(0); then book value will grow at rate g as well, and ρ will be the constant return on equity: e
(t) = ρ · b(t – 1).
Multiple Stocks
The more general form of the dividend discount model for multiple stocks indexed by n = 1, 2, . . . 
N is
The multiple-stock version of Eq. (9.7) becomes


---


### Page 239


Page 234
We can give this analysis some teeth by combining it with the consensus expected returns. The 
expected return fn includes both consensus expected returns2 and alphas: fn = βn · fB + αn. Substituting 
into Eq. (9.17), we see that
We illustrate this relationship in Fig. 9.2, for a 4 percent risk-free rate, a 6 percent expected excess 
return on the benchmark, and an asset beta of 1.2. If the asset's yield is 2.5 percent, then it will be 
fairly priced, αn = 0, if the expected rate of capital appreciation is 8.7 percent.
Figure 9.2
2Here we will assume that the expected benchmark return fB matches the long-run consensus expected 
benchmark return µB; i.e., we are assuming no benchmark timing.


---


### Page 240


Page 235
If we solve Eq. (9.18) for alpha, then we have a simple model for expected exceptional return in 
terms of yield, risk (as measured by beta), and growth:
This formula points out the most important insight we must keep in mind while using a dividend 
discount model:
The Golden Rule of the Dividend Discount Model: g in, g out.
Each additional 1 percent of growth adds 1 percent to the alpha. The alphas that come out of the 
dividend discount model are as good as (or as bad as) the growth estimates that go in. If it's garbage 
in, then it's garbage out.
Implied Growth Rates
We can use Eq. (9.19) in a novel way: starting with the presumption that the assets are fairly priced, 
and determining the growth rates necessary to fairly price the assets. We call these the implied 
growth rates:
We know the risk-free rate iF, and we can estimate the beta and the yield with reasonable accuracy. 
We can also make a reasonable estimate of the expected excess return on the market fB.
The implied growth rates are handy in several ways. First they provide a rational feel for what 
growth rates should be, and help to point out consistent biases in analysts' estimates, either within 
sectors or across all stocks. Second, the implied growth rates can identify companies whose prices 
reflect unrealistic growth prospects.
For example, in Table 9.1 we have listed the Major Market Index stocks along with their yield, 60month historical beta, and implied growth rates as of December 1992. The table assumes an 
expected excess return on the Major Market Index, fB, of 6 percent and uses the risk-free rate (3month Treasury bills) of 3.1 percent, which was the rate at the end of December 1992.


---

