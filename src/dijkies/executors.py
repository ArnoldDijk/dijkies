import logging
import time
import uuid
from abc import ABC, abstractmethod
from decimal import ROUND_DOWN, Decimal, getcontext
from typing import Literal, Optional, Union

import pandas as pd
from pandas.core.series import Series
from pydantic import BaseModel
from python_bitvavo_api.bitvavo import Bitvavo

from dijkies.exceptions import (
    GetOrderInfoError,
    InsufficientBalanceError,
    InsufficientOrderValueError,
    MultipleOrdersFoundError,
    NoOrderFoundError,
)

SUPPORTED_EXCHANGES = Literal["bitvavo", "backtest"]


class Order(BaseModel):
    order_id: str
    exchange: SUPPORTED_EXCHANGES
    market: str
    time_created: int
    time_canceled: Union[int, None] = None
    time_filled: Union[int, None] = None
    on_hold: float = 0
    side: Literal["buy", "sell"]
    limit_price: Optional[float] = None
    actual_price: Optional[float] = None
    filled: float = 0
    filled_quote: float = 0
    fee: float = 0
    is_taker: bool
    status: Literal["open", "filled", "cancelled"]

    @property
    def is_filled(self) -> bool:
        return self.status == "filled"

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    def is_equal(self, order: "Order") -> bool:
        return self.status == order.status

    def is_not_equal(self, order: "Order") -> bool:
        return not self.is_equal(order)


class State(BaseModel):
    base: str
    total_base: float
    total_quote: float
    orders: list[Order] = []

    @property
    def number_of_transactions(self) -> int:
        return len(self.filled_orders)

    @property
    def total_fee_paid(self) -> float:
        return sum([o.fee for o in self.filled_orders])

    @property
    def filled_orders(self) -> list[Order]:
        return [o for o in self.orders if o.is_filled]

    @property
    def open_orders(self) -> list[Order]:
        return [o for o in self.orders if o.is_open]

    @property
    def cancelled_orders(self) -> list[Order]:
        return [o for o in self.orders if o.is_cancelled]

    @property
    def base_on_hold(self) -> float:
        return sum([order.on_hold for order in self.sell_orders])

    @property
    def quote_on_hold(self) -> float:
        return sum([order.on_hold for order in self.buy_orders])

    @property
    def base_available(self) -> float:
        return self.total_base - self.base_on_hold

    @property
    def quote_available(self) -> float:
        return self.total_quote - self.quote_on_hold

    @property
    def buy_orders(self) -> list[Order]:
        return [o for o in self.open_orders if o.side == "buy"]

    @property
    def sell_orders(self) -> list[Order]:
        return [o for o in self.open_orders if o.side == "sell"]

    def add_order(self, order: Order) -> None:
        self.orders.append(order)

    def get_order(self, order_id: str) -> Order:
        list_found_order = [o for o in self.orders if o.order_id == order_id]
        if len(list_found_order) == 0:
            raise NoOrderFoundError(order_id)
        elif len(list_found_order) > 1:
            raise MultipleOrdersFoundError(order_id)
        return list_found_order[0]

    def cancel_order(self, order: Order) -> None:
        found_order = self.get_order(order.order_id)
        found_order.status = "cancelled"

    def process_filled_order(self, filled_order: Order) -> None:
        if filled_order.side == "buy":
            quote_mutation = -(filled_order.filled_quote + filled_order.fee)
            base_mutation = filled_order.filled
        else:
            quote_mutation = filled_order.filled_quote - filled_order.fee
            base_mutation = -filled_order.filled

        self.total_quote += quote_mutation
        self.total_base += base_mutation

        if filled_order.is_taker:
            self.add_order(filled_order)
        else:
            found_order = self.get_order(filled_order.order_id)
            found_order.status = "filled"

        self._check_non_negative()

    def _check_non_negative(self) -> None:
        if self.base_available < -1e-9:
            raise ValueError(f"Negative base balance: {self.base_available}")
        if self.quote_available < -1e-9:
            raise ValueError(f"Negative quote balance: {self.quote_available}")

    def total_value_in_base(self, price: float) -> float:
        return self.total_base + self.total_quote / price

    def total_value_in_quote(self, price: float) -> float:
        return self.total_quote + self.total_base * price

    def fraction_value_in_quote(self, price: float) -> float:
        return self.total_quote / max(self.total_value_in_quote(price), 0.00000001)

    def fraction_value_in_base(self, price: float) -> float:
        return 1 - self.fraction_value_in_quote(price)


