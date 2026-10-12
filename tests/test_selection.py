"""Deterministic data-quality selection, never strategy outcome selection."""
import importlib.util
from pathlib import Path

import pandas as pd


spec = importlib.util.spec_from_file_location('selection', Path(__file__).parents[1] / 'tools/select_comparison_window.py')
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)


def months(flags):
    starts = pd.date_range('2020-01-01', periods=len(flags), freq='MS', tz='UTC')
    return [{'start': t.isoformat(), 'end': (t + pd.offsets.MonthBegin()).isoformat(), 'valid': flag}
            for t, flag in zip(starts, flags)]


def test_earliest_twelve_months_not_later_or_longer_block():
    rows = months([False] + [True] * 13 + [False] + [True] * 20)
    chosen = selection.choose_window(rows)
    assert chosen == {'start': '2020-02-01T00:00:00+00:00', 'end': '2021-02-01T00:00:00+00:00', 'months': 12}


def test_fallback_longest_and_earliest_tie():
    rows = months([True, True, False, True, True, True, False, True, True, True])
    chosen = selection.choose_window(rows)
    assert chosen == {'start': '2020-04-01T00:00:00+00:00', 'end': '2020-07-01T00:00:00+00:00', 'months': 3}


def test_missing_month_breaks_continuity_even_if_valid_flags():
    rows = months([True, True, True, True])
    del rows[1]
    chosen = selection.choose_window(rows)
    assert chosen['start'] == '2020-03-01T00:00:00+00:00' and chosen['months'] == 2


def test_no_valid_month_or_single_month_does_not_invent_long_period():
    assert selection.choose_window(months([False, False])) is None
    assert selection.choose_window(months([False, True, False]))['months'] == 1
