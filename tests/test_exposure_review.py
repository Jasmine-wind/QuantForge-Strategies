"""Read-only research on synthetic correctness fixtures, never performance evidence."""
import json
from pathlib import Path
import subprocess
import shutil
import sys

import pandas as pd
import pytest

from conftest import save
from qfs.compare import run_comparison
from qfs.data import sha256
from qfs.diagnose import diagnose


TOOLS = Path(__file__).resolve().parents[1] / 'tools'
FIELDS = ['entry_time', 'exit_time', 'direction', 'exit_reason']


@pytest.fixture(autouse=True)
def tool_imports(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))


def test_hand_partition_includes_initial_flat_reversal_gap_and_terminal_close():
    from exposure_review import exposure
    trades = pd.DataFrame([
        ('2020-01-01T00:01Z', '2020-01-01T00:03Z', 'long', 'reverse_signal'),
        ('2020-01-01T00:04Z', '2020-01-01T00:06Z', 'short', 'end_of_test'),
    ], columns=FIELDS)
    trades['holding_hours'] = 999  # reported durations are not used for the partition
    assert exposure(trades, '2020-01-01T00:00Z', '2020-01-01T00:06Z') == {
        'window_minutes': 6, 'long_minutes': 2, 'short_minutes': 2, 'flat_minutes': 2,
        'holding_minutes': 4, 'long_fraction': 1/3, 'short_fraction': 1/3,
        'flat_fraction': 1/3, 'participation_rate': 2/3,
        'long_trade_count': 1, 'short_trade_count': 1,
        'long_average_holding_hours': 1/30, 'short_average_holding_hours': 1/30,
        'end_of_test_count': 1,
    }


@pytest.fixture
def report_pair(dataset, tmp_path):
    config, frames, _ = dataset(fee=.0005, slip=.0005)
    frames['trade_1m'].loc[2, ['high', 'close']] = 100.4
    frames['mark_1m'].loc[2, ['mark_high', 'mark_close']] = 100.4
    save(config, frames)
    run = run_comparison(config)
    diagnostic = diagnose(run, tmp_path / 'diagnostics')
    return config, run, diagnostic


def cli(output, sources, *flags):
    args = [sys.executable, *flags, str(TOOLS / 'exposure_review.py')]
    for label, run, diagnostic in sources:
        args += ['--source', label, str(run), str(diagnostic)]
    return subprocess.run([*args, '--output', str(output)], cwd=output.parent, text=True, capture_output=True)


def hashes(root):
    return {str(p.relative_to(root)): sha256(p) for p in root.rglob('*') if p.is_file()}


