import logging
import os
import pickle
import shutil
import time
from pathlib import Path
from typing import Any

from dijkies.constants import ASSET_HANDLING, BOT_STATUS, SUPPORTED_EXCHANGES
from dijkies.entities import Action
from dijkies.exceptions import CrucialException
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

    def execute_manual_action(
        self,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        status: BOT_STATUS,
        action: Action,
    ) -> None:
        strategy = self.load_strategy(person_id, exchange, bot_id, status)
        method = getattr(strategy.executor, action.name)
        method(**action.arguments)
        action.completed = True
        strategy.actions.append(action)

    def get_strategy_info(
        self,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        status: BOT_STATUS,
    ) -> dict[str, Any]:
        strategy = self.strategy_repository.read(person_id, exchange, bot_id, status)

        state = strategy.state

        return {
            "base_total": state.total_base,
            "base_available": state.base_available,
            "base_on_hold": state.base_on_hold,
            "quote_total": state.total_quote,
            "quote_available": state.quote_available,
            "quote_on_hold": state.quote_on_hold,
            "number_of_open_buy_orders": len(
                [order.model_dump() for order in state.buy_orders]
            ),
            "number_of_open_sell_orders": len(
                [order.model_dump() for order in state.sell_orders]
            ),
            "open_buy_orders": [order.model_dump() for order in state.buy_orders],
            "open_sell_orders": [order.model_dump() for order in state.sell_orders],
        }

    def change_status(
        self,
        person_id: str,
        exchange: SUPPORTED_EXCHANGES,
        bot_id: str,
        from_status: BOT_STATUS,
        to_status: BOT_STATUS,
    ) -> None:
        self.strategy_repository.change_status(
            person_id, exchange, bot_id, from_status, to_status
        )

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
        logger.info(
            f"{person_id} -- {exchange} -- {strategy.state.base} -- {bot_id} -- {status}"
        )
        data_pipeline = strategy.get_data_pipeline()
        data = data_pipeline.run()

        try:
            strategy.execute()  # finish actions from previous run if exceptions occured
            time.sleep(3)  # make sure exchange is up to date
            strategy.run(data)
            self.strategy_repository.store(
                strategy, person_id, exchange, bot_id, status
            )
        except CrucialException as e:

            self.strategy_repository.store(
                strategy, person_id, exchange, bot_id, status
            )
            self.strategy_repository.change_status(
                person_id, exchange, bot_id, status, "paused"
            )
            raise CrucialException(e)
        except Exception as e:
            self.strategy_repository.store(
                strategy, person_id, exchange, bot_id, status
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
