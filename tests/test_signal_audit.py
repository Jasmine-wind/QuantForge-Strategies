"""Independent signal acceptance; synthetic prices are correctness fixtures only."""
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from qfs.config import Config
from qfs.data import sha256
from conftest import save
from test_study import complete_study_fixture, study_raw


TOOLS = Path(__file__).resolve().parents[1] / 'tools'


@pytest.fixture(autouse=True)
def tool_imports(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))


def comparison(dataset, tmp_path, *, reversal=False):
    config, _, _ = dataset(minutes=242 if reversal else 3, closes={150: 50} if reversal else None)
    raw = config.as_dict()
    del raw['strategy']
    path = tmp_path / 'compare.json'
    path.write_text(json.dumps(raw))
    proc = subprocess.run([sys.executable, '-m', 'qfs.cli', 'compare', '--config', str(path)],
                          text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    return Path(proc.stdout.strip())


def corrupt_trade(output, field):
    """Flat 1m prices, zero costs/Funding make these false signals ledger-consistent.

    Refresh every affected metadata copy and digest, including holding duration.
    No financial calculation or engine is substituted/mocked.
    """
    payload = json.loads((output / 'comparison.json').read_text())
    member = payload['members'][0]
    raw = output / member['raw_report']
    trades = pd.read_csv(raw / 'trades.csv', float_precision='round_trip')
    if field == 'entry_time':
        trades.loc[0, field] = (pd.Timestamp(trades.loc[0, field]) + pd.Timedelta(minutes=1)).isoformat()
    elif field == 'exit_time':
        trades.loc[0, field] = (pd.Timestamp(trades.loc[0, field]) - pd.Timedelta(minutes=1)).isoformat()
    elif field == 'direction':
        trades.loc[0, field] = 'short'
        trades.loc[0, 'signed_quantity'] *= -1
    else:
        assert field == 'exit_reason' and trades.loc[0, field] == 'reverse_signal'
        trades.loc[0, field] = 'strategy_exit'
    trades['holding_hours'] = [(pd.Timestamp(b) - pd.Timestamp(a)).total_seconds() / 3600
                              for a, b in zip(trades.entry_time, trades.exit_time)]
    trades.to_csv(raw / 'trades.csv', index=False, float_format='%.17g', lineterminator='\n')
    summary = json.loads((raw / 'summary.json').read_text())
    summary['average_holding_hours'] = float(trades.holding_hours.mean())
    (raw / 'summary.json').write_text(json.dumps(summary))
    member['summary'] = summary
    for name in ('trades.csv', 'summary.json'):
        member['artifact_sha256'][name] = sha256(raw / name)
    (output / 'comparison.json').write_text(json.dumps(payload))
    return Config.from_dict(member['config']), raw


@pytest.mark.parametrize('field', ['entry_time', 'exit_time', 'direction', 'exit_reason'])
def test_ledger_consistent_false_signal_rejected_by_public_verifier(dataset, tmp_path, field):
    from ledger import reconcile
    from qfs.browse import load_view
    output = comparison(dataset, tmp_path, reversal=field == 'exit_reason')
    config, raw = corrupt_trade(output, field)
    # Both the unchanged old Ledger Audit and full report integrity check pass.
    reconcile(config, raw)
    load_view(output)
    audit = tmp_path / 'rejected.json'
    proc = subprocess.run([sys.executable, str(TOOLS / 'verify_comparison.py'),
                           '--run', str(output), '--output', str(audit)], text=True, capture_output=True)
    assert proc.returncode != 0, proc.stdout
    assert 'Signal Audit' in proc.stderr and field in proc.stderr
    assert not audit.exists()


def schedule(config, rows):
    """Literal hand-worked minute offsets, never derived from production signals."""
    return pd.DataFrame([{'entry_time': (config.start + pd.Timedelta(minutes=a)).isoformat(),
                          'exit_time': (config.start + pd.Timedelta(minutes=b)).isoformat(),
                          'direction': direction, 'exit_reason': reason}
                         for a, b, direction, reason in rows],
                        columns=['entry_time', 'exit_time', 'direction', 'exit_reason'])


@pytest.mark.parametrize('name,minutes,closes,rows', [
    ('ema', 3, {}, [(0, 3, 'long', 'end_of_test')]),
    ('ema', 3, {148: 110}, []),  # warmup golden cross is NOT an entry
    ('ema', 3, {149: 100}, []),  # equal averages, initially Flat
    ('ema', 242, {150: 50}, [(0, 240, 'long', 'reverse_signal'), (241, 242, 'short', 'end_of_test')]),
    ('ema', 242, {149: 90, 150: 150}, [(0, 240, 'short', 'reverse_signal'), (241, 242, 'long', 'end_of_test')]),
    ('ema', 241, {150: 50}, [(0, 240, 'long', 'reverse_signal')]),  # delayed entry would equal end
    ('ema', 240, {150: 50}, [(0, 240, 'long', 'end_of_test')]),  # signal at end excluded
    ('bollinger', 3, {149: 90}, [(0, 3, 'long', 'end_of_test')]),
    ('bollinger', 3, {}, [(0, 3, 'short', 'end_of_test')]),
    ('bollinger', 3, {149: 100}, []),  # equal to the outer band is not outside
    # Last window has 90, 110, seventeen 100s, 107.6. Population upper≈107.5196;
    # sample-ddof=1 upper≈107.7051 would incorrectly suppress this entry.
    ('bollinger', 3, {135: 90, 136: 110, 149: 107.6}, [(0, 3, 'short', 'end_of_test')]),
    ('bollinger', 3, {148: 90, 149: 90}, []),  # consecutive outside closes, not a crossing
    ('bollinger', 241, {140: 110, 149: 90, 150: 100}, [(0, 240, 'long', 'strategy_exit')]),
    ('bollinger', 241, {140: 90, 150: 100}, [(0, 240, 'short', 'strategy_exit')]),
    ('bollinger', 962, {149: 90, 150: 120, 151: 120, 152: 100, 153: 120},
     [(0, 240, 'long', 'strategy_exit'), (960, 962, 'short', 'end_of_test')]),
    ('cash', 3, {}, []),
    ('btc_perpetual_long_hold', 3, {}, [(0, 3, 'long', 'end_of_test')]),
])
def test_independent_hand_worked_schedules(dataset, name, minutes, closes, rows):
    from signal_audit import audit_signals
    config, _, _ = dataset(minutes=minutes, strategy={'name': name}, closes=closes)
    member = {'ema': 'ema_20_50', 'bollinger': 'bollinger_20_2', 'cash': 'usdt_cash',
              'btc_perpetual_long_hold': 'btcusdt_perpetual_long_hold'}[name]
    trades = schedule(config, rows)
    result = audit_signals(config, trades, member=member, bars_sha256=sha256(config.data['bars_4h']))
    assert result['status'] == 'passed' and result['trade_count'] == len(rows)
    assert result['expected_trades'] == trades.to_dict('records')


def test_ema_uses_first_supplied_close_not_just_last_150_or_adjusted_weights(dataset):
    from signal_audit import audit_signals
    config, frames, _ = dataset(closes={149: 99.5})
    bars = frames['bars_4h']
    seed = bars.iloc[[0]].copy()
    seed['open_time'] -= pd.Timedelta(hours=4)
    seed[['open', 'high', 'low', 'close']] = 80.
    frames['bars_4h'] = pd.concat([seed, bars], ignore_index=True)
    save(config, frames)
    # Unadjusted EMA from the 80 seed stays fast>slow at start (~99.9524>99.9309).
    # Reseeding at 100 or using adjusted weights would instead produce a short.
    result = audit_signals(config, schedule(config, []), member='ema_20_50',
                           bars_sha256=sha256(config.data['bars_4h']))
    assert result['completed_bars'] == 151 and result['trade_count'] == 0


@pytest.mark.parametrize('fault,message', [('missing', 'trade count'), ('extra', 'trade count'),
                                         ('same_minute_reverse', 'entry_time')])
def test_ema_schedule_rejects_missing_extra_and_undelayed_reversal(dataset, fault, message):
    from signal_audit import audit_signals
    config, _, _ = dataset(minutes=242, closes={150: 50})
    rows = [(0, 240, 'long', 'reverse_signal'), (241, 242, 'short', 'end_of_test')]
    if fault == 'missing':
        rows.pop()
    elif fault == 'extra':
        rows.append(rows[-1])
    else:
        rows[1] = (240, 242, 'short', 'end_of_test')
    with pytest.raises(ValueError, match=f'Signal Audit:.*{message}'):
        audit_signals(config, schedule(config, rows), member='ema_20_50',
                      bars_sha256=sha256(config.data['bars_4h']))


@pytest.mark.parametrize('fault,message', [('early_exit', 'exit_time'), ('wrong_reason', 'exit_reason'),
                                         ('same_bar_reentry', 'trade count')])
def test_bollinger_requires_middle_cross_and_new_outer_cross_after_exit(dataset, fault, message):
    from signal_audit import audit_signals
    config, _, _ = dataset(minutes=482, strategy={'name': 'bollinger'}, closes={149: 90, 150: 90, 151: 120})
    rows = [(0, 480, 'long', 'strategy_exit')]
    if fault == 'early_exit':
        rows = [(0, 240, 'long', 'strategy_exit')]
    elif fault == 'wrong_reason':
        rows = [(0, 480, 'long', 'reverse_signal')]
    else:
        rows.append((480, 482, 'short', 'end_of_test'))
    with pytest.raises(ValueError, match=f'Signal Audit:.*{message}'):
        audit_signals(config, schedule(config, rows), member='bollinger_20_2',
                      bars_sha256=sha256(config.data['bars_4h']))


@pytest.mark.parametrize('name,member', [('ema', 'ema_20_50'), ('bollinger', 'bollinger_20_2')])
def test_unfinished_bar_is_never_a_signal(dataset, name, member):
    from signal_audit import audit_signals
    config, _, _ = dataset(strategy={'name': name}, closes={150: 1e12})
    rows = [(0, 3, 'long' if name == 'ema' else 'short', 'end_of_test')]
    result = audit_signals(config, schedule(config, rows), member=member,
                           bars_sha256=sha256(config.data['bars_4h']))
    assert result['completed_bars'] == 150


@pytest.mark.parametrize('fault,message', [('hash', 'SHA'), ('warmup', 'warmup'), ('gap', 'gap'),
                                         ('duplicate', 'unique'), ('nan', 'non-finite'), ('params', 'fixed V2')])
def test_signal_audit_fails_closed_on_wrong_inputs(dataset, fault, message):
    from signal_audit import audit_signals
    config, frames, _ = dataset()
    digest = sha256(config.data['bars_4h'])
    if fault == 'warmup':
        frames['bars_4h'] = frames['bars_4h'].iloc[1:]
    elif fault == 'gap':
        frames['bars_4h'] = frames['bars_4h'].drop(index=100)
    elif fault == 'duplicate':
        frames['bars_4h'].loc[100, 'open_time'] = frames['bars_4h'].loc[99, 'open_time']
    elif fault == 'nan':
        frames['bars_4h'].loc[100, 'close'] = float('nan')
    elif fault == 'params':
        config = Config.from_dict(config.as_dict() | {'strategy': {'name': 'ema', 'params': {'fast': 19, 'slow': 50}}})
    else:
        frames['bars_4h'].loc[100, 'close'] = 101
    save(config, frames)
    with pytest.raises(ValueError, match=f'Signal Audit:.*{message}'):
        audit_signals(config, schedule(config, [(0, 3, 'long', 'end_of_test')]), member='ema_20_50',
                      bars_sha256=digest if fault == 'hash' else sha256(config.data['bars_4h']))


def test_audit_runs_when_production_package_is_unavailable(dataset, tmp_path):
    config, _, _ = dataset()
    path = tmp_path / 'normalized.json'
    path.write_text(json.dumps(config.as_dict()))
    script = '''
import json, sys
from types import SimpleNamespace
import pandas as pd
sys.path.insert(0, sys.argv[1])
sys.modules['qfs'] = None  # production package cannot be imported at all
from signal_audit import audit_signals
raw = json.loads(open(sys.argv[2]).read())
raw['start'], raw['end'] = pd.Timestamp(raw['start']), pd.Timestamp(raw['end'])
trades = pd.DataFrame([dict(entry_time=raw['start'].isoformat(), exit_time=raw['end'].isoformat(),
                            direction='long', exit_reason='end_of_test')])
assert audit_signals(SimpleNamespace(**raw), trades, member='ema_20_50',
                     bars_sha256=sys.argv[3])['status'] == 'passed'
'''
    proc = subprocess.run([sys.executable, '-I', '-c', script, str(TOOLS), str(path),
                           sha256(config.data['bars_4h'])], cwd=tmp_path, text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr


def test_study_rejects_false_exit_reason_after_all_nested_hashes_refreshed(complete_study_fixture, tmp_path):
    from ledger import reconcile
    from qfs.browse import load_view
    _, _, template = complete_study_fixture
    first = template['windows'][0]
    common = {k: v for k, v in template.items() if k not in {'windows', 'selection_evidence'}}
    config = Config.from_dict(common | {k: v for k, v in first.items() if k != 'label'} |
                              {'strategy': {'name': 'ema'}, 'output_dir': str(tmp_path / 'runs')})
    raw = study_raw(config, tmp_path, count=1)
    # Keep the shared fixture read-only. A separate synthetic 4H copy produces
    # an EMA entry at start and a later opposite cross (zero minute-price trend).
    bars = pd.read_parquet(config.data['bars_4h'])
    bars.loc[149, ['open', 'high', 'low', 'close']] = 110.
    bar_path = tmp_path / 'signal-bars.parquet'
    bars.to_parquet(bar_path, index=False)
    raw['windows'][0]['data']['bars_4h'] = str(bar_path)
    path = tmp_path / 'study.json'
    path.write_text(json.dumps(raw))
    proc = subprocess.run([sys.executable, '-m', 'qfs.cli', 'study', '--config', str(path)],
                          text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    output = Path(proc.stdout.strip())
    payload = json.loads((output / 'study.json').read_text())
    window = payload['windows'][0]
    child = output / window['comparison_path']
    corrupt_config, report = corrupt_trade(child, 'exit_reason')
    reconcile(corrupt_config, report)
    window['artifact_sha256'] = {str(p.relative_to(child)): sha256(p) for p in child.rglob('*') if p.is_file()}
    payload['artifact_sha256'] = {str(p.relative_to(output)): sha256(p) for p in output.rglob('*')
                                  if p.is_file() and p != output / 'study.json'}
    (output / 'study.json').write_text(json.dumps(payload))
    load_view(output)  # validates BOTH nested digest layers and copied metrics
    audit = tmp_path / 'rejected-study.json'
    checked = subprocess.run([sys.executable, str(TOOLS / 'verify_study.py'), '--run', str(output), '--output', str(audit)],
                             text=True, capture_output=True)
    assert checked.returncode != 0
    assert all(s in checked.stderr for s in ('Signal Audit', 'exit_reason', 'window-01'))
    assert not audit.exists()
