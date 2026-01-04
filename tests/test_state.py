import pandas as pd

from dijkies.executors import BacktestExchangeAssetClient, State


def test_place_limit_buy_order_adds_to_state():
    # Arrange
    start_investment_quote = 1000
    state = State(base="BTC", total_base=0, total_quote=start_investment_quote)
    client = BacktestExchangeAssetClient(
        state, fee_limit_order=0.0015, fee_market_order=0.0025
    )

    # Act
    order = client.place_limit_buy_order(
        base="BTC",
        limit_price=19000,
        amount_in_quote=500,
    )

    # Assert
    # 1. The order returned should be inside state.buy_orders
    assert order in state.buy_orders
    # 2. The order status should be open
    assert order.status == "open"
    # 3. The state's quote_available should have been reduced
    assert state.quote_available == start_investment_quote - 500
    # 4. The order should match the expected parameters
    assert order.market == "BTC"
    assert order.side == "buy"
    assert order.limit_price == 19000
    assert order.on_hold == 500


def test_cancel_limit_buy_order_moves_to_cancelled():
    # Arrange
    start_investment_quote = 1000
    start_investment_base = 1
    state = State(
        base="BTC",
        total_base=start_investment_base,
        total_quote=start_investment_quote,
    )
    client = BacktestExchangeAssetClient(
        state, fee_limit_order=0.0015, fee_market_order=0.0025
    )

    # Act: place a limit buy order
    order = client.place_limit_buy_order(
        base="BTC", limit_price=19000, amount_in_quote=500
    )

    # Assert: order is in open buy orders
    assert order in state.buy_orders
    assert order not in state.cancelled_orders
    assert order.status == "open"

    # Act: cancel the order
    client.cancel_order(order)

    # Assert: order is no longer in open buy orders
    assert order not in state.buy_orders
    # Order is added to cancelled orders
    assert order in state.cancelled_orders
    # Order status is updated
    assert order.status == "cancelled"
    # Quote balance restored
    assert state.quote_available == start_investment_quote


def test_multiple_limit_orders_create_fill_cancel():
    # Arrange
    start_investment_quote = 1000
    start_investment_base = 1
    state = State(
        base="BTC",
        total_base=start_investment_base,
        total_quote=start_investment_quote,
    )
    client = BacktestExchangeAssetClient(
        state, fee_limit_order=0.0015, fee_market_order=0.0025
    )

    # Place 3 buy limit orders
    order1 = client.place_limit_buy_order("BTC", limit_price=19500, amount_in_quote=200)
    order2 = client.place_limit_buy_order("BTC", limit_price=19000, amount_in_quote=300)
    order3 = client.place_limit_buy_order("BTC", limit_price=18000, amount_in_quote=400)

    # Precondition: all are open
    assert all(order.status == "open" for order in [order1, order2, order3])
    assert len(state.buy_orders) == 3
    assert len(state.filled_orders) == 0

    # Act: simulate a candle with low = 19000 (so order1 & order2 are fillable, order3 stays open)
    candle = pd.Series({"low": 19000, "high": 20000})
    client.update_current_candle(candle)
    client.update_state()

    # Assert:
    # - order1 and order2 should now be filled and in filled_orders
    assert order1.status == "filled"
    assert order2.status == "filled"
    assert order1 in state.filled_orders
    assert order2 in state.filled_orders
    # - order3 should remain open
    assert order3 in state.buy_orders
    assert order3.status == "open"
    # - filled orders are no longer in buy_orders
    assert order1 not in state.buy_orders
    assert order2 not in state.buy_orders
    # - quote balance decreased correctly (all open orders reduce balance on placement,
    #   then filled orders deduct fee but return filled base)
    assert state.number_of_transactions == 2
    # - amount of orders should be 3
    assert len(state.orders) == 3

    client.cancel_order(order3)

    assert len(state.open_orders) == 0
    assert len(state.cancelled_orders) == 1
    assert len(state.filled_orders) == 2
    assert len(state.orders) == 3

    retrieved_order = client.get_order_info(order3)

    assert retrieved_order.status == "cancelled"
