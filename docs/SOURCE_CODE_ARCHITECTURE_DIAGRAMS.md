# ARBS Architecture - Detailed Mermaid Diagrams

---

## 1. System Architecture Overview

```mermaid
graph LR
    subgraph DataSources["Data Sources"]
        CME["CME Futures<br/>End-of-Day"]
        FRED["Federal Reserve<br/>Economic Data"]
        SDR["SEC SDR<br/>Transaction Data"]
        ERIS["ERIS Derivatives<br/>Pricing"]
        BARCHART["Barchart<br/>Market Data"]
        WEBULL["Webull<br/>Bond Prices"]
        WSJ["Wall Street<br/>Journal"]
    end

    subgraph MDP["Market Data Provider Layer"]
        IRSMDP_BOX["IRSwapsMDP<br/>(IRSwapsMDP.py)"]
        FRBMDP_BOX["FixedRateBondsMDP<br/>(FixedRateBondsMDP.py)"]
    end

    subgraph PRICING["Pricing Engines"]
        QL["QuantLib<br/>Backend"]
        RL["RatesLib<br/>Backend"]
    end

    subgraph QUERY["Query Layer"]
        IRSQUERY["IRSwapQuery<br/>(IRSwapQuery.py)"]
        FRBQUERY["FixedRateBondQuery<br/>(FixedRateBondQuery.py)"]
    end

    subgraph ENGINE["Execution Engine"]
        BACKTEST["QueryDrivenBacktest<br/>(query_engine.py)"]
        STRAT["QueryStrategy<br/>(query_strategy.py)"]
        PORT["QueryPortfolio<br/>(query_portfolio.py)"]
    end

    subgraph TIMESERIES["Timeseries Builder"]
        TB_BOX["TimeseriesBuilder<br/>(TimeseriesBuilder.py)"]
        CACHE_BOX["Cache Layer<br/>(timeseries_cache.py)"]
    end

    DataSources --> MDP
    MDP --> PRICING
    PRICING --> QUERY
    QUERY --> ENGINE
    ENGINE --> TIMESERIES
    STRAT --> QUERY

    style DataSources fill:#e3f2fd
    style MDP fill:#fff3e0
    style PRICING fill:#f3e5f5
    style QUERY fill:#e8f5e9
    style ENGINE fill:#fce4ec
    style TIMESERIES fill:#f1f8e9
```

---

## 2. Data Flow - IR Swaps Backtest

```mermaid
graph TD
    A["Start: fomc_fly_backtest.py<br/>Create Strategy & Backtest Engine"]
    B["QueryDrivenBacktest.run()"]
    C["For each timestep in TimeGrid"]
    D["Strategy.get_orders(now)<br/>→ QueryOrder list"]
    E["For each QueryOrder"]
    F["AddQueryAction adds IRSwapQuery<br/>to portfolio"]
    G["MDP.get_pricer(request)<br/>request=curve_name + timestamp"]
    H["IRSwapsMDP dispatches to fetcher<br/>based on curve name"]
    I["Fetch raw market data<br/>CME/SDR/ERIS/FRED"]
    J["Build curve with pricing engine<br/>QuantLib or RatesLib"]
    K["Return _IRSwapGenericCurve"]
    L["Query.resolve_package<br/>IRSwapStructure→priceables+weights"]
    M["Value metrics computed<br/>NPV, PV01, DV01, etc."]
    N["TimeseriesBuilder captures<br/>results per query"]
    O["Accumulate portfolio<br/>MTM history, PnL"]
    P["Next timestep or end"]
    Q["Return DataFrame/Cube<br/>All results aggregated"]

    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
    I --> J
    J --> K
    K --> L
    L --> M
    M --> N
    N --> O
    O --> P
    P -.->|if more| C
    P -->|if done| Q

    style A fill:#c8e6c9
    style Q fill:#c8e6c9
    style G fill:#ffccbc
    style H fill:#ffccbc
    style I fill:#ffe0b2
    style J fill:#f8bbd0
    style K fill:#f8bbd0
```

---

## 3. Module Dependency Tree

