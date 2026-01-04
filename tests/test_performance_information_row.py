from datetime import datetime, timezone

import pandas as pd

from dijkies.executors import State
from dijkies.performance import PerformanceInformationRow


def test_performance_information_row() -> None:
    # arrange

    candle = pd.Series(
        {
            "time": datetime(2025, 8, 8, 5, 25, tzinfo=timezone.utc),
            "open": 1201,
            "high": 1246,
            "low": 1178,
            "close": 1212,
            "volume": 234,
        }
    )

    state = State(base="BTC", total_base=0, total_quote=105002.43)

    performance_information_row = PerformanceInformationRow.from_objects(
        candle, candle, state, state.total_value_in_quote(candle.open)
    )

    # assert

    assert isinstance(performance_information_row, PerformanceInformationRow)
