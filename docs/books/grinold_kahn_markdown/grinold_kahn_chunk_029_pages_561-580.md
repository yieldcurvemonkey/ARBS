# Grinold-Kahn Active Portfolio Management

## Pages 561-580


### Page 561


Page 556
Proposition 1
1. The portfolio BT,
is the minimum-risk, fully invested portfolio with β = βBT. As is clear from Eq. (19A.1), it is a linear 
combination of the benchmark and portfolio C.
2. Portfolio BT is also the minimum-residual-risk, fully invested portfolio with β = βBT.
3. Portfolio BT has residual risk ωBT:
where βPA is portfolio BT's active beta: βPA = βBT – 1.
Proof
To prove item 1, start with the observation that portfolio BT is clearly fully invested, since the 
weights in Eq. (19A.1) sum to 1, and the benchmark and portfolio C are fully invested. We can also 
quickly verify that portfolio BT has β = βBT. More generally, we can show that portfolio BT is the 
solution to the problem
It is the minimum-risk portfolio, subject to the constraints of full investment and β = βBT. To derive 
Eq. (19A.1), we must solve the minimization problem, use the definition of portfolio C, and use the 
definition of the vector β in terms of the benchmark portfolio.
To prove item 2, for any portfolio P, we can decompose total risk as
Among the universe of all portfolios with β = βP, the minimum-total-risk portfolio is also the 
minimum-residual-risk portfolio.


---


### Page 562


Page 557
To prove item 3, we can calculate the residual holding for portfolio BT:
Using Eq. (19A.8), we can directly calculate residual variance and verify Eq. (19A.2).
We can use this result to analyze further the value-added implications of this unavoidable residual 
risk. Assuming T forecasts per year, we will incur expected residual risk over the year of
The expected residual variance each period is
where the benchmark total variance over period 
. Using Eq. (19.14) from the main text, 
which solves for the active beta each period, Eq. (19A.10) becomes
Subtracting the value-added cost of this expected unconditional residual variance from the expected 
unconditional value added from benchmark timing [Eq. (19.16)] leads to
As we discussed in the main text, remembering that 
 and assuming σB = 18 percent and 
σC = 12 percent leads to βC = 4/9. Equation (19A.13) then shows that benchmark timing via stock 
selection leads to positive net value added only if the investor's


---


### Page 563


Page 558
aversion to residual risk is significantly less than his or her aversion to benchmark timing risk.
Exercise
1. Prove Eq. (19A.1), the formula for the minimum-risk, fully invested portfolio with β = βBT.
Applications Exercises
Using the MMI stocks, build portfolio BT, the minimum-risk, fully invested portfolio with β = 1.05 
relative to the (benchmark) CAPMMI. Also build portfolio C from MMI stocks.
1. What is the beta of portfolio C?
2. Compare portfolio BT to the linear combination of portfolio C and portfolio B (the CAPMMI) 
according to Eq. (19A.1).
3. What is the residual risk of portfolio BT? Compare the result to Eq. (19A.2).


---


### Page 564


Page 559
Chapter 20— 
The Historical Record for Active Management
Introduction
What makes for successful active management? We have argued that the process of successful 
active management consists of efficiently utilizing superior information. It has two key elements: 
finding superior information, and efficiently building portfolios based on that information.
Some sections of this book have described the meaning of superior information: better than the 
consensus, high information ratio, positive information coefficient, and, most likely, high breadth. 
We have also devoted many chapters to efficiently utilizing superior information. We showed how 
to process raw signals into alphas, how to build alphas into portfolios, how to trade off alphas 
against risk, and the cost of transacting.
We now want to step away from our prescriptions and view the historical record for active 
management. Ultimately we will want to see the historical evidence for our view of successful 
active management.
Finance academics have a fairly long history of studying active manager performance. Their 
motivation has typically been in the context of efficient markets theory. According to the strong 
version of the theory, active management is impossible. There is no source of superior information. 
Hence, efficient utilization is irrelevant. Of course some active managers will outperform and others 
will underperform, but no more so than at the roulette wheel, where some gamblers win through 
sheer luck.


---


### Page 565


