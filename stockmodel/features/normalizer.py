"""
Feature normalization utilities: rolling backward-looking z-scores and cross-sectional rank scaling.
"""

import polars as pl
from stockmodel.data.schema import MarketDataSchema


def compute_rolling_zscore(
    col_name: str,
    window_size: int = 60,
    min_samples: int = 20,
    epsilon: float = 1e-8,
    symbol_col: str = MarketDataSchema.SYMBOL,
) -> pl.Expr:
    """
    Computes rolling backward-looking z-score:
        z_{i, t} = (x_{i, t} - mu_{x, 60d}) / (sigma_{x, 60d} + epsilon)
    Strictly backward looking, no forward leakage.
    """
    mean_expr = (
        pl.col(col_name)
        .rolling_mean(window_size=window_size, min_samples=min_samples)
        .over(symbol_col)
    )
    std_expr = (
        pl.col(col_name)
        .rolling_std(window_size=window_size, min_samples=min_samples, ddof=1)
        .over(symbol_col)
    )
    return ((pl.col(col_name) - mean_expr) / (std_expr + epsilon)).alias(f"{col_name}_z60")


def compute_cross_sectional_rank(
    col_name: str,
    date_col: str = MarketDataSchema.DATE,
    output_col: str = None,
) -> pl.Expr:
    """
    Scales feature values uniformly across active universe at date t into [-1.0, 1.0].
    """
    if output_col is None:
        output_col = f"{col_name}_csrank"

    rank_expr = pl.col(col_name).rank("average").over(date_col)
    count_expr = pl.col(col_name).count().over(date_col)

    return (
        pl.when(count_expr > 1)
        .then(2.0 * (rank_expr - 1.0) / (count_expr - 1.0) - 1.0)
        .when(count_expr == 1)
        .then(0.0)
        .otherwise(None)
        .alias(output_col)
    )
