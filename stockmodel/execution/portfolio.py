"""
Portfolio selection and volatility parity weighting engine.
"""

from typing import List, Dict, Tuple
import numpy as np
import pandas as pd


def select_decile_baskets(
    scores_df: pd.DataFrame,
    score_col: str = "pred",
    symbol_col: str = "symbol",
    top_quantile: float = 0.10,
    bottom_quantile: float = 0.10,
) -> Tuple[List[str], List[str]]:
    """
    Selects top decile long candidate symbols and bottom decile short candidates.

    Returns:
        Tuple of (long_symbols, short_symbols)
    """
    if len(scores_df) == 0:
        return [], []

    sorted_df = scores_df.sort_values(by=score_col, ascending=False).reset_index(drop=True)
    n = len(sorted_df)
    n_top = max(1, int(np.ceil(n * top_quantile)))
    n_bottom = max(1, int(np.ceil(n * bottom_quantile)))

    long_symbols = sorted_df.iloc[:n_top][symbol_col].tolist()
    short_symbols = sorted_df.iloc[-n_bottom:][symbol_col].tolist()

    return long_symbols, short_symbols


def compute_inverse_atr_weights(
    symbols: List[str],
    atr_series: pd.Series,
    min_atr: float = 1e-4,
) -> Dict[str, float]:
    """
    Computes inverse realized ATR-14 volatility parity weights:
        w_i = (1 / ATR_{14, i}) / sum_{j=1}^N (1 / ATR_{14, j})

    Args:
        symbols: List of constituent stock tickers.
        atr_series: Series keyed by symbol with ATR values.
        min_atr: Minimum floor to prevent division by zero.

    Returns:
        Dict mapping symbol to portfolio weight (summing to 1.0).
    """
    if not symbols:
        return {}

    atrs = np.array([max(min_atr, float(atr_series.get(s, min_atr))) for s in symbols])
    inv_atrs = 1.0 / atrs
    total_inv = np.sum(inv_atrs)

    if total_inv <= 0 or np.isnan(total_inv):
        equal_w = 1.0 / len(symbols)
        return {s: equal_w for s in symbols}

    weights = inv_atrs / total_inv
    return {s: float(w) for s, w in zip(symbols, weights)}