def test_cli_copies_bound_diagnostics_partitions_every_member_and_is_deterministic(report_pair, tmp_path):
    _, run, diagnostic = report_pair
    before = hashes(run), hashes(diagnostic)
    first, repeat = tmp_path / 'first', tmp_path / 'repeat'
    for output in (first, repeat):
        proc = cli(output, [('fixture', run, diagnostic)])
        assert proc.returncode == 0, proc.stderr
        assert output.is_dir(), proc.stdout
    assert set(hashes(first)) == {'exposure.json', 'exposure.csv', 'report.md'}
    assert hashes(first) == hashes(repeat)
    payload = json.loads((first / 'exposure.json').read_text())
    assert payload['exposure_version'] == 'qfs-exposure-review-1' and payload['status'] == 'completed'
    prior = json.loads((diagnostic / 'diagnostics.json').read_text())
    rows = pd.read_csv(first / 'exposure.csv', float_precision='round_trip')
    assert list(rows.columns) == ('source window scenario member start end raw_report window_minutes long_minutes short_minutes '
        'flat_minutes holding_minutes long_fraction short_fraction flat_fraction participation_rate long_trade_count short_trade_count '
        'long_average_holding_hours short_average_holding_hours end_of_test_count initial_equity total_return maximum_drawdown '
        'trade_count net_pnl long_net_pnl short_net_pnl fees slippage_cost funding_net top5_net_pnl top5_positive_profit_share '
        'top5_total_net_share max_consecutive_losses return_minus_cash_pp return_minus_perpetual_pp cost_return_change_pp').split()
    assert len(payload['records']) == len(rows) == 12
    for csv, record in zip(rows.to_dict('records'), payload['records'], strict=True):
        for key in rows.columns:
            assert pd.isna(csv[key]) if record[key] is None else csv[key] == record[key]
    assert payload['overlaps'] == []
    assert payload['sources'][0]['report_sha256'] == before[0]
    assert payload['sources'][0]['diagnostics_sha256'] == before[1]
    for row, original in zip(payload['records'], prior['records'], strict=True):
        assert row['diagnostic_record'] == original
        assert row['total_return'] == original['summary']['total_return']
        assert row['long_net_pnl'] == original['directions']['long']['net_pnl']
        assert row['top5_positive_profit_share'] == original['top5_positive_profit_share']
        assert row['cost_return_change_pp'] == original['cost_change_from_base']['return_pp']
        assert row['return_minus_perpetual_pp'] == original['return_minus_perpetual_pp']
        assert row['long_minutes'] + row['short_minutes'] + row['flat_minutes'] == row['window_minutes'] == 3
        if row['member'] == 'usdt_cash':
            assert row['flat_minutes'] == 3 and row['participation_rate'] == 0
            assert row['long_average_holding_hours'] is None
        elif row['member'] == 'bollinger_20_2':
            assert row['short_minutes'] == 3 and row['end_of_test_count'] == 1
        else:
            assert row['long_minutes'] == 3 and row['participation_rate'] == 1
    assert {name: sha256(first / name) for name in ('exposure.csv', 'report.md')} == payload['artifact_sha256']
    text = (first / 'report.md').read_text()
    assert all(word in text for word in ('不是独立OOS', '不是历史绩效', 'synthetic correctness fixture', '因果', '空仓', '终点', '滑点', 'n/a', '由正变为非正'))
    assert before == (hashes(run), hashes(diagnostic))


@pytest.mark.parametrize('start,end,positions,expected', [
    ('2020-01-01T00:00Z', '2020-01-01T00:06Z', [(0, 2, 'long', 'strategy_exit'), (2, 6, 'short', 'end_of_test')], (2, 4, 0, 1, 1, 1)),
    ('2020-01-31T23:58Z', '2020-02-01T00:04Z', [(1, 4, 'long', 'strategy_exit'), (4, 5, 'short', 'strategy_exit')], (3, 1, 2, 1, 1, 0)),
    ('2020-01-01T00:00Z', '2020-01-01T00:06Z', [], (0, 0, 6, 0, 0, 0)),
    ('2020-01-01T00:00Z', '2020-01-01T00:06Z', [(0, 6, 'long', 'end_of_test')], (6, 0, 0, 1, 0, 1)),
    ('2020-01-01T00:00Z', '2020-01-01T00:06Z', [(0, 2, 'long', 'strategy_exit'), (3, 5, 'long', 'strategy_exit')], (4, 0, 2, 2, 0, 0)),
    ('2020-01-01T08:00+08:00', '2020-01-01T08:06+08:00', [(0, 6, 'short', 'end_of_test')], (0, 6, 0, 0, 1, 1)),
])
def test_hand_adjacent_cross_month_empty_terminal_and_direction_averages(start, end, positions, expected):
    from exposure_review import exposure
    trades = pd.DataFrame([(pd.Timestamp(start) + pd.Timedelta(minutes=a), pd.Timestamp(start) + pd.Timedelta(minutes=b), s, r)
                           for a, b, s, r in positions], columns=FIELDS)
    result = exposure(trades, start, end)
    assert tuple(result[k] for k in ('long_minutes', 'short_minutes', 'flat_minutes', 'long_trade_count',
                                     'short_trade_count', 'end_of_test_count')) == expected
    assert result['window_minutes'] == 6
    assert sum(result[k] for k in ('long_fraction', 'short_fraction', 'flat_fraction')) == pytest.approx(1)
    for i, side in enumerate(('long', 'short')):
        average = result[side + '_average_holding_hours']
        assert average is None if not expected[i + 3] else average == pytest.approx(expected[i] / expected[i + 3] / 60)


