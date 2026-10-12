"""Strict JSON configuration, resolved relative to the configuration file."""
from dataclasses import dataclass
import json
from pathlib import Path
import math

import pandas as pd


DATA_KEYS = ("bars_4h", "trade_1m", "mark_1m", "funding")


def utc(value, label="time"):
    if not isinstance(value, (str, pd.Timestamp)):
        raise ValueError(f"{label}: expected an ISO timestamp, not a numeric epoch")
    try:
        t = pd.Timestamp(value)
        if pd.isna(t):
            raise ValueError("missing time")
        return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{label}: invalid timestamp {value!r}") from exc


@dataclass(frozen=True)
class Config:
    strategy: dict
    symbol: str
    start: pd.Timestamp
    end: pd.Timestamp
    data: dict[str, Path]
    initial_equity: float
    position_fraction: float
    maximum_leverage: float
    taker_fee_rate: float
    slippage_rate: float
    output_dir: Path
    data_source: dict

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")), path.parent)

    @classmethod
    def from_dict(cls, raw, base=None):
        base = Path.cwd() if base is None else Path(base)
        required = {"strategy", "symbol", "start", "end", "data", "initial_equity",
                    "position_fraction", "maximum_leverage", "taker_fee_rate",
                    "slippage_rate", "output_dir"}
        if not isinstance(raw, dict) or required - raw.keys():
            raise ValueError(f"config: missing fields {sorted(required - raw.keys()) if isinstance(raw, dict) else required}")
        if raw.keys() - required - {"data_source"}:
            raise ValueError(f"config: unknown fields {sorted(raw.keys() - required - {'data_source'})}")
        if raw["symbol"] != "BTCUSDT":
            raise ValueError("config: V1 supports only Binance BTCUSDT USD-M perpetual")
        start, end = utc(raw["start"], "start"), utc(raw["end"], "end")
        if end <= start or start != start.floor("min") or end != end.floor("min"):
            raise ValueError("config: start/end must be minute aligned with start < end")
        values = {}
        for key in ("initial_equity", "position_fraction", "maximum_leverage", "taker_fee_rate", "slippage_rate"):
            val = raw[key]
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
                raise ValueError(f"config: {key} must be finite numeric")
            values[key] = float(val)
        if values["initial_equity"] <= 0:
            raise ValueError("config: initial_equity must be positive")
        if not 0 < values["position_fraction"] <= values["maximum_leverage"] <= 1:
            raise ValueError("config: require 0 < position_fraction <= maximum_leverage <= 1")
        if any(not 0 <= values[k] < 1 for k in ("taker_fee_rate", "slippage_rate")):
            raise ValueError("config: fee/slippage must be in [0, 1)")
        strategy = raw["strategy"]
        if not isinstance(strategy, dict) or strategy.keys() - {"name", "params"}:
            raise ValueError("config: strategy must contain name and optional params")
        name, params = strategy.get("name"), strategy.get("params", {})
        defaults = {"ema": {"fast": 20, "slow": 50}, "bollinger": {"window": 20, "std_multiplier": 2.0},
                    "cash": {}, "btc_perpetual_long_hold": {}}
        if name not in defaults or not isinstance(params, dict) or params.keys() - defaults[name].keys():
            raise ValueError("config: invalid strategy or parameters")
        params = defaults[name] | params
        int_keys = ("fast", "slow") if name == "ema" else (("window",) if name == "bollinger" else ())
        for key in int_keys:
            if type(params[key]) is not int or params[key] < 2:
                raise ValueError(f"config: {key} must be an integer >= 2")
        if name == "ema" and params["fast"] >= params["slow"]:
            raise ValueError("config: EMA fast must be less than slow")
        if name == "bollinger":
            mult = params["std_multiplier"]
            if isinstance(mult, bool) or not isinstance(mult, (float, int)) or not math.isfinite(mult) or mult <= 0:
                raise ValueError("config: std_multiplier must be positive finite")
        data = raw["data"]
        if not isinstance(data, dict) or set(data) != set(DATA_KEYS):
            raise ValueError(f"config: data must specify {DATA_KEYS}")
        source = raw.get("data_source", {"description": "unverified local input", "independent_out_of_sample": False})
        if not isinstance(source, dict):
            raise ValueError("config: data_source must be an object")
        return cls(strategy={"name": name, "params": params}, symbol=raw["symbol"],
                   start=start, end=end, data={k: (base / Path(v)).resolve() for k, v in data.items()},
                   output_dir=(base / Path(raw["output_dir"])).resolve(), data_source=source, **values)

    def as_dict(self):
        return {"strategy": self.strategy, "symbol": self.symbol, "start": self.start.isoformat(),
                "end": self.end.isoformat(), "data": {k: str(v) for k, v in self.data.items()},
                "initial_equity": self.initial_equity, "position_fraction": self.position_fraction,
                "maximum_leverage": self.maximum_leverage, "taker_fee_rate": self.taker_fee_rate,
                "slippage_rate": self.slippage_rate, "output_dir": str(self.output_dir),
                "data_source": self.data_source}