```mermaid
graph TB
    ROOT["ARBS"]

    subgraph CORE["Core Modules"]
        DEF["definitions/"]
        QUERY["Query/"]
        MDP["MDP/"]
        BT["BT/"]
        TB["TB/"]
    end

    subgraph SUPPORT["Support Modules"]
        CACHE["Caching/"]
        UTILS["utils/"]
        RVUTILS["RVUtils/"]
    end

    subgraph NOTEBOOKS["Notebooks"]
        FOMC["fomc_fly_backtest.py"]
        NB["*.ipynb"]
    end

    ROOT --> CORE
    ROOT --> SUPPORT
    ROOT --> NOTEBOOKS

    DEF -.->|defines| QUERY
    DEF -.->|defines| MDP
    QUERY -.->|consumed by| BT
    MDP -.->|consumed by| BT
    BT -.->|drives| TB
    TB -.->|uses| CACHE
    BT -.->|uses| CACHE
    MDP -.->|uses| UTILS
    QUERY -.->|uses| UTILS
    TB -.->|uses| RVUTILS
    NB -.->|uses| FOMC

    style CORE fill:#e1f5ff
    style SUPPORT fill:#f3e5f5
    style NOTEBOOKS fill:#e8f5e9
```

---

## 4. IR Swaps Module Detail

```mermaid
graph TD
    A["definitions/IRSwaps.py<br/>(20+ curve definitions)"]
    B["Query/IRSwaps/"]
    C["Query/Base/BaseQuery.py"]
    D["IRSwapQuery.py<br/>(Main Query Class)"]
    E["IRSwapStructure.py<br/>(OUTRIGHT, CURVE, FLY, etc.)"]
    F["IRSwapValue.py<br/>(NPV, PV01, DV01, CS01, etc.)"]
    G["adapter.py<br/>(Product Adapter)"]
    H["backends/"]
    I["quantlib/"]
    J["rateslib/"]
    K["QLIRSwapCurve.py"]
    L["ql_pricer.py"]
    M["RLIRSwapCurve.py"]
    N["rl_curve_definitions_map.py"]

    A --> D
    C --> D
    D --> E
    D --> F
    D --> G
    E --> H
    F --> H
    G --> H
    H --> I
    H --> J
    I --> K
    I --> L
    J --> M
    J --> N

    style A fill:#fff3e0
    style D fill:#ffcc80
    style E fill:#ffb74d
    style F fill:#ffb74d
    style G fill:#ffa726
    style K fill:#ff7043
    style L fill:#ff7043
    style M fill:#ff7043
```

---

## 5. Market Data Provider Hierarchy

```mermaid
graph TD
    A["MarketDataProvider.py<br/>(Abstract Base)"]
    B["IRSwapsMDP.py"]
    C["FixedRateBondsMDP.py"]

    B1["CME_NY_EOD_LIVE/"]
    B2["SDR_INTRADAY/"]
    B3["GSQUANT/"]
    B4["fixings_cache/"]

    B1A["ql_basic/"]
    B1B["rl_basic/"]
    B1A1["CMEFetcher.py"]
    B1A2["FredFetcher.py"]
    B1A3["ErisFuturesFetcher.py"]
    B1B1["CMEFetcher.py"]
    B1B2["ErisFuturesFetcher.py"]

    B2A["rl_curve_utils/"]
    B2B["rl_usd_sofr_mt_q12/"]
    B2C["rl_usd_ois_stir_q12x12/"]
    B2A1["SDRDataBuilder.py"]
    B2A2["stir_curve_building_utils.py"]
    B2A3["BarchartFetcher.py"]

    C1["WEBULL/"]
    C2["WSJ/"]
    C3["FEDINVEST/"]
    C4["PUBLICDOTCOM/"]
    C5["reference_data_cache/"]

    C1A["WebullFintechFetcher.py"]
    C2A["WSJFetcher.py"]
    C3A["FedInvestFetcher.py"]
    C4A["PublicDotcomDataFetcher.py"]

    A --> B
    A --> C

    B --> B1
    B --> B2
    B --> B3
    B --> B4

    B1 --> B1A
    B1 --> B1B
    B1A --> B1A1
    B1A --> B1A2
    B1A --> B1A3
    B1B --> B1B1
    B1B --> B1B2

    B2 --> B2A
    B2 --> B2B
    B2 --> B2C
    B2A --> B2A1
    B2A --> B2A2
    B2A --> B2A3

    C --> C1
    C --> C2
    C --> C3
    C --> C4
    C --> C5

    C1 --> C1A
    C2 --> C2A
    C3 --> C3A
    C4 --> C4A

    style A fill:#fff3e0
    style B fill:#ffe0b2
    style C fill:#ffe0b2
    style B1A fill:#ffcc80
    style B1B fill:#ffcc80
    style B2A fill:#ffcc80
    style C1A fill:#ffb74d
    style C2A fill:#ffb74d
    style C3A fill:#ffb74d
    style C4A fill:#ffb74d
```

