![Alt text](image.png)

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

- Data Scientists building algorithmic trading systems
- Quantitative traders who want full control over strategy logic
- Anyone who wants to move from backtesting to production without focussing on

## What Dijkies Is Not

- A no-code trading bot
- A black-box strategy optimizer
- A fully managed trading platform

Dijkies provides the **building blocks**, not the trading edge.

---

## Quick Start

This quick start shows how to define a strategy, fetch market data, and run a backtest in just a few steps.

### 1. Define a Strategy

A strategy is a class that inherits from `Strategy` and implements the `execute` and  `get_data_pipeline` method.
the execute method receives a pandas dataframe that should, at least, contain `open`, `high`, `low`, `close`, `volume` and `candle_time` columns.
more can be added, and used within your trading algorithm. The engineering of these columns falls outside of dijkies scope.

This data is then used to define and execute actions. The following actions are available (see docstrings in dijkies.interfaces.ExchangeAssetClient for more info):

-   `place limit buy order`
-   `place limit sell order`
-   `place market buy order`
-   `place market sell order`
-   `cancel (limit) order`
-   `get order information`
-   `get account balance`

Below is an example implementation of an RSI strategy:

```python
from dijkies.executors import BacktestExchangeAssetClient
from dijkies.exchange_market_api import BitvavoMarketAPI
from dijkies.interfaces import (
    Strategy,
    DataPipeline,
    ExchangeAssetClient
)
from dijkies.entities import State
from dijkies.data_pipeline import OHLCVDataPipeline

from ta.momentum import RSIIndicator
from pandas.core.frame import DataFrame as PandasDataFrame


class RSIStrategy(Strategy):
    analysis_dataframe_size_in_minutes = 60*24*30
    min_order_amount = 10

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

        if (
            is_buy_signal and
            self.state.quote_available > self.min_order_amount
        ):
            self.executor.place_market_buy_order(self.state.quote_available)

        is_sell_signal = (
            previous_candle.momentum_rsi < self.higher_threshold
            and current_candle.momentum_rsi > self.higher_threshold
        )

        if (
            is_sell_signal and
            self.state.base_available * candle_df.iloc[-1].close > self.min_order_amount
        ):
            self.executor.place_market_sell_order(self.state.base_available)

    def get_data_pipeline(self) -> DataPipeline:
        return OHLCVDataPipeline(
            BitvavoMarketAPI(),
            self.state.base,
            60,
            60*24*7
        )
```

### 2. fetch data for your backtest
Market data is provided as a pandas DataFrame containing OHLCV candles.

```python
from dijkies.exchange_market_api import BitvavoMarketAPI

bitvavo_market_api = BitvavoMarketAPI()

candle_df = bitvavo_market_api.get_candles()
```

### 3. Set Up State and BacktestingExecutor
final steps involve initializing a state and backtest-executor. The state keeps track of the assets that the strategy is managing.
This is in sync with the real state of the account at the exchange and is used as information source in decision making.
The backtest executor is a Mock for the execution of actions. This backtest executor is replaced by a real exchange executor in live trading. The backtest method returns a Pandas dataframe containing all important information about the backtest. For instance, a timeseries of the amount of assets, which buy orders are open, total amount of transactions made so far. the full list can be found in the performance module.


```python
# do backtest

fee_limit_order = 0.0015
fee_market_order = 0.0025

start_investment_base = 0
start_investment_quote = 1000

state = State(
    base="XRP",
    total_base=start_investment_base,
    total_quote=start_investment_quote
)

executor = BacktestExchangeAssetClient(
    state,
    fee_limit_order=fee_limit_order,
    fee_market_order=fee_market_order
)

strategy = RSIStrategy(
    executor,
    35,
    65,
)

results = strategy.backtest(candle_df)
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
from dijkies.deployment import LocalStrategyRepository

repo = LocalStrategyRepository(Path("./strategies"))

# read

strategy = repo.read(
    person_id="ArnoldDijk",
    exchange="bitvavo",
    bot_id="berend_botje",
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
export ArnoldDijk_bitvavo_api_key="..."
export ArnoldDijk_bitvavo_api_secret_key="..."
```

```python
from dijkies.deployment import LocalCredentialsRepository

credentials_repository = LocalCredentialsRepository()
bitvavo_api_key = credentials_repository.get_api_key(
    person_id="ArnoldDijk",
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
    person_id="ArnoldDijk",
    exchange="bitvavo",
    bot_id="berend_botje",
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
    person_id="ArnoldDijk",
    exchange="bitvavo",
    bot_id="berend_botje",
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

## Deployment locally Quickstart

In this example, we will continue from the earlier defined rsi strategy.
we ended at the moment we executed the backtest. Now suppose we decide to use this algorithm with real money.
Then we have to deploy the strategy. In this example we will deploy locally.

### Step 1: Prepare the Strategy for Deployment -> Create a Strategy Repository and store your strategy


```python
from pathlib import Path
from dijkies.deployment import LocalStrategyRepository

strategy_repository = LocalStrategyRepository(
    root_directory=Path("./strategies")
)

# adjust state to what you want to invest.

strategy.state = State(
    base="BTC",
    total_base=0,
    total_quote=13  # let's invest 13 euros initially
)

strategy_repository.store(
    strategy=strategy,
    person_id="ArnoldDijk",
    exchange="bitvavo",
    bot_id="berend_botje",
    status="active",
)
```

This serializes the strategy and its state so it can be resumed later.

### Step 2: Configure Exchange Credentials

Set your exchange credentials as environment variables:

```bash
export ArnoldDijk_bitvavo_api_key="foo"
export ArnoldDijk_bitvavo_api_secret_key="bar"
```

### Step 3: Create the Bot Runtime

The Bot orchestrates loading, execution, and lifecycle management.

```python
from dijkies.deployment import Bot, LocalCredentialsRepository

credentials_repository = LocalCredentialsRepository()

bot = Bot(
    strategy_repository=strategy_repository,
    credential_repository=credentials_repository,
)
```

### Step 4: Run the Strategy Live

start the live trading bot

```python
bot.run(
    person_id="ArnoldDijk",
    exchange="bitvavo",
    bot_id="berend_botje",
    status="active",
)
```

What Happens Under the Hood:
1. The strategy is loaded from disk
2. The backtest executor is replaced with BitvavoExchangeAssetClient where API credentials are injected
3. The strategy’s data pipeline fetches live market data
4. strategy.run() executes decision logic. Here, orders are executed on the exchange and state is modified accordingly
5. strategy is persisted, executor and credentials not included.

If an exception occurs, the bot is automatically moved to paused.

the strategy should be run repeatedly every, say, 60 minutes. There are plenty of ways to accomplish this, and below is a very
basic example:

```python
import time
from datetime import datetime, timezone

while True:
    try:
        print("running bot cycle at ", datetime.now(tz=timezone.utc))
        bot.run(
            person_id="ArnoldDijk",
            exchange="bitvavo",
            bot_id="berend_botje",
            status="active",
        )
        print("bot cycle finished")
    except Exception as e:
        print("an error occured: ", e)

    t = datetime.now(tz=timezone.utc)
    minutes_left = 60 - t.minute
    time.sleep((minutes_left - 1) * 60 + (60 - t.second))

```

However, it is much better to use orchestration tools like Apache Airflow. Many bots can be run in parallel using the fan-in/fan-out principle.
