"""
Market data loader supporting Parquet and CSV formats with validation.
"""

from pathlib import Path
from typing import Union
import polars as pl
from stockmodel.data.schema import validate_market_data


class MarketDataLoader:
    """Loads and validates point-in-time cross-sectional market data."""

    @staticmethod
    def load_file(path: Union[str, Path]) -> pl.DataFrame:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Data file not found at: {path}")

        if path.suffix == ".parquet":
            df = pl.read_parquet(path)
        elif path.suffix in (".csv", ".txt"):
            df = pl.read_csv(path)
        else:
            raise ValueError(f"Unsupported file format '{path.suffix}'. Use .parquet or .csv")

        return validate_market_data(df)

    @staticmethod
    def save_parquet(df: pl.DataFrame, path: Union[str, Path]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
