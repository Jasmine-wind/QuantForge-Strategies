"""Synthetic prices are correctness fixtures, never historical performance evidence."""
import json

import pandas as pd
import pytest

from qfs.config import Config


@pytest.fixture
def dataset(tmp_path):
    def create(minutes=3, strategy=None, closes=None, fee=0.0, slip=0.0):
        start = pd.Timestamp("2020-01-26T00:00:00Z")
        end = start + pd.Timedelta(minutes=minutes)
        bar_times = pd.date_range("2020-01-01T00:00:00Z", end, freq="4h", inclusive="left")
        values = [100.0] * len(bar_times)
        values[149] = 110.0
        if closes:
            for index, value in closes.items():
                values[index] = value
        bars = pd.DataFrame({"open_time": bar_times, "open": values, "high": values,
                             "low": values, "close": values, "volume": 1.0})
        times = pd.date_range(start, end, freq="min", inclusive="left")
        trade = pd.DataFrame({"open_time": times, "open": 100.0, "high": 100.0,
                              "low": 100.0, "close": 100.0, "volume": 1.0})
        mark = pd.DataFrame({"open_time": times, "mark_open": 100.0, "mark_high": 100.0,
                             "mark_low": 100.0, "mark_close": 100.0})
        funding = pd.DataFrame({"funding_time": pd.date_range(start, end, freq="8h", inclusive="left"),
                                "funding_rate": 0.0, "funding_mark_price": 100.0})
        frames = dict(bars_4h=bars, trade_1m=trade, mark_1m=mark, funding=funding)
        paths = {}
        for key, frame in frames.items():
            path = tmp_path / f"{key}.parquet"
            frame.to_parquet(path, index=False)
            paths[key] = str(path)
        raw = {"strategy": strategy or {"name": "ema"}, "symbol": "BTCUSDT",
               "start": start.isoformat(), "end": end.isoformat(), "data": paths,
               "initial_equity": 10000, "position_fraction": 0.5, "maximum_leverage": 1.0,
               "taker_fee_rate": fee, "slippage_rate": slip, "output_dir": str(tmp_path / "runs"),
               "data_source": {"description": "synthetic correctness fixture", "independent_out_of_sample": False}}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(raw))
        return Config.load(config_path), frames, config_path
    return create


def save(config, frames):
    for key, frame in frames.items():
        frame.to_parquet(config.data[key], index=False)
