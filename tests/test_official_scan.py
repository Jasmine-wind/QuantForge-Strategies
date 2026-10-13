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


@pytest.mark.parametrize('mutation', ['tail_after_four', 'missing_middle', 'shorter_scope', 'identity', 'canonical'])
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
