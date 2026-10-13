"""One isolated HTTP attempt; stdlib only so startup does not load the backtester.

Executed by acquire.download, which owns the wall deadline and kills/reaps this
process on expiry. Termination closes sockets even during DNS/TLS/header reads.
"""
import http.client
from pathlib import Path
import sys
import urllib.error
import urllib.request

ORIGIN = 'https://data.binance.vision/data/'


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith(ORIGIN):
            raise ValueError('acquire: refusing non-official redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def receive(url, target, timeout):
    opener = urllib.request.build_opener(OfficialRedirect())
    req = urllib.request.Request(url, headers={'User-Agent': 'qfs-official-archives/1', 'Accept-Encoding': 'identity'})
    with opener.open(req, timeout=timeout) as response:
        if response.status != 200 or response.headers.get('Content-Range'):
            raise ValueError(f'acquire: require full HTTP 200 response for {url}')
        size = 0
        with target.open('wb') as file:
            while block := response.read1(1024 * 1024):
                size += len(block)
                file.write(block)
        length = response.headers.get('Content-Length')
        if length is not None and size != int(length):
            raise ValueError(f'acquire: incomplete Content-Length for {url}')


if __name__ == '__main__':
    try:
        receive(sys.argv[1], Path(sys.argv[2]), float(sys.argv[3]))
    except (OSError, ValueError, http.client.HTTPException) as exc:
        print(f'{type(exc).__name__}: {exc}')
        # Permanent missing/denied objects are not retried by the parent.
        raise SystemExit(2 if isinstance(exc, urllib.error.HTTPError) and exc.code < 500 else 1)
