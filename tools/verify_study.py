"""Independent study audit; reuse the report ledger verifier, never the engine."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from qfs.data import sha256
from ledger import close
from verify_comparison import verify as verify_comparison


def selected_from_months(proof):
    # Independent fixed-rule replay; do not import the production selector/study.
    assert proof['mode'] == 'study' and proof['strategy_results_used'] is False
    assert proof['independent_out_of_sample'] is False
    assert proof['policy'] == {'window_months': 6, 'maximum_windows': 4,
           'selection': 'earliest consecutive qualified UTC months, nonoverlapping; gaps reset candidates'}
    windows, block = [], []
    previous = None
    for row in proof['months']:
        a, b = pd.Timestamp(row['start']), pd.Timestamp(row['end'])
        assert a == a.normalize().replace(day=1) and b == a + pd.DateOffset(months=1)
        if previous is not None:
            assert a == previous
        previous = b
        assert type(row['valid']) is bool and row['valid'] == (not row['errors'])
        if not row['valid']:
            block = []
            continue
        block.append((a, b))
        if len(block) == 6:
            windows.append({'label': f'window-{len(windows)+1:02d}', 'start': block[0][0].isoformat(),
                            'end': block[-1][1].isoformat(), 'months': 6})
            block = []
            if len(windows) == 4:
                break
    assert windows == proof['windows']
    return windows


def verify(output):
    payload = json.loads((output / 'study.json').read_text())
    assert payload['status'] == 'completed'
    config = payload['config']
    proof_info = config['selection_evidence']
    assert sha256(proof_info['path']) == proof_info['sha256']
    proof = json.loads(Path(proof_info['path']).read_text())
    assert proof == payload['selection_evidence']
    selected = selected_from_months(proof)
    assert len(payload['windows']) == len(config['windows']) == payload['window_count'] == len(selected)
    assert payload['multiwindow_validation_available'] == (len(selected) >= 2)
    assert payload['policy'] == proof['policy']
    full = pd.read_csv(output / 'study.csv', float_precision='round_trip')
    assert len(full) == len(payload['rows']) == 12 * len(selected)
    actual_hashes = {str(p.relative_to(output)): sha256(p) for p in output.rglob('*') if p.is_file() and p != output / 'study.json'}
    assert actual_hashes == payload['artifact_sha256']
    assert len(actual_hashes) == 2 + 52 * len(selected)
    all_records, expected_order = [], []
    for window, item, expected in zip(payload['windows'], config['windows'], selected):
        for key in ('label', 'start', 'end'):
            assert window[key] == item[key] == expected[key]
        relative = f"windows/{window['label']}"
        assert window['comparison_path'] == relative
        root = output / relative
        checked = verify_comparison(root)  # all trades/minutes/periods/annualized-null checks
        assert checked['artifact_sha256'] == window['artifact_sha256']
        comparison = json.loads((root / 'comparison.json').read_text())
        assert comparison['code'] == payload['code'] and comparison['runtime'] == payload['runtime']
        shared = comparison['shared_config']
        assert comparison['data_files'] == window['data_files']
        for key in ('symbol', 'initial_equity', 'position_fraction', 'maximum_leverage', 'taker_fee_rate', 'slippage_rate', 'output_dir'):
            assert shared[key] == config[key]
        for key in ('start', 'end', 'data', 'data_source'):
            assert shared[key] == item[key]
        assert shared['data_source']['dataset_identity_sha256'] == proof['dataset_identity_sha256']
        lookup = {(m['scenario'], m['member']): m['summary'] for m in comparison['members']}
        rows = [r for r in payload['rows'] if r['window'] == window['label']]
        assert len(rows) == 12
        for row, member in zip(rows, comparison['members']):
            scene, name = member['scenario'], member['member']
            expected_order.append((window['label'], scene, name))
            assert row['scenario'] == scene and row['member'] == name and row['comparison_path'] == relative
            assert row['start'] == shared['start'] and row['end'] == shared['end']
            summary = member['summary']
            assert summary['initial_equity'] == config['initial_equity']
            csv = full[(full.window == window['label']) & (full.scenario == scene) & (full.member == name)].iloc[0]
            for key in ('initial_equity', 'final_equity', 'net_pnl', 'total_return', 'annualized_return', 'maximum_drawdown',
                        'sharpe', 'sharpe_daily_returns', 'calendar_days', 'trade_count', 'gross_pnl', 'fees', 'slippage_cost', 'funding_net'):
                if summary[key] is None:
                    assert row[key] is None and pd.isna(csv[key])
                else:
                    close(row[key], summary[key])
                    close(csv[key], summary[key])
            for key, benchmark in (('return_minus_cash_pp', 'usdt_cash'), ('return_minus_perpetual_pp', 'btcusdt_perpetual_long_hold')):
                expected_pp = 100 * (summary['total_return'] - lookup[(scene, benchmark)]['total_return'])
                close(row[key], expected_pp)
                close(csv[key], expected_pp)
        all_records.append({'window': window['label'], 'comparison': checked})
    assert list(zip(full.window, full.scenario, full.member)) == expected_order
    assert [(r['window'], r['scenario'], r['member']) for r in payload['rows']] == expected_order
    return {'code': payload['code'], 'runs': [str(output)], 'windows': all_records,
            'selection_sha256': proof_info['sha256'],
            'artifact_sha256': {str(p.relative_to(output)): sha256(p) for p in output.rglob('*') if p.is_file()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', help='Run the study twice and compare every artifact')
    parser.add_argument('--run', help='Verify existing study, without a repeatability claim')
    parser.add_argument('--output', required=True, help='New evidence JSON')
    args = parser.parse_args()
    if bool(args.config) == bool(args.run) or Path(args.output).exists():
        parser.error('choose exactly one config/run and a new output path')
    runs = [Path(args.run)] if args.run else []
    if args.config:
        for _ in range(2):
            proc = subprocess.run([sys.executable, '-m', 'qfs.cli', 'study', '--config', args.config], capture_output=True, text=True)
            assert proc.returncode == 0, proc.stderr
            runs.append(Path(proc.stdout.strip()))
            print('study =>', runs[-1], flush=True)
        trees = [{str(p.relative_to(root)): sha256(p) for p in root.rglob('*') if p.is_file()} for root in runs]
        assert trees[0] == trees[1], 'study artifacts are not deterministic'
    evidence = verify(runs[0])
    evidence['runs'] = [str(p) for p in runs]
    evidence['repeatability'] = f"{len(evidence['artifact_sha256'])} files identical" if len(runs) == 2 else 'not checked in this invocation'
    with Path(args.output).open('x', encoding='utf-8') as f:
        json.dump(evidence, f, sort_keys=True, indent=2)
        f.write('\n')
    print('PASS: all windows, members, ledgers, periods, top metrics and percentage-point differences', flush=True)


if __name__ == '__main__':
    main()
