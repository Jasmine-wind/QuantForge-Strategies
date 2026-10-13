"""Real loopback HTTP: wall deadlines must cancel the transport, not just a waiter."""
from contextlib import contextmanager
import socketserver
import threading
import time

import pytest

from qfs.acquire import download


@contextmanager
def local_http(responses):
    """A finite scripted peer; records client disconnects before fixture teardown."""
    stop = threading.Event()
    requests = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(2)
            while self.rfile.readline().strip():
                pass
            record = {'disconnected': threading.Event(), 'completed': False, 'bytes_sent': 0}
            index = len(requests)
            requests.append(record)
            response = responses[min(index, len(responses) - 1)]
            status, body = response.get('status', 200), response.get('body', b'ok')
            headers = {'Content-Length': str(len(body)), 'Connection': 'close', **response.get('headers', {})}
            if response.get('header_delay'):
                headers['X-Drip'] = 'a' * 350
            head = (f'HTTP/1.1 {status} Fixture\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in headers.items()) + '\r\n').encode()
            try:
                if stop.wait(response.get('first_byte_delay', 0)):
                    return
                for content, delay in ((head, response.get('header_delay', 0)), (body, response.get('body_delay', 0))):
                    chunks = (bytes([b]) for b in content) if delay else (content,)
                    for block in chunks:
                        if stop.is_set():
                            return
                        self.connection.sendall(block)
                        record['bytes_sent'] += len(block)
                        if delay and stop.wait(delay):
                            return
                record['completed'] = True
            except (BrokenPipeError, ConnectionResetError):
                record['disconnected'].set()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = False

    with Server(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_address[1]}/fixture', requests
        finally:
            stop.set()
            server.shutdown()
            thread.join()


def test_slow_response_headers_deadline_actually_disconnects(tmp_path, monkeypatch):
    monkeypatch.setenv('NO_PROXY', '127.0.0.1')
    target = tmp_path / 'download'
    with local_http([{'header_delay': .005}]) as (url, requests):
        started = time.monotonic()
        with pytest.raises(ValueError, match='deadline'):
            download(url, target, timeout=.2, attempts=1)  # .8s total vs >2s headers
        elapsed = time.monotonic() - started
        assert elapsed < 1.4, f'transfer waited past budget and scheduling allowance: {elapsed}'
        assert len(requests) == 1
        assert requests[0]['disconnected'].wait(.5), 'deadline left the HTTP request running'
        assert not requests[0]['completed'] and not target.exists()


def test_body_drip_deadline_actually_disconnects(tmp_path, monkeypatch):
    monkeypatch.setenv('NO_PROXY', '127.0.0.1')
    target = tmp_path / 'download'
    with local_http([{'body': b'a' * 500, 'body_delay': .005}]) as (url, requests):
        started = time.monotonic()
        with pytest.raises(ValueError, match='deadline'):
            download(url, target, timeout=.2, attempts=1)
        assert time.monotonic() - started < 1.4
        assert len(requests) == 1 and requests[0]['disconnected'].wait(.5)
        assert not requests[0]['completed'] and not target.exists()


@pytest.mark.parametrize('response', [{'header_delay': .005}, {'body': b'a' * 500, 'body_delay': .005}])
def test_deadline_retry_budget_is_finite_and_every_request_is_closed(tmp_path, monkeypatch, response):
    monkeypatch.setenv('NO_PROXY', '127.0.0.1')
    target = tmp_path / 'download'
    with local_http([response]) as (url, requests):
        started = time.monotonic()
        with pytest.raises(ValueError, match='deadline.*attempt 2/2'):
            download(url, target, timeout=.2)
        assert time.monotonic() - started < 2.5
        assert len(requests) == 2
        assert all(r['disconnected'].wait(.5) and not r['completed'] for r in requests)
        assert not target.exists()


def test_headers_and_body_share_one_attempt_budget(tmp_path, monkeypatch):
    monkeypatch.setenv('NO_PROXY', '127.0.0.1')
    # Each phase fits .8s individually, but together they exceed it.
    with local_http([{'header_delay': .001, 'body': b'a' * 130, 'body_delay': .005}]) as (url, requests):
        with pytest.raises(ValueError, match='deadline'):
            download(url, tmp_path / 'download', timeout=.2, attempts=1)
        assert len(requests) == 1 and requests[0]['disconnected'].wait(.5)
        assert not (tmp_path / 'download').exists()


def test_retry_after_wall_expiry_gets_fresh_budget_and_discards_fragment(tmp_path, monkeypatch):
    monkeypatch.setenv('NO_PROXY', '127.0.0.1')
    body = b'good' * 20
    with local_http([{'body': b'partial' * 100, 'body_delay': .005},
                     {'body': body, 'body_delay': .004}]) as (url, requests):
        target = tmp_path / 'download'
        download(url, target, timeout=.2)
        assert len(requests) == 2 and requests[0]['disconnected'].wait(.5)
        assert target.read_bytes() == body


@pytest.mark.parametrize('timeout,attempts', [(float('inf'), 2), (0, 2), (1, 3)])
def test_invalid_budget_is_rejected_before_transport(tmp_path, timeout, attempts):
    with pytest.raises(ValueError, match='positive finite timeout and 1 or 2 attempts'):
        download('http://127.0.0.1:1/unused', tmp_path / 'download', timeout, attempts)
    assert not (tmp_path / 'download').exists()


def test_normal_real_request_and_permanent_http_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('NO_PROXY', '127.0.0.1')
    target = tmp_path / 'download'
    with local_http([{'body': b'complete body'}]) as (url, requests):
        download(url, target, timeout=.2)
        assert len(requests) == 1 and target.read_bytes() == b'complete body'
    target.unlink()
    with local_http([{'status': 404}]) as (url, requests):
        with pytest.raises(ValueError, match='HTTPError.*attempt 1/2'):
            download(url, target, timeout=.2)
        assert len(requests) == 1 and not target.exists()


def test_acquire_records_real_transport_expiry_and_cleans_staging(tmp_path, monkeypatch):
    from qfs import acquire as module
    from test_acquire import START, END, pair
    monkeypatch.setenv('NO_PROXY', '127.0.0.1')
    # Five verified local objects; the only missing object's CHECKSUM arrives,
    # then its ZIP really drips over HTTP. No public requests or engine mocks.
    raw = tmp_path / 'raw'
    plan = module.required_objects(START, END)
    for obj in plan[1:]:
        pair(raw, obj)
    missing_name = plan[0]['official_url'].rsplit('/', 1)[1]
    checksum = ('0' * 64 + '  ' + missing_name).encode()
    with local_http([{'body': checksum}, {'body': b'a' * 500, 'body_delay': .005}]) as (url, requests):
        def local_download(official_url, target):
            assert official_url in {plan[0]['official_url'], plan[0]['official_url'] + '.CHECKSUM'}
            return download(url, target, timeout=.2)
        monkeypatch.setattr(module, 'download', local_download)  # endpoint/timeout boundary only
        result = module.acquire(START, END, tmp_path / 'cache', tmp_path / 'evidence', [raw])
        assert len(result['obtained_objects']) == 5 and len(result['failed_objects']) == 1
        assert 'deadline' in result['failed_objects'][0]['error']
        assert len(requests) == 3 and all(r['disconnected'].wait(.5) for r in requests[1:])
        assert not list((tmp_path / 'cache').rglob('*.zip'))
        assert not list(tmp_path.rglob('.qfs-download-*')) and not list(tmp_path.glob('.qfs-acquire-*'))
        assert (tmp_path / 'evidence/acquisition.json').exists()
