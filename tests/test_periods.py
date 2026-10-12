import pandas as pd
import pytest

from qfs.periods import period_rows


def test_partial_months_continuous_boundaries_terminal_fees_and_local_drawdown():
    curve = pd.DataFrame({"time": ["2020-01-31T23:58Z", "2020-01-31T23:59Z", "2020-02-01T00:00Z",
                                   "2020-02-01T00:01Z", "2020-02-01T00:02Z", "2020-02-01T00:02Z"],
                          "equity": [100, 110, 120, 108, 126, 124]})
    rows = period_rows(curve, pd.Timestamp(curve.time.iloc[0]), pd.Timestamp(curve.time.iloc[-1]))
    jan, feb, year = rows
    assert jan["frequency"] == feb["frequency"] == "month"
    assert year["frequency"] == "year"
    assert jan["period"] == "2020-01" and feb["period"] == "2020-02"
    assert not jan["complete"] and not feb["complete"] and not year["complete"]
    assert jan["end_equity"] == feb["start_equity"] == 120
    assert feb["end_equity"] == 124
    assert jan["return"] == pytest.approx(.2)
    assert feb["return"] == pytest.approx(124 / 120 - 1)
    assert jan["maximum_drawdown"] == 0
    assert feb["maximum_drawdown"] == pytest.approx(.1)
    assert jan["effective_minutes"] == feb["effective_minutes"] == 2
    assert jan["calendar_days"] == pytest.approx(2 / 1440)
    assert (1 + jan["return"]) * (1 + feb["return"]) == pytest.approx(1 + year["return"])
    assert year["equity_change"] == 24
    assert not {"funding_net", "trade_count", "fees", "annualized_return"} & jan.keys()


def test_complete_month_and_partial_year():
    start, end = pd.Timestamp("2020-02-01T00:00Z"), pd.Timestamp("2020-03-01T00:00Z")
    curve = pd.DataFrame({"time": [start.isoformat(), end.isoformat()], "equity": [100, 110]})
    month, year = period_rows(curve, start, end)
    assert month["complete"] is True and year["complete"] is False
    assert month["calendar_days"] == 29
    assert month["effective_minutes"] == 41760


def test_year_boundary_shared_without_reset():
    start, boundary, end = map(pd.Timestamp, ["2020-12-31T23:59Z", "2021-01-01T00:00Z", "2021-01-01T00:01Z"])
    curve = pd.DataFrame({"time": [t.isoformat() for t in [start, boundary, end]], "equity": [100, 90, 99]})
    rows = period_rows(curve, start, end)
    years = [r for r in rows if r["frequency"] == "year"]
    assert [r["period"] for r in years] == ["2020", "2021"]
    assert years[0]["end_equity"] == years[1]["start_equity"] == 90
    assert years[0]["maximum_drawdown"] == pytest.approx(.1)
    assert years[1]["maximum_drawdown"] == 0  # period-local peak, not a carried all-time peak


def test_complete_leap_year_and_all_twelve_months():
    times = pd.date_range("2020-01-01", "2021-01-01", freq="MS", tz="UTC")
    curve = pd.DataFrame({"time": [t.isoformat() for t in times], "equity": 100.0})
    rows = period_rows(curve, times[0], times[-1])
    assert len(rows) == 13 and all(r["complete"] for r in rows)
    assert rows[-1]["frequency"] == "year" and rows[-1]["calendar_days"] == 366
    assert sum(r["calendar_days"] for r in rows[:-1]) == 366
    assert all(r["return"] == r["maximum_drawdown"] == 0 for r in rows)


def test_missing_exact_boundary_is_an_error():
    curve = pd.DataFrame({"time": ["2020-01-31T23:59Z", "2020-02-01T00:01Z"], "equity": [100, 100]})
    with pytest.raises(ValueError, match="boundary.*2020-02-01"):
        period_rows(curve, pd.Timestamp(curve.time.iloc[0]), pd.Timestamp(curve.time.iloc[-1]))