---

## 6. Backtesting Engine Flow

```mermaid
graph TD
    INIT["Initialize:<br/>QueryDrivenBacktest<br/>time_grid, mdp, strategy"]

    MAIN["Main Loop: for t in time_grid"]
    GET_ORDERS["strategy.get_orders(t)<br/>→ List[QueryOrder]"]
    FILTER_ADD["Filter AddQueryAction<br/>orders"]
    FILTER_UNWIND["Filter UnwindOrder<br/>orders"]

    ADD["For each Add order:"]
    ADD_REQ["Build MDP request<br/>from IRSwapQuery"]
    ADD_GET["pricer = mdp.get_pricer(req)"]
    ADD_RESOLVE["resolve_package(pricer)<br/>→ (priceables, weights)"]
    ADD_PORT["Add position<br/>to portfolio"]

    UNWIND["For each Unwind order:"]
    UNWIND_POS["Remove position<br/>from portfolio"]

    VALUE["For each portfolio position:"]
    VALUE_BUILD["Build value map<br/>for metric"]
    VALUE_COMPUTE["Compute metric<br/>NPV, PV01, etc."]

    RECORD["TimeseriesBuilder.record_mtm<br/>captures values"]

    UPDATE["Update portfolio stats<br/>MTM, PnL"]

    NEXT["Next timestep"]

    END["End: Return results<br/>DataFrame/Cube"]

    INIT --> MAIN
    MAIN --> GET_ORDERS
    GET_ORDERS --> FILTER_ADD
    GET_ORDERS --> FILTER_UNWIND

    FILTER_ADD --> ADD
    ADD --> ADD_REQ
    ADD_REQ --> ADD_GET
    ADD_GET --> ADD_RESOLVE
    ADD_RESOLVE --> ADD_PORT

    FILTER_UNWIND --> UNWIND
    UNWIND --> UNWIND_POS

    ADD_PORT --> VALUE
    UNWIND_POS --> VALUE
    VALUE --> VALUE_BUILD
    VALUE_BUILD --> VALUE_COMPUTE
    VALUE_COMPUTE --> RECORD
    RECORD --> UPDATE
    UPDATE --> NEXT
    NEXT -.->|while t < end| MAIN
    MAIN -.->|done| END

    style INIT fill:#c8e6c9
    style MAIN fill:#ffcc80
    style GET_ORDERS fill:#ffb74d
    style ADD_GET fill:#ff7043
    style RECORD fill:#ba68c8
    style END fill:#c8e6c9
```

---

## 7. Query Resolution Pipeline

```mermaid
graph LR
    A["IRSwapQuery<br/>structure_id=CURVE<br/>structure_kwargs={...}"]

    B["Step 1: Edit Query<br/>_edited()"]

    C["Step 2: Get Adapter<br/>get_adapter(product)"]

    D["Step 3: Build Structure Map<br/>adapter.build_structure_map"]

    E["Step 4: Apply Structure<br/>struct_map.apply(struct_id,<br/>**kwargs)"]

    F["Result: Package<br/>(priceables, weights)"]

    G["Step 5: Build Value Map<br/>adapter.build_value_map"]

    H["ValueMap<br/>(struct_id → value_id)<br/>→ metric"]

    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H

    style A fill:#e8f5e9
    style B fill:#c8e6c9
    style C fill:#a5d6a7
    style D fill:#81c784
    style E fill:#66bb6a
    style F fill:#4caf50
    style G fill:#66bb6a
    style H fill:#4caf50
```

