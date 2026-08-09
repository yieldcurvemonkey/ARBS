# CME MBO Suite — Primary-Source Reference Findings

**Date:** 2026-08-08
**Branch:** `feat/cme-mbo-analytics-suite`

The rules this engine has to encode, gathered from primary sources by a
seven-way parallel research sweep and then adversarially verified. Each finding
carries its confidence and its source. `inferred` means an agent reasoned it out
rather than read it, and those are kept separate on purpose.

What could not be established is listed under **Unresolved** for each topic. A
short findings list with an honest unresolved list is worth more here than a long
list of guesses — every one of these numbers ends up hard-coded somewhere.



## hftbacktest (github.com/nkaz001/hftbacktest) design — data model, queue models, latency models, L2-vs-L3 assumptions, and validation guidance, read from source for a self-built MDP 3.0 MBO fill simulator


### primary-source

**hftbacktest consumes BOTH L2 (Market-By-Price) and L3 (Market-By-Order) through ONE normalized 8-field event record; it does not have separate L2/L3 formats.**

Rust `Event` is `#[repr(C, align(64))]` with fields in this exact order: `ev: u64`, `exch_ts: i64`, `local_ts: i64`, `px: f64`, `qty: f64`, `order_id: u64`, `ival: i64`, `fval: f64`. Python side is the identical numpy structured dtype (`event_dtype`). Docstring on `order_id`: "Order ID is only for the L3 Market-By-Order feed." `ival`/`fval` are documented as "Reserved for an additional i64/f64 value". Record is 64-byte aligned (8 fields x 8 bytes).

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/types.rs ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/docs/data.rst

**The `ev` field is a u64 bitfield: low bits are a small integer event code, high bits are side and which-clock routing flags.**

Exact constants: DEPTH_EVENT=1, TRADE_EVENT=2, DEPTH_CLEAR_EVENT=3, DEPTH_SNAPSHOT_EVENT=4, DEPTH_BBO_EVENT=5, ADD_ORDER_EVENT=10, CANCEL_ORDER_EVENT=11, MODIFY_ORDER_EVENT=12, FILL_EVENT=13; SELL_EVENT=1<<28, BUY_EVENT=1<<29, LOCAL_EVENT=1<<30, EXCH_EVENT=1<<31. Semantics of BUY_EVENT: "when combined with a depth event, it means a bid-side event, while when combined with a trade event, it means that the trade initiator is a buyer." EXCH_EVENT = "a valid event to be handled by the exchange processor at the exchange timestamp"; LOCAL_EVENT = "...by the local processor at the local timestamp." A single row therefore carries both clocks and is replayed twice, once per side of the latency boundary.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/types.rs

**There is a first-party Databento DBN MBO converter in the repo, and its field mapping is directly reusable for GLBX.MDP3 mbo.**

`py-hftbacktest/hftbacktest/data/utils/databento.py`, `convert(input_file, symbol, output_filename=None, base_latency=0, file_type='mbo')` — only 'mbo' is supported (`raise ValueError(f'{file_type} is unsupported')`). Reads via `db.DBNStore.from_bytes`, selects columns `['ts_event','action','side','price','size','order_id','flags','ts_recv']`. Action map: 'A'->ADD_ORDER_EVENT, 'C'->CANCEL_ORDER_EVENT, 'M'->MODIFY_ORDER_EVENT, 'R'->DEPTH_CLEAR_EVENT, 'T'->TRADE_EVENT, 'F'->FILL_EVENT (anything else raises). Side map: 'B'->|BUY_EVENT, 'A'->|SELL_EVENT, 'N'->no side flag. Timestamps: exch_ts=int(ts_event.timestamp()*1e9), local_ts=int(ts_recv.timestamp()*1e9). DBN `flags` is written into `ival`; `fval`=0. Row tuple written is `(ev, exch_ts, local_ts, price, size, order_id, flags, 0)`.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/py-hftbacktest/hftbacktest/data/utils/databento.py

**The Databento converter special-cases CME's start-of-day snapshot by overwriting its timestamps, because the SOD orders carry historical submit times.**

Docstring verbatim: "DataBento's historical data includes a Start-of-Day (SOD) snapshot for CME data. In the snapshot, the exchange timestamp represents the original time when the order was submitted, and the data is sorted in chronological order. This ensures that orders are built with the correct price-time priority. However, since these timestamps are in the past (before the clear message), the exchange timestamp is artificially set to the local timestamp to indicate the snapshot." Code: on a DEPTH_CLEAR_EVENT it latches `snapshot_ts = local_ts`; while subsequent rows share that same `local_ts`, it sets `exch_ts = local_ts = snapshot_ts`; the first row with a different local_ts sets `snapshot_ts = None` and normal handling resumes.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/py-hftbacktest/hftbacktest/data/utils/databento.py

**Feed data is post-processed to guarantee non-negative feed latency and dual-clock event ordering before backtesting.**

`correct_local_timestamp(data, base_latency)`: computes `latency = min over rows of (local_ts - exch_ts)`; if that minimum is negative it adds `local_timestamp_offset = -latency + base_latency` to EVERY row's local_ts. Documented formula: `feed_latency = local_timestamp - exch_timestamp; adjusted_local_timestamp = local_timestamp + min(feed_latency, 0) + base_latency`. Then `correct_event_order(tmp, np.argsort(tmp['exch_ts'], kind='mergesort'), np.argsort(tmp['local_ts'], kind='mergesort'))` splits each row into its EXCH_EVENT and LOCAL_EVENT copies in the two sort orders, followed by `validate_event_order(data)`.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/py-hftbacktest/hftbacktest/data/validation.py ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/py-hftbacktest/hftbacktest/data/utils/databento.py

**The L2 queue-model interface is a 4-method trait; every model is just a different state update on 'quantity ahead of me'.**

`pub trait QueueModel<MD: MarketDepth> { fn new_order(&self, order: &mut Order, depth: &MD); fn trade(&self, order: &mut Order, qty: f64, depth: &MD); fn depth(&self, order: &mut Order, prev_qty: f64, new_qty: f64, depth: &MD); fn is_filled(&self, order: &mut Order, depth: &MD) -> f64; }`. Per-order state lives in `order.q` (a boxed `AnyClone`). `is_filled` returns a QUANTITY (f64), not a bool, in v2; v1 Python returned a bool.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/queue.rs

**RiskAdverseQueueModel (Rust spelling; v1 Python class is RiskAverseQueueModel) — queue position advances ONLY on trades; book-quantity decreases are assumed to occur entirely behind you.**

State: single f64 `front_q_qty`. new_order: `front_q_qty = depth.bid_qty_at_tick(price_tick)` (buy) or `ask_qty_at_tick` (sell) — i.e. you join behind the ENTIRE displayed size. trade(qty): `front_q_qty -= qty`. depth(prev,new): `front_q_qty = front_q_qty.min(new_qty)` (a decrease never advances you; it only caps you if the level shrank below your estimate). is_filled: `exec = (-front_q_qty / lot_size).round() as i64; if exec > 0 { front_q_qty = 0.0; return exec * lot_size } else { 0.0 }`. Docs: "This model is the most conservative model in terms of the chance of fill in the queue. The decrease in quantity by cancellation or modification in the order book happens only at the tail of the queue so your order queue position doesn't change."

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/queue.rs ; https://raw.githubusercontent.com/nkaz001/hftbacktest/v1.8.4/hftbacktest/models/queue.py ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/docs/order_fill.rst

**ProbQueueModel core update: the book-quantity decrease is split between 'in front of me' and 'behind me' by a probability p(front, back), with trade-driven decreases de-duplicated first. This single formula is shared by ALL probability variants.**

State: `QueuePos { front_q_qty, cum_trade_qty }`, both init 0; new_order sets front_q_qty = full displayed qty at the tick. trade(qty): `front_q_qty -= qty; cum_trade_qty += qty`. depth(prev_qty, new_qty): `chg = prev_qty - new_qty; chg -= cum_trade_qty; cum_trade_qty = 0.0;` then `if chg < 0.0 { front_q_qty = front_q_qty.min(new_qty); return; }` (quantity INCREASES never move you). Otherwise `front = front_q_qty; back = prev_qty - front; prob = self.prob(front, back); if prob.is_infinite() { prob = 1.0 }; est_front = front - (1.0 - prob) * chg + (back - prob * chg).min(0.0); front_q_qty = est_front.min(new_qty);`. Reading: fraction (1-prob) of the cancel volume is assumed to come from AHEAD of you (advancing you); the `min(back - prob*chg, 0)` term is the overflow correction when the volume attributed to behind you exceeds the actual size behind you. is_filled identical to RiskAdverse: `exec = (-front_q_qty/lot_size).round(); if exec>0 -> filled qty = exec*lot_size`. Author's cited references: quant.stackexchange.com/questions/3782 and rigtorp.se/2013/06/08/estimating-order-queue-position.html (plus math.ualberta.ca/~cfrei/PIMS/Almgren5.pdf in docs).

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/queue.rs

**Five probability functions ship in Rust v2 (plus two more in v1 Python). These are the ONLY thing that differs between the probabilistic models.**

With front = qty ahead of the order, back = prev_qty - front:  (1) `PowerProbQueueFunc::new(n)` -> prob = back^n / (back^n + front^n), f(x)=x.powf(n).  (2) `LogProbQueueFunc` -> prob = ln(1+back) / (ln(1+back) + ln(1+front)).  (3) `LogProbQueueFunc2` -> prob = ln(1+back) / ln(1 + back + front).  (4) `PowerProbQueueFunc2::new(n)` -> prob = back^n / (back + front)^n.  (5) `PowerProbQueueFunc3::new(n)` -> prob = 1 - (front / (front + back))^n. v1 Python additionally exposes `IdentityProbQueueModel` (f(x)=x, i.e. prob = back/(back+front)) and `SquareProbQueueModel` (f(x)=x**2), and names the three families ProbQueueModel / ProbQueueModel2 / ProbQueueModel3 for the f(back)/(f(back)+f(front)), f(back)/f(back+front), and 1-f(front/(front+back)) forms. Python API entry points: `BacktestAsset.power_prob_queue_model(n)`, `.power_prob_queue_model2(n)`, `.power_prob_queue_model3(n)`, `.log_prob_queue_model()`, `.log_prob_queue_model2()`, `.risk_adverse_queue_model()`, `.l3_fifo_queue_model()`.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/queue.rs ; https://raw.githubusercontent.com/nkaz001/hftbacktest/v1.8.4/hftbacktest/models/queue.py ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/py-hftbacktest/src/lib.rs

**The author states two boundary conditions any custom f must satisfy — these are the design constraints for rolling your own.**

Verbatim from docs/order_fill.rst: "When you set the function f, it should be as follows. * The probability at 0 should be 0 because if the order is at the head of the queue, all decreases should happen after the order. * The probability at 1 should be 1 because if the order is at the tail of the queue, all decreases should happen before the order." Also: "The function f = log(1 + x) exhibits a different probability profile depending on the total quantity at the price level, unlike power functions." (i.e. the log models are NOT scale-invariant in level size; the power models are.)

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/docs/order_fill.rst

**L3FIFOQueueModel is a genuine per-price-level FIFO deque holding BOTH market-feed orders and backtest orders; there is no probability anywhere in it.**

Struct: `backtest_orders: HashMap<OrderId,(Side,i64)>`, `mkt_feed_orders: HashMap<OrderId,(Side,i64)>`, `bid_queue: HashMap<i64, VecDeque<Order>>`, `ask_queue: HashMap<i64, VecDeque<Order>>` (key = price in ticks). `add_backtest_order` and `add_market_feed_order` both `queue.push_back(...)` — a new order joins the tail of the existing time-priority queue at its tick. Each queued Order tags its provenance in `order.q` as `L3OrderSource::Backtest | MarketFeed`. Trait `L3QueueModel<MD>` methods: contains_backtest_order, on_best_bid_update, on_best_ask_update, add_backtest_order, add_market_feed_order, cancel_backtest_order, cancel_market_feed_order, modify_backtest_order, modify_market_feed_order, fill_market_feed_order::<const DELETE: bool>, clear_orders.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/queue.rs

**L3 fill rule, stated precisely: when a market-feed order executes, every BACKTEST order sitting AHEAD of it in the same price-level deque is filled.**

`fill_market_feed_order::<DELETE>(order_id, order, depth)` walks the deque at the executed order's tick from index 0: `MarketFeed` entries that are not the executed order are skipped (`i += 1`); `Backtest` entries are removed and pushed onto `filled`; the loop `break`s when it reaches the executed market-feed order_id (removing it only if DELETE). Additionally, before that walk, orders better than the execution price are filled by crossing: buy side `if exec_price_tick < depth.best_bid_tick() { fill_bid_between::<false>(depth.best_bid_tick(), exec_price_tick + 1) }`, sell side `if exec_price_tick > depth.best_ask_tick() { fill_ask_between::<false>(depth.best_ask_tick(), exec_price_tick - 1) }`. Separately, `on_best_bid_update(prev,new)` fills ASK backtest orders in ticks `[prev_best_bid+1, new_best_bid]` and `on_best_ask_update(prev,new)` fills BID backtest orders in `[new_best_ask, prev_best_ask-1]` — i.e. fill-by-crossing.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/queue.rs

**L3 modify semantics encode the price-time-priority loss rule: a price change or a size INCREASE loses queue position; a size decrease keeps it.**

In both `modify_backtest_order` and `modify_market_feed_order`: `if (order_in_q.price_tick != new_price_tick) || (order_in_q.leaves_qty < order.qty) { ...remove(i)...; push_back(prev_order) }` (re-queued at the TAIL, of the new price level if the price moved) `else { order_in_q.qty = order.qty; order_in_q.leaves_qty = order.qty; order_in_q.exch_timestamp = ...; }` (position retained in place).

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/queue.rs

**The author explicitly warns that even an L3 FIFO model can be the wrong model, and that a book-clear message destroys queue information.**

L3FIFOQueueModel doc comment verbatim: "Backtest orders are assumed to be executed in the queue when the market order, order from the market feed, behind the backtest order is executed. Exchanges may have different matching algorithms, such as Pro-Rata, and may have exotic order types that aren't executed in a FIFO manner. Therefore, you should carefully choose the queue model, even when dealing with a Level 3 Market-By-Order feed." On clear_orders: "...estimating the order queue position becomes difficult because clearing the market feed orders leads to the loss of queue position information. Additionally, there's no guarantee that all orders preceding the clear message will persist. Due to these challenges, HftBacktest opts to clear all backtest orders upon receiving a clear message, even though this may differ from the exchange's actual behavior."

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/queue.rs

**Three latencies are modelled; feed latency is not a model at all — it is replayed from the data's two timestamps.**

docs/latency_models.rst names them: feed latency ("between the time the exchange sends the feed events ... and the time it is received by the local ... dealt with through two different timestamps: local timestamp and exchange timestamp"), order entry latency ("between the time you send an order request and the time it is processed by the exchange's matching engine"), order response latency ("between the time the exchange's matching engine processes an order request and the time the order response is received by the local. The response to your order fill is also affected by this type of latency."). Mechanically: the exchange processor only handles events flagged EXCH_EVENT and stamps them at `event.exch_ts` (`fn event_seen_timestamp(&self, event) -> Option<i64> { event.is(EXCH_EVENT).then_some(event.exch_ts) }`), while the local processor handles LOCAL_EVENT at `local_ts`. So the strategy sees a stale book by exactly `local_ts - exch_ts`.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/docs/latency_models.rst ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/proc/l3_nopartialfillexchange.rs

**Order latency enters the simulation through a two-way OrderBus that timestamps each order hand-off; this is the whole mechanism.**

`LocalToExch::request(order, reject)`: `let order_entry_latency = self.order_latency.entry(order.local_timestamp, &order); if order_entry_latency < 0 { reject(&mut order); let rej_recv_timestamp = order.local_timestamp - order_entry_latency; to_local.append(order, rej_recv_timestamp); } else { let exch_recv_timestamp = order.local_timestamp + order_entry_latency; to_exch.append(order, exch_recv_timestamp); }`. `ExchToLocal::respond(order)`: `let local_recv_timestamp = order.exch_timestamp + self.order_latency.response(order.exch_timestamp, &order); to_local.append(order, local_recv_timestamp);`. Trait: `pub trait LatencyModel { fn entry(&mut self, timestamp: i64, order: &Order) -> i64; fn response(&mut self, timestamp: i64, order: &Order) -> i64; }`. `OrderBus::append` clamps: `let timestamp = timestamp.max(latest_timestamp)` with the stated assumption "In crypto exchanges that use REST APIs, it may be still possible for order requests sent later to reach the matching engine before order requests sent earlier. However, for the purpose of simplifying the backtesting process, all requests and responses are assumed to be in order."

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/order.rs ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/latency.rs

**ConstantLatency and IntpOrderLatency are the only two order-latency models in Rust v2; IntpOrderLatency linearly interpolates a measured (req_ts, exch_ts, resp_ts) table and encodes rejection as NEGATIVE latency.**

`ConstantLatency::new(entry_latency, response_latency)` returns those constants unconditionally. `IntpOrderLatency::new(data, latency_offset)` over rows `OrderLatencyRow { req_ts: i64, exch_ts: i64, resp_ts: i64, _padding: i64 }` (`#[repr(C, align(32))]`). Interpolator: `intp(x,x1,y1,x2,y2) = ((y2-y1)/(x2-x1))*(x-x1) + y1`. entry(t): find bracketing rows with `row.req_ts <= t < next_row.req_ts`, then `lat1 = row.exch_ts - row.req_ts`, `lat2 = next.exch_ts - next.req_ts`, return `intp(t, row.req_ts, lat1, next.req_ts, lat2)`; but if `exch_ts <= 0 || next_exch_ts <= 0` it instead interpolates round-trip `resp_ts - req_ts` and returns its NEGATION ("Negative latency indicates that the order is rejected for technical reasons, and its value represents the latency that the local experiences when receiving the rejection notification"). response(t): brackets on exch_ts, `lat = intp(t, exch_ts, resp_ts-exch_ts, next_exch_ts, next_resp_ts-next_exch_ts)`, `assert!(lat >= 0)`. Before/after the table it clamps to the first/last row's latency. `latency_offset` preprocessing does `data[i].exch_ts += latency_offset; data[i].resp_ts += latency_offset + latency_offset;` (offset applied once to exch_ts, TWICE to resp_ts). Doc data example rows: `1670026844751525000, 1670026844759000000, 1670026844762122000, 0` (7.475 ms entry, 3.122 ms response).

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/latency.rs ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/docs/latency_models.rst

**The 'feed latency' order-latency family (FeedLatency / ForwardFeedLatency / BackwardFeedLatency) exists in v1 Python as live models; in v2 it survives only as a synthetic-data GENERATOR.**

v1 `FeedLatency(entry_latency_mul=1, resp_latency_mul=1, entry_latency=0, response_latency=0)`: feed_latency = mean of the nearest backward and nearest forward (local_ts - exch_ts) i.e. `(lat1 + lat2)/2.0`, falling back to whichever exists; then `entry = entry_latency + entry_latency_mul * feed_latency`, `response = response_latency + resp_latency_mul * feed_latency`. `ForwardFeedLatency` uses only the next valid forward row's `local_ts - exch_ts`; `BackwardFeedLatency` uses only the latest past row's. v2 replacement is offline: `generate_order_latency(feed_file, output_file, mul_entry=1, offset_entry=0, mul_resp=1, offset_resp=0, resampling_ns=1_000_000_000)` computing, per resampled row, `feed_latency = local_ts - exch_ts; order_entry_latency = mul_entry*feed_latency + offset_entry; order_resp_latency = mul_resp*feed_latency + offset_resp; req_ts = local_ts; exch_ts_out = req_ts + order_entry_latency; resp_ts = exch_ts_out + order_resp_latency`, resampled by `group_by_dynamic` at 1 s by default over rows having BOTH EXCH_EVENT and LOCAL_EVENT set — the output is then fed to IntpOrderLatency.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/v1.8.4/hftbacktest/models/latencies.py ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/py-hftbacktest/hftbacktest/data/utils/feed_order_latency.py

**With L2 only, the model's initial queue-position assumption is the most pessimistic one available: you are behind 100% of the displayed size at your tick, and everything after that is inference.**

Both RiskAdverse and Prob `new_order` do exactly `front_q_qty = depth.bid_qty_at_tick(order.price_tick)` / `ask_qty_at_tick(...)` — no allowance for hidden/iceberg size, no per-order granularity, no account of the order actually being at the front. Thereafter the ONLY two signals are (a) trades at your tick, which decrement front 1:1, and (b) net level-quantity changes, which are split by prob(front, back) with trade volume subtracted first to avoid double counting. docs/order_fill.rst states the premise: "Knowing your order's queue position is important to achieve accurate order fill simulation in backtesting depending on the liquidity of an order book and trading activities. If an exchange doesn't provide Market-By-Order, you have to guess it by modeling."

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/queue.rs ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/docs/order_fill.rst

**What changes with L3/MBO: queue position stops being estimated at all — it becomes an exact index in a deque — and the fill trigger changes from 'my front_q went negative' to 'a real order behind me traded' or 'the price crossed me'.**

L2 path: exchange proc calls `queue_model.trade(order, qty, depth)` then `queue_model.is_filled(order, depth) > 0.0` on same-price trades, and `queue_model.depth(order, prev_qty, new_qty, depth)` on `on_bid_qty_chg` / `on_ask_qty_chg`. L3 path: no `trade`/`depth`/`is_filled` at all; the exchange proc drives `add_market_feed_order` / `modify_market_feed_order` / `cancel_market_feed_order` / `fill_market_feed_order` / `clear_orders` from the MBO event stream and fills whatever the queue model hands back. Consequences to note: (i) L3 has only a no-partial-fill exchange processor (`l3_nopartialfillexchange.rs`; there is no `l3_partialfillexchange.rs`), whereas L2 has both `NoPartialFillExchange` and `PartialFillExchange`; (ii) the L3 exchange calls `fill_market_feed_order::<false>` i.e. DELETE=false, matching feeds (CME included) that send a fill and a subsequent delete as separate messages.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/proc/nopartialfillexchange.rs ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/proc/l3_nopartialfillexchange.rs

**A FILL event with no side flag is silently dropped by the L3 exchange processor — an upstream `todo`, and a real hazard for CME MBO where 'T' rows carry side 'N'.**

In `l3_nopartialfillexchange.rs`: `} else if event.is(EXCH_FILL_EVENT) { /* todo: handle properly if no side is provided. */ if event.is(BUY_EVENT) || event.is(SELL_EVENT) { let filled = self.queue_model.fill_market_feed_order::<false>(event.order_id, event, &self.depth)?; ... } }` — no else branch. The Databento converter maps DBN side 'N' to no side flag at all, so such events reach this guard and are skipped.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/proc/l3_nopartialfillexchange.rs ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/py-hftbacktest/hftbacktest/data/utils/databento.py

**L2 exchange fill conditions are documented exactly, and the liquidity-taking side is deliberately unrealistic.**

NoPartialFillExchange, full execution — Buy resting order: "Your order price >= the best ask price"; "Your order price > sell trade price"; "Your order is at the front of the queue && your order price == sell trade price". Sell resting order: "<= the best bid price"; "< buy trade price"; front-of-queue && == buy trade price. Liquidity-taking: "Regardless of the quantity at the best, liquidity-taking orders will be fully executed at the best. Be aware that this may cause unrealistic fill simulations if you attempt to execute a large quantity." PartialFillExchange drops the equal-price cases to partial: "Filled by (remaining) sell trade quantity: your order is at the front of the queue && your order price == sell trade price", and its taking orders "will be executed based on the quantity of the order book, even though the best price and quantity do not change due to your execution." In code, the partial-fill path uses `exec_qty = min(is_filled(...), order.leaves_qty)` and sets `Status::PartiallyFilled` while `(leaves_qty/lot_size).round() > 0`.

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/docs/order_fill.rst ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/proc/partialfillexchange.rs

**Author's stated validation method for a queue model: calibrate it against your OWN live fills, using a live-vs-backtest overlay, having first pinned down latency, and starting small.**

docs/debugging_backtesting_and_live_discrepancies.rst verbatim: "Plotting both live and backtesting values on a single chart is a good initial step. It's strongly recommended to include the equity curve and position plots for comparison purposes." ... "two significant factors may contribute to any observed discrepancies. 1. Latency: ... It's highly recommended to collect data yourself to accurately measure feed latency on your end. ... Order latency, measured from your end, can be collected by logging order actions or regularly submitting orders away from the mid-price and subsequently canceling them to measure and record order latency." ... "2. Queue Model: Selecting an appropriate queue model that accurately reflects live trading results is essential. You can either develop your own queue model or utilize existing ones. Hftbacktest offers three primary queue models such as ``PowerProbQueueModel`` series, allowing for adjustments to align with your results." ... "One crucial point to bear in mind is the backtesting conducted under the assumption of no market impact. A market order, or a limit order that take liquidity, can introduce discrepancies ... Moreover, if your limit order size is too large, partial fills and their market impact can also lead to discrepancies. It's advisable to begin trading with a small size and align the results first. Gradually increasing your trading size while observing both live and backtesting results is recommended." The latency-models doc adds the collection recipe: "You can collect the latency data by submitting unexecutable orders regularly."

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/docs/debugging_backtesting_and_live_discrepancies.rst ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/docs/latency_models.rst

**The framework's stated overall assumption — the one that bounds any fill simulator built this way — is zero market impact.**

docs/order_fill.rst verbatim: "HftBacktest is a market-data replay-based backtesting tool, which means your order cannot make any changes to the simulated market, no market impact is considered. Therefore, one of the most important assumptions is that your order is small enough not to make any market impact. In the end, you must test it in a live market with real market participants and adjust your backtesting based on the discrepancies between the backtesting results and the live outcomes." README adds the calibration standard: "if you run a live trading strategy in January 2025, the backtest for that exact period should produce results that closely align with the actual results."

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/docs/order_fill.rst ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/README.rst

**Naming caution: the Rust struct is misspelled relative to the Python class and the docs use both spellings.**

Rust v2: `pub struct RiskAdverseQueueModel<MD>(PhantomData<MD>)`; Python v1 class: `class RiskAverseQueueModel`; docs/order_fill.rst has the section heading "RiskAverseQueueModel" but links to "RiskAdverseQueueModel"; the pyo3 builder method is `risk_adverse_queue_model()`. Similarly the v2 Rust probability types are named `...ProbQueueFunc` (PowerProbQueueFunc, PowerProbQueueFunc2, PowerProbQueueFunc3, LogProbQueueFunc, LogProbQueueFunc2) while the v1 Python classes are named `...ProbQueueModel` (PowerProbQueueModel, LogProbQueueModel, IdentityProbQueueModel, SquareProbQueueModel, and the 2/3 variants).

*Source:* https://raw.githubusercontent.com/nkaz001/hftbacktest/master/hftbacktest/src/backtest/models/queue.rs ; https://raw.githubusercontent.com/nkaz001/hftbacktest/v1.8.4/hftbacktest/models/queue.py ; https://raw.githubusercontent.com/nkaz001/hftbacktest/master/py-hftbacktest/src/lib.rs


### secondary

**What the author says the probability queue models get WRONG: the underlying arrival assumption.**

The Probability Queue Models tutorial compares SquareProbQueueModel, LogProbQueueModel2 and PowerProbQueueModel3 on cumulative returns across ~100 assets and states "It is essential for accurate backtesting to find the proper queue position modeling by comparing backtest and real trading results", attributing underperformance on some assets to the fact that "order arrivals don't follow a Poisson distribution that this model assumes". (Retrieved as a WebFetch paraphrase of the rendered page with these quoted fragments; the notebook itself is not in docs/tutorials in the master repo.)

*Source:* https://hftbacktest.readthedocs.io/en/latest/tutorials/Probability%20Queue%20Models.html


### Unresolved

- No primary-source guidance exists on how to CHOOSE the exponent n for PowerProbQueueFunc/2/3. A WebSearch summary of a third-party mirror claimed 'typically in the range of 1.0 to 3.0, with higher n more conservative'; I could not find that in the repo, the docs .rst sources, or the readthedocs pages, and the algebra does not straightforwardly support 'higher n = more conservative' (higher n sharpens prob toward attributing the whole book decrease to whichever of front/back is larger, so it is conservative only while back > front). Treat the range as unsourced.

- The readthedocs v2 reference page for queue models (hftbacktest.readthedocs.io/en/latest/reference/queue_models.html) returns 404; the v1.8.4 path exists. All queue-model content here was reconstructed from repo source instead.

- docs/order_fill.rst still contains the stale sentence 'HftBacktest currently only supports Market-By-Price that is most crypto exchanges provide' in the Queue Models section, which is contradicted by the v2 source (L3FIFOQueueModel, L3MarketDepth, l3_nopartialfillexchange, the Databento MBO converter). I could not find a doc page that documents the L3 queue model narratively.

- No documented handling of a FILL event that carries no side flag (upstream `todo` in l3_nopartialfillexchange.rs); such events are silently skipped and I found no issue/PR resolving it.

- No first-party statement about how hftbacktest's L3 FIFO assumption maps onto CME Globex specifically (FIFO vs pro-rata vs configurable matching for SR3 and the UST futures complex). The author only warns generically that 'Exchanges may have different matching algorithms, such as Pro-Rata'. Establishing CME's actual per-product matching algorithm belongs to a CME-side sweep.

- No documented treatment of CME implied orders, iceberg/hidden quantity, or self-match prevention in the L3 model; the deque holds only what the MBO feed publishes.

- The Databento converter's use of the DBN `flags` byte is write-only into `ival` — I found no place in the Rust engine that reads `ival` for MBO semantics (e.g. F_LAST / F_TOB / F_SNAPSHOT), so end-of-packet batching is apparently not exploited. I could not prove this negative exhaustively (I grepped the models and proc sources, not the whole crate).

- No first-party quantitative benchmark of queue-model error (e.g. realised fill rate vs modelled fill rate) — the only comparison is the tutorial's cumulative-return/Sharpe chart across ~100 crypto assets.


## Lead-lag and price-discovery estimators for asynchronous, irregularly-spaced high-frequency data (HY / HRY contrast, Epps effect, Hasbrouck IS, Gonzalo-Granger CS, OFI cross-impact, inference)


### primary-source

**Hayashi-Yoshida (2005) cumulative covariance estimator: sum the product of every pair of increments whose observation intervals OVERLAP.**

Estimator = Σ_{i,j} r_i^X r_j^Y · 1_{O_ij ≠ ∅}, with O_ij = ]t_{i-1}, t_i] ∩ ]s_{j-1}, s_j], r_i^X = X_{t_i} − X_{t_{i-1}}, r_j^Y = Y_{s_j} − Y_{s_{j-1}}. Observation times 0=t_0≤…≤t_n=T for X and 0=s_0≤…≤s_m=T for Y, which must be independent of X and Y. It is an UNBIASED and CONSISTENT estimator of ∫_0^T σ_t^X σ_t^Y ρ_t dt as the largest mesh size goes to zero. Verbatim: 'In practice, it amounts to sum every product of increments as soon as they share any overlap of time.' No interpolation, no previous-tick, no common grid — hence no synchronisation bias. Correlation form: ρ̂ = Σ_{i,j} r_i^X r_j^Y 1_{O_ij≠∅} / sqrt(Σ_i (r_i^X)² · Σ_j (r_j^Y)²).

*Source:* https://arxiv.org/pdf/1111.7103 (Huth & Abergel, 'High Frequency Lead/lag Relationships — Empirical facts', §2.1, p.6), restating Hayashi & Yoshida (2005)

**The lagged (shifted) HY cross-correlation function: shift ALL timestamps of Y by ℓ, then apply the HY overlap rule.**

ρ̂(ℓ) = Σ_{i,j} r_i^X r_j^Y 1_{O^ℓ_ij ≠ ∅} / sqrt(Σ_i (r_i^X)² Σ_j (r_j^Y)²), with O^ℓ_ij = ]t_{i-1}, t_i] ∩ ]s_{j-1} − ℓ, s_j − ℓ]. 'It can be computed by shifting all the timestamps of Y and then using the Hayashi-Yoshida estimator. They define the lead/lag time as the lag that maximizes |ρ̂(ℓ)|.' Note the DENOMINATOR is not re-shifted — it is the unlagged realised-variance normaliser, so ρ̂(ℓ) is a proper correlation-scaled contrast.

*Source:* https://arxiv.org/pdf/1111.7103 (Huth & Abergel, §2.1, p.6)

**Hoffmann-Rosenbaum-Yoshida (Bernoulli 19(2), 2013) shifted HY contrast function U^n(θ) — exact definition including the two sign branches.**

Notation: for an interval H = (H_, H̄], the shift is H_θ := H + θ = (H_+θ, H̄+θ]; X(H) := ∫_0^{T+δ} 1_H(s) dX_s (i.e. the increment of X over H). I = {I = (s_{i,n1}, s_{i+1,n1}], i=1..n1−1} for X and J = {J = (t_{j,n2}, t_{j+1,n2}], j=1..n2−1} for Y. Then
U^n(θ̃) := 1_{θ̃≥0} Σ_{I∈I, J∈J, T̄≤T} X(I) Y(J) 1_{I ∩ J_{−θ̃} ≠ ∅}  +  1_{θ̃<0} Σ_{I∈I, J∈J, Ī≤T} X(I) Y(J) 1_{J ∩ I_θ̃ ≠ ∅}.
Estimator (their eq. 9): θ̂_n solves |U^n(θ̂_n)| = max_{θ̃ ∈ G^n} |U^n(θ̃)| over the finite grid G^n ⊂ Θ = (−δ, δ). Koike restates the same object concretely as U_n(θ) = Σ_{i,j} (X¹_{t¹_i} − X¹_{t¹_{i-1}})(X²_{t²_j} − X²_{t²_{j-1}}) 1_{{(t¹_{i-1},t¹_i] ∩ (t²_{j-1}−θ, t²_j−θ] ≠ ∅}}.

*Source:* https://arxiv.org/pdf/1303.4871 (Hoffmann, Rosenbaum & Yoshida, §3.2, p.9); restated in https://arxiv.org/pdf/1709.00353 (Koike, §1, p.2)

**HRY lead-lag model: which series leads is a sign convention on θ, and the pair is NOT jointly a semimartingale unless θ = 0.**

Bachelier version: X_t = x_0 + σ1 B^(1)_t; τ_θ(Ỹ)_t = y_0 + ρσ2 B^(1)_{t−θ} + σ2 (1−ρ²)^{1/2} W_{t−θ}, for t ∈ [θ, T], where τ_θ(Ỹ)_t := Ỹ_{t−θ}. 'Since θ ≥ 0, the sample path of X anticipates on the path of Y by a time shift θ … we say that X is the leader, and Y is the lagger. For the case θ < 0, we intertwine the roles of X and Y.' Remark 1: except when θ=0, (X_t,Y_t) is NOT an F-martingale; X is an F-martingale and Y is an F^θ-martingale with F^θ_t = F_{t−θ}. Parameter space Θ := (−δ, δ), δ = maximum temporal lead-lag allowed.

*Source:* https://arxiv.org/pdf/1303.4871 (§2.1–2.2, pp.4–5; §3.1, p.5)

**HRY Theorem 1: the lead-lag estimator is consistent at rate Δ_n (essentially Δ_n^{-1}), NOT the usual n^{-1/2} — because it is a change-point-type, not a regular parametric, problem.**

Theorem 1: 'The estimator θ̂_n defined in (9) satisfies v_n^{-1}(θ̂_n − θ) → 0 in probability, on the event {⟨X^c, τ_{−θ}(Y^c)⟩_T ≠ 0}, as n → ∞.' Here Δ_n := max{sup{|I|, I∈I}, sup{|J|, J∈J}} is the MAXIMAL distance between two data points, and Assumption B1 requires v_n < δ, v_n → 0, v_n^{-1}Δ_n → 0 in probability. Text: 'the rate of convergence of our estimator is essentially Δ_n^{-1} and not Δ_n^{-1/2}, as one would expect from a regular estimation problem in diffusion processes … This comes from the underlying structure of the statistical model, which is not regular, and which shares some analogy with change-point problems.' With regular sampling Δ_n = n^{-1}, T=1: 'the nearly obtained rate Δ_n = n^{-1} is substantially better than the usual n^{-1/2}-rate of a regular parametric statistical model.' The identification condition is ρ ≠ 0 — if ρ = 0, θ is not identified at all.

*Source:* https://arxiv.org/pdf/1303.4871 (Theorem 1, p.9; §1.2 p.3; §3.4 pp.11–12)

**HRY Proposition 1 gives the exact shape of the contrast function around the true lag: a triangular (hat) peak of half-width Δ_n on a Gaussian floor. This is the practical guide for grid choice and for reading a lead-lag plot.**

Let φ(t) = (1−|t|)1_{|t|≤1} (the hat function). In the synchronous Bachelier model with mesh Δ_n and |θ̃ − θ| ≤ Δ_n:
U^n(θ̃) = σ1σ2( T ρ φ(Δ_n^{-1}(θ̃−θ)) + T^{1/2} Δ_n^{1/2} sqrt(1 + ρ² φ(Δ_n^{-1}(θ̃−θ))) ξ^n ), ξ^n ⇒ N(0,1).
So |U^n(θ̃)| ~ |N(m_n(θ̃), a_n(θ̃)²)| with m_n(θ̃) = Tρφ(Δ_n^{-1}(θ̃−θ)) and a_n(θ̃) = T^{1/2}Δ_n^{1/2} sqrt(1+ρ²φ(·)), and |m_n|/a_n = Δ_n^{-1/2} ρ T^{1/2} φ/sqrt(1+ρ²φ) → ∞. CRITICAL DEGENERACY: 'if ρ is too small, namely of order Δ_n^{1/2}, the same kind of degeneracy phenomenon occurs … in that latter case, maximizing |U^n(θ̃)| does not locate the true value θ.' Outside |θ̃−θ| ≤ Δ_n the contrast behaves like a non-informative Δ_n^{1/2}·N(0,1).

*Source:* https://arxiv.org/pdf/1303.4871 (Proposition 1, p.10)

**HRY Proposition 2: NO central limit theorem exists for the lead-lag estimator. The strongest attainable statement is that θ lies in an interval of width 2Δ_n around θ̂_n.**

Proposition 2 (verbatim): 'Under the preceding assumptions, there is no random variable Z such that Δ_n^{-1}(θ̂_n − θ) converges in distribution to Z.' Cause: 'part of the error of θ̂_n is given by the difference between θ and its approximation on the grid G^n. This error is deterministic and cannot be controlled at the accuracy level Δ_n.' What IS obtainable: 'almost surely, for large enough n, θ ∈ (θ̂_n − Δ_n, θ̂_n + Δ_n). Therefore, we almost surely identify the interval of size 2Δ_n in which θ lies, but our method does not enable us to say something more accurate.' Tie-breaking convention used: θ̂_n = min{θ_n : θ_n ∈ argmax_{θ̃∈G^n} |U^n(θ̃)|}. DIRECT CONSEQUENCE FOR IMPLEMENTATION: a Wald-type standard error / t-statistic on θ̂ has no asymptotic justification; use bootstrap or placebo instead (see the Koike finding).

