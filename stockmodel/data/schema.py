"""
Market data schema definitions and Point-in-Time validation rules.
"""

from typing import List
import polars as pl


class MarketDataSchema:
    """Standardized column definitions for StockModel data feeds."""
    DATE = "date"
    SYMBOL = "symbol"
    SECTOR = "sector"
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"
    VWAP = "vwap"
    SHORT_INTEREST = "short_interest"
    ATM_CALL_GEX = "atm_call_gex"
    ATM_PUT_GEX = "atm_put_gex"
    PUT_VOLUME = "put_volume"
    CALL_VOLUME = "call_volume"
    VIX_SPOT = "vix_spot"
    VIX_3M = "vix_3m"
    DAYS_TO_EARNINGS = "days_to_earnings"
    SUE_SCORE = "sue_score"
    MARKET_CAP = "market_cap"

    REQUIRED_COLUMNS: List[str] = [
        DATE,
        SYMBOL,
        SECTOR,
        OPEN,
        HIGH,
        LOW,
        CLOSE,
        VOLUME,
    ]


def validate_market_data(df: pl.DataFrame) -> pl.DataFrame:
    """
    Validates market data against Point-in-Time integrity rules:
    1. Required columns present.
    2. Date column cast to Date dtype.
    3. Chronologically sorted per symbol.
    4. No duplicate (date, symbol) records.
    5. Positive prices and non-negative volumes.
    """
    missing = [c for c in MarketDataSchema.REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required market data columns: {missing}")

    # Ensure Date dtype
    if df.schema[MarketDataSchema.DATE] not in (pl.Date, pl.Datetime):
        df = df.with_columns(pl.col(MarketDataSchema.DATE).str.to_date().alias(MarketDataSchema.DATE))

    # Check for duplicate (date, symbol)
    duplicates = df.group_by([MarketDataSchema.DATE, MarketDataSchema.SYMBOL]).len().filter(pl.col("len") > 1)
    if duplicates.height > 0:
        raise ValueError(f"Found {duplicates.height} duplicate date-symbol entries violating point-in-time uniqueness.")

    # Validate price reasonableness
    invalid_prices = df.filter(
        (pl.col(MarketDataSchema.CLOSE) <= 0) |
        (pl.col(MarketDataSchema.HIGH) < pl.col(MarketDataSchema.LOW)) |
        (pl.col(MarketDataSchema.VOLUME) < 0)
    )
    if invalid_prices.height > 0:
        raise ValueError(f"Found {invalid_prices.height} records with non-positive close or inverted high/low.")

    # Sort strictly by date, symbol
    return df.sort([MarketDataSchema.DATE, MarketDataSchema.SYMBOL])