Page 560
Studies of Performance
As we discussed in Chap. 17, studies of active managers' performance began soon after the 
development of the CAPM, which provided a framework for performance analysis. Pioneers in this 
field included Jensen (1968), Sharpe (1966), and Treynor (1965).
Studies of managers' performance have focused on three separate questions: Has the average active 
manager outperformed, are the top performers skillful or lucky, and does performance persist? Note 
that a negative answer to the first of these questions would not prove that successful active 
management is impossible.
Let's start with the first question, about average manager performance. The early studies found that 
on average, mutual funds underperformed the index on a risk-adjusted basis, and that there existed a 
direct relationship between the level of fund expenses and the amount of underperformance. 
Subsequent work, summarized by Ippolito (1993), found that the performance of the average fund, 
net of expenses and on a risk-adjusted basis, is statistically indistinguishable from that of the index. 
At best, the performance of the average fund only matches the index.
More recent academic work on this question has extended the previous work in three directions: 
overcoming survivorship bias, controlling for style, and looking at portfolio holdings. Brown, 
Goetzmann, Ibbotson, and Ross (1992) demonstrate that survivorship bias in manager databases can 
significantly affect the results of performance studies. Several subsequent studies have very 
carefully built databases free of survivorship bias by including all funds that are no longer in 
business. Malkiel (1995), for example, shows that from 1982 through 1991, the average equity 
mutual fund still existing in 1991 underperformed the S&P 500 by 43 basis points per year. But 
when he includes all funds that existed over that period, even those no longer in business in 1991, 
the average underperformance drops to 1.83 percent per year. Survivorship bias is important, and 
the average U.S. equity manager significantly underperforms the S&P 500.
Several more recent academic studies analyzing manager performance have controlled for style and 
for publicly available information. Chapter 17 has described these methods. For example, Ferson 
and Schadt (1996) and Ferson and Warther (1996) control for


---


### Page 566


Page 561
publicly available information—namely, interest rates and market dividend yields—in analyzing 67 
U.S. equity mutual funds1 from 1968 through 1990. Their approach improves average manager 
performance from below the market to matching the market. While their database suffers from 
survivorship bias, they claim that this should not affect their result concerning the improvement in 
average manager performance.
From a slightly different perspective, Jones (1998) has analyzed median institutional manager 
performance. He finds that he can explain median performance relative to the S&P 500 almost 
entirely with three variables: market return, small-capitalization stocks versus large-capitalization 
stocks, and value stocks versus growth stocks. The average manager owns some cash, has a bias 
toward small stocks, and has a bias toward growth stocks. Hence, the average manager tends to 
underperform when the market is up, large-capitalization stocks outperform, and/or value stocks 
outperform growth stocks.
Daniel, Grinblatt, Titman, and Wermers (1997) control for size, book-to-price, and one-year 
momentum effects, and use quarterly portfolio holdings for more than 2500 U.S. equity mutual 
funds from 1975 through 1994 in their analysis. Their approach begins by estimating quarterly 
asset-level returns beyond the effects of size, book-to-price, and momentum. They do this by 
assigning all assets to 1 of 125 groupings based on quintile rankings for these three characteristics, 
and then looking at each asset's active return relative to its (capitalization-weighted) group return. 
To analyze mutual fund returns, they use the quarterly holdings and these active asset returns. They 
find statistically significant evidence for positive average performance of 1 to 1.5 percent, but only 
for growth and aggressive growth funds over the entire period. Most of this arises from performance 
from 1975 through 1979.
But we must view even this small evidence for average outperformance sceptically, since the study 
ignored both fees and transactions costs. The study used not the actual mutual fund returns, but 
returns to quarterly buy-and-hold portfolios with no quarterly rebalance charges. There is little 
reason to believe that the average
1Ferson and Warther examine 63 funds.


---


### Page 567