*Source:* https://arxiv.org/pdf/1303.4871 (Proposition 2 and surrounding text, p.11)

**HRY practical recipe for microstructure noise: their model has NO noise term, so subsample in TRADING time (not calendar time) using the signature plot to pick the subgrid.**

'Our model does not incorporate microstructure noise. This is reasonable if Δ_n is thought of on a daily basis … but is inconsistent in a high-frequency setting where T is of the order of one day.' Their pragmatic fix: 'A preliminary inspection of the signature plot in trading time — the realized volatility computed with different subsampling values for the trading times — enables us to select a coarse subgrid among the trading times where microstructure noise effects can be neglected. Thanks to the non-synchronous character of high-frequency data, we can take advantage of this subsampling in trading time and obtain accurate estimation of the lead-lag parameter, at a scale that is significantly smaller than the average mesh size of the coarse grid itself. This would not be possible with a regular subsampling in calendar time.' Their real-data illustration is FDAX (Dax future) vs FGBL (Euro-Bund future), same maturities.

*Source:* https://arxiv.org/pdf/1303.4871 (§3.4 'Microstructure noise' and 'How to use high-frequency data in practice', pp.12–13)

**Huth-Abergel Lead/Lag Ratio (LLR): a scalar direction statistic that avoids committing to a single argmax lag.**

LLR := Σ_{i=1}^p ρ²(ℓ_i) / Σ_{i=1}^p ρ²(−ℓ_i); X leads Y ⟺ LLR > 1. Derived from a projection argument: X leads Y iff ||r_t^Y − Proj(r_t^Y | r̄^X_{t−})||/||r^Y|| < ||r_t^X − Proj(r_t^X | r̄^Y_{t−})||/||r^X||, i.e. ||ε^{YX}||/||r^Y|| < ||ε^{XY}||/||r^X||, and ||ε^{YX}||²/||r^Y||² = 1 − (C^{YX})^T (C^{XX} C^{YY})^{-1} C^{YX}. Under uncorrelated predictors this is exactly Σρ²(ℓ_i) > Σρ²(−ℓ_i). They note it is 'closely related to the notion of Granger causality' — the Granger regression additionally includes lags of the lagger to control autocorrelation, which the LLR does not.

*Source:* https://arxiv.org/pdf/1111.7103 (Huth & Abergel, §2.1, pp.6–7)

**Tick time vs trade time matters and is a real modelling choice: the HY covariance is NOT the same in the two clocks.**

Verbatim: 'Computing the Hayashi-Yoshida correlation in trade time or in tick time does not yield the same result. Indeed, consider the trading sequence on figure 2. It is easily seen that the trade time covariance is zero while the tick time covariance is not.' Huth-Abergel define tick time as 'the clock that increments each time there is a non-zero variation of the midquote between two trades (not necessarily consecutive)' and use MIDQUOTES sampled on a trading-time basis (one quote per trade), preferring tick time because classification is binary — the midquote moves up or down.

*Source:* https://arxiv.org/pdf/1111.7103 (§2.1, p.7)

**The Epps effect: measured cross-correlation falls monotonically toward zero as sampling interval shrinks; the recovery is SLOW — hours, not minutes.**

Epps (1979) reported that stock return correlations decrease as sampling frequency increases. Tóth-Kertész, NYSE TAQ 1993-01-04 to 2003-12-31, previous-tick prices, per-day computation then averaged: for KO/PEP the cross-correlation coefficient rises from ≈0.05 at Δt of a few hundred seconds to an asymptote ≈0.26, and 'Several hours are needed for the correlation to reach its asymptotic value' (Figure 1, x-axis 0–9000 s). CAT/DE, KO/PEP, MRK/JNJ asymptotes lie in the 0.22–0.45 band depending on year. The asymptotic value is operationally defined as the mean of the cross-correlation coefficients for Δt = 6000 s through Δt = 9000 s.

*Source:* https://arxiv.org/pdf/0704.1099 (Tóth & Kertész, 'The Epps effect revisited', §2.1–2.2, Figs. 1–2, pp.4–6)

**Epps characteristic time: defined as the Δt at which the cross-correlation reaches (1 − e^{-1}) of its asymptotic value. Measured values are 420–1320 seconds and do NOT shrink as trading gets faster.**

Table 1 (characteristic time in SECONDS): CAT/DE — 1993: 940, 1997: 620, 2000: 1320, 2003: 700. KO/PEP — 920, 760, 1040, 800. MRK/JNJ — 800, 420, 880, 1060. Over the same window average intertrade time fell from ~160–180 s (1993) to under 20 s (2003), i.e. trading frequency rose by a factor of ~5–10, yet: 'a rise of the trading frequency by a factor of ∼5−10 does not lead to a measurable reduction of the characteristic time of the Epps effect.' After scaling by the asymptotic correlation the Epps curves for 1993/1997/2000/2003 collapse. Conclusion: 'the time scale of the phenomenon is connected to the reaction time of market participants (this we denote as human time scale), independent of market activity.' PRACTICAL READ FOR SR3/UST: budget an Epps characteristic time of order 7–22 minutes for the correlation to saturate, and do not assume a faster market has a shorter one.

*Source:* https://arxiv.org/pdf/0704.1099 (Table 1 and §2.2, p.7; Fig. 3 p.8; Fig. 4 p.9)

**Exact mechanism of the Epps effect: a grid-Δt correlation is a TRIANGULAR-KERNEL weighted sum of lagged fine-scale cross-correlations, so any decay in the lag profile (from asynchrony, lead-lag or tick discreteness) mechanically depresses it at small Δt.**

With Δt a multiple of Δt_0, r_Δt(t) = Σ_{s=1}^{Δt/Δt_0} r_{Δt_0}(t − Δt + sΔt_0), hence
⟨r^A_Δt(t) r^B_Δt(t)⟩ = Σ_{x=−Δt/Δt_0+1}^{Δt/Δt_0−1} (Δt/Δt_0 − |x|) ⟨r^A_{Δt_0}(t) r^B_{Δt_0}(t+xΔt_0)⟩, and analogously for the two variances (eqs. 7–8). Defining decay functions f^{A/B}_{Δt_0}(xΔt_0) = ⟨r^A_{Δt_0}(t) r^B_{Δt_0}(t+xΔt_0)⟩ / ⟨r^A_{Δt_0}(t) r^B_{Δt_0}(t)⟩ gives eq. (12): ρ^{A/B}_Δt = [Σ_x (Δt/Δt_0 − |x|) f^{A/B}(xΔt_0)] · [Σ_x (Δt/Δt_0−|x|) f^{A/A}(xΔt_0)]^{-1/2} · [Σ_x (Δt/Δt_0−|x|) f^{B/B}(xΔt_0)]^{-1/2} · ρ^{A/B}_{Δt_0}. For a pure random walk sampled with exponential(ν) waiting times, f^{A/A}=f^{B/B}=δ_{x,0} and f^{A/B}(xΔt_0) = e^{−ν Δt_0 |x|}, reproducing the observed Epps curve. The three cited contributing mechanisms are (i) asynchrony, (ii) lead-lag, (iii) tick-size discretisation.

*Source:* https://arxiv.org/pdf/0704.1099 (§3, eqs. 5–12, pp.9–11; §4, eqs. 13–19, pp.12–14)

**THE killer argument for replacing a grid-based lead_lag.py: previous-tick sampling MANUFACTURES a spurious lead-lag proportional to the activity ratio; HY does not. This is a controlled simulation with no true lead-lag.**

Setup: two synchronously correlated Brownian motions on [0, T=30600] with time step Δt = 5 and correlation ρ = 0.8, sampled along two INDEPENDENT Poisson grids with intensities λ1, λ2 (λ1 = 1/Δt = 0.2 held fixed), 64 replications averaged. Truth: the cross-correlation function should be a Dirac delta at lag 0 — there is NO lead-lag. Result (their Fig. 3): the Hayashi-Yoshida LLR stays at ≈1.0 across λ1/λ2 ∈ {1,2,4,6,8,10,20}; the PREVIOUS-TICK LLR rises monotonically to ≈40 at λ1/λ2 = 20 (and ≈32 at 10, ≈25 at 8, ≈17 at 6, ≈10 at 4). Text: 'The previous-tick correlation function is blurred by spurious liquidity effects: the asymmetry grows significantly with λ1/λ2, yielding the most active Brownian motion to always lead the other. In the contrary, the Hayashi-Yoshida LLR is not impacted.' The previous-tick cross-correlation level also collapses toward 0 with asynchrony while HY holds ~0.78–0.8. Caveat they state: the HY CCF 'remains symmetric' but 'is not exactly a Dirac mass. The irregular sampling creates correlation at non-zero lags.'

*Source:* https://arxiv.org/pdf/1111.7103 (§2.2 and Fig. 3, pp.8–9)

**Cont-Kukanov-Stoikov order flow imbalance: exact event-level definition e_n and the interval aggregate OFI_k.**

Level-1 book, observation n has (P^B_n, q^B_n, P^A_n, q^A_n). The per-event contribution is
e_n = I_{{P^B_n ≥ P^B_{n−1}}} q^B_n − I_{{P^B_n ≤ P^B_{n−1}}} q^B_{n−1} − I_{{P^A_n ≤ P^A_{n−1}}} q^A_n + I_{{P^A_n ≥ P^A_{n−1}}} q^A_{n−1}.
(Note the ≥/≤ overlap at equality is intentional: if q^B rises with P^B unchanged, e_n = q^B_n − q^B_{n−1}.) With event times τ_n and N(t) = max{n | τ_n ≤ t}, OFI_k = Σ_{n=N(t_{k−1})+1}^{N(t_k)} e_n over [t_{k−1}, t_k]; mid-price change in ticks ΔP_k = (P_k − P_{k−1})/δ. Stylised-book derivation: ΔP = OFI/(2D) + ε with OFI = L^b − C^b − M^s − L^s + C^s + M^b and D the per-level depth. OFI treats a market sell and a cancel-buy of equal size as equivalent, and includes limit orders and cancellations, not just trades.

*Source:* https://arxiv.org/pdf/1011.6402 (Cont, Kukanov & Stoikov, 'The price impact of order book events', §2.1–2.2, pp.3–6)

**OFI-to-price relation is LINEAR with slope inversely proportional to depth — the empirical anchor numbers.**

Data: 50 randomly chosen S&P 500 stocks, TAQ Level-1 consolidated quotes+trades, April 2010, 21 trading days, uniform grid with Δt = 10 seconds, β estimated by OLS in each half-hour subsample (273 subsamples, ~180 observations each), White heteroskedasticity-consistent standard errors. Regression ΔP_k = α̂_i + β̂_i OFI_k + ε̂_k: cross-sectional AVERAGE R² = 65%, average β̂ = 0.0398, average t(β̂) = 11.47, average α̂ = 0.0002 with t(α̂) = −0.02. Coefficient passed the 5% z-test in 97% of samples (α in 6%, quadratic term γ_Q in 9%). Adding γ_Q·OFI_k|OFI_k| raises R² only from 65% to 68% and γ̂_Q is insignificant in most samples. Excluding price-changing events from OFI (tautology check) drops R² to the 35–60% region — it does not collapse. Depth relation β_i = c/AD_i^λ + ν_i with AD_i = (1/(2(N(T_i)−N(T_{i−1})−1))) Σ (q^B_n + q^A_n): λ̂ ≈ 1 across stocks and λ=1 cannot be rejected for 35 of 50 stocks (SLB example: log β = −1.026 log AD − 1.096, R² = 0.863).

*Source:* https://arxiv.org/pdf/1011.6402 (§3.1–3.2, Tables 1–2, Figs. 2–4, pp.8–12)

**Koike (2019): the correct null distribution for an estimated lead-lag comes from a WILD (multiplier) BOOTSTRAP of max_θ|U_n(θ)|, with Rademacher multipliers. This is the theoretically-backed replacement for a Wald interval that HRY Prop 2 forbids.**

Model X¹_t = x¹_0 + σ1 B¹_t, X²_t = x²_0 + σ2 B²_{t−θ}, non-synchronous observation. Test H_0: ρ = 0 vs H_1: ρ ≠ 0 (eq. 1.2) — because θ is not identified when ρ=0, you must reject this null BEFORE reporting a lead-lag estimate. Statistic T_n = √n max_{θ∈G_n} |U_n(θ)|. Bootstrap: let (w¹_I)_{I∈Π¹_n} and (w²_J)_{J∈Π²_n} be mutually independent i.i.d. variables independent of X¹, X²; set U*_n(θ) = Σ_{I∈Π¹_n, J∈Π²_n} (w¹_I X¹(I))(w²_J X²(J)) K(I, J_{−θ}) with K(H,H') = 1_{H∩H'≠∅}; T*_n = √n max_{θ∈G_n}|U*_n(θ)|; q*_n(1−α) = inf{z ∈ R : P(T*_n ≤ z | F^X) ≥ 1−α}. Reject if T_n ≥ q*_n(1−α). In practice: generate R i.i.d. copies T*_n(1),…,T*_n(R) and compute the bootstrap p-value p̂* = (1/R) Σ_{r=1}^R 1_{{T*_n(r) > T_n}}, reject if p̂* ≤ α. Proposition 4.2: under H_0, P(T_n ≥ q*_n(1−α)) → α; under H_1 it → 1 (requires r_n = O(n^{−3/4−η})). Remark 4.5: the √n factor can be dropped in implementation. Remark 4.6 (verbatim): 'choosing Rademacher variables induces a quite good finite sample performance of our testing procedure. Namely, the proposed test performs very well in finite samples when the distributions of w¹_I and w²_J are chosen according to P(w¹_I = 1) = P(w¹_I = −1) = P(w²_J = 1) = P(w²_J = −1) = 1/2.' Bootstrap observations are generated UNDER H_0.

*Source:* https://arxiv.org/pdf/1709.00353 (Koike, 'Gaussian approximation of maxima of Wiener functionals…', §4.1, p.14)

**Koike's simulation gives concrete size/power for that test — and shows the power is WEAK at low correlation and sparse sampling, which is the operating regime of a thin SR3 outright vs a busy UST future.**

Setup: model (1.1) with T=1, θ=0.1, x¹_0=x²_0=0, σ1=σ2=1, ρ ∈ {0, 0.25, 0.5, 0.75}; Rademacher multipliers; 999 bootstrap replications; 10,000 Monte Carlo iterations. Synchronous scenario t¹_i = t²_i = i·h_n with h_n ∈ {10^-3, 3·10^-3, 6·10^-3}, grid G_n = {k·h_n : |k·h_n| ≤ 0.3}. Non-synchronous scenario: simulate on i·10^-3 (i=0..1000) then randomly pick 300 sampling times for X¹ and independently 300 for X², grid G_n = {k·10^-3 : |k| ≤ 300}. Table 1 rejection rates (α = 0.01/0.05/0.10):
 h_n=10^-3: ρ=0 → 0.011/0.050/0.100; ρ=0.25, 0.5, 0.75 → 1.000 throughout.
 h_n=3·10^-3: ρ=0 → 0.010/0.051/0.101; ρ=0.25 → 0.139/0.281/0.382; ρ=0.5 → 0.977/0.993/0.997; ρ=0.75 → 1.000.
 h_n=6·10^-3: ρ=0 → 0.011/0.050/0.099; ρ=0.25 → 0.041/0.131/0.214; ρ=0.5 → 0.634/0.802/0.867; ρ=0.75 → 0.997/1.000/1.000.
 Non-synchronous: ρ=0 → 0.010/0.051/0.099; ρ=0.25 → 0.056/0.152/0.235; ρ=0.5 → 0.753/0.879/0.919; ρ=0.75 → 1.000.
Size is accurate everywhere; power at ρ=0.25 collapses to 4–24% once sampling is sparse — consistent with HRY's finding that the contrast function goes flat when ρ is small. The procedure is implemented in the R package yuima as llag.test since version 1.7.2.

*Source:* https://arxiv.org/pdf/1709.00353 (§5 and Table 1, pp.17–18)

**yuima's llag()/mllag() ship pointwise CIs and p-values, and the documentation explicitly warns they are NOT simultaneous — a multiple-testing hazard across the lag grid.**

llag(ci=TRUE) computes pointwise confidence intervals and p-values; 'The asymptotic variances of the cross-correlations are calculated at each point of the grid by using the naive kernel approach descrived in Section 8.2 of Hayashi and Yoshida (2011).' Null tested: the corresponding correlation equals zero. Arguments: grid, ci, alpha (default 0.01), fisher (Fisher z-transformation of p-values and CIs), bw (bandwidth for the asymptotic variance). Verbatim caution: 'The evaluated p-values should carefully be interpreted because they are calculated based on _pointwise confidence intervals_ rather than _simultaneous confidence intervals_.' llag returns a skew-symmetric matrix of estimated lead-lag parameters; with psd=TRUE the covariance is converted via C → (C%*%C)^(1/2) so that θ_ij maximises the cross-CORRELATION rather than the covariation. mllag() returns ALL time shifts at which the cross-correlations exceed the threshold, and the docs concede this is 'mathematically debatable because there would be a multiple testing problem' and that 'the significance level alpha probably does not give the correct level.'

*Source:* https://rdrr.io/rforge/yuima/man/llag.html and https://rdrr.io/rforge/yuima/man/mllag.html (yuima package documentation)

**The standard PLACEBO for a lead-lag estimate: surrogate data that preserves the real timestamp structure exactly but destroys the true lead-lag. Huth-Abergel's construction, with the numbers that show it working.**

Construction: for each trading day, generate two SYNCHRONOUSLY correlated Brownian motions with the same correlation as the real pair, ρ = ρ̂_HY(0), on [0,T] with a mesh of one second (T = the duration of a trading day). Then sample these Brownian motions along THE TRUE TIMESTAMPS of the two assets, so the surrogate data have the same timestamp structure as the original. Any measured lead-lag in the surrogate is therefore an artefact of the sampling geometry, not of information flow. Lag grid used (seconds): 0, 0.01, 0.02, …, 0.1, 0.2, …, 1, 2, …, 10, 15, 20, 30, …, 120, 180, 240, 300. RESULTS (real value, sd in brackets → surrogate value): FCE/FSMI (future/future) LLR 1.26 (0.017), max lag 0.2 s (0.01) → surrogate LLR 1 (0.004), max lag −0.03 (0.059). FCE/TOTF.PA (index future/constituent stock) LLR 2.12 (0.038), max lag 0.6 s (0.078) → surrogate LLR 1 (0.006), max lag 0.02 (0.035). RENA.PA/PEUP.PA (stock/stock) LLR 1.15 (0.018), max lag 0.95 s (0.291) → surrogate LLR 1.01 (0.01), max lag −0.09 (0.298). FSMI/NESN.VX LLR 0.69 (0.017), max lag −16.89 s (8.442) → surrogate LLR 1 (0.011), max lag 0.43 (0.298). 'The LLR for surrogate data is equal to one and the maximum lag is statistically zero with a usual confidence level of 95% for the four pairs of assets considered.' Economic-size check they also report: the difference between the maximum correlation and the correlation at lag zero is 6% for FCE/FSMI, 7% for FCE/TOTF.PA, 0.3% for RENA.PA/PEUP.PA and 2% for FSMI/NESN.VX.

*Source:* https://arxiv.org/pdf/1111.7103 (Huth & Abergel, §3.1 and Figs. 4–5, pp.10–12)

**Pragmatic day-level confidence interval for an HY cross-correlation, as actually used in the literature — and its stated limitation.**

Footnote 8 verbatim construction: 'Assuming our dataset is made of D uncorrelated trading days, the confidence interval for the average correlation ρ̄_D = (1/D) Σ_{d=1}^D ρ_d is [ρ̄_D ± 1.96 σ_D/√D] where σ²_D = (1/D) Σ_{d=1}^D ρ²_d − ρ̄²_D. By doing so, we neglect the variance of the correlation estimator inside a day.' i.e. treat each day's HY estimate at each lag as one i.i.d. draw and use the across-day standard error. This is a day-block bootstrap in spirit and is the cheapest honest interval available given HRY Prop 2; it understates uncertainty because within-day estimator variance is ignored.

*Source:* https://arxiv.org/pdf/1111.7103 (Huth & Abergel, footnote 8, p.10)

**Empirically, HY-measured lead-lag is small in absolute time and correlates with liquidity — with the exact discriminatory statistics.**

Huth-Abergel, 41 CAC40 constituents + their future, 820 pairs, Reuters RTCE tick data 2010-03-01 to 2010-05-31, first and last half hours dropped, VWAP-aggregation of same-timestamp trade sequences. Table 3 (proportion of the 820 pairs falling in each quadrant of LLR−1 vs liquidity-ratio−1, i.e. the discriminatory power of each liquidity indicator): intertrade duration ⟨Δt⟩ 7%/6%/44%/43% (N++/N−−/N+−/N−+) → concordant 13%, discordant 87%; average turnover per trade ⟨P·V⟩ 35%/42%/16%/7% → concordant 77%, discordant 23%; bid/ask spread ⟨s⟩/δ 17%/12%/33%/38% → 29%/71%; midquote volatility ⟨|Δm|⟩/δ 20%/13%/31%/36% → 33%/67%; tick size ⟨δ/m⟩ → 48%/52%; trade-through frequency → 52%/48%. 'The most discriminatory indicators are the intertrade duration, the average turnover per trade, the average bid/ask spread and the midquote volatility. The tick size and the probability of having a trade through do not seem to play any direct role in determining who leads or lags.' Also: 'there is a trade-off in lead/lag relationships: while liquid vs illiquid pairs exhibit highly asymmetric cross-correlation functions, they tend to be less correlated than pairs with similar liquidity.' And on the strategy question: 'a naive strategy based on market orders cannot make any profit of this effect because of the bid/ask spread' despite ~60% directional forecast accuracy on the lagger's next midquote move.

*Source:* https://arxiv.org/pdf/1111.7103 (Abstract; §1 Tables 1–2, pp.3–5; §3.2 Table 3 and Figs. 6–7, pp.13–15)


### secondary

**Hasbrouck (1995) information share: the VECM/Wold/Beveridge-Nelson chain, exactly.**

VECM with K−1 lags: ΔP_t = A(Θ'P_{t−1} − μ) + Σ_{j=1}^{K−1} Γ_j ΔP_{t−j} + e_t, e_t ~ iid(0, Σ), P_t an n×1 vector of I(1) log prices, Θ' = (1_{n−1} : −I_{n−1}) the (n−1)×n cointegrating basis. Wold: ΔP_t = Ψ(L)e_t, Ψ_0 = I_n. Beveridge-Nelson: P_t = P_0 + Ψ(1) Σ_{j=0}^t e_j + Ψ*(L)e_t. Because Θ'Ψ(1) = 0, Ψ(1) has RANK ONE: Ψ(1) = 1_n ψ' with ψ = (ψ_1,…,ψ_n)'. Permanent (efficient-price) innovation η^P_t = ψ'e_t; var(η^P_t) = ψ'Σψ. Long-run matrix from Johansen factorisation: Ψ(1) = Θ⊥ (A'⊥ Γ(1) Θ⊥)^{-1} A'⊥ with Γ(1) = I_n − Σ_{j=1}^{K−1} Γ_j, Θ'Θ⊥ = 0, A'A⊥ = 0. (Equivalent notation elsewhere: Ψ(1) = β⊥(α'⊥ Γ β⊥)^{-1} α'⊥.)

*Source:* https://faculty.washington.edu/ezivot/research/Fifth%20Draft-%20An%20Order%20Invariant%20measure%20of%20price%20discovery,%20application%20to%20ETF%20-%20Copy.pdf (Sultan & Zivot, 'Price Discovery Share', §2, eqs. 1–9, pp.5–7) — independently corroborated by https://rdrr.io/rforge/ifrogs/f/inst/doc/pdshare.pdf (Aggarwal, §2, pp.2–3)

**Hasbrouck IS formula and the Cholesky/ordering problem, exactly.**

