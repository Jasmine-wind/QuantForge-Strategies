"""UTC calendar slices of a continuous account, never trade-exit attribution."""
import numpy as np
import pandas as pd


PERIOD_DEFINITIONS = {
    "return": "end boundary equity / start boundary equity - 1; no account reset or periodic liquidation",
    "boundary": "completed-minute state before same-time orders/Funding; actual run end uses last terminal-settlement row",
    "maximum_drawdown": "period-local peak initialized at left boundary; all minute-close samples plus actual terminal settlement; intraminute swings may be missed",
    "partial": "clip first/last calendar period to actual run; show effective duration, do not annualize or extrapolate",
    "attribution": "equity change only; no exit-month assignment of whole trades, fees or Funding",
}


def period_rows(equity, start, end):
    times = pd.DatetimeIndex(pd.to_datetime(equity.time, utc=True, format="ISO8601"))
    values = equity.equity.to_numpy(dtype=float)
    boundary = pd.Series(values, index=times)
    boundary = boundary[~boundary.index.duplicated(keep="last")]
    rows = []
    for frequency, offset in (("month", pd.offsets.MonthBegin(1)), ("year", pd.offsets.YearBegin(1))):
        nominal = start.normalize().replace(day=1)
        if frequency == "year":
            nominal = nominal.replace(month=1)
        while nominal < end:
            following = nominal + offset
            left, right = max(start, nominal), min(end, following)
            for time in (left, right):
                if time not in boundary.index:
                    raise ValueError(f"period boundary equity missing at {time.isoformat()}")
            first, last = float(boundary.loc[left]), float(boundary.loc[right])
            samples = np.concatenate(([first], values[(times > left) & (times <= right)]))
            if not np.isfinite(samples).all() or (samples <= 0).any():
                raise ValueError(f"period: non-positive/non-finite sampled equity at {left.isoformat()}")
            rows.append({"frequency": frequency, "period": nominal.strftime("%Y-%m" if frequency == "month" else "%Y"),
                         "calendar_start": nominal.isoformat(), "calendar_end": following.isoformat(),
                         "start": left.isoformat(), "end": right.isoformat(),
                         "complete": left == nominal and right == following,
                         "effective_minutes": int((right - left).total_seconds() / 60),
                         "calendar_days": (right - left).total_seconds() / 86400,
                         "start_equity": first, "end_equity": last, "equity_change": last - first,
                         "return": last / first - 1,
                         "maximum_drawdown": float(np.max(1 - samples / np.maximum.accumulate(samples)))})
            nominal = following
    return rows