Page 562
growth or aggressive growth fund delivered any of that outperformance to investors.
Overall, there is no evidence for average active management's producing exceptional returns. 
Fortunately, this says nothing about the possibility of successful active management. Why would we 
expect the average manager to outperform?
To focus more on the possibility of successful active management, Marcus (1990) looked at whether 
top-performing mutual funds exhibited statistically significant positive performance, given the large 
number of funds in existence. The Marcus study is a rigorous version of the classic (and anecdotal) 
defense of active management: ''Look at Peter Lynch, look at Warren Buffet." Using statistics for 
the maximum of a sample, he shows that the very top funds do outperform. Peter Lynch and Warren 
Buffet don't appear to be just the two out of tens of thousands of investors who are lucky enough to 
flip heads 10 or 15 times in a row. So this is one study that demonstrates that successful active 
management is possible.
But beyond whether the average fund outperforms or whether the top fund outperforms, the question 
concerning the possibility of successful active management that has received the most attention is 
whether performance persists. We now turn to this question.
Persistence of Performance
Do the winners in one period remain winners in a subsequent period? After 30 years of intensive 
research, the results fall into two camps: those that do not find persistence, and those that do.
Several studies have shown, based on different asset classes and different time periods, that 
performance does not persist. Jensen (1968) looked at the performance of 115 mutual funds over the 
1945–1964 period and found no evidence for persistence. Kritzman (1983) reached the same 
conclusion after examining the 32 fixed-income managers retained by AT&T for at least 10 years. 
Dunn and Theisen (1983) found no evidence of persistence in 201 institutional portfolios from 1973 
to 1982. And Elton, Gruber, and Rentzler (1990) showed that performance did not persist for 51 
publicly offered commodity funds from 1980 to 1988.


---


### Page 568


Page 563
Several other diverse studies, however, have found that performance does persist. Grinblatt and 
Titman (1988) found evidence of persistence in 157 mutual funds over the period 1975 to 1984. 
Lehmann and Modest (1987) report similar results from looking at 130 mutual funds from 1968 to 
1982. In the United Kingdom, Brown and Draper (1992) demonstrated evidence for persistence 
using data on 550 pension managers from 1981 to 1990. Hendricks, Patel, and Zeckhauser (1993) 
documented persistence of performance in 165 equity mutual funds from 1974 to 1988. Goetzmann 
and Ibbotson (1994) showed evidence for persistence using 728 mutual funds over the period 1976 
to 1988. Bauman and Miller (1994) showed evidence for persistence using as many as 608 
institutional portfolios from December 1972 through September 1991, but only when using periods 
corresponding to complete market cycles.
Kahn and Rudd (1995), after accounting for style effects, fees and expenses, and database errors, 
found no evidence for persistence of performance for 300 equity funds from October 1988 through 
September 1994. They did, however, find evidence for persistence of performance for 195 bond 
funds from October 1991 through September 1994. Unfortunately, this persistence was insufficient 
to support an outperforming investment strategy: It could not overcome the average 
underperformance of bond mutual funds (especially after fees and costs). Kahn and Rudd (1997a, b, 
c) find similar results when they extend the analysis to additional time periods and to institutional 
portfolios as well as mutual funds, and when they focus on managers rather than just on mutual 
funds.
Now remember that Brown, Goetzmann, Ibbotson, and Ross (1992) showed that survivorship bias 
could significantly affect performance studies. In particular, they demonstrated that survivorship 
bias would generate the appearance of significant persistence. This calls into question several of the 
studies that found evidence for persistence. The recent work on persistence has carefully utilized 
databases free of survivorship bias.
Looking at all U.S. equity mutual funds from 1971 through 1991, Malkiel (1995) found evidence for 
persistence of performance in the 1970s, but it disappeared in the 1980s. However, Gruber (1996), 
also looking at 270 U.S. equity mutual funds from 1985 to 1994, found persistence so strong, that, 
he argued, it explained the growth in active mutual funds. Malkiel measured performance


---


### Page 569