@pytest.mark.parametrize('damage', ['overlap', 'duplicate', 'order', 'before_start', 'after_end', 'zero', 'negative',
                                   'direction', 'reason', 'early_terminal', 'missing_terminal', 'timestamp', 'numeric', 'nat', 'subminute'])
def test_partition_refuses_invalid_trades_without_sorting_or_clipping(damage):
    from exposure_review import exposure
    trades = pd.DataFrame([('2020-01-01T00:00Z', '2020-01-01T00:02Z', 'long', 'strategy_exit'),
                           ('2020-01-01T00:03Z', '2020-01-01T00:06Z', 'short', 'end_of_test')], columns=FIELDS, dtype=object)
    if damage == 'overlap':
        trades.loc[1, 'entry_time'] = '2020-01-01T00:01Z'
    elif damage == 'duplicate':
        trades.iloc[1] = trades.iloc[0]
    elif damage == 'order':
        trades = trades.iloc[::-1]
    elif damage == 'before_start':
        trades.loc[0, 'entry_time'] = '2019-12-31T23:59Z'
    elif damage == 'after_end':
        trades.loc[1, 'exit_time'] = '2020-01-01T00:07Z'
    elif damage in {'zero', 'negative'}:
        trades.loc[0, 'exit_time'] = '2020-01-01T00:00Z' if damage == 'zero' else '2019-12-31T23:59Z'
    elif damage == 'direction':
        trades.loc[0, 'direction'] = 'flat'
    elif damage == 'reason':
        trades.loc[0, 'exit_reason'] = 'unknown'
    elif damage == 'early_terminal':
        trades.loc[0, 'exit_reason'] = 'end_of_test'
    elif damage == 'missing_terminal':
        trades.loc[1, 'exit_reason'] = 'strategy_exit'
    else:
        trades.loc[0, 'entry_time'] = {'timestamp': 'bad', 'numeric': 1577836800000, 'nat': pd.NaT,
                                      'subminute': '2020-01-01T00:00:00.047Z'}[damage]
    with pytest.raises(ValueError, match='exposure:'):
        exposure(trades, '2020-01-01T00:00Z', '2020-01-01T00:06Z')


@pytest.mark.parametrize('start,end', [('2020-01-01', '2020-01-01'), ('2020-01-02', '2020-01-01'),
                                     ('NaT', '2020-01-01'), ('2020-01-01', '2020-01-01T00:01:01Z')])
def test_invalid_window_is_not_reported_as_empty_valid_exposure(start, end):
    from exposure_review import exposure
    with pytest.raises(ValueError, match='exposure:'):
        exposure(pd.DataFrame(columns=FIELDS), start, end)


def test_missing_columns_are_not_treated_as_a_valid_cash_report():
    from exposure_review import exposure
    with pytest.raises(ValueError, match='complete trade time fields'):
        exposure(pd.DataFrame(), '2020-01-01T00:00Z', '2020-01-01T00:06Z')


@pytest.mark.parametrize('damage', ['source_hash', 'missing_file', 'hash_inventory', 'record', 'csv',
                                   'report_inventory', 'report_hash', 'extra_file'])
def test_cli_rejects_incomplete_or_mismatched_sources(report_pair, tmp_path, damage):
    _, run, diagnostic = report_pair
    path = diagnostic / 'diagnostics.json'
    payload = json.loads(path.read_text())
    if damage == 'source_hash':
        payload['source_sha256']['comparison.json'] = '0' * 64
    elif damage == 'missing_file':
        (diagnostic / 'report.md').unlink()
    elif damage == 'hash_inventory':
        del payload['artifact_sha256']['diagnostics.csv']
    elif damage == 'record':
        payload['records'][0]['directions']['long']['net_pnl'] += 1
    elif damage == 'csv':
        csv = diagnostic / 'diagnostics.csv'
        csv.write_text(csv.read_text() + '\n')
        payload['artifact_sha256']['diagnostics.csv'] = sha256(csv)  # semantic failure, not stale SHA
    elif damage == 'report_inventory':
        target = run / 'comparison.json'
        report = json.loads(target.read_text())
        del report['members'][0]['artifact_sha256']['trades.csv']
        target.write_text(json.dumps(report))
    elif damage == 'report_hash':
        target = run / 'reports/base/ema_20_50/trades.csv'
        target.write_text(target.read_text() + '\n')
    else:
        (diagnostic / 'extra.json').write_text('{}')
    path.write_text(json.dumps(payload))
    before = hashes(run), hashes(diagnostic)
    output = tmp_path / 'rejected'
    proc = cli(output, [('fixture', run, diagnostic)])
    assert proc.returncode != 0 and 'exposure review' in proc.stderr
    assert not output.exists() and not list(tmp_path.glob('.qfs-exposure-*'))
    assert before == (hashes(run), hashes(diagnostic))


