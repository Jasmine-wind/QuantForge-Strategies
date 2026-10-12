"""Study public-interface checks; synthetic fixtures are not performance evidence."""
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from qfs.data import sha256


def study_raw(config, root, count=2):
    common = config.as_dict()
    for key in ('strategy', 'start', 'end', 'data', 'data_source'):
        del common[key]
    times = pd.date_range('2020-01-01', periods=1 + 6 * count + 1, freq='MS', tz='UTC')
    months = [{'start': a.isoformat(), 'end': b.isoformat(), 'valid': i > 0,
               'errors': [] if i > 0 else ['synthetic insufficient prewarm month']}
              for i, (a, b) in enumerate(zip(times[:-1], times[1:]))]
    windows = [{'label': f'window-{i+1:02d}', 'start': times[1 + 6*i].isoformat(),
                'end': times[7 + 6*i].isoformat(), 'months': 6} for i in range(count)]
    evidence = {'mode': 'study', 'policy': {'window_months': 6, 'maximum_windows': 4,
                 'selection': 'earliest consecutive qualified UTC months, nonoverlapping; gaps reset candidates'},
                'dataset_identity_sha256': 'synthetic-fixture', 'strategy_results_used': False,
                'independent_out_of_sample': False,
                'source_coverage': {'start_utc_inclusive': times[0].isoformat(), 'end_utc_exclusive': times[-1].isoformat()},
                'months': months, 'windows': windows, 'stop_reason': 'synthetic fixture coverage exhausted'}
    path = root / 'selection.json'
    path.write_text(json.dumps(evidence))
    common['selection_evidence'] = {'path': str(path), 'sha256': sha256(path)}
    common['windows'] = [{k: v for k, v in w.items() if k != 'months'} | {
        'data': config.as_dict()['data'], 'data_source': {'description': 'synthetic correctness only',
                       'dataset_identity_sha256': 'synthetic-fixture', 'independent_out_of_sample': False}}
        for w in windows]
    return common


def test_study_config_records_shared_assumptions_and_selection(dataset, tmp_path):
    from qfs.study import StudyConfig
    config, _, _ = dataset()
    raw = study_raw(config, tmp_path)
    path = tmp_path / 'study.json'
    path.write_text(json.dumps(raw))
    study = StudyConfig.load(path)
    assert len(study.windows) == 2
    assert study.as_dict()['selection_evidence'] == raw['selection_evidence']
    for label, actual in study.windows:
        assert actual.initial_equity == 10000 and actual.position_fraction == .5
        assert actual.output_dir == config.output_dir
        assert actual.end == actual.start + pd.DateOffset(months=6)
        assert actual.strategy['name'] == 'ema'
    assert study.selection['strategy_results_used'] is False


@pytest.mark.parametrize('mutation', ['overlap', 'order', 'partial', 'five_months', 'duplicate', 'override_cost',
                                     'unknown_shared', 'evidence_hash', 'source', 'select_subset', 'evidence_policy', 'empty',
                                     'too_many', 'unsafe_label', 'quality_gap', 'strategy_selected'])
def test_study_rejects_bad_configuration_without_running(dataset, tmp_path, mutation):
    from qfs.study import StudyConfig
    config, _, _ = dataset()
    raw = study_raw(config, tmp_path)
    if mutation == 'overlap':
        raw['windows'][1].update(start=raw['windows'][0]['start'], end=raw['windows'][0]['end'])
    elif mutation == 'order':
        raw['windows'].reverse()
    elif mutation == 'partial':
        raw['windows'][0]['start'] = '2020-02-01T00:01:00Z'
    elif mutation == 'five_months':
        raw['windows'][0]['end'] = '2020-07-01T00:00:00Z'
    elif mutation == 'duplicate':
        raw['windows'][1]['label'] = raw['windows'][0]['label']
    elif mutation == 'override_cost':
        raw['windows'][1]['taker_fee_rate'] = .01
    elif mutation == 'unknown_shared':
        raw['maximum_windows'] = 5
    elif mutation == 'evidence_hash':
        raw['selection_evidence']['sha256'] = '0' * 64
    elif mutation == 'source':
        raw['windows'][1]['data_source']['dataset_identity_sha256'] = 'different'
    elif mutation == 'select_subset':
        raw['windows'] = raw['windows'][1:]
    elif mutation == 'evidence_policy':
        path = Path(raw['selection_evidence']['path'])
        evidence = json.loads(path.read_text())
        evidence['policy']['window_months'] = 5
        path.write_text(json.dumps(evidence))
        raw['selection_evidence']['sha256'] = sha256(path)
    elif mutation == 'too_many':
        raw['windows'] = raw['windows'] * 3
    elif mutation == 'unsafe_label':
        raw['windows'][0]['label'] = '../escape'
    elif mutation in {'quality_gap', 'strategy_selected'}:
        path = Path(raw['selection_evidence']['path'])
        evidence = json.loads(path.read_text())
        if mutation == 'quality_gap':
            del evidence['months'][3]
        else:
            evidence['strategy_results_used'] = True
        path.write_text(json.dumps(evidence))
        raw['selection_evidence']['sha256'] = sha256(path)
    else:
        raw['windows'] = []
    path = tmp_path / 'study.json'
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='study'):
        StudyConfig.load(path)
    assert not config.output_dir.exists()


