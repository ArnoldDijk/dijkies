import uuid
from datetime import datetime

import numpy as np
from pandas.core.series import Series
from pandas.core.series import Series as PandasSeries
from pydantic import BaseModel

from dijkies.entities import State
from dijkies.interfaces import Metric


class PerformanceInformationRow(BaseModel):
    id: str = str(uuid.uuid4())
    candle_time: datetime
    candle_open: float
    candle_high: float
    candle_low: float
    candle_close: float
    buy_orders: list = []
    sell_orders: list = []
    balance_total_base: float
    balance_total_quote: float
    balance_available_base: float
    balance_available_quote: float
    balance_base_on_hold: float
    balance_quote_on_hold: float
    total_fee_paid: float
    total_value_strategy: float
    roi_strategy: float
    roi_strategy_per_month: float
    total_value_hodl: float
    roi_hodl: float
    roi_hodl_per_month: float
    number_of_transactions: int
    absolute_profit: float

    @classmethod
    def from_objects(
        cls,
        candle: Series,
        start_candle: Series,
        state: State,
        initialization_value_in_quote: float,
    ) -> "PerformanceInformationRow":
        strategy_value = state.total_value_in_quote(candle.close)
        hodl_value = (candle.close / start_candle.open) * initialization_value_in_quote

        roi_strategy = ((strategy_value / initialization_value_in_quote) - 1) * 100
        roi_hodl = ((candle.close / start_candle.open) - 1) * 100

        duration_in_months = (candle.time - start_candle.time).total_seconds() / (
            60 * 60 * 24 * 30
        )

        strategy_per_month = (roi_strategy / 100 + 1) ** (
            1 / max(duration_in_months, 0.01)
        )
        hodl_per_month = (roi_hodl / 100 + 1) ** (1 / max(duration_in_months, 0.01))

        return cls(
            candle_time=candle.time,
            candle_open=candle.open,
            candle_high=candle.high,
            candle_low=candle.low,
            candle_close=candle.close,
            buy_orders=state.buy_orders,
            sell_orders=state.sell_orders,
            balance_total_base=state.total_base,
            balance_total_quote=state.total_quote,
            balance_available_base=state.base_available,
            balance_available_quote=state.quote_available,
            balance_base_on_hold=state.base_on_hold,
            balance_quote_on_hold=state.quote_on_hold,
            total_fee_paid=state.total_fee_paid,
            total_value_strategy=strategy_value,
            roi_strategy=roi_strategy,
            roi_strategy_per_month=strategy_per_month,
            total_value_hodl=hodl_value,
            roi_hodl=roi_hodl,
            roi_hodl_per_month=hodl_per_month,
            number_of_transactions=state.number_of_transactions,
            absolute_profit=strategy_value - initialization_value_in_quote,
        )


class DrawDown(Metric):
    @property
    def metric_name(self) -> str:
        return "draw_down"

    def calculate(self, time_series: PandasSeries) -> float:
        returns = time_series.pct_change()
        returns.fillna(0.0, inplace=True)

        cumulative = (returns + 1).cumprod()
        running_max = np.maximum.accumulate(cumulative)

        result = ((cumulative - running_max) / running_max).min() * 100

        return result


class ReturnOnInvestment(Metric):
    @property
    def metric_name(self) -> str:
        return "roi"

    def calculate(self, time_series: PandasSeries) -> float:
        return ((time_series.iloc[-1] / time_series.iloc[0]) - 1) * 100


class NormalizedReturnOnInvestment(Metric):
    def __init__(self, candle_interval_in_minutes: int) -> None:
        self.candle_interval_in_minutes = candle_interval_in_minutes

    @property
    def metric_name(self) -> str:
        return "normalized_roi"

    def calculate(self, time_series: PandasSeries) -> float:
        """
        returns the average return per month.
        """
        total_time_in_minutes = len(time_series) * self.candle_interval_in_minutes
        total_time_in_months = total_time_in_minutes / (60 * 24 * 30)

        total_return = time_series.iloc[-1] / time_series.iloc[0]
        return_per_month = total_return ** (min(1 / total_time_in_months, 1))

        return (return_per_month - 1) * 100


class SharpeRatio(Metric):
    def __init__(
        self, risk_free_rate_per_year: float, candle_interval_in_minutes: int
    ) -> None:
        self.risk_free_rate_per_year = risk_free_rate_per_year
        self.candle_interval_in_minutes = candle_interval_in_minutes

    @property
    def metric_name(self) -> str:
        return "sharpe_ratio"

    def calculate(self, time_series: PandasSeries) -> float:
        risk_free_rate_per_day = (1 + self.risk_free_rate_per_year) ** (1 / 365) - 1
        measurements_per_day = 60 * 24 / self.candle_interval_in_minutes
        normalized_std_return = risk_free_rate_per_day / max(measurements_per_day, 1)
        returns = time_series.pct_change()
        excess_return = returns.mean() - normalized_std_return
        volatility = max(returns.std(), 0.00001)
        sharpe_ratio = excess_return / volatility
        return sharpe_ratio * np.sqrt(measurements_per_day)
