import numpy as np
import pandas as pd
import pytest

from qfs.strategies import decision, indicators


@pytest.mark.parametrize("previous,current,expected", [
    ((1, 1), (2, 1), 1), ((1, 1), (1, 2), -1),
    ((2, 1), (1, 1), None), ((1, 2), (1, 1), None),
    ((2, 1), (3, 1), None), ((2, 1), (1, 2), -1),
    ((1, 2), (2, 1), 1), ((np.nan, 1), (2, 1), None),
])
def test_ema_equality_crossings(previous, current, expected):
    row = lambda v: pd.Series({"close": 10, "fast": v[0], "slow": v[1]})
    assert decision("ema", row(previous), row(current), 0) == expected


def test_ema_recursive_values_and_future_invariance():
    cfg = {"name": "ema", "params": {"fast": 2, "slow": 3}}
    close = pd.Series([10.0, 16.0, 4.0, 1000.0])
    full = indicators(close, cfg)
    assert full.fast.iloc[:3].tolist() == pytest.approx([10, 14, 22 / 3])
    assert full.slow.iloc[:3].tolist() == [10, 13, 8.5]
    pd.testing.assert_frame_equal(full.iloc[:3], indicators(close.iloc[:3], cfg))


def band(close, middle=10, lower=8, upper=12):
    return pd.Series(dict(close=close, middle=middle, lower=lower, upper=upper))


@pytest.mark.parametrize("previous,current,position,expected", [
    (band(8), band(7), 0, 1), (band(12), band(13), 0, -1),
    (band(9), band(8), 0, None), (band(11), band(12), 0, None),
    (band(7), band(6), 0, None), (band(13), band(14), 0, None),
    (band(7), band(13), 0, None), (band(9), band(10), 1, 0),
    (band(11), band(10), -1, 0), (band(10), band(10), 1, None),
    (band(10), band(10), -1, None), (band(11), band(13), 1, None),
    (band(9), band(7), -1, None), (band(9), band(13), 1, 0),
    (band(11), band(7), -1, 0), (band(9), band(7, lower=np.nan), 0, None),
])
def test_bollinger_crossing_boundaries(previous, current, position, expected):
    assert decision("bollinger", previous, current, position) == expected


def test_bollinger_population_std_and_no_lookahead():
    cfg = {"name": "bollinger", "params": {"window": 3, "std_multiplier": 2}}
    values = pd.Series([8., 10., 12., 1000.])
    result = indicators(values, cfg)
    assert result.middle.iloc[2] == 10
    assert result.upper.iloc[2] == pytest.approx(10 + 2 * np.sqrt(8 / 3))
    assert result.iloc[:2].middle.isna().all()
    pd.testing.assert_frame_equal(result.iloc[:3], indicators(values.iloc[:3], cfg))
