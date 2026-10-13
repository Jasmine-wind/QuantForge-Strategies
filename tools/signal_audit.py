"""Independent V1 signal/timing audit for the four fixed V2 comparison members.

Pandas handles Parquet/tables and timestamps, not indicator calculations.
EMA is scalar recursion; Bollinger uses a fresh 20-close mean/population variance. No production indicators, decisions,
loader or engine; no fills, quantities, Funding, costs or account calculations.
Only completed reports are eligible (the caller's Ledger Audit checks status).
"""
import hashlib
from io import BytesIO
import math
from pathlib import Path

import pandas as pd


FIXED_STRATEGIES = {
    'ema_20_50': {'name': 'ema', 'params': {'fast': 20, 'slow': 50}},
    'bollinger_20_2': {'name': 'bollinger', 'params': {'window': 20, 'std_multiplier': 2.0}},
    'usdt_cash': {'name': 'cash', 'params': {}},
    'btcusdt_perpetual_long_hold': {'name': 'btc_perpetual_long_hold', 'params': {}},
}
FOUR_HOURS = pd.Timedelta(hours=4)
ONE_MINUTE = pd.Timedelta(minutes=1)


def require(condition, message):
    # Do not let Python -O silently disable the new audit.
    if not condition:
        raise ValueError(f'Signal Audit: {message}')


def _closes(config, digest):
    blob = Path(config.data['bars_4h']).read_bytes()
    require(hashlib.sha256(blob).hexdigest() == digest, '4H snapshot SHA mismatch')
    bars = pd.read_parquet(BytesIO(blob))  # hash and decode the very same snapshot
    require({'open_time', 'close'} <= set(bars.columns) and len(bars) > 0, 'missing 4H closes')
    require(not any(isinstance(t, (int, float)) for t in bars.open_time), 'numeric 4H timestamp')
    times = pd.DatetimeIndex(pd.to_datetime(bars.open_time, utc=True, format='mixed'))
    require(not times.hasnans and times.is_unique and times.is_monotonic_increasing,
            '4H timestamps must be unique and increasing')
    require((times == times.floor('4h')).all(), '4H timestamps must be UTC aligned')
    prices = [float(value) for value in bars.close]
    require(all(math.isfinite(p) and p > 0 for p in prices), 'non-finite/non-positive 4H close')
    # Exclude the bar completing exactly at end, and all unfinished/future bars.
    count = sum(t + FOUR_HOURS < config.end for t in times)
    times, prices = times[:count], prices[:count]
    require(len(times) > 0, 'no completed 4H history')
    last_open = (config.end - pd.Timedelta(nanoseconds=1)).floor('4h') - FOUR_HOURS
    require(times.equals(pd.date_range(times[0], last_open, freq='4h')), 'gap in 4H history')
    warmup = 150 if config.strategy['name'] == 'ema' else 21 if config.strategy['name'] == 'bollinger' else 0
    require(sum(t + FOUR_HOURS <= config.start for t in times) >= warmup,
            f'need {warmup} completed pre-start warmup bars')
    return times + FOUR_HOURS, prices


def _features(prices, name):
    if name == 'ema':
        fast = slow = prices[0]  # first supplied close; preserve ALL supplied prehistory
        for price in prices:
            fast += (price - fast) * (2 / 21)
            slow += (price - slow) * (2 / 51)
            yield price, fast, slow
    else:
        for i, price in enumerate(prices):
            if i < 19:
                yield None
                continue
            window = prices[i - 19:i + 1]
            middle = math.fsum(window) / 20
            deviation = math.sqrt(math.fsum((p - middle) ** 2 for p in window) / 20)
            yield price, middle, middle - 2 * deviation, middle + 2 * deviation


def _trade(entry, exit, side, reason):
    return {'entry_time': entry.isoformat(), 'exit_time': exit.isoformat(),
            'direction': 'long' if side == 1 else 'short', 'exit_reason': reason}


def _schedule(times, prices, config):
    name, start, end = config.strategy['name'], config.start, config.end
    if name == 'cash':
        return []
    if name == 'btc_perpetual_long_hold':
        return [_trade(start, end, 1, 'end_of_test')]
    expected, previous, side, entry = [], None, 0, None
    for time, current in zip(times, _features(prices, name), strict=True):
        if time >= start and previous is not None and current is not None:
            if name == 'ema':
                _, old_fast, old_slow = previous
                _, fast, slow = current
                crossing = (1 if old_fast <= old_slow and fast > slow else
                            -1 if old_fast >= old_slow and fast < slow else 0)
                if crossing and crossing != side:
                    due = time
                    if side:
                        expected.append(_trade(entry, time, side, 'reverse_signal'))
                        due += ONE_MINUTE
                    # Consecutive signals are >=4H apart, so the reversed target
                    # cannot change before due. Never execute an entry at end.
                    side = crossing if due < end else 0
                    entry = due if side else None
            else:
                old_price, old_middle, old_lower, old_upper = previous
                price, middle, lower, upper = current
                if side:
                    crossed_middle = (old_price < old_middle and price >= middle if side == 1 else
                                      old_price > old_middle and price <= middle)
                    if crossed_middle:
                        expected.append(_trade(entry, time, side, 'strategy_exit'))
                        side, entry = 0, None
                    # Even if this bar crosses the opposite outer band, no same-bar re-entry.
                elif old_lower <= old_price <= old_upper:
                    side = 1 if price < lower else -1 if price > upper else 0
                    entry = time if side else None
        previous = current
    if side:
        # This is the end boundary timestamp, not the last minute's open time.
        # Reference/fill at the last minute CLOSE remains the Ledger Audit's job.
        expected.append(_trade(entry, end, side, 'end_of_test'))
    return expected


def audit_signals(config, trades, *, member, bars_sha256):
    """Compare every ordered trade's four timing/direction fields to raw 4H rules.

    Membership is independently pinned to V2, not inferred from potentially
    falsified report parameters. Timestamps/directions/reasons have no tolerance.
    Returned evidence is separate from (and never rewrites) the original report.
    """
    require(member in FIXED_STRATEGIES and config.strategy == FIXED_STRATEGIES[member],
            f'{member}: strategy differs from fixed V2 member')
    times, prices = _closes(config, bars_sha256)
    expected = _schedule(times, prices, config)
    require(len(trades) == len(expected),
            f'{member}: trade count expected {len(expected)}, reported {len(trades)}')
    fields = ('entry_time', 'exit_time', 'direction', 'exit_reason')
    require(set(fields) <= set(trades.columns), f'{member}: missing trade timing columns')
    for number, (actual, wanted) in enumerate(zip(trades.to_dict('records'), expected), 1):
        for field in fields:
            value, target = actual[field], wanted[field]
            if field.endswith('_time'):
                value, target = pd.Timestamp(value), pd.Timestamp(target)
            require(value == target,
                    f'{member}: trade {number} {field} expected {wanted[field]}, reported {actual[field]}')
    return {'version': 'qfs-signal-audit-1', 'status': 'passed', 'member': member,
            'bars_4h_sha256': bars_sha256, 'completed_bars': len(prices),
            'trade_count': len(expected), 'expected_trades': expected}
