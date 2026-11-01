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


def test_analyze_earnings_lifecycle_post_earnings_amzn():
    from stockmodel.data.moomoo_loader import analyze_earnings_lifecycle

    amzn_pubs = ["2026-04-29", "2026-07-30", "2026-10-29"]
    # 1 trading day after earnings release
    res = analyze_earnings_lifecycle("AMZN", "2026-10-30", amzn_pubs)

    assert res["is_post_earnings"] is True
    assert res["days_since_earnings"] == 1
    assert res["last_earnings_date"] == "2026-10-29"
    assert res["days_to_earnings"] >= 60
    assert "Passed 2026-10-29" in res["earnings_status_text"]


def test_analyze_earnings_lifecycle_blackout_aapl():
    from stockmodel.data.moomoo_loader import analyze_earnings_lifecycle

    aapl_pubs = ["2026-04-30", "2026-07-30", "2026-11-02"]
    # Friday 2026-10-30 before Monday 2026-11-02 earnings
    res = analyze_earnings_lifecycle("AAPL", "2026-10-30", aapl_pubs)

    assert res["is_post_earnings"] is False
    assert res["days_to_earnings"] == 1
    assert res["next_earnings_date"] == "2026-11-02"
    assert "Blackout" in res["earnings_status_text"]


def test_moomoo_earnings_calendar_cached():
    loader = MoomooMarketLoader(universe=["AAPL", "AMZN"])
    calendar = loader.fetch_earnings_calendar(["AAPL", "AMZN"], cache_path="data/earnings_calendar.json")

    assert "AMZN" in calendar
    assert "2026-10-29" in calendar["AMZN"]
    assert "AAPL" in calendar
    assert "2026-11-02" in calendar["AAPL"]
    loader.close()