@pytest.mark.parametrize('destination', ['report_child', 'diagnostic_child', 'existing', 'dangling_symlink'])
def test_cli_protects_sources_existing_output_and_symlinks(report_pair, tmp_path, destination):
    _, run, diagnostic = report_pair
    output = tmp_path / 'review'
    if destination == 'report_child':
        output = run / 'review'
    elif destination == 'diagnostic_child':
        output = diagnostic / 'review'
    elif destination == 'existing':
        output.mkdir()
        (output / 'keep').write_text('keep')
    else:
        output.symlink_to(tmp_path / 'missing-target')
    before = hashes(run), hashes(diagnostic)
    proc = cli(output, [('fixture', run, diagnostic)])
    assert proc.returncode != 0
    assert before == (hashes(run), hashes(diagnostic))
    if destination == 'existing':
        assert (output / 'keep').read_text() == 'keep'
    elif destination == 'dangling_symlink':
        assert output.is_symlink() and not (tmp_path / 'missing-target').exists()
    else:
        assert not output.exists()


@pytest.mark.parametrize('damage', ['label', 'path', 'copy', 'unsafe_label'])
def test_duplicate_sources_are_not_counted_as_more_evidence(report_pair, tmp_path, damage):
    _, run, diagnostic = report_pair
    sources = [('fixture', run, diagnostic)]
    if damage == 'copy':
        copied = tmp_path / 'copied-report'
        shutil.copytree(run, copied)
        sources.append(('copy', copied, diagnostic))
    elif damage == 'unsafe_label':
        sources[0] = ('bad|label', run, diagnostic)
    else:
        sources.append(('fixture' if damage == 'label' else 'second', run, diagnostic))
    output = tmp_path / 'rejected'
    proc = cli(output, sources)
    assert proc.returncode != 0 and ('duplicate' in proc.stderr or 'invalid' in proc.stderr)
    assert not output.exists()


def test_multiple_sources_keep_all_groups_and_disclose_overlap_without_market_files(report_pair, tmp_path):
    from qfs.config import Config
    config, run, diagnostic = report_pair
    other = run_comparison(Config.from_dict(config.as_dict() | {'taker_fee_rate': .0007, 'output_dir': str(tmp_path / 'other-runs')}))
    other_diagnostic = diagnose(other, tmp_path / 'other-diagnostic')
    # Analysis must need only the immutable reports/diagnostics, not the original
    # market inputs or a signal/account rerun. Remove ONLY synthetic fixture data.
    for path in config.data.values():
        Path(path).unlink()
    output = tmp_path / 'combined'
    proc = cli(output, [('one', run, diagnostic), ('two', other, other_diagnostic)])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((output / 'exposure.json').read_text())
    assert [r['source'] for r in payload['records']] == ['one'] * 12 + ['two'] * 12
    assert len(payload['overlaps']) == 1
    assert payload['overlaps'][0]['start'] == config.start.isoformat()
    assert payload['overlaps'][0]['end'] == config.end.isoformat()
    assert '不能作为新增独立样本' in (output / 'report.md').read_text()


