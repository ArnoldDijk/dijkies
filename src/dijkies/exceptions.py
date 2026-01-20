class CrucialException(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class TimeColumnNotDefinedError(Exception):
    def __init__(self):
        super().__init__("the provided data should have a 'time' column")


class InvalidTypeForTimeColumnError(Exception):
    def __init__(self):
        super().__init__("'time' column has not the right dtype")


class DataTimeWindowShorterThanSuggestedAnalysisWindowError(Exception):
    def __init__(self):
        super().__init__(
            """
            the timespan of provided data is shorter than the analysis window,
            so no backtest can be executed.
            """
        )


class MissingOHLCVColumnsError(Exception):
    def __init__(self):
        super().__init__("one of the OHLCV columns is missing in the provided data")


class DataTimeSpanDifferentFromAlgorithmSetting(Exception):
    def __init__(self):
        super().__init__("one of the OHLCV columns is missing in the provided data")


class InvalidExchangeAssetClientError(Exception):
    def __init__(self):
        super().__init__("use BacktestExchangeAssetExecutor! glad that I saved you :)")


class NoOrderFoundError(Exception):
    def __init__(self, order_id):
        super().__init__(f"order with order_id {order_id} not found.")


class MultipleOrdersFoundError(Exception):
    def __init__(self, order_id):
        super().__init__(f"multiple orders found with order_id {order_id}.")


class PlaceOrderError(Exception):
    def __init__(self, message: str):
        super().__init__(f"an error occured during order creation: {message}")


class GetOrderInfoError(Exception):
    def __init__(self, message: str):
        super().__init__(f"an error occured during order info retrieval: {message}")


class CancelOrderError(Exception):
    def __init__(self, message: str):
        super().__init__(f"an error occured during cancelling order: {message}")


class MethodNotDefinedError(Exception):
    def __init__(self):
        super().__init__("method not implemented...")


class InsufficientBalanceError(CrucialException):
    def __init__(
        self,
        balance: dict[str, float],
        requested: float,
    ):
        super().__init__(
            f"""
            not enough balance:\n
            available: {balance["available"]}, requested: {requested}\n
            """
        )


class InsufficientOrderValueError(CrucialException):
    def __init__(self):
        super().__init__(
            """
            order value should be at least 5 euro:
            """
        )


class AssetNotAvailableError(CrucialException):
    def __init__(self, asset: str):
        super().__init__(
            f"""
            the asset {asset} in the strategy state is not available in the exchange.
            """
        )


class InvalidOrderRequest(CrucialException):
    def __init__(self, asset: str):
        super().__init__(
            f"""
            Invalid order request for {asset}
            """
        )
