"""Independent comparison acceptance: CLI repeatability, raw ledgers and period slices."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from qfs.config import Config
from qfs.data import sha256
from ledger import close, reconcile


def verify(output):
    payload = json.loads((output / 'comparison.json').read_text())
    assert payload['status'] == 'completed'
    expected_members = ['ema_20_50', 'bollinger_20_2', 'usdt_cash', 'btcusdt_perpetual_long_hold']
    expected_scenarios = ['base', 'slippage_x2', 'fee_and_slippage_x2']
    assert [(r['scenario'], r['member']) for r in payload['members']] == [(s, m) for s in expected_scenarios for m in expected_members]
    full = pd.read_csv(output / 'comparison.csv', float_precision='round_trip')
    periods_csv = pd.read_csv(output / 'periods.csv', float_precision='round_trip', dtype={'period': str})
    assert len(full) == 12 and len(periods_csv) == len(payload['periods'])
    for file, digest in payload['artifact_sha256'].items():
        assert sha256(output / file) == digest
    records = []
    for member in payload['members']:
        config = Config.from_dict(member['config'])
        shared = payload['shared_config']
        for key in ('data', 'symbol', 'start', 'end', 'initial_equity', 'position_fraction', 'maximum_leverage', 'output_dir', 'data_source'):
            assert config.as_dict()[key] == shared[key]
        scene = member['scenario']
        fee_multiple = 2 if scene == 'fee_and_slippage_x2' else 1
        slip_multiple = 1 if scene == 'base' else 2
        close(config.taker_fee_rate, shared['taker_fee_rate'] * fee_multiple)
        close(config.slippage_rate, shared['slippage_rate'] * slip_multiple)
        raw = output / member['raw_report']
        for file, digest in member['artifact_sha256'].items():
            assert sha256(raw / file) == digest
        summary, manifest, trades, curve = reconcile(config, raw)
        assert manifest['code'] == payload['code'] and manifest['runtime'] == payload['runtime']
        assert member['summary'] == summary
        row = full[(full.member == member['member']) & (full.scenario == scene)].iloc[0]
        for key in ('final_equity', 'net_pnl', 'total_return', 'maximum_drawdown', 'fees', 'slippage_cost', 'funding_net', 'trade_count'):
            close(row[key], summary[key])
        values = curve.equity.to_numpy()
        close(summary['maximum_drawdown'], np.max(1 - values / np.maximum.accumulate(values)))
        days = (config.end - config.start).total_seconds() / 86400
        # Decide representability independently from ledger equity and actual duration,
        # not from the reported null. Negative log-growth underflow remains finite (-1).
        log_growth = math.log(float(values[-1]) / config.initial_equity) * 365 / days
        if log_growth > math.log(sys.float_info.max):
            assert summary['annualized_return'] is None, f"{scene}/{member['member']}: annualized_return must be null for float64 overflow"
        else:
            assert summary['annualized_return'] is not None, f"{scene}/{member['member']}: unexpected null for representable annualized_return"
            close(summary['annualized_return'], math.expm1(log_growth))
        time = pd.DatetimeIndex(pd.to_datetime(curve.time, utc=True))
        boundaries = pd.Series(values, index=time)
        boundaries = boundaries[~boundaries.index.duplicated(keep='last')]
        dates = pd.date_range(config.start.ceil('D'), config.end.floor('D'), freq='D')
        returns = [boundaries.loc[b] / boundaries.loc[a] - 1 for a, b in zip(dates[:-1], dates[1:])]
        assert summary['sharpe_daily_returns'] == len(returns)
        std = np.std(returns, ddof=1) if len(returns) >= 2 else 0
        if std > 0:
            close(summary['sharpe'], np.mean(returns) / std * math.sqrt(365))
        else:
            assert summary['sharpe'] is None
        slices = [r for r in payload['periods'] if r['scenario'] == scene and r['member'] == member['member']]
        for frequency in ('month', 'year'):
            selected = [r for r in slices if r['frequency'] == frequency]
            assert pd.Timestamp(selected[0]['start']) == config.start and pd.Timestamp(selected[-1]['end']) == config.end
            compounded, last_end = 1.0, None
            for period in selected:
                left, right = pd.Timestamp(period['start']), pd.Timestamp(period['end'])
                if last_end is not None:
                    assert left == last_end
                a, b = boundaries.loc[left], boundaries.loc[right]
                close(period['start_equity'], a)
                close(period['end_equity'], b)
                close(period['equity_change'], b - a)
                close(period['return'], b / a - 1)
                samples = np.r_[a, values[(time > left) & (time <= right)]]
                close(period['maximum_drawdown'], np.max(1 - samples / np.maximum.accumulate(samples)))
                assert period['complete'] == (left == pd.Timestamp(period['calendar_start']) and right == pd.Timestamp(period['calendar_end']))
                close(period['calendar_days'], (right - left).total_seconds() / 86400)
                assert period['effective_minutes'] == int((right - left).total_seconds() / 60)
                csv_row = periods_csv[(periods_csv.member == member['member']) & (periods_csv.scenario == scene) &
                                      (periods_csv.frequency == frequency) & (periods_csv.period == period['period'])].iloc[0]
                close(csv_row['return'], period['return'])
                close(csv_row.maximum_drawdown, period['maximum_drawdown'])
                compounded *= 1 + period['return']
                last_end = right
            close(compounded, 1 + summary['total_return'])
            close(sum(r['calendar_days'] for r in selected), days)
        if member['member'] == 'usdt_cash':
            assert trades.empty and (curve.equity == config.initial_equity).all()
        if member['member'] == 'btcusdt_perpetual_long_hold':
            assert len(trades) == 1 and trades.iloc[0].direction == 'long'
            assert trades.iloc[0].entry_time == config.start.isoformat() and trades.iloc[0].exit_time == config.end.isoformat()
        records.append({'scenario': scene, 'member': member['member'], 'trades': len(trades), 'equity_rows': len(curve),
                        'period_rows': len(slices), 'final_equity': summary['final_equity'], 'funding_net': summary['funding_net']})
        print(scene, member['member'], 'PASS: all trades, minute states and periods reconciled')
    return {'code': payload['code'], 'runs': [str(output)], 'members': records,
            'artifact_sha256': {str(p.relative_to(output)): sha256(p) for p in sorted(output.rglob('*')) if p.is_file()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', help='Run compare twice; verify every artifact is byte-identical')
    parser.add_argument('--run', help='Verify an existing comparison without claiming repeatability')
    parser.add_argument('--output', required=True, help='New local verification JSON')
    args = parser.parse_args()
    if bool(args.config) == bool(args.run) or Path(args.output).exists():
        parser.error('choose exactly one of --config/--run and a new output path')
    runs = [Path(args.run)] if args.run else []
    if args.config:
        for _ in range(2):
            proc = subprocess.run([sys.executable, '-m', 'qfs.cli', 'compare', '--config', args.config], capture_output=True, text=True)
            assert proc.returncode == 0, proc.stderr
            runs.append(Path(proc.stdout.strip()))
            print('compare =>', runs[-1])
        trees = [{str(p.relative_to(root)): sha256(p) for p in root.rglob('*') if p.is_file()} for root in runs]
        assert trees[0] == trees[1], 'comparison output is not deterministic'
    result = verify(runs[0])
    result['runs'] = [str(p) for p in runs]
    result['repeatability'] = '52/52 files identical' if len(runs) == 2 else 'not checked in this invocation'
    Path(args.output).write_text(json.dumps(result, sort_keys=True, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
