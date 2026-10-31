"""
Data module for StockModel.
"""

from stockmodel.data.schema import MarketDataSchema, validate_market_data
from stockmodel.data.loader import MarketDataLoader
from stockmodel.data.synthetic import SyntheticMarketGenerator

__all__ = [
    "MarketDataSchema",
    "validate_market_data",
    "MarketDataLoader",
    "SyntheticMarketGenerator",
]
