import pandas as pd
import pytest

from conftest import save, engine_data
from qfs.data import load_data
from qfs.engine import run_backtest


def test_no_fill_before_4h_bar_completes(dataset):
    config, frames, _ = dataset(minutes=242, closes={149: 100, 150: 110})
    save(config, frames)
    result = run_backtest(config, load_data(config))
    assert len(result.trades) == 1
    assert result.trades.iloc[0].entry_time == (config.start + pd.Timedelta(hours=4)).isoformat()
    assert (result.equity.iloc[:241].equity == 10000).all()


def test_missing_exact_signal_minute_cannot_seek_next_price(dataset):
    config, frames, _ = dataset(minutes=242, closes={149: 100, 150: 110})
    frames["trade_1m"] = frames["trade_1m"].drop(index=240)
    save(config, frames)
    with pytest.raises(ValueError, match="2020-01-26 04:00:00"):
        load_data(config)


def test_end_excludes_same_time_signal_and_funding(dataset):
    config, frames, _ = dataset(minutes=480, closes={150: 110, 151: 50})
    frames["funding"] = pd.concat([frames["funding"], pd.DataFrame({
        "funding_time": [config.end], "funding_rate": [.1], "funding_mark_price": [100]})], ignore_index=True)
    save(config, frames)
    result = run_backtest(config, load_data(config))
    assert len(result.trades) == 1
    assert result.trades.iloc[0].exit_reason == "end_of_test"
    assert result.trades.iloc[0].funding == 0


def test_reverse_in_last_minute_does_not_open_outside_window(dataset):
    config, frames, _ = dataset(minutes=241, closes={150: 50})
    save(config, frames)
    result = run_backtest(config, load_data(config))
    assert len(result.trades) == 1
    assert result.trades.iloc[0].exit_reason == "reverse_signal"
    assert result.equity.iloc[-1].unrealized_pnl == 0


@pytest.mark.parametrize("first,second", [(110, 50), (90, 150)])
def test_reversal_has_four_fees_adverse_fills_and_new_equity_sizing(dataset, first, second):
    config, frames, _ = dataset(minutes=242, closes={149: first, 150: second}, fee=.001, slip=.01)
    save(config, frames)
    result = run_backtest(config, load_data(config))
    one, two = result.trades.iloc[0], result.trades.iloc[1]
    first_side = 1 if first == 110 else -1
    assert one.entry_fill == 100 + first_side
    assert one.exit_fill == 100 - first_side
    assert two.entry_fill == 100 - first_side
    assert two.exit_fill == 100 + first_side
    assert two.entry_time == (config.start + pd.Timedelta(minutes=241)).isoformat()
    assert two.quantity * two.entry_fill == pytest.approx((10000 + one.net_pnl) * .5)
    assert one.entry_fee == 5
    assert one.exit_fee > 0 and two.entry_fee > 0 and two.exit_fee > 0
    assert result.equity.iloc[-1].equity == pytest.approx(10000 + one.net_pnl + two.net_pnl)


def test_funding_after_delayed_short_entry_credits_short(dataset):
    config, frames, _ = dataset(minutes=242, closes={150: 50})
    frames["funding"] = pd.concat([frames["funding"], pd.DataFrame({
        "funding_time": [config.start + pd.Timedelta(minutes=241, milliseconds=47)],
        "funding_rate": [.01], "funding_mark_price": [120]})], ignore_index=True)
    result = run_backtest(config, engine_data(config, frames))
    assert result.trades.iloc[0].funding == 0
    assert result.trades.iloc[1].funding == 60
    assert result.equity.iloc[-1].equity == 10060


def test_bad_numeric_reports_file_and_timestamp(dataset):
    config, frames, _ = dataset()
    frames["trade_1m"]["close"] = frames["trade_1m"].close.astype(str)
    frames["trade_1m"].loc[1, "close"] = "invalid"
    save(config, frames)
    with pytest.raises(ValueError, match="trade_1m.parquet.*2020-01-26 00:01:00"):
        load_data(config)
