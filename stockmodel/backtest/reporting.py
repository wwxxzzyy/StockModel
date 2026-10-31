"""
Performance Tear-Sheet and Metric Reporting Engine.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd


@dataclass
class BacktestMetrics:
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    win_rate: float
    profit_factor: float
    total_turnover: float
    annualized_turnover: float
    friction_drag_bps: float
    benchmark_return: float
    alpha_over_benchmark: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "Total Return (%)": self.total_return * 100.0,
            "Annualized Return (%)": self.annualized_return * 100.0,
            "Annualized Volatility (%)": self.annualized_volatility * 100.0,
            "Sharpe Ratio": self.sharpe_ratio,
            "Sortino Ratio": self.sortino_ratio,
            "Max Drawdown (%)": self.max_drawdown * 100.0,
            "Calmar Ratio": self.calmar_ratio,
            "Win Rate (%)": self.win_rate * 100.0,
            "Profit Factor": self.profit_factor,
            "Annualized Turnover (x)": self.annualized_turnover,
            "Total Friction Drag (bps)": self.friction_drag_bps,
            "Benchmark Return (%)": self.benchmark_return * 100.0,
            "Alpha over Benchmark (%)": self.alpha_over_benchmark * 100.0,
        }


def compute_metrics(
    daily_df: pd.DataFrame,
    return_col: str = "net_return",
    benchmark_col: str = "benchmark_return",
    turnover_col: str = "turnover",
    friction_col: str = "friction_drag",
    annualization_factor: float = 252.0,
) -> BacktestMetrics:
    """
    Computes rigorous performance statistics from daily backtest returns.
    """
    rets = daily_df[return_col].to_numpy()
    n_days = len(rets)
    if n_days < 2:
        return BacktestMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    # Compounded total return
    cum_ret = float(np.prod(1.0 + rets) - 1.0)
    years = max(1e-4, n_days / annualization_factor)
    ann_ret = float((1.0 + cum_ret) ** (1.0 / years) - 1.0)

    # Volatility
    ann_vol = float(np.std(rets, ddof=1) * np.sqrt(annualization_factor))

    # Sharpe ratio (0 risk free rate assumed for excess return)
    sharpe = float(ann_ret / ann_vol) if ann_vol > 1e-8 else 0.0

    # Sortino ratio (downside deviation)
    downside_rets = rets[rets < 0]
    downside_std = float(np.std(downside_rets, ddof=1) * np.sqrt(annualization_factor)) if len(downside_rets) > 1 else ann_vol
    sortino = float(ann_ret / downside_std) if downside_std > 1e-8 else 0.0

    # Drawdown
    cum_series = np.cumprod(1.0 + rets)
    running_max = np.maximum.accumulate(cum_series)
    drawdowns = (cum_series - running_max) / running_max
    max_dd = float(abs(np.min(drawdowns)))
    calmar = float(ann_ret / max_dd) if max_dd > 1e-6 else 0.0

    # Win rate & profit factor
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    win_rate = float(len(wins) / len(rets)) if len(rets) > 0 else 0.0
    gross_gains = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_losses = float(abs(np.sum(losses))) if len(losses) > 0 else 1e-8
    profit_factor = float(gross_gains / gross_losses)

    # Turnover & Friction
    total_to = float(daily_df[turnover_col].sum()) if turnover_col in daily_df else 0.0
    ann_to = float(total_to / years)
    total_fric = float(daily_df[friction_col].sum()) if friction_col in daily_df else 0.0
    fric_bps = float(total_fric * 10000.0)

    # Benchmark comparison
    bench_cum = float(np.prod(1.0 + daily_df[benchmark_col].to_numpy()) - 1.0) if benchmark_col in daily_df else 0.0

    return BacktestMetrics(
        total_return=cum_ret,
        annualized_return=ann_ret,
        annualized_volatility=ann_vol,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=max_dd,
        calmar_ratio=calmar,
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_turnover=total_to,
        annualized_turnover=ann_to,
        friction_drag_bps=fric_bps,
        benchmark_return=bench_cum,
        alpha_over_benchmark=cum_ret - bench_cum,
    )


def generate_tearsheet(
    metrics: BacktestMetrics,
    title: str = "StockModel Quantitative Swing Strategy Tear-Sheet",
    oos_ic: Optional[float] = None,
    oos_icir: Optional[float] = None,
) -> str:
    """
    Formats the performance metrics into a clean markdown table.
    """
    m = metrics.to_dict()
    lines = [
        f"## {title}",
        "",
        "| Metric | Strategy Value | Benchmark / Hurdle |",
        "| :--- | :--- | :--- |",
    ]

    for k, v in m.items():
        if "Ratio" in k or "Factor" in k or "(x)" in k:
            val_str = f"{v:.2f}"
        else:
            val_str = f"{v:.2f}%" if "%" in k else f"{v:.1f}"
        lines.append(f"| **{k}** | `{val_str}` | - |")

    if oos_ic is not None:
        lines.append(f"| **Out-of-Sample IC** | `{oos_ic:.4f}` | `Hurdle: >= 0.035` |")
    if oos_icir is not None:
        lines.append(f"| **Out-of-Sample ICIR** | `{oos_icir:.2f}` | `Hurdle: >= 0.75` |")

    return "\n".join(lines)
