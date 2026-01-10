from pandas.core.frame import DataFrame as PandasDataFrame

from dijkies.interfaces import Strategy


def test_backest(candle_df: PandasDataFrame, rsi_strategy: Strategy) -> None:
    # act

    results = rsi_strategy.backtest(candle_df)

    # assert

    assert isinstance(results, PandasDataFrame)


def test_params(rsi_strategy: Strategy) -> None:
    assert set(rsi_strategy._get_strategy_params()) == {
        "lower_threshold",
        "higher_threshold",
    }
