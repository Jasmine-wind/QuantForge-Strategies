"""Funding loader regressions; synthetic inputs prove correctness, not profitability."""
from dataclasses import replace
import subprocess
import sys

import pandas as pd
import pytest

from conftest import save
from qfs.data import load_data, validate_frame
from qfs.engine import run_backtest
from qfs.funding import validate_funding_schedule, funding_policy
from qfs.report import metric_summary


def test_same_settlement_different_milliseconds_rejected(dataset):
    config, frames, _ = dataset(minutes=481)
    frames["funding"].loc[1, "funding_rate"] = .01
    save(config, frames)
    normal = run_backtest(config, load_data(config))
    assert normal.trades.iloc[0].funding == -50
    assert normal.equity.iloc[-1].equity == 9950
    extra = frames["funding"].iloc[1:].copy()
    extra["funding_time"] += pd.Timedelta(milliseconds=47)
    frames["funding"] = pd.concat([frames["funding"], extra], ignore_index=True)
    save(config, frames)
    with pytest.raises(ValueError, match="duplicate Funding settlement") as err:
        load_data(config)
    assert str(config.data["funding"]) in str(err.value)
    assert "expected 2020-01-26T08:00:00+00:00" in str(err.value)
    assert "08:00:00.047000" in str(err.value)


def test_record_moved_seven_hours_rejected(dataset):
    config, frames, _ = dataset(minutes=421)
    frames["funding"].loc[0, "funding_rate"] = .01
    save(config, frames)
    normal = run_backtest(config, load_data(config))
    assert normal.trades.iloc[0].funding == 0
    assert normal.equity.iloc[-1].equity == 10000
    frames["funding"].loc[0, "funding_time"] += pd.Timedelta(hours=7)
    save(config, frames)
    with pytest.raises(ValueError, match="off-schedule Funding") as err:
        load_data(config)
    assert str(config.data["funding"]) in str(err.value)
    assert "expected 2020-01-26T08:00:00+00:00" in str(err.value)
    assert "actual 2020-01-26T07:00:00+00:00" in str(err.value)


@pytest.mark.parametrize("milliseconds", [0, 1, 15, 46, 47])
def test_legal_delay_preserved_and_existing_long_charged_once(dataset, milliseconds):
    config, frames, _ = dataset(minutes=481, closes={150: 110, 151: 110})
    actual = config.start + pd.Timedelta(hours=8, milliseconds=milliseconds)
    frames["funding"].loc[1, ["funding_time", "funding_rate"]] = [actual, .01]
    save(config, frames)
    data = load_data(config)
    assert data.funding.index[1] == actual  # matching is not timestamp rewriting
    assert data.files["funding"]["settlement_validation"] == funding_policy()
    result = run_backtest(config, data)
    assert result.trades.iloc[0].funding == -50
    assert result.equity.iloc[-1].equity == 9950


@pytest.mark.parametrize("offset", [pd.Timedelta(milliseconds=-1), pd.Timedelta(milliseconds=48),
                                     pd.Timedelta(seconds=1), pd.Timedelta(hours=4),
                                     pd.Timedelta(microseconds=1)])
def test_fixed_tolerance_not_inferred_from_candidate_input(dataset, offset):
    config, frames, _ = dataset(minutes=481)
    frames["funding"].loc[1, "funding_time"] += offset
    save(config, frames)
    with pytest.raises(ValueError, match="off-schedule Funding") as err:
        load_data(config)
    assert str(config.data["funding"]) in str(err.value)
    assert "[0,47]ms" in str(err.value)
    assert "expected" in str(err.value) and "actual" in str(err.value)


def test_record_shifted_by_whole_interval_does_not_replace_original_settlement(dataset):
    config, frames, _ = dataset()
    frames["funding"].loc[0, "funding_time"] += pd.Timedelta(hours=8)
    save(config, frames)
    with pytest.raises(ValueError, match="missing Funding settlement") as err:
        load_data(config)
    assert "expected 2020-01-26T00:00:00+00:00" in str(err.value)
    assert "08:00:00" in str(err.value)


