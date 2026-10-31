"""
Purged and Embargoed Walk-Forward Cross-Validation.
Prevents serial correlation and label leakage across overlapping multi-week returns.
"""

from typing import Iterator, Tuple, List
import numpy as np


class PurgedWalkForwardValidator:
    """
    Purged and Embargoed Walk-Forward Cross-Validation.
    Prevents serial correlation and label leakage across overlapping multi-week returns.

    Attributes:
        n_splits: Maximum number of walk-forward evaluation folds.
        train_period: Lookback window length in trading days for training.
        test_period: Out-of-sample evaluation window length in trading days.
        embargo: Number of buffer days between train_end and test_start (horizon_days + buffer).
    """

    def __init__(
        self,
        n_splits: int = 5,
        train_period_days: int = 504,
        test_period_days: int = 63,
        horizon_days: int = 15,
        embargo_buffer_days: int = 5,
    ):
        self.n_splits = n_splits
        self.train_period = train_period_days
        self.test_period = test_period_days
        self.embargo = horizon_days + embargo_buffer_days

    def split(
        self,
        unique_dates: np.ndarray,
        chronological: bool = True,
    ) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        """
        Generates purged and embargoed train and test date slices.

        Args:
            unique_dates: 1D array of sorted unique trading dates.
            chronological: If True, yields folds from past to future (earliest to latest).

        Yields:
            Tuple of (train_dates, test_dates) arrays.
        """
        unique_dates = np.asarray(unique_dates)
        total_dates = len(unique_dates)
        folds: List[Tuple[np.ndarray, np.ndarray]] = []

        train_period = self.train_period
        test_period = self.test_period
        embargo = self.embargo

        # Adaptively scale if available dates are fewer than required full lookback
        if total_dates < train_period + embargo + test_period:
            test_period = max(10, int(total_dates * 0.15))
            embargo = min(embargo, max(5, int(total_dates * 0.05)))
            train_period = max(20, total_dates - test_period - embargo)

        for i in range(self.n_splits):
            test_end_idx = total_dates - i * test_period
            test_start_idx = test_end_idx - test_period
            train_end_idx = test_start_idx - embargo
            train_start_idx = train_end_idx - train_period

            if train_start_idx < 0:
                break

            train_dates = unique_dates[train_start_idx:train_end_idx]
            test_dates = unique_dates[test_start_idx:test_end_idx]
            folds.append((train_dates, test_dates))

        if chronological:
            folds.reverse()

        for train_d, test_d in folds:
            yield train_d, test_d
