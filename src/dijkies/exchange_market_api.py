import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from binance.client import Client
from pandas.core.frame import DataFrame as PandasDataFrame
from python_bitvavo_api.bitvavo import Bitvavo

from dijkies.interfaces import ExchangeMarketAPI

logger = logging.getLogger(__name__)


class BinanceMarketAPI(ExchangeMarketAPI):
    def __init__(
        self,
        logger: logging.Logger = logger,
    ):
        self.logger = logger
        self.binance_data_client = Client()

    def get_candles(
        self,
        base: str = "BTC",
        interval_in_minutes: int = 60,
        lookback_in_minutes: int = 24 * 62 * 60,
    ) -> PandasDataFrame:
        trading_pair = base + "USDT"
        interval = f"{int(interval_in_minutes / 60)}h"
        lookback = f"{lookback_in_minutes} min ago UTC"
        df = pd.DataFrame(
            self.binance_data_client.get_historical_klines(
                symbol=trading_pair, interval=interval, start_str=lookback
            )
        )

        df = df.iloc[:, :6]
        df.columns = ["time", "open", "high", "low", "close", "volume"]
        df.time = pd.to_datetime(df.time, unit="ms", utc=True)
        df[["open", "high", "low", "close", "volume"]] = df[
            ["open", "high", "low", "close", "volume"]
        ].astype(float)

        return df

    def get_price(self, base: str = "BTC") -> float:
        trading_pair = base + "USDT"
        key = f"https://api.binance.com/api/v3/ticker/price?symbol={trading_pair}"
        data = requests.get(key)
        data = data.json()
        return float(data["price"])  # type: ignore


class BitvavoMarketAPI(ExchangeMarketAPI):
    def __init__(
        self,
        logger: logging.Logger = logger,
        max_workers: int = 4,
        rate_limit_threshold: int = 50,
    ):
        self.logger = logger
        self.bitvavo_data_client = Bitvavo()
        self.max_workers = max_workers
        self.rate_limit_threshold = rate_limit_threshold
        self._lock = threading.Lock()  # shared rate-limit lock

    def _wait_if_rate_limited(self):
        """Check Bitvavo remaining limit and sleep if it's too low."""
        remaining = self.bitvavo_data_client.getRemainingLimit()
        if remaining < self.rate_limit_threshold:
            self.logger.warning(
                f"💤 Rate limit low ({remaining}). Sleeping 60s to recover."
            )
            time.sleep(60)

    def _fetch_candle_chunk(
        self, trading_pair: str, interval: str, start: int, end: int
    ) -> PandasDataFrame:
        """Fetch a single chunk of candles and return as DataFrame."""
        options = {"start": f"{start}", "end": f"{end}"}

        with self._lock:
            # Ensure only one thread checks/sleeps for rate limit at a time
            self._wait_if_rate_limited()

        try:
            candles = self.bitvavo_data_client.candles(trading_pair, interval, options)
        except Exception as e:
            self.logger.error(f"⚠️ Error fetching candles ({start}-{end}): {e}")
            return pd.DataFrame(
                [], columns=["time", "open", "high", "low", "close", "volume"]
            )

        if not candles:
            return pd.DataFrame(
                [], columns=["time", "open", "high", "low", "close", "volume"]
            )

        df = pd.DataFrame(
            candles, columns=["time", "open", "high", "low", "close", "volume"]
        )
        df.time = pd.to_datetime(df.time, unit="ms", utc=True)
        df[["open", "high", "low", "close", "volume"]] = df[
            ["open", "high", "low", "close", "volume"]
        ].astype(float)
        df = df.iloc[::-1].reset_index(drop=True)
        return df

    def get_candles(
        self,
        base: str = "BTC",
        interval_in_minutes: int = 60,
        lookback_in_minutes: int = 60 * 24 * 60,
    ) -> PandasDataFrame:
        trading_pair = base + "-EUR"

        # Determine correct Bitvavo interval
        if interval_in_minutes < 3:
            corrected_interval = 1
            interval = "1m"
        elif interval_in_minutes < 10:
            corrected_interval = 5
            interval = "5m"
        elif interval_in_minutes < 23:
            corrected_interval = 15
            interval = "15m"
        elif interval_in_minutes < 45:
            corrected_interval = 30
            interval = "30m"
        elif interval_in_minutes < 90:
            corrected_interval = 60
            interval = "1h"
        elif interval_in_minutes < 180:
            corrected_interval = 120
            interval = "2h"
        elif interval_in_minutes < 300:
            corrected_interval = 240
            interval = "4h"
        elif interval_in_minutes < 420:
            corrected_interval = 360
            interval = "6h"
        elif interval_in_minutes < 600:
            corrected_interval = 480
            interval = "8h"
        elif interval_in_minutes < 1080:
            corrected_interval = 720
            interval = "12h"
        elif interval_in_minutes < 4 * 1440:
            corrected_interval = 1440
            interval = "1d"
        elif interval_in_minutes < 19 * 1440:
            corrected_interval = 1440 * 7
            interval = "1W"
        else:
            corrected_interval = 1440 * 30
            interval = "1M"

        now = int(time.time() * 1000)
        start = now - lookback_in_minutes * 60000

        # Split into chunks
        chunk_size_minutes = (
            corrected_interval * 1440
        )  # 1440 x interval minutes per chunk
        chunks = []
        s = start
        while s < now:
            e = s + chunk_size_minutes * 60000
            chunks.append((s, e))
            s = e - corrected_interval * 60000  # small overlap to prevent gaps

        self.logger.info(
            f"""
            📮 Fetching {len(chunks)} chunks in parallel (interval={interval},
            max_workers={self.max_workers})
            """
        )

        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_range = {
                executor.submit(
                    self._fetch_candle_chunk, trading_pair, interval, s, e
                ): (s, e)
                for (s, e) in chunks
            }

            for future in as_completed(future_to_range):
                s, e = future_to_range[future]
                try:
                    df = future.result()
                    results.append(df)
                except Exception as exc:
                    self.logger.error(f"❌ Chunk {s}-{e} generated an exception: {exc}")

        if not results:
            return pd.DataFrame(
                [], columns=["time", "open", "high", "low", "close", "volume"]
            )

        all_df = (
            pd.concat(results)
            .drop_duplicates()
            .sort_values("time")
            .reset_index(drop=True)
        )
        self.logger.info(f"✅ Retrieved {len(all_df)} candles successfully.")
        return all_df

    def get_price(self, base: str = "BTC") -> float:
        trading_pair = base + "-EUR"
        price = self.bitvavo_data_client.tickerPrice({"market": trading_pair})

        return float(price["price"])
