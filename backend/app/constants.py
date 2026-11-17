"""Static research constants: assets, buckets and checkpoint intervals."""
from __future__ import annotations

MARKET_DURATION_SECONDS = 300  # 5-minute markets only. 15m markets are excluded.
MARKET_WINDOW_LABEL = "5m"

ASSETS: dict[str, dict] = {
    "BTC": {"name": "Bitcoin", "slug": "btc", "chainlink": "btc/usd", "binance": "btcusdt", "coinbase": "BTC-USD"},
    "ETH": {"name": "Ethereum", "slug": "eth", "chainlink": "eth/usd", "binance": "ethusdt", "coinbase": "ETH-USD"},
    "SOL": {"name": "Solana", "slug": "sol", "chainlink": "sol/usd", "binance": "solusdt", "coinbase": "SOL-USD"},
    "XRP": {"name": "XRP", "slug": "xrp", "chainlink": "xrp/usd", "binance": "xrpusdt", "coinbase": "XRP-USD"},
    "DOGE": {"name": "Dogecoin", "slug": "doge", "chainlink": "doge/usd", "binance": "dogeusdt", "coinbase": "DOGE-USD"},
    "HYPE": {"name": "Hyperliquid", "slug": "hype", "chainlink": "hype/usd", "binance": "hypeusdt", "coinbase": "HYPE-USD"},
    "BNB": {"name": "BNB", "slug": "bnb", "chainlink": "bnb/usd", "binance": "bnbusdt", "coinbase": "BNB-USD"},
}

# Favourite implied-probability buckets: (low, high) — low inclusive, high exclusive
# except the final bucket which includes 1.0.
PROBABILITY_BUCKETS: list[tuple[float, float, str]] = [
    (0.50, 0.60, "50-60%"),
    (0.60, 0.70, "60-70%"),
    (0.70, 0.80, "70-80%"),
    (0.80, 0.85, "80-85%"),
    (0.85, 0.90, "85-90%"),
    (0.90, 0.93, "90-93%"),
    (0.93, 0.95, "93-95%"),
    (0.95, 0.97, "95-97%"),
    (0.97, 0.98, "97-98%"),
    (0.98, 0.99, "98-99%"),
    (0.99, 0.995, "99-99.5%"),
    (0.995, 1.0000001, "99.5-100%"),
]

# Underdog executable entry-price buckets (USD per share).
PRICE_BUCKETS: list[tuple[float, float, str]] = [
    (0.0, 0.01, "<1c"),
    (0.01, 0.02, "1-2c"),
    (0.02, 0.03, "2-3c"),
    (0.03, 0.05, "3-5c"),
    (0.05, 0.07, "5-7c"),
    (0.07, 0.10, "7-10c"),
    (0.10, 0.15, "10-15c"),
    (0.15, 0.2000001, "15-20c"),
]

# Seconds-before-settlement checkpoints. Never pooled together.
CHECKPOINTS: list[int] = [120, 90, 60, 45, 30, 20, 15, 10, 7, 5, 3, 2, 1]
KEY_CHECKPOINTS: list[int] = [10, 5, 3, 1]

# Settlement distance buckets in basis points of the opening reference price.
DISTANCE_BUCKETS_BPS: list[tuple[float, float, str]] = [
    (0, 1, "<1bp"),
    (1, 2, "1-2bp"),
    (2, 5, "2-5bp"),
    (5, 10, "5-10bp"),
    (10, 20, "10-20bp"),
    (20, 1e9, ">20bp"),
]

CALCULATOR_PRICES = [0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10, 0.15, 0.20]

MIN_SAMPLE_WARNING = 30   # below this a rate is flagged "insufficient sample"
MIN_SAMPLE_SOLID = 200    # below this a rate is flagged "small sample"


def bucket_for(value: float | None, buckets: list[tuple[float, float, str]]) -> str | None:
    if value is None:
        return None
    for lo, hi, label in buckets:
        if lo <= value < hi:
            return label
    return None


def probability_bucket(p: float | None) -> str | None:
    return bucket_for(p, PROBABILITY_BUCKETS)


def price_bucket(p: float | None) -> str | None:
    return bucket_for(p, PRICE_BUCKETS)


def distance_bucket(bps: float | None) -> str | None:
    return None if bps is None else bucket_for(abs(bps), DISTANCE_BUCKETS_BPS)