Case 1, Σ (=Ω) DIAGONAL: IS_i = (ψ_i σ_i)² / (ψ'Σψ), i=1..n  [equivalently IS_j = ψ_j² Ω_jj / (ψΩψ')]. Case 2, Σ NON-DIAGONAL: IS_i = ((ψ'_i F)_i)² / (ψ'Σψ), where (ψ'_i F)_i is the i-th element of ψ'F and F is a LOWER TRIANGULAR Cholesky factor with FF' = Σ. 'The value of F and hence, also the value of IS_i, depends on the ordering in which the individual prices enter into the vector of price, P_t. Therefore, when Σ is non-diagonal Hasbrouck's approach can only provide upper and lower bounds for IS_i based on all possible orderings of prices in the vector.' Upper bound = that market's price placed FIRST; lower bound = placed LAST (Baillie et al. 2002). For n markets that is n! permutations. Bivariate closed form with F = [[σ1, 0],[ρσ2, σ2(1−ρ)^{1/2}]] (as printed; the (1−ρ)^{1/2} is almost certainly a typo for (1−ρ²)^{1/2}) and ρ² = σ12²/(σ1²σ2²):
IS_{1,non-diag} = (ψ1²σ1² + ψ2²σ2²ρ² + 2ψ1ψ2σ12) / (ψ1²σ1² + ψ2²σ2² + 2ψ1ψ2σ12);
IS_{2,non-diag} = (ψ2²σ2² − ψ2²σ2²ρ²) / (ψ1²σ1² + ψ2²σ2² + 2ψ1ψ2σ12). Reversing the ordering swaps subscripts 1 and 2.

*Source:* https://faculty.washington.edu/ezivot/research/Fifth%20Draft-%20An%20Order%20Invariant%20measure%20of%20price%20discovery,%20application%20to%20ETF%20-%20Copy.pdf (eqs. 10–11, 17–19, pp.7, 9); same formulas in https://rdrr.io/rforge/ifrogs/f/inst/doc/pdshare.pdf (§2.1, p.3)

**How wide the IS bounds actually get: with equal error-correction speeds and ρ=0.9 the Hasbrouck bounds are [0.05, 0.95] — the metric is essentially uninformative — while the Gonzalo-Granger share is pinned at exactly 0.50.**

Baillie-Booth-Tse-Zabotina (2002) analytic model: Δx_1 = −α_1(x_{1,t−1} − x_{2,t−1}) + ε_{1t}; Δx_2 = α_2(x_{1,t−1} − x_{2,t−1}) + ε_{2t}; cov(e_{1t},e_{2t}) = [[1, ρ],[ρ, 1]]. TRUE values for x_1 (IS-UB / IS-LB / CS): Case A (α1=α2=0.05): ρ=0 → 0.50/0.50/0.50; ρ=0.1 → 0.55/0.45/0.50; ρ=0.5 → 0.75/0.25/0.50; ρ=0.9 → 0.95/0.05/0.50. Case B (α1=0.0, α2=0.05): ρ=0 → 1.00/1.00/1.00; ρ=0.5 → 1.00/0.75/1.00; ρ=0.9 → 1.00/0.19/1.00. Case C (α1=0.025, α2=0.05): ρ=0 → 0.80/0.80/0.67; ρ=0.5 → 0.89/0.43/0.67; ρ=0.9 → 0.98/0.09/0.67. Baillie et al. (2002) proposed using the MEAN of the two bounds as a unique value; Lien & Shrestha (2009) point out the mean 'cannot be derived as a result of any particular factor structure' and that for >2 prices the mid-points often do not sum to 100%.

*Source:* https://rdrr.io/rforge/ifrogs/f/inst/doc/pdshare.pdf (Aggarwal, Table 1, p.8) — bound-mean critique from https://faculty.washington.edu/ezivot/research/Fifth%20Draft-%20An%20Order%20Invariant%20measure%20of%20price%20discovery,%20application%20to%20ETF%20-%20Copy.pdf (footnote 5, p.2)

**Data alignment required by Hasbrouck IS: a COMMON REGULAR CALENDAR GRID, canonically 1 second — and even 1 second is not fine enough to kill the contemporaneous correlation that creates the bound width. This is precisely the requirement HY does not have.**

Verbatim: 'Hasbrouck (1995) suggests sampling the trade and quote prices at a high enough frequency such that contemporaneous correlation among the innovations becomes negligible. However, numerous studies including ours find that even with the use of bid-ask quotes sampled at a 1-second interval there is still enough residual correlation to produce a wide range for IS.' Worked example on 1-second data (RELIANCE spot vs futures, NSE India, 2009-05-06 06:25:07–12:00:00, AIC-selected 52 VECM lags): IS original ordering spot 0.07401349 / futures 0.92598651; reversed ordering futures 0.9842687 / spot 0.0157313; CS spot 0.1092093 / futures 0.8907907. Residual covariance matrix: [[2.973507e-08, 4.173273e-09],[4.173273e-09, 2.630731e-08]]. With override.lags=60: IS 0.06864645/0.93135355 and reversed 0.986837/0.013163; CS 0.1006936/0.8993064. Also: 'IS reports misleading results due to its serious identification problem. In contrast, PDS results are consistent and also robust to the use of quotes data with higher time intervals.'

*Source:* https://rdrr.io/rforge/ifrogs/f/inst/doc/pdshare.pdf (§4, pp.4–6); https://faculty.washington.edu/ezivot/research/Fifth%20Draft-%20An%20Order%20Invariant%20measure%20of%20price%20discovery,%20application%20to%20ETF%20-%20Copy.pdf (footnote 5, p.2; §1, p.4)

**Gonzalo-Granger permanent-transitory component share: a function of the error-correction loadings ALONE. It ignores the innovation covariance Ω entirely — that is the crisp difference from Hasbrouck.**

Decomposition p_t = A_1 f_t + A_2 z_t, with f = γ'p_t ~ I(1) the permanent component and z_t ~ I(0) the transitory component; A_1, A_2 loading matrices; γ' the matrix of common factor weights. Gonzalo-Granger define γ = (α'⊥ β⊥)^{-1} α'⊥ such that α'⊥ α = 0 and β'⊥ β = 0, where α is the VECM error-correction coefficient matrix (ΔP_t = αβ'P_{t−1} + Γ_1ΔP_{t−1} + … + Γ_kΔP_{t−k} + ε_t, ε_t ~ N(0,Ω)) and β the cointegrating vector (β = (1,−β)' for a bivariate system). Component share for market j (Booth et al. 1999; Chu et al. 1999; Harris-McInish-Wood 2002; Baillie et al. 2002):
CS_j = α⊥,j / (α⊥,1 + α⊥,2),  j = 1, 2.
Contrast: 'Hasbrouck's IS focuses on the variance of the efficient price innovation, and measures what proportion of the efficient price variance can be attributed to the innovations from different markets. The CS approach, on the other hand, focuses on the composition of the efficient price innovation and measures a market's contribution to price discovery as its contribution to the efficient price innovation.' Consequence: CS is ORDER-INVARIANT and unique (no Cholesky, no bounds), but it also discards all information in Ω — see the Baillie table where CS is flat at 0.50 while the IS bounds spread to [0.05, 0.95].

*Source:* https://rdrr.io/rforge/ifrogs/f/inst/doc/pdshare.pdf (§2.2 and §1, pp.2–3)

**Both IS and CS are only valid 'who moves first' metrics when the two price series carry EQUAL noise; otherwise they mix leadership with noise-avoidance. Putniņš's information leadership share (ILS) is the standard fix.**

Putniņš (2013), Journal of Empirical Finance 23: 'Hasbrouck information share and Harris-McInish-Wood component share are only consistent with the view that a market dominates price discovery if it is the first to reflect new information IF the price series have equal levels of noise, including microstructure frictions and liquidity. If the noise in the price series differs, the information and component shares measure a combination of leadership in impounding new information and relative avoidance of noise, to varying degrees. A third price discovery metric, the information leadership share, uses the information share and the component share together to identify the price series that is first to impound new information, and is robust to differences in noise levels.' NOTE FOR SR3-vs-UST-futures work: SR3 and the UST complex have very different tick sizes, spreads and depths, i.e. very different noise levels — so a bare IS or CS comparison between them is exactly the case Putniņš warns about.

*Source:* https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2261009 (Putniņš, 'What Do Price Discovery Metrics Really Measure?') — abstract/summary only; full text not fetched

**Cont-Cucuringu-Zhang headline split: CONTEMPORANEOUS cross-impact is redundant once multi-level OFI is integrated, but LAGGED cross-asset OFI does add forecasting power at short horizons and decays fast.**

In-sample R² (Table 3): PI^1 71.16% (sd 13.80), CI^1 73.87% (sd 12.23), PI^I 87.14% (sd 9.16), CI^I 87.85% (sd 8.58). Out-of-sample R² (Table 5): PI^1 64.64% (sd 21.82), CI^1 66.03% (sd 19.51), PI^I 83.83% (sd 16.90), CI^I 83.62% (sd 14.53). So adding cross-impact buys +2.71 pp in-sample with best-LEVEL OFIs but only +0.71 pp with INTEGRATED OFIs, and −0.21 pp out-of-sample. Abstract-level statement: 'Once information from multiple levels is integrated into OFI, multi-asset models with cross-impact do not provide additional explanatory power for contemporaneous impact compared to a sparse model without cross-impact terms. However, lagged cross-asset OFIs do improve the forecasting of future returns, with this lagged cross-impact mainly manifesting at short-term horizons and decaying rapidly in time.' PRACTICAL READ: the cross-asset signal lives in the LAG structure, not in contemporaneous co-movement — which is exactly the object an HY-style lead-lag contrast is built to measure.

*Source:* https://arxiv.org/html/2112.13213v4 (Cont, Cucuringu & Zhang, Tables 2/3/5 and abstract); numbers confirmed by two independent extraction passes of the same page but not read by me directly


### inferred

**There is NO standard Hayashi-Yoshida-style lead-lag estimator for order flow. The standard treatment of cross-asset OFI is a LAGGED, LASSO-regularised cross-impact regression on a regular grid — which reintroduces exactly the synchronisation problem HY solves.**

Cont, Cucuringu & Zhang (Quantitative Finance 23(10), 2023; arXiv 2112.13213) is the canonical multi-asset OFI treatment. Multi-level OF: OF^{m,b}_{i,n} = q^{m,b}_{i,n} if P^{m,b}_{i,n} > P^{m,b}_{i,n−1}; q^{m,b}_{i,n} − q^{m,b}_{i,n−1} if equal; −q^{m,b}_{i,n} if less (ask side analogous with opposite signs). OFI^{m,h}_{i,t} = Σ (OF^{m,b}_{i,n} − OF^{m,a}_{i,n}) over (t−h, t]; normalised ofi^{m,h}_{i,t} = OFI^{m,h}_{i,t}/Q^{M,h}_{i,t} by average book depth. INTEGRATED OFI: ofi^{I,h}_{i,t} = (w_1^T ofi^{(h)}_{i,t}) / ||w_1||_1 with w_1 the first principal vector, L1-normalised so the weights sum to unity; the first PC explains 89.06% of total variance. Contemporaneous cross-impact: r^h_{i,t} = α_i + β_{i,i} ofi^{I,h}_{i,t} + Σ_{j≠i} β_{i,j} ofi^{I,h}_{j,t} + η_{i,t}, LASSO over ~100 stocks. Lagged/forecasting: r^{(h)}_{i,t+τ} = α_i + β_{i,i} ofi^{I,h}_{i,t} + Σ_{j≠i} β_{i,j} ofi^{I,h}_{j,t} + ε_t. The 'no standard HY-on-OFI estimator' claim is my own conclusion from failing to find one in the sweep — treat it as inferred, not established.

*Source:* https://arxiv.org/html/2112.13213v4 (Cont, Cucuringu & Zhang) for the specifications and PCA; the absence of an HY-on-OFI treatment is my own negative result from searching


### Unresolved

- The ORIGINAL papers for four of the six topics were never opened — all are paywalled and I read only consistent secondary restatements: Hasbrouck (1995) 'One security, many markets', Journal of Finance 50(4); Gonzalo & Granger (1995), JBES 13(1); Epps (1979) 'Comovements in stock prices in the very short run', JASA; Hayashi & Yoshida (2005), Bernoulli 11(2). The IS and CS formulas I report were corroborated across two independent secondary sources (Sultan-Zivot PDS working paper and the ifrogs pdshare vignette) which agree exactly, but I have not verified them against Hasbrouck's or Gonzalo-Granger's own notation.

- The Cholesky factor printed in the Sultan-Zivot bivariate example is F = [[σ1, 0],[ρσ2, σ2(1−ρ)^{1/2}]]. For FF' = Σ this should be σ2(1−ρ²)^{1/2}. I believe this is a typo in that paper but I could not confirm it against another source, so DO NOT copy that line verbatim into code — re-derive the Cholesky.

- Hayashi & Yoshida (2011) Section 8.2 'naive kernel approach' — the actual asymptotic-variance formula behind yuima's llag(ci=TRUE) pointwise confidence intervals. I have only the yuima documentation's pointer to it; the formula itself was not fetched. If you want analytic (non-bootstrap) standard errors on the HY cross-correlation at each lag, this is the one thing still missing.

- No paper was found that applies the Hayashi-Yoshida contrast function to ORDER FLOW (cumulative OFI) rather than price. The cross-asset OFI literature (Cont-Cucuringu-Zhang) works exclusively with fixed-h regular-grid regressions. Whether the HY overlap rule is even well-posed on a cumulative OFI series (which is a jump process of queue-size changes, not a continuous semimartingale) is an open modelling question the HRY theory does not cover — their Assumption A requires a regular semimartingale with a continuous local-martingale part.

- Cont-Cucuringu-Zhang report that lagged cross-asset OFI improves forecasting 'at short-term horizons' with rapid decay, but I did not extract the actual forecast-horizon R^2 table or the numeric decay profile (which horizons in seconds/minutes, and how much R^2 at each). If the decay curve matters for design, that table needs a direct read of arXiv:2112.13213 §4.

- Nothing was found specific to SR3 or the US Treasury futures complex: no published HY lead-lag or Hasbrouck IS estimate for SR3 vs ZT/ZF/ZN/TN/ZB/UB, or for CME futures vs the cash Treasury market, was located in this sweep. The Fed FEDS note on Treasury OFI (Nov 2025) uses a coarse definition (buyer- minus seller-initiated volume, 5-minute bars, 7am-5pm ET) and performs NO lead-lag or cross-market analysis. The OFR working paper 19-04 'Cross-Asset Market Order Flow, Liquidity, and Price Discovery' (Garrison, Jain, Paddrik) does cross-asset order flow and price discovery but on S&P 500 ETFs vs E-mini futures, not Treasuries; I read only its title page and abstract and did not verify its specification or results.

- Putniņš (2013) information leadership share: I have the paper's own summary of what ILS does but NOT its formula. If you want ILS (the robust-to-unequal-noise metric, and the one most relevant to comparing a tight UST future against a wider SR3 book), the exact construction from IS and CS still needs to be fetched.

- The Epps magnitude numbers I report are equities (NYSE TAQ 1993-2003). Whether SR3 or UST futures show a comparable 7-22 minute characteristic time is untested — Tóth-Kertész's own finding is that the time scale is set by human reaction time, not activity, which would suggest similar magnitudes, but that is an extrapolation from their data, not a measurement on futures.


## Order-flow imbalance at the touch and multi-level (OFI / MLOFI / integrated OFI), trade-sign flow measures, and their pitfalls — sourced for a numba MBO engine over Databento GLBX.MDP3 (SR3, ZT/ZF/ZN/TN/ZB/UB)


### primary-source

**CKS define the per-event contribution e_n from two consecutive best-quote states with four indicator terms**

Read verbatim off arXiv:1011.6402v3 p.4:  e_n = I_{P^B_n >= P^B_{n-1}} * q^B_n  -  I_{P^B_n <= P^B_{n-1}} * q^B_{n-1}  -  I_{P^A_n <= P^A_{n-1}} * q^A_n  +  I_{P^A_n >= P^A_{n-1}} * q^A_{n-1}.  P^B_n, q^B_n = bid price and bid queue size (shares) at observation n; P^A_n, q^A_n = ask price and ask size. Note both indicators fire on equality, so a same-price size change gives e_n = q^B_n - q^B_{n-1} (bid) exactly. Paper's own gloss: 'if q^B increases but P^B remains the same, we assign e_n = q^B_n - q^B_{n-1} ... If P^B increases, we let e_n = q^B_n, representing the size of a price-improving limit order. If P^B decreases, we let e_n = q^B_{n-1}' (sign reversed on the ask). Only ONE of the four event types occurs between consecutive observations. Consequence: a market sell and a cancel-buy of the same size are treated as identical.

*Source:* https://arxiv.org/pdf/1011.6402 (v3, 13 Apr 2011), Section 2.1, p.4

**CKS bar aggregation is a plain sum of e_n over the events falling in the bar; the response variable is the mid-price change in ticks**

OFI_k = sum_{n = N(t_{k-1})+1}^{N(t_k)} e_n, where events occur at random times tau_n, N(t) = max{n : tau_n <= t}, and N(t_{k-1})+1 / N(t_k) index the first and last event in (t_{k-1}, t_k].  Response: Delta P_k = (P_k - P_{k-1}) / delta, where P_k is the mid-quote at t_k and delta is the tick size (1 cent in their data). Their grid is uniform in CALENDAR time with Delta t = 10 seconds.

*Source:* https://arxiv.org/pdf/1011.6402 (v3), Section 2.1, p.4

**The stylized-book derivation gives the exact depth scaling ΔP = OFI/(2D)**

With D shares at every price level beyond the best and arrivals/cancels only at the best: Delta P^b = ceil[(L^b - C^b - M^s)/D];  Delta P^a = -ceil[(L^s - C^s - M^b)/D];  mid: Delta P = (1/2)ceil[(L^b - C^b - M^s)/D] - (1/2)ceil[(L^s - C^s - M^b)/D].  'Note that the above is equivalent (up to truncation) to  Delta P = OFI/(2D) + epsilon'  (eq. 1), where OFI = L^b - C^b - M^s - L^s + C^s + M^b and epsilon is the truncation error. So the stylized model has beta = 1/(2D), i.e. c = 1/2 and lambda = 1.

*Source:* https://arxiv.org/pdf/1011.6402 (v3), Section 2.2, pp.5-6

**CKS price-impact regression: OLS of tick-mid-change on contemporaneous OFI, one fit per half-hour subsample**

Model (2): Delta P_k = beta * OFI_k + epsilon_k.  Estimated form (4): Delta P_k = alpha_hat_i + beta_hat_i * OFI_k + epsilon_hat_k, estimated by OLS separately in each half-hour interval [T_i, T_{i+1}] with White heteroskedasticity-consistent standard errors. 50 randomly chosen S&P 500 stocks, TAQ consolidated quotes/trades, April 2010, 21 trading days; 273 half-hour subsamples per stock, ~180 observations each (Delta t = 10 s). Grand-mean results (Table 2): alpha_hat = 0.0002, t(alpha_hat) = -0.02, beta_hat = 0.0398, t(beta_hat) = 11.47, R^2 = 65%; beta significant at 5% in 97% of samples, alpha in only 6%. Adding gamma_Q * OFI_k*|OFI_k| raises mean R^2 from 65% to 68% and gamma_Q is insignificant in most samples (significant in 9%).

*Source:* https://arxiv.org/pdf/1011.6402 (v3), Section 3.2 and Table 2, pp.8-11

**CKS depth scaling: beta_i = c / AD_i^lambda, with AD_i an explicit average of bid+ask queue sizes; empirically lambda ≈ 1**

Depth measure as printed:  AD_i = [ 1 / ( 2 * ( N(T_i) - N(T_{i-1}) - 1 ) ) ] * sum_{n = N(T_{i-1})+1}^{N(T_i)} ( q^B_n + q^A_n ).  (Note: the sum has N(T_i) - N(T_{i-1}) terms, so the printed '-1' in the denominator is a small inconsistency in the arXiv v3 text — reproduce it exactly or use the plain mean, the difference is O(1/n).)  Specification (3): beta_i = c / AD_i^lambda + nu_i.  Estimated in two steps: (5) log beta_hat_i = alpha_hat_{L,i} - lambda_hat * log AD_i + eps, then (6) beta_hat_i = alpha_hat_{M,i} + c_hat / AD_i^lambda_hat + eps, both OLS with Newey-West standard errors.  Table 3 grand mean: c_hat = 0.45, lambda_hat = 0.98, t(c_hat) = 20.74, t(lambda_hat) = 29.53, R^2 = 74%. 'the hypothesis {lambda = 1} cannot be rejected for 35 out of 50 stocks'. But c_hat = 0.45 differs from the stylized c = 1/2, and three bad fits (APOL, AZO, CME) are wide-spread / low-depth names.  Variance identity: var[Delta P_k]_i = beta_i^2 * var[OFI_k]_i + var[eps_k]_i (eq. 7).

*Source:* https://arxiv.org/pdf/1011.6402 (v3), Section 2.3 (p.6), Section 3.2 (p.12) and Table 3 (p.13)

**CKS: OFI beats trade imbalance roughly 2:1 in R^2, and trade imbalance is subsumed by OFI**

Trade imbalance TI_k = sum_{n=N(t_{k-1})+1}^{N(t_k)} b_n  -  sum_{n=N(t_{k-1})+1}^{N(t_k)} s_n, where b_n is the size of a buyer-initiated trade at the n-th quote (0 if none) and s_n the seller-initiated size. Three regressions (8a/8b/8c): OFI alone, TI alone, both. Table 4 grand means: OFI R^2 = 65%, TI R^2 = 32%, both = 65% (i.e. TI adds nothing). 'the average t-statistic of TI_k decreases by a factor of four and the coefficients theta_T,i are statistically significant in only 31% of subsamples.'  On volume: |Delta P_k| regressions give OFI R^2 = 58%, VOL^H R^2 = 23%, both 61%; the fitted power-law exponent H has grand mean 0.18 (sd 0.18).

*Source:* https://arxiv.org/pdf/1011.6402 (v3), Section 4.1 and Tables 4-5, pp.16-17, 22

**CKS warn the square-root price/volume law falls out of their linear model as a statistical artefact of aggregation**

Proposition 1: if events accumulate at rate Lambda, {e_i} are iid with finite variance sigma^2, and {w_i} iid with finite mean mu*pi, then sqrt(mu*pi)/sigma * OFI(T)/sqrt(VOL(T)) => N(0,1). Hence OFI(T) = xi * (sigma/sqrt(mu*pi)) * sqrt(VOL(T)) and substituting into (2) gives Delta P_k = theta_k * sqrt(VOL_k) + epsilon_k with theta_k a RANDOM normal slope. Their verdict verbatim: 'This additional randomness makes this model considerably less robust than (2) and we do not recommend to use it.'

*Source:* https://arxiv.org/pdf/1011.6402 (v3), Section 4.2, pp.19-20

**MLOFI (Xu, Gould & Howison): per-level e^m built from two three-case functions, kept as an M-vector, never summed**

Let b^m(tau_n), a^m(tau_n) be the level-m bid/ask price and r^m(tau_n), q^m(tau_n) the total size at the level-m bid / ask, all measured IMMEDIATELY AFTER the n-th order arrival or cancellation. Only populated price levels are counted (a^{m+1} need not be one tick above a^m). Then for m = 1..M:
  Delta W^m(tau_n) = r^m(tau_n)                        if b^m(tau_n) > b^m(tau_{n-1})
                   = r^m(tau_n) - r^m(tau_{n-1})       if b^m(tau_n) = b^m(tau_{n-1})
                   = -r^m(tau_{n-1})                   if b^m(tau_n) < b^m(tau_{n-1})
  Delta V^m(tau_n) = -q^m(tau_{n-1})                   if a^m(tau_n) > a^m(tau_{n-1})
                   = q^m(tau_n) - q^m(tau_{n-1})       if a^m(tau_n) = a^m(tau_{n-1})
                   = q^m(tau_n)                        if a^m(tau_n) < a^m(tau_{n-1})
  e^m(tau_n) = Delta W^m(tau_n) - Delta V^m(tau_n)
  MLOFI^m(t_{k-1}, t_k) = sum over {n : t_{k-1} < tau_n <= t_k} of e^m(tau_n)
MLOFI is the vector (MLOFI^1, ..., MLOFI^M). At M = 1 it is identical to CKS OFI. Critically: 'if an order-flow event causes a change of the bid-price b^1(tau_n), then the values of b^2, b^3, b^4 ... all change' — one event can move several components at once.

*Source:* https://arxiv.org/pdf/1907.06230v2, Sections 2.2.4 and 3.1, pp.5-9

**MLOFI regression is a single multivariate linear fit on the level vector, and OLS on it is unstable — Ridge is required**

Eq (16): Delta P(t_{i,k-1}, t_{i,k}) = alpha + sum_{m=1}^{M} beta^m * MLOFI^m(t_{i,k-1}, t_{i,k}) + epsilon, with M = 10. Data: LOBSTER Nasdaq, 6 stocks (AMZN, TSLA, NFLX, ORCL, CSCO, MU), 4 Jan 2016 - 30 Dec 2016, 10:00-15:30, I = 11 windows of Delta T = 30 min each subdivided into K = 180 windows of Delta t = 10 s -> 252*11 = 2772 regressions per stock.  Multicollinearity: pairwise sample correlations between MLOFI components stay above 0.5 even between level 1 and level 10 for small-tick stocks, and above 0.7 for ALL pairs for the other stocks; eigenvalue ratio lambda_i/lambda_1 ~ 0 for all i >= 2. OLS beta^m are therefore mostly insignificant (e.g. AMZN beta^1 = 3.16 with mean se 1.41, beta^5 = 1.13 with se 2.33).  Fix: Ridge, C(beta, lambda) = ||y - X beta||_2^2 + lambda ||beta||_2^2, lambda chosen by 5-fold CV over 50 log-spaced candidates in [1e-5, 1e5]. Fitted lambda_hat: AMZN 139.0, TSLA 54.3, NFLX 33.9, ORCL 3.2, CSCO 1.3, MU 2.0. Under Ridge nearly all beta^m become strongly significant.

*Source:* https://arxiv.org/pdf/1907.06230v2, Sections 4.2, 5.2-5.4, pp.13-20

**MLOFI headline result: deeper levels buy a large out-of-sample RMSE reduction, and the gain is far bigger for LARGE-tick instruments**

Table 10, out-of-sample RMSE in ticks for the M=10 MLOFI fit vs the M=1 OFI fit:
  OFI:          AMZN 9.72, TSLA 5.35, NFLX 2.03, ORCL 0.25, CSCO 0.19, MU 0.22
  MLOFI OLS:    8.53, 4.97, 1.49, 0.09, 0.06, 0.09
  MLOFI Ridge:  8.05, 4.53, 1.41, 0.08, 0.05, 0.08
  Improvement Ridge vs OFI: 17%, 15%, 31%, 68%, 74%, 64%
Abstract/summary wording: 'When using Ridge regression, the improvement is about 65-75% for large-tick stocks and about 15-30% for small-tick stocks.' Adjusted R^2 at M = 10: ~0.65 (OLS) / ~0.6 (Ridge) for AMZN and TSLA, ~0.9 / ~0.85 for NFLX, and 'very close to 1' for ORCL, CSCO and MU. R^2 increases monotonically with M for every stock, with the largest rate of increase at small M.  Overfitting signature: for AMZN and TSLA the OLS out-of-sample RMSE first falls then RISES for M larger than about 5; Ridge is monotone decreasing in M for all stocks.

*Source:* https://arxiv.org/pdf/1907.06230v2, Sections 5.5.1-5.5.2 and Table 10, pp.22-26

**MLOFI documents two tick-size degeneracies that cap the fit for small-tick (wide-spread) instruments**

(i) 'a new buy (respectively, sell) limit order arriving inside the spread will create the same MLOFI vector as a new buy (respectively, sell) limit order with the same size arriving at the level-1 bid-price ... The first such limit order arrival would create a change in mid-price, whereas the second such limit order would not.' (ii) 'a new buy ... limit order arriving one tick inside the bid-ask spread will create the same MLOFI vector as a new buy ... limit order arriving many ticks inside the bid-ask spread. However, these events would lead to considerably different changes in the mid-price.' Both map the same input vector to different outputs and 'may reduce the predictive power of the statistical relationship for small-tick stocks'. For large-tick stocks the spread is almost always 1 tick, so possibility (i) cannot occur at all.  Supporting split (Table 2, share of order-flow events deeper than the best quotes, by count): AMZN 53.10%, TSLA 49.61%, NFLX 53.42% vs ORCL 29.75%, CSCO 30.69%, MU 28.97%.

*Source:* https://arxiv.org/pdf/1907.06230v2, Sections 4.1 and 6.4, pp.11-12, 27-28

**Cont, Cucuringu & Zhang define per-level order flow with an explicit DEPTH NORMALISATION before any aggregation**

Per-level order flows (their eqs., Section 2.1), for stock i, level m, between consecutive book states n-1 and n:
  OF^{m,b}_{i,n} =  q^{m,b}_{i,n}                    if P^{m,b}_{i,n} > P^{m,b}_{i,n-1}
                 =  q^{m,b}_{i,n} - q^{m,b}_{i,n-1}  if equal
                 = -q^{m,b}_{i,n}                    if less
  OF^{m,a}_{i,n} = -q^{m,a}_{i,n}                    if P^{m,a}_{i,n} > P^{m,a}_{i,n-1}
                 =  q^{m,a}_{i,n} - q^{m,a}_{i,n-1}  if equal
                 =  q^{m,a}_{i,n}                    if less
Level-m OFI over (t-h, t]:  OFI^{m,h}_{i,t} = sum_{n = N(t-h)+1}^{N(t)} ( OF^{m,b}_{i,n} - OF^{m,a}_{i,n} ).
Scaled: ofi^{m,h}_{i,t} = OFI^{m,h}_{i,t} / Q^{M,h}_{i,t}, where
  Q^{M,h}_{i,t} = (1/M) * sum_{m=1}^{M} [ (1/(2*DeltaN(t))) * sum_{n = N(t-h)+1}^{N(t)} ( q^{m,b}_{i,n} + q^{m,a}_{i,n} ) ],  DeltaN(t) = N(t) - N(t-h).
Rationale given: 'Due to the intraday pattern in limit order depth, we use the average size to scale OFIs at the corresponding levels'. Note the SAME scalar Q^{M,h} (averaged across all M levels) divides every level — it is not a per-level normaliser. Dependent variable is the log mid return r^{(h)}_{i,t} = log(P_{i,t}/P_{i,t-h}) with P = (P^{1,b}+P^{1,a})/2, so ofi is unitless and the coefficient is in return units.

*Source:* https://arxiv.org/pdf/2112.13213v4, Section 2.1, pp.5-6

**Integrated OFI = the first principal component of the multi-level OFI vector, L1-normalised so the weights sum to 1**

ofi^{I,h}_{i,t} = ( w_1^T * ofi^{(h)}_{i,t} ) / ||w_1||_1, where ofi^{(h)}_{i,t} = (ofi^{1,h}_{i,t}, ..., ofi^{10,h}_{i,t})^T and w_1 is the first principal vector computed from historical data. M = 10. 'We further normalize the first principal component by dividing by its l_1 norm so that the weights of multi-level OFIs in constructing integrated OFIs sum to 1.' Justification: PC1 explains 89.06% (sd 6.12) of total variance of the 10-level vector (PC2 4.99%, PC3 2.28%); correlations between all levels exceed 0.75. The best-level OFI carries the SMALLEST weight in PC1 but the highest cross-stock standard deviation. A simple average across the 10 levels captures 85.07% vs PC1's 89.06%, and PC beats SA in every volume/volatility/spread quartile bucket.  Data: LOBSTER Nasdaq ITCH, top 100 S&P 500 by market cap, 2017-01-01 to 2019-12-31, non-overlapping 30-min estimation windows over 10:00-15:30, 1-minute returns and OFIs.

*Source:* https://arxiv.org/pdf/2112.13213v4, Section 2.1-2.2 and Appendix A, pp.6-8, 33-34

**The decisive number for preferring integrated OFI over a raw multi-level vector: out-of-sample R^2 PEAKS at 8 levels and then declines, while integrated OFI beats every raw variant**

Model PI^[m]: r^{(h)}_{i,t} = alpha^{[m]}_i + sum_{k=1}^{m} beta^{[m],k}_i * ofi^{k,(h)}_{i,t} + eps (OLS). Table B.1, averaged across stocks and windows:
  In-sample R^2 by m = 1..10:  71.16, 81.61, 85.07, 86.69, 87.66, 88.30, 88.74, 89.04, 89.24, 89.38
  Out-of-sample R^2 by m:      64.64, 75.81, 79.47, 81.13, 82.05, 82.65, 83.01, 83.16, 83.15, 83.11
'Out-of-sample R^2 reaches a peak at PI^[8].'  By contrast the integrated model PI^I (Table 5) reaches OS R^2 = 83.83 (sd 16.90) — higher than ANY PI^[m] — with a single regressor, vs PI^[1] best-level 64.64 (sd 21.82). In sample: PI^[1] 71.16 (13.80) vs PI^I 87.14 (9.16). Simple-average aggregation PI^SA gets OS R^2 82.34 (18.02), i.e. PCA weighting is worth ~1.5 R^2 points over a flat average.  Under a 1-minute (rather than 30-minute) refit cadence the same ordering holds: PI^[1] OS 59.67 vs PI^I OS 78.88.

*Source:* https://arxiv.org/pdf/2112.13213v4, Table 5 (p.16), Appendix A Table A.3 (p.34), Appendix B Table B.1 (p.35), Appendix D Table D.1 (p.38)

**CCZ also show OFI explanatory power rises sharply with the tick-to-price ratio — directly relevant to SR3 and the front UST contracts**

Table 6, out-of-sample R^2 by tick-to-price-ratio quartile [0%,25%) ... [75%,100%]:
  PI^[1] (best-level OFI): 44.38, 62.51, 77.55, 70.70
  PI^I  (integrated OFI):  68.14, 84.58, 88.14, 89.86
So the large-tick (high tick-to-price) bucket is where OFI works, and integrated OFI lifts the low-tick bucket by ~24 R^2 points. This mirrors Xu-Gould-Howison's large-tick vs small-tick split. SR3 and the short-end UST futures sit at the large-tick end of this axis (1 tick is a large fraction of a typical move), which is the favourable regime for both OFI and MLOFI.

*Source:* https://arxiv.org/pdf/2112.13213v4, Section 3.2.2 and Table 6, p.18

**CCZ's cross-impact result: once OFI is integrated over levels, cross-asset OFI adds essentially nothing contemporaneously, but lagged cross-asset OFI does forecast**

Contemporaneous in-sample R^2: best-level self PI^[1] 71.16 -> with LASSO cross terms CI^[1] 73.87 (+2.71); integrated self PI^I 87.14 -> CI^I 87.85 (+0.71). Out-of-sample: PI^[1] 64.64 -> CI^[1] 66.03 (+1.39), but PI^I 83.83 -> CI^I 83.62 (WORSE). Giacomini-White test: cross-impact beats price-impact for 91.0% (94.4%) of stocks at the 1% (5%) level using best-level OFI, but for only 28.1% (33.7%) using integrated OFI. Cross-impact coefficients selected by LASSO 17.34% of the time under CI^[1] vs 8.29% under CI^I, and are ~1/3 the magnitude. Separately, LAGGED cross-asset OFIs DO improve forecasting of future returns, with predictability decaying fast (annualised PnL falls sharply from 1-min to 3-min horizon and converges to the benchmark by 30 min).

*Source:* https://arxiv.org/pdf/2112.13213v4, Sections 3.2.1-3.2.2, 4.3-4.4, Tables 3-5, pp.11-12, 16-17, 27-28

**VPIN: equal-VOLUME buckets, absolute buy-sell imbalance normalised by total bucket volume**

Buckets are groups of trades each containing the same traded volume V, so (1/n) * sum_{tau=1}^{n} ( V^B_tau + V^S_tau ) = V, where n is the number of buckets in the support window. Then
  VPIN = [ sum_{tau=1}^{n} | V^S_tau - V^B_tau | ] / ( n * V )
equivalently written over bars j as VPIN = sum_j |V^b_j - V^s_j| / sum_j V_j. This estimates PIN = alpha*mu / (alpha*mu + 2*epsilon) because E|V^S - V^B| ~= alpha*mu and V = alpha*mu + 2*epsilon.  Free parameters actually needed in practice (LBNL/NOMAD study): nominal price of a bar (closing / unweighted mean / unweighted median / volume-weighted mean / volume-weighted median), BVC parameter nu, buckets per day beta, VPIN threshold tau, support window sigma (as a fraction of a day's buckets), event horizon eta. Bars per bucket fixed at 30. Best parameter sets found: beta = 200 (also 600, 1000), sigma = 0.5 or 1, eta = 0.1 days, tau = 0.99, giving false-positive rates alpha = 0.071-0.075 over 97 futures contracts, 2007-2012; a brute-force search cut average FPR from 20% to 7%, NOMAD optimisation to 2%.

*Source:* Song, Wu & Simon (LBNL), 'Parameter Analysis of the VPIN Metric', Sections 2-2.x, pp.6-9 — https://escholarship.org/content/qt2sr9m6gk/qt2sr9m6gk_noSplash_31c899ac57bd2a510b3277cbbacb36b5.pdf

**Bulk Volume Classification (BVC) is a CDF-weighted split of each bar's volume — an approximation that exists only because the true aggressor side was unavailable**

V^b_j = V_j * Z( delta_j / zeta ),  V^s_j = V_j - V^b_j,  where delta_j = P_j - P_{j-1} over a sequence of (volume or time) bars {P_j}, zeta = standard deviation of {delta_j}, and Z is the CDF of either the standard normal or a Student-t with nu degrees of freedom (nu = 0 denotes standard normal). The center is always taken as ZERO, not the sample mean. ELO (2011a) used the tick rule (TR-VPIN); ELO (2012a) used a normal-CDF BVC on time bars; ELO (2012b) used a Student-t CDF.  For an MBO engine on GLBX.MDP3 this entire construct is unnecessary: the exchange publishes the aggressor side, so V^B_tau and V^S_tau are computed exactly and VPIN is the true-classification (TTR-equivalent, in fact better than tick rule) version.

*Source:* LBNL Parameter Analysis of VPIN, Section 2 'Bulk Volume Classification', p.7 (restating Easley, Lopez de Prado & O'Hara 2012)

**VPIN is empirically contested, and every documented failure traces back to trade-CLASSIFICATION error — which MBO removes**

Andersen & Bondarenko (JFM 2014, 17:1-46; response CREATES RP 2013-42) report: (a) Chakrabarty, Pascual & Shkilko (2012), hundreds of NASDAQ INET stocks — 'the best BV specification misclassifies 20.3% of the trades, and TTR only 9.2%'; TTR-VPIN correctly identifies 91%-93% of toxic events vs 64%-70% for BV-VPIN. (b) AB (2013) on 5+ years of S&P 500 futures — 'at the volume bucket level, TTR misclassifies 2.3% of trades, while the one-minute time bar BV - favored by ELO (2012a) - misclassifies 8.3%'. (c) 'the BV errors are highly correlated with the volatility level, thus inflating the misclassification rate when markets grow turbulent' — so BV-VPIN spikes are a volatility artefact, not an imbalance signal. (d) On the flash crash itself: on 2010-05-06 TR-VPIN (BV-VPIN) reached a CDF level of 95.3% (78.7%) at 12:30; that value was surpassed on 71 (189) preceding days, i.e. 11.7% (31.2%) of the pre-crash sample. AB conclude VPIN's predictive content is 'fully subsumed by realized volatility'.

*Source:* Andersen & Bondarenko, 'Reflecting on the VPIN Dispute', CREATES RP 2013-42, Sections 3.1-3.4, pp.3-7 — https://repec.econ.au.dk/repec/creates/rp/13/rp13_42.pdf ; published as JFM 17:1-46 (2014)

**Trade-sign autocorrelation is a long-memory power law with a non-summable exponent**

Lillo & Farmer (2004): for the London Stock Exchange, the autocorrelation function of order signs 'decays roughly as tau^(-alpha) with alpha ~= 0.6, corresponding to a Hurst exponent H ~= 0.7'. Since alpha < 1 the ACF is not summable, i.e. genuine long memory — signed-flow bars are strongly serially correlated at ALL lags, so OLS standard errors on signed-flow regressors are badly understated unless HAC/Newey-West is used or the response is a contemporaneous (not predictive) change. Note the contrast with CKS, who report that mid-price change and OFI autocorrelations at their 10-second bar 'are small and quickly vanish' beyond ~10 seconds (their Figure 1 ACF for SLB) — the long memory lives in the SIGNS, not in the net imbalance.

*Source:* Lillo & Farmer, 'The Long Memory of the Efficient Market', arXiv:cond-mat/0311053 (abstract); autocorrelation contrast from arXiv:1011.6402 v3, Fig. 1, p.7

**Databento DBN gives the true aggressor side directly: `side` on a Trade record IS the aggressor side**

From the DBN Rust source (databento/dbn, rust/dbn/src/enums.rs), the Side enum doc comment reads verbatim: 'A side of the market. The side of the market for resting orders, or the side of the aggressor for trades.' Variants: Ask = b'A' — 'A sell order or sell aggressor in a trade.'; Bid = b'B' — 'A buy order or a buy aggressor in a trade.'; None = b'N' — 'No side specified by the original source.'
Action enum variants: Modify = b'M' 'An existing order was modified: price and/or size.'; Trade = b'T' 'An aggressing order traded. Does not affect the book.'; Fill = b'F' 'An existing order was filled. Does not affect the book.'; Cancel = b'C' 'An order was fully or partially cancelled.'; Add = b'A' 'A new order was added to the book.'; Clear = b'R' 'Reset the book; clear all orders for an instrument.'; None = b'N' 'Has no effect on the book, but may carry flags or other information.'
Consequence: signed volume is exactly +size if side == 'B' else -size on action == 'T'; Lee-Ready and the tick rule are never needed. Note that side == 'N' is a real, representable state and must be handled explicitly.

*Source:* https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/enums.rs (Side and Action enums)

**Pitfall — the OFI/price-change R^2 is partly tautological because OFI contains price-changing events**

CKS footnote 3 verbatim: 'We note that OFI_k includes the contributions of price-changing order book events, leading to a possible tautology in the regression (4). This problem is inherent to all price impact modeling, because the explanatory variables (events or trades) can directly cause price changes. To test that the high R^2 in our regressions is not due to this tautology, we estimated (4) on a subsample of stocks, excluding the price-changing events from OFI_k. With this change the R^2 declined, but remained in the 35%-60% region.' Practical implication: report both the full-OFI R^2 and the price-change-excluded R^2, otherwise the headline 65% is not a measure of predictive content.

*Source:* https://arxiv.org/pdf/1011.6402 (v3), Section 3.2 footnote 3, p.8

**Pitfall — sampling frequency: the fit rises with bar length within an asset, and cross-asset correlations collapse at high frequency (Epps effect)**

Within-asset (CKS): they repeated everything for Delta t from 10 quote updates (usually under half a second in their data) up to 10 minutes; 'The fit of our model generally increases with Delta t, but the rest of the results stays the same.' Time aggregation 'alleviates the issue of data discreteness' and 'mitigates the errors due to the trade matching algorithm.' Xu-Gould-Howison likewise found adjusted R^2 rising slightly as both Delta T (30->60 min) and Delta t (5->40 s) grew, varying by ~10% for AMZN.
Cross-asset (Epps effect): Toth & Kertesz, NYSE TAQ 1993-2003, define the characteristic time as the sampling scale at which the cross-correlation reaches 1 - e^{-1} of its asymptotic value. Measured (Table 1, seconds): CAT/DE 940 (1993), 620 (1997), 1320 (2000), 700 (2003); KO/PEP 920, 760, 1040, 800; MRK/JNJ 800, 420, 880, 1060 — i.e. roughly 7-22 minutes. For KO/PEP the correlation coefficient rises from about 0.05 at very short Delta t to an asymptote near 0.26, needing 'several hours' to converge. Crucially, a rise in trading frequency by a factor of ~5-10 over the decade did NOT measurably shorten the characteristic time, 'not even the changing tick sizes for the stocks ... alter the characteristic time of the effect'. Implication for SR3-vs-ZN cross-contract OFI: any correlation or cross-impact coefficient estimated at sub-minute bars is biased toward zero by construction, independent of how liquid the contracts are.

*Source:* https://arxiv.org/pdf/1011.6402 (v3) Section 3.1 p.8; https://arxiv.org/pdf/1907.06230v2 Section 4.2.1 p.13; Toth & Kertesz, 'The Epps effect revisited', https://arxiv.org/pdf/0704.1099 Sections 2.1-2.2 and Table 1, pp.4-7

**Pitfall — depth normalisation is not optional and the two literatures disagree on where to put it**

CKS put depth on the COEFFICIENT (beta_i = c / AD_i^lambda, lambda_hat = 0.98, so effectively beta ∝ 1/depth) and leave OFI in raw share units — which means beta is not comparable across time of day or across contracts, and the intraday seasonality is large: near the open 'depth is two times lower than it is on average', beta is 'two times higher near the market open than on average', and 'price impact is five times higher at the market open compared to the market close'. CCZ instead put depth on the REGRESSOR (ofi = OFI / Q^{M,h}, Q averaged over the same window and over all M levels) and regress log returns, making the coefficient stable and cross-sectionally poolable. For a futures panel spanning SR3 (huge queues, small ticks in yield terms) and the UST complex (very different queue sizes per contract), the CCZ convention is the one that lets you pool; the CKS convention forces a per-contract, per-half-hour refit. Also note CCZ's Q divides EVERY level by the same cross-level average, so relative level weighting is preserved and only the overall scale is removed.

*Source:* https://arxiv.org/pdf/1011.6402 (v3) Section 3.3 pp.14-15; https://arxiv.org/pdf/2112.13213v4 Section 2.1 eq. (3), p.6

**Pitfall — level indexing must follow POPULATED price levels, not price offsets, and one event can perturb several MLOFI components**

Xu-Gould-Howison footnote 3 verbatim: 'Observe that we only count populated price levels, so it does not necessarily follow that a^{m+1}(tau_n) is exactly one tick greater than a^m(tau_n).' And: 'if an order-flow event causes a change of the bid-price b^1(tau_n), then the values of b^2(tau_n), b^3(tau_n), b^4(tau_n) ... all change.' Their worked example (M = 3): a book with b^1 = $1.40 (size 10) and b^2 = $1.39 (size 10) receives a single buy limit order at $1.41 for 7; the resulting vector is MLOFI = (7, 10, 10), i.e. one order of size 7 produces 27 units of level-summed imbalance. This is exactly why summing MLOFI across levels is wrong and why the components are so collinear. For a numba implementation over MBO: rebuild the level ladder from populated prices at each event, and emit the full M-vector per event before bar aggregation.

*Source:* https://arxiv.org/pdf/1907.06230v2, Section 3.1-3.2 and footnote 3, pp.8-9


### secondary

**CME MDP 3.0 tag 5797-AggressorSide has an explicit 'no aggressor' value, and implied matching is a documented cause — this is the SR3 hazard**

SBE enum (from the machine-generated CME MDP 3.0 SBE v1.10 template mirror): AggressorSide : byte { NoValue = 255, NoAggressor = 0, Buy = 1, Sell = 2 }. CME's client-systems wiki states that tag 5797 'indicates if the trade had an aggressor and, if so, which side of the book it was on', and that when an Aggressor Side is defined (1 = Buy, 2 = Sell) the first Order Detail level related to the Summary Level represents the aggressor order. Documented no-aggressor scenarios: (i) 'When an aggressing customer order trades against implied orders, at least one Summary Level will not have a defined aggressor' — that Summary Level 'represents the customer orders that created the executed implied orders'; Order Details are sent only for the customer orders, and 'any unreported quantity represents the participating implied orders'; (ii) at Market Open, after a Pre-Open, or after a Pause; (iii) when the triggering order is a CME Globex-generated implied bid/offer. Also: 'An implied order is never the Aggressor in a trade during continuous trading', and Trade Summary (tag 269-MDEntryType = 2) 'is only disseminated when at least one actual (non-implied) order participates in the trade.' For SR3 — where calendar-spread-driven implied liquidity is a large share of outright activity — a non-trivial fraction of trade volume will therefore carry side = 'N' and must be handled by an explicit policy (drop, or split 50/50, or fall back to tick rule) rather than silently coerced to a side.

*Source:* CME Group Client Systems Wiki, 'MDP 3.0 - Trade Summary' and 'MDP 3.0 - Trade Summary Order Level Detail' (content retrieved via search extraction; Confluence pages truncate on direct fetch) — https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457418925/ and .../457225774/ ; enum values from https://github.com/Open-Markets-Initiative/CSharp.Hft.Structs/blob/master/Cme/Cme.Futures.Mdp3.Sbe.v1.10.cs


### Unresolved

- I could not retrieve the CME Group client-systems wiki pages verbatim — every direct WebFetch of the Confluence pages (both cmegroupclientsite.atlassian.net and www.cmegroup.com/confluence) returned truncated content or timed out. The AggressorSide=0 / implied-order facts above come from search-engine extraction of those pages plus a third-party mirror of the SBE template, so the exact CME wording is unverified. Someone should read 'MDP 3.0 - Trade Summary' and 'MDP 3.0 - Trade Summary Order Level Detail' in a browser before hard-coding the no-aggressor handling.

- Databento's own docs pages (schemas-and-data-formats/mbo, venues-and-datasets/glbx-mdp3, standards-and-conventions) all truncate under WebFetch. I got Side/Action semantics from the DBN Rust source instead, which is authoritative for the enum meaning, but I did NOT establish from primary docs: (a) whether GLBX.MDP3 MBO emits BOTH a T record (aggressor) and one or more F records (resting fills) for the same match — if it does, naive signed-volume summation over all T+F records double-counts, and the correct rule is 'sum T only'; (b) what fraction of GLBX MBO trade records carry side='N'; (c) the exact flags bitfield semantics (e.g. any implied/last-message flags) that would let you identify implied-driven matches programmatically.

- No measurement found of what share of SR3 or UST-futures trade volume arises from implied (calendar-spread) matching and therefore carries AggressorSide=0. This is the single most consequential unknown for a signed-flow measure on SR3, and it should be measured directly from the data rather than assumed.

- I could not obtain the ORIGINAL Easley, Lopez de Prado & O'Hara (2012, RFS 25(5):1457-1493) text. The VPIN and BVC equations above are restated from the LBNL parameter-analysis paper and cross-checked against the Andersen-Bondarenko critique; the notation (V^B_tau vs V^b_j, and whether the denominator is nV or sum_j V_j) may differ cosmetically from ELO's own printing.

- Every empirical result cited — CKS R^2=65%, MLOFI 65-75%/15-30%, CCZ 83.83 vs 64.64 — is from US EQUITIES (NYSE TAQ 2010, Nasdaq LOBSTER 2016 and 2017-2019). I found no primary study reporting OFI or MLOFI explanatory power for SR3, ZN, or any CME interest-rate futures. The large-tick/small-tick and tick-to-price-ratio results suggest the futures numbers should be at the favourable end, but that is an extrapolation, not a finding.

- Cont-Kukanov-Stoikov's AD_i formula as printed in arXiv v3 divides by 2*(N(T_i)-N(T_{i-1})-1) while the sum has N(T_i)-N(T_{i-1}) terms. I could not check the published JFEC version to see whether this '-1' is a typo or intentional; I report it as printed.

- I did not find a primary source quantifying how OFI behaves specifically under a COARSE tick lattice where a large fraction of bars have zero mid-price change (which is the SR3 back-of-strip regime). Xu-Gould-Howison's large-tick stocks reach adjusted R^2 near 1.0, which may be an artefact of the mid-price being almost deterministic given the queues rather than evidence of tradeable signal — no source addresses this directly.

- Lillo & Farmer's alpha ≈ 0.6 / H ≈ 0.7 is from the LSE. I did not retrieve per-market gamma values for CME futures, nor the Bouchaud et al. (2004) companion exponents, so the exact long-memory exponent to expect in SR3/ZN sign series is unestablished.


## arXiv 1909.09495 (Zotikov & Antonov, "CME Iceberg Order Detection and Prediction") and CME native/synthetic iceberg mechanics for an MDP 3.0 MBO engine over Databento DBN v3


### primary-source

**On CME Globex an iceberg is called a Display Quantity order; the refresh is generated by the exchange after a match event completes, and takes the LESSER of the display quantity or the order remainder.**

CME Globex Matching Algorithm Steps, verbatim: "A Display Quantity order is filled according to the working displayed quantity for its current timestamp. After a match event is complete, a Display Quantity order is refreshed with the lesser quantity of either: 1. The Display Quantity of the Order. 2. The remainder of the order if equal to or less than the Display Quantity." Order-entry side uses iLink tag 1138-DisplayQty (FIX tag 210-MaxShow).

*Source:* https://cmegroupclientsite.atlassian.net/wiki/display/EPICSANDBOX/CME+Globex+Matching+Algorithm+Steps

**The refreshed native iceberg slice LOSES queue priority — it is placed at the END of the queue at that price level.**

Verbatim: "the Display Quantity order's priority is refreshed to be the lowest of the remaining orders at the price level (order is placed at the end of the queue)." Same page lists the three modify events that forfeit timestamp priority: "Increase of working quantity of the order", "Change of price", "Change of account number". FIFO defined as: "During FIFO, resting orders are matched in timestamp order only." Corroborated by the CME Display Quantity overview: the quantity "will be reinstated as this value at the bottom of the order book until the entire quantity is depleted."

*Source:* https://cmegroupclientsite.atlassian.net/wiki/display/EPICSANDBOX/CME+Globex+Matching+Algorithm+Steps

**DBN v3 Action enum letter codes and flag bits, as consumed by an MBO book builder.**

From databento/dbn rust/dbn/src/enums.rs, verbatim doc comments: A=Add "A new order was added to the book."; C=Cancel "An order was fully or partially cancelled."; M=Modify "An existing order was modified: price and/or size."; R=Clear "Reset the book; clear all orders for an instrument."; T=Trade "An aggressing order traded. Does not affect the book."; F=Fill "An existing order was filled. Does not affect the book."; N=None "Has no effect on the book, but may carry flags or other information." Flags: LAST 0x80 "Indicates it's the last record in the event from the venue for a given instrument_id"; TOB 0x40; SNAPSHOT 0x20; MBP 0x10; BAD_TS_RECV 0x08; MAYBE_BAD_BOOK 0x04. The iceberg refresh therefore surfaces as action='M' on an unchanged order_id with size restored.

*Source:* https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/enums.rs and https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/flags.rs

**PAPER Q2 — native detection rule: flag an order as an iceberg on EITHER (a) a trade whose volume exceeds the order's current resting volume, OR (b) the order being fully traded and then modified back to non-zero volume.**

Paper §1.2/§3.1 verbatim: "All new tranches are submitted as modifications of the initial order; this means that the original order ID is preserved throughout the whole lifetime of the iceberg"; "when the iceberg has its displayed quantity refreshed (by means of an update action), the refreshed order will have the same order ID as the original order"; "any trades involving the iceberg order will indicate the total volume of trade, including the hidden part of the iceberg". §3.1: "once a trade larger than the resting volume is detected, or the order is fully traded but then modified to have non-zero volume again, then the order is marked as an iceberg." No time window and no volume threshold — it is an exact structural rule on a single order_id. Detection is described as "unambiguous and accurate".

*Source:* https://arxiv.org/pdf/1909.09495 §1.2, §3.1

**PAPER Q2 — the three tracked quantities and the peak-size solver, with the divisor formula and the mod-based disambiguation.**

V_total = sum of all traded volume V_T ("which may exceed the sum of limit and/or update volumes") plus any explicitly deleted volume V_D. V_R = last modify action volume V_M. V_peak: if the iceberg enters the book directly as a limit order, V_peak = V_L. If trades precede placement, V_L = V_peak − V_T mod V_peak, so V_T − k·V_peak = V_peak − V_L for k in N_0, giving V_peak = (V_T+V_L)/(k+1) = (V_T+V_L)/d, d = 1,…,V_T+V_L, V_peak ∈ {n ∈ N : n ≥ V_L}. If multiple admissible V_peak survive: (i) if the first tranche traded for exactly the resting volume, the following update message identifies V_peak unambiguously; (ii) if trade volume > resting volume, keep only values satisfying V_peak = V_M + (V_T − V_R) mod V*_peak. Worked example (Table 2): total volume 43, 4 tranches, peaks 9, 9, 9 and 7, display quantity 9. Full grammar is the FSM in Fig 1 over actions L(new), M(update), T(own trade), T_A(affected trade), D(delete), with states start / initial trade / first tranche / first tranche traded / first tranche partially traded / ordinary / next tranche / next tranche traded / next tranche partially traded / complete / cancelled.

*Source:* https://arxiv.org/pdf/1909.09495 §3.1, Table 2, Fig 1

**PAPER Q2 caveat that breaks a naive FSM: CME does not disseminate price adjustments that move an order to the top of the book, so a resting iceberg can re-aggress invisibly.**

Verbatim: "all price adjustments which move the order to the top of the book are not disseminated by the exchange, meaning that even after the placement the order can again act as an aggressive order and initiate a trade." Also: an iceberg "enters the book as a new limit order, possibly following a sequence of trades", and "each trade corresponds to one trade summary message, in which case it is followed by an update action... If more than one trade messages are seen before the next update action, then this should be accounted for."

*Source:* https://arxiv.org/pdf/1909.09495 §3.1

**PAPER Q3 — synthetic detection rule: a new limit order at the SAME price and SAME volume as the initial tranche arriving within dt after the previous tranche's trade+delete. dt = 0.3 seconds in their run.**

Assumptions stated verbatim: "we assume that new tranches arrive to the same price level as the initial tranche, and their volumes are expected to be equal to the initial tranche volume as well, which is taken to be the iceberg display quantity"; "we only detect orders that have constant peak size". Explicit blind spots: varying peak sizes or prices are undetectable, and "if the iceberg is not a multiple of the display quantity, the last tranche will be smaller than all the previous tranches in volume, hence its detection using the current approach does not seem to be possible." Completion: "If a tranche is executed, but no refill orders follow within dt, the iceberg is considered complete. If a tranche is placed and later cancelled, the whole iceberg is considered cancelled (incomplete)." Ambiguity: "Our very strong assumption is that the next tranche arrives faster than any other new limit order, so for each tranche there is only one child"; simultaneous same-price/same-size deletes produce a TREE of possible tranches and "Every path from all leaves to the root (a chain) is a possible iceberg." Chain aggregation options: V^all (average total volume of all chains), V^unique (average over chains of unique length), V^longest (total volume of the longest chain). Minimum tranches per iceberg is a tunable parameter, default 3.

*Source:* https://arxiv.org/pdf/1909.09495 §3.2, §7, Table 3, Fig 2

**PAPER Q4 — Kaplan-Meier: the 'survival time' is accumulated iceberg VOLUME (not clock time), and the censoring event is CANCELLATION BEFORE FULL EXECUTION.**

Verbatim: "accumulated iceberg volumes play the role of time to event durations, so the task is to estimate the distribution of V_p for each p under random right-censoring." Censoring arises because "a significant amount of synthetic icebergs are cancelled before being completely executed. Hence for some icebergs only a lower bound on their total volume is known: for the i-th iceberg, v_i ≥ c_i, c_i ∈ N." Estimator: with u_1,…,u_K the unique volumes of all detected icebergs sorted ascending, d_j = number of COMPLETE icebergs of volume u_j, and n_j = "the total number of both complete and incomplete icebergs of volumes u_j,…,u_K", the MLE is Ŝ_p(v) = Π_{j: u_j ≥ v} (1 − d_j/n_j). Motivation for using KM even for native (where cancellation is rare): "The proportion of cancelled native icebergs is much smaller, and, in fact, could be disregarded... Nevertheless, we would like to utilise the same approach to simplify the analysis."

*Source:* https://arxiv.org/pdf/1909.09495 §4.1

**PAPER Q4 — the weighted KM variant for synthetic icebergs uses chain weights w = 1/h_i, and the pmf must be renormalised.**

Given the i-th tranche tree with h_i chains of unique length, weights are w_{i,ℓ} = 1/h_i, ℓ ∈ 1:h_i — "A weight can be also interpreted as a probability of the total iceberg volume being equal to the accumulated tranche chain volume... we assign uniform probabilities because there is no prior knowledge that would affect our preference for a particular chain." Weighted counts: d̃_j = Σ_{i∈C} Σ_{ℓ∈H_i} w_{i,ℓ} where H_i = {ℓ : v_{i,ℓ} = u_j} and C indexes complete icebergs; ñ_j analogously. Then Ŝ_p(u_j) = Π_{k=1..j} (1 − d̃_k/ñ_k). Degenerate case: "if d_K = 0, then S_p(u_K) ≠ 0 and the probabilities do not sum up to 1. This is fixed trivially by normalising the probabilities." When each tree has one chain, all weights are 1 and d̃_j = d_j, ñ_j = n_j.

*Source:* https://arxiv.org/pdf/1909.09495 §4.2

**PAPER Q4 — turning the fitted curve into a size estimate: restrict the pmf to a constrained optimisation space above the volume seen so far, then take conditional mean / median / k-th mode. Native and synthetic use DIFFERENT constraints (strict > vs ≥).**

NATIVE: with v_r the accumulated volume up to but NOT including tranche r, the space is 𝒱_p = {u_j : u_j > v_r}_{j=1..K_p}. mean: v̂^mean = (Σ_{u∈𝒱_p} f̂_p(u))^-1 Σ_{u∈𝒱_p} u·f̂_p(u), "rounded to the nearest integer"; median: v̂^median = max{u_J : Σ_{j=1..J} f̂_p(u_j) ≤ 0.5, u_j ∈ 𝒱_p}; k-best-mode: v̂^mode(k) = u_(k) where u_(1),…,u_(|𝒱_p|) are ordered by f̂_p(u_(1)) ≥ … ≥ f̂_p(u_(|𝒱_p|)), "Tied volumes are taken in ascending order." SYNTHETIC: with v'_{ℓ,r} the accumulated volume for chain ℓ up to AND INCLUDING tranche r, v̂^mode_ℓ = argmax_{u∈𝒱'_p} f̂_p(u), 𝒱'_p = {u_j : u_j ≥ v'_{ℓ,r}}; the per-chain prediction is then aggregated across chains as V̂^all, V̂^unique or V̂^longest. Prediction begins after the iceberg becomes 'active' (native) or after a default of 3 tranches (synthetic).

*Source:* https://arxiv.org/pdf/1909.09495 §5.1, §5.2

**PAPER Q5 — validation was on ONE instrument (ESU19, E-mini S&P 500) over ONE training day and ONE out-of-sample day. No interest-rate product was tested.**

Available data: "full order depth (FOD) LOB log of a September E-Mini S&P 500 futures contract... under the ticker symbol ESU19, for the period from 2019-06-14, 11:00:00 CDT to 2019-06-21, 16:00:00 CDT." TRAINING (§7): "from 2019-06-18, roughly 16:45:00 CDT, to 2019-06-19, 16:00:00 CDT; for synthetic icebergs, dt was set to 0.3 seconds." OUT-OF-SAMPLE (§7.3): "from 2019-06-19 16:45:00 CDT to 2019-06-20 16:45:00 CDT." Note the two windows end at DIFFERENT clock times (16:00 train vs 16:45 OOS) — verified by direct render of p.10 and p.14. Authors' own scope caveat: "An extensive study of the model robustness is required to claim its applicability on other instruments and time spans; we leave this out of the scope of this article." Source log fields (Table 1): Time (millisecond resolution), Order ID (12-digit), Side (B/S), Action (Limit/Modify/Delete/Trade), Price, Volume, plus an "Affected" passive order ID on trade records.

*Source:* https://arxiv.org/pdf/1909.09495 §1.1, §7, §7.3, Table 1

**PAPER Q5 — headline hidden-volume shares: native icebergs = 4% of all traded volume but only 0.06% of orders by number; synthetic = 3.3% to 14.3% of traded volume depending on the minimum-tranche parameter.**

Verbatim: "We estimate that 4% of all traded volume is contributed by native icebergs, while the volume contributed by synthetic icebergs ranges from 3.3 to 14.3%, depending on the minimum number of tranches." And: "usually there is no hidden depth, but when it is present, it is substantial. This is especially true for native icebergs, that constitute 0.06% of all orders by number, but 4% by volume." Denominator choice matters: "We divide the total volume of all iceberg orders by the total traded volume of all orders... and not the total daily limit order volume." Literature range cited for comparison: 2% (Fleming et al. 2018) to 52% (Moro et al. 2009). More than half of all synthetic icebergs are cancelled before completion; native cancellation is much rarer. Median total volume is identical for native and synthetic at 6. Native order sizes cluster on multiples of 5 (15, 25, 50, 100) — "indicative of a human bias".

*Source:* https://arxiv.org/pdf/1909.09495 §7.2, §7.1

**PAPER Q5 — headline predictive accuracy: synthetic ≈70% accuracy with MAE 1.78 contracts; native best case (mode(3)) 90.21% accuracy but MAE 61.79 contracts (63.92% of mean total volume).**

Synthetic (Table 4) — All-chains average: Accuracy 68.95%, Precision 52.66%, Recall 41.47%, F1 46.40%, MAE 1.78 (22.55%), RMSE 3.94 (49.85%). Longest chain: Accuracy 67.54%, Precision 49.95%, Recall 83.67%, F1 62.56%, MAE 2.15 (24.94%), RMSE 4.52 (52.37%). Native (Table 6): Mean — Acc 82.69%, Prec 33.33%, Rec 4.83%, F1 8.43%, MAE 94.60 (97.87%), RMSE 217.08 (224.58%); Median — Acc 58.31%, Prec 19.22%, Rec 47.59%, F1 27.38%, MAE 89.40 (92.49%), RMSE 234.45 (242.55%); Mode(1) — Acc 72.55%, Prec 26%, Rec 35.86%, F1 30.14%, MAE 99.66 (103.14%), RMSE 239.22 (247.49%); Mode(2) — Acc 88.15%, Prec 73.03%, Rec 44.83%, F1 55.56%, MAE 69.66 (72.07%), RMSE 204.35 (211.41%); Mode(3) — Acc 90.21%, Prec 83.91%, Rec 50.34%, F1 62.93%, MAE 61.79 (63.92%), RMSE 190.43 (197.01%). Percentages in parentheses are relative to mean total volume. Authors' own deflation of the accuracy figure: "high accuracy values are mainly contributed by a large number of true negatives." 33 native icebergs with non-unique peak size were filtered out, "leaving 98% of the initial amount".

*Source:* https://arxiv.org/pdf/1909.09495 Tables 4, 5, 6, 7, §7.3

**PAPER Q5 — latency reality check: most tranches arrive under one second after the previous one, and a large share arrive with zero measured delay (38.94% native, 4.71% synthetic).**

Verbatim: "Zero values are discarded for the purpose of drawing the plot, but they amount to 4.71% and 38.94% of all values for synthetic and native icebergs, correspondingly. If the initial tranche is not considered, then it can be seen that the majority of tranches arrive less than one second after the previous tranche (before being traded). This suggests that the proposed detection algorithm is more suitable as an input to other trading algorithms, rather than a signal to a day trader, who would not be able to react sufficiently fast." Footnote on the synthetic zeros: "The fact that we observe zero delays for synthetic icebergs may be attributed to an insufficient accuracy of time records (millisecond resolution)." Note that the paper's source log is millisecond-resolution, whereas DBN carries nanosecond ts_event/ts_recv — so the zero-delay share should be far lower on Databento data.

*Source:* https://arxiv.org/pdf/1909.09495 §7.2, Fig 11

**PAPER Q6 — the paper makes NO product-eligibility statement; it says only that "CME supports two types of iceberg orders: native and synthetic". ESU19 was a data-availability choice, not a claim about scope.**

§1.2 opens "CME supports two types of iceberg orders: native and synthetic (CME, 2019a)" with no product list, no exclusions, and no minimum-size or ratio rules anywhere in the text. Nothing in the paper speaks to SR3 or to the Treasury futures complex.

*Source:* https://arxiv.org/pdf/1909.09495 §1.2


### secondary

**The native iceberg refresh keeps the SAME OrderID but gets a NEW priority ID; synthetic (ISV) refreshes get a NEW OrderID. This is the single discriminator between native and synthetic in MBO.**

CME MBO FAQ: "When CME Group-held iceberg orders (referred to as native icebergs) have displayed quantity refreshed, the refreshed order will have the same OrderID as the original order." And: "PriorityID may change if order modified or refreshed, OrderID is consistent for the life of the order." For ISV-managed icebergs: "Refreshed quantities from these systems are treated as new orders to the exchange and receive a new OrderID." Wire fields: OrderID = tag 37; priority = tag 37707-MDOrderPriority (book sorted by tag 270-MDEntryPx then tag 37707); action = tag 279-MDUpdateAction or tag 37708-OrderUpdateAction (New/Change/Delete).

*Source:* https://www.cmegroup.com/articles/faqs/market-by-order-mbo.html (reached via search-result summaries; direct WebFetch timed out 3x)

**IMPLEMENTATION TRAP: Databento omits MDOrderPriority from normalized MBO, so the priority reset caused by an iceberg refresh is NOT directly observable in DBN — and the recommended ts_event substitute is explicitly wrong for interest rate options and LMM instruments.**

Databento states it "currently leaves out MDOrderPriority from normalized MBO messages because this behavior is CME-specific and most other venues adopt ITCH-based behavior where ordering is based on timestamp", and recommends inferring priority from ts_event. Critical caveat: ts_event "serves the same purpose as MDOrderPriority for all instruments except for interest rate options and instruments where there's a LMM". Consequence for this engine: DBN order_id is the stable CME OrderID (tag 37), so the same-order-id native-detection rule holds; but queue-position modelling for SR3 options / LMM'd IR products cannot rely on ts_event ordering.

*Source:* https://databento.com/docs/venues-and-datasets/glbx-mdp3 (via search-result summary; direct fetch truncated)

**CME Q6 — Display Quantity is available for ALL order types on futures products; only options-on-futures carry exclusions. SOFR futures carry a maximum display ratio of 1:60.**

CME Display Quantity Order Overview: "Display quantity is available for all order types for futures products. For options on futures products, display quantity is not supported for stop order with protection and stop-limit order types." Product-specific ratio: "In CME Secured Overnight Financing Rate (SOFR) futures products, the maximum display ratio is 1:60" — i.e. total order quantity may be at most 60x the displayed quantity, which bounds the per-order hidden size an SR3 detector can ever infer. Minimum: "If an order is submitted with the display quantity lower than the instrument's minimum order quantity, the order will be rejected." Modify restriction: "A resting display quantity order (tag 1138-DisplayQty>0) cannot be modified to a non-display quantity (tag 1138-DisplayQty=0), and vice-versa" — note this specific quote surfaced from EBS Market wiki pages, so treat its applicability to Globex futures as unconfirmed. TOP interaction: "A Display Quantity order can become TOP only at the time of entry, and only the initial display quantity of the order is considered for TOP status."

*Source:* https://www.cmegroup.com/education/display-quantity-order-overview.html (reached via search-result summaries; direct WebFetch timed out 3x)

**MDP 3.0 event framing: MatchEventIndicator is an 8-bit boolean bitmap whose most significant bit (bit 7) marks the last message of a Globex event; in DBN this surfaces as the F_LAST (0x80) flag.**

"MatchEventIndicator is a bitmap field of eight Boolean type indicators reflecting the end of updates for a given CME Globex Event", with bit 7 (MSB) representing the last message for a given event. CME also notes "The MBP update contains the end of event update, and in scenarios where price updates are outside the MBP book, the MBO update receives the end of event update", and that "A single Trade Summary message can be split across multiple packets if the total number of related entries cannot be fit in a single UDP packet." DBN's LAST flag (0x80) is documented as "Indicates it's the last record in the event from the venue for a given instrument_id", giving the consumer an event boundary to group trade+refresh records against.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/display/EPICSANDBOX/MDP+3.0+-+Market+Data+Incremental+Refresh+-+MBOFD (via search-result summary); DBN flag verbatim from https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/flags.rs


### inferred

**Evidence on refresh-vs-trade packet co-location is suggestive but NOT specified: CME says the refresh happens after the match event completes, and the paper's own trace shows Trade and Modify at the same millisecond.**

CME wording is "After a match event is complete, a Display Quantity order is refreshed..." which orders the refresh after the match but does not state whether it is disseminated inside the same MatchEventIndicator event or a subsequent one. The paper's Table 2 trace shows every Trade and its following Modify sharing an identical millisecond stamp (e.g. 14:05:33.416 for the first 18 records), which is consistent with same-event dissemination but is millisecond-resolution evidence, not a specification statement. An implementation should group on the F_LAST event boundary rather than on timestamp equality.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/display/EPICSANDBOX/CME+Globex+Matching+Algorithm+Steps and https://arxiv.org/pdf/1909.09495 Table 2


### Unresolved

- Whether the native iceberg refresh (Modify) is disseminated inside the SAME MDP 3.0 match event / MatchEventIndicator group as the Trade Summary that consumed the previous slice, or in a subsequent event. CME states only that the refresh occurs 'After a match event is complete'. The paper's Table 2 shows same-millisecond Trade->Modify pairs, which is evidence but not a spec statement. Needs verification against the MDP 3.0 - Market by Order - Book Management wiki page, which truncated on every fetch attempt.

- Explicit confirmation that Databento's DBN order_id for GLBX.MDP3 is sourced from CME tag 37-OrderID (as opposed to tag 37707-MDOrderPriority). Strongly implied — Databento documents that it deliberately OMITS MDOrderPriority from normalized MBO and tells users to infer priority from ts_event — but I never rendered the venue page directly to read the field-mapping table verbatim. The whole native-detection rule keys on order_id stability across refresh, so this is worth confirming empirically against a real DBN file before building on it.

- Maximum display ratio and any minimum display quantity for the US Treasury futures complex (ZT, ZF, ZN, TN, ZB, UB). Only the SOFR futures figure (1:60) was found. Whether Treasury futures carry a different ratio, the same ratio, or none at all is not established.

- Whether the SOFR 1:60 'maximum display ratio' applies to SR3 (Three-Month SOFR) specifically or to all CME SOFR futures products including SR1 (One-Month SOFR), and whether the same rule extends to SOFR options.

- Direct verbatim text of the CME MBO FAQ and the CME Display Quantity Order Overview pages. Both timed out on three separate direct WebFetch attempts; their content was reconstructed from search-result summaries, so those quotes are marked 'secondary' rather than 'primary-source'.

- Whether the paper's detection rules were ever validated on any instrument other than ESU19. The authors explicitly decline to claim cross-instrument applicability, so transfer of the 4% native hidden-volume figure or the dt=0.3s synthetic threshold to SR3 or the UST complex is unsupported — the tick size, queue depth, and matching algorithm all differ, and CME interest-rate products can use non-FIFO allocation with LMM, which the paper never contemplates.

- The exact list of CME products that use a non-FIFO matching algorithm (pro-rata / allocation / LMM) among the target instruments, which matters because the paper's FSM implicitly assumes FIFO price-time and because Databento's ts_event priority substitute is documented as invalid for LMM instruments.

- Precise iceberg counts underlying Figure 5 (complete vs cancelled, native vs synthetic). These are only presented as bar charts with log-ish axes; the approximate magnitudes readable from the figure (~70k synthetic / ~1.7k native) are eyeballed and deliberately excluded from the findings above.


## Databento DBN MBO schema semantics and GLBX.MDP3 specifics for a Python/numba MBO analytics engine over GLBX.MDP3 mbo (DBN v3), consumed for SR3 and UST futures microstructure research


### primary-source

**BREAKING TODAY (2026-08-08): CME MBO normalization changes how F_LAST is delivered — it moves off the final book update onto a standalone action='N' record — and is applied RETROACTIVELY to the full historical dataset.**

Databento blog 'Upcoming changes to CME data normalization', dated July 07, 2026. Exact wording: "Currently, for events spanning multiple packets, we buffer all MBO records until the packet containing the last event is processed. F_LAST is then set on the final record for each instrument to mark the end of the event. This delays earlier records in the event." ... "To reduce latency, records will be published immediately after each packet is processed rather than being buffered until the event is complete. As a result, the final book update will no longer contain F_LAST. Instead, the end of the event for each instrument is marked by a new, separate record with F_LAST and action='N' (None)." ... "Note the additional record with F_LAST set (flags=128 corresponds to the F_LAST flag)." Rollout timeline verbatim: "2026-07-07: Data with the new normalization is available in the preview environment" / "2026-08-08: Data with the new normalization will be available in production from the live and historical APIs. End of the live preview environment." And: "The new normalization will replace the current normalization and apply to both live data and the full historical dataset retroactively." Preview gateways were hist-preview.databento.com (historical) and glbx-mdp3.preview.lsg.databento.com:13000 (live). CONSEQUENCE for the engine: an event terminator must be detected as flags & F_LAST regardless of action, and action='N' records must NOT be treated as no-ops to be filtered out. Files downloaded before vs after today can carry different shapes for the same historical date. Other four changes in the same release: per-leg definition records; price limits in statistics schema; implied matching status in status schema; new FX spot instrument_class=X.

*Source:* https://databento.com/blog/cme-normalization-changes-2026-07

**MBO record layout (DBN MboMsg): 14 32-bit words, exact field set and types.**

From dbn Rust source rust/dbn/src/record.rs (struct MboMsg, #[repr(C)], #[dbn_record(rtype::MBO)]) and the docs field table. Fields in struct order: hd (RecordHeader: length u8 [record length in 32-bit words], rtype u8, publisher_id u16, instrument_id u32, ts_event u64), order_id u64, price i64, size u32, flags FlagSet(u8), channel_id u8, action c_char, side c_char, ts_recv u64, ts_in_delta i32, sequence u32. rtype is ALWAYS 160 (0xA0) for MBO. price fixed-point: "every 1 unit corresponds to 1e-9, i.e. 1/1,000,000,000 or 0.000000001". order_id = "The order ID assigned by the venue"; sequence = "The message sequence number assigned at the venue"; channel_id = "The channel ID assigned by Databento as an incrementing integer starting at zero". ts_recv is the INDEX timestamp (#[dbn(index_ts)]) — the primary sort key. In the observed Debug output every GLBX MboMsg has length: 14 (i.e. 56 bytes). UNDEF_TIMESTAMP = UINT64_MAX = 18446744073709551615; UNDEF_PRICE appears in clear records.

*Source:* https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/record.rs and https://databento.com/docs/schemas-and-data-formats/mbo

**Action codes: exactly seven — A, M, C, R, T, F, N — with these exact meanings.**

Databento 'Common fields, enums and types' Action table verbatim (Name | Value | Action): Add | A | "Insert a new order into the book."; Modify | M | "Change an order's price and/or size."; Cancel | C | "Fully or partially cancel an order from the book."; Clear | R | "Remove all resting orders for the instrument."; Trade | T | "An aggressing order traded. Does not affect the book."; Fill | F | "A resting order was filled. Does not affect the book."; None | N | "No action: does not affect the book, but may carry flags or other information." The dbn Rust enum Action (repr as ASCII byte) agrees, with None = b'N' as #[default]: Modify=b'M' "An existing order was modified: price and/or size"; Trade=b'T'; Fill=b'F' "An existing order was filled. Does not affect the book"; Cancel=b'C' "An order was fully or partially cancelled"; Add=b'A'; Clear=b'R' "Reset the book; clear all orders for an instrument"; None=b'N' "Has no effect on the book, but may carry flags or other information." There are no other action codes. Side codes: A = Ask (sell order or sell aggressor), B = Bid (buy order or buy aggressor), N = None/no side specified.

*Source:* https://databento.com/docs/standards-and-conventions/common-fields-enums-types and https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/enums.rs

**On GLBX, T and F never mutate the book; the book decrement arrives as a separate MBOFD-derived Modify/Cancel. Trade/Fill pairing has a documented asymmetry.**

Databento GLBX.MDP3 page, MBO normalization, verbatim: "Records in the MBO schema with Add, Modify, and Cancel actions are normalized from Market Data Incremental Refresh - MBOFD, and records with Trade and Fill actions are normalized from Market Data Incremental Refresh - Trade Summary messages, and records with the cleaR action are normalized from Market Data Incremental Refresh - Channel Reset messages." ... "Each CME MDP 3.0 Market Data Incremental Refresh - Trade Summary message from CME contains two repeating groups: a set of trade summaries, followed by a set of order ID entries. Each trade summary in the message is normalized into one Trade record. If there is a defined aggressor for the trade, its corresponding order ID entry from the second set is used to populate the order_id field. This commonly happens when an incoming order partially executes, leaving the remaining quantity to rest on the book." ... "Following each Trade record, the remaining (passive) order ID entries are normalized into Fill records. These records correspond to resting orders in the order book, but do not modify the orders." ... "If the aggressing order existed on the book, then a Fill record will be emitted for it. This can happen if a resting order was modified to cross the book. If the aggressing order did not already exist on the book then its Fill record is suppressed, however its order ID is still reported in the Trade record as described above." ENGINE CONSEQUENCE: never decrement resting size on T or F; the size change comes from the paired M/C record. A T record's order_id identifies the AGGRESSOR (when one is defined), not a resting order.

*Source:* https://databento.com/docs/venues-and-datasets/glbx-mdp3

**Flags bitfield: exact values, including two the question did not name (F_PUBLISHER_SPECIFIC = 2 and a reserved bit 0 = 1).**

Databento flags table verbatim (Flag | Value | Decimal | Description): F_LAST | 1 << 7 | 128 | "Marks the last record in a single event for a given instrument_id."; F_TOB | 1 << 6 | 64 | "Top-of-book message, not an individual order."; F_SNAPSHOT | 1 << 5 | 32 | "Message sourced from a replay, such as a snapshot server."; F_MBP | 1 << 4 | 16 | "Aggregated price level message, not an individual order."; F_BAD_TS_RECV | 1 << 3 | 8 | "The ts_recv value is inaccurate due to clock issues or packet reordering."; F_MAYBE_BAD_BOOK | 1 << 2 | 4 | "An unrecoverable gap was detected in the channel."; F_PUBLISHER_SPECIFIC | 1 << 1 | 2 | "Semantics depend on the publisher_id. Refer to the relevant dataset supplement for more details."; (unnamed) | 1 << 0 | 1 | "Reserved for internal use can safely be ignored. May be set or unset." Identical constants in dbn Rust flags.rs: LAST=1<<7, TOB=1<<6, SNAPSHOT=1<<5, MBP=1<<4, BAD_TS_RECV=1<<3, MAYBE_BAD_BOOK=1<<2, PUBLISHER_SPECIFIC=1<<1. Databento's own warning, verbatim: "Comparing the field with a single flag's value, such as flags == 128 to check for F_LAST, will miss any record that has other flags set too." Test with bitwise AND, never equality. For an MBO consumer, F_TOB (64) and F_MBP (16) should never be set (they mark aggregated/TOB records in other schemas).

*Source:* https://databento.com/docs/standards-and-conventions/common-fields-enums-types and https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/flags.rs

**Observed GLBX flag COMBINATIONS differ between historical batch and live: historical shows 40/168 (no bit 1), live shows 130/170 (bit 1 set).**

From the worked examples on Databento's MBO snapshot page. Historical batch (GLBX.MDP3, publisher GlbxMdp3Glbx): snapshot body records carry "flags: SNAPSHOT | BAD_TS_RECV (40)" = 32+8; the final snapshot record carries "flags: LAST | SNAPSHOT | BAD_TS_RECV (168)" = 128+32+8. Live stream on the same dataset: snapshot terminator "flags: LAST | SNAPSHOT | BAD_TS_RECV (170)" = 128+32+8+2, and ordinary post-snapshot real-time records "flags: LAST (130)" = 128+2. The Debug renderer in those examples predates the naming of bit 1, so it printed only the recognized names alongside the raw decimal. ENGINE CONSEQUENCE: 128 and 130 are BOTH plain end-of-event records; masking (flags & 128) is mandatory. Because bit 0 (1) is documented as "May be set or unset", flags values 129/131/169/171 are also legal shapes of the same states.

*Source:* https://databento.com/docs/standards-and-conventions/mbo-snapshot

**ts_event = matching-engine-received (CME tag 60-TransactTime); ts_recv = Databento capture-server receive (PTP/GPS, monotonic per symbol); ts_in_delta = nanoseconds BEFORE ts_recv that the publisher sent (CME tag 52-SendingTime).**

GLBX.MDP3 page mapping table verbatim: ts_recv | N/A | "The capture-server-received timestamp."; ts_event | 60-TransactTime | "The matching-engine-received timestamp."; ts_in_delta | 52-SendingTime | "The matching-engine-sending timestamp." Common-fields page: ts_event is "the time that the event is received by the matching engine (tag 60 in FIX encoding)" and "Since we do not adjust the publisher's timestamps, any non-monotonicity in the original data will remain." ts_in_delta "expresses the number of nanoseconds between the Databento receive timestamp (ts_recv) and the publisher sending timestamp. To get the sending timestamp itself, simply subtract ts_in_delta from ts_recv. Since the publisher and Databento are not necessarily synchronized to the same clock source, ts_in_delta may be negative." It is int32 and "The minimum will clamp to INT32_MIN and the maximum will clamp to INT32_MAX, even if the true value exceeds these limits." ts_recv is "synchronized against UTC with sub-microsecond accuracy... always guaranteed to be monotonic for any given symbol" (hardware NIC timestamping, GPS/PTP, slewed not stepped, leap-second corrected at end of session). Four timestamp types exist: ts_event, ts_in_delta, ts_recv, and ts_out (live only). USAGE: (a) exchange-side event ordering — use STREAM ORDER, with ts_event only as a label (it can tie and is not guaranteed monotonic); (b) latency-aware research — use ts_recv (the only monotonic, UTC-disciplined clock), with publisher send time = ts_recv - ts_in_delta and wire-to-capture latency = ts_recv - ts_event.

*Source:* https://databento.com/docs/venues-and-datasets/glbx-mdp3 and https://databento.com/docs/standards-and-conventions/common-fields-enums-types

**ts_recv is the INDEX timestamp for MBO — the field to sort/merge on, not ts_event.**

Common-fields page, Index timestamp section, verbatim: "All schemas have a primary timestamp that should be used for sorting records as well as indexing into any symbology data structure. This index timestamp will be ts_recv if it exists in the schema, otherwise it [is ts_event]." This is mirrored in the dbn source, where MboMsg::ts_recv carries the #[dbn(index_ts)] attribute. HAZARD: snapshot records deliberately carry a synthetic ts_recv (see snapshot findings), so a naive global sort on ts_recv reorders or misplaces them relative to the real-time stream.

*Source:* https://databento.com/docs/standards-and-conventions/common-fields-enums-types

**MDOrderPriority (CME tag 37707) is omitted — the CURRENT operative guidance is to use MESSAGE ORDER, not ts_event.**

Databento GLBX.MDP3 page, 'Order Priority', verbatim: "Although Databento does not expose tag 37707-MDOrderPriority in the MBO schema, first in, first out priority (FIFO) can be determined from message order. Messages for a single instrument_id are never reordered, even if they have the same timestamps. Our daily MBO snapshots also preserve FIFO order priority." This is stronger and more operational than the older ts_event-based advice: ts_event VALUES tie, so an engine must key queue position on stream position (file/record order), and must not re-sort within an instrument by ts_event. CME's own side confirms the transmission order is priority-faithful: "MBOFD Order Priority is based on the sequence of iLink orders received by a CME Globex market segment (tag 1300-MarketSegmentID) and will be sent accordingly regardless of the match algorithm."

*Source:* https://databento.com/docs/venues-and-datasets/glbx-mdp3 and https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457605721/MDP+3.0+-+Market+by+Order+-+Book+Management

**CONFIRMED: the exact ts_event / interest-rate-options / LMM statement, with its source and date.**

issues.databento.com, issue titled "MDOrderPriority is not provided for CME Globex MDP 3.0", posted by Tessa Hollinger, 5 Mar 2023, tags #http-api #raw-api, status Confirmed, "tracked internally as D-2130". Verbatim: "We currently leave out MDOrderPriority from our normalized MBO messages, due to 2 reasons: This behavior is CME-specific. Most other venues adopt ITCH-based behavior, where ordering is based on timestamp instead. If we supported MDOrderPriority, it would bloat the data for all of the non-CME venues. ts_event serves the same purpose as MDOrderPriority for all instruments except for interest rate options and instruments where there's a LMM. We confirmed this with CME GCC and also from practical experience of comparing simulation against live order matching. We actually recommend most users to infer MDOrderPriority from ts_event since it makes their order book implementation more reusable for other venues." It goes on to reject 'supplementing' normalized MBO with venue-specific fields in favour of exposing raw payloads/PCAPs. NOTE: this is a March 2023 statement; the current GLBX docs page (message order, never reordered even on equal timestamps) is the operative engineering guidance and is strictly safer.

*Source:* https://issues.databento.com/b/6vrl98vl/feature-ideas/mdorderpriority-is-not-provided-for-cme-globex-mdp-30

**CME states flatly that LMMs do not exist in futures products — so the LMM half of Databento's caveat cannot bite SR3 or Treasury futures.**

CME Group Client Systems Wiki, 'CME Globex Matching Algorithm Steps', LMM section, verbatim first rule: "LMMs do not exist in futures products at CME Group." Other rules on the same page: "LMM percentages are proprietary between the designated party and CME Group."; "Products can have multiple LMMs assigned."; "The total LMM percentage assigned a product will not exceed a certain value. This value is proprietary to CME Group, differs by product, and is less than 50%."; "LMMs, by participating, are guaranteed their percentage of the match quantity rounded down to no less than one lot." The page's Algorithm Matrix gives the step sequence per tag-1142 code: A = Allocation (Pro Rata w/ Top): TOP -> Pro Rata -> FIFO; C = Currency Roll (Pro Rata w/o Top): Pro Rata -> FIFO; F = FIFO: FIFO; K = Configurable: TOP -> LMM -> Split -> FIFO* -> Pro Rata* -> Leveling* -> FIFO; O: TOP -> Pro Rata -> FIFO; Q: TOP -> LMM -> Pro Rata -> FIFO; S: TOP -> LMM -> FIFO; T: LMM -> FIFO. Only K, Q, S, T contain an LMM step.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457218521/CME+Globex+Matching+Algorithm+Steps

**SEPARATE HAZARD: SOFR futures do NOT match FIFO — queue position is not fill priority for SR3, even though MBO stream order is faithful.**

CME 'Supported Matching Algorithms' wiki, section heading 'Pro-Rata Allocation for Secured Overnight Financing Rate (SOFR) Futures', verbatim: "This match algorithm known as Pro Rata or Allocation Algorithm is applied only to the SOFR futures at CME Group (SOFR packs and Bundles match via FIFO)." Rules verbatim (abridged): "A TOP order is an order having a price that betters the market at the time the order is received and which is therefore designated as having time priority. Only a single buy order and a single sell order can have time priority at any given moment. Orders having time priority match first regardless of size."; "Only non-implied orders can be top orders."; "The Pro Rata algorithm will only allocate to resting orders that will receive 2 or more contracts."; "After percentage allocation, all remaining contracts not previously allocated due to rounding considerations are allocated to the remaining orders on a FIFO basis."; "Outright orders will have priority over implied orders and will be allocated the remaining quantity according to their timestamps." Allocation ('A') step order is TOP -> Pro Rata (min 2 lots) -> FIFO residual. Treasury futures are FIFO ('F': timestamp only). ENGINE CONSEQUENCE: a queue-position/fill-probability model built from MBO arrival order is valid for ZT/ZF/ZN/TN/ZB/UB but WRONG for SR3 outrights, where expected fill scales with the order's share of price-level size plus the TOP flag. SR3 packs and bundles are FIFO. Also note re-queue rules: an order loses time priority on an increase in quantity, a change of price, or a change of account number — the account-number case is invisible in MBO.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457218479/Supported+Matching+Algorithms

**Historical batch MBO snapshot: delimited by a leading action='R' and terminated by F_LAST; all records carry F_SNAPSHOT|F_BAD_TS_RECV.**

Databento 'MBO snapshots' page, verbatim: "An MBO snapshot represents the order book at a specific point in time, including all outstanding buy and sell orders. The snapshot is streamed as a sequence of MBO records to insert new orders in the book (a sequence of Add Actions). The snapshot records preserve the priority order (per instrument) at each price level, enabling accurate reconstruction of the order book." ... "All snapshot records are marked with the F_SNAPSHOT and F_BAD_TS_RECV flags (ts_recv is set to the snapshot generation timestamp). An instrument's snapshot starts with a cleaR action, followed by zero or more Add Actions." End detection, verbatim: "The order book of a given instrument is not guaranteed to be in a complete and valid state after the last snapshot record because it might not correspond to the final event record (indicated with the F_LAST flag). If the last snapshot record does not have the F_LAST flag set, the order book will not be valid until the next MBO record with the F_LAST flag set." Historical availability, verbatim: "We offer MBO snapshot through the Historical API for venues that follow a weekly session structure (CME Globex MDP 3.0), and for venues whose daily trading sessions cross 00:00:00 UTC (ICE Europe Commodities iMpact). The order book snapshot is generated at 00:00:00 UTC each weekday (Monday-Friday)." and "Snapshot records are streamed through the Historical API when the requested interval includes midnight UTC for a given weekday." Timestamp rules, verbatim: "ts_event: unchanged. The cleaR book MBO record from the Live API snapshot contains the snapshot generation timestamp instead"; "ts_in_delta: always 0"; "ts_recv: set to the snapshot generation timestamp (indicated with the F_BAD_TS_RECV flag)"; "ts_out: unchanged". Worked example values: snapshot body flags 40, terminator flags 168, ts_recv 1718582400000000000 (= 2024-06-17T00:00:00Z) on every record while ts_event retains the original per-order times.

*Source:* https://databento.com/docs/standards-and-conventions/mbo-snapshot

**HAZARD: an empty-book snapshot is a lone R record whose ts_recv is UNDEF_TIMESTAMP (u64 max), while ts_recv is the sort key.**

Observed in the documented example on the MBO snapshot page, for instrument_id 14160: "MboMsg { hd: RecordHeader { length: 14, rtype: Mbo, publisher_id: GlbxMdp3Glbx, instrument_id: 14160, ts_event: 1718117495809255541 }, order_id: 0, price: UNDEF_PRICE, size: 0, flags: LAST | SNAPSHOT | BAD_TS_RECV (168), channel_id: 0, action: 'R', side: 'N', ts_recv: 18446744073709551615, ts_in_delta: 0, sequence: 0 }". Contrast the populated instrument 4916 whose R record carries ts_recv = 1718582400000000000. So within ONE snapshot block, ts_recv is not uniform: instruments with no resting orders get UNDEF_TIMESTAMP (18446744073709551615). Since ts_recv is the documented index/sort timestamp, any global sort or time-window filter on ts_recv will fling these records to the far end of the stream or drop them, silently skipping the book clear for that instrument. Clear records also carry price = UNDEF_PRICE, size = 0, order_id = 0, sequence = 0, side = 'N' — do not feed them to price/size parsers. Report as an observed documented example; I did not find a general statement that all empty-book snapshots behave this way.

*Source:* https://databento.com/docs/standards-and-conventions/mbo-snapshot

**The leading snapshot clear record (action=R with F_SNAPSHOT) only exists from 2024-02-10; earlier history was backfilled later.**

Databento blog 'We're making improvements to MBO publishing', February 07, 2024, verbatim: "Currently, each day of historical data starts from 00:00 UTC. For datasets with sessions crossing over UTC boundaries like CME, on the MBO schema, we publish the current state of the order book as a number of order snapshots with this timestamp." ... "For MBO data timestamped on or after February 10, 2024, at 00:00 UTC, we'll publish a clear record with action=R. This will be sent at the start of every session or order book snapshot for every instrument, and for book recovery, if needed. This clear message will have the F_SNAPSHOT flag set to make it explicit that it's part of the snapshot process." ... "For datasets with sessions contained within UTC date boundaries that don't have order snapshots (such as Databento Equities Basic), a clear message will be published at 00:00 UTC as well. This clear message will not have the F_SNAPSHOT flag set." Live: "a clear message will be published for every instrument before the first message received for that instrument in the session (weekly session in CME's case, daily session for other datasets)." Backfill: "For historical data prior to February 10, 2024, clear records are expected to be available by early March 2024." Rationale verbatim: "There was recurring confusion regarding how to process the snapshot records when reading multiple files sequentially."

*Source:* https://databento.com/blog/improvements-mbo-publishing

**OPEN DEFECT: since 2026-03-22 the Sunday CME GTC restatement on GLBX.MDP3 is missing F_SNAPSHOT.**

issues.databento.com, title "GLBX.MDP3 - F_SNAPSHOT flag missing from Sunday GTC restatement since 2026-03-22", filed by Renan Gemignani (Databento), ~18 days before 2026-08-08 (so ~2026-07-21), tags #bug #data-quality, status Confirmed, 2 votes. Verbatim: "Since 2026-03-22, the CME GTC restatement on Sunday (ahead of the week's trading session) has not had the F_SNAPSHOT flag set (to indicate that this is the venue's snapshot). GTC restatements on Saturday are unaffected." CONSEQUENCE: an engine that classifies the weekly-session-open CME GTC restatement by testing flags & F_SNAPSHOT will mis-classify Sunday restatement orders as genuine real-time adds for every week from 2026-03-22 onward, inflating Sunday-open order-arrival counts and corrupting any order-lifetime or queue-age statistic anchored at the weekly open. Saturday restatements are unaffected.

*Source:* https://issues.databento.com/b/6vrl98vl/feature-ideas/glbxmdp3-f-snapshot-flag-missing-from-sunday-gtc-restatement-since-2026-03-22

**The CME weekly-session GTC snapshot is re-sorted by Databento into priority order and is stamped with F_BAD_TS_RECV + F_SNAPSHOT.**

Databento GLBX.MDP3 page, 'CME MBO snapshot', verbatim: "At the beginning of the weekly trading session, CME publishes a MBO order snapshot. This snapshot contains any orders that persisted from the previous trading session, such as Good 'Till Cancelled orders. The event timestamp (ts_event) for these orders corresponds to the time the snapshot is generated by CME. It does not reflect the original time the order was entered or last modified." ... "These orders are not published by CME in priority order. As Databento does not expose tag 37707-MDOrderPriority, if these MBO records were published by Databento in the same order they were sent from CME, it would not be possible to determine the correct order priority. In order to publish the records in priority order, Databento buffers the orders from the first CME event of the trading session, per instrument. Once the End of Event is reached, Databento sorts the records in priority order and then publishes them. Therefore, the order priority is correctly reflected by the order of publishing. The ts_recv for these records will be set to the ts_recv of the final record of the event. As the records have been slightly delayed and the ts_recv of the initial records may not match the original ts_recv, the flag F_BAD_TS_RECV is set on these records. The F_SNAPSHOT flag is also set on these records to indicate that they are from the CME snapshot." Weekly session context, verbatim: "Although CME pauses trading daily, the market follows a weekly session structure with most instruments accepting orders from Sunday night to Friday night (local time). To make it easier to work with historical MBO data, Databento includes an order book snapshot at 00:00:00 UTC each weekday (Monday-Friday)." And: "Before the trading session begins, or during the daily pause, it is normal for order books to be locked or crossed: CME will accept orders but won't execute any trades until the opening uncrossing." ENGINE CONSEQUENCE: at the weekly open, ts_event is a snapshot-generation stamp, NOT order entry time — do not compute order age or queue age from it; locked/crossed books pre-open are expected and must not trigger a book-integrity assertion.

*Source:* https://databento.com/docs/venues-and-datasets/glbx-mdp3

**F_LAST on GLBX is Databento-rewritten from CME tag 5799, per instrument — and it is REQUIRED for correct BBO computation.**

Databento GLBX.MDP3 page, verbatim: "When interpreting MBO data, the F_LAST flag (0x80, 128) is used to mark the last record in a single event for each instrument_id. This flag is based on CME's \"End of event\" flag in tag 5799-MatchEventIndicator. However, CME only sets this flag on one single message, even if the event spanned multiple instruments. Instead, we set the F_LAST flag on the last record for each instrument, so that the data can be interpreted consistently with any subset of instruments. Records with action None may carry F_LAST." ... "Across all of Databento's feeds, it is important to use the F_LAST flag when calculating the best bid and offer, like our MBP-1 schema. Between records without the F_LAST flag, the book is in the process of updating, and the apparent best bid and offer may have already been traded." ... "This is accounted for when we construct our other schemas, such as MBP-1 and Trades. Outside of MBO, this flag can be ignored." ENGINE CONSEQUENCE: derive top-of-book / mid / microprice ONLY at F_LAST boundaries. Intra-event snapshots of the book are transient states that never existed as a tradable market. Note the doc already anticipates the new normalization: "Records with action None may carry F_LAST."

*Source:* https://databento.com/docs/venues-and-datasets/glbx-mdp3

**DBN v1 vs v2 vs v3: the MBO record layout NEVER changed. Only metadata, definitions, symbol mapping, statistics, and gateway messages changed.**

Databento DBN 'Versioning' section, verbatim. Version 2: "Metadata: Sets version to 2; Adds symbol_cstr_len field; Rearranges padding; The fixed-length strings for symbology are now defined to have symbol_cstr_len characters (currently 71), whereas in version 1 they always had 22. InstrumentDefMsg (definition schema): raw_symbol now has symbol_cstr_len characters (71); Rearranges padding. SymbolMappingMsg (live symbology): stype_in_symbol and stype_out_symbol now have symbol_cstr_len characters (71); Adds stype_in and stype_out fields; Removes padding. ErrorMsg: Adds space to err for longer error messages; Adds code and is_last fields. SystemMsg: Add space to msg for longer messages; Adds code field." Version 3: "Added 8-byte alignment padding to the end of metadata; Expanded quantity to 64 bits in StatMsg; InstrumentDefMsg: A definition record will be created for each strategy leg" plus leg_count, leg_index, leg_instrument_id, leg_raw_symbol, leg_side, leg_underlying_id, leg_instrument_class, leg_ratio_qty_numerator/denominator, leg_ratio_price_numerator/denominator, leg_price, leg_delta; "Expands asset to 11 bytes; Expands raw_instrument_id to 64 bits"; removal of trading_reference_price, trading_reference_date, settl_price_type, md_security_trading_status. Corroborated by dbn CHANGELOG 0.14.0 (2023-11-15) for v2: "Affects SymbolMappingMsg, InstrumentDefMsg, and Metadata. All other record types and market data schemas are unchanged" and 0.35.0 (2025-05-28) for v3. HARD PROOF for MBO: rust/dbn/src/compat.rs defines versioned variants only for ErrorMsgV1, InstrumentDefMsgV1, StatMsgV1, SymbolMappingMsgV1, SystemMsgV1, InstrumentDefMsgV2 — there is NO MboMsgV1/V2; and v1.rs, v2.rs, v3.rs all re-export the identical crate::record::MboMsg. Constants: SYMBOL_CSTR_LEN_V1 = 22, SYMBOL_CSTR_LEN_V2 = 71, SYMBOL_CSTR_LEN_V3 = SYMBOL_CSTR_LEN_V2; DBN_VERSION = 1/2/3 per module. Metadata header layout: version char[4] ("DBN" + version byte), length uint32 (remaining metadata length, excluding version and length), dataset char[16], schema uint16 (u16::MAX = mixed schemas, "which will always be the case for live data"), start uint64, ... then optional symbology mappings.

*Source:* https://databento.com/docs/standards-and-conventions/databento-binary-encoding + https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/compat.rs + https://raw.githubusercontent.com/databento/dbn/main/CHANGELOG.md

**GLBX.MDP3 is one of only nine datasets served as DBN v3; everything else is still v1 (v2 is effectively skipped).**

Databento DBN Versioning section, verbatim: "Currently, version 3 is used for the GLBX.MDP3, IFEU.IMPACT, IFLL.IMPACT, IFUS.IMPACT, NDEX.IMPACT, OCEA.MEMOIR, XCBF.PITCH, XEEE.EOBI, and XEUR.EOBI datasets. All other datasets use version 1. The DBN crate and client libraries will continue to support decoding earlier versions." Upgrade path: "DBN files can be upgraded to the latest version with the dbn CLI tool by passing the --upgrade or -u flag", e.g. `dbn version1.dbn --output version3.dbn --upgrade`. Since MboMsg is byte-identical across versions, a numba MBO decoder can parse the 56-byte record with one struct layout for any DBN version; only the metadata header parse and any definition/statistics side-loading are version-sensitive. The dbn library default VersionUpgradePolicy is UpgradeToV3 as of 0.35.0.

*Source:* https://databento.com/docs/standards-and-conventions/databento-binary-encoding

**CME's own MDOrderPriority semantics (useful if you ever cross-check against raw MDP3): lower value = higher priority, and it is NOT sortable across prices.**

CME Client Systems Wiki, 'MDP 3.0 - Market by Order - Book Management', verbatim: "Order Priority (tag 37707-MDOrderPriority), from lowest to highest values, is used to position the order against other orders of the same instrument side, and price." ... "To build the full depth MBOFD order book, each order must be sorted by instrument side, and price (in descending order for Bids and ascending order for Asks). Then the order priority number must be applied only to the orders of the same price/ side." ... "For tag 37707-MDOrderPriority, a lower value is a higher priority." ... "Priority may not be sequential for tag 37707-MDOrderPriority outside of price (tag 270-MDEntryPx). Therefore, systems must first sort by price (tag 270-MDEntryPx), then by priority (tag 37707-MDOrderPriority) to determine the book order." ... "For MBOFD, there is no maximum number of orders or depth allowed on the book. All MBOFD book updates for an instrument within an event must be processed before the MBOFD book is valid." The wiki's own worked example: OrderID 111 (MDOrderPriority 653654) has book priority 1 while OrderID 901 (MDOrderPriority 524123, a LOWER number) has book priority 4, because 901 rests at a worse price. MBOFD update actions are tag 37708-OrderUpdateAction (or tag 279-MDUpdateAction depending on SBE template): 0 = New, 1 = Update, 2 = Delete — which map to Databento's A, M, C.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457605721/MDP+3.0+-+Market+by+Order+-+Book+Management

**match_algorithm value set in the Databento definition schema — the per-instrument, machine-checkable way to settle SR3 vs UST matching.**

Databento instrument-definitions page, Matching algorithm table verbatim (Name | Value | Description): Undefined | (blank) | "A matching algorithm was not specified."; FIFO | F | "First-in-first-out matching."; Configurable | K | "A configurable match algorithm."; Pro-Rata | C | "Trade quantity is allocated to resting orders based on a pro-rata percentage: resting order quantity divided by total quantity."; FIFO with LMM | T | "Like FIFO, but with LMM allocations prior to FIFO allocations."; Threshold Pro-Rata | O | "Like Pro-Rata, but includes a configurable allocation to the first order that improves the market. Minimum order thresholds may exist."; FIFO with Top Order and LMM | S | "Like FIFO with LMM, but includes a configurable allocation to the first order that improves the market."; Threshold Pro-Rata with LMM | Q | "Like Threshold Pro-Rata, but includes a special priority to LMMs."; Eurodollar Futures | Y | "Special variant used only for Eurodollar futures on CME."; Time Pro-Rata | P | "Trade quantity is shared between all orders at the best price. Orders with the highest time priority receive a higher matched quantity."; Institutional Prioritization | V | "A two-pass FIFO algorithm..."; Allocation | A | "Like Pro-Rata, but includes a configurable allocation to the first order that improves the market." In the dbn source the field is documented as "The matching algorithm used for the instrument, typically FIFO" (match_algorithm, c_char, in InstrumentDefMsg). ACTION: pull the definition schema for your SR3 and ZT/ZF/ZN/TN/ZB/UB instrument_ids and read match_algorithm directly — that resolves the SR1-vs-SR3 ambiguity and any per-expiry variation without relying on prose.

*Source:* https://databento.com/docs/schemas-and-data-formats/instrument-definitions


### inferred

**SR3 futures and the UST futures complex (ZT/ZF/ZN/TN/ZB/UB) fall OUTSIDE Databento's MDOrderPriority caveat.**

This is a syllogism from two primary sources, not a sentence anyone published. Databento's caveat has exactly two exception classes: (1) interest-rate OPTIONS, and (2) instruments where there is an LMM. SR3 futures and ZT/ZF/ZN/TN/ZB/UB are futures, not options — so (1) does not apply (options ON SR3 and ON Treasury futures DO fall under it). CME states "LMMs do not exist in futures products at CME Group" — so (2) does not apply either, and none of the LMM-bearing algorithms (K, Q, S, T) can be assigned to them. Therefore ts_event / stream-order reconstruction of queue priority is sound for the instruments in scope. Verification path inside the engine: read the definition schema's match_algorithm field per instrument and assert it is not in {K, Q, S, T}.

*Source:* https://issues.databento.com/b/6vrl98vl/feature-ideas/mdorderpriority-is-not-provided-for-cme-globex-mdp-30 + https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457218521/CME+Globex+Matching+Algorithm+Steps

**GLBX MBO contains NO implied resting orders — implied liquidity is absent from the MBOFD feed Databento normalizes from.**

Chain of two primary statements. CME Group Client Systems Wiki, 'MDP 3.0 - Market by Order - Book Management', verbatim: "Implied order book information is not sent in MBOFD format." (The same holds for the limited-depth variant, MBOLD, on its companion page.) Databento GLBX.MDP3 page, verbatim: "Records in the MBO schema with Add, Modify, and Cancel actions are normalized from Market Data Incremental Refresh - MBOFD...". Therefore every A/M/C record in GLBX MBO is a direct (outright) order; implied depth appears only in MBP schemas. Implied TRADES do reach MBO, and the tell is the side field — Databento GLBX page, verbatim: "Implied trades may not have an aggressing side set. These trades will be normalized with side set to None." So side='N' on an action='T' record flags a likely implied trade. Forward-looking detection: the 2026-07-07 normalization release adds implied matching state to the status schema — "The status will appear in the trading_event field as either IMPLIED_MATCHING_ON or IMPLIED_MATCHING_OFF" — which lets the engine know when CME was generating implied depth at all. Also relevant to SR3: CME's Allocation rules state "Only non-implied orders can be top orders" and "Outright orders will have priority over implied orders".

*Source:* https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457605721/MDP+3.0+-+Market+by+Order+-+Book+Management + https://databento.com/docs/venues-and-datasets/glbx-mdp3


### Unresolved

- F_PUBLISHER_SPECIFIC (1 << 1, decimal 2) semantics for publisher GLBX.MDP3. The flags table says only "Semantics depend on the publisher_id. Refer to the relevant dataset supplement for more details." No such GLBX supplement was findable: the databento.com/docs/venues-and-datasets/glbx-mdp3 page contains no occurrence of 'publisher-specific' or 'supplement', and web searches returned nothing. I therefore CANNOT say what bit 1 means when it appears in GLBX MBO records — only that the live examples on Databento's own snapshot page show it set (flags 130 and 170) while the historical batch examples do not (flags 40 and 168). Those examples predate the naming of bit 1, so it is possible the bit was reserved-but-set at the time rather than carrying today's F_PUBLISHER_SPECIFIC meaning. Resolve by asking Databento support, or by histogramming raw flags bytes over a real GLBX mbo file per action/regime.

- F_MAYBE_BAD_BOOK (1 << 2, decimal 4): what a consumer must actually DO. I found only the definition ("An unrecoverable gap was detected in the channel" / dbn: "Indicates an unrecoverable gap was detected in the channel"). The standards-and-conventions/normalization page does not mention it. I could not establish: whether GLBX emits a book-clear (action='R') alongside or after the gap, how long the flag persists after the gap, whether it is sticky per channel_id or per instrument_id, or whether Databento's recommended recovery is 'discard the affected instrument until the next snapshot' vs 'clear and rebuild'. Do not guess this in the engine — ask Databento support and pin the answer with a real gap day.

- SR1-vs-SR3 scope and the exact tag-1142 letter for Three-Month SOFR futures. The CME wiki says the Allocation/Pro-Rata algorithm "is applied only to the SOFR futures at CME Group (SOFR packs and Bundles match via FIFO)" but does not disambiguate 1-Month SOFR (SR1) from 3-Month SOFR (SR3), does not name the tag-1142 code, and I could not obtain the GCC Product Reference Sheet / Globex Reference Sheet that carries per-product algorithm assignments. The cmegroup.com SR3 contract-specs page does not list a matching algorithm at all. Note the definition-schema table also has a distinct 'Allocation | A' and 'Threshold Pro-Rata | O' whose English descriptions are nearly identical, so guessing between them is unsafe. Resolution: read match_algorithm from your own GLBX definition records for the specific SR3 instrument_ids and expiries you trade, and re-check it per contract month (do not assume it is uniform across the strip or stable over time).

- Whether GLBX mbo files you ALREADY hold locally for dates before 2024-02-10 contain the retro-fitted action='R' snapshot clear records. Databento said clear records for pre-2024-02-10 history were "expected to be available by early March 2024" — so a file downloaded before that backfill will differ from a re-download of the same date. Similarly, any GLBX file downloaded before today's 2026-08-08 cutover carries the OLD F_LAST placement while a re-download of the identical date range will carry the new standalone action='N' terminator. I could not verify what your local copies contain. Resolution: for a sample date, count records with action='R' & F_SNAPSHOT and count action='N' records with F_LAST in your local file, and compare against a fresh pull.

- The exact F_LAST behaviour of the NEW normalization in edge cases: whether the standalone action='N' terminator carries a meaningful price/size/order_id/side (the blog example shows flags=128 but the truncated table did not let me read the other fields), whether exactly one such record is emitted per instrument_id per event, and whether any book-update record can still carry F_LAST under the new scheme. Verify empirically against a post-cutover file before hard-coding 'F_LAST implies action==N'.

- Whether ts_event is guaranteed monotonic within a single instrument_id on GLBX. Databento states generally that "any non-monotonicity in the original data will remain" for ts_event, and separately that ts_recv is "always guaranteed to be monotonic for any given symbol" and that MBO "Messages for a single instrument_id are never reordered" — but I found no explicit statement that CME tag-60 TransactTime is monotonic per instrument on MDP 3.0. Treat stream order as authoritative and do not assert ts_event monotonicity in the engine.


## CME MDP 3.0 Market-by-Order (MBOFD) book management, order priority, implied orders, spread-leg printing, and matching algorithms — for a Python/numba MBO engine over Databento GLBX.MDP3 DBN v3


### primary-source

**MBOFD uses only three book actions: New=0, Change/Update=1, Delete=2. Overlay is NOT an MBO action.**

Wiki 457605721: 'New: Create/insert a new order (tag 37708-OrderUpdateAction=0 or tag 279-MDUpdateAction=0)'; 'Update: Change order information (=1)'; 'Delete: Remove an order (=2)'. Note: 'Depending on the SBE template, either tag 37708-OrderUpdateAction or tag 279-MDUpdateAction will be used for book updates.' The page contains NO mention of Overlay. Wording is via a summarizing fetch of the REST body; quoted fragments are verbatim from that body.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457605721?expand=body.view

**The full tag 279-MDUpdateAction enum is New=0, Change=1, Delete=2, DeleteThru=3, DeleteFrom=4, Overlay=5, NULL_VAL=255 — values 3/4/5 are Market-by-PRICE book operations, not MBO.**

SBE-generated enum (epam java-cme-mdp3-handler, MDUpdateAction.java): New=0, Change=1, Delete=2, DeleteThru=3, DeleteFrom=4, Overlay=5, NULL_VAL=255. Semantics (secondary): DeleteThru deletes the top 'n' levels on one side of the book; DeleteFrom deletes all book levels from a level down on one side; Overlay is CME-specific — when the best price changes, CME sends a single overlay instruction for price level 1. Because MBOFD carries individual orders (not levels), a numba MBO engine will never see 3/4/5 in the order repeating group; it will see them in the MBP repeating group of the same combined message.

*Source:* https://github.com/epam/java-cme-mdp3-handler/blob/master/mbp-with-mbo/src/test/java/com/epam/cme/mdp3/test/gen/MDUpdateAction.java

**Overlay IS the book-management model for MBO Limited Depth (MBOLD) — a full restate, not an incremental action.**

Wiki 457638457: 'MBOLD uses an overlay approach to book management. Overlay book management completely restates the MBOLD book with each new Market Data Snapshot Full Refresh (tag 35-MsgType=W) message.' This is a different product from MBOFD; do not conflate. Databento GLBX.MDP3 mbo schema is the full-depth (MBOFD) feed.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457638457?expand=body.view

**MBOFD order entries carry only tag 269-MDEntryType 0=Bid and 1=Offer. There is no trade/fill entry type inside the MBO order block.**

Wiki 457575222 (MDP 3.0 - Market Data Incremental Refresh - MBOFD): tag 269-MDEntryType valid values for MBOFD are exactly '0=Bid' and '1=Offer'. Order-block fields observed: tag 37-OrderID, tag 37707-MDOrderPriority, tag 270-MDEntryPx, tag 37706-MDDisplayQty, tag 48-SecurityID, tag 279-MDUpdateAction, tag 269-MDEntryType. Consequence: a fill reaches the MBO book ONLY as a Change (reduced MDDisplayQty) or a Delete — the execution itself is reported separately in the Trade Summary entry (tag 269-MDEntryType=2) of the same event.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457575222?expand=body.view

**MBP and MBOFD arrive in ONE Incremental Refresh message with two repeating groups, joined by tag 9633-ReferenceID.**

Wiki 457227795: 'The Market Data Incremental Refresh message below is sent for book updates that include both Market by Price (MBP) and Market by Order Full Depth (MBOFD) updates.' RG1 = tag 268-NoMDEntries (aggregate price levels: MDEntryPx, MDEntrySize, SecurityID, MDUpdateAction, MDEntryType). RG2 = tag 37705-NoOrderIDEntries, described as 'Repeating group of MBO book updates included in an event. Repeating group used for MBP and MBOFD combined updates.' tag 9633-ReferenceID = 'Reference to corresponding Price and Security ID, sequence of MD entry in the message' — it links each order entry back to its MBP price-level entry.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457227795?expand=body.view

**EVENT ATOMICITY IS MANDATORY: the MBO book is not valid mid-event. tag 5799-MatchEventIndicator bit 7 marks end of event; bit 0 marks last Trade Summary of the event.**

Wiki 457605721: 'All MBOFD book updates for an instrument within an event must be processed before the MBOFD book is valid.' Wiki 457575222/457227795 on tag 5799-MatchEventIndicator: 'Bitmap field of eight Boolean type indicators reflecting the end of updates for a given CME Globex Event'; 'Bit 0: (least significant bit) Last Trade Summary message for a given event'; 'Bit 7: (most significant bit) Last message for a given event'. For a numba engine this is a correctness requirement, not an optimization: any metric computed from a partially-applied event (e.g. queue position, top-of-book) is reading a torn book.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457605721?expand=body.view

**MBOFD has no maximum depth and no maximum order count.**

Wiki 457605721: 'MBOFD has no maximum number of orders or depth allowed.' Contrast with MBP, which disseminates a fixed 10 levels for most futures — the wiki's cancel example shows OrderID 251 (qty 25 @ price 850) removed from the full-depth book with NO MBP change, because that level is below the 10 disseminated levels. Pre-allocating fixed-size numba arrays per instrument must therefore be sized defensively or grow.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457605721?expand=body.view

**Trade Summary structure: Summary Level groups + Order Detail groups, with tag 346-NumberOfOrders giving the count of Order Detail entries belonging to each Summary Level.**

Wiki 457225774: 'Tag 346-NumberOfOrders in each Summary Level entry indicates the number of repeating groups in the associated Order Detail.' Order Detail repeating groups are 'each associated with a single Summary Level and contain detailed order participation information.' Summary Level fill quantity is tag 271; per-order participation quantity is tag 32-LastQty.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457225774?expand=body.view

**When tag 5797-AggressorSide is defined (1=Buy, 2=Sell), the FIRST Order Detail entry is the aggressor, and its tag 32-LastQty equals the Summary Level fill quantity (tag 271).**

Wiki 457225774: 'An aggressor is defined as any customer order that triggers a trade immediately upon entering the book.' 'The aggressor quantity (tag 32) in the first Order Detail entry is equal to the Summary Level fill quantity (tag 271).' Corollary given on the page: 'When aggressor quantity is not equal to Summary Level fill quantity, the aggressor joined a pool of resting orders' (i.e. it did not take — it rested and was hit).

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457225774?expand=body.view

**Implied participation in a trade is detectable arithmetically: aggressor qty != sum of remaining Order Detail qtys means implied orders filled, and the shortfall IS the implied quantity.**

Wiki 457225774 verbatim: 'If the aggressor quantity (tag 32) is not equal to the sum of the remaining Order Detail entries quantity associated with that Summary Level, customer and implied orders were filled in the trade.' And: 'Order Details are only sent for the customer orders. Any unreported quantity represents the participating implied orders.' Also: 'trades that only involve implied orders are not published in a Trade Summary message, but volume and price statistics are updated real-time.' Two cases produce tag 5797-AggressorSide=0: (a) an aggressing customer order trading against implied orders leaves at least one Summary Level with no defined aggressor, representing the customer orders that created the executed implied orders; (b) Market Open or Re-Open after a Velocity Logic Event.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457225774?expand=body.view

**tag 37707-MDOrderPriority: LOWER value = HIGHER priority. It is only meaningful WITHIN a (side, price) bucket — you must sort by price first, then by priority.**

Wiki 457605721 verbatim: 'Order Priority (tag 37707-MDOrderPriority), from lowest to highest values, is used to position the order against other orders of the same instrument side, and price.' 'For tag 37707-MDOrderPriority, a lower value is a higher priority.' 'Priority may not be sequential for tag 37707-MDOrderPriority outside of price.' 'Then the order priority number must be applied only to the orders of the same price/side.' 'MBOFD Order Priority is based on the sequence of iLink orders received by a CME Globex market segment (tag 1300-MarketSegmentID)' — and is sent that way REGARDLESS of the product's match algorithm. Book build = sort by side and price (bids descending, asks ascending), then apply MDOrderPriority ascending within each level.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457605721?expand=body.view

**THE RETAIN/LOSE TABLE. Priority is LOST on: quantity INCREASE, price change, account change, order type change, stop trigger price change, minimum fill quantity change. Priority is RETAINED on: quantity DECREASE, displayed quantity, TIF, client order ID, and all other attributes.**

Wiki 457414497 (Order Functionalities), modifiable-parameter table with a footnote: '*Modifying these parameters will result in a change of priority of the order in the order book.' Asterisked (LOSE priority): Account*, Increase quantity*, Order type*, Price*, Stop trigger price*, Minimum fill quantity*. NOT asterisked (RETAIN priority): Client order ID, Decrease quantity, Customer handling instruction, Time in Force, ATS indicator, Give-up instructions, Customer of firm flag, Displayed quantity, Order expiration date, Self-Match Prevention ID and instructions, CTI code, In-Flight Mitigation. This table is the exact rule set a queue model must implement. Content is primary-source; the parameter names are verbatim, the surrounding prose is paraphrased through a summarizing fetch.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457414497?expand=body.view

**Worked MBOFD example confirms a quantity INCREASE re-prices priority: OrderID 555 qty 30->50 moved MDOrderPriority 722095 -> 722787.**

Wiki 457605721 'Modify Order - Update MBOFD Quantity Example': increasing OrderID 555's quantity from 30 to 50 causes its MDOrderPriority to change from 722095 to 722787, moving it to a lower priority position among orders at price 950. IMPORTANT NEGATIVE RESULT: the page contains NO quantity-DECREASE example, so the retain-on-decrease rule is sourced from the Order Functionalities table above, not from an MBOFD worked example. Note the new priority number is ~692 higher — priority numbers are a monotonically increasing per-market-segment sequence, so a modified order gets a fresh (worse) stamp.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457605721?expand=body.view

**tag 37-OrderID is stable for the life of the order; MDOrderPriority is the field that churns.**

MBO FIX FAQ (wiki 457223111) verbatim Q&A: 'Should an Order ID (Tag37) change during the life of an order?' — 'No, tag37 should stay the same for each order until it has been cancelled or filled.' So order identity is safe to use as a hash key across modifications; queue position is not derivable from OrderID.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457223111?expand=body.view

**An iceberg / display-quantity REFRESH sends the refreshed tranche to the BACK of the queue — this is distinct from a 'displayed quantity' modify, which retains priority.**

Wiki 457218521 (Matching Algorithm Steps), FIFO section: 'When display quantity orders refresh after matching, they return to queue end with lowest priority' — i.e. 'The Display Quantity order's priority is refreshed to be the lowest of the remaining orders at the price level (order is placed at the end of the queue).' A queue model that treats iceberg replenishment as a same-position size increase will systematically overstate the iceberg's fill probability.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457218521?expand=body.view

**DBN's MboMsg HAS NO PRIORITY FIELD — the engine must reconstruct queue position itself from record arrival order plus the retain/lose rules.**

MboMsg fields from databento/dbn rust/dbn/src/record.rs, complete: order_id (u64, 'The order ID assigned at the venue'), price (i64, 1 unit = 1e-9), size (u32), flags (FlagSet), channel_id (u8), action (c_char), side (c_char), ts_recv (u64, ns since epoch), ts_in_delta (i32, 'The matching-engine-sending timestamp expressed as the number of nanoseconds before ts_recv'), sequence (u32, 'The message sequence number assigned at the venue'). tag 37707-MDOrderPriority is NOT carried. Confirming that priority is conveyed by record ORDER: Databento's MBO-snapshot doc states 'Each snapshot record maintains the priority order at every price level.' Practical rule for the engine: queue position = arrival order within (instrument, side, price); on action='M', RE-QUEUE to the back iff price changed or size increased, RETAIN position iff size decreased.

*Source:* https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/record.rs

**DBN Action enum: A=Add, C=Cancel, M=Modify, R=Clear, T=Trade, F=Fill, N=None. T and F explicitly DO NOT affect the book.**

databento/dbn rust/dbn/src/enums.rs verbatim doc comments: Modify=b'M' 'An existing order was modified: price and/or size.'; Trade=b'T' 'An aggressing order traded. Does not affect the book.'; Fill=b'F' 'An existing order was filled. Does not affect the book.'; Cancel=b'C' 'An order was fully or partially cancelled.'; Add=b'A' 'A new order was added to the book.'; Clear=b'R' 'Reset the book; clear all orders for an instrument.'; None=b'N' 'Has no effect on the book, but may carry flags or other information.' Side: Ask=b'A', Bid=b'B', None=b'N'. Because T and F are book-neutral, every book mutation caused by a fill arrives as an explicit M or C record in the same event — the book cannot silently decay.

*Source:* https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/enums.rs

**DBN flag values: LAST=128, TOB=64, SNAPSHOT=32, MBP=16, BAD_TS_RECV=8, MAYBE_BAD_BOOK=4.**

databento/dbn rust/dbn/src/flags.rs — constants are named LAST/TOB/SNAPSHOT/MBP/BAD_TS_RECV/MAYBE_BAD_BOOK (NOT F_-prefixed) at 1<<7, 1<<6, 1<<5, 1<<4, 1<<3, 1<<2. Doc comments: LAST 'Indicates it's the last record in the event from the venue for a given instrument_id.'; TOB 'Indicates a top-of-book record, not an individual order.'; SNAPSHOT 'Indicates the record was sourced from a replay, such as a snapshot server.'; MBP 'Indicates an aggregated price level record, not an individual order.'; BAD_TS_RECV 'Indicates the ts_recv value is inaccurate due to clock issues or packet reordering.'; MAYBE_BAD_BOOK 'Indicates an unrecoverable gap was detected in the channel.' LAST is how CME's event-atomicity rule reaches the engine; MAYBE_BAD_BOOK must invalidate any queue state.

*Source:* https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/flags.rs

**BREAKING AND CURRENT: Databento changed CME event-boundary normalization effective 2026-07-07, in production 2026-08-08 (today), applied RETROACTIVELY to the full history. Event end is now a SEPARATE record with F_LAST and action='N'.**

Databento blog 'Upcoming changes to CME data normalization': 'Starting July 7, 2026', production availability 2026-08-08. Old behaviour: 'For events spanning multiple packets, MBO records are buffered until the packet containing the last event is processed, and F_LAST is then set on the final record for each instrument to mark the end of the event, which delays earlier records in the event.' New behaviour: records are 'published immediately after each packet is processed', and the end of events is marked by 'a new, separate record with F_LAST and action=N'. Also: 'Each strategy leg will have its own definition record, so a strategy with three legs will have three definition records'; two new stat types UPPER_PRICE_LIMIT (17) and LOWER_PRICE_LIMIT (18); implied matching status added to the status schema; FX spot instruments get instrument_class=X. OPERATIONAL CONSEQUENCE: DBN files downloaded before today and after today have DIFFERENT event-boundary semantics for the same historical dates. A book builder that flushes on 'F_LAST seen on a real A/C/M record' silently never flushes under the new normalization; one that flushes only on action='N' never flushes under the old. Handle both.

*Source:* https://databento.com/blog/cme-normalization-changes-2026-07

**IMPLIED ORDERS ARE NOT IN MBO AT ALL. Single sentence, unambiguous.**

Wiki 457605721 verbatim: 'Implied order book information is not sent in MBOFD format.' Corroborated by MBO FIX FAQ (457223111): 'Should orders be tied to implied prices?' — 'No, orders are not tied to implied prices.' Consequence for the engine: the MBO book is the TRUE order book of real, ID-bearing orders. Implied liquidity is invisible in MBO, so MBO-derived depth systematically understates tradable depth at the top of book for implied-eligible instruments — which is every SR3 and Treasury outright with a listed calendar spread.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457605721?expand=body.view

**Implied liquidity is disseminated only in MBP, as tag 269-MDEntryType=E (implied bid) and F (implied offer), 2 levels deep, with NO OrderID.**

Wiki 457422235 (MDP 3.0 - Implied Book): 'Implied book updates are denoted by tag 269-MDEntryType=E (implied bid) and F (implied offer).' 'CME Group provides a 2-deep best bid and ask in the market for each implied-eligible futures contract.' Implied entries carry SecurityID, RptSeq, MDPriceLevel, MDEntrySize, MDEntryPx — no OrderID field appears in any implied book update. Sequencing rule: 'Implied Book changes are the last update of an event' (and may arrive in a subsequent packet if not included initially).

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457422235?expand=body.view

**Implied IN vs implied OUT definitions, and outrights match before spreads.**

Wiki 457095346 (Implied Orders): implied IN is 'an order CME Globex identifies as existing in the spread market based on orders in the outright market'; implied OUT is 'an order CME Globex identifies as existing in the outright market based on orders in the spread market'. Wiki 457096650 (Futures Implied Order Matching Priority): 'Outrights (generation 0) always trades first, then followed by spreads (1st generation).' So real outright orders in the MBO book have matching precedence over implied liquidity generated from spread orders at the same price.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457095346?expand=body.view

**SPREAD LEGS DO NOT GET A TRADE SUMMARY. A spread execution prints tag 269-MDEntryType=e (Electronic Volume) in each leg instead.**

Wiki 457418925 (MDP 3.0 - Trade Summary) verbatim: 'The Trade Summary market data entry (tag 269-MDEntryType=2) message for legs of spread trades is NOT disseminated, but an Electronic Volume update (tag 269-MDEntryType=e) message is sent.' This is the single most important fact for anyone reconstructing per-instrument traded volume from MBO/trades: SR3 and Treasury outright volume built ONLY from Trade Summary prints will be materially understated, because calendar-spread and butterfly activity legs into the outrights with volume updates only. Reconciling MBO-derived outright volume against exchange volume REQUIRES the e-type electronic volume stream.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457418925?expand=body.view

**Exchange-listed spread instruments have their OWN MBO book, quoted at the spread differential price.**

MBO FIX FAQ (wiki 457223111) verbatim: 'Are spreads included in the MBO files?' — 'MBO for Exchange-listed spread products is included for both futures and options spreads.' 'How are spreads prices reflected in the MBO files?' — 'The MBO records for exchange-listed spreads contain the price as it is entered through CME Globex, which is the spread differential price.' So an SR3 calendar spread (e.g. SR3H6-SR3M6) is a first-class instrument_id in GLBX.MDP3 mbo with its own resting orders and its own queue, priced in differential ticks — NOT synthesized from leg books.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457223111?expand=body.view

**tag 1142-MatchAlgorithm code letters: A=Allocation, F=FIFO, T=FIFO with LMM, S=FIFO with Top Order and LMM, C=Pro-Rata, K=Configurable, O=Threshold Pro-Rata, Q=Threshold Pro-Rata with LMM, V=Institutional Prioritization.**

Wiki 457218479 (Supported Matching Algorithms) table. Descriptions: Allocation (A) 'An enhanced pro-rata algorithm that incorporates a priority (top order) to the first incoming order that betters the market' — stages are top-order allocation, pro-rata with minimum 2-lot allocation, then FIFO for residual. FIFO (F) uses 'price and time as the only criteria for filling an order'; the page notes orders lose priority if quantity increases, price changes, or account number changes. FIFO with LMM (T) 'Enhanced FIFO algorithm that allows for LMM allocations prior to the FIFO allocations'. Pro-Rata (C) 'Fills orders according to price, order lot size and time'. Configurable (K) 'Combines steps used with other CME Match Algorithms' in sequence: TOP, LMM, Split (FIFO/Pro-Rata), Leveling, then FIFO. Institutional Prioritization (V) is a 'Two pass FIFO algorithm that provides matching priority to Globex Firm IDs (GFIDs) in the same Institution Group.'

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457218479?expand=body.view

**Exact matching-algorithm STEP mechanics: pro-rata formula, 2-lot minimum, round-DOWN, and FIFO residual.**

Wiki 457218521 (CME Globex Matching Algorithm Steps). Pro Rata allocation formula verbatim: '{Displayed working quantity of an order} / {Total working lots present} * {Match quantity} >= PR Min = allocation'. 'Fractional lots received are rounded down prior to allocation.' Orders receiving less than PR Min get zero in that step; if allocated size is less than two it is rounded to zero. Pro Rata 'will always be followed by either a FIFO step or Leveling and FIFO steps'. LMM: match quantity x LMM percentage, 'guaranteed their percentage of the match quantity rounded down to no less than one lot'; if insufficient quantity for all LMMs, 'tiebreak is based on entry times of the participating orders'. Leveling (K only): distributes pro-rata rounding remainders, 'at most one lot' per qualifying order, tiebreak by working quantity size then earliest timestamp. TOP: order receives 'all fills up to its Top MAX parameter', and only lots filled 'after the order rests in the market count against the running total'. Split step: quantity is split between a FIFO step and a Pro Rata step per product parameters; the two percentages always sum to 100%.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457218521?expand=body.view

**PRIMARY SOURCE: all Treasury futures calendar spreads and the 2-Year/3-Year butterfly spreads use the 'K' algorithm with pro-rata allocation; the residual step changed from Leveling to FIFO on 2021-09-29.**

CME SER-8867, 'Modification of Residual Allocation Step in All Treasury Futures Calendar Spreads and Certain Butterfly Spreads', issued 2021-09-29: CBOT will modify the residual allocation step in the matching algorithms of all Treasury futures calendar spreads and the two short-term note (2-Year and 3-Year) butterfly spreads with a pro-rata allocation; the 'K' algorithm is utilized for each of the Treasury futures calendar and butterfly spreads, and the Exchange will amend the residual allocation of pro-rata from 'Leveling' to 'FIFO'. This is direct primary evidence that ZN/ZF/ZB/ZT CALENDAR SPREADS are pro-rata-based, NOT FIFO — so a FIFO queue model applied to Treasury calendar spread MBO books is wrong even where the outright is FIFO. Retrieved via search summary of the PDF (the PDF itself timed out on direct fetch); the algorithm letter and the Leveling->FIFO change are consistent across two independent retrievals.

*Source:* https://www.cmegroup.com/notices/ser/2021/09/SER-8867.pdf

**GROUND-TRUTH VERIFICATION PATH: read tag 1142-MatchAlgorithm per instrument from Databento's definition schema field `match_algorithm` rather than trusting any document.**

databento/dbn record.rs, InstrumentDefMsg: `match_algorithm` is a `c_char` with doc comment 'The matching algorithm used for the instrument, typically FIFO.' This is CME's tag 1142 passed through verbatim, so the letter codes are exactly A/F/T/S/C/K/O/Q/V from the CME table above. Since it is per-INSTRUMENT (not per-product-family), it resolves SR3 vs SR3 calendars vs ZN vs ZN calendars vs TN vs UB in one query, for the exact dates being studied, and catches algorithm changes over the sample. This could not be executed in this session (no DATABENTO_API_KEY in the environment and no local .dbn files found under the ARBS repo), so it remains the recommended first empirical step.

*Source:* https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/record.rs


### secondary

**A FIFO QUEUE MODEL IS NOT UNIFORMLY CORRECT ACROSS THIS PRODUCT SET. The answer is three-way, not one-way.**

(1) PLAUSIBLY FIFO — ZN, ZF, ZB outrights (grouped with ES, NQ, CL as FIFO in Databento's algorithm survey). A pure price-time queue model is defensible here. TN and UB are never named in any source found; treat as unconfirmed. (2) NOT FIFO — ZT outrights, grouped with ZQ and the ags under 'Configurable' (K). A FIFO queue model on ZT is wrong. (3) NOT FIFO — SR3 outrights: 'First assigns a top order percent allocation, followed by pro rata with a minimum allocation of two lots, followed by FIFO', i.e. Allocation (A) mechanics. Queue position does NOT determine fill order for the pro-rata portion; SIZE does. Any SR3 queue-position/fill-probability model built on FIFO will be structurally wrong — a small resting order can be starved regardless of arrival time (allocation < 2 lots rounds to zero), while a large late order gets filled. (4) NOT FIFO — Treasury calendar spreads and 2Y/3Y butterfly spreads use K with pro-rata allocation (see next finding).

*Source:* https://databento.com/blog/cme-matching-algorithms-explained


### inferred

**A PARTIAL FILL retains queue priority — but no fetched CME source states this explicitly.**

Reasoning: (a) the Order Functionalities table enumerates MODIFICATIONS that change priority, and a fill is not a customer modification; (b) a partial fill reduces working quantity, and 'Decrease quantity' is explicitly in the retain column; (c) all CME algorithm steps (FIFO, Pro-Rata, TOP, LMM) presuppose that a partially-filled resting order remains at the front of its level, otherwise TOP MAX accounting ('only lots filled AFTER the order rests count against the running total') would be incoherent. Expected wire behaviour: MDUpdateAction=1 (Change) with reduced MDDisplayQty and UNCHANGED MDOrderPriority. THIS IS THE ONE ASSUMPTION TO VALIDATE EMPIRICALLY against real DBN data before trusting a queue model — see unresolved.

*Source:* Derived from https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457414497 and .../457218521


### Unresolved

- PARTIAL FILL AND PRIORITY: no CME primary source found that explicitly states a partially-filled resting order retains its MDOrderPriority. The MBOFD Book Management page has a quantity-INCREASE example only; the Order Functionalities table covers customer MODIFICATIONS, not fills. VERIFY EMPIRICALLY: in raw MDP3 (not DBN, which drops the field), find a resting order that partially fills and check whether its tag 37707-MDOrderPriority is unchanged in the accompanying MDUpdateAction=1 Change. In DBN, the equivalent check is whether the order's implied queue position relative to same-price neighbours is preserved across the M record that reduces its size.

- SR3 tag 1142 LETTER NOT CONFIRMED FROM CME PRIMARY. The mechanics (TOP % -> pro-rata min 2 -> FIFO residual) match Allocation (A), but the only source naming SR3 is the Databento blog (secondary). A line in one fetch of the CME Supported Matching Algorithms page reading 'SOFR futures specifically use Pro Rata Allocation' did NOT appear in that page's verbatim table and may be summarizer synthesis — it is not being relied on. Resolve via the definition-schema match_algorithm query.

- SR3 / SOFR CALENDAR SPREAD ALGORITHM COMPLETELY UNRESOLVED. SER-8867 covers Treasury calendar spreads only. The one SOFR-adjacent statement found ('SOFR packs and Bundles match via FIFO') covers packs/bundles, not calendar spreads. Since the SR3 calendar spread is likely the primary tradable for this research, this gap is material — resolve via definition-schema match_algorithm on the spread instrument_ids directly.

- TN and UB tag 1142 NOT ESTABLISHED. No source found names TN (Ultra 10-Year) or UB (Ultra Bond) at all. Do not assume they inherit ZN's FIFO. ZT is affirmatively grouped under 'Configurable' (K) rather than FIFO in the only source that enumerates products, so intra-complex heterogeneity is real, not hypothetical.

- LEG-INSTRUMENT MBO BEHAVIOUR ON AN IMPLIED MATCH: it is confirmed that leg Trade Summary is suppressed (Electronic Volume type 'e' sent instead), but no source was found stating whether the leg instrument's MBO book emits Change/Delete records for the real leg orders consumed by an implied-out match. Supporting argument for assuming YES: DBN's own doc comments state that Trade (T) and Fill (F) 'do not affect the book', so at the DBN layer every book mutation must arrive as an explicit M or C record — a leg book therefore cannot silently decay, whatever the trade-reporting suppression does. Practical stance while unconfirmed: trust the MBO book records for leg state, do NOT trust Trade Summary for leg volume.

- EXACT CME WORDING FOR THE OVERLAY ACTION was not obtained. The numeric enum (Overlay=5) is confirmed from SBE-generated source, and the semantics ('when the best price changes, CME sends a single overlay instruction for price level 1') are secondary. The MDP 3.0 - Market by Price - Book Management page (id 457325741) and MDP 3.0 - Book Management (id 457223312) both returned only navigation metadata through the REST body fetch. Low impact for an MBO engine, since MBOFD never uses action 5.

- MBOFD PRODUCT COVERAGE: no source found stating whether MBOFD is disseminated for ALL CME Globex products or a subset. The AutoCert+ webhelp has separate pages titled 'Book Management Messages for MBO (Outright Only)' and 'Implied Book Management Messages for MBO', which hints at per-channel variation; all four cmegroup.com/tools-information/webhelp/* URLs timed out repeatedly and could not be read. Determine coverage empirically from the actual GLBX.MDP3 mbo data per instrument_id.

- The 'Implied Orders - Examples' wiki page (id 457705043) — which would have given worked implied-match examples showing exactly what prints in the leg instruments — could not be read: its content is inside Confluence macros that failed to export ('We've encountered an issue exporting this macro'). Both the Complex Match Example page (457087723) and this one therefore contributed nothing to the spread-to-leg print question.


## Exact CME contract specifications for SR3, ZT, ZF, ZN, TN, ZB, UB — for a hard-coded ProductSpec table in a GLBX.MDP3 MBO analytics engine


### primary-source

**SR3 (Three-Month SOFR) contract unit is $2,500 x contract-grade IMM Index; one basis point per annum = $25 per contract**

Contract specs page: "CONTRACT UNIT: $2,500 x contract-grade IMM Index". Rulebook 46001: "Each contract is valued at $2,500 times the contract-grade IMM Index (Rule 46002.C.)." Rulebook 46002.B: "...each basis point per annum of such interest rate shall be worth $25 per futures contract."

*Source:* https://www.cmegroup.com/markets/interest-rates/stirs/three-month-sofr.contractSpecs.html and CME Rulebook Chapter 460 https://www.cmegroup.com/rulebook/CME/IV/400/460.pdf

**SR3 price quotation is the IMM Index = 100.0000 minus compounded daily SOFR over the Reference Quarter**

Spec page: "contract-grade IMM Index = 100 minus R; R = business-day compounded Secured Overnight Financing Rate (SOFR) per annum during contract Reference Quarter. Reference Quarter: For a given contract, interval from (and including) 3rd Wed of 3rd month preceding delivery month, to (and not including) 3rd Wed of delivery month." Rulebook 46002.C example: "Where the value of such compounded daily SOFR is 2.055 percent per annum, it shall be quoted as an Index value of 97.9450."

*Source:* https://www.cmegroup.com/markets/interest-rates/stirs/three-month-sofr.contractSpecs.html ; https://www.cmegroup.com/rulebook/CME/IV/400/460.pdf

**SR3 OUTRIGHT has a two-tier tick: 0.0025 index points ($6.25) for contracts with four months or less to termination, 0.005 index points ($12.50) otherwise — this is the ONLY product of the seven with a finer front-month tick**

Spec page verbatim: "All contract months with four months or less until last day of trading (as defined in Rulebook section 46002.C): 0.0025 IMM Index points (1/4 basis point per annum) = $6.25. All other contract months: 0.005 IMM Index points (1/2 basis point per annum) = $12.50. Min Final Settle Fluctuation: 0.0001 IMM Index points". Note this tier is scoped by 'four months or less until last day of trading', NOT by 'nearest expiring contract' — several secondary sources word it loosely. Among ZT/ZF/ZN/TN/ZB/UB there is NO front-vs-deferred tick distinction; for the Treasuries the finer tick lives on the calendar spread instead.

*Source:* https://www.cmegroup.com/markets/interest-rates/stirs/three-month-sofr.contractSpecs.html

**CME Rulebook 46002.C defines the SR3 quarter-tick ('four-month') window exactly, by calendar rule**

Verbatim: "The minimum price fluctuation shall be 0.005 Index points, equal to $12.50 per contract, provided that the minimum price fluctuation shall be 0.0025 Index points, equal to $6.25 per contract, for any contract with four months or less until its termination of trading (Rule 46002.G.), where the applicable four-month interval shall be defined so as to begin on, and to include, either (i) the Monday before the third Wednesday of the fourth month preceding the month in which trading in such contract terminates, if such Monday is a Business Day, or (ii) the Business Day next following such Monday, if such Monday is not a Business Day." CME's settlement documentation calls these contracts "quarter tick eligible".

*Source:* CME Rulebook Chapter 460, Rule 46002.C — https://www.cmegroup.com/rulebook/CME/IV/400/460.pdf

**SR3 listing cycle: 39 consecutive March-quarterlies PLUS the nearest 6 serial contract months; trading terminates the business day prior to the 3rd Wednesday of the delivery month**

Spec page verbatim: "LISTED CONTRACTS: Quarterly contracts (Mar, Jun, Sep, Dec) listed for 39 consecutive quarters and the nearest 6 serial contract months"; "TERMINATION OF TRADING: Trading terminates on the business day prior to the 3rd Wednesday of contract delivery month"; "SETTLEMENT METHOD: Financially Settled". Product code SR3 on Globex/ClearPort/Clearing. The 6 serials are a current addition — older secondary sources (incl. CME's own Dec-2024 strategy guide) say only "39 consecutive quarters".

*Source:* https://www.cmegroup.com/markets/interest-rates/stirs/three-month-sofr.contractSpecs.html

**ZT (2-Year T-Note): $200,000 face value; tick 1/8 of 1/32 of one point = 0.00390625 = $7.8125; NO separate calendar-spread tick row**

Spec page verbatim: "CONTRACT UNIT: Face value at maturity of $200,000"; "PRICE QUOTATION: Points and fractions of points with par on the basis of 100 points"; "MINIMUM PRICE FLUCTUATION: 1/8 of 1/32 of one point (0.00390625) = $7.8125 [TAS: Zero or +/- 4 ticks...]". Arithmetic check: 1 point = $2,000 on $200k face, 1/32 = $62.50, 1/8 of 1/32 = $7.8125. Unlike ZN/TN/ZB/UB the page shows a single value with no "Outright:"/"CALENDAR SPREAD" split. Listing: "Quarterly contracts (Mar, Jun, Sep, Dec) listed for 3 consecutive quarters". Termination: "12:01 p.m. CT on the last business day of the contract month". Rulebook CBOT Chapter 21.

*Source:* https://www.cmegroup.com/markets/interest-rates/us-treasury/2-year-us-treasury-note.contractSpecs.html

**ZF (5-Year T-Note): $100,000 face value; tick 1/4 of 1/32 of one point = 0.0078125 = $7.8125; NO separate calendar-spread tick row**

Spec page verbatim: "Face value at maturity of $100,000"; "Points and fractions of points with par on the basis of 100 points"; "1/4 of 1/32 of one point (0.0078125) = $7.8125 [TAS: Zero or +/- 4 ticks...]". Listing: "Quarterly contracts (Mar, Jun, Sep, Dec) listed for 3 consecutive quarters". Rulebook CBOT Chapter 20 (per SER-8867 Exhibit 1). Confirmed by direct DOM inspection that no "Outright:"/"CALENDAR SPREAD" split exists on this page.

*Source:* https://www.cmegroup.com/markets/interest-rates/us-treasury/5-year-us-treasury-note.contractSpecs.html

**ZN (10-Year T-Note): $100,000 face; OUTRIGHT tick 1/2 of 1/32 = 0.015625 = $15.625; CALENDAR SPREAD tick 1/4 of 1/32 = 0.0078125 = $7.8125**

Spec page shows two labelled rows verbatim — "Outright: 1/2 of 1/32 of one point (0.015625) = $15.625" and "CALENDAR SPREAD: 1/4 of 1/32 of one point (0.0078125) = $7.8125". Contract unit "Face value at maturity of $100,000"; quotation "Points and fractions of points with par on the basis of 100 points"; listing "Quarterly contracts (Mar, Jun, Sep, Dec) listed for 3 consecutive quarters". Rulebook CBOT Chapter 19.

*Source:* https://www.cmegroup.com/markets/interest-rates/us-treasury/10-year-us-treasury-note.contractSpecs.html

**TN (Ultra 10-Year T-Note): $100,000 face; OUTRIGHT tick 1/2 of 1/32 = 0.015625 = $15.625; CALENDAR SPREAD tick 1/4 of 1/32 = 0.0078125 = $7.8125**

Spec page verbatim rows: "Outright: 1/2 of 1/32 of one point (0.015625) = $15.625"; "CALENDAR SPREAD: 1/4 of 1/32 of one point (0.0078125) = $7.8125". Contract unit "Face value at maturity of $100,000"; "Points and fractions of points with par on the basis of 100 points"; listing "Quarterly contracts (Mar, Jun, Sep, and Dec) listed for 3 consecutive quarters"; termination "12:01 p.m. CT, 7 business days prior to the last business day of the contract month"; last delivery "Last business day of the contract month". Rulebook CBOT Chapter 26. TAS product code TNT.

*Source:* https://www.cmegroup.com/markets/interest-rates/us-treasury/ultra-10-year-us-treasury-note.contractSpecs.html

**ZB (U.S. Treasury Bond / 30-Year): $100,000 face; OUTRIGHT tick 1/32 of one point = 0.03125 = $31.25; CALENDAR SPREAD tick 1/4 of 1/32 = 0.0078125 = $7.8125**

Spec page verbatim rows: "Outright: 1/32 of one point (0.03125) = $31.25"; "CALENDAR SPREAD: 1/4 of 1/32 of one point (0.0078125) = $7.8125". Contract unit "Face value at maturity of $100,000"; "Points and fractions of points with par on the basis of 100 points"; listing "Quarterly contracts (Mar, Jun, Sep, Dec) listed for 3 consecutive quarters". Rulebook CBOT Chapter 18. Note the spread tick is 1/4 of the outright tick, i.e. a 4:1 reduction.

*Source:* https://www.cmegroup.com/markets/interest-rates/us-treasury/30-year-us-treasury-bond.contractSpecs.html

**UB (Ultra U.S. Treasury Bond): $100,000 face; OUTRIGHT tick 1/32 of a point = 0.03125 = $31.25; CALENDAR SPREAD tick 1/4 of 1/32 = 0.0078125 = $7.8125**

Spec page rows: "Outright: 1/32 of a point (0.03125) = $31.25" and "CALENDAR SPREAD: 1/4 of 1/32 of a point (0.0078125) = $7.8125". Contract unit "Face value at maturity of $100,000"; "Points and fractions of points with par on the basis of 100 points"; listing "Quarterly contracts (Mar, Jun, Sep, Dec) listed for 3 consecutive quarters"; grade "U.S. Treasury bonds with remaining term to maturity of not less than 25 years from the first day of [the contract month]". Rulebook CBOT Chapter 40.

*Source:* https://www.cmegroup.com/markets/interest-rates/us-treasury/ultra-t-bond.contractSpecs.html

**Treasury futures CALENDAR SPREADS are SecuritySubType RT (Reduced Tick), not SP — CME's own worked example is literally ZNZ9-ZNH0**

CME Client Systems Wiki verbatim: "RT Reduced Tick — SecuritySubType=RT. The Reduced Tick Calendar Spread is the simultaneous purchase (sale) of one product with a nearby expiration and a sale (purchase) of the same product at a deferred expiration... Spreads with SecuritySubType RT will have a smaller tick than their corresponding outright legs... Example: Instrument Symbol = ZNZ9-ZNH0, Leg1 = +1 ZNZ9, Leg2 = -1 ZNH0. Quantity/side ratio of the legs is +1:-1... The Reduced Tick Calendar Spread Trade Price is = Leg1 - Leg2. All prices below are in a fractional pricing format." SR3 calendar spreads by contrast are Globex strategy code SP (per CME's SOFR Globex Strategy Guide).

*Source:* https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457089763/Spreads+and+Combinations+Available+on+CME+Globex

**Calendar spreads (SP and RT) are quoted as a PRICE DIFFERENCE: spread price = Leg1 - Leg2, nearby minus deferred; may be zero or negative**

CME wiki, SP Standard Calendar, verbatim: "The listing convention of this spread and its corresponding symbol is to have the nearby expiration first and the deferred expiration second, creating a differential spread of nearby expiration minus the deferred expiration... Leg1 (buy leg) must be the nearest expiration; Leg2 (sell leg) must be the deferred expiration. Quantity/side ratio of the legs is +1:-1. Buying a Standard Calendar Spread buys leg1, sells leg2... This spread can trade at zero and at a negative price... The Standard Calendar Spread Trade Price is = Leg1 - Leg2." Leg price assignment uses an anchor leg (most recent price update; else nearest expiration), and firms may override via SLEDS in Clearing, so Clearing leg prices can differ from Globex-assigned leg prices.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457089763/Spreads+and+Combinations+Available+on+CME+Globex

**Listed BUTTERFLY (SecuritySubType BF) is quoted as Leg1 - (2 x Leg2) + Leg3 with leg ratio +1:-2:+1, symbol form '<PRODUCT>:BF <M1>-<M2>-<M3>'**

CME wiki verbatim: "Quantity/side ratio of the legs is +1:-2:+1"; "Buying a Butterfly buys leg1, sells 2 * leg2, buys leg3"; "Selling a Butterfly sells leg1, buys 2 * leg2, sells leg3"; "The Butterfly Trade Price is = Leg1 - (2 * Leg2) + Leg3". Leg2 must be the middle expiration at twice the quantity; Leg3 the most deferred. Expiration differentials must be sequential and equal: "Leg 2 month - Leg 1 month = Leg 3 month - Leg 2 month" (a Broken Butterfly relaxes this). CME's own examples use exactly the symbol form in the question: "SR1:BF M9-U9-Z9" and (CME SOFR strategy guide) "SR3:BF Z4-H5-M5" with Leg1=+1 SR3Z4, Leg2=-2 SR3H5, Leg3=+1 SR3M5. Leg-price assignment: Leg1 and Leg2 are anchor legs at fair market price, Leg3 = Trade Price + 2*Leg2 - Leg1, with daily-limit fallbacks; when a recalculated Leg2 is off-tick, "Round one leg up to the nearest on tick price and round one leg down to the nearest on tick price."

*Source:* https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457089763/Spreads+and+Combinations+Available+on+CME+Globex ; https://www.cmegroup.com/articles/2024/sofr-futures-and-options-globex-strategy-guide.html

**CME's nine supported match algorithms and their tag 1142 codes**

Verbatim table (Algorithm / tag 1142-MatchAlgorithm value): Allocation = A; FIFO = F; FIFO with LMM = T; FIFO with Top Order and LMM = S; Pro-Rata = C; Configurable = K; Threshold Pro-Rata = O; Threshold Pro-Rata with LMM = Q; Institutional Prioritization Match Algorithm = V. "Algorithms apply to both outright and implied matching." The K (Configurable) step order is fixed regardless of which steps are enabled: TOP, LMM, Split, FIFO, Pro Rata, Leveling, FIFO. "Details of the K algorithm parameters and configuration for each product are available in the GCC Product Reference Sheet."

*Source:* https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457218479/Supported+Matching+Algorithms

**SR3 OUTRIGHT futures match under the Pro Rata / Allocation algorithm (TOP order first regardless of size, then pro-rata with a 2-lot minimum, then FIFO residual); SOFR packs and bundles match FIFO**

CME wiki verbatim: "This match algorithm known as Pro Rata or Allocation Algorithm is applied only to the SOFR futures at CME Group (SOFR packs and Bundles match via FIFO)." Rules: "Top orders are matched first, regardless of size... The Pro Rata algorithm will only allocate to resting orders that will receive 2 or more contracts... allocated decimal quantities are always rounded down... After percentage allocation, all remaining contracts not previously allocated due to rounding considerations are allocated to the remaining orders on a FIFO basis. Outright orders will have priority over implied orders... Implied orders will be then allocated by maturity, with the earliest expiration receiving the allocation before the later expiring contracts." Databento's product survey independently lists "Allocation ... Popular CME products: SR3 outrights" and "FIFO with lead market maker (LMM) ... Popular products: SR3 averaged price bundles" — note the wiki says plain FIFO for packs/bundles while Databento says FIFO-with-LMM for averaged-price bundles; both wordings reported, not merged.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457218479/Supported+Matching+Algorithms ; https://databento.com/blog/cme-matching-algorithms-explained

**ALL Treasury futures CALENDAR SPREADS use the 'K' (Configurable) algorithm; pro-rata allocation is 80% for ZT/Z3N/ZF/ZN/TN and 100% for ZB/UB, with FIFO residual**

CME Special Executive Report SER-8867 (dated Sept 29, 2021; effective Sunday Nov 7, 2021 for trade date Monday Nov 8, 2021), Exhibit 2 - Treasury Futures Calendar Spread Algorithms (Product | Globex Symbol | Algorithm | Pro-Rata Allocation | Residual current -> amended): 2-Year ZT-ZT | K | 80% | Leveling -> FIFO; 3-Year Z3N-Z3N | K | 80%; 5-Year ZF-ZF | K | 80%; 10-Year ZN-ZN | K | 80%; Ultra 10-Year TN-TN | K | 80%; U.S. Treasury Bond ZB-ZB | K | 100%; Ultra T-Bond UB-UB | K | 100%. Body text verbatim: "The 'K' algorithm is utilized for each of the Treasury futures calendar and butterfly spreads. The Exchange will amend the residual allocation of pro-rata from 'Leveling' to 'FIFO.'" 80% pro-rata implies a 20% FIFO / 80% pro-rata split. These parameters are as of the 2021 notice.

*Source:* https://www.cmegroup.com/notices/ser/2021/09/SER-8867.pdf

**Listed Treasury BUTTERFLY spreads exist and use the 'K' algorithm; only ZT:BF and Z3N:BF carry a pro-rata component (60%), all other Treasury butterflies were left unchanged**

SER-8867 Exhibit 3 - Treasury Futures Butterfly Spread Algorithms: 2-Year U.S. Treasury Note Futures | ZT:BF | K | 60% | Leveling -> FIFO; 3-Year U.S. Treasury Note Futures | Z3N:BF | K | 60% | Leveling -> FIFO. Body note verbatim: "The 2-Year and 3-Year butterfly spreads use the 'K' algorithm with a portion of its allocation being pro-rata. The Exchange will amend the residual allocation of pro-rata from 'Leveling' to 'FIFO.' Please note, the balance of the Treasury futures butterfly spreads shall remain unchanged." Note the symbol convention 'ZT:BF' matches the 'ZN:BF M6-U6-Z6' form in the question. ZF/ZN/TN/ZB/UB butterfly algorithms are NOT stated in this notice.

*Source:* https://www.cmegroup.com/notices/ser/2021/09/SER-8867.pdf

**Rulebook chapter map (settles conflicting spec-page links)**

SER-8867 Exhibit 1 gives Contract Title | Commodity Code | Rulebook Chapter: 2-Year ZT/26 -> 21; 3-Year Z3N/3YR -> 39; 5-Year ZF/25 -> 20; 10-Year ZN/21 -> 19; Ultra 10-Year TN -> 26; U.S. Treasury Bond ZB/17 -> 18; Ultra T-Bond UB/UBE -> 40. SR3 is CME (not CBOT) Rulebook Chapter 460. Note the commodity codes 26/3YR/25/21/17/UBE are clearing codes and collide numerically with chapter numbers — do not confuse them.

*Source:* https://www.cmegroup.com/notices/ser/2021/09/SER-8867.pdf

**SR3 listed exchange-traded combination types and their Globex strategy codes**

CME SOFR Futures and Options Globex Strategy Guide (03 DEC 2024): calendar spread = SP; butterfly = BF; double butterfly = DF (ratio +1:-3:+3:-1, e.g. SR3:DF Z4-H5-M5-U5); condor = CF (long leg1 and leg4, short leg2 and leg3); packs and bundles = AB; pack spreads = SB; pack butterflies = BB (launched July 29, 2024, implied functionality on). Pack BPV = $100 per pack; bundle BPV = $100 x number of packs (1st 4 quarterlies $100 ... 1st 40 quarterlies $1,000). Note SR3 calendars are SP, whereas Treasury calendars are subtype RT.

*Source:* https://www.cmegroup.com/articles/2024/sofr-futures-and-options-globex-strategy-guide.html

**SR3 daily settlement explicitly consumes spread and butterfly markets, and rounds VWAPs 'half towards zero' to the nearest tradable tick**

CME wiki verbatim: "The first 10 or 11 (depending on quarter tick eligibility) quarterly 3-Month SOFR (SR3) months settle based upon the bid/ask activity of both outright and spread markets on CME Globex between 13:59:00 and 14:00:00 Central Time (CT)... Spreads to be considered in this manner are 3 month calendars, 6 month calendars, 9 month calendars, 12 month calendars, 3 month butterflies, and 12 month butterflies." And: "all VWAPs calculated in the above procedure will be rounded to the nearest tradable tick, following a symmetric - 'round half towards zero' - rounding convention. For instance, a VWAP of 99.6525 of a non-quarter tick eligible outright will be rounded to 99.650. A spread VWAP of -12.25 will be rounded to -12.0." The units of the '-12.25 -> -12.0' spread example are not stated on the page; do not infer the SR3 spread tick from it.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457219181/SOFR

**The definitive per-instrument source for spread/butterfly ticks and match algorithms is the Globex security definition (tag 969 MinPriceIncrement, tag 1142 MatchAlgorithm) or CME's Globex Product Reference Sheet**

CME's GCC Product Resources page points to https://www.cmegroup.com/globex/files/globex-product-reference-sheet.xls, described as carrying, per instrument, "implied eligibility, matching algorithms (TOP, FIFO, Pro-rata), price bands, non-reviewable ranges, protection points, spread types, maximum quantities, and symbols", including "Top order percent allocation minimum/maximum, FIFO percent allocation, pro-rata percent allocation, and algorithm leveling components". This file was NOT downloaded (downloading requires the user's explicit authorization). Equivalently, Databento's `definition` schema on GLBX.MDP3 exposes min_price_increment and match_algorithm per instrument_id. Checked locally: the only DBN file present is C:\Users\chris\Downloads\glbx-mdp3-20260715.mbo.dbn.zst (mbo schema), which carries no tick-size or match-algorithm fields.

*Source:* https://cmegroupclientsite.atlassian.net/wiki/display/EPICSANDBOX/GCC+Product+Resources


### secondary

**Treasury OUTRIGHT match algorithms differ across the complex: ZN, ZF and ZB are FIFO while ZT is Configurable (K)**

Databento product survey (Aug 1, 2025) verbatim: under "First in, first out (FIFO)" — "Popular products: ES, NQ, ZN, ZF, ZB, CL outrights. Volume: 70.3%"; under "Configurable" — "Popular CME products: ZT, ZQ, ZC, ZS, ZW outrights. Volume: 12.7%". This ZT-vs-rest distinction matters for a matching simulator: ZT outrights carry a pro-rata component while ZN/ZF/ZB do not. Secondary source only — CME's own per-product parameters live in the Globex Product Reference Sheet (.xls) and in tag 1142 of each security definition.

*Source:* https://databento.com/blog/cme-matching-algorithms-explained


### inferred

**ZT and ZF calendar spreads almost certainly tick at the same increment as their outrights ($7.8125), i.e. they are not reduced-tick**

Reasoning: (a) direct DOM inspection of both spec pages confirms neither carries the "Outright:" / "CALENDAR SPREAD" split that ZN, TN, ZB and UB all carry — the ZT row is a single value "1/8 of 1/32 of one point (0.00390625) = $7.8125" and the ZF row a single value "1/4 of 1/32 of one point (0.0078125) = $7.8125"; (b) every reduced calendar-spread tick CME publishes for this complex lands on exactly $7.8125 (ZN, TN, ZB, UB all = 1/4 of 1/32 = $7.8125), and ZT's and ZF's OUTRIGHT ticks are already $7.8125 — so there is no room left to reduce. $7.8125 appears to be CME's floor tick value for the Treasury complex. This is an inference from the absence of a row, not a published statement.

*Source:* https://www.cmegroup.com/markets/interest-rates/us-treasury/2-year-us-treasury-note.contractSpecs.html ; https://www.cmegroup.com/markets/interest-rates/us-treasury/5-year-us-treasury-note.contractSpecs.html


### Unresolved

- SR3 calendar spread (SP) minimum price increment and dollar value. Not stated on the contract specs page, not in Rulebook Chapter 460 (which covers only the outright), and not in CME's SOFR Globex Strategy Guide. Do NOT extrapolate the 0.0025/0.005 outright tiers to spreads. The only public clue is the settlement page's rounding example, quoted without interpretation: 'A spread VWAP of -12.25 will be rounded to -12.0' — the units of that number are not stated. Resolve via tag 969 in the security definition (Databento `definition` schema) or the Globex Product Reference Sheet .xls.

- SR3 butterfly (BF), double butterfly (DF) and condor (CF) minimum price increments and dollar values. Nowhere on the public web that this sweep could find. Resolve via tag 969.

- Treasury BUTTERFLY (BF) minimum price increments for ZT, ZF, ZN, TN, ZB, UB. The CME contract specs pages publish only outright and calendar-spread ticks. SER-8867 confirms listed Treasury butterflies exist (ZT:BF, Z3N:BF named explicitly) but states no tick. It is plausible but UNVERIFIED that the BF tick equals the reduced calendar-spread tick ($7.8125); do not hard-code that without checking tag 969.

- Match algorithm for SR3 CALENDAR SPREADS and BUTTERFLIES. The CME wiki says only 'This match algorithm known as Pro Rata or Allocation Algorithm is applied only to the SOFR futures at CME Group (SOFR packs and Bundles match via FIFO)' — SR3 calendar spreads and flies are simply not addressed. Ambiguous as written; resolve via tag 1142 per instrument.

- Match algorithm for TN and UB OUTRIGHTS. The Databento product survey names ZN/ZF/ZB under FIFO and ZT under Configurable, but never mentions TN or UB. FIFO by analogy with ZN/ZB is a guess, not a source.

- Whether SER-8867's K-algorithm parameters (80%/100% calendar-spread pro-rata; 60% for ZT:BF and Z3N:BF) are still current in 2026. That notice is dated Sept 29, 2021 / effective Nov 8, 2021. Live parameters are in the Globex Product Reference Sheet .xls and in each day's security definition.

- Match algorithms for the Treasury butterflies NOT named in SER-8867 (ZF:BF, ZN:BF, TN:BF, ZB:BF, UB:BF). The notice says only that 'the balance of the Treasury futures butterfly spreads shall remain unchanged' — it never states what those algorithms are. Plausibly K with 0% pro-rata (i.e. effectively FIFO), but unstated.

- Whether ZT and ZF calendar spreads are published as SecuritySubType SP or RT. Their tick equals the outright tick (so 'reduced tick' would be a misnomer), but CME's subtype assignment is not published per product; it is only visible in the security definition. This matters if the engine keys spread handling off SecuritySubType.

- Exact SR3 serial-month listing rule beyond the spec page's phrase 'the nearest 6 serial contract months' — Rulebook Chapter 460's contract-months rule was not read (only 46001, 46002.B and 46002.C were captured).

- Full deliverable-grade / quality wording for ZT, TN and UB. The spec-page accordion values truncated at ~100 characters in the accessibility tree and only partial strings were captured; the task did not require these, so they were not re-fetched.


## Adversarial verification


Load-bearing claims were re-checked by an independent agent instructed to refute them and to default to REFUTED when it could not confirm from a primary source.


**CONFIRMED** — DBN flag values: LAST=128, TOB=64, SNAPSHOT=32, MBP=16, BAD_TS_RECV=8, MAYBE_BAD_BOOK=4 — constants in databento/dbn rust/dbn/src/flags.rs named without an F_ prefix, at 1<<7 .. 1<<2, with the quoted doc comments.

Verified against two independent primary sources. (1) https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/flags.rs returns verbatim: `pub const LAST: u8 = 1 << 7; TOB = 1 << 6; SNAPSHOT = 1 << 5; MBP = 1 << 4; BAD_TS_RECV = 1 << 3; MAYBE_BAD_BOOK = 1 << 2;` — unprefixed, exactly as claimed. All six doc comments match the claim word for word, including "Indicates it's the last record in the event from the venue for a given `instrument_id`." and "Indicates an unrecoverable gap was detected in the channel." (2) docs.rs for the published crate dbn 0.65.0 confirms each decimal value independently: LAST=128 (flags.rs line 10), TOB=64 (line 12), SNAPSHOT=32, MBP=16, BAD_TS_RECV=8 (line 19), MAYBE_BAD_BOOK=4 (line 21). Line numbers agree between main and the published crate, so there is no main-vs-release drift and the source is not stale. Two caveats found that do NOT refute the claim as scoped: (a) the Python bindings expose these with an F_ prefix (python/src/lib.rs: `m.add("F_LAST", flags::LAST)?` etc.), so a Python-side reader will see F_LAST/F_TOB/... — but they bind to the identical Rust constants, so no numeric disagreement exists, and the claim scoped its "NOT F_-prefixed" statement to rust/dbn/src/flags.rs, where it is true. (b) The file also defines a seventh flag, PUBLISHER_SPECIFIC = 1 << 1 = 2 ("Used to indicate a publisher-specific event."), added in dbn 0.39.1; the claim omits it but never asserts its list is exhaustive, and every value it does list is correct. The two trailing interpretive sentences are not source assertions but are consistent: CME MDP 3.0 tag 5799 MatchEventIndicator sets its high bit ('10000000') on the last message of an event, which is what LAST conveys, and MAYBE_BAD_BOOK's documented "unrecoverable gap" makes invalidating book/queue state the correct handling.


**CONFIRMED** — tag 37707-MDOrderPriority: LOWER value = HIGHER priority. It is only meaningful WITHIN a (side, price) bucket — you must sort by price first, then by priority. Book build = sort by side and price (bids descending, asks ascending), then apply MDOrderPriority ascending within each level; MBOFD priority is based on iLink receipt sequence within a market segment and is sent that way regardless of the product's match algorithm.

Fetched the cited primary source directly (Confluence REST API, content id 457605721 = "MDP 3.0 - Market by Order - Book Management", version 2, last modified 2024-12-23 UTC). All five quoted sentences appear verbatim, including "For tag 37707-MDOrderPriority, a lower value is a higher priority", "To build the full depth MBOFD order book, each order must be sorted by instrument side, and price (in descending order for Bids and ascending order for Asks). Then the order priority number must be applied only to the orders of the same price/side", "Priority may not be sequential for tag 37707-MDOrderPriority outside of price (tag 270-MDEntryPx)", and "MBOFD Order Priority is based on the sequence of iLink orders received by a CME Globex market segment (tag 1300-MarketSegmentID) and will be sent accordingly regardless of the match algorithm". Decisive independent check: the page's own worked example table ranks OrderID 901 (MDOrderPriority 524123, price 980, Buy) LAST at book priority 4, behind OrderID 111 (653654), 759 (703699) and 201 (765935) all at price 1000 — i.e. the lowest priority number in the table sorts last because its price is worse. A priority-first sort would invert this, so the example only reproduces if price-first / priority-ascending-within-level is correct. Cross-checks that failed to refute: the tag dictionary page (457575222) defines 37707 as uInt64NULL, "Order priority for execution on the order book. A lower value is a higher priority. Value is unique for all orders within a market segment and assigned for all orders" — no absent/null carve-out; the MBOLD page (457638457) uses the identical lowest-to-highest wording, so this is not a rule stated for one product and applied to another; the page is 2024-vintage on the live wiki, not stale. Three scope caveats that do not refute the claim as stated: (1) Databento's normalized MBO schema (DBN MboMsg) does NOT carry tag 37707 — per Databento, ts_event serves the same purpose "except for interest rate options and instruments where there's a LMM" — so on Databento the priority sort must be implemented as arrival/ts_event order and that substitution is documented as imperfect for interest-rate options; (2) because priority reflects iLink receipt sequence regardless of match algorithm, a lower MDOrderPriority does not imply a larger allocation on pro-rata / allocation / LMM products — it orders the displayed book, not the fill split, despite the tag definition's "priority for execution" phrasing; (3) the quoted rules are the MBOFD (full-depth incremental) statements, while MBOLD reaches the same ordering via snapshot overlay rather than incremental book maintenance.


**REFUTED** — CME wiki 457414497 (Order Functionalities) modifiable-parameter table defines the retain/lose priority rule set: priority LOST on account, quantity increase, order type, price, stop trigger price, minimum fill quantity; RETAINED on quantity decrease, displayed quantity, TIF, client order ID, and all other attributes — and this table is "the exact rule set a queue model must implement."

I pulled the raw Confluence REST JSON (not a summarizer's paraphrase) for page 457414497 and stripped the markup. The transcription itself is faithful: the six asterisked parameters are exactly Account*, Increase quantity*, Order type*, Price*, Stop trigger price*, Minimum fill quantity*, and the footnote reads verbatim "*Modifying these parameters will result in a change of priority of the order in the order book." Displayed quantity, Decrease quantity, Client order ID and Time in Force are indeed unasterisked. So the copying is not the defect.

The defect is the claim's load-bearing assertion that this is "the exact rule set a queue model must implement," and specifically the RETAIN row for displayed quantity. Two newer primary-source pages on the same wiki contradict it, in opposite directions:

(1) BrokerTec on CME Globex Market Functionality (page 457316646, v7 2025-12-01), "Display Quantity Processing Rules," states verbatim: "a display quantity increase causes a loss of priority" and "remaining quantity can be increased at any time without loss of priority." Worked Example 7 ("BrokerTec Display Quantity Increase Outside of Workup with Priority Loss") and Example 4 ("BrokerTec Remaining Quantity Increase with No Priority Loss (Non-US Repo)") make it explicit. That inverts BOTH claimed rows: displayed-quantity modification LOSES priority, and quantity increase RETAINS it. US Repo is carved back the other way (Example 5: total quantity increase does lose priority), and workup owners in the private phase are exempt again (Examples 6 and 8).

(2) CME Globex Matching Algorithm Steps (page 457218521, v5 2026-06-02) — the futures/options matching page, and the newest of the three — gives a DIFFERENT and shorter list under "Order Modification Loss of Timestamp Priority with FIFO": "A modified order loses its timestamp priority when any of these values are modified: Increase of working quantity of the order. Change of price. Change of account number." Three items, not six — order type, stop trigger price and minimum fill quantity are absent. The same page also states that for futures/options icebergs, "the Display Quantity order's priority is refreshed to be the lowest of the remaining orders at the price level (order is placed at the end of the queue)" after every match event. A queue model that codes displayed quantity as priority-neutral will be wrong about iceberg replenishment on GLBX.MDP3.

Staleness supports this: the Order Functionalities page is v4, last edited 2025-04-22, and sits under Order Management as generic prose; both contradicting pages are newer (2025-12-01 and 2026-06-02) and are the venue-specific matching documents. The general table is not venue-qualified and is not reconciled with them.

Two smaller fidelity problems. The claim asserts the parameter names are verbatim but drops a qualifier: the source reads "In-Flight Mitigation (first modification only)", not "In-Flight Mitigation". And "all other attributes" is inference dressed as source — the footnote only makes a positive statement about the six asterisked rows; it never asserts that everything else is priority-preserving, and the BrokerTec page proves it is not.

Files with the extracted primary-source text: C:\Users\chris\AppData\Local\Temp\claude\C--Users-chris-clee-ARBS\546c5bd0-3d16-4294-a405-eae00cac5d12\scratchpad\of.txt (page 457414497), \457218521.txt (Matching Algorithm Steps), \457316646.txt (BrokerTec).

*Correction:* Wiki 457414497 (Order Functionalities, v4 2025-04-22) does carry the table as transcribed — six asterisked parameters (Account, Increase quantity, Order type, Price, Stop trigger price, Minimum fill quantity) under the footnote "*Modifying these parameters will result in a change of priority of the order in the order book," with Client order ID, Decrease quantity, Customer handling instruction, Time in Force, ATS indicator, Give-up instructions, Customer of firm flag, Displayed quantity, Order expiration date, Self-Match Prevention ID and instructions, CTI code, and "In-Flight Mitigation (first modification only)" unasterisked.

But it is a generic, venue-unqualified summary, not the rule set a queue model implements, and two rows are wrong once venue is fixed:

- DISPLAYED QUANTITY DOES NOT RETAIN PRIORITY. On BrokerTec (page 457316646), "a display quantity increase causes a loss of priority"; only a display quantity decrease is priority-neutral. On futures/options FIFO (page 457218521), an iceberg's priority is "refreshed to be the lowest of the remaining orders at the price level" after every match event, i.e. it goes to the back of the queue on each replenish.
- QUANTITY INCREASE DOES NOT ALWAYS LOSE PRIORITY. On non-US-Repo BrokerTec instruments, "remaining quantity can be increased at any time without loss of priority." US Repo is the exception where a total quantity increase does lose priority, and workup owners during the private phase can increase display or remaining quantity with no loss at all.

For CME futures and options specifically, the authoritative and more recent statement (page 457218521, v5 2026-06-02) lists only THREE priority-losing modifications under FIFO: increase of working quantity, change of price, and change of account number. It does not list order type, stop trigger price, or minimum fill quantity. A queue model must be built from the venue-specific matching-algorithm pages and reconciled against the MBO PriorityID stream, not from the single generic table on 457414497.


**CONFIRMED** — Overlay IS the book-management model for MBO Limited Depth (MBOLD) — a full restate, not an incremental action. Per CME wiki 457638457: 'MBOLD uses an overlay approach to book management. Overlay book management completely restates the MBOLD book with each new Market Data Snapshot Full Refresh (tag 35-MsgType=W) message.' MBOLD is a distinct product from MBOFD; Databento GLBX.MDP3 mbo is the full-depth (MBOFD) feed.

Fetched the cited page directly (cmegroupclientsite.atlassian.net REST content/457638457?expand=body.view). Title: "MDP 3.0 - Market By Order Limited Depth Book Processing", version 2, last updated 2024-12-26T20:09:20.862Z. The page contains verbatim: "Unlike standard CME Globex MDP incremental book processing, MBOLD uses an overlay approach to book management." and "Overlay book management completely restates the MBOLD book with each new Market Data Snapshot Full Refresh (tag 35-MsgType=W) message." Both quoted sentences match character-for-character, and the same wording was reproduced independently via a second retrieval route of the same page. Adversarial checks all came back negative: (1) No numeric assertion to be wrong — the only literal is tag 35-MsgType=W, printed as the source prints it; corroborating page facts are top-10 bid/ask orders, interleaved bid-ask encoding, implied orders excluded, MBOLD sent before MBP within a market event. (2) No cross-product misapplication — the source itself separates MBOLD from MBOFD, notes CME rebranded legacy Globex MBO to "Market By Order Full Depth (MBOFD)", and a distinct page "MDP 3.0 - Market Data Incremental Refresh - MBOFD" confirms MBOFD uses the incremental path, which is exactly the contrast the claim draws. (3) Not stale — v2 dated Dec 2024, present tense, no sunset/coming-soon language. (4) Not inference dressed as fact — it is a direct quotation. (5) Databento sub-claim holds: Databento describes its mbo schema as every order update across the entire order book including queue position, i.e. full-depth MBOFD semantics, not a top-10 limited book. Residual gaps, neither load-bearing: sibling page 457673162 identifies the MBOLD carrier as the SnapshotRefreshTopOrders template (framed for conflated market data groups) but its field table begins at tag 60 and never lists tag 35, so MsgType=W is confirmed only from the prose on 457638457, not from a schema table; and I could not retrieve a Databento template-level mapping table tying mbo to the MBOFD templates, so that leg rests on Databento's own full-depth description.


**CONFIRMED** — Worked MBOFD example confirms a quantity INCREASE re-prices priority: OrderID 555 qty 30->50 moved MDOrderPriority 722095 -> 722787.

Fetched the primary source directly (CME wiki content id 457605721, title "MDP 3.0 - Market by Order - Book Management") and re-fetched it a second time byte-identically (53,668 chars of body.view), then extracted the tables row by row rather than trusting a summarizer.

Every number in the claim is verbatim correct. The section is headed "Modify Order - Update MBOFD Quantity of Resting Order Example" and its intro reads "The order will lose priority at the price level (950)." The Modify data block is 270-MDEntryPx=950, 37-OrderID=555, 37706-MDDisplayQty=50, 37707-MDOrderPriority=722787, 37708-OrderUpdateAction=1 (Update). The closing line is verbatim: "Order quantity is increased from 30 to 50. OrderID 555 loses priority in the book, and Order Priority changes from 722095 to 722787."

The book-position assertion also holds. Starting book bid side at 950: 722095/555/qty 30 at Book Priority 6, then 722512/721/qty 100 at Book Priority 7. Final book: 722512/721/qty 100 at Book Priority 6, then 722787/555/qty 50 at Book Priority 7. So 555 does move to a lower priority position among orders at price 950. 722787 - 722095 = 692 exactly, matching the claimed "~692 higher".

The IMPORTANT NEGATIVE RESULT holds too. The page carries exactly three example headings: "Limit Order - New Action Example", "Modify Order - Update MBOFD Quantity of Resting Order Example", and "Cancel Resting Order - MBOFD Update Only Example". The strings "decreas", "reduc" and "retain" each occur 0 times in the full page text, so there is genuinely no quantity-decrease worked example and the retain-on-decrease rule cannot be sourced from this page's examples.

Two imprecisions in the DETAIL that do not falsify the claim but should not be propagated as source text. First, "the Order Functionalities table above": the string "Functionalit" appears 0 times on 457605721, so that table is on a different page and the pointer is misleading if read as same-page. Second, "priority numbers are a monotonically increasing per-market-segment sequence" is inference, not source text -- "monotonic" appears 0 times; the page states only that "MBOFD Order Priority is based on the sequence of iLink orders received by a CME Globex market segment (tag 1300-MarketSegmentID)", and it twice cautions that "Priority may not be sequential for tag 37707-MDOrderPriority outside of price (tag 270-MDEntryPx)". That caution concerns cross-price ordering rather than assignment order, so it does not contradict the inference, but the inference is carrying more certainty than the primary source supports. The claim's core factual assertion is confirmed.


**CONFIRMED** — Implied orders are not in MBO at all — CME does not disseminate implied order book information in Market by Order format.

Verified live at the exact claimed primary source. CME Group Client Systems Wiki content ID 457605721 ("MDP 3.0 - Market by Order - Book Management") returns the quoted sentence verbatim: "Implied order book information is not sent in MBOFD format." The same page confirms the surrounding context is genuine ("CME Globex Market by Order Full Depth (MBOFD) disseminates individual orders and quotes at every price level"; "For MBOFD, there is no maximum number of orders or depth allowed on the book"). The second cited source, wiki 457223111 ("MBO FIX"), returns the corroborating FAQ answer verbatim: "No, orders are not tied to implied prices."

The generalization from MBOFD to "MBO at all" is independently supported, not inferred: the sibling page "MDP 3.0 - Market By Order Limited Depth Book Processing" states "Implied order book information is not sent in MBOLD format." Both MBO variants CME publishes (MBOFD full depth, MBOLD top-10 on the Conflated UDP/TCP groups) exclude implied, so no MBO flavor carries it. No stale-rule, wrong-product, or off-number defect found in the claim sentence.

Two scoping caveats on the DETAIL paragraph, neither of which contradicts the claim:
(1) "Implied liquidity is invisible" is true only of a book built from the MBO repeating group alone, not of the feed. Wiki 457227795 ("MDP 3.0 - Market Data Incremental Refresh - MBP and MBOFD") shows MBP and MBOFD ride the SAME incremental refresh event: repeating group 1 carries MBP entries including MDEntryType "E=Implied Bid" and "F=Implied Offer" (with an event-flag bit for "Last implied quote message for a given event"), while repeating group 2 carries the MBOFD order detail linked by ReferenceID. So a consumer of the same channel does receive implied depth — in MBP form, not MBO form. The correct engine consequence is "implied is not order-attributed and must be read from the MBP side," not "the feed omits implied."
(2) "Every SR3 and Treasury outright with a listed calendar spread" is an unverified sweep. Implied eligibility is a per-instrument security-definition flag (tag 871-InstAttribType=24 with tag 872-InstAttribValue=19), not a product-class guarantee; I did not confirm blanket eligibility across all SR3 and Treasury outrights. The word "every" should be treated as unverified.


**CONFIRMED** — Databento changed CME (GLBX.MDP3) event-boundary normalization: preview 2026-07-07, production 2026-08-08, applied retroactively to the full history; event end is now a separate record carrying F_LAST with action='N', plus per-leg definition records, stat types UPPER_PRICE_LIMIT (17) / LOWER_PRICE_LIMIT (18), implied matching status, and FX spot instrument_class=X.

Primary source https://databento.com/blog/cme-normalization-changes-2026-07 (published 2026-07-07) matches the claim essentially verbatim, verified across three independent fetches with different prompts (consistent, so not a summarizer artifact) and corroborated by web search. Verbatim from the source: "Starting July 7, 2026, we're rolling out a series of improvements to how we normalize data for CME Globex MDP3 (GLBX.MDP3)"; "2026-07-07: Data with the new normalization is available in the preview environment"; "2026-08-08: Data with the new normalization will be available in production from the live and historical APIs"; "The new normalization will replace the current normalization and apply to both live data and the full historical dataset retroactively." On the event boundary, verbatim: "Currently, for events spanning multiple packets, we buffer all MBO records until the packet containing the last event is processed. F_LAST is then set on the final record for each instrument to mark the end of the event. This delays earlier records in the event... records will be published immediately after each packet is processed rather than being buffered until the event is complete. As a result, the final book update will no longer contain F_LAST. Instead, the end of the event for each instrument is marked by a new, separate record with F_LAST and action='N' (None)." Also verbatim: "each strategy leg will have its own definition record, so a strategy with three legs will have three definition records." Every checkable number survived an independent cross-check against the DBN source of truth (github.com/databento/dbn, rust/dbn/src/enums.rs): UpperPriceLimit = 17 ("The exchange defined upper price limit"), LowerPriceLimit = 18, Action None = b'N' ("Has no effect on the book, but may carry flags or other information"), InstrumentClass FxSpot = b'X'. Adversarial probes that did NOT break the claim: (1) I searched specifically for a slipped/delayed production date and found none — the 2026-08-08 date stands as published, though note the blog is future-tense ("will be available"), so the claim's "in production today" is the source's published schedule with no delay found, not an independently observed live flip; (2) stat types 17/18 already existed in DBN (added 0.47.0, 2026-01-20, for XCBF.PITCH) — but the blog calls them new to the CME statistics schema, which is what the claim says, and their pre-existence confirms the numbers are the real enum values rather than invented; (3) the claim's "old behaviour" quotation stitches two source sentences into one with "and...which" — semantically identical, not a factual error; (4) the F_LAST-removal sentence is not explicitly scoped to multi-packet events, so the operational consequence (a builder flushing on F_LAST seen on a real A/C/M record stops flushing) follows from the source as written. No product/rule mismatch, no stale rule, and nothing material dressed up as fact.


**REFUTED** — A PARTIAL FILL retains queue priority — but no fetched CME source states this explicitly. Expected wire behaviour: MDUpdateAction=1 (Change) with reduced MDDisplayQty and UNCHANGED MDOrderPriority, to be validated empirically against real DBN data.

The claim is refuted by its own cited source, on four counts.

(1) A CME source DOES state a partial-fill priority rule explicitly — and it states the OPPOSITE, for Display Quantity (iceberg) orders. Page 457414497... rather, page 457218521 ("CME Globex Matching Algorithm Steps"), one of the two the claim cites, says verbatim: "After a match event is complete, a Display Quantity order is refreshed with the lesser quantity of either: 1. The Display Quantity of the Order. 2. The remainder of the order if equal to or less than the Display Quantity. 3. The remainder of the Display Quantity in the event of a partial fill on that Display Quantity. In addition, the Display Quantity order's priority is refreshed to be the lowest of the remaining orders at the price level (order is placed at the end of the queue)." Item 3 is explicitly the partial-fill case and the priority-refresh sentence applies to all three. The same page adds "All refreshes of the Display Quantity order will not have TOP status," and "A Display Quantity order can become TOP only at the time of entry." So for iceberg orders a partial fill LOSES both queue priority and TOP status. The claim states a universal rule and misses an explicit, documented exception — a rule true for one order type applied to all.

(2) Reasoning (b) misstates the table. Page 457414497 ("Order Functionalities") has NO "retain column." Priority-losing parameters are marked with a trailing asterisk (Account*, Increase quantity*, Order type*, Price*, Stop trigger price*, Minimum fill quantity*) under the footnote "*Modifying these parameters will result in a change of priority of the order in the order book." "Decrease quantity" is simply unmarked. Absence of a mark is not an explicit statement of retention — this is inference dressed as fact.

(3) Reasonings (a) and (b) are mutually contradictory: (a) argues the modification table cannot bear on fills because a fill is not a customer modification; (b) then uses that same table as affirmative evidence about fills.

(4) Reasoning (c) is a non sequitur, and the wire/validation half is not executable. TOP MAX ("only lots filled after the order rests count against the running total") is a counter of filled lots against a cap; TOP is a designated status, not a queue position, so the rule is coherent either way. And the stated test cannot be run in DBN: Databento omits MDOrderPriority from normalized MBO as CME-specific behaviour, recommending users infer it from ts_event — while explicitly warning ts_event is NOT equivalent to MDOrderPriority for interest rate options and instruments with an LMM, i.e. exactly the STIR/SR3 universe at issue. DBN MBO also has no MDUpdateAction or MDDisplayQty fields (it carries an `action` char and `size`), so "MDUpdateAction=1 with unchanged MDOrderPriority" is unobservable in DBN.

*Correction:* For an ORDINARY (non-Display-Quantity) resting order, a partial fill does retain queue priority: CME enumerates the priority-losing triggers as modifications to Account, Increase quantity, Order type, Price, Stop trigger price, and Minimum fill quantity, and a fill is not among them. But this is NOT universal. CME states explicitly that a Display Quantity (iceberg) order's priority "is refreshed to be the lowest of the remaining orders at the price level (order is placed at the end of the queue)" after a match event — including the case of "a partial fill on that Display Quantity" — and that "all refreshes of the Display Quantity order will not have TOP status." So a partially filled iceberg goes to the BACK of its price level and forfeits TOP. Note also that CME's modification table has no "retain" column (priority-losing rows carry an asterisk; others are merely unmarked), and TOP MAX accounting implies nothing about queue position since TOP is a status, not a slot. Finally, this cannot be validated as described against DBN: Databento deliberately omits MDOrderPriority from normalized MBO and carries no MDUpdateAction/MDDisplayQty fields; it advises inferring priority from ts_event while warning that this proxy fails for interest rate options and LMM instruments — precisely the STIR/SR3 products in question. Empirical validation requires raw CME MDP 3.0 MBOFD (tag 37707) or PCAP, not DBN MBO.


**REFUTED** — Implied participation in a trade is detectable arithmetically: aggressor qty != sum of remaining Order Detail qtys means implied orders filled, and the shortfall IS the implied quantity.

I pulled the primary source myself — the raw Confluence storage body of page 457225774 ("MDP 3.0 - Trade Summary Order Level Detail", version 4, last updated 2026-05-07T17:33:53Z), not the rendered summary. Every verbatim quote in the DETAIL checked out exactly, word for word: the tag-32/sum-of-remaining sentence, "Order Details are only sent for the customer orders. Any unreported quantity represents the participating implied orders.", "trades that only involve implied orders are not published in a Trade Summary message, but volume and price statistics are updated real-time.", and both AggressorSide=0 scenarios. The wiki is not being misquoted, and the source is current, not stale.

What is wrong is the headline rule, which drops the precondition that governs it. In the storage HTML the sentence is a CHILD bullet nested under the parent branch "The aggressor quantity (tag 32) in the first Order Detail entry IS equal to the Summary Level fill quantity (tag 271)". The doc gives a coordinate sibling branch — "The aggressor quantity (tag 32) in the first Order Detail entry is NOT equal to the Summary Level fill quantity (tag 271)... the aggressor joined a pool of resting orders and thereby created sufficient quantity to trigger a trade. This scenario can occur in any ratio spread... Examples include IVR and butterfly spreads." In that branch tag 32 necessarily also differs from the sum of the remaining entries (either sum(remaining) = tag 271 != tag 32 by the branch's own definition, or sum(remaining) = 2*tag271 - tag32 if the co-resting same-side fills are enumerated). Either way the claimed signature fires with ZERO implied participation, and the "shortfall" is negative. So the rule false-positives precisely on ratio spreads and butterflies — the instruments where implieds actually live. This is a rule stated for one case and applied to all.

Three further doc-grounded breakers: (1) On an AggressorSide=0 Summary Level there is no aggressor Order Detail entry at all, so "aggressor qty minus sum of remaining" is not even computable; the doc's rule there is different arithmetic — implied = tag 271 minus the sum of ALL Order Detail entries, since "Order Details are only sent for the customer orders". (2) At a scheduled Market Open or a Re-Open after a Velocity Logic Event the doc states "Order Detail entries are non-deterministic", "Both buys and sells are reported", and "The sum of the Order Detail quantities (all tag 32-LastQty values), divided by 2, will equal tag 271-MDEntrySize" — so the shortfall formula returns garbage, and CME explicitly "recommends that customers report the market opening trades or the trades that occur after a Velocity Logic Event at the Summary Level." (3) The claim's own premise defeats its headline: implied-only trades never appear in a Trade Summary message (corroborated on sibling page 457418925, which states the Trade Summary "is only disseminated when at least one actual (non-implied) order participates in the trade"), so implied participation is not fully detectable arithmetically even in principle. Also unmentioned: the page's own scope banner limits all of this to "futures and options and BrokerTec markets".

*Correction:* The arithmetic test is valid only inside one branch, not in general. Correctly stated: for a Summary Level with a DEFINED aggressor (tag 5797-AggressorSide = 1 or 2) AND where the first Order Detail entry's aggressor quantity (tag 32) EQUALS the Summary Level fill quantity (tag 271) — then if tag 32 does not equal the sum of the remaining Order Detail entries' quantity for that Summary Level, customer and implied orders were both filled, and the unreported quantity (the doc's term; it never says "shortfall") is the participating implied quantity; if only one Order Detail entry is present, the aggressor traded against implied orders only. If instead tag 32 does NOT equal tag 271, the inequality means the aggressor joined a pool of resting orders to create sufficient quantity to trigger the trade (ratio spreads such as IVR and butterflies) — that is not evidence of implied participation, and the difference is not an implied quantity. On a Summary Level with tag 5797 = 0 there is no aggressor entry, so implied quantity must instead be derived as tag 271 minus the sum of ALL Order Detail entries; and at a Market Open or Re-Open after a Velocity Logic Event the entries are non-deterministic with both sides reported (sum of all tag 32 = 2 x tag 271), so CME directs that these be processed at the Summary Level only. Finally, trades involving implied orders exclusively are never published in a Trade Summary message, so this arithmetic can never detect them. The entire mechanism is supported only on futures and options and BrokerTec markets.


**CONFIRMED** — EVENT ATOMICITY IS MANDATORY: the MBO book is not valid mid-event. tag 5799-MatchEventIndicator bit 7 marks end of event; bit 0 marks last Trade Summary of the event.

I attempted to refute this and could not; every checkable element matched the cited primary source verbatim.

(1) Book validity. CME wiki content ID 457605721 ("MDP 3.0 - Market by Order - Book Management"), the exact URL cited, contains verbatim: "All MBOFD book updates for an instrument within an event must be processed before the MBOFD book is valid." MBOFD (Market by Order Full Depth) is genuine CME terminology, not a corruption. Same page documents the three data-block actions (New/Update/Delete via tag 37708-OrderUpdateAction or tag 279-MDUpdateAction).

(2) Tag 5799 definition. Both 457575222 ("MDP 3.0 - Market Data Incremental Refresh - MBOFD") and 457227795 ("MDP 3.0 - Market Data Incremental Refresh - MBP and MBOFD") carry verbatim: "Bitmap field of eight Boolean type indicators reflecting the end of updates for a given CME Globex Event". Page IDs are correctly attributed to the correct pages.

(3) Bit positions. Confirmed exactly as claimed, including LSB/MSB labelling: bit 0 (least significant) = "Last Trade Summary message for a given event"; bit 7 (most significant) = "Last message for a given event". Intervening bits (1=last electronic volume, 2=last customer order quote, 3=last statistic, 4=last implied quote, 5=recovery resend, 6=reserved) are consistent across both pages and corroborated independently by the OnixS CME MDP3 handler reference and the EPAM java-cme-mdp3-handler MatchEventIndicator source — so this is not a summarizer echoing my prompt.

(4) The "correctness requirement, not an optimization" framing is not inference dressed as fact; it is CME's own position. The Event Based Market Data Messaging page states that event boundaries are flagged with MatchEventIndicator specifically "to allow applications to apply market data updates transactionally, with explicit knowledge of when market data is consistent for analysis in cases of complex order book updates or multiple instruments affected by a matching event."

No off-by-one in bit numbering, no stale rule, no cross-product misattribution (MBOFD rule is stated on MBOFD pages), no fabricated page ID.

IMPORTANT SCOPING CAVEAT (verified, does not change the verdict): the claim is true of the CME native SBE feed, where tag 5799 exists. It does NOT survive the mapping into Databento DBN, which is what a GLBX.MDP3 MBO numba engine actually consumes. In DBN there is no tag 5799; the semantics land in the 8-bit `flags` field with a DIFFERENT layout (per docs.rs/dbn source): LAST=1<<7=128, TOB=1<<6=64, SNAPSHOT=1<<5=32, MBP=1<<4=16, BAD_TS_RECV=1<<3=8, MAYBE_BAD_BOOK=1<<2=4, PUBLISHER_SPECIFIC=1<<1=2, and bit 0 is UNASSIGNED. Two consequences: (a) testing DBN flags bit 0 for "last Trade Summary" reads a bit that is always zero — that semantic does not exist in DBN; (b) DBN's LAST means "the last record in the event from the venue for a given instrument_id" (per-instrument), whereas CME's raw EndOfEvent marks the end of the whole event, which may span multiple instruments and multiple sequential UDP packets. For per-instrument book building DBN's F_LAST is the correct delimiter to gate on and is in fact more directly usable than CME's raw bit 7; only bit 7 aligns numerically between the two encodings, and even then the scope differs.


**REFUTED** — DBN's MboMsg HAS NO PRIORITY FIELD — the engine must reconstruct queue position itself from record arrival order plus the retain/lose rules. Supporting detail: the MboMsg field list given is "complete" (order_id, price, size, flags, channel_id, action, side, ts_recv, ts_in_delta, sequence); tag 37707-MDOrderPriority is not carried; practical rule: queue position = arrival order within (instrument, side, price), and on action='M' re-queue iff price changed or size increased, retain iff size decreased.

The headline is right but the packaged detail has two independently checkable defects, one of which is a live hazard for this repo's products.

CORRECT (verified at the claimed primary source, rust/dbn/src/record.rs): MboMsg has no priority field, and CME tag 37707-MDOrderPriority is genuinely not carried. Databento's own issue tracker states verbatim: "We currently leave out MDOrderPriority from our normalized MBO messages, due to 2 reasons."

DEFECT 1 — the "complete" field list is not complete, and the omission is the load-bearing one. record.rs shows MboMsg's FIRST field is `pub hd: RecordHeader`, which the claim's list drops. RecordHeader carries length(u8), rtype(u8), publisher_id(u16), instrument_id(u32), and ts_event(u64, "The matching-engine-received timestamp"). ts_event is exactly the field Databento designates as the priority proxy, so the claim omits the field that actually conveys the thing the claim is about. (Also minor: the claim glosses ts_recv as "ns since epoch"; record.rs says "The capture-server-received timestamp" — i.e. capture-server, not matching-engine, which is ts_event.)

DEFECT 2 — "inferred dressed up as fact." The claim states arrival-order-as-priority as an unqualified rule. Databento's actual documented guidance (issues.databento.com, verbatim): "We actually recommend most users to infer MDOrderPriority from ts_event since it makes their order book implementation more reusable for other venues" — BUT "ts_event serves the same purpose as MDOrderPriority for all instruments except for interest rate options and instruments where there's a LMM." That carve-out is not a footnote here: this engine runs on SR3/SFR, i.e. interest-rate products, and CME runs LMM programs on SOFR. The claim propagates a documented failure case as an exact rule.

DEFECT 3 (weaker, but real) — the cited MBO-snapshot line ("Each snapshot record maintains the priority order at every price level") is a statement about SNAPSHOT record emission order; it is used in the claim to "confirm" the general live-incremental ordering mechanism. Different thing.

NOT a refutation ground: the retain/lose modify rule itself (lose on price change or size increase, retain on size decrease) is consistent with everything I found and I did not contradict it — but I could not extract it verbatim from CME's primary wiki (the Atlassian page and Databento's GLBX.MDP3 spec both truncated on fetch). CME primary material does confirm the sort key: "systems must first sort by price (tag 270-MDEntryPx), then by priority (tag 37707-MDOrderPriority)," and that for 37707 a lower value is a higher priority. Treat the modify rule as consistent-but-not-primary-confirmed.

I also checked and DISCONFIRMED a plausible-sounding alternative: order_id is NOT CME's MDOrderPriority repurposed. Databento drops 37707 entirely; order_id is the venue's order ID.

*Correction:* DBN's MboMsg has no priority field, and CME tag 37707-MDOrderPriority is not carried in Databento's normalized MBO — that core is correct. Corrections to the detail:

(1) The complete MboMsg field list is: hd (RecordHeader), order_id (u64), price (i64, 1 unit = 1e-9), size (u32), flags (FlagSet), channel_id (u8), action (c_char), side (c_char), ts_recv (u64, capture-server-received ns since epoch), ts_in_delta (i32, ns before ts_recv that the matching engine sent), sequence (u32). The claim omitted `hd`, which carries length, rtype, publisher_id, instrument_id and ts_event (u64, matching-engine-received ns since epoch).

(2) The reconstruction key is ts_event, not bare record arrival order. Databento explicitly recommends inferring MDOrderPriority from ts_event, ordering within (instrument, side, price).

(3) This inference has a documented exception that must be carried with the rule: per Databento, "ts_event serves the same purpose as MDOrderPriority for all instruments except for interest rate options and instruments where there's a LMM" — confirmed by Databento with CME GCC. For SR3/SFR work, that exception is in scope, so ts_event-ordered queue position is an approximation with known-wrong cases, not ground truth. True priority ordering requires MDOrderPriority from the raw MDP 3.0 feed (sort by price, then by 37707 ascending, lower = higher priority), which DBN does not expose.

(4) The action='M' rule (re-queue on price change or size increase; retain on size decrease) is CME's MDP 3.0 book-management convention and is consistent with available sources, but was not verifiable verbatim from CME's primary wiki page in this check — treat it as unconfirmed-primary rather than established.


**CONFIRMED** — tag 37-OrderID is stable for the life of the order; MDOrderPriority is the field that churns. Order identity is safe as a hash key across modifications; queue position is not derivable from OrderID.

Verified against CME's own wiki via the REST API (rendered pages truncate; I pulled and de-HTMLed the raw body JSON).

1) The quoted Q&A is verbatim-accurate. Page 457223111 "MBO FIX" (version 5, last updated 2025-06-10, so not stale) reads: "Should an Order ID (Tag37) change during the life of an order? / No, tag37 should stay the same for each order until it has been cancelled or filled. If there is any modification other than a cancel or fill the Order ID stays the same." The claim reproduces the first sentence exactly and drops the second, which only reinforces it.

2) The MDOrderPriority half is independently confirmed on page 457605721 "MDP 3.0 - Market by Order - Book Management" by the sharpest available test — the priority-LOSING modify, which is precisely the case that would have refuted the claim. "OrderID 555 quantity is increased from 30 to 50. The order loses priority in the book." The incremental refresh carries tag 37-OrderID = 555 (unchanged) with tag 37708-OrderUpdateAction=1, and the page states: "OrderID 555 loses priority in the book, and Order Priority changes from 722095 to 722787." Same order ID, new priority. My adversarial hypothesis that Globex mints a new OrderID on loss of priority is directly falsified by CME's own worked example.

3) "Queue position is not derivable from OrderID" is confirmed by the same page: "Priority may not be sequential for tag 37707-MDOrderPriority outside of price (tag 270-MDEntryPx). Therefore, systems must first sort by price (tag 270-MDEntryPx), then by priority (tag 37707-MDOrderPriority) to determine the book order." CME's own table has book priority 1/2/3 held by OrderIDs 111/759/201 — non-monotonic in OrderID.

4) "Safe as a hash key" holds on scope: MDP 3.0 defines tag 37 as "Unique ID assigned by CME Globex to identify orders" (page 457575222, v3, 2026-02-19) and iLink defines it as "Globally unique identifier for each order assigned by the exchange" (page 715587819, v7, 2026-03-18). Note the asymmetry the claim gets right: it is tag 37707 whose uniqueness is scoped — "Value is unique for all orders within a market segment."

Other refutation angles run and closed: no product mismatch (the rule holds across MBOFD and MBOLD, both of which use the same 37/37707 semantics; implied orders are simply not disseminated in either); no stale-rule problem (all pages current, newest 2026-02/03); no off numbers to catch since the claim asserts no tick size, dollar value, or flag value.

Two caveats that qualify but do not refute. (a) The citation under-covers: page 457223111 never mentions MDOrderPriority at all, so the single claimed URL supports only the first half; the second half required page 457605721. (b) Consumer-side, Databento does not expose tag 37707 in its normalized MBO at all and tells users to infer priority from ts_event — which if anything strengthens the claim's final point that queue position must come from somewhere other than OrderID.


**REFUTED** — DBN Action enum: A=Add, C=Cancel, M=Modify, R=Clear, T=Trade, F=Fill, N=None, with the quoted verbatim doc comments and Side=Ask b'A'/Bid b'B'/None b'N'; T and F do not affect the book; and therefore every book mutation caused by a fill arrives as an explicit M or C record IN THE SAME EVENT, so the book cannot silently decay.

The enum half is exactly right and I confirmed it byte-for-byte, but the appended guarantee in the final sentence is inference presented as primary-source fact, and its timing qualifier is false. (1) Mis-sourced: I downloaded rust/dbn/src/enums.rs from main (1745 lines) and grepped it — it contains no statement about compensating records, and a full tree listing of databento/dbn shows the repo has NO book-building code whatsoever (only csv_serialize_duplicate_encode_orders.rs test fixtures match 'order'). The cited file cannot support the guarantee. (2) Empirically false as stated: Databento's own worked example (docs/examples/order-book/order-actions, GLBX.MDP3, ES, order_id 6410543150678) shows the fill and its compensating record in DIFFERENT packets — F size 7 at 10:59:50.544746948 but M at .544805832 (~59us later), and the terminal F size 3 at .545075499 but C at .545093643 (~18us later). The control that makes this decisive: three other F/M pairs in the same run share ts_recv EXACTLY (.544805832, .544880884, .544927788), proving ts_recv is packet-granular, so the two mismatches are real packet boundaries and not clock jitter. (3) Causality inverted: Databento's order-tracking page states 'Trade and Fill actions do not affect the book because all fills will be accompanied by cancel actions that do update the book' — the normalization guarantee is the cause and book-neutrality the consequence, not the reverse as claimed. The same page adds the rule the claim omits: F_LAST denotes the last record for an instrument in an event and 'The book state should only be examined after a record with F_LAST set.' Verified as correct: all seven Action variants at enums.rs:318-341 with those exact byte values and exact doc comments (no eighth variant), and Side at enums.rs:273 with Ask=b'A', Bid=b'B', None=b'N'; source is current on main, not stale. Incidentally the claim's 'M or C' is more accurate than Databento's own prose, which says only 'cancel' while their example plainly uses M for partial fills.

*Correction:* The DBN Action enum is exactly as quoted — verified on main in rust/dbn/src/enums.rs lines 318-341: Modify=b'M' ('An existing order was modified: price and/or size.'), Trade=b'T' ('An aggressing order traded. Does not affect the book.'), Fill=b'F' ('An existing order was filled. Does not affect the book.'), Cancel=b'C', Add=b'A', Clear=b'R', None=b'N' — exactly seven variants; and Side (line 273) is Ask=b'A', Bid=b'B', None=b'N'. T and F are indeed book-neutral. But the reason is the reverse of the claim: per Databento's order-tracking docs, T and F do not affect the book BECAUSE fills are separately accompanied by book-updating records — the normalization guarantee is the cause, not the consequence. That compensating record is an M for a partial fill or a C for a full fill, and it is NOT guaranteed to arrive in the same event or packet as the F: in Databento's own GLBX.MDP3 example the first F (size 7) precedes its M by ~59us and the terminal F (size 3) precedes its C by ~18us, each at a distinct ts_recv, while other pairs in the same run share ts_recv exactly. Consequently a consumer must gate on the F_LAST flag — 'The book state should only be examined after a record with F_LAST set' — and must not assume a fill and its book update are co-located in one event. Note also that this pairing behavior is a venue-normalization property observed on GLBX.MDP3, not something the DBN enum definition asserts or guarantees across all datasets.


**CONFIRMED** — MBP and MBOFD arrive in ONE Incremental Refresh message with two repeating groups, joined by tag 9633-ReferenceID.

Verified against the cited primary source and independently corroborated by the SBE schema; every tag number and every quoted string matches.

(1) CITED SOURCE, fetched directly from CME's Atlassian REST API (content 457227795, version 3, last updated 2026-04-20 — current, not stale). Title: "MDP 3.0 - Market Data Incremental Refresh - MBP and MBOFD". It states the message "is sent for book updates that include both Market by Price (MBP) and Market by Order Full Depth (MBOFD) updates" and "maps to the MDIncrementalRefreshBook template in the SBE MDP Core Message schema". Tag 37705-NoOrderIDEntries carries the exact description quoted in the claim ("Repeating group of MBO book updates included in an event. Repeating group used for MBP and MBOFD combined updates."), and tag 9633-ReferenceID the exact description quoted ("Reference to corresponding Price and Security ID, sequence of MD entry in the message"). The sibling processing page (457095907) states plainly that "Tag 9633-ReferenceID is used to link the MBOFD repeating group to the MBP repeating group" in the combined template ID 46.

(2) INDEPENDENT CORROBORATION — CME MDP 3.0 SBE schema v1.13 (obtained from the Open-Markets-Initiative mirror; a third-party mirror, so it is corroboration rather than the sole leg — the claimed CME source was fetched directly and agrees). MDIncrementalRefreshBook46 is ONE message containing exactly TWO repeating groups: group id 268 NoMDEntries (MDEntryPx 270, MDEntrySize 271, SecurityID 48, RptSeq 83, NumberOfOrders 346, MDPriceLevel 1023, MDUpdateAction 279, MDEntryType 269, TradeableSize 37719 — all five RG1 fields the claim names are present) and group id 37705 NoOrderIDEntries (OrderID 37, MDOrderPriority 37707, MDDisplayQty 37706, ReferenceID 9633, OrderUpdateAction 37708). The schema's description of 9633 is byte-for-byte identical to the wiki's and to the claim's quote.

ADVERSARIAL CHECKS THAT FOUND NOTHING: no off-by-one or wrong tag number (268, 37705, 9633 all exact); no cross-product rule transfer (the page, the template and the claim are all scoped to the combined MBP+MBOFD message); no staleness (page v3 dated 2026-04-20; template 46 present in the current v1.13 schema); the quoted descriptions are verbatim source text, not inference dressed as fact.

TWO NON-BLOCKING NUANCES, neither of which changes the verdict:
- Tag 9633 is typed uInt8NULL in the schema, i.e. nullable, so "links each order entry back to its MBP price-level entry" is marginally strong at the edges. I deliberately do not assert a mechanism for when it is null — I looked for one on the Market by Order Book Management page (457605721) and the page does not state it, so any such explanation would be unverified. The claim's own DETAIL correctly conveys the positional "sequence of MD entry in the message" semantics.
- Two related templates coexist but are outside the claim's scope and do not contradict it: MDIncrementalRefreshOrderBook47 is MBO-only (single 268 group, no 37705 and no 9633), and MDIncrementalRefreshBookLongQty64 is the long-quantity twin of the combined message with the identical two-group + 9633 structure.


**CONFIRMED** — tag 1142-MatchAlgorithm code letters: A=Allocation, F=FIFO, T=FIFO with LMM, S=FIFO with Top Order and LMM, C=Pro-Rata, K=Configurable, O=Threshold Pro-Rata, Q=Threshold Pro-Rata with LMM, V=Institutional Prioritization (per CME wiki 457218479, Supported Matching Algorithms).

Fetched the cited primary source directly (curl on https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457218479?expand=body.view). Page id 457218479, title "Supported Matching Algorithms", version 2, last updated 2025-02-11 — current, not stale. Its "Supported Algorithms" table (header literally reads "tag 1142-MatchAlgorithtm Value", a CME typo) contains exactly the nine rows claimed, with exactly the claimed letters: Allocation A, FIFO F, FIFO with LMM T, FIFO with Top Order and LMM S, Pro-Rata C, Configurable K, Threshold Pro-Rata O, Threshold Pro-Rata with LMM Q, Institutional Prioritization Match Algorithm V. All DETAIL quotes verify verbatim or as faithful paraphrase: Allocation is "an enhanced pro-rata algorithm that incorporates a priority (top order) to the first incoming order that betters the market" with stages top-order percent allocation / pro-rata with minimum allocation of two lots / FIFO for residual; FIFO "uses price and time as the only criteria for filling an order" and lists the three re-queue triggers (increase quantity, change price, change account number); T is an "enhanced FIFO algorithm that allows for LMM allocations prior to the FIFO allocations"; K "combines steps used with other CME Match Algorithms" in the order TOP, LMM, Split (FIFO/Pro Rata), Leveling, FIFO; V is a "two pass FIFO algorithm that provides matching priority to Globex Firm IDs (GFIDs) in the same Institution Group". Adversarial checks that did NOT break it: the retired "N=NYMEX FIFO with LMM" appears in no current CME page; the letters are unchanged across the MDP 3.0 Security Definition pages.

TWO CAVEATS the parent should carry forward, neither of which falsifies a stated pairing:

(1) COMPLETENESS — the claimed nine are not the full tag 1142 value space on the wire. The MDP 3.0 Security Definition pages document values absent from the Supported Matching Algorithms page: "P=Size Priority" (MDP 3.0 - Market Data Security Definition - FX, id 457327502, which enumerates only F, V, P) — and EBS Size Priority Matching (id 457421972) states outright that "The code 'P' for the Size Priority matching algorithm is sent via tag 1142-MatchAlgorithm of the MDP 3.0 - Security Definition (tag 35-MsgType=d) message"; and "Y" (MDP 3.0 SecDef Futures, id 457327569, enumerates F,K,C,A,T,O,S,Q,Y with Y="Eurodollar options" — itself a stale label since Eurodollars are delisted; the Options SecDef page, id 457575167, carries the same slot as Y="SOFR options"). A Databento/MDP decoder built from the claim's nine letters will fail to decode P and Y. Also note the SecDef pages spell S as "FIFO with TOP and LMM" rather than "FIFO with Top Order and LMM", and per-asset-class enumerations are narrower than the master list (Fixed Income and Spreads SecDef pages list F only).

(2) SOURCE QUIRK — the page's Pro-Rata section body does not name Pro-Rata; it literally reads "The FX Calendar algorithm fills orders according to price, order lot size and time" and "The FX Calendar algorithm follows these stages to match trades". The claim's quoted words are verbatim but the subject is normalized to Pro-Rata. Defensible (section heading is "Pro-Rata" and the table maps Pro-Rata to C), and it looks like a CME copy-paste artifact rather than a claim error — but it is a light case of a quote being tidied.


**REFUTED** — Exact CME Globex matching-algorithm STEP mechanics per wiki 457218521: Pro Rata formula '{Displayed working quantity of an order} / {Total working lots present} * {Match quantity} >= PR Min = allocation'; fractional lots rounded down; a 2-lot minimum such that an allocated size less than two is rounded to zero; Pro Rata always followed by FIFO or Leveling+FIFO; LMM guaranteed percentage rounded down to no less than one lot with entry-time tiebreak; Leveling (K only) distributing rounding remainders at most one lot each, tiebreak working quantity then earliest timestamp; TOP receives all fills up to Top MAX with only post-resting fills counting; Split divides quantity between FIFO and Pro Rata percentages summing to 100%.

I pulled the primary source directly (Confluence REST API, content 457218521, version 5, last modified 2026-06-02) and rendered the full body to text (475 lines, saved at C:\Users\chris\AppData\Local\Temp\claude\C--Users-chris-clee-ARBS\546c5bd0-3d16-4294-a405-eae00cac5d12\scratchpad\cme457218521.txt). Nine of the ten claim elements check out verbatim against that page: the Pro Rata formula '{Displayed working quantity of an order} / {Total working lots present} * {Match quantity} >= PR Min = allocation'; 'Fractional lots received are rounded down prior to allocation.'; 'Any orders that would execute less quantity than the PR Min will not get any fills in the Pro Rata step.'; 'the Pro Rata step will always be followed by either a FIFO step or Leveling and FIFO steps'; 'LMMs, by participating, are guaranteed their percentage of the match quantity rounded down to no less than one lot.'; 'the tiebreak is based on entry times of the participating orders'; 'Leveling is unique to the K algorithm' with 'at most one lot' and tiebreaks 'Working quantity of the order at the time of distribution. Earliest Timestamp.'; 'The TOP step entitles one order to all fills up to its Top MAX parameter' and 'Only lots filled after the order rests in the market count against the running total'; 'Split is expressed in a percentage of FIFO/Pro Rata totaling 100%.'

The one failing element is the '2-lot minimum'. It fails on both scoping and sourcing. (a) Sourcing: the sentence 'if an allocated trade quantity is less than two lots, it is rounded down to zero' does not appear anywhere on 457218521 -- a grep for 'less than two|two lot|rounded down to zero' returns only unrelated Split and Leveling example text. It actually appears on a different page, 457218479 ('Supported Matching Algorithms', version 2), under the Allocation (A) algorithm. (b) Scoping: 457218521 states the opposite of a fixed 2 -- 'The Pro Rata step includes a parameter called Pro Rata Minimum. This is configured by CME Group as the minimum allocation eligible to participate in the Pro Rata step.' The number 2 appears only as an example given: 'The Pro Rata Minimum for this contract is 2.' Page 457218479 confirms the variance across algorithms: A is 'Pro-rata with minimum allocation of two lots' (and is the algorithm applied to SOFR futures), C is 'Pro-rata with a minimum allocation' (no number), S and Q are 'Pro-rata with configurable minimum allocation', and the K algorithm's Pro Rata step is described with no minimum at all -- 'All fills are rounded down to the nearest integer (which may be zero).' So a per-product/per-algorithm parameter has been hardened into a universal step mechanic and attributed to a page that does not say it. This is the 'rule stated for one product but applied to another' failure mode, and it is one of the four headline items in the claim, so the claim as stated is refuted despite the rest being accurate.

*Correction:* Every step mechanic in the claim is verbatim-accurate against wiki 457218521 (v5, 2026-06-02) EXCEPT the 2-lot minimum. Correct statement: the Pro Rata Minimum (PR Min) is a per-product parameter 'configured by CME Group as the minimum allocation eligible to participate in the Pro Rata step' -- it is not fixed at 2. Orders whose computed allocation is below their product's PR Min receive nothing in the Pro Rata step (they may still be picked up by the following Leveling and/or FIFO steps). The page's Pro Rata worked example merely happens to use a contract where 'The Pro Rata Minimum for this contract is 2'. The sentence 'if an allocated trade quantity is less than two lots, it is rounded down to zero' comes from a different page, wiki 457218479 ('Supported Matching Algorithms'), and describes the Allocation (A) algorithm specifically -- the algorithm CME applies to SOFR futures ('The Pro Rata algorithm will only allocate to resting orders that will receive 2 or more contracts'; SOFR packs and bundles match FIFO). Threshold Pro-Rata (S) and Threshold Pro-Rata with LMM (Q) use a 'configurable minimum allocation', and the Configurable (K) algorithm's Pro Rata step is documented with rounding down to the nearest integer 'which may be zero' and no stated minimum. So the number 2 is correct for SR3/SOFR futures under algorithm A, but it is neither a universal Pro Rata step mechanic nor sourced from 457218521. Two further nuances from the primary source that the claim omits: the algorithm matrix footnote states 'Leveling can be optionally on or off for K', and in the Split step 'Lots designated to FIFO will be at least the percentage expressed for FIFO', i.e. FIFO is rounded UP to the next whole lot above its designated percentage.


**CONFIRMED** — Implied liquidity is disseminated only in MBP, as tag 269-MDEntryType=E (implied bid) and F (implied offer), 2 levels deep, with NO OrderID. Sequencing: 'Implied Book changes are the last update of an event' (may arrive in a subsequent packet, which then carries the End of Event indicator).

I pulled the cited page and four other CME primary pages via the Confluence REST API, and every component holds; I could not break it.

1) E/F and 2-deep — verbatim from the cited page 457422235 (MDP 3.0 - Implied Book): "CME Group provides a 2-deep best bid and ask in the market for each implied-eligible futures contract. Implied book updates are denoted by tag 269-MDEntryType=E (implied bid) and F (implied offer)." Also "Client systems should shift current price levels down, and delete any price levels past 2-deep." Independently corroborated by 457227666 (Consolidating Implied and Multiple Depth Books), which shows the implied book at 2 levels and states the implied and multiple-depth books "must be built and managed separately, then consolidated". Eligibility is flagged on the Security Definition via tag 1022-MDFeedType=GBI ("CME Globex Implied Book Depth"), with depth carried in tag 264-MarketDepth.

2) Direction of the enum is right, not reversed — page 457227795 (Market Data Incremental Refresh - MBP and MBOFD, SBE template 46) lists tag 269 MDEntryType type MDEntryTypeBook with values 0=Bid, 1=Offer, E=Implied Bid, F=Implied Offer.

3) No OrderID — on template 46 the implied entries live in repeating group 1, NoMDEntries (tag 268): MDEntryPx 270, MDEntrySize 271, SecurityID 48, RptSeq 83, NumberOfOrders 346, MDPriceLevel 1023, MDUpdateAction 279, MDEntryType 269, TradeableSize 37719. Tag 37-OrderID appears only in repeating group 2, NoOrderIDEntries (tag 37705), which is the MBOFD order-level group. So no OrderID attaches to an E/F entry.

4) "Only in MBP" — this exact word is not in the cited page, but it is supported by two other primary pages rather than inferred: 457638457 (Market By Order Limited Depth Book Processing) states flatly "Implied order book information is not sent in MBOLD format", and 457575222 (Incremental Refresh - MBOFD, the MBO-only template 47) enumerates MDEntryType as only 0=Bid and 1=Offer — no E/F. Implied therefore reaches clients only through the MBP path (template 46 NoMDEntries, plus the MBP Snapshot Full Refresh 35=W, which is still MBP).

5) Sequencing — verbatim: "Implied Book changes are the last update of an event" and "If an event creates implied updates and the implied updates are not included in the initial packet, that packet will contain no End of Event Indicator. Meaning implied updates are included in a subsequent packet which will contain the End of Event indicator." Corroborated structurally by MatchEventIndicator having a dedicated bit for "Last implied quote message for a given event".

Stale-rule check: I searched for any CME advisory changing implied depth away from 2 or adding implied to MBO, and for Databento's July 2026 CME normalization changes. Nothing changes implied dissemination — Databento's 2026-07 change only adds implied *matching* status (IMPLIED_MATCHING_ON/OFF) to the status schema, which is a matching-engine state flag, not implied book content.

Two non-defeating caveats worth carrying: (a) implied entries do sit in a group that has a NumberOfOrders field (tag 346), it is simply null/not meaningful for implied, so "carries only SecurityID/RptSeq/MDPriceLevel/MDEntrySize/MDEntryPx" is a description of what is populated, not of the wire layout; (b) implied is 2-deep per implied-eligible instrument as declared by the GBI feed-type entry in the Security Definition, so a consumer should read tag 264 rather than hardcode 2.


**CONFIRMED** — Implied IN vs implied OUT definitions, and outrights match before spreads. Wiki 457095346: implied IN = 'an order CME Globex identifies as existing in the spread market based on orders in the outright market'; implied OUT = 'an order CME Globex identifies as existing in the outright market based on orders in the spread market'. Wiki 457096650: 'Outrights (generation 0) always trades first, then followed by spreads (1st generation).' So real outright orders in the MBO book have matching precedence over implied liquidity generated from spread orders at the same price.

Fetched both cited Confluence pages directly via the REST API. Quote 1 is verbatim from page 457095346 'Implied Orders' (v5, modified 2026-05-15): "An implied order is an order CME Globex identifies as existing in the spread market based on orders in the outright market (IMPLIED IN) OR, an order CME Globex identifies as existing in the outright market based on orders in the spread market (IMPLIED OUT)." Quote 2 is verbatim from page 457096650 'Futures Implied Order Matching Priority' (v6, modified 2025-05-07), under the 'Generation' heading: "Outrights (generation 0) always trades first, then followed by spreads (1st generation)." Both pages are current, not stale; the claim contains no numeric assertions (tick size, dollar value, flag value, threshold) to be off. The concluding sentence about real-vs-implied precedence is an inference rather than a printed quote, but it is sound and independently supported: the Implied Orders page's basic rule 5 states "Implied quantity in futures markets does not have time priority", and quantity without time priority in a price-time book necessarily fills behind timestamped real orders at the same price; CME's BrokerTec RV page corroborates that implied outrights are "prioritized behind real outright orders in the underlying outright orderbooks at a given price." No primary source shows implied filling ahead of real at the same price. Two scope caveats the claim omits, both stated by CME in info boxes on the priority page, qualify but do not flip it: (1) these priority rules apply to futures markets using the FIFO algorithm - in non-FIFO (pro-rata/allocation) markets CME Globex allocates fills via algorithm steps and applies these rules only as a tie-breaker when implied sources have equal available quantity; (2) "Options priority of implied sources follows different rules." Since the claim concerns futures MBO (e.g. SR3, a FIFO product), both caveats are non-binding here. Documentation nit, not a defect in the substance: the CLAIMED SOURCE field lists only 457095346, but the generation-0 quote comes from 457096650 - page 457095346 contains no occurrence of "generation" at all. The DETAIL text does attribute each quote to the correct page.


**CONFIRMED** — An iceberg / display-quantity REFRESH sends the refreshed tranche to the BACK of the queue — this is distinct from a 'displayed quantity' modify, which retains priority.

Both halves independently confirmed from CME primary documentation.

(1) REFRESH -> back of queue. The claimed source (Confluence 457218521, "CME Globex Matching Algorithm Steps", FIFO section) contains the sentence verbatim: "In addition, the Display Quantity order's priority is refreshed to be the lowest of the remaining orders at the price level (order is placed at the end of the queue)." Retrieved three independent ways (REST body.view, REST body.storage, /wiki/display/EPICSANDBOX/ HTML) plus an independent search snippet — all identical. The surrounding text also confirms the refresh triggers: after a match event the order refreshes to the lesser of the Display Quantity, the remainder of the order, or "the remainder of the Display Quantity in the event of a partial fill on that Display Quantity" — i.e. it applies even to a partial fill of the displayed tranche, so priority loss is not limited to full exhaustion of the tranche.

(2) MODIFY -> priority retained. Not on the cited page; confirmed instead on CME's "iLink Order Cancel Replace - Tag Value Modification" (Confluence 716079235), whose priority table gives: tag 1138-DisplayQty, "Change/add display quantity" -> priority **Maintained**, in the same table where tag 38-OrderQty "Increase order size" -> **Lost**, tag 44-Price (either direction) -> **Lost**, account change -> **Lost**, tag 38-OrderQty "Decrease order size" -> **Maintained**. Retrieved twice (body.view and a row-by-row body.storage transcription), agreeing.

I probed the apparent conflict with the FIFO page's "Increase of working quantity of the order -> loses timestamp priority" and it resolves in the claim's favour: the same page writes "working *displayed* quantity", treating working quantity (total OrderQty) and displayed quantity as distinct, and the tag table settles it by splitting tag 38 from tag 1138.

(3) The modeling implication is independently corroborated by MDP 3.0 Market-by-Order book management: a CME-held ("native") iceberg refresh carries the SAME OrderID as the original order but takes a new tag 37707-MDOrderPriority (systems must sort by price then MDOrderPriority, which "may not be sequential"), and refreshes never carry TOP status. So a Databento/MBO queue model that keys on OrderID and reads replenishment as a same-position size increase commits exactly the error described, and will overstate the iceberg's fill probability.

Scope caveats, neither verdict-bearing: the refresh-to-back rule is documented under the FIFO section (the claim's DETAIL scopes it there correctly); and the table row's "/add" case appears stale relative to an Oct-2020 Globex notice that rejects modifying a resting displayed-quantity order to non-displayed and vice versa — I could not fetch that notice directly (repeated timeouts on cmegroup.com), so treat that wrinkle as unverified. It concerns the "add" variant only, not the "change display quantity on an existing iceberg" case the claim rests on.

No numeric error, cross-product misapplication, or inferred-as-fact defect found.


**CONFIRMED** — Exchange-listed spread instruments have their OWN MBO book in GLBX.MDP3, quoted at the spread differential price — so an SR3 calendar spread is a first-class instrument_id with its own resting orders and its own queue, not synthesized from leg books.

PRIMARY SOURCE CHECK: Fetched https://cmegroupclientsite.atlassian.net/wiki/rest/api/content/457223111?expand=body.view (CME "MBO FIX" wiki page). Both quotes are verbatim and correctly attributed: "MBO for Exchange-listed spread products is included for both futures and options spreads" and "The MBO records for exchange-listed spreads contain the price as it is entered through CME Globex, which is the spread differential price." An independent web-search snippet reproduced the second sentence identically.

REFUTATION ATTEMPTS THAT FAILED:
(1) Wrong-product leap (DataMine file vs MDP 3.0 feed). Dead — the same page states its files are "produced from CME Globex Market Data Platform FIX/FAST feeds" and its layout guides reference "CME MDP 3.0 (Current Production Format)". Same feed Databento captures; the FAQ describes feed content, not a file-format quirk.
(2) MBO coverage excludes SR3 spreads. Refuted empirically (below).
(3) Stale rule / changed behavior. No evidence; Databento's July 2026 normalization change adds per-leg definition records, which presupposes spreads are their own instruments.
(4) A wrong number (tick/unit/flag). The claim asserts no numeric value, so there is nothing to catch it on.

EMPIRICAL CONFIRMATION (decisive, run locally): C:\Users\chris\Downloads\glbx-mdp3-20260715.mbo.dbn.zst — metadata dataset=GLBX.MDP3, schema=mbo, stype_in=parent (SR3.FUT), 1,188 instrument_ids. Breakdown: 46 outrights, 517 calendar spreads, 139 listed butterflies, plus condors/double-flies/bundles. Example SR3U6-SR3Z6 = instrument_id 43410: 95,279 MBO records, 19,788 distinct order_ids, actions {M:53883, A:19200, C:18823, F:2302, T:1070, R:1}, and 18,937 order_ids carrying multi-event Add→Modify…→Cancel lifecycles — i.e. a genuine per-instrument resting queue. Price range -37.5 to +65.5 (median 14.0), differential magnitudes including negatives, versus outright SR3M9 (id 189) at 95.5–98.3 index points. Listed butterfly SR3:BF M7-U7-Z7 (id 20958) likewise: 80,233 records, 10,207 order_ids, prices -6.5 to 8.5. Verification script: C:\Users\chris\AppData\Local\Temp\claude\C--Users-chris-clee-ARBS\546c5bd0-3d16-4294-a405-eae00cac5d12\scratchpad\verify_spread_mbo.py

TWO CAVEATS (do not change the verdict): (a) The same FAQ says "No, orders are not tied to implied prices" — MBO carries only direct/real orders, so the spread's MBO book is NOT the full executable market; implied-in liquidity generated from the leg books is absent from MBO and appears only in MBP. Reconstructing a spread's tradable top-of-book from MBO alone understates available size. (b) The illustrative symbol "SR3H6-SR3M6" would already have expired by the 2026-07-15 dataset date (H6 = Mar-2026); the live equivalents in that file are SR3U6-SR3Z6, SR3Z6-SR3H7, etc. The symbol FORM is exactly right, so this is a cosmetic slip in the example, not an error in the claim.


**REFUTED** — PRIMARY SOURCE: all Treasury futures calendar spreads and the 2-Year/3-Year butterfly spreads use the 'K' algorithm with pro-rata allocation; the residual step changed from Leveling to FIFO on 2021-09-29.

I retrieved and read the actual PDF (cmegroup.com blocked direct fetch with 403/timeouts; obtained via Wayback snapshot 20260517235731, saved at C:\Users\chris\AppData\Local\Temp\claude\C--Users-chris-clee-ARBS\546c5bd0-3d16-4294-a405-eae00cac5d12\scratchpad\SER-8867.pdf).

DATE IS WRONG (the load-bearing error). The notice reads verbatim: "DATE: September 29, 2021 / SER#: 8867" and then "Effective Sunday, November 7, 2021, for trade date Monday, November 8, 2021, The Board of Trade of the City of Chicago, Inc. ... will modify the residual allocation step...". 2021-09-29 is the ISSUE date of the Special Executive Report, not the date anything changed. The Leveling->FIFO switch took effect on trade date 2021-11-08. Given the claim's own stated use case (dating a queue-model regime change in Treasury calendar-spread MBO books), this misclassifies ~40 days of sessions (2021-09-29 through 2021-11-05) as post-change. Corroborated by the CME Globex Notice of October 18, 2021, which states the change effective Sunday November 7 / trade date Monday November 8.

"PRO-RATA ALLOCATION" IS OVERSTATED. The claim (and its rider "pro-rata-based, NOT FIFO") presents the allocation as flatly pro-rata. Exhibit 2 of the notice gives a per-product "Pro-Rata Allocation" column: ZT-ZT 80%, Z3N-Z3N 80%, ZF-ZF 80%, ZN-ZN 80%, TN-TN 80%, ZB-ZB 100%, UB-UB 100%. Exhibit 3 gives ZT:BF 60% and Z3N:BF 60%, and the text says the 2-Year and 3-Year butterflies "use the 'K' algorithm with a portion of its allocation being pro-rata" — not wholly pro-rata. So a pure FIFO model is genuinely wrong for ZB/UB calendar spreads (100% pro-rata), but the note calendar spreads carry a 20% non-pro-rata share and the two butterflies a 40% share (the historical 2014 notice SER for 2Y/3Y/5Y describes this remainder as a 20% FIFO / 80% pro-rata split), and after this change the pro-rata residual step is itself FIFO.

Also worth noting for precision: 'K' is not a pro-rata algorithm per se. CME's Supported Matching Algorithms page (fetched directly) lists K = "Configurable" (distinct from C = Pro-Rata, A = Allocation, O/Q = Threshold Pro-Rata); pro-rata is one configured step within K.

WHAT THE CLAIM GOT RIGHT: the URL is correct and live; the SER number, issue date and subject line match exactly ("Modification of Residual Allocation Step in All Treasury Futures Calendar Spreads and Certain Butterfly Spreads CME Globex Matching Algorithms"); all seven calendar spreads including the bonds (ZT, Z3N, ZF, ZN, TN, ZB, UB) and the ZT/Z3N butterflies are listed with Algorithm = K; and the residual allocation of pro-rata was indeed amended from "Leveling" to "FIFO". One bounded staleness check surfaced no superseding notice.

*Correction:* CME SER-8867 was ISSUED 2021-09-29 but the change took effect Sunday November 7, 2021, for trade date Monday November 8, 2021 — nothing changed on 2021-09-29. The notice covers all seven Treasury futures calendar spreads (ZT-ZT, Z3N-Z3N, ZF-ZF, ZN-ZN, TN-TN, ZB-ZB, UB-UB) and the 2-Year and 3-Year butterfly spreads (ZT:BF, Z3N:BF); every one is listed with Algorithm 'K', which is CME's "Configurable" algorithm (pro-rata is one step inside it, not the whole of it). The pro-rata share is 80% for the note calendar spreads (ZT/Z3N/ZF/ZN/TN), 100% for the bond calendar spreads (ZB/UB), and 60% for the two butterflies — so only ZB/UB spreads are wholly pro-rata; the others retain a non-pro-rata (FIFO) component. What SER-8867 changed was the residual allocation step of the pro-rata portion, from "Leveling" to "FIFO", effective trade date 2021-11-08.


**CONFIRMED** — MBOFD order entries carry only tag 269-MDEntryType 0=Bid and 1=Offer. There is no trade/fill entry type inside the MBO order block; a fill reaches the MBO book only as a Change (reduced 37706-MDDisplayQty) or a Delete, with the execution reported separately in the Trade Summary entry (tag 269-MDEntryType=2) of the same event.

Fetched the cited primary source (Confluence page 457575222, "MDP 3.0 - Market Data Incremental Refresh - MBOFD", v3 last updated Feb 19 2026, space EPICSANDBOX, ancestors ... > MDP 3.0 - Core Schema > MDP 3.0 - Market Data Incremental Refresh) twice, asking for verbatim rows. It states "This message maps to the MDIncrementalRefreshOrderBook template in the SBE MDP Core Message schema" and its single repeating group (268-NoMDEntries) is exactly 37-OrderID, 37707-MDOrderPriority, 270-MDEntryPx, 37706-MDDisplayQty, 48-SecurityID, 279-MDUpdateAction (valid values "0=New; 1=Change; 2=Delete"), 269-MDEntryType type MDEntryTypeBook with valid values "0=Bid; 1=Offer" — no trade or fill entry type, matching the claim tag-for-tag. The consequence also checks out: the sibling Trade Summary page (457227733) shows 269-MDEntryType of type MDEntryTypeTrade with valid value "2=Trade Summary", carrying 270-MDEntryPx, 271-MDEntrySize, 5797-AggressorSide, plus a 37705-NoOrderIDEntries group of 37-OrderID and 32-LastQty — i.e. the execution is indeed reported in a separate Trade Summary entry, elaborating (not contradicting) the claim; Databento's MBO 'T'/'F' actions are synthesized from that Trade Summary group, not from the order block, which is precisely what the claim asserts. Two caveats that do not overturn the verdict. (1) The cited page's valid-values column is literally headed "Valid Values for BrokerTec", which looks like a product-scoping problem — but it is not one: the MDP 3.0 Message Specification page (457323107) lists "MDP 3.0 - Market Data Incremental Refresh - MBOFD" under CME Globex Futures and Options (CME MDP Premium Incremental UDP, and TCP Recovery for UDP), and the MBOLD page (457638457) states "Current CME Globex Market by Order (MBO) functionality will be re-branded to 'Market By Order Full Depth (MBOFD)'". So the message is a Globex futures/options message, not BrokerTec-only. (2) MBOFD is documented in two SBE template forms and the claim's field list only describes one. The combined form, "MDP 3.0 - Market Data Incremental Refresh - MBP and MBOFD" (457227795, MDIncrementalRefreshBook), also listed for CME Globex F&O, carries its MBO updates in a 37705-NoOrderIDEntries group of 37-OrderID, 37707-MDOrderPriority, 37706-MDDisplayQty, 9633-ReferenceID, 37708-OrderUpdateAction — no tag 269 and no tag 279 at all, with price/side/instrument inherited from the referenced MBP entry (whose own 269 valid values are "0=Bid, 1=Offer, E=Implied Bid, F=Implied Offer"). CME's MBO Book Management page (457605721) confirms this: "Depending on the SBE template, either 37708-OrderUpdateAction or tag 279-MDUpdateAction order action will be used for book updates." So the claim's enumerated field list is template-specific rather than universal — but its operative conclusion, that no trade/fill entry type exists inside the MBO order block, holds in both template forms.


**REFUTED** — Read tag 1142-MatchAlgorithm per instrument from Databento's definition-schema field `match_algorithm` (databento/dbn record.rs, InstrumentDefMsg, a `c_char` doc'd "The matching algorithm used for the instrument, typically FIFO"); it is CME's tag 1142 passed through verbatim, so the letter codes are exactly A/F/T/S/C/K/O/Q/V.

I pulled the cited primary source (curl of https://raw.githubusercontent.com/databento/dbn/main/rust/dbn/src/record.rs and .../enums.rs) and it falsifies two of the claim's specifics.

(1) THE CODE SET IS WRONG. The claim says the letter codes are "exactly A/F/T/S/C/K/O/Q/V" (9 values). rust/dbn/src/enums.rs lines 429-473 defines `pub enum MatchAlgorithm` with TWELVE values: `Undefined = b' '` (marked `#[default]`), `Fifo = b'F'`, `Configurable = b'K'`, `ProRata = b'C'`, `FifoLmm = b'T'`, `ThresholdProRata = b'O'`, `FifoTopLmm = b'S'`, `ThresholdProRataLmm = b'Q'`, `EurodollarFutures = b'Y'`, `TimeProRata = b'P'`, `InstitutionalPrioritization = b'V'`, `Allocation = b'A'`. The claim omits `' '`, `'Y'` and `'P'`. The `' '` omission is operationally load-bearing, not cosmetic: it is the enum's `#[default]`, so an unpopulated/absent field decodes to a space rather than erroring — a screen that matches only the 9 claimed letters silently mis-buckets those rows instead of flagging them. `'Y'` is a real CME value (CME Globex notices: 1142=Y was the Eurodollar Option algorithm, migrated to 1142=Q effective 2016-10-23), so a sample reaching back before Oct-2016 hits a code the claim says does not exist.

(2) "CME's tag 1142 passed through verbatim" IS INFERENCE PRESENTED AS PRIMARY-SOURCE. grep for "1142" in record.rs returns ZERO hits; the field's only documentation is the doc comment and a link to databento.com/docs. Nothing in the cited file states the CME tag number or asserts an identity mapping. DBN's `MatchAlgorithm` is Databento's own cross-venue normalized enum (it grew variants over time: `Undefined` and `TimeProRata` added in DBN 0.17.0 on 2024-04-01, `InstitutionalPrioritization` added in 0.33.1 on 2025-04-29, per the repo CHANGELOG), which is why the "verbatim, therefore exactly these letters" step does not follow from the source.

What DID check out, verbatim: record.rs lines 864-868 read `/// The matching algorithm used for the instrument, typically **F**IFO.` then `#[dbn(c_char)] pub match_algorithm: c_char,` inside `pub struct InstrumentDefMsg` (line 657) — type, doc text and struct are exactly as claimed (the claim just drops the `**F**` markdown bolding). The field is also present in `InstrumentDefMsgV1` and `InstrumentDefMsgV2` (compat.rs lines 281 and 617), so the read path is stable across DBN record versions. It is genuinely per-instrument, so the per-instrument discrimination argument stands. `V` is genuinely CME (the enums.rs doc comment links to CME's Institutional Prioritization page). The environment sub-claim is consistent with what I see now: no DATABENTO_API_KEY in env, no .dbn files found under the repo, and only 7 files mention databento at all.

So the recommended procedure is sound; the enumerated value space attached to it is wrong and the "verbatim tag 1142" justification is not in the source.

*Correction:* Reading `match_algorithm` per instrument_id from Databento's definition schema is a sound ground-truth path — the field is real, is a `c_char` in `InstrumentDefMsg` (record.rs:864-868) with the quoted doc comment, and is present in `InstrumentDefMsgV1`/`V2` as well (compat.rs:281, 617), so it works across DBN record versions and does discriminate SR3 from SR3 calendars from ZN from TN/UB per instrument and per date. But: (a) the value space is TWELVE codes, not nine — per rust/dbn/src/enums.rs:429-473 it is `' '` Undefined (the enum's `#[default]`), F Fifo, K Configurable, C ProRata, T FifoLmm, O ThresholdProRata, S FifoTopLmm, Q ThresholdProRataLmm, Y EurodollarFutures, P TimeProRata, V InstitutionalPrioritization, A Allocation. Any query must handle `' '`/Undefined explicitly (it is what an unpopulated field decodes to, not an error), and must expect Y on pre-2016-10-23 Eurodollar-option data (CME moved 1142=Y to 1142=Q effective 2016-10-23). (b) The mapping to CME tag 1142 is a well-supported inference for GLBX.MDP3, not something the cited file states — record.rs contains no reference to "1142"; `MatchAlgorithm` is Databento's own normalized enum that has gained variants over time (Undefined/TimeProRata in DBN 0.17.0, InstitutionalPrioritization in 0.33.1). Treat it as Databento's normalization of the venue field, and confirm the CME letter semantics against CME's own MDP 3.0 tag-1142 table rather than against the DBN doc comments (whose Y variant is labelled "Eurodollar futures" while CME's notices call 1142=Y the Eurodollar *Option* algorithm).
