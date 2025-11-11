# Grinold-Kahn Active Portfolio Management

## Pages 1-20


### Page 1


Page iii
Active Portfolio Management
A Quantitative Approach for Providing Superior Returns and Controlling Risk
Richard C. Grinold 
Ronald N. Kahn
SECOND EDITION


---


### Page 2


Page vii
CONTENTS
Preface
xi
Acknowledgments
xv
Chapter 1 
Introduction
1
Part One 
Foundations
 
Chapter 2 
Consensus Expected Returns: The Capital Asset Pricing Model
11
Chapter 3
Risk
41
Chapter 4 
Exceptional Return, Benchmarks, and Value Added
87
Chapter 5 
Residual Risk and Return: The Information Ratio
109
Chapter 6 
The Fundamental Law of Active Management
147
Part Two 
Expected Returns and Valuation
 
Chapter 7 
Expected Returns and the Arbitrage Pricing Theory
173


---


### Page 3


Page viii
Chapter 8 
Valuation in Theory
199
Chapter 9 
Valuation in Practice
225
Part Three 
Information Processing
 
Chapter 10 
Forecasting Basics
261
Chapter 11 
Advanced Forecasting
295
Chapter 12 
Information Analysis
315
Chapter 13 
The Information Horizon
347
Part Four 
Implementation
 
Chapter 14 
Portfolio Construction
377
Chapter 15 
Long/Short Investing
419
Chapter 16 
Transactions Costs, Turnover, and Trading
445
Chapter 17 
Performance Analysis
477


---


### Page 4


Page ix
Chapter 18 
Asset Allocation
517
Chapter 19 
Benchmark Timing
541
Chapter 20 
The Historical Record for Active Management
559
Chapter 21 
Open Questions
573
Chapter 22
Summary
577
Appendix A 
Standard Notation
581
Appendix B
Glossary
583
Appendix C 
Return and Statistics Basics
587
Index
591


---


### Page 5


Page xi
PREFACE
Why a second edition? Why take time from busy lives? Why devote the energy to improving an 
existing text rather than writing an entirely new one? Why toy with success?
The short answer is: our readers. We have been extremely gratified by Active Portfolio 
Management's reception in the investment community. The book seems to be on the shelf of every 
practicing or aspiring quantitatively oriented investment manager, and the shelves of many 
fundamental portfolio managers as well.
But while our readers have clearly valued the book, they have also challenged us to improve it. 
Cover more topics of relevance to today. Add empirical evidence where appropriate. Clarify some 
discussions.
The long answer is that we have tried to improve Active Portfolio Management along exactly these 
dimensions.
First, we have added significant amounts of new material in the second edition. New chapters cover 
Advanced Forecasting (Chap. 11), The Information Horizon (Chap. 13), Long/Short Investing 
(Chap. 15), Asset Allocation (Chap. 18), The Historical Record for Active Management (Chap. 20), 
and Open Questions (Chap. 21).
Some previously existing chapters also cover new material. This includes a more detailed discussion 
of risk (Chap. 3), dispersion (Chap. 14), market impact (Chap. 16), and academic proposals for 
performance analysis (Chap. 17).
Second, we receive exhortations to add more empirical evidence, where appropriate. At the most 
general level: how do we know this entire methodology works? Chapter 20, on The Historical 
Record for Active Management, provides some answers. We have also added empirical evidence 
about the accuracy of risk models, in Chap. 3.
At the more detailed level, readers have wanted more information on typical numbers for 
information ratios and active risk. Chapter 5 now includes empirical distributions of these statistics. 
Chapter 15 provides similar empirical results for long/short portfolios. Chapter 3 includes empirical 
distributions of asset level risk statistics.


---


### Page 6


