import logging

from pandas.core.frame import DataFrame as PandasDataFrame

from dijkies.exchange_market_api import BitvavoMarketAPI


def test_bitvavo_market_api() -> None:
    # arrange

    logger = logging.getLogger(__name__)

    bitvavo_market_api = BitvavoMarketAPI(logger)

    # act

    candle_df = bitvavo_market_api.get_candles()

    # assert

    assert isinstance(candle_df, PandasDataFrame)
    assert set(candle_df.columns) == {"time", "open", "high", "low", "close", "volume"}
