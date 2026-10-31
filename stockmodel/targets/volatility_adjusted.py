"""
Volatility-Adjusted Multi-Week Cross-Sectional Target Engine.

Computes:
    y_{i, t} = Rank_t ( ln(P_{i, t+H} / P_{i, t}) / (sigma_{i, t, 20d} * sqrt(H)) )
with uniform scaling into [-1.0, 1.0].
"""

import numpy as np
import polars as pl
from stockmodel.data.schema import MarketDataSchema
from stockmodel.config import TargetConfig


def compute_volatility_adjusted_target(
    df: pl.DataFrame,
    config: TargetConfig = TargetConfig(),
) -> pl.DataFrame:
    """
    Computes the cross-sectionally ranked, volatility-adjusted H-day forward return target.

    Args:
        df: Input DataFrame containing date, symbol, close.
        config: TargetConfig containing horizon_days and vol_lookback_days.

    Returns:
        DataFrame with added columns:
            - 'log_ret': daily log return r_{i, t}
            - 'realized_vol_20d': 20-day annualized realized volatility sigma_{i, t, 20d}
            - 'fwd_log_ret_H': H-day forward log return ln(P_{t+H} / P_t)
            - 'vol_adjusted_raw_target': unscaled ratio
            - 'target': cross-sectional uniform rank scaled to [-1.0, 1.0]
    """
    h = config.horizon_days
    lookback = config.vol_lookback_days
    ann_factor = config.annualization_factor

    # Sort strictly by symbol and date
    sorted_df = df.sort([MarketDataSchema.SYMBOL, MarketDataSchema.DATE])

    # 1. Compute daily log returns per symbol
    # r_{i, t} = ln(close_t / close_{t-1})
    df_with_ret = sorted_df.with_columns(
        (pl.col(MarketDataSchema.CLOSE) / pl.col(MarketDataSchema.CLOSE).shift(1))
        .log()
        .over(MarketDataSchema.SYMBOL)
        .alias("log_ret")
    )

    # 2. Compute 20-day annualized realized volatility
    # sigma = sqrt( (252 / 20) * sum_{k=0}^{19} (r_{t-k} - r_bar)^2 )
    # Note: sample variance ddof=0 or 1: sum( (r - mean)^2 ) / 20 is exactly population variance,
    # so sqrt( 252 * rolling_std(ddof=0)^2 ) or sqrt(252) * rolling_std(ddof=0)
    df_with_vol = df_with_ret.with_columns(
        (
            pl.col("log_ret")
            .rolling_std(window_size=lookback, min_samples=lookback, ddof=0)
            .over(MarketDataSchema.SYMBOL)
            * np.sqrt(ann_factor)
        ).alias("realized_vol_20d")
    )

    # 3. Compute H-day forward log return: ln(close_{t+H} / close_t)
    df_with_fwd = df_with_vol.with_columns(
        (pl.col(MarketDataSchema.CLOSE).shift(-h) / pl.col(MarketDataSchema.CLOSE))
        .log()
        .over(MarketDataSchema.SYMBOL)
        .alias(f"fwd_log_ret_{h}")
    )

    # 4. Compute unscaled volatility-adjusted forward return
    # raw = fwd_log_ret / (sigma * sqrt(H))
    df_with_raw = df_with_fwd.with_columns(
        (
            pl.col(f"fwd_log_ret_{h}") /
            (pl.col("realized_vol_20d") * np.sqrt(h) + 1e-8)
        ).alias("vol_adjusted_raw_target")
    )

    # 5. Cross-sectional uniform ranking into [-1.0, 1.0] per date
    # Scaled rank = 2 * (rank - 1) / (N - 1) - 1 for valid observations
    # Using Polars expressions grouped by date:
    # rank("average") or rank("ordinal")
    df_ranked = df_with_raw.with_columns(
        pl.when(pl.col("vol_adjusted_raw_target").is_not_null())
        .then(
            pl.col("vol_adjusted_raw_target").rank("average").over(MarketDataSchema.DATE)
        )
        .otherwise(None)
        .alias("_rank_val"),
        pl.when(pl.col("vol_adjusted_raw_target").is_not_null())
        .then(
            pl.col("vol_adjusted_raw_target").count().over(MarketDataSchema.DATE)
        )
        .otherwise(None)
        .alias("_group_count"),
    ).with_columns(
        pl.when(pl.col("_group_count") > 1)
        .then(
            2.0 * (pl.col("_rank_val") - 1.0) / (pl.col("_group_count") - 1.0) - 1.0
        )
        .when(pl.col("_group_count") == 1)
        .then(0.0)
        .otherwise(None)
        .alias("target")
    ).drop(["_rank_val", "_group_count"])

    return df_ranked.sort([MarketDataSchema.DATE, MarketDataSchema.SYMBOL])
