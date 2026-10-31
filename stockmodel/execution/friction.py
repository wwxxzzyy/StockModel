"""
Execution Friction Model: Slippage and Short Borrow Costs.

Specifications:
- Slippage model: 8 bps per trade for large caps, 15 bps for mid caps.
- Short borrow cost: Subtracted continuously using point-in-time annualized borrow rates.
"""

from typing import Dict


def compute_execution_friction(
    traded_weights: Dict[str, float],
    market_cap_map: Dict[str, float],
    active_short_weights: Dict[str, float],
    large_cap_threshold: float = 1e10,  # $10 Billion
    large_cap_slippage_bps: float = 8.0,
    mid_cap_slippage_bps: float = 15.0,
    annual_short_borrow_bps: float = 100.0,
    trading_days_per_year: float = 252.0,
) -> float:
    """
    Computes total frictional drag (slippage + short borrow cost) for the current step.

    Args:
        traded_weights: Absolute turnover weight per symbol: |w_new - w_old|.
        market_cap_map: Dict mapping symbol -> point-in-time market cap in USD.
        active_short_weights: Dict mapping symbol -> negative weight for active short positions.
        large_cap_threshold: Market cap above which 8 bps slippage applies; below uses 15 bps.
        large_cap_slippage_bps: Slippage in basis points for large cap stocks (0.0008).
        mid_cap_slippage_bps: Slippage in basis points for mid cap stocks (0.0015).
        annual_short_borrow_bps: Annualized short borrow fee in basis points.
        trading_days_per_year: 252.

    Returns:
        float: Total friction drag fraction (e.g. 0.0004 = 4 bps).
    """
    total_friction = 0.0

    # 1. Slippage drag on traded turnover
    for sym, delta_w in traded_weights.items():
        if delta_w <= 0:
            continue
        mcap = market_cap_map.get(sym, 5e10)
        bps = large_cap_slippage_bps if mcap >= large_cap_threshold else mid_cap_slippage_bps
        slippage_fraction = bps / 10000.0
        total_friction += delta_w * slippage_fraction

    # 2. Continuous daily short borrow fee
    daily_borrow_rate = (annual_short_borrow_bps / 10000.0) / trading_days_per_year
    for sym, short_w in active_short_weights.items():
        # short_w is negative, take abs
        abs_short = abs(short_w)
        total_friction += abs_short * daily_borrow_rate

    return float(total_friction)