Page xii
Third, we have tried to clarify certain discussions. We received feedback on how clearly we had 
conveyed certain ideas through at least two channels. First, we presented a talk summarizing the 
book at several investment management conferences.1 "Seven Quantitative Insights into Active 
Management" presented the key ideas as:
1. Active Management is Forecasting: consensus views lead to the benchmark.
2. The Information Ratio (IR) is the Key to Value-Added.
3. The Fundamental Law of Active Management: 
4. Alphas must control for volatility, skill, and expectations: Alpha = Volatility · IC · Score.
5. Why Datamining is Easy, and guidelines to avoid it.
6. Implementation should subtract as little value as possible.
7. Distinguishing skill from luck is difficult.
This talk provided many opportunities to gauge understanding and confusion over these basic ideas.
We also presented a training course version of the book, called "How to Research Active 
Strategies." Over 500 investment professionals from New York to London to Hong Kong and 
Tokyo have participated. This course, which involved not only lectures, but problem sets and 
extensive discussions, helped to identify some remaining confusions with the material. For example, 
how does the forecasting methodology in the book, which involves information about returns over 
time, apply to the standard case of information about many assets at one time? We have devoted 
Chap. 11, Advanced Forecasting, to that important discussion.
Finally, we have fixed some typographical errors, and added more problems and exercises to each 
chapter. We even added a new type of problem—applications exercises. These use commercially 
available analytics to demonstrate many of the ideas in the
1The BARRA Newsletter presented a serialized version of this talk during 1997 and 1998.


---


### Page 7


Page xiii
book. These should help make some of the more technical results accessible to less mathematical 
readers.
Beyond these many reader-inspired improvements, we may also bring a different perspective to the 
second edition of Active Portfolio Management. Both authors now earn their livelihoods as active 
managers.
To readers of the first edition of Active Portfolio Management, we hope this second edition answers 
your challenges. To new readers, we hope you continue to find the book important, useful, 
challenging, and comprehensive.
RICHARD C. GRINOLD
RONALD N. KAHN


---


### Page 8


Page xv
ACKNOWLEDGMENTS
Many thanks to Andrew Rudd for his encouragement of this project while the authors were 
employed at BARRA, and to Blake Grossman for his continued enthusiasm and support of this 
effort at Barclays Global Investors.
Any close reader will realize that we have relied heavily on the path breaking work of Barr 
Rosenberg. Barr was the pioneer in applying economics, econometrics and operations research to 
solve practical investment problems. To a lesser, but not less crucial extent, we are indebted to the 
original and practical work of Bill Sharpe and Fischer Black. Their ideas are the foundation of much 
of our analysis.
Many people helped shape the final form of this book. Internally at BARRA and Barclays Global 
Investors, we benefited from conversations with and feedback from Andrew Rudd, Blake Grossman, 
Peter Algert, Stan Beckers, Oliver Buckley, Vinod Chandrashekaran, Naozer Dadachanji, Arjun 
DiVecha, Mark Engerman, Mark Ferrari, John Freeman, Ken Hui, Ken Kroner, Uzi Levin, Richard 
Meese, Peter Muller, George Patterson, Scott Scheffler, Dan Stefek, Nicolo Torre, Marco 
Vangelisti, Barton Waring, and Chris Woods. Some chapters appeared in preliminary form at 
BARRA seminars and as journal articles, and we benefited from broader feedback from the 
quantitative investment community.
At the more detailed level, several members of the research groups at BARRA and Barclays Global 
Investors helped generate the examples in the book, especially Chip Castille, Mikhail Dvorkin, Cliff 
Gong, Josh Rosenberg, Mike Shing, Jennifer Soller, and Ko Ushigusa.
BARRA and Barclays Global Investors have also been supportive throughout.
Finally, we must thank Leslie Henrichsen, Amber Mayes, Carolyn Norton, and Mary Wang for their 
administrative help over many years.


---


### Page 9


Page 1
Chapter 1— 
Introduction
The art of investing is evolving into the science of investing. This evolution has been happening 
slowly and will continue for some time. The direction is clear; the pace varies. As new generations 
of increasingly scientific investment managers come to the task, they will rely more on analysis, 
process, and structure than on intuition, advice, and whim. This does not mean that heroic personal 
investment insights are a thing of the past. It means that managers will increasingly capture and 
apply those insights in a systematic fashion.
We hope this book will go part of the way toward providing the analytical underpinnings for the 
new class of active investment managers. We are addressing a fresh topic. Quantitative active 
management—applying rigorous analysis and a rigorous process to try to beat the market—is a 
cousin of the modern study of financial economics. Financial economics is conducted with much 
vigor at leading universities, safe from any need to deliver investment returns. Indeed, from the 
perspective of the financial economist, active portfolio management appears to be a mundane 
consideration, if not an entirely dubious proposition. Modern financial economics, with its theories 
of market efficiency, inspired the move over the past decade away from active management (trying 
to beat the market) to passive management (trying to match the market).
This academic view of active management is not monolithic, since the academic cult of market 
efficiency has split. One group now enthusiastically investigates possible market inefficiencies.


