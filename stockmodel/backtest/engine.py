"""
Walk-Forward Portfolio Simulation and Backtest Engine.

Simulates execution under realistic friction, weekly rebalancing, inertia bands,
earnings blackouts, and volatility parity inverse-ATR weighting.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from stockmodel.data.schema import MarketDataSchema
from stockmodel.config import SystemConfig
from stockmodel.execution.rebalance import RebalanceManager
from stockmodel.execution.friction import compute_execution_friction


@dataclass
class BacktestResult:
    daily_records: pd.DataFrame
    final_nav: float
    total_turnover: float
    total_friction_cost: float
    weights_history: Dict[str, Dict[str, float]]


class BacktestEngine:
    """
    Simulates production execution and risk management over time.
    """

    def __init__(self, config: Optional[SystemConfig] = None):
        self.config = config if config is not None else SystemConfig()
        exec_cfg = self.config.execution
        self.rebalance_mgr = RebalanceManager(
            rebalance_interval=exec_cfg.rebalance_frequency_days,
            inertia_exit_percentile=exec_cfg.inertia_exit_percentile,
            top_decile_quantile=exec_cfg.long_top_quantile,
            bottom_decile_quantile=exec_cfg.short_bottom_quantile,
            entry_blackout_days=exec_cfg.earnings_entry_blackout_days,
            trim_days_prior=int(exec_cfg.earnings_trim_hours_prior / 24),
            trim_ratio=exec_cfg.earnings_trim_ratio,
        )

    def run(
        self,
        panel_df: pd.DataFrame,
        pred_col: str = "pred",
        date_col: str = MarketDataSchema.DATE,
        symbol_col: str = MarketDataSchema.SYMBOL,
        close_col: str = MarketDataSchema.CLOSE,
        atr_col: str = "atr_14",
        dte_col: str = MarketDataSchema.DAYS_TO_EARNINGS,
        mcap_col: str = MarketDataSchema.MARKET_CAP,
        initial_capital: float = 1_000_000.0,
    ) -> BacktestResult:
        """
        Executes historical backtest using model prediction scores.
        """
        exec_cfg = self.config.execution
        df = panel_df.sort_values(by=[date_col, symbol_col]).copy()
        unique_dates = df[date_col].drop_duplicates().tolist()

        if len(unique_dates) < 2:
            raise ValueError("Backtest requires at least 2 distinct trading dates.")

        current_weights: Dict[str, float] = {}
        nav = initial_capital
        total_turnover = 0.0
        total_friction = 0.0

        daily_records: List[Dict] = []
        weights_history: Dict[str, Dict[str, float]] = {}

        # Pre-group data by date for speed
        date_groups = {dt: grp for dt, grp in df.groupby(date_col)}

        prev_closes: Dict[str, float] = {}

        for step_idx, dt in enumerate(unique_dates):
            current_day_df = date_groups[dt]
            date_str = str(dt)

            current_closes = dict(zip(current_day_df[symbol_col], current_day_df[close_col]))
            atr_map = dict(zip(current_day_df[symbol_col], current_day_df.get(atr_col, pd.Series([1.0]*len(current_day_df)))))
            dte_map = dict(zip(current_day_df[symbol_col], current_day_df.get(dte_col, pd.Series([999]*len(current_day_df)))))
            mcap_map = dict(zip(current_day_df[symbol_col], current_day_df.get(mcap_col, pd.Series([5e10]*len(current_day_df)))))

            # 1. Compute asset returns from previous day
            asset_returns = {}
            if prev_closes:
                for sym, curr_p in current_closes.items():
                    if sym in prev_closes and prev_closes[sym] > 0:
                        asset_returns[sym] = (curr_p - prev_closes[sym]) / prev_closes[sym]

            # 2. Portfolio gross return from yesterday's held weights
            gross_return = 0.0
            benchmark_return = 0.0
            if asset_returns:
                # Benchmark = equal weight of universe
                benchmark_return = float(np.mean(list(asset_returns.values())))

                # Strategy gross return
                for sym, w in current_weights.items():
                    if sym in asset_returns:
                        gross_return += w * asset_returns[sym]

            # 3. Check for rebalancing today
            step_friction = 0.0
            turnover_today = 0.0
            if self.rebalance_mgr.should_rebalance(step_idx) and pred_col in current_day_df.columns:
                valid_preds = current_day_df.dropna(subset=[pred_col, symbol_col])
                if len(valid_preds) > 0:
                    target_weights = self.rebalance_mgr.rebalance_portfolio(
                        current_holdings=current_weights,
                        scores_df=valid_preds[[symbol_col, pred_col]],
                        atr_series=pd.Series(atr_map),
                        days_to_earnings_map=dte_map,
                        allow_short=exec_cfg.allow_short,
                    )

                    # Compute turnover: |w_target - w_current|
                    all_symbols = set(current_weights.keys()).union(target_weights.keys())
                    turnover_map = {}
                    for sym in all_symbols:
                        delta = abs(target_weights.get(sym, 0.0) - current_weights.get(sym, 0.0))
                        turnover_map[sym] = delta
                        turnover_today += delta

                    # Active shorts for borrow cost
                    active_shorts = {s: w for s, w in target_weights.items() if w < 0}

                    # Compute friction
                    step_friction = compute_execution_friction(
                        traded_weights=turnover_map,
                        market_cap_map=mcap_map,
                        active_short_weights=active_shorts,
                        large_cap_threshold=exec_cfg.market_cap_mid_threshold,
                        large_cap_slippage_bps=exec_cfg.large_cap_slippage_bps,
                        mid_cap_slippage_bps=exec_cfg.mid_cap_slippage_bps,
                        annual_short_borrow_bps=exec_cfg.annual_short_borrow_bps,
                    )

                    current_weights = target_weights
                    total_turnover += turnover_today
                    total_friction += step_friction
            else:
                # Deduct ongoing short borrow costs even on non-rebalance days
                active_shorts = {s: w for s, w in current_weights.items() if w < 0}
                if active_shorts:
                    step_friction = compute_execution_friction(
                        traded_weights={},
                        market_cap_map=mcap_map,
                        active_short_weights=active_shorts,
                        annual_short_borrow_bps=exec_cfg.annual_short_borrow_bps,
                    )
                    total_friction += step_friction

            # 4. Net portfolio return
            net_return = gross_return - step_friction
            nav *= (1.0 + net_return)

            # Record metrics
            weights_history[date_str] = current_weights.copy()
            long_weight = sum(w for w in current_weights.values() if w > 0)
            short_weight = sum(w for w in current_weights.values() if w < 0)

            daily_records.append({
                date_col: dt,
                "nav": nav,
                "gross_return": gross_return,
                "friction_drag": step_friction,
                "net_return": net_return,
                "benchmark_return": benchmark_return,
                "turnover": turnover_today,
                "long_exposure": long_weight,
                "short_exposure": short_weight,
                "net_exposure": long_weight + short_weight,
                "gross_exposure": long_weight + abs(short_weight),
                "active_positions_count": len([w for w in current_weights.values() if abs(w) > 1e-5]),
            })

            prev_closes = current_closes

        result_df = pd.DataFrame(daily_records)
        return BacktestResult(
            daily_records=result_df,
            final_nav=nav,
            total_turnover=total_turnover,
            total_friction_cost=total_friction,
            weights_history=weights_history,
        )
