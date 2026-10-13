import json
from pathlib import Path

import pytest

from qfs.browse import export_html
from qfs.cli import main
from qfs.compare import run_comparison
from qfs.data import sha256
from qfs.diagnose import diagnose


def embedded(path):
    return json.loads(path.read_text().split('const DATA=', 1)[1].split(';\nconst names=', 1)[0])


def test_browse_optional_diagnostics_cli_matches_every_switch(dataset, tmp_path):
    config, _, _ = dataset(minutes=480, fee=.0005, slip=.0005)
    run = run_comparison(config)
    output = diagnose(run, tmp_path / 'diagnostic')
    html = tmp_path / 'with-diagnostics.html'
    assert main(['browse', '--run', str(run), '--output', str(html), '--diagnostics', str(output)]) == 0
    view = embedded(html)
    page = html.read_text()
    assert 'end_of_test · 终点强制平仓' in page and '终点强平' not in page
    assert '终点强制平仓是窗口处理规则' in page
    assert 'complete margin/liquidation model' in page
    records = json.loads((output / 'diagnostics.json').read_text())['records']
    assert [m['diagnostics'] for m in view['windows'][0]['members']] == records
    for member in view['windows'][0]['members']:
        assert member['diagnostics']['summary'] == member['summary']
    repeat = tmp_path / 'repeat.html'
    export_html(run, repeat, output)
    assert sha256(html) == sha256(repeat)
    plain = tmp_path / 'plain.html'
    export_html(run, plain)
    assert 'diagnostics' not in embedded(plain)
    assert 'id="diagnostics" hidden' in plain.read_text()
    assert 'fetch(' not in html.read_text() and 'src="http' not in html.read_text()
    with pytest.raises(ValueError):
        export_html(run, output / 'unsafe.html', output)


@pytest.mark.parametrize('damage', ['wrong_run', 'missing_hash', 'missing_metadata'])
def test_browse_diagnostic_failure_is_atomic(dataset, tmp_path, damage):
    config, _, _ = dataset()
    run = run_comparison(config)
    diagnosis = diagnose(run, tmp_path / 'diagnostic')
    file = diagnosis / 'diagnostics.json'
    payload = json.loads(file.read_text())
    if damage == 'wrong_run':
        payload['source_sha256']['comparison.json'] = '0' * 64
    elif damage == 'missing_hash':
        del payload['artifact_sha256']['report.md']
    else:
        del payload['diagnostic_code']
    file.write_text(json.dumps(payload))
    output = tmp_path / 'failed.html'
    assert main(['browse', '--run', str(run), '--diagnostics', str(diagnosis), '--output', str(output)]) == 1
    assert not output.exists() and not list(tmp_path.glob('.qfs-browse-*'))