Page 564
using simple CAPM regressions, while Gruber also controlled for size, book-to-price, and bond 
market effects. Finally, Carhart (1997) looked at 1892 diversified equity mutual funds from 1962 
through 1993, controlling for size, book-to-price, and 1-year momentum effects. The only 
significant persistence he found was for the strong underperformance of the very worst mutual 
funds.
In summary, the past 30 years of research on persistence of performance has generated at best a 
mixed record. These data have been tortured mercilessly, analyzed in as many different ways as 
there have been studies, and with widely varying results even among recent studies produced by 
highly respected academics. In spite of mutual fund advertising (though consistent with proxy 
statements), the connection between historical performance and future performance is weak. The 
probability that a winner will repeat is not 90 percent but perhaps 55 percent, with academics 
strongly arguing about the statistical significance of such a result.2
What does the limited connection between historical performance and future performance tell us 
about the possibility of successful active management?
A Simple Model of the Manager Population
The mixed results on persistence of performance clearly show that a simple strategy of picking last 
year's winners (above-median performers) will not have much (if any) more than a 50 percent 
chance of being a winner (outperforming the median) this year. These results do not definitively say 
that active management is impossible. At the same time, they are hardly a dramatic vindication of 
active management. These results do say that it isn't easy to find successful active managers from 
their track records alone.
We can better understand this with a simple model. Instead of investments, we will consider flipping 
coins. Imagine that the
2Goetzmann and Ibbotson (1994), in one of the more optimistic studies, find, for example, that the probability 
of equity mutual fund winners' (defined by above-median alphas) repeating, on average, year by year from 
1978 through 1987, is 62 percent. The more pessimistic studies find numbers like 50 percent. That roughly 
defines the range of the academic argument.


---


### Page 570


Page 565
population consists of two different groups. There are the "persistent winners," who consistently call 
heads or tails correctly. They exhibit the ultimate in skill: They are correct every time.
Then there are the "coin tossers," who call heads or tails at random. Since we want to rig this to be a 
zero-sum game, we will set up the coin tossers to be correct slightly less than half the time. Then, 
when we average over the entire population, with persistent winners always correct and coin tossers 
correct slightly less than half the time, the calls are correct exactly half the time. We will assume 
that most of the population are coin tossers.
We will analyze our overall population using a 2 X 2 contingency table, Fig. 20.1. Every member of 
the population will call a coin toss. Half will be correct (winners), and half will be incorrect (losers). 
The experiment will then be repeated. Each member of the population will be either a winner or a 
loser on the first toss and either a winner or a loser on the second toss. A contingency table records 
how many members of the population are winners on both tosses, losers on both tosses, winners 
then losers, and losers then winners.
The persistent winners will show persistence. They will all appear in the two-time winner category. 
The coin tossers will show up in all four categories. Some, through sheer luck, will be consistent 
winners. The rest will be scattered through the other categories.
If there are no persistent winners—if coin tossers constitute the entire population—then we expect 
one-quarter of the population in each category. The probability of a winner repeating is exactly 50
Figure 20.1 
Contingency tables.


---


### Page 571


Page 566
percent. In this simple model, any deviations from this random pattern result from the presence of 
the persistent winners. In fact, we can relate the probability p of winners repeating to the fraction δ 
of consistent winners in the population:
If the probability of winners repeating is just 50 percent, then δ = 0. If the probability of winners 
repeating is 100 percent, then δ = 50 percent. The consistent winners represent half the entire 
population. Note that in a zero-sum game, the winners can't make up more than 50 percent of the 
population.
Now, if the probability of winners repeating is 60 percent, which corresponds to about the highest 
claimed probability of investment winners' repeating in any academic study, then Eq. (20.1) implies 
that about 17 percent of the population is skilled.
Note that this model implies a way to identify the persistent winners: Look over more periods. This 
effectively divides the population into more groups. If we look at the players who call coin tosses 
correctly three periods in a row, these will consist of all the persistent winners, plus the few coin 
tossers who were lucky three times in a row. Even fewer coin tossers will be lucky four times in a 
row. In this way, we can filter out the persistent winners.
But this simple model does not perfectly capture the investment world. Even skilled managers do 
not outperform every day, or every month, or even every year. We can never escape some element 
of noise in historical performance numbers, and the shorter the horizon, the more that noise is a 
significant factor. Hence, Eq. (20.1) will underestimate the fraction of skillful managers.
Put another way, we would be happy to be able to identify managers with information ratios of 0.5. 
But given the levels of noise in performance numbers, in any 1-year period, such a manager has 
only a 69 percent chance of ouperforming (assuming normal distributions). The probability of 
outperforming in two consecutive periods is 48 percent. If we look at 5-year periods, then these 
probabilities change to 87 percent and 75 percent, respectively. Even if we choose two consecutive 
5-year periods and build a contingency table as described before, only 75 percent of our target pool 
of managers (those with information ratios above 0.5) will


