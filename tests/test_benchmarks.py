"""Synthetic benchmark account checks, not historical performance evidence."""
import pandas as pd
import pytest

from conftest import save
from qfs.config import Config
from qfs.data import load_data
from qfs.engine import run_backtest
from qfs.report import metric_summary


@pytest.mark.parametrize("name", ["cash", "btc_perpetual_long_hold"])
def test_benchmarks_share_v1_account_costs_and_actual_funding(dataset, name):
    config, frames, _ = dataset(fee=.001, slip=.01)
    config = Config.from_dict(config.as_dict() | {"strategy": {"name": name}})
    frames["funding"].loc[0, "funding_time"] += pd.Timedelta(milliseconds=1)
    frames["funding"].loc[0, ["funding_rate", "funding_mark_price"]] = [.01, 120]
    frames["trade_1m"].loc[2, ["high", "close"]] = 110
    save(config, frames)
    result = run_backtest(config, load_data(config))
    summary = metric_summary(config, result)
    if name == "cash":
        assert result.trades.empty
        assert (result.equity.equity == 10000).all()
        assert summary["total_return"] == summary["maximum_drawdown"] == 0
        assert summary["fees"] == summary["slippage_cost"] == summary["funding_net"] == 0
        assert summary["sharpe"] is None
    else:
        assert len(result.trades) == 1
        trade = result.trades.iloc[0]
        assert trade.direction == "long"
        assert trade.quantity == pytest.approx(49.504950495049506)
        assert trade.entry_fill == 101
        assert trade.exit_fill == pytest.approx(108.9)
        assert trade.entry_time == config.start.isoformat()
        assert trade.exit_time == config.end.isoformat()
        assert trade.exit_reason == "end_of_test"
        assert trade.funding == pytest.approx(-59.40594059405941)
        assert trade.fees == pytest.approx(10.39108910891089)
        assert trade.net_pnl == pytest.approx(321.2920792079208)
        assert result.equity.iloc[-1].equity == pytest.approx(10321.292079207921)


@pytest.mark.parametrize("delay", [0, 1, 47])
@pytest.mark.parametrize("rate", [-.01, .01])
def test_perpetual_start_funding_real_time_and_sign(dataset, delay, rate):
    config, frames, _ = dataset()
    config = Config.from_dict(config.as_dict() | {"strategy": {"name": "btc_perpetual_long_hold"}})
    frames["funding"].loc[0, "funding_time"] += pd.Timedelta(milliseconds=delay)
    frames["funding"].loc[0, "funding_rate"] = rate
    save(config, frames)
    result = run_backtest(config, load_data(config))
    expected = 0 if delay == 0 else (-50 if rate > 0 else 50)
    assert result.trades.iloc[0].funding == expected
    assert result.equity.iloc[-1].equity == 10000 + expected


def test_perpetual_does_not_follow_signals_or_rebalance_after_funding(dataset):
    config, frames, _ = dataset(minutes=481, closes={150: 50})
    config = Config.from_dict(config.as_dict() | {"strategy": {"name": "btc_perpetual_long_hold"}})
    frames["funding"].loc[1, "funding_rate"] = .01
    save(config, frames)
    result = run_backtest(config, load_data(config))
    assert len(result.trades) == 1
    assert result.trades.iloc[0].quantity == 50
    assert result.trades.iloc[0].funding == -50
    assert result.trades.iloc[0].exit_time == config.end.isoformat()


@pytest.mark.parametrize("name", ["cash", "btc_perpetual_long_hold"])
def test_benchmark_rejects_parameters(dataset, name):
    config, _, _ = dataset()
    with pytest.raises(ValueError, match="invalid strategy or parameters"):
        Config.from_dict(config.as_dict() | {"strategy": {"name": name, "params": {"window": 20}}})
