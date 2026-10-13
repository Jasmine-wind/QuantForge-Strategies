import copy
import json
from pathlib import Path
import sys
import zipfile

import pandas as pd
import pytest

from qfs.acquire import required_objects
from qfs.data import sha256
from qfs.official import CONVERSION, SCAN_SCOPE, SCAN_START, SCAN_END, source_identity
from qfs.scan import scan
from qfs.study import StudyConfig, STUDY_POLICY, choose_study_windows

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from verify_study import selected_from_months, verify_official_link


def official_case(config, root):
    times = pd.date_range(SCAN_START, SCAN_END, freq='MS')
    rows = [{'start': a.isoformat(), 'end': b.isoformat(), 'valid': True, 'errors': []} for a, b in zip(times[:-1], times[1:])]
    sources = [o | {'sha256': 'a' * 64, 'checksum_sha256': 'b' * 64} for o in required_objects(SCAN_START, SCAN_END)]
    proof = {'mode': 'study', 'scan_version': 'qfs-official-full-scan-1', 'scan_scope': SCAN_SCOPE,
             'policy': STUDY_POLICY, 'strategy_results_used': False, 'independent_out_of_sample': False,
             'source_identity': source_identity(sources), 'source_files': sources,
             'months': rows, 'windows': choose_study_windows(rows)}
    raw = {k: v for k, v in config.as_dict().items() if k not in ('strategy', 'start', 'end', 'data', 'data_source')}
    raw['windows'] = []
    for window in proof['windows']:
        needed = {o['official_url'] for o in required_objects(window['start'], window['end'])}
        subset = [o for o in sources if o['official_url'] in needed]
        source = {'source_files': subset, 'source_identity': source_identity(subset), 'conversion': CONVERSION,
                  'independent_out_of_sample': False, 'run_coverage': {k: window[k] for k in ('start', 'end')},
                  'normalized_files': {k: {'sha256': sha256(p)} for k, p in config.data.items()}}
        raw['windows'].append({k: v for k, v in window.items() if k != 'months'} | {'data': config.as_dict()['data'], 'data_source': source})
    raw['selection_evidence'] = {'path': str(root / 'selection.json')}
    return raw, proof


def save(raw, proof):
    path = Path(raw['selection_evidence']['path'])
    path.write_text(json.dumps(proof))
    raw['selection_evidence']['sha256'] = sha256(path)


def test_official_identity_accepts_no_canonical_and_independent_association(dataset, tmp_path):
    config, _, _ = dataset()
    raw, proof = official_case(config, tmp_path)
    save(raw, proof)
    assert len(StudyConfig.from_dict(raw).windows) == 4
    assert selected_from_months(proof) == proof['windows']
    for item in raw['windows']:
        verify_official_link(item, proof)
    assert source_identity(list(reversed(proof['source_files']))) == proof['source_identity']
    moved = copy.deepcopy(proof['source_files'])
    for obj in moved:
        obj['path'] = '/another/local/root'
    assert source_identity(moved) == proof['source_identity']


@pytest.mark.parametrize('mutation', ['tail_after_four', 'missing_middle', 'shorter_scope', 'identity', 'canonical', 'merged_tail', 'nonboolean_tail'])
def test_official_full_scan_rejected_by_both_validators(dataset, tmp_path, mutation):
    config, _, _ = dataset()
    raw, proof = official_case(config, tmp_path)
    if mutation == 'tail_after_four':
        proof['months'] = proof['months'][:24]
    elif mutation == 'missing_middle':
        del proof['months'][25]
    elif mutation == 'shorter_scope':
        proof['scan_scope'] = dict(SCAN_SCOPE, end_utc_exclusive=proof['months'][23]['end'])
        proof['months'] = proof['months'][:24]
    elif mutation == 'identity':
        proof['source_identity']['sha256'] = 'c' * 64
    elif mutation == 'merged_tail':
        proof['months'][24]['end'] = proof['months'][25]['end']
        del proof['months'][25]  # still adjacent, same final end, but not one row per month
    elif mutation == 'nonboolean_tail':
        proof['months'][-1]['valid'] = 1
    else:
        proof['dataset_identity_sha256'] = 'pretend-canonical'
    save(raw, proof)
    with pytest.raises(ValueError):
        StudyConfig.from_dict(raw)
    with pytest.raises(AssertionError):
        selected_from_months(proof)


