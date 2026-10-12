"""Offline report browsing must preserve exact results and original artifacts."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from qfs.compare import run_comparison
from qfs.data import sha256


def test_offline_browser_matches_all_report_switches_and_is_deterministic(dataset, tmp_path):
    from qfs.browse import export_html, load_view
    config, _, _ = dataset(minutes=480, fee=.0005, slip=.0005)
    root = run_comparison(config)
    before = {str(p.relative_to(root)): sha256(p) for p in root.rglob('*') if p.is_file()}
    data = load_view(root)
    original = json.loads((root / 'comparison.json').read_text())
    assert len(data['windows']) == 1 and len(data['windows'][0]['members']) == 12
    for item, member in zip(data['windows'][0]['members'], original['members']):
        assert item['summary'] == member['summary']
        assert item['member'] == member['member'] and item['scenario'] == member['scenario']
        assert item['periods'] == [p for p in original['periods'] if p['member'] == item['member'] and p['scenario'] == item['scenario']]
        assert item['samples'][0][1] == 10000
        assert item['samples'][-1][1] == member['summary']['final_equity']
    a, b = tmp_path / 'one.html', tmp_path / 'two.html'
    export_html(root, a)
    export_html(root, b)
    assert a.read_bytes() == b.read_bytes()
    page = a.read_text()
    assert '<select id="window"' in page and '<select id="scenario"' in page and '<select id="member"' in page
    assert '百分点' in page and '不等同独立核账' in page and '已见历史' in page
    assert 'src="http' not in page and 'fetch(' not in page
    assert before == {str(p.relative_to(root)): sha256(p) for p in root.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):
        export_html(root, a)
    with pytest.raises(ValueError):
        export_html(root, root / 'page.html')


@pytest.mark.parametrize('damage', ['artifact', 'csv_copy', 'summary_copy', 'members', 'unsafe_path', 'empty_curve'])
def test_browse_rejects_bad_reports_without_publishing(dataset, tmp_path, damage):
    import pandas as pd
    from qfs.browse import export_html
    config, _, _ = dataset()
    root = run_comparison(config)
    payload = json.loads((root / 'comparison.json').read_text())
    m = payload['members'][0]
    if damage in {'artifact', 'csv_copy'}:
        path = root / 'comparison.csv'
        frame = pd.read_csv(path)
        frame.loc[0, 'final_equity'] = 999
        frame.to_csv(path, index=False)
        if damage == 'csv_copy':
            payload['artifact_sha256']['comparison.csv'] = sha256(path)
    elif damage == 'summary_copy':
        m['summary']['final_equity'] = 999
    elif damage == 'members':
        payload['members'].pop()
    elif damage == 'unsafe_path':
        payload['artifact_sha256']['../escaped.txt'] = '0' * 64
    else:
        path = root / m['raw_report'] / 'equity.csv'
        pd.DataFrame(columns=['time', 'equity']).to_csv(path, index=False)
        m['artifact_sha256']['equity.csv'] = sha256(path)
    (root / 'comparison.json').write_text(json.dumps(payload))
    output = tmp_path / 'failed.html'
    with pytest.raises(ValueError):
        export_html(root, output)
    assert not output.exists() and not list(tmp_path.glob('.qfs-browse-*'))


def test_chart_sampling_keeps_full_curve_extremes():
    import pandas as pd
    from qfs.browse import display_samples
    curve = pd.DataFrame({'time': pd.date_range('2020-02-01', periods=10000, freq='min', tz='UTC').map(str),
                          'equity': 100.0})
    curve.loc[5000, 'equity'] = 40
    curve.loc[8000, 'equity'] = 200
    curve.loc[9000, 'equity'] = 40
    samples = display_samples(curve, buckets=10)
    assert len(samples) <= 60
    assert min(s[1] for s in samples) == 40 and max(s[1] for s in samples) == 200
    assert max(s[2] for s in samples) == .8
    assert samples[0][0] == curve.time.iloc[0] and samples[-1][0] == curve.time.iloc[-1]


def test_html_escaping_cli_and_exclusive_publish_cleanup(dataset, tmp_path, monkeypatch):
    import os
    from qfs.browse import export_html
    config, _, _ = dataset()
    root = run_comparison(config)
    payload = json.loads((root / 'comparison.json').read_text())
    attack = '</script><img src=x onerror=alert(1)>'
    payload['limitations'].append(attack)
    (root / 'comparison.json').write_text(json.dumps(payload))
    output = tmp_path / 'browser.html'
    proc = subprocess.run([sys.executable, '-m', 'qfs.cli', 'browse', '--run', str(root), '--output', str(output)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert '\\u003c/script>' in output.read_text() and attack not in output.read_text()
    def fail(*args):
        raise OSError('publish denied')
    monkeypatch.setattr(os, 'link', fail)
    with pytest.raises(OSError, match='publish denied'):
        export_html(root, tmp_path / 'failed.html')
    assert not (tmp_path / 'failed.html').exists() and not list(tmp_path.glob('.qfs-browse-*'))
