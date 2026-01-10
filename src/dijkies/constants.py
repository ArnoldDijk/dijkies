from typing import Literal

SUPPORTED_EXCHANGES = Literal["bitvavo", "backtest"]
BOT_STATUS = Literal["active", "paused", "stopped"]
ASSET_HANDLING = Literal["quote_only", "base_only", "ignore"]