---


### Page 10


Page 2
Still, a hard core remains dedicated to the notion of efficient markets, although they have become 
more and more subtle in their defense of the market.1
Thus we can look to the academy for structure and insight, but not for solutions. We will take a 
pragmatic approach and develop a systematic approach to active management, assuming that this is 
a worthwhile goal. Worthwhile, but not easy. We remain aware of the great power of markets to 
keep participants in line. The first necessary ingredient for success in active management is a 
recognition of the challenge. On this issue, financial economists and quantitative researchers fall 
into three categories: those who think successful active management is impossible, those who think 
it is easy, and those who think it is difficult. The first group, however brilliant, is not up to the task. 
You cannot reach your destination if you don't believe it exists. The second group, those who don't 
know what they don't know, is actually dangerous. The third group has some perspective and 
humility. We aspire to belong to that third group, so we will work from that perspective. We will 
assume that the burden of proof rests on us to demonstrate why a particular strategy will succeed.
We will also try to remember that this is an economic investigation. We are dealing with spotty data. 
We should expect our models to point us in the correct direction, but not with laserlike accuracy. 
This reminds us of a paper called ''Estimation for Dirty Data and Flawed Models."2 We must accept 
this nonstationary world in which we can never repeat an experiment. We must accept that investing 
with real money is harder than paper investing, since we actually affect the transaction prices.
Perspective
We have written this book on two levels. We have aimed the material in the chapters at the MBA 
who has had a course in investments
1A leading academic refined this technique to the sublime recently when he told an extremely successful 
investor that his success stemmed not from defects in the market but from the practitioner's sheer brilliance. 
That brilliance would have been as well rewarded if he had chosen some other endeavor, such as designing 
microchips, recombining DNA, or writing epic poems. Who could argue with such a premise?
2Krasker, Kuh, and Welch (1983).


---


### Page 11


Page 3
or the practitioner with a year of experience. The technical appendices at the end of each chapter use 
mathematics to cover that chapter's insights in more detail. These are for the more technically 
inclined, and could even serve as a gateway to the subject for the mathematician, physicist, or 
engineer retraining for a career in investments. Beyond its use in teaching the subject to those 
beginning their careers, we hope the comprehensiveness of the book also makes it a valuable 
reference for veteran investment professionals.
We have written this book from the perspective of the active manager of institutional assets: 
defined-benefit plans, defined-contribution plans, endowments, foundations, or mutual funds. Plan 
sponsors, consultants, broker-dealers, traders, and providers of data and analytics should also find 
much of interest in the book. Our examples mainly focus on equities, but the analysis applies as well 
to bonds, currencies, and other asset classes.
Our goal is to provide a structured approach—a process—for active investment management. The 
process includes researching ideas (quantitative or not), forecasting exceptional returns, constructing 
and implementing portfolios, and observing and refining their performance. Beyond describing this 
process in considerable depth, we also hope to provide a set of strategic concepts and rules of thumb 
which broadly guide this process. These concepts and rules contain the intuition behind the process.
As for background, the book borrows from several academic areas. First among these is modern 
financial economics, which provides the portfolio analysis model. Sharpe and Alexander's book 
Investments is an excellent introduction to the modern theory of investments. Modern Portfolio 
Theory, by Rudd and Clasing, describes the concepts of modern financial economics. The appendix 
of Richard Roll's 1977 paper "A Critique of the Asset Pricing Theory's Tests" provides an excellent 
introduction to portfolio analysis. We also borrow ideas from statistics, regression, and 
optimization.
We like to believe that there are no books covering the same territory as this.
Strategic Overview
Quantitative active management is the poor relation of modern portfolio theory. It has the power and 
structure of modern portfolio theory without the legitimacy. Modern portfolio theory brought


---


### Page 12


