"""Independent report-ledger reconciliation; never calls the account/engine.

This is acceptance tooling, not an alternative execution engine.
"""
# Guard the module boundary, not only CLI main: direct callers need assertions too.
if not __debug__:
    raise RuntimeError('audit: optimized Python is unsafe; remove -O/-OO or PYTHONOPTIMIZE')

import json
import math

import pandas as pd

from qfs.data import sha256


def close(a, b):
    assert math.isclose(float(a), float(b), rel_tol=1e-11, abs_tol=1e-8), (a, b)


def reconcile(config, output):
    summary = json.loads((output / 'summary.json').read_text())
    manifest = json.loads((output / 'manifest.json').read_text())
    assert manifest['status'] == summary['status'] == 'completed'
    assert manifest['config'] == summary['config'] == config.as_dict()
    for key, info in manifest['data_files'].items():
        assert sha256(config.data[key]) == info['sha256']
    trades = pd.read_csv(output / 'trades.csv', float_precision='round_trip')
    curve = pd.read_csv(output / 'equity.csv', float_precision='round_trip')
    funding = pd.read_parquet(config.data['funding'])
    funding.funding_time = pd.to_datetime(funding.funding_time, utc=True)
    price = pd.read_parquet(config.data['trade_1m']).set_index('open_time')
    marks = pd.read_parquet(config.data['mark_1m']).set_index('open_time')
    events = []
    balance_before_next_entry = config.initial_equity
    for trade in trades.itertuples():
        entry, exit = pd.Timestamp(trade.entry_time), pd.Timestamp(trade.exit_time)
        side = 1 if trade.direction == 'long' else -1
        close(trade.signed_quantity, side * trade.quantity)
        close(trade.entry_reference, price.loc[entry, 'open'])
        close(trade.exit_reference, price.loc[config.end - pd.Timedelta(minutes=1), 'close']
              if trade.exit_reason == 'end_of_test' else price.loc[exit, 'open'])
        close(trade.entry_fill, trade.entry_reference * (1 + side * config.slippage_rate))
        close(trade.exit_fill, trade.exit_reference * (1 - side * config.slippage_rate))
        close(trade.quantity * trade.entry_fill, balance_before_next_entry * config.position_fraction)
        close(trade.entry_fee, trade.quantity * trade.entry_fill * config.taker_fee_rate)
        close(trade.exit_fee, trade.quantity * trade.exit_fill * config.taker_fee_rate)
        close(trade.fees, trade.entry_fee + trade.exit_fee)
        close(trade.entry_slippage, trade.quantity * abs(trade.entry_fill - trade.entry_reference))
        close(trade.exit_slippage, trade.quantity * abs(trade.exit_fill - trade.exit_reference))
        close(trade.slippage, trade.entry_slippage + trade.exit_slippage)
        gross = trade.signed_quantity * (trade.exit_fill - trade.entry_fill)
        cash_sum = 0
        held = funding[(funding.funding_time > entry) & (funding.funding_time <= exit) & (funding.funding_time < config.end)]
        for f in held.itertuples():
            cash = -trade.signed_quantity * f.funding_mark_price * f.funding_rate
            cash_sum += cash
            events.append((f.funding_time, 0, 'fund', cash))
        close(trade.gross_pnl, gross)
        close(trade.funding, cash_sum)
        close(trade.net_pnl, gross - trade.entry_fee - trade.exit_fee + cash_sum)
        close(trade.holding_hours, (exit - entry).total_seconds() / 3600)
        events.extend([(entry, 2, 'entry', trade), (exit, 1, 'exit', trade)])
        balance_before_next_entry += trade.net_pnl
    events.sort(key=lambda e: (e[0], e[1]))
    expected_times = list(pd.date_range(config.start, config.end, freq='min'))
    if (trades.exit_reason == 'end_of_test').any():
        expected_times.append(config.end)
    assert list(pd.to_datetime(curve.time, utc=True)) == expected_times
    wallet, active, i = config.initial_equity, None, 0
    for row in curve.itertuples():
        time = pd.Timestamp(row.time)
        close(row.mark_price, marks.loc[config.start, 'mark_open'] if row.event == 'initial'
              else marks.loc[time - pd.Timedelta(minutes=1), 'mark_close'])
        while i < len(events) and (events[i][0] < time or (events[i][0] == time and row.event == 'end_of_test')):
            _, _, kind, obj = events[i]
            if kind == 'fund':
                wallet += obj
            elif kind == 'entry':
                assert active is None
                wallet -= obj.entry_fee
                active = obj
            else:
                assert active is not None
                wallet += obj.gross_pnl - obj.exit_fee
                active = None
            i += 1
        unrealized = 0 if active is None else active.signed_quantity * (row.mark_price - active.entry_fill)
        close(row.wallet, wallet)
        close(row.unrealized_pnl, unrealized)
        close(row.equity, wallet + unrealized)
    assert active is None and i == len(events)
    close(summary['final_equity'], config.initial_equity + trades.net_pnl.sum())
    close(summary['final_equity'], curve.iloc[-1].equity)
    close(summary['total_return'], summary['final_equity'] / config.initial_equity - 1)
    for metric, column in [('net_pnl', 'net_pnl'), ('gross_pnl', 'gross_pnl'), ('fees', 'fees'),
                           ('slippage_cost', 'slippage'), ('funding_net', 'funding')]:
        close(summary[metric], trades[column].sum())
    assert len(trades) == summary['trade_count']
    return summary, manifest, trades, curve
