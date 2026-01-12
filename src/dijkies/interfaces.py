import inspect
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

import pandas as pd
from pandas.core.frame import DataFrame as PandasDataFrame
from pandas.core.series import Series as PandasSeries

from dijkies.constants import BOT_STATUS, SUPPORTED_EXCHANGES
from dijkies.entities import Order, State
from dijkies.exceptions import (
    DataTimeWindowShorterThanSuggestedAnalysisWindowError,
    InvalidExchangeAssetClientError,
    InvalidTypeForTimeColumnError,
    MissingOHLCVColumnsError,
    TimeColumnNotDefinedError,
)

logger = logging.getLogger(__name__)


class Metric(ABC):
    @property
    @abstractmethod
    def metric_name(self) -> str:
        pass

    @abstractmethod
    def calculate(self, time_series: PandasSeries) -> float:
        pass


class DataPipeline(ABC):
    @abstractmethod
    def run(self) -> PandasDataFrame:
        pass


class ExchangeMarketAPI(ABC):
    @abstractmethod
    def get_candles(
        self,
        base: str,
        interval_in_minutes: int,
        lookback_in_minutes: int,
    ) -> PandasDataFrame:
        pass

    @abstractmethod
    def get_price(self, base: str) -> float:
        pass


class ExchangeAssetClient(ABC):
    def __init__(self, state: State) -> None:
        self.state = state

    @abstractmethod
    def assets_in_state_are_available(self) -> bool:
        pass

    @abstractmethod
    def place_limit_buy_order(
        self, limit_price: float, amount_in_quote: float
    ) -> Order:
        pass

    @abstractmethod
    def place_limit_sell_order(
        self, limit_price: float, amount_in_base: float
    ) -> Order:
        pass

    @abstractmethod
    def place_market_buy_order(self, amount_in_quote: float) -> Order:
        pass

    @abstractmethod
    def place_market_sell_order(self, amount_in_base: float) -> Order:
        pass

    @abstractmethod
    def get_order_info(self, order: Order) -> Order:
        pass

    @abstractmethod
    def cancel_order(self, order: Order) -> Order:
        pass

    def update_state(self) -> None:
        for order in self.state.open_orders:
            newest_info_order = self.get_order_info(order)
            if order.is_not_equal(newest_info_order):
                self.state.process_filled_order(newest_info_order)


class Strategy(ABC):
    def __init__(
        self,
        executor: ExchangeAssetClient,
    ) -> None:
        self.executor = executor
        self.state = self.executor.state

    @abstractmethod
    def execute(self, data: PandasDataFrame) -> None:
        pass

    def run(self, data: PandasDataFrame) -> None:
        self.executor.update_state()
        self.execute(data)

    @classmethod
    def _get_strategy_params(cls) -> list[str]:
        subclass_sig = inspect.signature(cls.__init__)
        base_sig = inspect.signature(Strategy.__init__)

        subclass_params = {
            name: p for name, p in subclass_sig.parameters.items() if name != "self"
        }
        base_params = {
            name: p for name, p in base_sig.parameters.items() if name != "self"
        }

        unique_params = {
            name: p for name, p in subclass_params.items() if name not in base_params
        }

        return list(unique_params.keys())

    def params_to_json(self):
        params = self._get_strategy_params()
        return {p: getattr(self, p) for p in params}

    def __getstate__(self):
        state = self.__dict__.copy()
        state["executor"] = None
        state["data_pipeline"] = None
        return state

    @property
    @abstractmethod
    def analysis_dataframe_size_in_minutes(self) -> int:
        pass

    def get_data_pipeline(self) -> DataPipeline:
        """
        implement this method for deployement
        """
        raise NotImplementedError()

    def backtest(self, data: PandasDataFrame) -> PandasDataFrame:
        """
        This method runs the backtest.
        It expects data, this should have the following properties:
        """

        from dijkies.executors import BacktestExchangeAssetClient
        from dijkies.performance import PerformanceInformationRow

        # validate args

        if "time" not in data.columns:
            raise TimeColumnNotDefinedError()

        if not pd.api.types.is_datetime64_any_dtype(data.time):
            raise InvalidTypeForTimeColumnError()

        lookback_in_min = self.analysis_dataframe_size_in_minutes
        timespan_data_in_min = (data.time.max() - data.time.min()).total_seconds() / 60

        if lookback_in_min > timespan_data_in_min:
            raise DataTimeWindowShorterThanSuggestedAnalysisWindowError()

        if not {"open", "high", "low", "close", "volume"}.issubset(data.columns):
            raise MissingOHLCVColumnsError()

        if not isinstance(self.executor, BacktestExchangeAssetClient):
            raise InvalidExchangeAssetClientError()

        start_time = data.iloc[0].time + timedelta(minutes=lookback_in_min)
        simulation_df: PandasDataFrame = data.loc[data.time >= start_time]
        start_candle = simulation_df.iloc[0]
        start_value_in_quote = self.state.total_value_in_quote(start_candle.open)
        result: list[PerformanceInformationRow] = []

        def get_analysis_df(
            data: PandasDataFrame, current_time: datetime, look_back_in_min: int
        ) -> PandasDataFrame:
            start_analysis_df = current_time - timedelta(minutes=look_back_in_min)

            analysis_df = data.loc[
                (data.time >= start_analysis_df) & (data.time <= current_time)
            ]

            return analysis_df.copy()

        for _, candle in simulation_df.iterrows():
            analysis_df = get_analysis_df(data, candle.time, lookback_in_min)
            self.executor.update_current_candle(candle)

            self.run(analysis_df)

            result.append(
                PerformanceInformationRow.from_objects(
                    candle, start_candle, self.state, start_value_in_quote
                )
            )

        return pd.DataFrame([r.model_dump() for r in result])


class StrategyRepository(ABC):
    @abstractmethod
    def store(
        self,
        strategy: Strategy,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        status: BOT_STATUS,
    ) -> None:
        pass

    @abstractmethod
    def read(
        self,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        status: BOT_STATUS,
    ) -> Strategy:
        pass

    @abstractmethod
    def change_status(
        self,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        from_status: BOT_STATUS,
        to_status: BOT_STATUS,
    ) -> None:
        pass


class CredentialsRepository(ABC):
    @abstractmethod
    def get_api_key(self, person_id: str, exchange: str) -> str:
        pass

    @abstractmethod
    def get_api_secret_key(self, person_id: str, exchange: str) -> str:
        pass
