import logging
import os
import pickle
import shutil
from pathlib import Path

from dijkies.constants import ASSET_HANDLING, BOT_STATUS, SUPPORTED_EXCHANGES
from dijkies.exceptions import AssetNotAvailableError
from dijkies.interfaces import (
    CredentialsRepository,
    Strategy,
    StrategyRepository,
)

logger = logging.getLogger(__name__)


class LocalCredentialsRepository(CredentialsRepository):
    def get_api_key(self, person_id: str, exchange: str) -> str:
        return os.environ.get(f"{person_id}_{exchange}_api_key")

    def get_api_secret_key(self, person_id: str, exchange: str) -> str:
        return os.environ.get(f"{person_id}_{exchange}_api_secret_key")


class LocalStrategyRepository(StrategyRepository):
    def __init__(self, root_directory: Path) -> None:
        self.root_directory = root_directory

    def store(
        self,
        strategy: Strategy,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        status: BOT_STATUS,
    ) -> None:
        (self.root_directory / person_id / exchange / status).mkdir(
            parents=True, exist_ok=True
        )
        path = os.path.join(
            self.root_directory, person_id, exchange, status, bot_id + ".pkl"
        )
        with open(path, "wb") as file:
            pickle.dump(strategy, file)

    def read(
        self,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        status: BOT_STATUS,
    ) -> Strategy:
        path = os.path.join(
            self.root_directory, person_id, exchange, status, bot_id + ".pkl"
        )
        with open(path, "rb") as file:
            strategy = pickle.load(file)
        return strategy

    def change_status(
        self,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        from_status: BOT_STATUS,
        to_status: BOT_STATUS,
    ) -> None:
        if from_status == to_status:
            return
        src = (
            Path(f"{self.root_directory}/{person_id}/{exchange}/{from_status}")
            / f"{bot_id}.pkl"
        )
        dest_folder = Path(f"{self.root_directory}/{person_id}/{exchange}/{to_status}")

        dest_folder.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dest_folder / src.name)


class Bot:
    def __init__(
        self,
        strategy_repository: StrategyRepository,
        credential_repository: CredentialsRepository,
    ) -> None:
        self.strategy_repository = strategy_repository
        self.credential_repository = credential_repository

    def load_strategy(
        self,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        status: BOT_STATUS,
    ) -> Strategy:
        from dijkies.executors import get_executor

        strategy = self.strategy_repository.read(person_id, exchange, bot_id, status)
        strategy.executor = get_executor(
            person_id, exchange, strategy.state, self.credential_repository
        )
        return strategy

    def run(
        self,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        status: BOT_STATUS,
    ) -> None:

        strategy = self.load_strategy(person_id, exchange, bot_id, status)
        data_pipeline = strategy.get_data_pipeline()
        data = data_pipeline.run()

        try:
            if not strategy.executor.assets_in_state_are_available():
                raise AssetNotAvailableError(strategy.state.base)
            strategy.run(data)
            self.strategy_repository.store(
                strategy, person_id, exchange, bot_id, status
            )
        except Exception as e:
            self.strategy_repository.store(
                strategy, person_id, exchange, bot_id, status
            )
            self.strategy_repository.change_status(
                person_id, exchange, bot_id, status, "paused"
            )
            raise Exception(e)

    def stop(
        self,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        status: BOT_STATUS,
        asset_handling: ASSET_HANDLING,
    ) -> None:
        strategy = self.load_strategy(person_id, exchange, bot_id, status)

        try:
            for open_order in strategy.state.open_orders:
                _ = strategy.executor.cancel_order(open_order)
            if asset_handling == "base_only":
                _ = strategy.executor.place_market_buy_order(
                    strategy.state.quote_available
                )
            elif asset_handling == "quote_only":
                _ = strategy.executor.place_market_sell_order(
                    strategy.state.base_available
                )
            self.strategy_repository.store(
                strategy, person_id, exchange, bot_id, status
            )
            self.strategy_repository.change_status(
                person_id, exchange, bot_id, status, "stopped"
            )

        except Exception as e:
            self.strategy_repository.store(
                strategy, person_id, exchange, bot_id, status
            )
            self.strategy_repository.change_status(
                person_id, exchange, bot_id, status, "paused"
            )
            raise Exception(e)
