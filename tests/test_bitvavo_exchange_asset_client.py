import pytest

from dijkies.entities import Order
from dijkies.exchange_market_api import BitvavoMarketAPI
from dijkies.executors import BitvavoExchangeAssetClient
from dijkies.interfaces import ExchangeAssetClient


def state_is_in_sync_with_bitvavo(
    bitvavo_exchange_asset_client: BitvavoExchangeAssetClient,
) -> bool:
    state = bitvavo_exchange_asset_client.state

    base_response = bitvavo_exchange_asset_client.bitvavo.balance(
        {"symbol": bitvavo_exchange_asset_client.state.base}
    )
    quote_response = bitvavo_exchange_asset_client.bitvavo.balance({"symbol": "EUR"})

    available_base = float(base_response[0]["available"]) if base_response else 0
    available_quote = float(quote_response[0]["available"]) if quote_response else 0
    in_order_base = float(base_response[0]["inOrder"]) if base_response else 0
    in_order_quote = float(quote_response[0]["inOrder"]) if quote_response else 0

    available_base_matches = abs(state.base_available - available_base) < 1e-8
    in_order_base_matches = abs(state.base_on_hold - in_order_base) < 1e-8
    available_quote_matches = abs(state.quote_available - available_quote) < 1e-8
    in_order_quote_matches = abs(state.quote_on_hold - in_order_quote) < 1e-8

    return (
        available_base_matches
        and in_order_base_matches
        and available_quote_matches
        and in_order_quote_matches
    )


@pytest.mark.exchange
def test_bitvavo_exchange_asset_client_place_market_buy_order(
    bitvavo_exchange_asset_client: ExchangeAssetClient,
) -> None:

    # act

    order = bitvavo_exchange_asset_client.place_market_buy_order(10)

    # assert
    assert isinstance(order, Order)
    assert order in bitvavo_exchange_asset_client.state.orders
    assert state_is_in_sync_with_bitvavo(bitvavo_exchange_asset_client)


@pytest.mark.exchange
def test_bitvavo_exchange_asset_client_place_market_sell_order(
    bitvavo_exchange_asset_client: ExchangeAssetClient,
) -> None:

    # act

    order = bitvavo_exchange_asset_client.place_market_sell_order(0.0001)

    # assert
    assert isinstance(order, Order)
    assert order in bitvavo_exchange_asset_client.state.orders
    assert state_is_in_sync_with_bitvavo(bitvavo_exchange_asset_client)


@pytest.mark.exchange
def test_bitvavo_exchange_asset_client_place_and_cancel_limit_buy_order(
    bitvavo_exchange_asset_client: ExchangeAssetClient,
    bitvavo_market_api: BitvavoMarketAPI,
) -> None:

    # arrange
    limit_price = bitvavo_market_api.get_price("BTC") * 0.9
    amount_in_quote = bitvavo_exchange_asset_client.state.quote_available

    # act

    order = bitvavo_exchange_asset_client.place_limit_buy_order(
        limit_price, amount_in_quote
    )

    # assert
    assert isinstance(order, Order)
    assert order in bitvavo_exchange_asset_client.state.open_orders
    assert state_is_in_sync_with_bitvavo(bitvavo_exchange_asset_client)

    # act - cancel order

    canceled_order = bitvavo_exchange_asset_client.cancel_order(order)

    # assert
    assert canceled_order.status == "cancelled"
    assert canceled_order not in bitvavo_exchange_asset_client.state.open_orders
    assert canceled_order in bitvavo_exchange_asset_client.state.orders
    assert state_is_in_sync_with_bitvavo(bitvavo_exchange_asset_client)


@pytest.mark.exchange
def test_bitvavo_exchange_asset_client_place_and_cancel_limit_sell_order(
    bitvavo_exchange_asset_client: ExchangeAssetClient,
    bitvavo_market_api: BitvavoMarketAPI,
) -> None:

    # arrange

    limit_price = bitvavo_market_api.get_price("BTC") * 1.1
    amount_in_base = bitvavo_exchange_asset_client.state.base_available

    # act

    order = bitvavo_exchange_asset_client.place_limit_sell_order(
        limit_price, amount_in_base
    )

    # assert
    assert isinstance(order, Order)
    assert order in bitvavo_exchange_asset_client.state.open_orders
    assert state_is_in_sync_with_bitvavo(bitvavo_exchange_asset_client)

    # act - cancel order

    canceled_order = bitvavo_exchange_asset_client.cancel_order(order)

    # assert
    assert canceled_order.status == "cancelled"
    assert canceled_order not in bitvavo_exchange_asset_client.state.open_orders
    assert canceled_order in bitvavo_exchange_asset_client.state.orders
    assert state_is_in_sync_with_bitvavo(bitvavo_exchange_asset_client)


@pytest.mark.exchange
def test_bitvavo_exchange_asset_client_place_limit_buy_order_above_price(
    bitvavo_exchange_asset_client: ExchangeAssetClient,
    bitvavo_market_api: BitvavoMarketAPI,
) -> None:

    # arrange

    limit_price = bitvavo_market_api.get_price("BTC") * 1.1
    amount_in_quote = bitvavo_exchange_asset_client.state.quote_available

    # act / assert

    order = bitvavo_exchange_asset_client.place_limit_buy_order(
        limit_price, amount_in_quote
    )

    assert order.status == "filled"
    assert state_is_in_sync_with_bitvavo(bitvavo_exchange_asset_client)


@pytest.mark.exchange
def test_bitvavo_exchange_asset_client_place_limit_sell_order_below_price(
    bitvavo_exchange_asset_client: ExchangeAssetClient,
    bitvavo_market_api: BitvavoMarketAPI,
) -> None:

    # arrange

    limit_price = bitvavo_market_api.get_price("BTC") * 0.9
    amount_in_base = bitvavo_exchange_asset_client.state.base_available

    # act / assert

    order = bitvavo_exchange_asset_client.place_limit_sell_order(
        limit_price, amount_in_base
    )

    assert order.status == "filled"
    assert state_is_in_sync_with_bitvavo(bitvavo_exchange_asset_client)
