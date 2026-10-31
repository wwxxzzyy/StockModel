"""
Turnover & Rebalancing Inertia Engine.

Rules:
1. Reranking occurs weekly (every 5 trading days).
2. Inertia Band: An existing holding is not liquidated on rebalance unless its cross-sectional
   predicted score falls below the 60th percentile, suppressing portfolio turnover and friction.
"""

from typing import Dict, List, Set, Tuple
import pandas as pd
from stockmodel.execution.portfolio import select_decile_baskets, compute_inverse_atr_weights
from stockmodel.execution.blackouts import apply_earnings_blackouts


class RebalanceManager:
    """
    Manages periodic portfolio rebalancing with inertia bands and earnings blackout integration.
    """

    def __init__(
        self,
        rebalance_interval: int = 5,
        inertia_exit_percentile: float = 0.60,
        top_decile_quantile: float = 0.10,
        bottom_decile_quantile: float = 0.10,
        entry_blackout_days: int = 3,
        trim_days_prior: int = 2,
        trim_ratio: float = 0.50,
    ):
        self.rebalance_interval = rebalance_interval
        self.inertia_exit_percentile = inertia_exit_percentile
        self.top_decile_quantile = top_decile_quantile
        self.bottom_decile_quantile = bottom_decile_quantile
        self.entry_blackout_days = entry_blackout_days
        self.trim_days_prior = trim_days_prior
        self.trim_ratio = trim_ratio

    def should_rebalance(self, step_idx: int) -> bool:
        """Returns True every rebalance_interval days."""
        return (step_idx % self.rebalance_interval) == 0

    def rebalance_portfolio(
        self,
        current_holdings: Dict[str, float],
        scores_df: pd.DataFrame,
        atr_series: pd.Series,
        days_to_earnings_map: Dict[str, int],
        allow_short: bool = True,
    ) -> Dict[str, float]:
        """
        Calculates new target portfolio weights applying inertia and earnings blackout rules.

        Args:
            current_holdings: Dict mapping symbol -> current weight (+ for long, - for short).
            scores_df: DataFrame with 'symbol' and 'pred'.
            atr_series: Series mapping symbol -> ATR_14.
            days_to_earnings_map: Dict mapping symbol -> DTE.
            allow_short: Whether to execute short positions or remain flat/cash on bottom decile.

        Returns:
            Dict mapping symbol -> target weight.
        """
        if len(scores_df) == 0:
            return {}

        # 1. First, apply earnings trim to current holdings
        trimmed_holdings, _ = apply_earnings_blackouts(
            current_holdings=current_holdings,
            candidate_symbols=set(),
            days_to_earnings_map=days_to_earnings_map,
            entry_blackout_days=self.entry_blackout_days,
            trim_days_prior=self.trim_days_prior,
            trim_ratio=self.trim_ratio,
        )

        # 2. Compute cross-sectional percentiles for all symbols (0.0 = lowest, 1.0 = highest)
        df = scores_df.sort_values(by="pred", ascending=True).reset_index(drop=True)
        n = len(df)
        df["percentile"] = df.index / max(1, n - 1)
        pct_map = dict(zip(df["symbol"], df["percentile"]))

        # Identify candidate baskets
        long_candidates, short_candidates = select_decile_baskets(
            scores_df=scores_df,
            score_col="pred",
            symbol_col="symbol",
            top_quantile=self.top_decile_quantile,
            bottom_quantile=self.bottom_decile_quantile,
        )

        # Filter new entries by earnings blackout (must have DTE > entry_blackout_days)
        _, approved_long_candidates = apply_earnings_blackouts(
            current_holdings={},
            candidate_symbols=set(long_candidates),
            days_to_earnings_map=days_to_earnings_map,
            entry_blackout_days=self.entry_blackout_days,
        )
        _, approved_short_candidates = apply_earnings_blackouts(
            current_holdings={},
            candidate_symbols=set(short_candidates),
            days_to_earnings_map=days_to_earnings_map,
            entry_blackout_days=self.entry_blackout_days,
        )

        # 3. Determine active long basket with Inertia Band:
        # Existing long positions stay UNLESS their percentile drops below inertia_exit_percentile (0.60)
        # OR earnings trim/close forces liquidation
        retained_longs: Set[str] = set()
        for sym, w in trimmed_holdings.items():
            if w > 0:
                p = pct_map.get(sym, 0.0)
                dte = days_to_earnings_map.get(sym, 999)
                if p >= self.inertia_exit_percentile and dte > self.trim_days_prior:
                    retained_longs.add(sym)

        final_longs = list(retained_longs.union(approved_long_candidates))

        # 4. Determine active short basket with Inertia Band (if shorting allowed):
        # Existing short positions stay UNLESS their percentile rises above (1.0 - inertia_exit_percentile = 0.40)
        retained_shorts: Set[str] = set()
        if allow_short:
            for sym, w in trimmed_holdings.items():
                if w < 0:
                    p = pct_map.get(sym, 1.0)
                    dte = days_to_earnings_map.get(sym, 999)
                    if p <= (1.0 - self.inertia_exit_percentile) and dte > self.trim_days_prior:
                        retained_shorts.add(sym)

            final_shorts = list(retained_shorts.union(approved_short_candidates))
        else:
            final_shorts = []

        # 5. Volatility Parity Weighting (Inverse ATR-14)
        long_weights = compute_inverse_atr_weights(final_longs, atr_series)
        short_weights = compute_inverse_atr_weights(final_shorts, atr_series)

        # Combine into target portfolio
        # Longs sum to +0.50 (or +1.0 if long-only), shorts sum to -0.50 (dollar-neutral long/short)
        target_weights: Dict[str, float] = {}
        if allow_short and final_shorts:
            for s, w in long_weights.items():
                target_weights[s] = w * 0.50
            for s, w in short_weights.items():
                target_weights[s] = -w * 0.50
        else:
            for s, w in long_weights.items():
                target_weights[s] = w * 1.0

        return target_weights