---


### Page 572


Page 567
show up as repeat winners. And that is if their skill (and their career with one firm) has lasted 10 
years.
This simple model of the population of active managers leads to two conclusions. First, the limited 
evidence for persistence of performance does not rule out the possibility of successful active 
management. It simply puts a rough bound on the fraction of skillful managers in the population. 
Second, the levels of noise in performance numbers imply that historical performance will never 
precisely identify skillful managers.
What Does Predict Performance?
After 30 years, the academics have beaten to death this question of persistence of performance. It's 
time to frame the question more broadly: What, if anything, does predict performance?
Here, we can rely on some results given in this book. The fundamental law of active management 
shows that high information ratios depend on skill and breadth. We might expect to see high 
information ratios for managers who hold more positions or exhibit more turnover, both of which 
are proxies for breadth. Of course, higher turnover also implies higher transactions costs, so the 
connection may not be very strong.
Stewart (1998) examined 1527 U.S. institutional equity products from January 1978 through March 
1996, and found just such a connection. Rather than looking at information ratios, he grouped all 
managers into quintiles based on their fraction of monthly positive active returns, a measure he 
labeled "consistency of performance." This fraction should be a monotonic function of the 
information ratio,3 and so this should correspond to information ratio quintiles as well. He found 
that the number of holdings, and the turnover, increases as we move to the more consistent (higher 
information ratio) quintiles. Furthermore, Stewart found that the more consistent performers in one 
period had higher active returns in the next period.
3 Assuming normally distributed active returns, this fraction is just


---


### Page 573


Page 568
Kahn and Rudd (1997c) have presented similar results for 367 institutional equity portfolios from 
October 1993 through December 1996. After controlling for style effects, they regressed 
information ratios in the second half of the period cross-sectionally against a set of possible 
explanatory variables from the first half of the period. While the information ratio in the first half of 
the period does not show up as statistically significant, the number of assets in the portfolio does 
have statistically significant forecasting power, consistent with Stewart's results.
These results may be the clearest empirical evidence of the importance of the precepts in this book.4
Why Believe in Successful Active Management?
We have reviewed the empirical results. The references include a long list of learned studies. We 
have compiled some evidence that successful active managers exist. We have encouraging evidence 
that the approaches outlined in this book help. But the evidence for successful active management 
isn't overwhelming, and besides, all this evidence looks backward. Why should we believe in active 
management, looking forward?
First, we know that markets aren't perfectly efficient, because market participants are human. 
Humans are not perfectly rational. Perhaps more surprising, humans are irrational in consistent and 
specific ways. The field of behavioral finance has developed to understand these persistent human 
behaviors and their impact on financial markets.5
Behavioral finance has claimed that markets are not efficient because of human behavior. Until 
evolution cooperates, market inefficiencies will remain available for successful active management.
4 In a more flattering vein, Chevalier and Ellison (1997) have uncovered a positive connection between active 
returns and manager SAT scores. We naturally believe that the followers of the ideas in this book represent the 
high end of the active manager intelligence spectrum.
5 One seminal article is Tversky and Kahneman (1974). See also DeBondt and Thaler (1985) and Kahneman and 
Riepke (1998).


---


### Page 574