Page 4
economics, quantitative methods, and the scientific perspective to the study of investments. 
Economics, with its powerful emphasis on equilibrium and efficiency, has little to say about 
successful active management. It is almost a premise of the theory that successful active 
management is not possible. Yet we will borrow some of the quantitative tools that economists 
brought to the investigation of investments for our attack on the difficult problem of active 
management.
We will add something, too: separating the risk forecasting problem from the return forecasting 
problem. Here professionals are far ahead of academics. Professional services now provide standard 
and unbiased3 estimates of investment risk. BARRA pioneered these services and has continued to 
set the standard in terms of innovation and quality in the United States and worldwide. We will 
review the fundamentals of risk forecasting, and rely heavily on the availability of portfolio risk 
forecasts.
The modern portfolio theory taught in most MBA programs looks at total risk and total return. The 
institutional investor in the United States and to an increasing extent worldwide cares about active 
risk and active return. For that reason, we will concentrate on the more general problem of 
managing relative to a benchmark. This focus on active management arises for several reasons:
• Clients can clump the large number of investment advisers into recognizable categories. With the 
advisers thus pigeonholed, the client (or consultant) can restrict searches and peer comparisons to 
pigeons in the same hole.
• The benchmark acts as a set of instructions from the fund sponsor, as principal, to the investment 
manager, as agent. The benchmark defines the manager's investment neighborhood. Moves away 
from the benchmark carry substantial investment and business risk.
• Benchmarks allow the trustee or sponsor to manage the aggregate portfolio without complete 
knowledge of the
3Risk forecasts from BARRA or other third-party vendors are unbiased in that the process used to derive them 
is independent from that used to forecast returns.


---


### Page 13


Page 5
holdings of each manager. The sponsor can manage a mix of benchmarks, keeping the "big picture."
In fact, analyzing investments relative to a benchmark is more general than the standard total risk 
and return framework. By setting the benchmark to cash, we can recover the traditional framework.
In line with this relative risk and return perspective, we will move from the economic and textbook 
notion of the market to the more operational notion of a benchmark. Much of the apparatus of 
portfolio analysis is still relevant. In particular, we retain the ability to determine the expected 
returns that make the benchmark portfolio (or any other portfolio) efficient. This extremely valuable 
insight links the notion of a mean/variance efficient portfolio to a list of expected returns on the 
assets.
Throughout the book, we will relate portfolios to return forecasts or asset characteristics. The 
technical appendixes will show explicitly how every asset characteristic corresponds to a particular 
portfolio. This perspective provides a novel way to bring heterogeneous characteristics to a common 
ground (portfolios) and use portfolio theory to study them.
Our relative perspective will focus us on the residual component of return: the return that is 
uncorrelated with the benchmark return. The information ratio is the ratio of the expected annual 
residual return to the annual volatility of the residual return. The information ratio defines the 
opportunities available to the active manager. The larger the information ratio, the greater the 
possibility for active management.
Choosing investment opportunities depends on preferences. In active management, the preferences 
point toward high residual return and low residual risk. We capture this in a mean/variance style 
through residual return minus a (quadratic) penalty on residual risk (a linear penalty on residual 
variance). We interpret this as "risk-adjusted expected return" or "value-added." We can describe 
the preferences in terms of indifference curves. We are indifferent between combinations of 
expected residual return and residual risk which achieve the same value-added. Each indifference 
curve will include a "certainty equivalent'' residual return with zero residual risk.


---


### Page 14


Page 6
When our preferences confront our opportunities, we make investment choices. In active 
management, the highest value-added achievable is proportional to the square of the information 
ratio.
The information ratio measures the active management opportunities, and the square of the 
information ratio indicates our ability to add value. Larger information ratios are better than smaller. 
Where do you find large information ratios? What are the sources of investment opportunity? 
According to the fundamental law of active management, there are two. The first is our ability to 
forecast each asset's residual return. We measure this forecasting ability by the information 
coefficient, the correlation between the forecasts and the eventual returns. The information 
coefficient is a measure of our level of skill.
The second element leading to a larger information ratio is breadth, the number of times per year 
that we can use our skill. If our skill level is the same, then it is arguably better to be able to forecast 
the returns on 1000 stocks than on 100 stocks. The fundamental law tells us that our information 
ratio grows in proportion to our skill and in proportion to the square root of the breadth: 
. This concept is valuable for the insight it provides, as well as the explicit 
help it can give in designing a research strategy.
One outgrowth of the fundamental law is our lack of enthusiasm for benchmark timing strategies. 
Betting on the market's direction once every quarter does not provide much breadth, even if we have 
skill.
Return, risk, benchmarks, preferences, and information ratios are the foundations of active portfolio 
management. But the practice of active management requires something more: expected return 
forecasts different from the consensus.
What models of expected returns have proven successful in active management? The science of 
asset valuation proceeded rapidly in the 1970s, with those new ideas implemented in the 1980s. 
Unfortunately, these insights are mainly the outgrowth of option theory and are useful for the 
valuation of dependent assets such as options and futures. They are not very helpful in the valuation 
of underlying assets such as equities. However, the structure of the options-based theory does point 
in a direction and suggest a form.


