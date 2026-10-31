"""
Backtesting and performance reporting module.
"""

from stockmodel.backtest.engine import BacktestEngine, BacktestResult
from stockmodel.backtest.reporting import generate_tearsheet, BacktestMetrics

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "generate_tearsheet",
    "BacktestMetrics",
]
