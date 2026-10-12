import pandas as pd
import pytest

from conftest import save, engine_data
from qfs.data import load_data
from qfs.engine import Account, run_backtest
from qfs.report import metric_summary


@pytest.mark.parametrize("direction", [1, -1])
def test_adverse_slippage_bilateral_fees_not_double_deducted(direction):
    account = Account(10000, 0.001, 0.01)
    start = pd.Timestamp("2020-01-01T00:00:00Z")
    account.open(start, 100, direction, 0.5, 100)
    # 5000 entry notional => fee 5, regardless of direction.
    assert account.wallet == 9995
    expected_entry = 101 if direction == 1 else 99
    assert account.position["entry_fill"] == expected_entry
    q = 5000 / expected_entry
    trade = account.close(start + pd.Timedelta(hours=1), 110, "strategy_exit")
    expected_exit = 108.9 if direction == 1 else 111.1
    gross = direction * q * (expected_exit - expected_entry)
    exit_fee = q * expected_exit * 0.001
    assert trade["exit_fill"] == pytest.approx(expected_exit)
    assert trade["gross_pnl"] == pytest.approx(gross)
    assert trade["net_pnl"] == pytest.approx(gross - 5 - exit_fee)
    assert trade["slippage"] == pytest.approx(q * 2.1)
    assert account.wallet == pytest.approx(10000 + gross - 5 - exit_fee)


@pytest.mark.parametrize("direction,rate,expected", [(1, .01, -60), (-1, .01, 60), (1, -.01, 60), (-1, -.01, -60)])
def test_funding_sign_direction_and_net_trade(direction, rate, expected):
    account = Account(10000, 0, 0)
    time = pd.Timestamp("2020-01-01T00:00:00Z")
    account.open(time, 100, direction, .5, 100)
    assert account.settle(rate, 120) == expected
    assert account.equity(90) == 10000 + expected + direction * -500
    trade = account.close(time + pd.Timedelta(hours=8), 100, "end_of_test")
    assert trade["net_pnl"] == expected
    assert trade["funding"] == expected


def test_4h_close_next_1m_open_mark_equity_and_terminal_close(dataset):
    config, frames, _ = dataset(slip=.01, fee=.001)
    frames["trade_1m"].loc[2, ["high", "close"]] = 110
    frames["mark_1m"].loc[0, ["mark_low", "mark_close"]] = 90
    frames["mark_1m"].loc[1:, ["mark_high", "mark_close"]] = 120
    save(config, frames)
    result = run_backtest(config, load_data(config))
    trade = result.trades.iloc[0]
    assert trade.entry_time == config.start.isoformat()
    assert trade.entry_reference == 100
    assert trade.entry_fill == 101
    assert trade.exit_time == config.end.isoformat()
    assert trade.exit_reference == 110
    assert trade.exit_fill == pytest.approx(108.9)
    assert trade.exit_reason == "end_of_test"
    q = 5000 / 101
    assert result.equity.iloc[1].equity == pytest.approx(9995 + q * (90 - 101))
    assert result.equity.iloc[2].equity == pytest.approx(9995 + q * (120 - 101))
    assert result.equity.iloc[-1].unrealized_pnl == 0
    assert result.equity.iloc[-1].equity == pytest.approx(10000 + trade.net_pnl)
    summary = metric_summary(config, result)
    assert summary["maximum_drawdown"] == pytest.approx((10000 - (9995 - 11 * q)) / 10000)
    assert summary["fees"] == pytest.approx(trade.entry_fee + trade.exit_fee)


def test_funding_before_entry_and_before_reversal_and_delay(dataset):
    config, frames, _ = dataset(minutes=242, closes={150: 50})
    frames["funding"] = pd.DataFrame({"funding_time": [config.start, config.start + pd.Timedelta(hours=4),
                                                       config.start + pd.Timedelta(hours=4, minutes=1)],
                                     "funding_rate": [.01, .01, .01], "funding_mark_price": [100, 100, 100]})
    result = run_backtest(config, engine_data(config, frames))
    long, short = result.trades.iloc[0], result.trades.iloc[1]
    assert long.funding == -50  # entry-time funding ignored, reversal-time charged to long
    assert long.exit_time == (config.start + pd.Timedelta(hours=4)).isoformat()
    assert short.entry_time == (config.start + pd.Timedelta(hours=4, minutes=1)).isoformat()
    assert short.quantity == 49.75  # after funding, entry re-sized from 9950 equity
    assert short.funding == 0  # delayed-entry-time funding sees flat account
    assert long.exit_reason == "reverse_signal"


@pytest.mark.parametrize("rate,expected", [(.01, -50), (-.01, 50)])
def test_millisecond_funding_is_not_silently_ignored(dataset, rate, expected):
    config, frames, _ = dataset()
    frames["funding"].loc[0, "funding_time"] = config.start + pd.Timedelta(milliseconds=47)
    frames["funding"].loc[0, "funding_rate"] = rate
    save(config, frames)
    result = run_backtest(config, load_data(config))
    assert result.trades.iloc[0].funding == expected


def test_pre_start_cross_does_not_open_without_new_cross(dataset):
    config, frames, _ = dataset(closes={148: 110, 149: 110})
    save(config, frames)
    result = run_backtest(config, load_data(config))
    assert result.trades.empty
    assert (result.equity.equity == 10000).all()


def test_future_incomplete_4h_cannot_change_run(dataset):
    config, frames, _ = dataset()
    original = run_backtest(config, load_data(config))
    frames["bars_4h"].loc[150, ["open", "high", "low", "close"]] = 1e9
    save(config, frames)
    changed = run_backtest(config, load_data(config))
    pd.testing.assert_frame_equal(original.trades, changed.trades)
    pd.testing.assert_frame_equal(original.equity, changed.equity)


def test_insolvency_latches_and_prevents_new_entry(dataset):
    config, frames, _ = dataset(minutes=242, closes={149: 90, 150: 150})
    frames["mark_1m"].loc[0, ["mark_high", "mark_close"]] = 400
    save(config, frames)
    result = run_backtest(config, load_data(config))
    assert result.invalid_reason == "non_positive_equity"
    assert result.invalid_time == (config.start + pd.Timedelta(minutes=1)).isoformat()
    assert len(result.trades) == 1
    assert result.trades.iloc[0].direction == "short"
    assert metric_summary(config, result)["maximum_drawdown"] == 1.5


@pytest.mark.parametrize("direction,closes", [("long", {149: 90, 150: 90, 151: 120, 152: 120}),
                                               ("short", {149: 110, 150: 110, 151: 80, 152: 80})])
def test_bollinger_uses_same_engine_exits_without_same_bar_reversal(dataset, direction, closes):
    strategy = {"name": "bollinger", "params": {"window": 3, "std_multiplier": 1}}
    config, frames, _ = dataset(minutes=722, strategy=strategy, closes=closes)
    save(config, frames)
    result = run_backtest(config, load_data(config))
    assert len(result.trades) == 1
    assert result.trades.iloc[0].direction == direction
    assert result.trades.iloc[0].exit_time == (config.start + pd.Timedelta(hours=8)).isoformat()
    assert result.trades.iloc[0].exit_reason == "strategy_exit"
