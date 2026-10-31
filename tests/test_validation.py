"""
Unit tests for Purged & Embargoed Walk-Forward Validation and IC/ICIR metrics.
"""

import numpy as np
import pytest
from stockmodel.validation.purged_walk_forward import PurgedWalkForwardValidator
from stockmodel.validation.metrics import (
    evaluate_ic,
    evaluate_icir,
    check_acceptance_gate,
)


def test_purged_walk_forward_splitter():
    total_days = 600
    dates = np.array([f"day_{i:04d}" for i in range(total_days)])

    horizon = 15
    embargo_buffer = 5
    expected_embargo = horizon + embargo_buffer  # 20 days
    train_period = 200
    test_period = 50

    validator = PurgedWalkForwardValidator(
        n_splits=3,
        train_period_days=train_period,
        test_period_days=test_period,
        horizon_days=horizon,
        embargo_buffer_days=embargo_buffer,
    )

    folds = list(validator.split(dates, chronological=True))
    assert len(folds) == 3

    for train_d, test_d in folds:
        assert len(train_d) == train_period
        assert len(test_d) == test_period

        # Check embargo gap
        last_train_idx = int(train_d[-1].split("_")[1])
        first_test_idx = int(test_d[0].split("_")[1])
        gap = first_test_idx - last_train_idx
        # gap must be >= embargo (20 days)
        assert gap >= expected_embargo

        # Absolutely no overlap
        assert len(set(train_d).intersection(set(test_d))) == 0


def test_spearman_ic_and_icir():
    # Perfect positive rank correlation
    preds = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    targets = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    assert np.isclose(evaluate_ic(preds, targets), 1.0)

    # Perfect inverse rank correlation
    inv_targets = np.array([50.0, 40.0, 30.0, 20.0, 10.0])
    assert np.isclose(evaluate_ic(preds, inv_targets), -1.0)

    # ICIR formula
    ic_series = [0.05, 0.04, 0.06, 0.05, 0.05]
    icir = evaluate_icir(ic_series)
    assert icir > 0.0


def test_acceptance_gate():
    # Meets all criteria
    pass_res = check_acceptance_gate(mean_ic=0.040, icir=0.80, baseline_ic=0.020, min_ic=0.035, min_icir=0.75)
    assert pass_res["passed"] is True

    # Fails IC hurdle
    fail_ic = check_acceptance_gate(mean_ic=0.025, icir=0.80, baseline_ic=0.020, min_ic=0.035, min_icir=0.75)
    assert fail_ic["passed"] is False

    # Fails Baseline gate (LightGBM <= ElasticNet)
    fail_base = check_acceptance_gate(mean_ic=0.040, icir=0.80, baseline_ic=0.045, min_ic=0.035, min_icir=0.75)
    assert fail_base["passed"] is False
