from pandas.core.frame import DataFrame as PandasDataFrame

from dijkies.exchange_market_api import BinanceMarketAPI
from dijkies.logger import get_logger


def test_binance_market_api() -> None:
    # arrange

    logger = get_logger()

    binance_market_api = BinanceMarketAPI(logger)

    # act

    candle_df = binance_market_api.get_candles()

    # assert

    assert isinstance(candle_df, PandasDataFrame)
    assert set(candle_df.columns) == {"time", "open", "high", "low", "close", "volume"}
