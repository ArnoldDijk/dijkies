from typing import Literal

SUPPORTED_EXCHANGES = Literal["bitvavo", "backtest"]
ACTION_STATUS = Literal["open", "completed", "failed"]
BOT_STATUS = Literal["active", "paused", "stopped"]
ASSET_HANDLING = Literal["quote_only", "base_only", "ignore"]