@pytest.mark.parametrize('damage', ['report_change', 'diagnostic_change', 'appearing_target', 'disk_error'])
def test_public_review_cleans_staging_after_filesystem_fault(report_pair, tmp_path, monkeypatch, damage):
    from exposure_review import review
    _, run, diagnostic = report_pair
    output = tmp_path / 'failed'
    original_write = Path.write_text
    def write_then_fault(path, *args, **kwargs):
        result = original_write(path, *args, **kwargs)
        if path.name == 'report.md' and path.parent.name.startswith('.qfs-exposure-'):
            # Actual filesystem mutations after source reads; no mocked engine,
            # financial result or integrity check.
            if damage == 'report_change':
                original_write(run / 'report.md', 'external modification')
            elif damage == 'diagnostic_change':
                original_write(diagnostic / 'report.md', 'external modification')
            elif damage == 'appearing_target':
                output.mkdir()
                original_write(output / 'keep', 'concurrent evidence')
            else:
                raise OSError('fixture disk full')
        return result
    monkeypatch.setattr(Path, 'write_text', write_then_fault)
    with pytest.raises((ValueError, OSError), match='changed|appeared|disk full'):
        review([('fixture', run, diagnostic)], output)
    assert not list(tmp_path.glob('.qfs-exposure-*'))
    if damage == 'appearing_target':
        assert sorted(p.name for p in output.iterdir()) == ['keep']
        assert (output / 'keep').read_text() == 'concurrent evidence'
    else:
        assert not output.exists()


def test_time_calculation_binds_the_exact_read_snapshot_even_if_source_restored(report_pair, tmp_path, monkeypatch):
    from exposure_review import review
    _, run, diagnostic = report_pair
    target = run / 'reports/base/ema_20_50/trades.csv'
    original_read = Path.read_bytes
    original = original_read(target)
    changed = original.replace(b'2020-01-26T00:00:00+00:00', b'2020-01-26T00:01:00+00:00', 1)
    assert changed != original
    def read_during_replacement(path):
        if path == target:
            # Real filesystem replace/read/restore at the I/O boundary. A final
            # tree hash alone cannot bind the bytes actually used for duration.
            path.write_bytes(changed)
            try:
                return original_read(path)
            finally:
                path.write_bytes(original)
        return original_read(path)
    monkeypatch.setattr(Path, 'read_bytes', read_during_replacement)
    output = tmp_path / 'rejected'
    with pytest.raises(ValueError, match='trade snapshot changed'):
        review([('fixture', run, diagnostic)], output)
    assert not output.exists() and original_read(target) == original


@pytest.mark.parametrize('iterator', [False, True])
def test_empty_source_iterable_cannot_publish_success(tmp_path, iterator):
    from exposure_review import review
    output = tmp_path / 'empty'
    with pytest.raises(ValueError, match='require sources'):
        review(iter([]) if iterator else [], output)
    assert not output.exists() and not list(tmp_path.glob('.qfs-exposure-*'))


def test_zero_duration_with_refreshed_metadata_and_diagnosis_is_rejected(report_pair, tmp_path):
    _, run, _ = report_pair
    payload = json.loads((run / 'comparison.json').read_text())
    member = payload['members'][0]
    raw = run / member['raw_report']
    trades = pd.read_csv(raw / 'trades.csv', float_precision='round_trip')
    trades.loc[0, 'entry_time'] = trades.loc[0, 'exit_time']
    trades.loc[0, 'holding_hours'] = 0.
    trades.to_csv(raw / 'trades.csv', index=False, float_format='%.17g', lineterminator='\n')
    summary = json.loads((raw / 'summary.json').read_text())
    summary['average_holding_hours'] = 0.
    (raw / 'summary.json').write_text(json.dumps(summary))
    member['summary'] = summary
    for name in ('trades.csv', 'summary.json'):
        member['artifact_sha256'][name] = sha256(raw / name)
    (run / 'comparison.json').write_text(json.dumps(payload))
    # The existing grouping verifier permits equal entry/exit. Its complete
    # source-bound diagnosis is valid, but the new interval contract is not.
    diagnostic = diagnose(run, tmp_path / 'refreshed-diagnosis')
    output = tmp_path / 'rejected'
    proc = cli(output, [('fixture', run, diagnostic)], '-O')
    assert proc.returncode != 0 and 'non-positive duration' in proc.stderr
    assert not output.exists()