---


### Page 15


Page 7
The traditional methods of asset valuation and return forecasting are more ad hoc. Foremost among 
these is the dividend discount model, which brings the ideas of net present value to bear on the 
valuation problem. The dividend discount model has one unambiguous benefit. If used effectively, it 
will force a structure on the investment process. There is, of course, no guarantee of success. The 
outputs of the dividend discount model will be only as good as the inputs.
There are other structured approaches to valuation and return forecasting. One is to identify the 
characteristics of assets that have performed well, in order to find the assets that will perform well in 
the future. Another approach is to use comparative valuation to identify assets with different market 
prices, but with similar exposures to factors priced by the market. These imply arbitrage 
opportunities. Yet another approach is to attempt to forecast returns to the factors priced by the 
market.
Active management is forecasting. Without forecasts, managers would invest passively and choose 
the benchmark. In the context of this book, forecasting takes raw signals of asset returns and turns 
them into refined forecasts. This information processing is a critical step in the active management 
process. The basic insight is the rule of thumb Alpha = volatility · IC · score, which allows us to 
relate a standardized (zero mean and unit standard deviation) score to a forecast of residual return 
(an alpha). The volatility in question is the residual volatility, and the IC is the information 
coefficient—the correlation between the scores and the returns. Information processing takes the 
raw signal as input, converts it to a score, then multiplies it by volatility to generate an alpha.
This forecasting rule of thumb will at least tame the refined forecasts so that they are reasonable 
inputs into a portfolio selection procedure. If the forecasts contain no information, IC = 0, the rule of 
thumb will convert the informationless scores to residual return forecasts of zero, and the manager 
will invest in the benchmark. The rule of thumb converts "garbage in" to zeros.
Information analysis evaluates the ability of any signal to forecast returns. It determines the 
appropriate information coefficient to use in forecasting, quantifying the information content of the 
signal.
There is many a slip between cup and lip. Even those armed with the best forecasts of return can let 
the prize escape through


---


### Page 16


Page 8
inconsistent and sloppy portfolio construction and excessive trading costs. Effective portfolio 
construction ensures that the portfolio effectively represents the forecasts, with no unintended risks. 
Effective trading achieves that portfolio at minimum cost. After all, the investor obtains returns net 
of trading costs.
The entire active management process—from information to forecasts to implementation—requires 
constant and consistent monitoring, as well as feedback on performance. We provide a guide to 
performance analysis techniques and the insights into the process that they can provide.
This book does not guarantee success in investment management. Investment products are driven by 
concepts and ideas. If those concepts are flawed, no amount of efficient implementation and 
analysis can help. If it is garbage in, then it's garbage out; we can only help to process the garbage 
more effectively. However, we can provide at least the hope that successful and worthy ideas will 
not be squandered in application. If you are willing to settle for that, read on.
References
Krasker, William S., Edwin Kuh, and William S. Welsch. "Estimation for Dirty Data and Flawed 
Models." In Handbook of Econometrics vol. 1, edited by Z. Griliches and M.D. Intriligator (NorthHolland, New York, 1983), pp. 651–698.
Roll, Richard. "A Critique of the Asset Pricing Theory's Tests." Journal of Financial Economics, 
March 1977, pp. 129–176.
Rudd, Andrew, and Henry K. Clasing, Jr. Modern Portfolio Theory, 2d ed. (Orinda, Calif.: Andrew 
Rudd, 1988).
Sharpe, William F., and Gordon J. Alexander, Investments (Englewood Cliffs, N.J.: Prentice-Hall, 
1990).


---


### Page 17


Page 9
PART ONE— 
FOUNDATIONS


---


### Page 18


