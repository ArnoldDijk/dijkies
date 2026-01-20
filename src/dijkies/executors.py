import logging
import time
import uuid
from decimal import ROUND_DOWN, Decimal, getcontext

import pandas as pd
from pandas.core.series import Series
from python_bitvavo_api.bitvavo import Bitvavo

from dijkies.constants import SUPPORTED_EXCHANGES
from dijkies.entities import Order, State
from dijkies.exceptions import (
    GetOrderInfoError,
    InsufficientBalanceError,
    InsufficientOrderValueError,
    InvalidOrderRequest,
)
from dijkies.interfaces import CredentialsRepository, ExchangeAssetClient

logger = logging.getLogger(__name__)


class BacktestExchangeAssetClient(ExchangeAssetClient):
    def __init__(
        self, state: State, fee_market_order: float, fee_limit_order: float
    ) -> None:
        super().__init__(state)
        self.fee_market_order = fee_market_order
        self.fee_limit_order = fee_limit_order
        self.current_candle = pd.Series({"high": 80000, "low": 78000, "close": 79000})

    def assets_in_state_are_available(self) -> bool:
        return True

    def update_current_candle(self, current_candle: Series) -> None:
        self.current_candle = current_candle

    def place_limit_buy_order(
        self, limit_price: float, amount_in_quote: float
    ) -> Order:
        order = Order(
            order_id=str(uuid.uuid4()),
            exchange="bitvavo",
            time_created=int(time.time()),
            market=self.state.base,
            side="buy",
            limit_price=limit_price,
            on_hold=amount_in_quote,
            status="open",
            is_taker=False,
        )

        self.state.add_order(order)

        return order

    def place_limit_sell_order(
        self, limit_price: float, amount_in_base: float
    ) -> Order:
        order = Order(
            order_id=str(uuid.uuid4()),
            exchange="bitvavo",
            time_created=int(time.time()),
            market=self.state.base,
            side="sell",
            limit_price=limit_price,
            on_hold=amount_in_base,
            status="open",
            is_taker=False,
        )

        self.state.add_order(order)

        return order

    def place_market_buy_order(self, amount_in_quote: float) -> Order:
        fee = amount_in_quote * self.fee_market_order / (1 + self.fee_market_order)
        amount_in_base = (amount_in_quote - fee) / self.current_candle.close

        order = Order(
            order_id=str(uuid.uuid4()),
            exchange="bitvavo",
            time_created=int(time.time()),
            market=self.state.base,
            side="buy",
            filled=amount_in_base,
            filled_quote=amount_in_quote - fee,
            status="filled",
            fee=fee,
            is_taker=True,
        )

        self.state.process_filled_order(order)

        return order

    def place_market_sell_order(self, amount_in_base: float) -> Order:
        amount_in_quote = amount_in_base * self.current_candle.close
        fee = amount_in_quote * self.fee_market_order

        order = Order(
            order_id=str(uuid.uuid4()),
            exchange="bitvavo",
            time_created=int(time.time()),
            market=self.state.base,
            side="sell",
            filled=amount_in_base,
            filled_quote=amount_in_quote,
            status="filled",
            fee=fee,
            is_taker=True,
        )

        self.state.process_filled_order(order)

        return order

    def get_order_info(self, order: Order) -> Order:
        found_order = self.state.get_order(order.order_id)
        if found_order.status == "open":
            is_filled = (
                found_order.side == "buy"
                and found_order.limit_price >= self.current_candle.low
            ) or (
                found_order.side == "sell"
                and found_order.limit_price <= self.current_candle.high
            )
            if is_filled:
                return self.fill_open_order(found_order)
        return found_order

    def cancel_order(self, order: Order) -> Order:
        self.state.cancel_order(order)
        return order

    def fill_open_order(self, order: Order) -> Order:
        fee_limit_order = self.fee_limit_order
        if order.status != "open":
            raise ValueError("only open orders can be filled")
        if order.side == "buy":
            fee = order.on_hold * fee_limit_order / (1 + fee_limit_order)
            filled_quote = order.on_hold - fee
            filled = filled_quote / order.limit_price  # type: ignore
        else:
            filled = order.on_hold
            filled_quote = order.on_hold * order.limit_price  # type: ignore
            fee = filled_quote * fee_limit_order
        return Order(
            order_id=order.order_id,
            exchange=order.exchange,
            time_created=order.time_created,
            market=order.market,
            side=order.side,
            limit_price=order.limit_price,
            on_hold=0,
            status="filled",
            is_taker=False,
            fee=fee,
            filled_quote=filled_quote,
            filled=filled,
        )