class ExchangeAssetClient(ABC):
    def __init__(self, state: State) -> None:
        self.state = state

    @abstractmethod
    def place_limit_buy_order(
        self, base: str, limit_price: float, amount_in_quote: float
    ) -> Order:
        pass

    @abstractmethod
    def place_limit_sell_order(
        self, base: str, limit_price: float, amount_in_base: float
    ) -> Order:
        pass

    @abstractmethod
    def place_market_buy_order(self, base: str, amount_in_quote: float) -> Order:
        pass

    @abstractmethod
    def place_market_sell_order(self, base: str, amount_in_base: float) -> Order:
        pass

    @abstractmethod
    def get_order_info(self, order: Order) -> Order:
        pass

    @abstractmethod
    def cancel_order(self, order: Order) -> Order:
        pass

    def update_state(self) -> None:
        for order in self.state.open_orders:
            newest_info_order = self.get_order_info(order)
            if order.is_not_equal(newest_info_order):
                self.state.process_filled_order(newest_info_order)


class BacktestExchangeAssetClient(ExchangeAssetClient):
    def __init__(
        self, state: State, fee_market_order: float, fee_limit_order: float
    ) -> None:
        super().__init__(state)
        self.fee_market_order = fee_market_order
        self.fee_limit_order = fee_limit_order
        self.current_candle = pd.Series({"high": 80000, "low": 78000, "close": 79000})

    def update_current_candle(self, current_candle: Series) -> None:
        self.current_candle = current_candle

    def place_limit_buy_order(
        self, base: str, limit_price: float, amount_in_quote: float
    ) -> Order:
        order = Order(
            order_id=str(uuid.uuid4()),
            exchange="bitvavo",
            time_created=int(time.time()),
            market=base,
            side="buy",
            limit_price=limit_price,
            on_hold=amount_in_quote,
            status="open",
            is_taker=False,
        )

        self.state.add_order(order)

        return order

    def place_limit_sell_order(
        self, base: str, limit_price: float, amount_in_base: float
    ) -> Order:
        order = Order(
            order_id=str(uuid.uuid4()),
            exchange="bitvavo",
            time_created=int(time.time()),
            market=base,
            side="sell",
            limit_price=limit_price,
            on_hold=amount_in_base,
            status="open",
            is_taker=False,
        )

        self.state.add_order(order)

        return order

    def place_market_buy_order(self, base: str, amount_in_quote: float) -> Order:
        fee = amount_in_quote * self.fee_market_order / (1 + self.fee_market_order)
        amount_in_base = (amount_in_quote - fee) / self.current_candle.close

        order = Order(
            order_id=str(uuid.uuid4()),
            exchange="bitvavo",
            time_created=int(time.time()),
            market=base,
            side="buy",
            filled=amount_in_base,
            filled_quote=amount_in_quote - fee,
            status="filled",
            fee=fee,
            is_taker=True,
        )

        self.state.process_filled_order(order)

        return order

    def place_market_sell_order(self, base: str, amount_in_base: float) -> Order:
        amount_in_quote = amount_in_base * self.current_candle.close
        fee = amount_in_quote * self.fee_market_order

        order = Order(
            order_id=str(uuid.uuid4()),
            exchange="bitvavo",
            time_created=int(time.time()),
            market=base,
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
        logger: logging.Logger,
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
        self.logger = logger

    def quantity_decimals(self, base: str) -> int:
        trading_pair = base + "-EUR"
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

    def get_balance(self, base: str) -> dict[str, float]:
        balance = self.bitvavo.balance({"symbol": base})
        if balance:
            balance = balance[0]
        else:
            balance = {"available": 0, "inOrder": 0}
        return balance

    def place_limit_buy_order(
        self, base: str, limit_price: float, amount_in_quote: float
    ) -> Order:
        trading_pair = base + "-EUR"
        limit_price = self.__closest_valid_price(price=float(limit_price))

        amount_in_base = round(
            (float(amount_in_quote) - 0.01) / (limit_price * (1 + self.max_fee)),
            self.quantity_decimals(base),
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
        if "errorCode" in response:
            error_code = response["errorCode"]
            if error_code in [107, 108, 109]:
                time.sleep(3)
                order = self.place_limit_buy_order(base, limit_price, amount_in_quote)
                return order
            elif error_code == 216:
                balance = self.get_balance(base)
                raise InsufficientBalanceError(balance, amount_in_base)
            elif error_code == 217:
                raise InsufficientOrderValueError()
            else:
                raise Exception(str(response))

        order = order_from_bitvavo_response(response)
        self.state.add_order(order)
        return order

    def place_limit_sell_order(
        self, base: str, limit_price: float, amount_in_base: float
    ) -> Order:
        trading_pair = base + "-EUR"

        quantity_decimals = self.quantity_decimals(base)

        factor = 1 / (10**quantity_decimals)
        amount_in_base = round(
            (float(amount_in_base) // factor) * factor,
            quantity_decimals,
        )

        limit_price = self.__closest_valid_price(price=float(limit_price))

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
        if "errorCode" in response:
            error_code = response["errorCode"]
            if error_code in [107, 108, 109]:
                time.sleep(3)
                order = self.place_limit_sell_order(base, limit_price, amount_in_base)
                return order
            elif error_code == 216:
                balance = self.get_balance(base)
                raise InsufficientBalanceError(balance, amount_in_base)
            elif error_code == 217:
                raise InsufficientOrderValueError()
            else:
                raise Exception(str(response))

        order = order_from_bitvavo_response(response)
        self.state.add_order(order)
        return order

    def place_market_buy_order(self, base: str, amount_in_quote: float) -> Order:
        trading_pair = base + "-EUR"

        amount_in_quote = str(round(float(amount_in_quote), 2))

        response = self.bitvavo.placeOrder(
            market=trading_pair,
            side="buy",
            orderType="market",
            body={"amountQuote": amount_in_quote, "operatorId": self.operator_id},
        )
        if "errorCode" in response:
            error_code = response["errorCode"]
            if error_code in [107, 108, 109]:
                time.sleep(3)
                order = self.place_market_buy_order(base, amount_in_quote)
                return order
            elif error_code == 216:
                balance = self.get_balance("EUR")
                raise InsufficientBalanceError(balance, amount_in_quote)
            elif error_code == 217:
                raise InsufficientOrderValueError()
            else:
                raise Exception(str(response))

        order = order_from_bitvavo_response(response)
        time.sleep(3)
        order = self.get_order_info(order)
        self.state.process_filled_order(order)
        return order

    def place_market_sell_order(self, base: str, amount_in_base: float) -> Order:
        trading_pair = base + "-EUR"
        quantity_decimals = self.quantity_decimals(base)

        factor = 1 / (10**quantity_decimals)
        amount_in_base = round(
            (float(amount_in_base) // factor) * factor,
            quantity_decimals,
        )
        response = self.bitvavo.placeOrder(
            market=trading_pair,
            side="sell",
            orderType="market",
            body={"amount": str(amount_in_base), "operatorId": self.operator_id},
        )
        if "errorCode" in response:
            error_code = response["errorCode"]
            if error_code in [107, 108, 109]:
                time.sleep(3)
                order = self.place_market_sell_order(base, amount_in_base)
                return order
            elif error_code == 216:
                balance = self.get_balance(base)
                raise InsufficientBalanceError(balance, amount_in_base)
            elif error_code == 217:
                raise InsufficientOrderValueError()
            else:
                raise Exception(str(response))

        order = order_from_bitvavo_response(response)
        time.sleep(3)
        order = self.get_order_info(order)
        self.state.process_filled_order(order)
        return order

    def get_order_info(self, order: Order) -> Order:

        response = self.bitvavo.getOrder(market=order.market, orderId=order.order_id)
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
        if "errorCode" in response:
            if response["errorCode"] != 240:
                raise GetOrderInfoError(response)
        self.state.cancel_order(order)
