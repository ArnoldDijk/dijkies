from pathlib import Path

import pytest
from pandas.core.frame import DataFrame as PandasDataFrame

from dijkies.deployment import Bot, LocalCredentialsRepository, LocalStrategyRepository
from dijkies.executors import Order, State
from dijkies.interfaces import Strategy


def fail_execute(data: PandasDataFrame) -> None:
    raise Exception("BOOM")


def test_local_strategy_store_and_read(rsi_strategy: Strategy, tmp_path: Path) -> None:
    # arrange

    strategy_repository = LocalStrategyRepository(tmp_path)
    person_id = "AD"
    exchange = "backtest"
    bot_id = "ddd"
    status = "active"

    # act

    strategy_repository.store(rsi_strategy, person_id, exchange, bot_id, status)

    loaded = strategy_repository.read(person_id, exchange, bot_id, status)

    # assert

    assert isinstance(loaded, Strategy)
    assert loaded.executor is None
    assert isinstance(loaded.state, State)


def test_local_strategy_store_change_status(
    rsi_strategy: Strategy, tmp_path: Path
) -> None:
    # arrange

    strategy_repository = LocalStrategyRepository(tmp_path)
    person_id = "AD"
    exchange = "backtest"
    bot_id = "ddd"
    status_from = "active"
    status_to = "paused"

    # act

    strategy_repository.store(rsi_strategy, person_id, exchange, bot_id, status_from)
    strategy_repository.change_status(
        person_id, exchange, bot_id, status_from, status_to
    )

    src_file = tmp_path / person_id / exchange / status_from / f"{bot_id}.pkl"
    dest_file = tmp_path / person_id / exchange / status_to / f"{bot_id}.pkl"

    # assert

    assert dest_file.exists()
    assert not src_file.exists()


def test_bot_run_method_success(rsi_strategy: Strategy, tmp_path: Path) -> None:
    # arrange

    person_id = "AD"
    exchange = "backtest"
    bot_id = "ddd"
    status = "active"

    src_file = tmp_path / person_id / exchange / status / f"{bot_id}.pkl"

    strategy_repository = LocalStrategyRepository(tmp_path)
    strategy_repository.store(rsi_strategy, person_id, exchange, bot_id, status)

    credential_repository = LocalCredentialsRepository()
    bot = Bot(strategy_repository, credential_repository)

    # act

    bot.run(person_id, exchange, bot_id, status)

    # assert

    assert src_file.exists()


def test_bot_run_method_failure(rsi_strategy: Strategy, tmp_path: Path) -> None:
    # arrange

    person_id = "AD"
    exchange = "backtest"
    bot_id = "ddd"
    status = "active"

    rsi_strategy.execute = fail_execute

    src_file = tmp_path / person_id / exchange / status / f"{bot_id}.pkl"
    replaced_file = tmp_path / person_id / exchange / "paused" / f"{bot_id}.pkl"

    strategy_repository = LocalStrategyRepository(tmp_path)
    strategy_repository.store(rsi_strategy, person_id, exchange, bot_id, status)

    credential_repository = LocalCredentialsRepository()
    bot = Bot(strategy_repository, credential_repository)

    # act
    with pytest.raises(Exception):
        bot.run(person_id, exchange, bot_id, status)

    # assert

    assert replaced_file.exists()
    assert not src_file.exists()


def test_bot_stop_method(
    rsi_strategy: Strategy,
    tmp_path: Path,
    open_buy_order: Order,
    open_sell_order: Order,
) -> None:
    # arrange

    person_id = "AD"
    exchange = "backtest"
    bot_id = "ddd"
    status = "active"

    rsi_strategy.state.add_order(open_buy_order)
    rsi_strategy.state.add_order(open_sell_order)

    src_file = tmp_path / person_id / exchange / status / f"{bot_id}.pkl"
    replaced_file = tmp_path / person_id / exchange / "stopped" / f"{bot_id}.pkl"

    strategy_repository = LocalStrategyRepository(tmp_path)
    strategy_repository.store(rsi_strategy, person_id, exchange, bot_id, status)

    credential_repository = LocalCredentialsRepository()
    bot = Bot(strategy_repository, credential_repository)

    # act

    bot.stop(person_id, exchange, bot_id, status, "quote_only")

    # assert

    assert replaced_file.exists()
    assert not src_file.exists()

    loaded = strategy_repository.read(person_id, exchange, bot_id, "stopped")

    assert len(loaded.state.open_orders) == 0
    assert loaded.state.total_base == 0
