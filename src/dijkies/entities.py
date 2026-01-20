from typing import Any, Literal, Optional, Union

from pydantic import BaseModel

from dijkies.constants import ACTION_STATUS, SUPPORTED_EXCHANGES
from dijkies.exceptions import (
    MultipleOrdersFoundError,
    NoOrderFoundError,
)


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
            found_order.fee = filled_order.fee

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


class Action(BaseModel):
    name: Literal[
        "place_limit_buy_order",
        "place_limit_sell_order",
        "place_market_buy_order",
        "place_market_sell_order",
        "place_limit_buy_order_by_fraction",
        "place_limit_sell_order_by_fraction",
        "place_market_buy_order_by_fraction",
        "place_market_sell_order_by_fraction",
        "cancel_order",
    ]
    arguments: dict[str, Any]
    status: ACTION_STATUS = "open"