def test_missing_expected_event_reports_neighbouring_actual_records(dataset):
    config, frames, _ = dataset(minutes=961)
    frames["funding"] = frames["funding"].drop(index=1)
    save(config, frames)
    with pytest.raises(ValueError, match="missing Funding settlement") as err:
        load_data(config)
    message = str(err.value)
    assert str(config.data["funding"]) in message
    assert "expected 2020-01-26T08:00:00+00:00" in message
    assert "actual records nearby" in message and "16:00:00" in message


@pytest.mark.parametrize("date", ["2019-12-31T16:00:00Z", "2026-08-01T00:00:00Z"])
def test_unverified_record_is_rejected_even_outside_execution_interval(dataset, date):
    config, frames, _ = dataset()
    extra = frames["funding"].iloc[:1].copy()
    extra["funding_time"] = pd.Timestamp(date)
    # Fixture construction orders rows; the loader itself must never sort them.
    frames["funding"] = pd.concat([frames["funding"], extra]).sort_values("funding_time")
    save(config, frames)
    with pytest.raises(ValueError, match="unverified Funding settlement") as err:
        load_data(config)
    assert pd.Timestamp(date).isoformat() in str(err.value)


@pytest.mark.parametrize("start,end", [("2019-12-31T00:00:00Z", "2020-01-01T00:00:00Z"),
                                       ("2026-07-31T00:00:00Z", "2026-08-01T00:01:00Z")])
def test_unknown_period_cannot_reuse_audited_schedule(start, end):
    empty = pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
    with pytest.raises(ValueError, match="unverified Funding schedule"):
        validate_funding_schedule(empty, pd.Timestamp(start), pd.Timestamp(end), "funding.parquet")


@pytest.mark.parametrize("delay,expected", [(0, 0), (1, -50), (47, -50)])
def test_entry_at_nominal_boundary_uses_actual_not_matched_time(dataset, delay, expected):
    config, frames, _ = dataset()
    frames["funding"].loc[0, ["funding_time", "funding_rate"]] = [config.start + pd.Timedelta(milliseconds=delay), .01]
    save(config, frames)
    result = run_backtest(config, load_data(config))
    assert result.trades.iloc[0].funding == expected
    assert result.equity.iloc[-1].equity == 10000 + expected


@pytest.mark.parametrize("delay,expected,short_quantity", [(0, -50, 49.75), (1, 0, 50), (47, 0, 50)])
def test_nominal_exit_then_delayed_reversal_keeps_funding_order(dataset, delay, expected, short_quantity):
    config, frames, _ = dataset(minutes=482, closes={150: 110, 151: 50})
    actual = config.start + pd.Timedelta(hours=8, milliseconds=delay)
    frames["funding"].loc[1, ["funding_time", "funding_rate"]] = [actual, .01]
    save(config, frames)
    result = run_backtest(config, load_data(config))
    long, short = result.trades.iloc[0], result.trades.iloc[1]
    assert long.funding == expected  # exact T charged before exit, delayed T sees Flat
    assert short.funding == 0
    assert short.quantity == short_quantity
    assert short.entry_time == (config.start + pd.Timedelta(hours=8, minutes=1)).isoformat()
    assert result.equity.iloc[-1].equity == 10000 + expected


@pytest.mark.parametrize("delay", [0, 1, 47])
@pytest.mark.parametrize("minutes,expected", [(480, 0), (481, -50)])
def test_terminal_boundary_excludes_actual_events_at_or_after_end(dataset, delay, minutes, expected):
    config, frames, _ = dataset(minutes=minutes, closes={150: 110, 151: 110})
    frames["funding"] = pd.DataFrame({"funding_time": [config.start, config.start + pd.Timedelta(hours=8, milliseconds=delay)],
                                    "funding_rate": [0, .01], "funding_mark_price": [100, 100]})
    save(config, frames)
    data = load_data(config)
    assert len(data.funding) == (1 if minutes == 480 else 2)
    result = run_backtest(config, data)
    assert result.trades.iloc[0].funding == expected
    assert result.equity.iloc[-1].equity == 10000 + expected


