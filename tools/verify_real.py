"""Local acceptance check of real CLI outputs; no performance/inference claim."""
import argparse
import json
from pathlib import Path
import subprocess
import math

import pandas as pd
from qfs.config import Config
from qfs.data import sha256


def close(a, b):
    assert math.isclose(float(a), float(b), rel_tol=1e-11, abs_tol=1e-8), (a, b)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config-prefix', default='.local/real', help='Read <prefix>-ema.json and <prefix>-bollinger.json')
parser.add_argument('--output', default='.local/verification.json')
parser.add_argument('--baseline', help='Prior verification JSON; assert fixed-input financial results/CSV bytes unchanged')
args = parser.parse_args()
baseline = json.loads(Path(args.baseline).read_text()) if args.baseline else None
results = {}
for name in ('ema', 'bollinger'):
    path = Path(f'{args.config_prefix}-{name}.json')
    config = Config.load(path)
    runs = []
    for _ in range(2):
        command = ['.venv/bin/qfs', 'backtest', '--config', str(path)]
        proc = subprocess.run(command, text=True, capture_output=True)
        assert proc.returncode == 0, proc.stderr
        output = Path(proc.stdout.strip())
        runs.append(output)
        print(' '.join(command), '=>', output)
    for file in runs[0].iterdir():
        assert file.read_bytes() == (runs[1] / file.name).read_bytes(), file.name
    output = runs[0]
    summary = json.loads((output / 'summary.json').read_text())
    manifest = json.loads((output / 'manifest.json').read_text())
    assert manifest['status'] == summary['status'] == 'completed'
    assert manifest['data_source']['independent_out_of_sample'] is False
    for key, info in manifest['data_files'].items():
        assert sha256(config.data[key]) == info['sha256']
    trades = pd.read_csv(output / 'trades.csv')
    curve = pd.read_csv(output / 'equity.csv')
    funding = pd.read_parquet(config.data['funding'])
    funding.funding_time = pd.to_datetime(funding.funding_time, utc=True)
    events = []
    balance_before_next_entry = config.initial_equity
    for trade in trades.itertuples():
        entry, exit = pd.Timestamp(trade.entry_time), pd.Timestamp(trade.exit_time)
        side = 1 if trade.direction == 'long' else -1
        close(trade.entry_fill, trade.entry_reference * (1 + side * config.slippage_rate))
        close(trade.exit_fill, trade.exit_reference * (1 - side * config.slippage_rate))
        close(trade.quantity * trade.entry_fill, balance_before_next_entry * config.position_fraction)
        close(trade.entry_fee, trade.quantity * trade.entry_fill * config.taker_fee_rate)
        close(trade.exit_fee, trade.quantity * trade.exit_fill * config.taker_fee_rate)
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
        events.extend([(entry, 2, 'entry', trade), (exit, 1, 'exit', trade)])
        balance_before_next_entry += trade.net_pnl
    events.sort(key=lambda e: (e[0], e[1]))
    wallet, active, i = config.initial_equity, None, 0
    for row in curve.itertuples():
        time = pd.Timestamp(row.time)
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
    assert len(trades) == summary['trade_count']
    if baseline:
        previous = Path(baseline[name]['outputs'][0])
        for file in ('trades.csv', 'equity.csv'):
            assert (output / file).read_bytes() == (previous / file).read_bytes(), f'{name}: baseline {file} changed'
        prior_summary = json.loads((previous / 'summary.json').read_text())
        for key in prior_summary.keys() - {'contract_version', 'limitations', 'metric_definitions', 'funding_validation'}:
            assert prior_summary[key] == summary[key], f'{name}: baseline {key} changed'
        print(name, 'baseline financial results and both CSV files unchanged')
    results[name] = {'outputs': [str(p) for p in runs], 'code': manifest['code'],
                     'trade_count': len(trades), 'equity_rows': len(curve),
                     'byte_determinism': '4/4 files identical', 'ledger_reconciliation': 'all trades and every equity row passed',
                     'artifact_sha256': {p.name: sha256(p) for p in output.iterdir()}}
    print(name, 'PASS:', len(trades), 'trades /', len(curve), 'equity rows; deterministic and independently reconciled')
Path(args.output).write_text(json.dumps(results, sort_keys=True, indent=2) + '\n', encoding='utf-8')