def order_from_bitvavo_response(response: dict) -> Order:
    return Order(
        exchange="bitvavo",
        order_id=response["orderId"],
        market=response["market"],
        time_created=int(response["created"]),
        time_canceled=None,
        time_filled=(
            max([int(fill["timestamp"]) for fill in response["fills"]])
            if len(response["fills"]) > 0
            else None
        ),
        on_hold=float(response["onHold"]),
        side=response["side"],
        limit_price=float(response["price"]) if "price" in response else None,
        actual_price=(
            float(response["filledAmountQuote"]) / float(response["filledAmount"])
            if float(response["filledAmount"]) > 0
            else None
        ),
        filled=float(response["filledAmount"]),
        filled_quote=float(response["filledAmountQuote"]),
        fee=float(response["feePaid"]),
        is_taker=response["fills"][0]["taker"] if response["fills"] else False,
        status=(
            response["status"]
            if response["status"] in ["filled", "cancelled"]
            else "open"
        ),
    )


class BitvavoExchangeAssetClient(ExchangeAssetClient):
    max_fee = 0.0025

    def __init__(
        self,
        state: State,
        bitvavo_api_key: str,
        bitvavo_api_secret_key: str,
        operator_id: int,
    ) -> None:
        super().__init__(state)
        self.operator_id = operator_id
        self.bitvavo = Bitvavo(
            {
                "APIKEY": bitvavo_api_key,
                "APISECRET": bitvavo_api_secret_key,
                "RESTURL": "https://api.bitvavo.com/v2",
                "WSURL": "wss://ws.bitvavo.com/v2/",
                "ACCESSWINDOW": 10000,
                "DEBUGGING": False,
            }
        )

    def assets_in_state_are_available(self) -> bool:
        base_response = self.bitvavo.balance({"symbol": self.state.base})
        quote_response = self.bitvavo.balance({"symbol": "EUR"})

        available_base = float(base_response[0]["available"]) if base_response else 0
        available_quote = float(quote_response[0]["available"]) if quote_response else 0
        in_order_base = float(base_response[0]["inOrder"]) if base_response else 0
        in_order_quote = float(quote_response[0]["inOrder"]) if quote_response else 0

        base_is_available = self.state.base_available <= available_base * 1.000001
        quote_is_available = self.state.quote_available <= available_quote * 1.000001
        in_order_base_is_available = self.state.base_on_hold <= in_order_base * 1.000001
        in_order_quote_is_available = (
            self.state.quote_on_hold <= in_order_quote * 1.000001
        )

        logger.info(
            "base available exchange: %s | base available state: %s",
            available_base,
            self.state.base_available,
        )
        logger.info(
            "quote available exchange: %s | quote available state: %s",
            available_quote,
            self.state.quote_available,
        )
        logger.info(
            "base in order exchange: %s | base on hold state: %s",
            in_order_base,
            self.state.base_on_hold,
        )
        logger.info(
            "quote in order exchange: %s | quote on hold state: %s",
            in_order_quote,
            self.state.quote_on_hold,
        )

        return (
            base_is_available
            and quote_is_available
            and in_order_base_is_available
            and in_order_quote_is_available
        )

    def quantity_decimals(self) -> int:
        trading_pair = self.state.base + "-EUR"
        return self.bitvavo.markets({"market": trading_pair})["quantityDecimals"]

    @staticmethod
    def __closest_valid_price(price: float) -> float:
        getcontext().prec = 20
        price = Decimal(str(price))
        x = 0

        ten = Decimal("10")

        if price > 1:
            while price / (ten**x) > 1:
                x += 1
        else:
            while price / (ten**x) < 1:
                x -= 1
            x += 1

        shifted = price / (ten**x)
        rounded = shifted.quantize(Decimal("1.00000"), rounding=ROUND_DOWN)
        corrected = rounded * (ten**x)

        return float(corrected)

    def get_balance_base(self) -> dict[str, float]:
        balance = self.bitvavo.balance({"symbol": self.state.base})
        logger.info(f"response Balance base: {balance}")
        if balance:
            balance = balance[0]
        else:
            balance = {"available": 0, "inOrder": 0}
        return balance

    def get_balance_quote(self) -> dict[str, float]:
        balance = self.bitvavo.balance({"symbol": "EUR"})
        logger.info(f"response Balance quote: {balance}")
        if balance:
            balance = balance[0]
        else:
            balance = {"available": 0, "inOrder": 0}
        return balance

    def place_limit_buy_order(
        self, limit_price: float, amount_in_quote: float
    ) -> Order:
        trading_pair = self.state.base + "-EUR"
        limit_price = self.__closest_valid_price(price=float(limit_price))

        amount_in_base = round(
            (float(amount_in_quote) - 0.01) / (limit_price * (1 + self.max_fee)),
            self.quantity_decimals(),
        )
        logger.info(
            f"""
            place limit buy order;
            market: {trading_pair}
            limitPrice: {limit_price}
            amount: {amount_in_base}
            operatorId: {self.operator_id}
            """
        )
        response = self.bitvavo.placeOrder(
            market=trading_pair,
            side="buy",
            orderType="limit",
            body={
                "amount": str(amount_in_base),
                "price": str(limit_price),
                "operatorId": self.operator_id,
            },
        )
        logger.info(f"place limit buy order response: {response}")
        if "errorCode" in response:
            error_code = response["errorCode"]
            if error_code in [107, 108, 109]:
                time.sleep(3)
                order = self.place_limit_buy_order(limit_price, amount_in_quote)
                return order
            elif error_code in [205, 210, 211, 214, 215]:
                raise InvalidOrderRequest(self.state.base)
            elif error_code == 216:
                balance = self.get_balance_quote()
                raise InsufficientBalanceError(balance, amount_in_quote)
            elif error_code == 217:
                raise InsufficientOrderValueError()
            else:
                raise Exception(str(response))

        order = order_from_bitvavo_response(response)
        if order.is_filled:
            """
            if the order is immediately filled, we have to treat the order as a market order.
            wait a bit to make sure the fills are registered in the exchange
            before fetching and processing the order info
            """
            time.sleep(3)
            order = self.get_order_info(order)
            self.state.process_filled_order(order)
        else:
            self.state.add_order(order)
        return order

    def place_limit_sell_order(
        self, limit_price: float, amount_in_base: float
    ) -> Order:
        trading_pair = self.state.base + "-EUR"

        quantity_decimals = self.quantity_decimals()
        factor = 1 / (10**quantity_decimals)
        amount_in_base = round(
            (float(amount_in_base) // factor) * factor,
            quantity_decimals,
        )

        limit_price = self.__closest_valid_price(price=float(limit_price))
        logger.info(
            f"""
            place limit sell order
            market: {trading_pair}
            amount: {amount_in_base}
            price: {limit_price}
            operatorId: {self.operator_id}
            """
        )
        response = self.bitvavo.placeOrder(
            market=trading_pair,
            side="sell",
            orderType="limit",
            body={
                "amount": str(amount_in_base),
                "price": str(limit_price),
                "operatorId": self.operator_id,
            },
        )
        logger.info(f"place limit sell order response: {response}")
        if "errorCode" in response:
            error_code = response["errorCode"]
            if error_code in [107, 108, 109]:
                time.sleep(3)
                order = self.place_limit_sell_order(limit_price, amount_in_base)
                return order
            elif error_code in [205, 210, 211, 214, 215]:
                raise InvalidOrderRequest(self.state.base)
            elif error_code == 216:
                balance = self.get_balance_base()
                raise InsufficientBalanceError(balance, amount_in_base)
            elif error_code == 217:
                raise InsufficientOrderValueError()
            else:
                raise Exception(str(response))

        order = order_from_bitvavo_response(response)
        if order.is_filled:
            """
            if the order is immediately filled, we have to treat the order as a market order.
            wait a bit to make sure the fills are registered in the exchange
            before fetching and processing the order info
            """
            time.sleep(3)
            order = self.get_order_info(order)
            self.state.process_filled_order(order)
        else:
            self.state.add_order(order)
        return order

    def place_market_buy_order(self, amount_in_quote: float) -> Order:
        trading_pair = self.state.base + "-EUR"

        amount_in_quote = str(round(float(amount_in_quote), 2))
        logger.info(
            f"""
            place market buy order
            market: {trading_pair}
            amountQuote: {amount_in_quote}
            operatorId: {self.operator_id}
            """
        )
        response = self.bitvavo.placeOrder(
            market=trading_pair,
            side="buy",
            orderType="market",
            body={"amountQuote": amount_in_quote, "operatorId": self.operator_id},
        )
        logger.info(f"place market buy order response: {response}")
        if "errorCode" in response:
            error_code = response["errorCode"]
            if error_code in [107, 108, 109]:
                time.sleep(3)
                order = self.place_market_buy_order(amount_in_quote)
                return order
            elif error_code in [205, 210, 211, 214, 215]:
                raise InvalidOrderRequest(self.state.base)
            elif error_code == 216:
                balance = self.get_balance_quote()
                raise InsufficientBalanceError(balance, amount_in_quote)
            elif error_code == 217:
                raise InsufficientOrderValueError()
            else:
                raise Exception(str(response))

        order = order_from_bitvavo_response(response)
        # wait a bit to make sure the fills are registered in the exchange
        time.sleep(3)
        order = self.get_order_info(order)
        self.state.process_filled_order(order)
        return order

    def place_market_sell_order(self, amount_in_base: float) -> Order:
        trading_pair = self.state.base + "-EUR"
        quantity_decimals = self.quantity_decimals()

        factor = 1 / (10**quantity_decimals)
        amount_in_base = round(
            (float(amount_in_base) // factor) * factor,
            quantity_decimals,
        )
        logger.info(
            f"""
            place market sell order
            market: {trading_pair}
            amount: {amount_in_base}
            operatorId: {self.operator_id}
            """
        )
        response = self.bitvavo.placeOrder(
            market=trading_pair,
            side="sell",
            orderType="market",
            body={"amount": str(amount_in_base), "operatorId": self.operator_id},
        )
        logger.info(f"place market sell order response: {response}")
        if "errorCode" in response:
            error_code = response["errorCode"]
            if error_code in [107, 108, 109]:
                time.sleep(3)
                order = self.place_market_sell_order(amount_in_base)
                return order
            elif error_code in [205, 210, 211, 214, 215]:
                raise InvalidOrderRequest(self.state.base)
            elif error_code == 216:
                balance = self.get_balance_base()
                raise InsufficientBalanceError(balance, amount_in_base)
            elif error_code == 217:
                raise InsufficientOrderValueError()
            else:
                raise Exception(str(response))

        order = order_from_bitvavo_response(response)
        # wait a bit to make sure the fills are registered in the exchange
        time.sleep(3)
        order = self.get_order_info(order)
        self.state.process_filled_order(order)
        return order

    def get_order_info(self, order: Order) -> Order:

        response = self.bitvavo.getOrder(market=order.market, orderId=order.order_id)
        logger.info(f"get order info response: {response}")
        if "errorCode" in response:
            if response["errorCode"] == 240:
                raise GetOrderInfoError(response)
        return order_from_bitvavo_response(response)

    def cancel_order(self, order: Order) -> Order:
        response = self.bitvavo.cancelOrder(
            market=order.market,
            orderId=order.order_id,
            operatorId=self.operator_id,
        )
        logger.info(f"cancel order response: {response}")
        if "errorCode" in response:
            if response["errorCode"] != 240:
                raise GetOrderInfoError(response)
        self.state.cancel_order(order)
        return order


def get_executor(
    person_id: str,
    exchange: SUPPORTED_EXCHANGES,
    state: State,
    credentials_repository: CredentialsRepository,
) -> ExchangeAssetClient:
    if exchange == "bitvavo":
        api_key = credentials_repository.get_api_key(person_id, exchange)
        api_secret_key = credentials_repository.get_api_secret_key(person_id, exchange)
        return BitvavoExchangeAssetClient(state, api_key, api_secret_key, operator_id=1)
    elif exchange == "backtest":
        return BacktestExchangeAssetClient(
            state, fee_market_order=0.0025, fee_limit_order=0.0015
        )
    else:
        raise ValueError(f"Unsupported exchange: {exchange}")
