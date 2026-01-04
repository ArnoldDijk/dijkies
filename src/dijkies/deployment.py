import os
import pickle
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from dijkies.executors import (
    SUPPORTED_EXCHANGES,
    BacktestExchangeAssetClient,
    BitvavoExchangeAssetClient,
)
from dijkies.logger import get_logger
from dijkies.strategy import Strategy

BOT_STATUS = Literal["active", "paused", "stopped"]
ASSET_HANDLING = Literal["quote_only", "base_only", "ignore"]


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


class CredentialsRepository(ABC):
    @abstractmethod
    def get_api_key(self, person_id: str, exchange: str) -> str:
        pass

    @abstractmethod
    def store_api_key(self, person_id: str, exchange: str, api_key: str) -> None:
        pass

    @abstractmethod
    def get_api_secret_key(self, person_id: str, exchange: str) -> str:
        pass

    @abstractmethod
    def store_api_secret_key(
        self, person_id: str, exchange: str, api_secret_key: str
    ) -> None:
        pass


class LocalCredentialsRepository(CredentialsRepository):
    def get_api_key(self, person_id: str, exchange: str) -> str:
        return os.environ.get(f"{person_id}_{exchange}_api_key")

    def store_api_key(self, person_id: str, exchange: str, api_key: str) -> None:
        pass

    def get_api_secret_key(self, person_id: str, exchange: str) -> str:
        return os.environ.get(f"{person_id}_{exchange}_api_secret_key")

    def store_api_secret_key(self, id: str, api_secret_key: str) -> None:
        pass


class Bot:
    def __init__(
        self,
        strategy_repository: StrategyRepository,
        credential_repository: CredentialsRepository,
    ) -> None:
        self.strategy_repository = strategy_repository
        self.credential_repository = credential_repository

    def set_executor(
        self,
        strategy: Strategy,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
    ) -> None:
        if exchange == "bitvavo":
            api_key = self.credential_repository.get_api_key(person_id, exchange)
            api_secret_key = self.credential_repository.get_api_secret_key(
                person_id, exchange
            )
            strategy.executor = BitvavoExchangeAssetClient(
                strategy.state, api_key, api_secret_key, 1, get_logger()
            )
        elif exchange == "backtest":
            strategy.executor = BacktestExchangeAssetClient(
                strategy.state, 0.0025, 0.0015
            )
        else:
            raise Exception("exchange not defined")

    def run(
        self,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        status: BOT_STATUS,
    ) -> None:

        strategy = self.strategy_repository.read(person_id, exchange, bot_id, status)
        self.set_executor(strategy, person_id, exchange)

        data_pipeline = strategy.get_data_pipeline()
        data = data_pipeline.run()

        try:
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
        if status == "stopped":
            return

        strategy = self.strategy_repository.read(person_id, exchange, bot_id, status)
        self.set_executor(strategy, person_id, exchange)

        try:
            for open_order in strategy.state.open_orders:
                _ = strategy.executor.cancel_order(open_order)
            if asset_handling == "base_only":
                _ = strategy.executor.place_market_buy_order(
                    strategy.state.base, strategy.state.quote_available
                )
            elif asset_handling == "quote_only":
                _ = strategy.executor.place_market_sell_order(
                    strategy.state.base, strategy.state.base_available
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
