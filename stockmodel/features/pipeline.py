"""
Feature Pipeline Engine.

Implements all 7 core features specified in Section 4:
1. Short Squeeze Pressure
2. Net Gamma Exposure (GEX)
3. Put/Call Ratio Momentum
4. Sector-Relative Momentum
5. VWAP Divergence
6. VIX Term Structure Slope
7. SUE Score (Fundamental Drift)
"""

from typing import List, Tuple
import polars as pl
from stockmodel.data.schema import MarketDataSchema
from stockmodel.config import FeatureConfig
from stockmodel.features.normalizer import compute_rolling_zscore, compute_cross_sectional_rank


class FeaturePipeline:
    """
    Polars-accelerated feature factory ensuring strict temporal hygiene (no lookahead bias).
    """

    FEATURE_NAMES: List[str] = [
        "feat_short_squeeze_pressure",
        "feat_net_gex",
        "feat_pcr_momentum",
        "feat_sector_relative_momentum",
        "feat_vwap_divergence",
        "feat_vix_slope",
        "feat_sue_score",
    ]

    def __init__(self, config: FeatureConfig = FeatureConfig()):
        self.config = config

    def build_features(self, df: pl.DataFrame) -> Tuple[pl.DataFrame, List[str]]:
        """
        Transforms raw point-in-time market data into full normalized feature panel.

        Returns:
            Tuple of (DataFrame with features and normalizations, list of active feature column names)
        """
        cfg = self.config
        eps = cfg.epsilon

        # Ensure sorted by symbol and date
        p = df.sort([MarketDataSchema.SYMBOL, MarketDataSchema.DATE])

        # -------------------------------------------------------------
        # 1. Base Moving Averages and Rolling Quantities per Symbol
        # -------------------------------------------------------------
        # True Range: max(H - L, |H - C_prev|, |L - C_prev|)
        p = p.with_columns(
            pl.col(MarketDataSchema.CLOSE).shift(1).over(MarketDataSchema.SYMBOL).alias("_prev_close")
        ).with_columns(
            pl.max_horizontal(
                pl.col(MarketDataSchema.HIGH) - pl.col(MarketDataSchema.LOW),
                (pl.col(MarketDataSchema.HIGH) - pl.col("_prev_close")).abs(),
                (pl.col(MarketDataSchema.LOW) - pl.col("_prev_close")).abs(),
            ).alias("_tr")
        )

        # ATR 14-day
        p = p.with_columns(
            pl.col("_tr")
            .rolling_mean(window_size=cfg.atr_period, min_samples=cfg.atr_period)
            .over(MarketDataSchema.SYMBOL)
            .alias("atr_14")
        )

        # ADV 20-day (Average Daily Volume)
        p = p.with_columns(
            pl.col(MarketDataSchema.VOLUME)
            .rolling_mean(window_size=cfg.adv_period, min_samples=cfg.adv_period)
            .over(MarketDataSchema.SYMBOL)
            .alias("adv_20")
        )

        # SMA 50-day
        p = p.with_columns(
            pl.col(MarketDataSchema.CLOSE)
            .rolling_mean(window_size=cfg.sma_trend_period, min_samples=cfg.sma_trend_period)
            .over(MarketDataSchema.SYMBOL)
            .alias("sma_50")
        )

        # 20-day Rolling VWAP = sum(Close * Volume, 20) / sum(Volume, 20)
        p = p.with_columns(
            (
                (pl.col(MarketDataSchema.CLOSE) * pl.col(MarketDataSchema.VOLUME))
                .rolling_sum(window_size=cfg.vwap_period, min_samples=cfg.vwap_period)
                .over(MarketDataSchema.SYMBOL)
                / (
                    pl.col(MarketDataSchema.VOLUME)
                    .rolling_sum(window_size=cfg.vwap_period, min_samples=cfg.vwap_period)
                    .over(MarketDataSchema.SYMBOL) + eps
                )
            ).alias("vwap_20")
        )

        # 20-day Return: r_{i, 20d} = (close_t - close_{t-20}) / close_{t-20}
        p = p.with_columns(
            (
                (pl.col(MarketDataSchema.CLOSE) - pl.col(MarketDataSchema.CLOSE).shift(cfg.sector_momentum_period))
                / (pl.col(MarketDataSchema.CLOSE).shift(cfg.sector_momentum_period) + eps)
            )
            .over(MarketDataSchema.SYMBOL)
            .alias("ret_20d")
        )

        # -------------------------------------------------------------
        # 2. Sector Return for Sector-Relative Momentum
        # -------------------------------------------------------------
        # Average ret_20d across all symbols in the same sector at date t
        p = p.with_columns(
            pl.col("ret_20d")
            .mean()
            .over([MarketDataSchema.DATE, MarketDataSchema.SECTOR])
            .alias("sector_ret_20d")
        )

        # -------------------------------------------------------------
        # 3. PCR Fast (10d) and Slow (50d)
        # PCR = sum(put_vol) / (sum(call_vol) + eps)
        # -------------------------------------------------------------
        p = p.with_columns(
            (
                pl.col(MarketDataSchema.PUT_VOLUME)
                .rolling_sum(window_size=cfg.pcr_fast_period, min_samples=cfg.pcr_fast_period)
                .over(MarketDataSchema.SYMBOL)
                / (
                    pl.col(MarketDataSchema.CALL_VOLUME)
                    .rolling_sum(window_size=cfg.pcr_fast_period, min_samples=cfg.pcr_fast_period)
                    .over(MarketDataSchema.SYMBOL) + eps
                )
            ).alias("pcr_10d"),
            (
                pl.col(MarketDataSchema.PUT_VOLUME)
                .rolling_sum(window_size=cfg.pcr_slow_period, min_samples=cfg.pcr_slow_period)
                .over(MarketDataSchema.SYMBOL)
                / (
                    pl.col(MarketDataSchema.CALL_VOLUME)
                    .rolling_sum(window_size=cfg.pcr_slow_period, min_samples=cfg.pcr_slow_period)
                    .over(MarketDataSchema.SYMBOL) + eps
                )
            ).alias("pcr_50d"),
        )

        # -------------------------------------------------------------
        # 4. Construct 7 Raw Feature Formulations
        # -------------------------------------------------------------
        # F1: Short Squeeze Pressure = (Short Interest / ADV_20) * ((P_t - SMA_50) / ATR_14)
        # F2: Net GEX = ATM Call GEX - ATM Put GEX
        # F3: PCR Momentum = PCR_10d / (PCR_50d + eps)
        # F4: Sector-Relative Momentum = ret_20d - sector_ret_20d
        # F5: VWAP Divergence = (P_t - VWAP_20) / ATR_14
        # F6: VIX Term Structure Slope = VIX_spot / (VIX_3M + eps)
        # F7: SUE Score = raw SUE
        p = p.with_columns(
            (
                (pl.col(MarketDataSchema.SHORT_INTEREST) / (pl.col("adv_20") + eps))
                * ((pl.col(MarketDataSchema.CLOSE) - pl.col("sma_50")) / (pl.col("atr_14") + eps))
            ).alias("feat_raw_short_squeeze_pressure"),
            (
                pl.col(MarketDataSchema.ATM_CALL_GEX) - pl.col(MarketDataSchema.ATM_PUT_GEX)
            ).alias("feat_raw_net_gex"),
            (
                pl.col("pcr_10d") / (pl.col("pcr_50d") + eps)
            ).alias("feat_raw_pcr_momentum"),
            (
                pl.col("ret_20d") - pl.col("sector_ret_20d")
            ).alias("feat_raw_sector_relative_momentum"),
            (
                (pl.col(MarketDataSchema.CLOSE) - pl.col("vwap_20")) / (pl.col("atr_14") + eps)
            ).alias("feat_raw_vwap_divergence"),
            (
                pl.col(MarketDataSchema.VIX_SPOT) / (pl.col(MarketDataSchema.VIX_3M) + eps)
            ).alias("feat_raw_vix_slope"),
            (
                pl.col(MarketDataSchema.SUE_SCORE)
            ).alias("feat_raw_sue_score"),
        )

        # -------------------------------------------------------------
        # 5. Cross-Sectional Uniform Quantile / Rank Normalization
        # Maps all features to uniform [-1.0, 1.0] across universe at date t
        # -------------------------------------------------------------
        rank_exprs = [
            compute_cross_sectional_rank("feat_raw_short_squeeze_pressure", output_col="feat_short_squeeze_pressure"),
            compute_cross_sectional_rank("feat_raw_net_gex", output_col="feat_net_gex"),
            compute_cross_sectional_rank("feat_raw_pcr_momentum", output_col="feat_pcr_momentum"),
            compute_cross_sectional_rank("feat_raw_sector_relative_momentum", output_col="feat_sector_relative_momentum"),
            compute_cross_sectional_rank("feat_raw_vwap_divergence", output_col="feat_vwap_divergence"),
            compute_cross_sectional_rank("feat_raw_vix_slope", output_col="feat_vix_slope"),
            compute_cross_sectional_rank("feat_raw_sue_score", output_col="feat_sue_score"),
        ]

        p = p.with_columns(rank_exprs)

        # Drop temporary intermediate columns
        drop_cols = [c for c in p.columns if c.startswith("_")]
        p = p.drop(drop_cols)

        return p.sort([MarketDataSchema.DATE, MarketDataSchema.SYMBOL]), self.FEATURE_NAMES
