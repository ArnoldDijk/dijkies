import os
import time
import uuid

import pandas as pd
import pytest
from pandas.core.frame import DataFrame as PandasDataFrame
from ta.momentum import RSIIndicator

from dijkies.data_pipeline import OHLCVDataPipeline
from dijkies.exchange_market_api import BitvavoMarketAPI
from dijkies.executors import (
    BacktestExchangeAssetClient,
    ExchangeAssetClient,
    Order,
    State,
)
from dijkies.interfaces import DataPipeline, Strategy


class RSIStrategy(Strategy):
    analysis_dataframe_size_in_minutes = 60 * 24 * 30

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
        return OHLCVDataPipeline(
            BitvavoMarketAPI(),
            self.state.base,
            60,
            self.analysis_dataframe_size_in_minutes,
        )


def get_state() -> State:
    return State(base="BTC", total_base=0.1, total_quote=10000)


def get_executor() -> ExchangeAssetClient:
    state = get_state()
    return BacktestExchangeAssetClient(state, 0.0025, 0.0015)


@pytest.fixture
def candle_df() -> PandasDataFrame:
    path = os.path.join("tests", "fixtures", "candle_df.csv")
    df = pd.read_csv(path)
    df.time = pd.to_datetime(df.time)
    return df


@pytest.fixture
def state() -> State:
    return get_state()


@pytest.fixture
def executor() -> ExchangeAssetClient:
    return get_executor()


@pytest.fixture
def rsi_strategy() -> RSIStrategy:
    return RSIStrategy(get_executor(), 35, 65)


@pytest.fixture
def open_sell_order() -> Order:
    return Order(
        order_id=str(uuid.uuid4()),
        exchange="bitvavo",
        time_created=int(time.time()),
        market="BTC",
        side="sell",
        limit_price=90000,
        on_hold=0.01,
        status="open",
        is_taker=False,
    )


@pytest.fixture
def open_buy_order() -> Order:
    return Order(
        order_id=str(uuid.uuid4()),
        exchange="bitvavo",
        time_created=int(time.time()),
        market="BTC",
        side="buy",
        limit_price=60000,
        on_hold=1000,
        status="open",
        is_taker=False,
    )
