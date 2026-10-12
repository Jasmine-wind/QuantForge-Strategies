"""Local transport fixtures only: no CI network or real market data."""
import io
import json
from pathlib import Path
import zipfile

import pytest

from qfs import acquire as module
from qfs.cli import main
from qfs.data import sha256

START, END = '2024-03-01T00:00:00Z', '2024-04-01T00:00:00Z'


def pair(root, obj):
    path = root / module.object_path(obj['kind'], obj['month'])
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(path.stem + '.csv', 'fixed synthetic transport fixture\n')
    path.with_name(path.name + '.CHECKSUM').write_text(sha256(path) + '  ' + path.name)
    return path


def test_plan_scope_warmup_and_boundary():
    plan = module.required_objects(START, END)
    assert len(plan) == 6
    assert plan[0]['role'] == 'warmup' and plan[0]['month'] == '2024-02'
    assert [(o['kind'], o['role']) for o in plan if o['month'] == '2024-04'] == [('mark_1m', 'boundary'), ('funding', 'boundary')]
    assert not any(o['month'] == '2026-08' for o in module.required_objects('2026-07-01', '2026-08-01'))
    with pytest.raises(ValueError, match='scope'):
        module.required_objects(START, '2026-09-01')


def test_reuse_offline_cli_and_determinism(tmp_path, monkeypatch):
    raw = tmp_path / 'raw'
    for obj in module.required_objects(START, END):
        pair(raw, obj)
    def no_network(*args):
        pytest.fail('valid local cache must not download')
    monkeypatch.setattr(module, 'download', no_network)
    args = ['acquire', '--start', START, '--end', END, '--cache', str(tmp_path / 'cache'), '--reuse', str(raw), '--offline']
    for name in ('first', 'repeat'):
        assert main(args + ['--output', str(tmp_path / name)]) == 0
    assert {p.name: sha256(p) for p in (tmp_path / 'first').iterdir()} == {p.name: sha256(p) for p in (tmp_path / 'repeat').iterdir()}
    assert main(args + ['--output', str(tmp_path / 'first')]) == 1


@pytest.mark.parametrize('damage', ['zip', 'checksum', 'member', 'missing_checksum'])
def test_damaged_cache_rejected_not_overwritten(tmp_path, monkeypatch, damage):
    obj = module.required_objects(START, END)[0]
    path = pair(tmp_path / 'raw', obj)
    check = path.with_name(path.name + '.CHECKSUM')
    if damage == 'zip':
        path.write_bytes(b'fragment')
    elif damage == 'checksum':
        check.write_text('0' * 64 + ' other.zip')
    elif damage == 'missing_checksum':
        check.unlink()
    else:
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('wrong.csv', 'x')
        check.write_text(sha256(path) + ' ' + path.name)
    before = sha256(path)
    result = module.acquire(START, END, tmp_path / 'cache', tmp_path / 'out', [tmp_path / 'raw'], offline=True)
    assert len(result['failed_objects']) == 6 and not result['obtained_objects']
    assert sha256(path) == before
    assert json.loads((tmp_path / 'out/manifest.json').read_text())['archives'] == []


def test_download_publication_and_failure_cleanup(tmp_path, monkeypatch):
    raw = tmp_path / 'remote'
    for obj in module.required_objects(START, END):
        pair(raw, obj)
    def download(url, target):
        target.write_bytes((raw / url.removeprefix(module.ORIGIN)).read_bytes())
    monkeypatch.setattr(module, 'download', download)
    result = module.acquire(START, END, tmp_path / 'cache', tmp_path / 'ok')
    assert not result['failed_objects'] and len(result['obtained_objects']) == 6
    def fail(url, target):
        target.write_bytes(b'partial')
        raise ValueError('timeout fixture')
    monkeypatch.setattr(module, 'download', fail)
    result = module.acquire(START, END, tmp_path / 'failed-cache', tmp_path / 'failed')
    assert len(result['failed_objects']) == 6
    assert not list((tmp_path / 'failed-cache').rglob('*.zip'))
    assert not list(tmp_path.rglob('.qfs-download-*'))


@pytest.mark.parametrize('status,headers,body', [(206, {}, b'x'), (200, {'Content-Range': 'bytes 0-1/3'}, b'x'), (200, {'Content-Length': '3'}, b'x')])
def test_partial_responses_never_accepted(tmp_path, monkeypatch, status, headers, body):
    calls = []
    class Opener:
        def open(self, req, timeout):
            calls.append(timeout)
            stream = io.BytesIO(body)
            stream.status, stream.headers = status, headers
            return stream
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *args: Opener())
    target = tmp_path / 'partial'
    with pytest.raises(ValueError):
        module.download(module.ORIGIN + 'test', target, timeout=1)
    assert calls == [1, 1] and not target.exists()


def test_timeouts_bounded_and_successful_http_body(tmp_path, monkeypatch):
    calls = []
    class Opener:
        def open(self, req, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                raise TimeoutError('connect fixture')
            stream = io.BytesIO(b'complete')
            stream.status, stream.headers = 200, {'Content-Length': '8'}
            return stream
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *args: Opener())
    target = tmp_path / 'download'
    module.download(module.ORIGIN + 'test', target, timeout=1)
    assert calls == [1, 1] and target.read_bytes() == b'complete'
