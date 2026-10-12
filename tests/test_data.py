import pandas as pd
import pytest

from conftest import save
from qfs.config import Config
from qfs.data import load_data


@pytest.mark.parametrize("key", ["bars_4h", "trade_1m", "mark_1m", "funding"])
@pytest.mark.parametrize("corruption", ["duplicate", "order", "nan", "bad_time"])
def test_corrupt_inputs_fail_with_file(dataset, key, corruption):
    config, frames, _ = dataset(minutes=481)
    frame = frames[key].copy()
    if len(frame) < 2:
        frame = pd.concat([frame, frame.assign(funding_time=frame.funding_time + pd.Timedelta(minutes=1))], ignore_index=True)
    if corruption == "duplicate":
        frame = pd.concat([frame.iloc[:1], frame], ignore_index=True)
    elif corruption == "order":
        frame = frame.iloc[::-1]
    elif corruption == "nan":
        col = "funding_rate" if key == "funding" else "mark_close" if key == "mark_1m" else "close"
        frame.loc[frame.index[0], col] = float("nan")
    else:
        col = "funding_time" if key == "funding" else "open_time"
        frame[col] = frame[col].astype(str)
        frame.loc[frame.index[0], col] = "not-a-time"
    frames[key] = frame
    save(config, frames)
    with pytest.raises(ValueError, match=str(config.data[key])):
        load_data(config)


@pytest.mark.parametrize("key,col,val", [
    ("trade_1m", "low", 101), ("trade_1m", "high", 99),
    ("trade_1m", "volume", -1), ("bars_4h", "open", -1),
    ("mark_1m", "mark_close", 110), ("mark_1m", "mark_low", 0),
    ("funding", "funding_mark_price", 0), ("funding", "funding_mark_price", float("inf")),
    ("funding", "funding_rate", float("inf")),
])
def test_invalid_prices_and_funding(dataset, key, col, val):
    config, frames, _ = dataset()
    frames[key].loc[0, col] = val
    save(config, frames)
    with pytest.raises(ValueError, match=str(config.data[key])):
        load_data(config)


@pytest.mark.parametrize("key", ["bars_4h", "trade_1m", "mark_1m", "funding"])
def test_missing_required_timestamps_fail(dataset, key):
    config, frames, _ = dataset(minutes=481)
    index = 145 if key == "bars_4h" else 0
    frames[key] = frames[key].drop(index=index)
    save(config, frames)
    with pytest.raises(ValueError, match="missing required timestamp|warmup|missing Funding"):
        load_data(config)


def test_timezone_normalization_and_half_open_interval(dataset):
    config, frames, _ = dataset()
    for key, frame in frames.items():
        col = "funding_time" if key == "funding" else "open_time"
        frame[col] = frame[col].dt.tz_convert("Asia/Shanghai")
    save(config, frames)
    data = load_data(config)
    assert data.trade.index[0] == config.start
    assert data.trade.index[-1] == config.end - pd.Timedelta(minutes=1)


@pytest.mark.parametrize("key", ["bars_4h", "trade_1m", "mark_1m"])
def test_unaligned_kline_time_fails(dataset, key):
    config, frames, _ = dataset()
    frames[key].loc[0, "open_time"] += pd.Timedelta(milliseconds=47)
    save(config, frames)
    with pytest.raises(ValueError, match="alignment"):
        load_data(config)


def test_relative_config_paths_use_call_time_directory(dataset, monkeypatch):
    config, _, path = dataset()
    raw = config.as_dict() | {"data": {k: v.name for k, v in config.data.items()}, "output_dir": "runs"}
    monkeypatch.chdir(path.parent)
    resolved = Config.from_dict(raw)
    assert resolved.data == config.data
    assert resolved.output_dir == path.parent / "runs"


def test_inadequate_ema_warmup_fails(dataset):
    config, frames, _ = dataset()
    frames["bars_4h"] = frames["bars_4h"].iloc[1:]
    save(config, frames)
    with pytest.raises(ValueError, match="150"):
        load_data(config)


@pytest.mark.parametrize("change", [
    {"symbol": "ETHUSDT"}, {"position_fraction": 1.1}, {"maximum_leverage": 2},
    {"initial_equity": 0}, {"taker_fee_rate": -1}, {"slippage_rate": 1},
    {"start": "2020-01-26T00:00:01Z"}, {"end": "2019-01-01T00:00:00Z"},
    {"strategy": {"name": "ema", "params": {"fast": 50, "slow": 20}}},
    {"strategy": {"name": "bollinger", "params": {"std_multiplier": float("nan")}}},
])
def test_invalid_config(dataset, change):
    config, _, _ = dataset()
    with pytest.raises(ValueError):
        Config.from_dict(config.as_dict() | change)
