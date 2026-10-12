"""Causal 4H indicators and direction-only decisions, independent of execution."""
import pandas as pd


def indicators(close: pd.Series, strategy: dict):
    p = strategy["params"]
    out = pd.DataFrame({"close": close})
    if strategy["name"] == "ema":
        out["fast"] = close.ewm(span=p["fast"], adjust=False).mean()
        out["slow"] = close.ewm(span=p["slow"], adjust=False).mean()
    else:
        middle = close.rolling(p["window"]).mean()
        deviation = close.rolling(p["window"]).std(ddof=0) * p["std_multiplier"]
        out["middle"], out["lower"], out["upper"] = middle, middle - deviation, middle + deviation
    return out


def decision(name: str, previous: pd.Series, current: pd.Series, position: int):
    """Return a new target -1/0/+1, or None (no event). Equality is intentional."""
    if previous.isna().any() or current.isna().any():
        return None
    if name == "ema":
        if previous.fast <= previous.slow and current.fast > current.slow:
            return 1
        if previous.fast >= previous.slow and current.fast < current.slow:
            return -1
        return None
    if position == 1:
        return 0 if previous.close < previous.middle and current.close >= current.middle else None
    if position == -1:
        return 0 if previous.close > previous.middle and current.close <= current.middle else None
    inside = previous.lower <= previous.close <= previous.upper
    if inside and current.close < current.lower:
        return 1
    if inside and current.close > current.upper:
        return -1
    return None