@pytest.mark.parametrize('mutation', ['object', 'boundary', 'normalized', 'coverage', 'conversion', 'identity'])
def test_official_prepared_source_mismatch_rejected_independently(dataset, tmp_path, mutation):
    config, _, _ = dataset()
    raw, proof = official_case(config, tmp_path)
    source = raw['windows'][0]['data_source']
    if mutation == 'object':
        source['source_files'][0] = dict(source['source_files'][0], sha256='c' * 64)
        source['source_identity'] = source_identity(source['source_files'])
    elif mutation == 'boundary':
        source['source_files'] = source['source_files'][:-1]
        source['source_identity'] = source_identity(source['source_files'])
    elif mutation == 'normalized':
        source['normalized_files']['funding']['sha256'] = 'c' * 64
    elif mutation == 'coverage':
        source['run_coverage']['end'] = SCAN_END
    elif mutation == 'conversion':
        source['conversion'] = 'rounded funding'
    else:
        source['source_identity']['sha256'] = 'c' * 64
    save(raw, proof)
    with pytest.raises(ValueError):
        StudyConfig.from_dict(raw)
    with pytest.raises(AssertionError):
        verify_official_link(raw['windows'][0], proof)


def month_fixture(root):
    root.mkdir()
    entries = []
    for obj in required_objects('2024-03-01', '2024-04-01'):
        kind = obj['kind']
        start = pd.Timestamp(obj['month'] + '-01', tz='UTC')
        end = start + (pd.Timedelta(minutes=1) if obj['role'] == 'boundary' else pd.DateOffset(months=1))
        times = pd.date_range(start, end, freq='8h' if kind == 'funding' else 'min', inclusive='left')
        ms = times.as_unit('ms').asi8
        if kind == 'funding':
            frame = pd.DataFrame({'calc_time': ms + 47, 'funding_interval_hours': 8, 'last_funding_rate': .0001})
        else:
            frame = pd.DataFrame({0: ms, 1: 100, 2: 100, 3: 100, 4: 100, 5: '.1', 6: ms + 59999,
                                  7: 0, 8: 1, 9: 0, 10: 0, 11: 0})
        path = root / kind / obj['official_url'].split('/')[-1]
        path.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(path.stem + '.csv', frame.to_csv(index=False, header=kind == 'funding'))
        checksum = path.with_name(path.name + '.CHECKSUM')
        checksum.write_text(sha256(path) + '  ' + path.name)
        entries.append({'kind': kind, 'path': str(path), 'checksum': str(checksum), 'official_url': obj['official_url'], 'sha256': sha256(path)})
    manifest = root / 'manifest.json'
    manifest.write_text(json.dumps({'symbol': 'BTCUSDT', 'archives': entries}))
    return manifest


def test_real_preparation_scan_records_missing_tail_and_boundary(tmp_path):
    manifest = month_fixture(tmp_path / 'raw')
    a = scan(manifest, tmp_path / 'scan.json')
    assert len(a['months']) == 29 and a['months'][0]['valid']
    assert a['months'][0]['normalized_row_counts']['funding'] == 94
    assert all(not row['valid'] for row in a['months'][1:]) and not a['windows']
    assert a['months'][-1]['start'] == '2026-07-01T00:00:00+00:00'
    scan(manifest, tmp_path / 'repeat.json')
    assert sha256(tmp_path / 'scan.json') == sha256(tmp_path / 'repeat.json')
    assert 'source_coverage' not in a and a['scan_scope'] == SCAN_SCOPE
    raw = json.loads(manifest.read_text())
    raw['archives'] = [o for o in raw['archives'] if not ('markPriceKlines' in o['official_url'] and '2024-04' in o['official_url'])]
    manifest.write_text(json.dumps(raw))
    b = scan(manifest, tmp_path / 'missing-boundary.json')
    assert not b['months'][0]['valid'] and '2024-04' in b['months'][0]['errors'][0]


def test_empty_manifest_cli_keeps_all_requested_months(tmp_path):
    from qfs.cli import main
    root = tmp_path / 'raw'
    root.mkdir()
    manifest = root / 'manifest.json'
    manifest.write_text(json.dumps({'symbol': 'BTCUSDT', 'archives': []}))
    output = tmp_path / 'scan.json'
    assert main(['scan', '--manifest', str(manifest), '--output', str(output)]) == 0
    payload = json.loads(output.read_text())
    assert len(payload['months']) == 29 and not payload['multiwindow_validation_available']
    assert selected_from_months(payload) == []
    assert main(['scan', '--manifest', str(manifest), '--output', str(output)]) == 1
    assert not list(tmp_path.glob('.qfs-scan-*'))


def test_scan_publish_failure_cleans_temporary_file(tmp_path, monkeypatch):
    import os
    root = tmp_path / 'raw'
    root.mkdir()
    manifest = root / 'manifest.json'
    manifest.write_text(json.dumps({'symbol': 'BTCUSDT', 'archives': []}))
    def fail(*args):
        raise OSError('fixture publication failure')
    monkeypatch.setattr(os, 'link', fail)
    with pytest.raises(OSError):
        scan(manifest, tmp_path / 'selection.json')
    assert not (tmp_path / 'selection.json').exists() and not list(tmp_path.glob('.qfs-scan-*'))