Page 11
Chapter 2— 
Consensus Expected Returns: 
The Capital Asset Pricing Model
Introduction
Risk and expected return are the key players in the game of active management. We will introduce 
these players in this chapter and the next, which begin the "Foundations" section of the book.
This chapter contains our initial attempts to come to grips with expected returns. We will start with 
an exposition of the capital asset pricing model, or CAPM, as it is commonly called.
The chapter is an exposition of the CAPM, not a defense. We could hardly start a book on active 
management with a defense of a theory that makes active management look like a dubious 
enterprise. There is a double purpose for this exploration of CAPM. First, we should establish the 
humility principle from the start. It will not be easy to be a successful active manager. Second, it 
turns out that much of the analysis originally developed in support of the CAPM can be turned to 
the task of quantitative active management. Our use of the CAPM throughout this book will be 
independent of any current debate over the CAPM's validity. For discussions of these points, see 
Black (1993) and Grinold (1993).
One of the valuable by-products of the CAPM is a procedure for determining consensus expected 
returns. These consensus expected returns are valuable because they give us a standard of 
comparison. We know that our active management decisions will be driven by the difference 
between our expected returns and the consensus.


---


### Page 19


Page 12
The major points of this chapter are:
• The return of any stock can be separated into a systematic (market) component and a residual 
component. No theory is required to do this.
• The CAPM says that the residual component of return has an expected value of zero.
• The CAPM is easy to understand and relatively easy to implement.
• There is a powerful logic of market efficiency behind the CAPM.
• The CAPM thrusts the burden of proof onto the active manager. It suggests that passive 
management is a lower-risk alternative to active management.
• The CAPM provides a valuable source of consensus expectations. The active manager can 
succeed to the extent that his or her forecasts are superior to the CAPM consensus forecasts.
• The CAPM is about expected returns, not risk.
The remainder of this chapter outlines the arguments that lead to the conclusions listed above. The 
chapter contains a technical appendix deriving the CAPM and introducing some formal notions used 
in technical appendixes of later chapters.
The goal of this book is to help the investor produce forecasts of expected return that differ from the 
consensus. This chapter identifies the CAPM as a source of consensus expected returns.
The CAPM is not the only possible forecast of expected returns, but it is arguably the best. As a 
later section of this chapter demonstrates, the CAPM has withstood many rigorous and practical 
tests since its proposal. One alternative is to use historical average returns, i.e., the average return to 
the stock over some previous period. This is not a good idea, for two main reasons. First, the 
historical returns contain a large amount of sample error.1 Second,
1Given returns generated by an unvarying random process with known annual standard deviation σ, the 
standard error of the estimated annual return will be 
 where Y measures the number of years of data. 
This result is the same whether we observe daily, monthly, quarterly, or annual returns. Since typical 
volatilities are ~35 percent, standard errors are ~16 percent after 5 years of observations!


---


### Page 20


Page 13
the universe of stocks changes over time: New stocks become available, and old stocks expire or 
merge. The stocks themselves change over time: Earnings change, capital structure may change, and 
the volatility of the stock may change. Historical averages are a poor alternative to consensus 
forecasts.2
A second alternative for providing expected returns is the arbitrage pricing theory (APT). We will 
consider the APT in Chap. 7. We find that it is an interesting tool for the active manager, but not as 
a source of consensus expected returns.
The CAPM has a particularly important role to play when selecting portfolios according to 
mean/variance preferences. If we use CAPM forecasts of expected returns and build optimal 
mean/variance portfolios, those portfolios will consist simply of positions in the market and the riskfree asset (with proportions depending on risk tolerance). In other words, optimal mean/variance 
portfolios will differ from the market portfolio and cash if and only if the forecast excess returns 
differ from the CAPM consensus excess returns.
This is in fact what we mean by "consensus." The market portfolio is the consensus portfolio, and 
the CAPM leads to the expected returns which make the market mean/variance optimal.
Separation of Return
The CAPM relies on two constructs, first the idea of a market portfolio M, and second the notion of 
beta, β, which links any stock or portfolio to the market. In theory, the market portfolio includes all 
assets: U.K. stocks, Japanese bonds, Malaysian plantations, etc. In practice, the market portfolio is 
generally taken as some broad value-weighted index of traded domestic equities, such as the NYSE 
Composite in the United States, the FTA in the United Kingdom, or the TOPIX in Japan.
Let's consider any portfolio P with excess returns rP and the market portfolio M with excess returns 
rM. Recall that excess returns
2For an alternative view, see Grauer and Hakansson (1982).


---

