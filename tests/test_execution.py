"""
Unit tests for portfolio selection, earnings blackouts, inertia bands, and friction.
"""

import numpy as np
import pandas as pd
import pytest
from stockmodel.execution.portfolio import select_decile_baskets, compute_inverse_atr_weights
from stockmodel.execution.blackouts import apply_earnings_blackouts
from stockmodel.execution.rebalance import RebalanceManager
from stockmodel.execution.friction import compute_execution_friction


def test_decile_basket_selection():
    df = pd.DataFrame({
        "symbol": [f"S_{i}" for i in range(100)],
        "pred": np.linspace(-1.0, 1.0, 100),
    })

    longs, shorts = select_decile_baskets(df, top_quantile=0.10, bottom_quantile=0.10)
    assert len(longs) == 10
    assert len(shorts) == 10
    # Top values should be in longs
    assert "S_99" in longs
    # Lowest values should be in shorts
    assert "S_0" in shorts


def test_inverse_atr_weights():
    symbols = ["AAPL", "TSLA"]
    # TSLA has double the ATR of AAPL
    atr_series = pd.Series({"AAPL": 2.0, "TSLA": 4.0})

    weights = compute_inverse_atr_weights(symbols, atr_series)
    assert np.isclose(sum(weights.values()), 1.0)
    # AAPL should have double the weight of TSLA (inverse ATR parity)
    assert np.isclose(weights["AAPL"], 2.0 * weights["TSLA"])


def test_earnings_blackouts():
    # 1. Entry blackout: symbol with DTE <= 3 must be blocked from entry
    candidates = {"AAPL", "MSFT", "GOOG"}
    dte_map = {"AAPL": 2, "MSFT": 10, "GOOG": 1}

    _, approved = apply_earnings_blackouts(
        current_holdings={},
        candidate_symbols=candidates,
        days_to_earnings_map=dte_map,
        entry_blackout_days=3,
    )
    assert "MSFT" in approved
    assert "AAPL" not in approved
    assert "GOOG" not in approved

    # 2. Existing holding trim: holding with DTE <= 2 trimmed by 50%
    holdings = {"MSFT": 0.50, "AAPL": 0.50}
    adjusted, _ = apply_earnings_blackouts(
        current_holdings=holdings,
        candidate_symbols=set(),
        days_to_earnings_map=dte_map,
        trim_days_prior=2,
        trim_ratio=0.50,
    )
    assert np.isclose(adjusted["MSFT"], 0.50)  # DTE=10 > 2, unaffected
    assert np.isclose(adjusted["AAPL"], 0.25)  # DTE=2 <= 2, trimmed 50%


def test_rebalance_inertia_band():
    """Verify holding is kept unless cross-sectional percentile drops below 60th pct."""
    mgr = RebalanceManager(inertia_exit_percentile=0.60)

    # Symbol A is currently held, score drops to 65th percentile (above 60th) -> KEEP
    # Symbol B is currently held, score drops to 50th percentile (below 60th) -> DROP
    symbols = [f"S_{i}" for i in range(100)]
    scores = np.linspace(0.0, 1.0, 100)
    scores_df = pd.DataFrame({"symbol": symbols, "pred": scores})
    atr_series = pd.Series({s: 2.0 for s in symbols})
    dte_map = {s: 50 for s in symbols}

    current_holdings = {"S_65": 0.50, "S_50": 0.50}

    new_weights = mgr.rebalance_portfolio(
        current_holdings=current_holdings,
        scores_df=scores_df,
        atr_series=atr_series,
        days_to_earnings_map=dte_map,
        allow_short=False,
    )

    assert "S_65" in new_weights  # Kept due to inertia
    assert "S_50" not in new_weights  # Dropped because below 60th percentile


def test_friction_calculation():
    # Large cap (8 bps) vs mid cap (15 bps)
    traded = {"LARGE": 0.50, "MID": 0.50}
    mcap = {"LARGE": 50e9, "MID": 5e9}  # threshold is 10e9

    friction = compute_execution_friction(
        traded_weights=traded,
        market_cap_map=mcap,
        active_short_weights={},
        large_cap_threshold=10e9,
        large_cap_slippage_bps=8.0,
        mid_cap_slippage_bps=15.0,
    )

    expected = 0.50 * (8.0 / 10000.0) + 0.50 * (15.0 / 10000.0)
    assert np.isclose(friction, expected)