def test_independent_source_checks_unused_object_url(dataset, tmp_path):
    import hashlib
    config, _, _ = dataset()
    raw, proof = official_case(config, tmp_path)
    proof['source_files'][-1]['official_url'] = proof['source_files'][-1]['official_url'].replace('BTCUSDT', 'ETHUSDT')
    identity = proof['source_identity']
    identity['objects'] = sorted([{k: o[k] for k in ('kind', 'official_url', 'sha256', 'checksum_sha256')} for o in proof['source_files']], key=lambda o: (o['kind'], o['official_url']))
    identity['sha256'] = hashlib.sha256(json.dumps({k: v for k, v in identity.items() if k != 'sha256'}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    save(raw, proof)
    with pytest.raises(ValueError, match='URL'):
        StudyConfig.from_dict(raw)
    with pytest.raises(AssertionError, match='URL'):
        selected_from_months(proof)


@pytest.fixture
def official_study_fixture(dataset, tmp_path):
    """One minimum legal six-month study; synthetic provenance, never real evidence."""
    config, _, _ = dataset()
    start = pd.Timestamp(SCAN_START)
    end = start + pd.DateOffset(months=6)
    minutes = pd.date_range(start - pd.Timedelta(hours=600), end, freq='min', inclusive='left')
    bars = pd.date_range(minutes[0], end, freq='4h', inclusive='left')
    for key, times in [('trade_1m', minutes), ('bars_4h', bars), ('mark_1m', minutes[minutes >= start])]:
        prefix = 'mark_' if key == 'mark_1m' else ''
        frame = pd.DataFrame({'open_time': times, **{prefix + k: 100. for k in ('open', 'high', 'low', 'close')}})
        if not prefix:
            frame['volume'] = 1.
        frame.to_parquet(config.data[key], index=False)
    pd.DataFrame({'funding_time': pd.date_range(start, end, freq='8h') + pd.Timedelta(milliseconds=47),
                  'funding_rate': .0001, 'funding_mark_price': 100.}).to_parquet(config.data['funding'], index=False)
    raw, proof = official_case(config, tmp_path)
    for row in proof['months'][6:]:
        row.update(valid=False, errors=['synthetic fixture: remaining requested months unavailable'])
    proof['windows'] = proof['windows'][:1]
    raw['windows'] = raw['windows'][:1]
    save(raw, proof)
    path = tmp_path / 'study.json'
    path.write_text(json.dumps(raw))
    return path


def test_official_source_study_cli_and_independent_ledger_on_full_synthetic_grid(official_study_fixture, tmp_path):
    import subprocess
    path = official_study_fixture
    run = subprocess.run([sys.executable, '-m', 'qfs.cli', 'study', '--config', str(path)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    report = Path(run.stdout.strip())
    evidence = tmp_path / 'independent-audit.json'
    proc = subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'tools/verify_study.py'),
                           '--run', str(report), '--output', str(evidence)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert len(json.loads(evidence.read_text())['windows']) == 1
    assert len([p for p in report.rglob('*') if p.is_file()]) == 55


@pytest.mark.parametrize('key', ['bars_4h', 'trade_1m', 'mark_1m', 'funding'])
def test_study_rejects_normalized_replacement_after_config_validation(official_study_fixture, key):
    from qfs.study import run_study
    study = StudyConfig.load(official_study_fixture)
    config = study.windows[0][1]
    path = config.data[key]
    frame = pd.read_parquet(path)
    # Still valid schema, times, OHLC and Funding; only the source binding is bad.
    numeric = frame.select_dtypes(include='number').columns
    frame[numeric] *= 1.01
    frame.to_parquet(path, index=False)
    assert sha256(path) != config.data_source['normalized_files'][key]['sha256']
    with pytest.raises(ValueError, match='official normalized hash mismatch'):
        run_study(study)
    assert not list(config.output_dir.iterdir())


def test_study_cli_rejects_replacement_between_config_and_loading(official_study_fixture, monkeypatch, capsys):
    from qfs.cli import main
    raw = json.loads(official_study_fixture.read_text())
    output = Path(raw['output_dir'])
    output.mkdir()
    preserved = output / 'previous-evidence.txt'
    preserved.write_bytes(b'keep previous evidence')
    funding = Path(raw['windows'][0]['data']['funding'])
    original_mkdir = Path.mkdir
    changed = False

    def mkdir(path, *args, **kwargs):
        nonlocal changed
        if path == output and not changed:
            # Filesystem boundary reached only after StudyConfig.load completed.
            changed = True
            frame = pd.read_parquet(funding)
            frame['funding_rate'] = .0002
            frame.to_parquet(funding, index=False)
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'mkdir', mkdir)
    assert main(['study', '--config', str(official_study_fixture)]) == 1
    captured = capsys.readouterr()
    assert changed and not captured.out
    assert 'window-01' in captured.err and 'official normalized hash mismatch' in captured.err
    assert str(funding) in captured.err
    assert list(output.iterdir()) == [preserved]
    assert preserved.read_bytes() == b'keep previous evidence'
