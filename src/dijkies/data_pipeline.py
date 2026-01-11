import pandas as pd
from pandas.core.frame import DataFrame as PandasDataFrame

from dijkies.interfaces import DataPipeline, ExchangeMarketAPI


class NoDataPipeline(DataPipeline):
    def run(self) -> PandasDataFrame:
        return pd.DataFrame([{}], columns=["close"])


class CurrentValueDataPipeline(DataPipeline):
    def __init__(self, base: str, exchange_market_api: ExchangeMarketAPI) -> None:
        self.exchange_market_api = exchange_market_api
        self.base = base

    def run(self) -> PandasDataFrame:
        current_price = self.exchange_market_api.get_price(self.base)
        return pd.DataFrame([{"close": current_price}])


class OHLCVDataPipeline(DataPipeline):
    def __init__(
        self,
        exchange_market_api: ExchangeMarketAPI,
        base: str,
        candle_interval_in_minutes: int,
        lookback_in_minutes: int,
    ) -> None:
        self.exchange_market_api = exchange_market_api
        self.base = base
        self.candle_interval_in_minutes = candle_interval_in_minutes
        self.lookback_in_minutes = lookback_in_minutes

    def run(self) -> PandasDataFrame:
        return self.exchange_market_api.get_candles(
            self.base, self.candle_interval_in_minutes, self.lookback_in_minutes
        ).iloc[
            :-1
        ]  # Exclude the current forming candle
