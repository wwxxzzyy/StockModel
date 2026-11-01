"""
Tests for Moomoo OpenD Data Ingestion Engine.
"""

from unittest.mock import MagicMock, patch
import pandas as pd
import polars as pl
import pytest

from stockmodel.data.moomoo_loader import MoomooMarketLoader, DEFAULT_UNIVERSE, SECTOR_MAP
from stockmodel.data.schema import MarketDataSchema, validate_market_data


def test_moomoo_loader_init():
    loader = MoomooMarketLoader(host="192.168.1.20", port=11111, universe=["AAPL", "MSFT"])
    assert loader.host == "192.168.1.20"
    assert loader.port == 11111
    assert loader.universe == ["AAPL", "MSFT"]
    assert loader._us_code("AAPL") == "US.AAPL"
    assert loader._us_code("US.NVDA") == "US.NVDA"
    loader.close()


def test_moomoo_loader_live_connection():
    loader = MoomooMarketLoader(host="192.168.1.20", port=11111)
    connected, msg = loader.check_connection()
    # If gateway is online on LAN, verify success message
    if connected:
        assert "Connected to OpenD" in msg
    else:
        assert isinstance(msg, str)
    loader.close()


def test_moomoo_panel_schema_compliance():
    """Validates that a simulated Moomoo output DataFrame satisfies MarketDataSchema."""
    n_days = 20
    dates = pd.date_range("2026-09-01", periods=n_days, freq="B").strftime("%Y-%m-%d").tolist()
    records = []
    for d in dates:
        for sym in ["AAPL", "NVDA"]:
            records.append({
                "date": d,
                "symbol": sym,
                "sector": SECTOR_MAP.get(sym, "Technology"),
                "open": 100.0,
                "high": 105.0,
                "low": 98.0,
                "close": 102.0,
                "volume": 1_000_000.0,
                "turnover": 102_000_000.0,
                "vwap": 101.5,
                "market_cap": 2_000_000_000_000.0,
                "vix_spot": 17.5,
                "vix_3m": 19.0,
                "days_to_earnings": 30,
                "short_interest": 50_000_000.0,
                "sue_score": 0.5,
                "atm_call_gex": 10000.0,
                "atm_put_gex": 10000.0,
                "call_volume": 50000.0,
                "put_volume": 40000.0,
            })

    raw_df = pd.DataFrame(records)
    pl_df = pl.from_pandas(raw_df)
    validated = validate_market_data(pl_df)
    assert validated.height == n_days * 2
    assert MarketDataSchema.DATE in validated.columns
    assert MarketDataSchema.ATM_CALL_GEX in validated.columns
    assert MarketDataSchema.SHORT_INTEREST in validated.columns
