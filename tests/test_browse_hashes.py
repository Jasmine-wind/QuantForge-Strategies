"""Hash manifests must cover the fixed report structure before HTML publication."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pandas as pd
import pytest

from qfs.compare import run_comparison
from qfs.data import sha256
from test_study import complete_study_fixture


def browse_cli(root, output):
    return subprocess.run([sys.executable, '-m', 'qfs.cli', 'browse', '--run', str(root),
                           '--output', str(output)], capture_output=True, text=True)


def test_browse_cli_rejects_unhashed_intermediate_equity(dataset, tmp_path):
    config, _, _ = dataset(minutes=8)
    root = run_comparison(config)
    path = root / 'comparison.json'
    payload = json.loads(path.read_text())
    member = payload['members'][0]
    del member['artifact_sha256']['equity.csv']
    equity_path = root / member['raw_report'] / 'equity.csv'
    curve = pd.read_csv(equity_path, float_precision='round_trip')
    curve.loc[3, 'equity'] = 1.0  # unchanged endpoints, impossible reported drawdown
    assert 1 - curve.equity.min() / curve.equity.max() > member['summary']['maximum_drawdown']
    curve.to_csv(equity_path, index=False)
    path.write_text(json.dumps(payload))
    # All still-declared hashes and all input data remain untouched and valid.
    output = tmp_path / 'failed.html'
    result = browse_cli(root, output)
    assert result.returncode != 0, 'unhashed altered curve was published'
    assert 'hash manifest' in result.stderr and 'equity.csv' in result.stderr
    assert 'hash mismatch' not in result.stderr
    assert not output.exists() and not list(tmp_path.glob('.qfs-browse-*'))


def write_copy(path, payload):
    # Study clones share immutable files for speed, never mutate source hardlinks.
    path.unlink()
    path.write_text(json.dumps(payload))


def assert_manifest_failure(root, tmp_path, detail):
    output = tmp_path / 'failed.html'
    result = browse_cli(root, output)
    assert result.returncode != 0, 'incomplete/invalid manifest was accepted'
    assert 'hash manifest' in result.stderr and detail in result.stderr, result.stderr
    assert 'hash mismatch' not in result.stderr, result.stderr
    assert not output.exists() and not list(tmp_path.glob('.qfs-browse-*'))


@pytest.mark.parametrize('level,entry', [
    ('comparison', 'comparison.csv'), ('comparison', 'periods.csv'), ('comparison', 'report.md'),
    ('member', 'summary.json'), ('member', 'trades.csv'), ('member', 'manifest.json'),
])
def test_cli_rejects_each_other_required_comparison_entry(dataset, tmp_path, level, entry):
    config, _, _ = dataset()
    root = run_comparison(config)
    path = root / 'comparison.json'
    payload = json.loads(path.read_text())
    owner = payload if level == 'comparison' else payload['members'][-1]
    del owner['artifact_sha256'][entry]
    write_copy(path, payload)
    assert_manifest_failure(root, tmp_path, entry)


@pytest.mark.parametrize('value', [{}, None, [], ['report.md'], 'not a map', 7])
def test_cli_rejects_empty_or_nonobject_hash_manifest(dataset, tmp_path, value):
    config, _, _ = dataset()
    root = run_comparison(config)
    path = root / 'comparison.json'
    payload = json.loads(path.read_text())
    payload['artifact_sha256'] = value
    write_copy(path, payload)
    assert_manifest_failure(root, tmp_path, 'comparison.csv')


@pytest.mark.parametrize('digest', [None, True, 7, '', '0' * 63, '0' * 65, 'g' * 64,
                                   'A' * 64, '0' * 63 + '\n', ['0' * 64]])
def test_cli_rejects_illegal_hash_digest_before_hashing_files(dataset, tmp_path, digest):
    config, _, _ = dataset()
    root = run_comparison(config)
    path = root / 'comparison.json'
    payload = json.loads(path.read_text())
    payload['artifact_sha256']['report.md'] = digest
    write_copy(path, payload)
    assert_manifest_failure(root, tmp_path, 'report.md')


@pytest.fixture(scope='module')
def browse_study_report(complete_study_fixture):
    """Genuine full two-window synthetic study, not a mocked execution engine."""
    from qfs.study import StudyConfig, run_study
    _, path, _ = complete_study_fixture
    return run_study(StudyConfig.load(path))


def test_study_diagnostics_stay_bound_to_every_window(browse_study_report, tmp_path):
    from qfs.browse import export_html
    from qfs.diagnose import diagnose
    from test_browse_diagnostics import embedded
    root = browse_study_report
    before = {str(p.relative_to(root)): sha256(p) for p in root.rglob('*') if p.is_file()}
    diagnostic = diagnose(root, tmp_path / 'diagnostics')
    page = tmp_path / 'study.html'
    export_html(root, page, diagnostic)
    view = embedded(page)
    assert len(view['windows']) == 2
    for w in view['windows']:
        for member in w['members']:
            d = member['diagnostics']
            assert (d['window'], d['member'], d['scenario']) == (w['label'], member['member'], member['scenario'])
            assert d['summary'] == member['summary']
            assert d['raw_report'].startswith('windows/' + w['label'] + '/')
    assert before == {str(p.relative_to(root)): sha256(p) for p in root.rglob('*') if p.is_file()}
    # Reuse this genuine, already produced study; exposure must not rerun it.
    output = tmp_path / 'exposure'
    proc = subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'tools/exposure_review.py'),
                           '--source', 'synthetic', str(root), str(diagnostic), '--output', str(output)],
                          text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    records = json.loads((output / 'exposure.json').read_text())['records']
    assert len(records) == 24
    assert [r['window'] for r in records] == ['window-01'] * 12 + ['window-02'] * 12
    for r in records:
        assert r['window_minutes'] == {'window-01': 262080, 'window-02': 264960}[r['window']]
        if r['member'] == 'btcusdt_perpetual_long_hold':
            assert r['long_minutes'] == r['window_minutes'] and r['end_of_test_count'] == 1
        else:
            assert r['flat_minutes'] == r['window_minutes'] and r['participation_rate'] == 0
    assert before == {str(p.relative_to(root)): sha256(p) for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('level,damage', [
    ('study', 'study.csv'), ('study', 'report.md'), ('study', 'nested_equity'),
    ('window', 'comparison.json'), ('window', 'comparison.csv'), ('window', 'periods.csv'),
    ('window', 'report.md'), ('window', 'nested_equity'),
    ('nested_comparison', 'periods.csv'), ('nested_member', 'equity.csv'),
    ('nested_member', 'unhashed_curve'),
    ('study', 'empty'), ('window', 'empty'), ('nested_comparison', 'empty'), ('nested_member', 'empty'),
    ('study', 'absent'), ('window', 'absent'), ('nested_comparison', 'absent'), ('nested_member', 'absent'),
    ('study', 'digest'), ('window', 'digest'), ('nested_comparison', 'digest'), ('nested_member', 'digest'),
])
def test_study_cli_rejects_each_layer_of_incomplete_hash_manifests(
        browse_study_report, tmp_path, level, damage):
    root = tmp_path / 'study'
    shutil.copytree(browse_study_report, root, copy_function=os.link)
    path = root / 'study.json'
    study = json.loads(path.read_text())
    window = study['windows'][-1]  # exercise later-window failure as well
    child = root / window['comparison_path']
    child_path = child / 'comparison.json'
    comparison = json.loads(child_path.read_text())
    member = comparison['members'][-1]
    owner = {'study': study, 'window': window, 'nested_comparison': comparison,
             'nested_member': member}[level]
    entry = 'equity.csv' if level == 'nested_member' else 'report.md'
    if damage == 'unhashed_curve':
        entry = 'equity.csv'
        del owner['artifact_sha256'][entry]
        equity_path = child / member['raw_report'] / entry
        curve = pd.read_csv(equity_path, float_precision='round_trip')
        curve.loc[3, 'equity'] = 1.0
        assert 1 - curve.equity.min() / curve.equity.max() > member['summary']['maximum_drawdown']
        equity_path.unlink()  # detach hardlink before altering only the clone
        curve.to_csv(equity_path, index=False)
        # Keep enclosing curve digests unchanged to assert that manifest
        # completeness is checked before any stale outer-file hash.
    elif damage in {'empty', 'absent', 'digest'}:
        if damage == 'empty':
            owner['artifact_sha256'] = {}
        elif damage == 'absent':
            del owner['artifact_sha256']
        else:
            owner['artifact_sha256'][entry] = 'invalid digest'
    else:
        entry = f"{member['raw_report']}/equity.csv" if damage == 'nested_equity' else damage
        if level == 'study' and damage == 'nested_equity':
            entry = f"{window['comparison_path']}/{entry}"
        del owner['artifact_sha256'][entry]
    if level in {'nested_comparison', 'nested_member'}:
        write_copy(child_path, comparison)
        # Synchronize enclosing, still-present digests so rejection cannot be
        # attributed to an old enclosing hash or to missing market data.
        window['artifact_sha256']['comparison.json'] = sha256(child_path)
        study['artifact_sha256'][f"{window['comparison_path']}/comparison.json"] = sha256(child_path)
    write_copy(path, study)
    assert_manifest_failure(root, tmp_path, entry if damage not in {'empty', 'absent'} else 'missing=')


def test_cli_exports_legal_study_without_touching_reports(browse_study_report, tmp_path):
    before = {str(p.relative_to(browse_study_report)): sha256(p)
              for p in browse_study_report.rglob('*') if p.is_file()}
    assert len(before) == 107  # two windows: 3 + 2*52; four remain 211
    one, two = tmp_path / 'one.html', tmp_path / 'two.html'
    for path in (one, two):
        result = browse_cli(browse_study_report, path)
        assert result.returncode == 0, result.stderr
    assert one.read_bytes() == two.read_bytes()
    assert not list(tmp_path.glob('.qfs-browse-*'))
    assert before == {str(p.relative_to(browse_study_report)): sha256(p)
                      for p in browse_study_report.rglob('*') if p.is_file()}