@pytest.fixture(scope='module')
def complete_study_fixture(tmp_path_factory):
    """Two real six-month grids, fixed offline synthetic prices; no engine mocks."""
    from qfs.config import Config
    root = tmp_path_factory.mktemp('study-full-grids')
    start, end = pd.Timestamp('2020-02-01T00:00Z'), pd.Timestamp('2021-02-01T00:00Z')
    minutes = pd.date_range(start, end, freq='min', inclusive='left')
    bars = pd.date_range(start - pd.Timedelta(hours=600), end, freq='4h', inclusive='left')
    frames = {
        'bars_4h': pd.DataFrame({'open_time': bars, 'open': 100., 'high': 100., 'low': 100., 'close': 100., 'volume': 1.}),
        'trade_1m': pd.DataFrame({'open_time': minutes, 'open': 100., 'high': 100., 'low': 100., 'close': 100., 'volume': 1.}),
        'mark_1m': pd.DataFrame({'open_time': minutes, 'mark_open': 100., 'mark_high': 100., 'mark_low': 100., 'mark_close': 100.}),
        'funding': pd.DataFrame({'funding_time': pd.date_range(start, end, freq='8h'),
                                 'funding_rate': .0001, 'funding_mark_price': 100.})}
    data = {}
    for key, frame in frames.items():
        path = root / f'{key}.parquet'
        frame.to_parquet(path, index=False)
        data[key] = str(path)
    config = Config.from_dict({'strategy': {'name': 'ema'}, 'symbol': 'BTCUSDT', 'start': start, 'end': end,
                              'data': data, 'initial_equity': 10000, 'position_fraction': .5, 'maximum_leverage': 1,
                              'taker_fee_rate': .001, 'slippage_rate': .001, 'output_dir': str(root / 'runs')})
    raw = study_raw(config, root)
    path = root / 'study.json'
    path.write_text(json.dumps(raw))
    return root, path, raw


def test_full_study_cli_deterministic_and_independently_reconciled(complete_study_fixture):
    root, path, raw = complete_study_fixture
    outputs = []
    for _ in range(2):
        proc = subprocess.run([sys.executable, '-m', 'qfs.cli', 'study', '--config', str(path)],
                              text=True, capture_output=True)
        assert proc.returncode == 0, proc.stderr
        outputs.append(Path(proc.stdout.strip()))
    trees = [{str(p.relative_to(o)): sha256(p) for p in o.rglob('*') if p.is_file()} for o in outputs]
    assert trees[0] == trees[1] and len(trees[0]) == 107
    output = outputs[0]
    payload = json.loads((output / 'study.json').read_text())
    assert payload['window_count'] == 2 and payload['multiwindow_validation_available'] is True
    assert len(payload['rows']) == 24
    assert 'percentage points' in payload['return_difference_unit']
    assert not {'combined_return', 'combined_annualized', 'portfolio_equity'} & payload.keys()
    for record in payload['windows']:
        comparison = json.loads((output / record['comparison_path'] / 'comparison.json').read_text())
        for member in comparison['members']:
            summary = member['summary']
            assert summary['initial_equity'] == 10000
            row = next(r for r in payload['rows'] if r['window'] == record['label'] and r['member'] == member['member'] and r['scenario'] == member['scenario'])
            assert row['final_equity'] == summary['final_equity']
            assert row['trade_count'] == summary['trade_count']
            if member['member'] == 'usdt_cash':
                assert row['return_minus_cash_pp'] == 0
            if member['member'] == 'btcusdt_perpetual_long_hold':
                assert row['return_minus_perpetual_pp'] == 0
                trades = pd.read_csv(output / record['comparison_path'] / member['raw_report'] / 'trades.csv')
                assert trades.iloc[0].quantity * trades.iloc[0].entry_fill == pytest.approx(5000)
    verifier = Path(__file__).parents[1] / 'tools/verify_study.py'
    proc = subprocess.run([sys.executable, str(verifier), '--run', str(output), '--output', str(root / 'audit.json')],
                          text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    assert len(json.loads((root / 'audit.json').read_text())['windows']) == 2


def test_later_window_input_failure_cleans_entire_study(complete_study_fixture, tmp_path):
    root, _, raw = complete_study_fixture
    broken = json.loads(json.dumps(raw))
    broken['output_dir'] = str(tmp_path / 'failed-study-runs')
    broken['windows'][1]['data']['mark_1m'] = str(tmp_path / 'missing-mark.parquet')
    path = tmp_path / 'broken-study.json'
    path.write_text(json.dumps(broken))
    proc = subprocess.run([sys.executable, '-m', 'qfs.cli', 'study', '--config', str(path)],
                          text=True, capture_output=True)
    assert proc.returncode != 0 and 'study window-02' in proc.stderr and 'missing-mark.parquet' in proc.stderr
    assert not proc.stdout
    assert not list(Path(broken['output_dir']).iterdir())
