"""
StockModel: Quantitative Swing Behavior Model (2-4 Week Horizon).
Cross-Sectional Gradient-Boosted Trees with ElasticNet Baseline.
"""

__version__ = "0.1.0"

from stockmodel.config import (
    SystemConfig,
    TargetConfig,
    FeatureConfig,
    ValidationConfig,
    ModelConfig,
    GatingConfig,
    ExecutionConfig,
)

__all__ = [
    "SystemConfig",
    "TargetConfig",
    "FeatureConfig",
    "ValidationConfig",
    "ModelConfig",
    "GatingConfig",
    "ExecutionConfig",
]
