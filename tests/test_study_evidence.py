"""Selection completeness at config/audit/CLI boundaries; no historical performance."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from qfs.data import sha256
from qfs.study import StudyConfig
from test_study import study_raw

# The standalone audit tool is also importable without running its CLI.
sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from verify_study import selected_from_months


def shortened_evidence(config, root):
    raw = study_raw(config, root)
    path = Path(raw['selection_evidence']['path'])
    proof = json.loads(path.read_text())
    # Keep Jan prewarm failure and Feb--Jul: a legitimate prefix, not a gap.
    # Source coverage still runs through 2021-02; synchronize everything else.
    proof['months'] = proof['months'][:7]
    proof['windows'] = proof['windows'][:1]
    proof['stop_reason'] = 'audited complete-month coverage exhausted; no shortened windows'
    path.write_text(json.dumps(proof))
    raw['windows'] = raw['windows'][:1]
    raw['selection_evidence']['sha256'] = sha256(path)
    return raw, proof


def test_config_rejects_synchronized_truncated_tail(dataset, tmp_path):
    config, _, _ = dataset()
    raw, _ = shortened_evidence(config, tmp_path)
    path = tmp_path / 'study.json'
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='incomplete.*month.*scan'):
        StudyConfig.load(path)


def test_independent_audit_rejects_synchronized_truncated_tail(dataset, tmp_path):
    config, _, _ = dataset()
    _, proof = shortened_evidence(config, tmp_path)
    with pytest.raises(AssertionError, match='incomplete.*month.*scan'):
        selected_from_months(proof)


@pytest.mark.parametrize('command', ['study', 'verify'])
def test_cli_rejects_tail_before_market_or_report_access(dataset, tmp_path, command):
    config, _, _ = dataset()
    raw, proof = shortened_evidence(config, tmp_path)
    assert sha256(raw['selection_evidence']['path']) == raw['selection_evidence']['sha256']
    if command == 'study':
        path = tmp_path / 'study.json'
        path.write_text(json.dumps(raw))
        args = ['-m', 'qfs.cli', 'study', '--config', str(path)]
    else:
        # Minimal audit envelope; completeness must fail before reading artifacts.
        root = tmp_path / 'report'
        root.mkdir()
        (root / 'study.json').write_text(json.dumps({'status': 'completed', 'config': raw,
                                                   'selection_evidence': proof}))
        args = [str(Path(__file__).parents[1] / 'tools/verify_study.py'), '--run', str(root),
                '--output', str(tmp_path / 'audit.json')]
    proc = subprocess.run([sys.executable, *args], capture_output=True, text=True)
    assert proc.returncode != 0
    assert 'incomplete complete-month scan' in proc.stderr
    assert 'hash mismatch' not in proc.stderr and 'missing required timestamp' not in proc.stderr
    assert not proc.stdout and not config.output_dir.exists()
    assert not (tmp_path / 'audit.json').exists()


@pytest.mark.parametrize('mutation', ['missing_first', 'missing_middle', 'before_funding', 'partial_tail'])
def test_scan_requires_whole_months_from_prescribed_start(dataset, tmp_path, mutation):
    config, _, _ = dataset()
    raw = study_raw(config, tmp_path, count=1)
    proof = json.loads(Path(raw['selection_evidence']['path']).read_text())
    if mutation == 'missing_first':
        proof['months'] = proof['months'][1:]
    elif mutation == 'missing_middle':
        del proof['months'][3]
    elif mutation == 'before_funding':
        proof['source_coverage']['start_utc_inclusive'] = '2019-12-01T00:00:00Z'
        proof['months'].insert(0, {'start': '2019-12-01T00:00:00+00:00',
                                   'end': '2020-01-01T00:00:00+00:00', 'valid': False, 'errors': ['outside scope']})
    else:
        proof['source_coverage']['end_utc_exclusive'] = '2020-08-20T12:00:00Z'
        proof['months'].append({'start': '2020-08-01T00:00:00+00:00',
                                 'end': '2020-09-01T00:00:00+00:00', 'valid': False, 'errors': ['partial month']})
    path = save_case(raw, proof, tmp_path)
    with pytest.raises(ValueError, match='month'):
        StudyConfig.load(path)
    with pytest.raises(AssertionError, match='month'):
        selected_from_months(proof)


def save_case(raw, proof, root):
    evidence_path = Path(raw['selection_evidence']['path'])
    evidence_path.write_text(json.dumps(proof))
    raw['selection_evidence']['sha256'] = sha256(evidence_path)
    config_path = root / 'study.json'
    config_path.write_text(json.dumps(raw))
    return config_path


@pytest.mark.parametrize('count', [1, 2, 3])
def test_complete_scan_accepts_fewer_than_four_windows(dataset, tmp_path, count):
    config, _, _ = dataset()
    raw = study_raw(config, tmp_path, count=count)
    proof = json.loads(Path(raw['selection_evidence']['path']).read_text())
    # Descriptive flags are not evidence of completion; calendar coverage is.
    proof['stop_reason'] = 'irrelevant description'
    path = save_case(raw, proof, tmp_path)
    assert len(StudyConfig.load(path).windows) == count
    assert len(selected_from_months(proof)) == count


def test_four_earliest_windows_allow_early_stop(dataset, tmp_path):
    config, _, _ = dataset()
    raw = study_raw(config, tmp_path, count=4)
    proof = json.loads(Path(raw['selection_evidence']['path']).read_text())
    proof['source_coverage'] = {'start_utc_inclusive': '2019-12-15T12:00:00Z',
                                'end_utc_exclusive': '2027-02-15T12:00:00Z'}
    proof['stop_reason'] = 'irrelevant description'
    path = save_case(raw, proof, tmp_path)
    assert len(StudyConfig.load(path).windows) == 4
    assert len(selected_from_months(proof)) == 4


@pytest.mark.parametrize('coverage_start,coverage_end,scan_start,months,invalid_month,window_start,window_end', [
    # Funding lower bound removes December; source ends in a partial August.
    ('2019-12-15T12:00:00Z', '2020-08-20T13:00:00Z', '2020-01-01', 7, '2020-01', '2020-02-01', '2020-08-01'),
    # Both source endpoints are partial months, including non-midnight times.
    ('2020-01-15T12:00:00Z', '2020-09-17T13:00:00Z', '2020-02-01', 7, '2020-08', '2020-02-01', '2020-08-01'),
    # Month start +1ns excludes January; month end -1ns excludes August.
    ('2020-01-01T00:00:00.000000001Z', '2020-08-31T23:59:59.999999999Z', '2020-02-01', 6, None, '2020-02-01', '2020-08-01'),
    # Funding upper bound excludes all August and September 2026.
    ('2026-01-15T12:00:00Z', '2026-09-20T13:00:00Z', '2026-02-01', 6, None, '2026-02-01', '2026-08-01'),
    # UTC boundaries, not the displayed local dates, determine complete months.
    ('2019-12-31T20:00:00-04:00', '2020-08-01T01:00:00+01:00', '2020-01-01', 7, '2020-01', '2020-02-01', '2020-08-01'),
])
def test_full_month_scan_intersection_boundaries(dataset, tmp_path, coverage_start, coverage_end,
                                                 scan_start, months, invalid_month, window_start, window_end):
    import pandas as pd
    config, _, _ = dataset()
    raw = study_raw(config, tmp_path, count=1)
    proof = json.loads(Path(raw['selection_evidence']['path']).read_text())
    times = pd.date_range(scan_start, periods=months + 1, freq='MS', tz='UTC')
    proof['source_coverage'] = {'start_utc_inclusive': coverage_start, 'end_utc_exclusive': coverage_end}
    proof['months'] = [{'start': a.isoformat(), 'end': b.isoformat(), 'valid': a.strftime('%Y-%m') != invalid_month,
                        'errors': ['synthetic gap'] if a.strftime('%Y-%m') == invalid_month else []}
                       for a, b in zip(times[:-1], times[1:])]
    proof['windows'][0].update(start=window_start + 'T00:00:00+00:00', end=window_end + 'T00:00:00+00:00')
    raw['windows'][0].update(start=proof['windows'][0]['start'], end=proof['windows'][0]['end'])
    path = save_case(raw, proof, tmp_path)
    assert len(StudyConfig.load(path).windows) == 1
    assert selected_from_months(proof) == proof['windows']
