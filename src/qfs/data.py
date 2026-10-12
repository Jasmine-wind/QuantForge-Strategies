"""Fail-closed normalized Parquet input. No sorting, filling or price proxies."""
from dataclasses import dataclass
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, utc
from .funding import funding_policy, validate_funding_schedule


SCHEMAS = {
    "bars_4h": ("open_time", ["open", "high", "low", "close", "volume"]),
    "trade_1m": ("open_time", ["open", "high", "low", "close", "volume"]),
    "mark_1m": ("open_time", ["mark_open", "mark_high", "mark_low", "mark_close"]),
    "funding": ("funding_time", ["funding_rate", "funding_mark_price"]),
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_frame(frame, kind, label):
    time_col, numeric = SCHEMAS[kind]
    missing = set([time_col, *numeric]) - set(frame.columns)
    if missing:
        raise ValueError(f"{label}: missing columns {sorted(missing)}")
    df = frame[[time_col, *numeric]].copy()
    times = [utc(v, f"{label} row {i}") for i, v in enumerate(df[time_col])]
    df.index = pd.DatetimeIndex(times, tz="UTC", name=time_col)
    if df.index.has_duplicates:
        t = df.index[df.index.duplicated()][0]
        if kind == "funding":
            raise ValueError(f"{label}: duplicate Funding settlement; expected {t.round('8h').isoformat()}, "
                             f"actual [{t.isoformat()}, {t.isoformat()}]")
        raise ValueError(f"{label}: duplicate timestamp {t}")
    if not df.index.is_monotonic_increasing:
        i = np.flatnonzero(df.index[1:] < df.index[:-1])[0] + 1
        raise ValueError(f"{label}: out-of-order timestamp {df.index[i]}")
    df = df.drop(columns=time_col)
    for col in numeric:
        try:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{label}: invalid numeric {col}") from exc
        invalid = ~np.isfinite(df[col].to_numpy())
        if invalid.any():
            raise ValueError(f"{label}: non-finite {col} at {df.index[np.flatnonzero(invalid)[0]]}")
    if kind == "funding":
        bad = df.funding_mark_price <= 0
    else:
        prefix = "mark_" if kind == "mark_1m" else ""
        o, h, l, c = [df[prefix + k] for k in ("open", "high", "low", "close")]
        bad = (l <= 0) | (h < l) | (o < l) | (o > h) | (c < l) | (c > h)
        if "volume" in df:
            bad |= df.volume < 0
        freq = "4h" if kind == "bars_4h" else "min"
        bad |= df.index != df.index.floor(freq)
    if bad.any():
        raise ValueError(f"{label}: invalid OHLC/price/volume/alignment at {df.index[np.flatnonzero(bad)[0]]}")
    return df


def require_grid(df, expected, label):
    missing = expected.difference(df.index)
    if len(missing):
        raise ValueError(f"{label}: missing required timestamp {missing[0]}")


@dataclass(frozen=True)
class MarketData:
    bars: pd.DataFrame
    trade: pd.DataFrame
    mark: pd.DataFrame
    funding: pd.DataFrame
    files: dict


def load_data(config: Config):
    frames, files = {}, {}
    for key, path in config.data.items():
        label = str(path)
        before = sha256(path)
        frame = validate_frame(pd.read_parquet(path), key, label)
        if sha256(path) != before:
            raise ValueError(f"{path}: input changed while reading")
        time_col, _ = SCHEMAS[key]
        files[key] = {"path": str(path), "sha256": before, "row_count": len(frame),
                      "first_time": frame.index[0].isoformat() if len(frame) else None,
                      "last_time": frame.index[-1].isoformat() if len(frame) else None,
                      "time_column": time_col}
        frames[key] = frame
    minutes = pd.date_range(config.start, config.end, freq="min", inclusive="left")
    for key in ("trade_1m", "mark_1m"):
        require_grid(frames[key], minutes, config.data[key])
        frames[key] = frames[key].loc[minutes]
    bars = frames["bars_4h"]
    if bars.empty:
        raise ValueError(f"{config.data['bars_4h']}: empty 4H input")
    # Only completed bars enter the strategy. Require contiguous warmup + signal history.
    bars = bars[bars.index + pd.Timedelta(hours=4) < config.end]
    warmup = (150 if config.strategy["name"] == "ema" else
              config.strategy["params"]["window"] + 1 if config.strategy["name"] == "bollinger" else 0)
    completed = bars[bars.index + pd.Timedelta(hours=4) <= config.start]
    if len(completed) < warmup:
        raise ValueError(f"{config.data['bars_4h']}: need {warmup} completed pre-start warmup bars at {config.start}")
    # Preserve all supplied prehistory for adjust=False EMA seed reproducibility.
    last_signal_open = (config.end - pd.Timedelta(nanoseconds=1)).floor("4h") - pd.Timedelta(hours=4)
    required = pd.date_range(bars.index[0], last_signal_open, freq="4h")
    require_grid(bars, required, config.data["bars_4h"])
    funding = validate_funding_schedule(frames["funding"], config.start, config.end, config.data["funding"])
    files["funding"]["settlement_validation"] = funding_policy()
    files["funding"]["execution_row_count"] = len(funding)
    return MarketData(bars, frames["trade_1m"], frames["mark_1m"], funding, files)