Page 569
Second, and perhaps paradoxically, only active management can make markets efficient. Since the 
development of the CAPM and efficient markets theory in the 1960s, passive management has 
grown in popularity. According to Ambachtsheer (1994), in the 1970s, 100 percent of institutional 
assets were actively managed. That fraction had dropped significantly. As he points out, if only 10 
percent or 1 percent of assets were actively managed, then elementary investment research, not even 
efficiently implemented, should pay off. As the fraction of active management increases, some 
inefficiencies will remain, but they will be exploitable only with an efficient implementation. 
Moreover, that exploitation will be exactly at the expense of managers with inefficient processes 
and/or inferior information.
Ambachtsheer argues that successful active management must be possible, because efficient 
markets require it. Furthermore, successful active management will require both superior 
information and efficient implementation.
Looking forward, there are compelling arguments for believing in successful active management. 
But, not surprisingly, successful active management will require cleverness and hard work: to 
uncover information superior to that of other managers, and to implement more efficiently than 
other managers.
References
Ambachtsheer, Keith P. "Active Management That Adds Value: Reality or Illusion." Journal of 
Portfolio Management, vol. 21, no. 1, 1994, pp. 89–92.
Bauman, W. Scott, and Robert E. Miller. "Can Managed Portfolio Performance Be Predicted?" 
Journal of Portfolio Management, vol. 20, no. 4, 1994, pp. 31–40.
Bello, Zakri, and Vahan Janjigian. "A Reexamination of the Market-Timing and Security-Selection 
Performance of Mutual Funds." Financial Analysts Journal, vol. 53, no. 5, 1997, pp. 24–30.
Bogle, John C. "The Implications of Style Analysis for Mutual Fund Performance Evaluation." 
Journal of Portfolio Management, vol. 24, no. 4, 1998, pp. 34–42.
Brown, G., and P. Draper. "Consistency of U.K. Pension Fund Investment Performance." University 
of Strath Clyde Department of Accounting and Finance, Working Paper, 1992.
Brown, Stephen J., William N. Goetzmann, Roger G. Ibbotson, and Stephen A. Ross. "Survivorship 
Bias in Performance Studies." Review of Financial Studies, vol. 5, no. 4, 1992, pp. 553–580.


---


### Page 575


Page 570
Brown, Stephen J., William N. Goetzmann, and Alok Kumar. "The Dow Theory: William Peter 
Hamilton's Track Record Reconsidered." Journal of Finance, vol. 53, no. 4, 1998, pp. 1311–1333.
Brown, Stephen J., William N. Goetzmann, and Stephen A. Ross. "Survival." Journal of Finance, 
vol. 50, no. 3, 1995, pp. 853–873.
Carhart, Mark M. "On Persistence in Mutual Fund Performance." Journal of Finance, vol. 52, no. 1, 
1997, pp. 57–82.
Chevalier, Judith, and Glenn Ellison. "Do Mutual Fund Managers Matter? An Empirical 
Investigation of the Performance, Career Concerns, and Behavior of Fund Managers." National 
Bureau of Economic Research Preprint, 1997.
Christopherson, Jon A., and Frank C. Sabin. "How Effective Is the Effective Mix?" Journal of 
Investment Consulting, vol. 1, no. 1, 1998, pp. 39–50.
Daniel, Kent, Mark Grinblatt, Sheridan Titman, and Russ Wermers. "Measuring Mutual Fund 
Performance with Characteristic-based Benchmarks." Journal of Finance, vol. 52, no. 3, 1997, pp. 
1035–1058.
DeBondt, W. F. M., and Richard Thaler. "Does the Stock Market Overreact?" Journal of Finance, 
vol. 40, no. 3, 1985, pp. 793–805.
Dunn, Patricia C., and Rolf D. Theisen. "How Consistently Do Active Managers Win?" Journal of 
Portfolio Management, vol. 9, no. 4, 1983, pp. 47–50.
Elton, E., Martin Gruber, and J. Rentzler. "The Performance of Publicly Offered Commodity 
Funds." Financial Analysts Journal, vol. 46, no. 4, 1990, pp. 23–30.
Ferson, Wayne E., and Rudi W. Schadt. "Measuring Fund Strategy and Performance in Changing 
Economic Conditions." Journal of Finance, vol. 51, no. 2, 1996, pp. 425–461.
Ferson, Wayne E., and Vincent A. Warther. "Evaluating Fund Performance in a Dynamic Market." 
Financial Analysts Journal, vol. 52, no. 6, 1996, pp. 20–28.
Goetzmann, William N., and Roger Ibbotson. "Do Winners Repeat?" Journal of Portfolio 
Management, vol. 20, no. 2, 1994, pp. 9–18.
Grinblatt, Mark, and Sheridan Titman. "The Evaluation of Mutual Fund Performance: An Analysis 
of Monthly Returns." Working Paper 13-86, John E. Anderson Graduate School of Management, 
University of California at Los Angeles, 1988.
Gruber, Martin J. "Another Puzzle: The Growth in Actively Managed Mutual Funds." Journal of 
Finance, vol. 51, no. 3, 1996, pp. 783–810.
Hendricks, Darryll, Jayendu Patel, and Richard Zeckhauser. "Hot Hands in Mutual Funds: ShortRun Persistence of Relative Performance, 1974–1988." Journal of Finance, vol. 48, no. 1, 1993, pp. 
93–130.
Ippolito, Richard A. "On Studies of Mutual Fund Performance 1962–1991." Financial Analysts 
Journal, vol. 49, no. 1, 1993, pp. 42–50.
Jensen, Michael C. "The Performance of Mutual Funds in the Period 1945–1964." Journal of 
Finance, vol. 23, no. 2, 1968, pp. 389–416.


