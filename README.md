# Dijkies

**Dijkies** is a Python framework for creating, testing, and deploying algorithmic trading strategies in a clean, modular, and exchange-agnostic way.

The core idea behind Dijkies is to **separate trading logic from execution and infrastructure**, allowing the same strategy code to be reused for:

- Historical backtesting
- Paper trading
- Live trading

## Philosophy

In Dijkies, a strategy is responsible only for **making decisions** — when to buy, when to sell, and how much. Everything else, such as order execution, fee calculation, balance management, and exchange communication, is handled by dedicated components.

This separation ensures that strategies remain:

- Easy to reason about
- Easy to test
- Easy to reuse across environments

A strategy written once can be backtested on historical data and later deployed to a real exchange without modification.

## How It Works

At a high level, Dijkies operates as follows:

1. Market data (candles) is fetched from an exchange or data provider
2. A rolling window of historical data is passed to a strategy
3. The strategy analyzes the data and generates buy/sell signals
4. Orders are placed through a standardized execution interface
5. Account state is updated accordingly
6. Results are collected (during backtesting) or executed live


## Key Design Principles

- **Strategy–Executor separation**
  Trading logic is completely decoupled from execution logic.

- **Single interface for backtesting and live trading**
  Switching between backtesting and live trading requires no strategy changes.

- **Explicit state management**
  All balances and positions are tracked in a transparent `State` object.

- **Minimal assumptions**
  Dijkies does not enforce indicators, timeframes, or asset types.

- **Composable and extensible**
  New exchanges, execution models, and risk layers can be added easily.

## Who Is This For?

Dijkies is designed for:

- Developers building algorithmic trading systems
- Quantitative traders who want full control over strategy logic
- Anyone who wants to move from backtesting to production without rewriting code

## What Dijkies Is Not

- A no-code trading bot
- A black-box strategy optimizer
- A fully managed trading platform

Dijkies provides the **building blocks**, not the trading edge.

---

## Quick Start

This quick start shows how to define a strategy, fetch market data, and run a backtest in just a few steps.

### 1. Define a Strategy

A strategy is a class that inherits from `Strategy` and implements the `execute` method.
It receives a rolling dataframe of candles and decides when to place orders.

```python
from dijkies.strategy import Strategy
from dijkies.executors import ExchangeAssetClient
from ta.momentum import RSIIndicator
import pandas as pd


class RSIStrategy(Strategy):
    # Amount of historical data passed into execute()
    analysis_dataframe_size_in_minutes = 60 * 24 * 30  # 30 days

    def __init__(
        self,
        executor: ExchangeAssetClient,
        lower_threshold: float,
        higher_threshold: float,
    ) -> None:
        self.lower_threshold = lower_threshold
        self.higher_threshold = higher_threshold
        super().__init__(executor)

    def execute(self, candle_df: pd.DataFrame) -> None:
        candle_df["rsi"] = RSIIndicator(candle_df.close).rsi()

        previous = candle_df.iloc[-2]
        current = candle_df.iloc[-1]

        # Buy when RSI crosses below lower threshold
        if previous.rsi > self.lower_threshold and current.rsi < self.lower_threshold:
            self.executor.place_market_buy_order(
                self.executor.state.base,
                self.executor.state.quote_available,
            )

        # Sell when RSI crosses above higher threshold
        if previous.rsi < self.higher_threshold and current.rsi > self.higher_threshold:
            self.executor.place_market_sell_order(
                self.executor.state.base,
                self.executor.state.base_available,
            )
```

### 2. fetch data for your backtest
Market data is provided as a pandas DataFrame containing OHLCV candles.

```python
from dijkies.exchange_market_api import BitvavoMarketAPI

market_api = BitvavoMarketAPI()
candle_df = market_api.get_candles(base="XRP", lookback_in_minutest=60*24*365)
```

### 3. Set Up State and BacktestingExecutor
Market data is provided as a pandas DataFrame containing OHLCV candles.

```python
from dijkies.executors import BacktestExchangeAssetClient, State

state = State(
    base="XRP",
    total_base=0,
    total_quote=1000,
)

executor = BacktestExchangeAssetClient(
    state=state,
    fee_limit_order=0.0015,
    fee_market_order=0.0025,
)
```

### 4. Run the Backtest

Use the Backtester to run the strategy over historical data.

```python
from dijkies.backtest import Backtester

strategy = RSIStrategy(
    executor=executor,
    lower_threshold=35,
    higher_threshold=65,
)

backtester = Backtester()

results = backtester.run(
    candle_df=candle_df,
    strategy=strategy,
)

results.total_value_strategy.plot()
results.total_value_hodl.plot()
```