def test_start_after_delayed_event_does_not_charge_or_require_past_settlement(dataset):
    config, frames, _ = dataset(minutes=482)
    frames["funding"].loc[1, "funding_time"] += pd.Timedelta(milliseconds=47)
    frames["funding"].loc[1, "funding_rate"] = .01
    save(config, frames)
    config = replace(config, start=config.start + pd.Timedelta(hours=8, minutes=1))
    data = load_data(config)
    assert data.funding.empty
    result = run_backtest(config, data)
    assert result.trades.empty and result.equity.iloc[-1].equity == 10000


@pytest.mark.parametrize("outside", ["before_start", "at_end"])
def test_duplicate_not_hidden_by_interval_filter(dataset, outside):
    config, frames, _ = dataset(minutes=482)
    nominal = config.start + pd.Timedelta(hours=8)
    frames["funding"] = pd.DataFrame({"funding_time": [nominal, nominal + pd.Timedelta(milliseconds=47)],
                                    "funding_rate": .01, "funding_mark_price": 100})
    config = replace(config, start=nominal + pd.Timedelta(minutes=1)) if outside == "before_start" else replace(config, end=nominal)
    save(config, frames)
    with pytest.raises(ValueError, match="duplicate Funding settlement"):
        load_data(config)


@pytest.mark.parametrize("actual_ms,selected", [(0, False), (20, True), (29, True), (30, False), (47, False)])
def test_ms_boundary_halo_evidence_is_matched_before_actual_interval_selection(actual_ms, selected):
    # The public validator also handles sub-minute boundaries; CLI remains minute-aligned.
    nominal = pd.Timestamp("2020-02-01T08:00:00Z")
    actual = nominal + pd.Timedelta(milliseconds=actual_ms)
    df = validate_frame(pd.DataFrame({"funding_time": [actual], "funding_rate": [.01], "funding_mark_price": [100]}), "funding", "funding.parquet")
    result = validate_funding_schedule(df, nominal + pd.Timedelta(milliseconds=20), nominal + pd.Timedelta(milliseconds=30), "funding.parquet")
    assert len(result) == int(selected)
    if selected:
        assert result.index[0] == actual


def test_missing_boundary_evidence_is_not_assumed_to_be_zero():
    nominal = pd.Timestamp("2020-02-01T08:00:00Z")
    empty = pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
    with pytest.raises(ValueError, match="missing Funding settlement"):
        validate_funding_schedule(empty, nominal + pd.Timedelta(milliseconds=20), nominal + pd.Timedelta(milliseconds=30), "funding.parquet")


@pytest.mark.parametrize("damage", ["duplicate", "shifted", "missing", "outside_tolerance"])
def test_cli_rejects_bad_schedule_without_success_artifacts(dataset, damage):
    config, frames, config_path = dataset(minutes=481)
    if damage == "duplicate":
        extra = frames["funding"].iloc[1:].copy()
        extra["funding_time"] += pd.Timedelta(milliseconds=47)
        frames["funding"] = pd.concat([frames["funding"], extra], ignore_index=True)
    elif damage == "shifted":
        frames["funding"].loc[0, "funding_time"] += pd.Timedelta(hours=7)
    elif damage == "missing":
        frames["funding"] = frames["funding"].iloc[:1]
    else:
        frames["funding"].loc[1, "funding_time"] += pd.Timedelta(milliseconds=48)
    save(config, frames)
    process = subprocess.run([sys.executable, "-m", "qfs.cli", "backtest", "--config", str(config_path)], text=True, capture_output=True)
    assert process.returncode == 1
    assert str(config.data["funding"]) in process.stderr
    assert "expected" in process.stderr and "actual" in process.stderr
    assert not process.stdout and not config.output_dir.exists()


def test_drawdown_remains_minute_close_sampled_not_intraminute_event_peak(dataset):
    config, frames, _ = dataset()
    frames["funding"].loc[0, ["funding_time", "funding_rate"]] = [config.start + pd.Timedelta(milliseconds=1), .01]
    frames["mark_1m"][["mark_high", "mark_close"]] = 101
    frames["trade_1m"].loc[2, ["high", "close"]] = 101
    save(config, frames)
    result = run_backtest(config, load_data(config))
    assert result.trades.iloc[0].funding == -50  # transient equity 9950 at T+1ms
    assert (result.equity.equity == 10000).all()  # Mark close recovers the 50 loss
    assert metric_summary(config, result)["maximum_drawdown"] == 0