---

## 8. Timeseries Builder Architecture

```mermaid
graph TB
    A["QueryDrivenBacktest results<br/>(portfolio positions,<br/>values per timestep)"]

    B["TimeseriesBuilder"]

    C["Per-Query Timeseries"]
    D["product=IRS<br/>structure=CURVE<br/>structure_id=.."]
    E["For each value metric:<br/>NPV, PV01, DV01"]
    F["Build column:"]
    G["(query_signature)<br/>_(metric_name)"]

    H["Annotation Layer"]
    I["Curve snapshots<br/>at each timestep"]
    J["Structure metadata"]
    K["Trade lifecycle<br/>entry/exit dates"]

    L["Cube/DataFrame<br/>Construction"]
    M["Time index:<br/>timesteps"]
    N["Columns:<br/>per metric"]
    O["Values:<br/>computed metrics"]

    P["Output<br/>DataFrame or MultiIndex<br/>Cube"]

    A --> B
    B --> C
    B --> H
    C --> D
    D --> E
    E --> F
    F --> G
    H --> I
    H --> J
    H --> K
    C --> L
    H --> L
    I --> L
    J --> L
    K --> L
    L --> M
    L --> N
    L --> O
    M --> P
    N --> P
    O --> P

    style A fill:#fff3e0
    style B fill:#ffe0b2
    style P fill:#c8e6c9
```

---

## 9. RVUtils Analysis Tools

```mermaid
graph TD
    A["RVUtils/"]

    B["Interpolation/"]
    C["regression.py"]
    D["plt_timeseries.py"]
    E["ust_viz.py"]
    F["Other utils"]

    B1["GeneralCurveInterpolator.py"]
    B2["nss.py<br/>Nelson-Siegel-Svensson"]
    B3["MonotoneConvex.py"]
    B4["SmithWilson.py"]
    B5["Vasicek.py"]
    B6["calibrate.py"]
    B7["Other methods..."]

    C1["Time-series models"]
    C2["Risk models"]
    C3["Statistical tests"]

    D1["Plot timeseries"]
    D2["Plot curves"]
    D3["Plot risk metrics"]

    E1["UST curve viz"]
    E2["Tenor analysis"]

    F1["arbl_hedge_ratios.py"]
    F2["seasonality_utils.py"]
    F3["mean_reversion.py"]

    A --> B
    A --> C
    A --> D
    A --> E
    A --> F

    B --> B1
    B --> B2
    B --> B3
    B --> B4
    B --> B5
    B --> B6
    B --> B7

    C --> C1
    C --> C2
    C --> C3

    D --> D1
    D --> D2
    D --> D3

    E --> E1
    E --> E2

    F --> F1
    F --> F2
    F --> F3

    style A fill:#f3e5f5
    style B fill:#e1bee7
    style C fill:#e1bee7
    style D fill:#e1bee7
    style E fill:#e1bee7
    style F fill:#e1bee7
    style B1 fill:#ce93d8
    style B2 fill:#ce93d8
    style B3 fill:#ce93d8
    style C1 fill:#ce93d8
    style D1 fill:#ce93d8
```

---

## 10. Data Source Integration