---


### Page 576


Jones, Robert C. "Why Most Active Managers Underperform (and What You Can Do About It)." In 
Enhanced Index Strategies for the Multi-Manager Portfolio, edited by Brian Bruce (New York: 
Institutional Investor, 1998).
Kahn, Ronald N., and Andrew Rudd. "Does Historical Performance Predict Future Performance?" 
Financial Analysts Journal, vol. 51, no. 6, 1995, pp. 43–52.


---


### Page 577


Page 571
———. "The Persistence of Equity Style Performance: Evidence from Mutual Fund Data." In The 
Handbook of Equity Style Management, 2d ed., edited by J. Daniel Coggin, Frank J. Fabozzi, and 
Robert D. Arnott (New Hope, Pa. Frank J. Fabozzi Associates, 1997a).
———. "The Persistence of Fixed Income Style Performance: Evidence from Mutual Fund Data." 
In Managing Fixed Income Portfolios, edited by Frank J. Fabozzi (New Hope, Pa: Frank J. Fabozzi 
Associates, 1997b), chap. 18.
———. "The Persistence of Institutional Portfolio Performance." BARRA International Research 
Seminar, Montreux, Switzerland, September 1997c.
Kahneman, Daniel, and Mark W. Riepke. "Aspects of Investor Psychology." Journal of Portfolio 
Management, vol. 24, no. 4, 1998, pp. 52–65.
Kritzman, M. "Can Bond Managers Perform Consistently?" Journal of Portfolio Management, vol. 
9, no. 4, 1983, pp. 54–56.
Lehmann, Bruce N., and David M. Modest. "Mutual Fund Performance Evaluation: A Comparison 
of Benchmarks and Benchmark Comparisons." Journal of Finance, vol. 42, no. 2, 1987, pp. 233–
265.
Malkiel, Burton G. "Returns from Investing in Equity Mutual Funds 1971 to 1991." Journal of 
Finance, vol. 50, no. 2, 1995, pp. 549–572.
Marcus, Alan J. "The Magellan Fund and Market Efficiency." Journal of Portfolio Management, 
vol 17, no. 1, 1990, pp 85–88.
Sharpe, William F. "Mutual Fund Performance." Journal of Business, vol. 39, no. 1, Part II, 1966, 
pp. 119–138.
Stewart, Scott D. "Is Consistency of Performance a Good Measure of Manager Skill?" Journal of 
Portfolio Management, vol. 24, no. 3, 1998, pp. 22–32.
Treynor, Jack L. "How to Rate Management of Investment Funds." Harvard Business Review, vol. 
43, January–February 1965, pp. 63–75.
Tversky, Amos, and Daniel Kahneman. "Judgment under Uncertainty: Heuristics and Biases." 
Science, vol. 185, 1974, pp. 1124–1131.


---


### Page 578


