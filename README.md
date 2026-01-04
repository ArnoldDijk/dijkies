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
# create strategy

from dijkies.executors import ExchangeAssetClient
from dijkies.strategy import Strategy

from ta.momentum import RSIIndicator
from pandas.core.frame import DataFrame as PandasDataFrame

from dijkies.executors import BacktestExchangeAssetClient, State

from dijkies.data_pipeline import DataPipeline, NoDataPipeline


class RSIStrategy(Strategy):
    analysis_dataframe_size_in_minutes = 60*24*30

    def __init__(
        self,
        executor: ExchangeAssetClient,
        lower_threshold: float,
        higher_threshold: float,
    ) -> None:
        self.lower_threshold = lower_threshold
        self.higher_threshold = higher_threshold
        super().__init__(executor)

    def execute(self, candle_df: PandasDataFrame) -> None:
        candle_df["momentum_rsi"] = RSIIndicator(candle_df.close).rsi()

        previous_candle = candle_df.iloc[-2]
        current_candle = candle_df.iloc[-1]

        is_buy_signal = (
            previous_candle.momentum_rsi > self.lower_threshold
            and current_candle.momentum_rsi < self.lower_threshold
        )

        if is_buy_signal:
            self.executor.place_market_buy_order(
                self.executor.state.base,
                self.executor.state.quote_available,
            )

        is_sell_signal = (
            previous_candle.momentum_rsi < self.higher_threshold
            and current_candle.momentum_rsi > self.higher_threshold
        )

        if is_sell_signal:
            self.executor.place_market_sell_order(
                self.executor.state.base,
                self.executor.state.base_available,
            )

    def get_data_pipeline(self) -> DataPipeline:
        """
        Implement this metho
        """
        return NoDataPipeline()
```

### 2. fetch data for your backtest
Market data is provided as a pandas DataFrame containing OHLCV candles.

```python
from dijkies.exchange_market_api import BitvavoMarketAPI

bitvavo_market_api = BitvavoMarketAPI()

candle_df = bitvavo_market_api.get_candles()
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

results = strategy.backtest(
    candle_df=candle_df,
)

results.total_value_strategy.plot()
results.total_value_hodl.plot()
```

## Deployment & Live Trading

Dijkies supports deploying strategies to live trading environments using the **same strategy code** that is used for backtesting. Deployment is built around a small set of composable components that handle persistence, credentials, execution switching, and bot lifecycle management.

At a high level, deployment works by:

1. Persisting a configured strategy
2. Attaching a live exchange executor
3. Running the strategy via a `Bot`
4. Managing lifecycle states such as *active*, *paused*, and *stopped*

---

## Core Deployment Concepts

### Strategy Persistence

Strategies are **serialized and stored** so they can be resumed, paused, or stopped without losing state.

This includes:
- Strategy parameters
- Internal indicators or buffers
- Account state (balances, open orders, etc.)

Persistence is handled through a `StrategyRepository`.

---

### Strategy Status

Each deployed strategy (bot) exists in one of the following states:

- **active** — strategy is running normally
- **paused** — strategy execution stopped due to an error
- **stopped** — strategy has been intentionally stopped

Status transitions are managed automatically by the deployment system.

---

### Executor Switching

One of Dijkies’ key design goals is that **strategies do not know whether they are backtesting or live trading**.

At deployment time, the executor is injected dynamically:

- `BacktestExchangeAssetClient` for backtesting
- `BitvavoExchangeAssetClient` for live trading

No strategy code changes are required.

---

## Strategy Repository

The `StrategyRepository` abstraction defines how strategies are stored and retrieved.

```python
class StrategyRepository(ABC):
    def store(...)
    def read(...)
    def change_status(...)
```

### LocalStrategyRepository

The provided implementation stores strategies locally using pickle.

#### Directory Structure

root/
└── person_id/
    └── exchange/
        └── status/
            └── bot_id.pkl

```python
from pathlib import Path
from dijkies.bot import LocalStrategyRepository

repo = LocalStrategyRepository(Path("./strategies"))

# read

strategy = repo.read(
    person_id="ArnoldDijk",
    exchange="bitvavo",
    bot_id="rsi_bot",
    status="active"
)

# store

repo.store(
    strategy=strategy,
    person_id="ArnoldDijk",
    exchange="bitvavo",
    bot_id="berend_botje",
    status="active"
)

# change status

repo.change_status(
    person_id="ArnoldDijk",
    exchange="bitvavo",
    bot_id="berend_botje",
    from_status="active",
    to_status="stopped",
)
```

This makes it easy to:

- Resume bots after restarts
- Inspect stored strategies
- Build higher-level orchestration around the filesystem

## Credentials Management

Live trading requires exchange credentials. These are abstracted behind a CredentialsRepository.

```python
class CredentialsRepository(ABC):
    def get_api_key(...)
    def get_api_secret_key(...)
```

The local implementation retrieves credentials from environment variables:

```bash
export alice_bitvavo_api_key="..."
export alice_bitvavo_api_secret_key="..."
```

```python
import LocalCredentialsRepository

credentials_repository = LocalCredentialsRepository()
bitvavo_api_key = credentials_repository.get_api_key(
    person_id="alice",
    exchange="bitvavo"
)
```

This keeps secrets out of source code and allows standard deployment practices (Docker, CI/CD, etc.).

## The Bot

The Bot class is the runtime orchestrator responsible for:

- Loading a stored strategy
- Injecting the correct executor
- Running or stopping the strategy
- Handling failures and state transitions

### running the bot

```python
bot.run(
    person_id="alice",
    exchange="bitvavo",
    bot_id="rsi-xrp",
    status="active",
)
```

What happens internally:

1. The state of the strategy is loaded from the repository
2. The executor is replaced with a live exchange client
3. The strategy’s data pipeline is executed
4. strategy.run() is called
5. The new state of the strategy is persisted

If an exception occurs:
1. The strategy is stored
2. The bot is automatically moved to paused

### Stopping a Bot

Bots can be stopped gracefully using the stop method.

```python
bot.stop(
    person_id="alice",
    exchange="bitvavo",
    bot_id="rsi-xrp",
    status="active",
    asset_handling="quote_only",
)
```

#### Asset Handling Options

When stopping a bot, you must specify how assets should be handled:

`quote_only`
Sell all base assets and remain in quote currency

`base_only`
Buy base assets using all available quote currency

`ignore`
Leave balances unchanged

Before stopping, the bot:

1. Cancels all open orders
2. Handles assets according to the selected mode
3. Persists the final state
4. Moves the bot to stopped

If anything fails, the bot is moved to paused.