```mermaid
graph LR
    subgraph CME_LAYER["CME End-of-Day<br/>(Daily)"]
        CME1["Futures quotes"]
        CME2["Implied rates"]
    end

    subgraph FRED_LAYER["Federal Reserve<br/>(Daily/Weekly)"]
        FRED1["Fed Funds rate"]
        FRED2["OIS rates"]
        FRED3["Swap rates"]
    end

    subgraph SDR_LAYER["SEC SDR<br/>(Tick-by-tick)"]
        SDR1["OTC swap trades"]
        SDR2["Realized spreads"]
        SDR3["Notional flows"]
    end

    subgraph BOND_LAYER["Bond Sources"]
        WSJ1["WSJ quotes"]
        WEBULL1["Webull prices"]
        FEDINVEST1["FedInvest prices"]
    end

    CME_LAYER -->|CMEFetcher| PRICER["Pricing Engine<br/>(QL or RL)"]
    FRED_LAYER -->|FredFetcher| PRICER
    SDR_LAYER -->|SDRDataBuilder| PRICER
    BOND_LAYER -->|Multiple Fetchers| PRICER

    PRICER -->|Pricer object| QUERY["Query Layer"]

    style CME_LAYER fill:#e3f2fd
    style FRED_LAYER fill:#e3f2fd
    style SDR_LAYER fill:#e3f2fd
    style BOND_LAYER fill:#e8f5e9
    style PRICER fill:#fff3e0
    style QUERY fill:#f3e5f5
```

---

## 11. Curve Building Pipeline (SDR_INTRADAY)

```mermaid
graph TD
    A["SDRDataBuilder<br/>(1049 lines)"]
    B["Fetch SDR data<br/>from API/cache"]
    C["Parse swap transactions<br/>Tenor, Side, Rate"]
    D["Group by tenor"]
    E["stir_curve_building_utils<br/>(950 lines)"]
    F["Interpolate between<br/>tenors"]
    G["Build RatesLib curve"]
    H["Add ERIS futures<br/>if available"]
    I["Add SOFR fixings<br/>if available"]
    J["Validate curve<br/>monotonicity, spreads"]
    K["Cache curve<br/>_RLCurveCache"]
    L["Return<br/>_IRSwapGenericCurve"]

    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
    I --> J
    J --> K
    K --> L

    style A fill:#ffcc80
    style B fill:#ffb74d
    style C fill:#ffb74d
    style D fill:#ffb74d
    style E fill:#ff9800
    style F fill:#ff9800
    style G fill:#ff7043
    style H fill:#ff7043
    style I fill:#ff7043
    style J fill:#ff5722
    style K fill:#ff5722
    style L fill:#d84315
```

---

## 12. Fixed Rate Bond Pricing

```mermaid
graph TD
    A["FixedRateBondQuery<br/>cusip=..."]

    B["FRB Adapter"]

    C["FixedRateBondMDP<br/>Route to fetcher"]

    D["Fetcher Selection<br/>Webull/WSJ/etc"]

    E["Fetch bond data<br/>Price, Yield, Accrued"]

    F["FRB Pricer<br/>QL or RL"]

    G["Compute metrics<br/>YTM, Duration, Convexity"]

    H["Return pricer"]

    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H

    style A fill:#e8f5e9
    style B fill:#c8e6c9
    style C fill:#a5d6a7
    style D fill:#81c784
    style E fill:#66bb6a
    style F fill:#4caf50
    style G fill:#4caf50
    style H fill:#2e7d32
```

---

## 13. Caching Strategy

```mermaid
graph TD
    A["Request<br/>curve_name=USD-SOFR-1D<br/>timestamp=2024-01-15"]

    B["Check Pricer Cache<br/>(request signature)"]

    C{Found?}

    D["Return cached<br/>pricer"]

    E["Fetch market data<br/>CME/SDR/FRED/etc"]

    F["Build curve<br/>QL or RL"]

    G["Store in cache<br/>with timestamp"]

    H["Return pricer"]

    I["(Optional) ZODB<br/>persistent cache"]

    A --> B
    B --> C
    C -->|Yes| D
    C -->|No| E
    E --> F
    F --> G
    G --> I
    I --> H
    D --> H

    style A fill:#ffcc80
    style B fill:#ffb74d
    style C fill:#ffb74d
    style D fill:#4caf50
    style E fill:#ff9800
    style F fill:#ff7043
    style G fill:#ff7043
    style H fill:#2e7d32
    style I fill:#ba68c8
```

---

Generated automatically with comprehensive Mermaid diagrams showing all major data flows and architectural relationships.