Page 573
Chapter 21— 
Open Questions
Introduction
For 20 chapters, we have aspired to be magicians. We have attempted to present a comprehensive 
and seamless theory: covering every aspect of active portfolio management, and smoothly flowing 
from foundations to expected returns and valuation to information processing to implementation.
We must now confess—if you don't already know—that the theory isn't seamless. We have swept 
aside, ignored, or simply assumed away the poorly understood aspects of portfolio management—
the open questions—that require additional work.
Successful active management efficiently utilizes superior information. The search for the next 
source of superior information is an inherent open question all the time for every active manager, 
but it isn't an open question for active management. We will not deal here with any specifically 
focused valuation questions (e.g., what combination of accounting variables correlates most closely 
with future returns?).
Instead, we wish to highlight open questions for the process of active management. Our goal is to 
emphasize that we haven't completed the theory of active portfolio management. It is still fertile 
ground for research.1
1In 1900, the mathematician David Hilbert presented a now-famous list of important open questions as a 
challenge and a research plan for the mathematics community for the twentieth century. This book is appearing 
at the beginning of the twentyfirst century, but we cannot claim ambitions quite as lofty.


---


### Page 579


Page 574
These open questions will cover the general topics of
• Dynamics
• Transactions costs
• Liabilities, asset allocation, and risk over time
• Nonlinearities
• After-tax investing
• Behavioral finance
Dynamics
Active portfolio management is a dynamic problem. We manage portfolios over time. We confront 
a flow of information (and noise). Risk changes as volatilities change and as our exposures change 
over time. (Benchmark timing is just the most obvious example.) Transactions costs change over 
time and with our speed of trading.
Active portfolio management confronts these changing parameters simultaneously. With a proper 
frame, managers should make investment decisions now, accounting for these dynamics and 
interactions now and in the future.
This full dynamic problem is both complicated and important. One simple open question is, when 
should we trade? This simple question demands more than just a static analysis. If transactions costs 
were zero, the solution would be obvious: Trade every time the alpha changes. But transactions 
costs aren't zero. When should we trade, given the dynamics of returns, risks, and costs over time?
Another open question concerns dynamic strategies and risk. Even if single-period returns are 
normal or lognormal, dynamic strategies can generate skewed and optionlike return patterns. 
Portfolio insurance is one example. So another open question is, how should we decide on an 
appropriate dynamic strategy, and what are its implications for our return distribution?
Transactions Costs
As we stated in Chap. 16, there is no CAPM or Black-Scholes model of transactions costs. A 
complete and practical model of transactions costs would cover three important aspects: tightness, 
depth, and resiliency. Tightness measures the bid/ask spread. Depth measures


---


### Page 580


Page 575
market impact. Resiliency measures how depth or market impact evolves over time. An investor 
buys a large block and pushes up the price. How long will it take for the price to sink back to 
equilibrium? What factors influence resiliency? One open question is, how do we model tightness, 
depth, and resiliency? A second open question is, how do transactions costs in one stock influence 
transactions costs in other stocks?
Liabilities, Asset Allocation, and Risk Over Time
Investors choose assets based on their future liabilities. This is most obvious in strategic asset 
allocation. Accurate liability modeling is one open question. Liabilities aren't certain. They are often 
contingent on other factors (e.g., inflation, dead or alive). Another question concerns managing 
assets against fixed-horizon liabilities. How should our asset allocation change as we approach 
retirement, and move past it?
Nonlinearities
Nonlinearities arise in at least two contexts in finance. We empirically observe nonlinear responses 
to certain exposures, particularly size. Relative behavior along the size dimension is still poorly 
understood. How do small stocks behave relative to midcap, large, and megacap stocks? Size is a 
pervasive issue in portfolio management. It enters into benchmarks and market averages. It is linked 
to the typical long-only constraint. The open question is, How do we adequately capture the 
nonlinear (and multidimensional) behavior of size?
Quite separately, researchers have investigated the applicability of nonlinear dynamic models like 
chaos or catastrophe theory to finance. An open question: Do nonlinear models offer any predictive 
power for understanding financial market behavior?
After-Tax Investing
Managing after-tax returns is extremely complicated. It combines all the intricacies of dynamic 
portfolio management with wash sale


---

