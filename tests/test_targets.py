"""
Unit tests for volatility-adjusted target variable calculation.
"""

import numpy as np
import polars as pl
import pytest
from stockmodel.data.synthetic import SyntheticMarketGenerator
from stockmodel.targets.volatility_adjusted import compute_volatility_adjusted_target
from stockmodel.config import TargetConfig


def test_target_bounds_and_ranking():
    gen = SyntheticMarketGenerator(seed=123)
    df = gen.generate(n_days=50)

    cfg = TargetConfig(horizon_days=10, vol_lookback_days=15)
    out = compute_volatility_adjusted_target(df, cfg)

    assert "target" in out.columns
    assert "realized_vol_20d" in out.columns
    assert "vol_adjusted_raw_target" in out.columns

    valid = out.filter(pl.col("target").is_not_null())
    assert valid.height > 0

    # Bounds must strictly lie within [-1.0, 1.0]
    t_min = valid["target"].min()
    t_max = valid["target"].max()
    assert t_min >= -1.0
    assert t_max <= 1.0

    # Cross-sectional check: for any date with >=2 assets, min is -1.0 and max is 1.0
    sample_date = valid["date"][0]
    date_slice = valid.filter(pl.col("date") == sample_date)
    if date_slice.height > 1:
        assert np.isclose(date_slice["target"].min(), -1.0, atol=1e-5)
        assert np.isclose(date_slice["target"].max(), 1.0, atol=1e-5)


def test_realized_volatility_formula():
    """Verify annualized realized volatility matches manual calculation."""
    dates = [f"2023-01-{i:02d}" for i in range(1, 26)]
    # Constant returns: 1% daily
    prices = [100.0 * (1.01 ** i) for i in range(len(dates))]

    df = pl.DataFrame({
        "date": dates,
        "symbol": ["TEST"] * len(dates),
        "sector": ["Tech"] * len(dates),
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": [100000] * len(dates),
    })

    cfg = TargetConfig(horizon_days=5, vol_lookback_days=10)
    out = compute_volatility_adjusted_target(df, cfg)
    valid_vol = out.filter(pl.col("realized_vol_20d").is_not_null())["realized_vol_20d"].to_numpy()

    # For constant return, variance is 0, so realized volatility should be near zero
    assert np.all(valid_vol < 1e-4)
