"""Small official-only downloader. Backtests and preparation remain offline."""
import http.client
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

import pandas as pd

from .config import utc
from .data import sha256
from .funding import VERIFIED_START, VERIFIED_END
from .prepare import KINDS
from .report import write_json

ORIGIN = 'https://data.binance.vision/data/'


def object_path(kind, month):
    category = KINDS[kind]
    suffix = 'fundingRate' if kind == 'funding' else '1m'
    return f'futures/um/monthly/{category}/BTCUSDT/' + ('' if kind == 'funding' else '1m/') + f'BTCUSDT-{suffix}-{month}.zip'


def required_objects(start, end):
    start, end = utc(start), utc(end)
    if not VERIFIED_START <= start < end <= VERIFIED_END:
        raise ValueError('acquire: interval outside audited Funding scope')
    if any(t != t.normalize().replace(day=1) for t in (start, end)):
        raise ValueError('acquire: require complete UTC month boundaries')
    objects = []
    for kind in KINDS:
        lower = start - pd.Timedelta(hours=600) if kind == 'trade_1m' else start
        upper = end if kind == 'trade_1m' or end == VERIFIED_END else end + pd.Timedelta(minutes=1)
        for month in pd.date_range(lower.normalize().replace(day=1), upper, freq='MS', inclusive='left'):
            text = month.strftime('%Y-%m')
            objects.append({'kind': kind, 'month': text, 'official_url': ORIGIN + object_path(kind, text),
                            'role': 'warmup' if month < start else 'boundary' if month >= end else 'research'})
    return objects


def checked_pair(path, obj):
    checksum = path.with_name(path.name + '.CHECKSUM')
    checksum_before = sha256(checksum)
    fields = checksum.read_text(encoding='utf-8').split()
    if len(fields) != 2 or fields[1] != path.name or not re.fullmatch('[0-9a-f]{64}', fields[0]):
        raise ValueError(f'{path}: invalid official CHECKSUM / filename')
    if sha256(path) != fields[0]:
        raise ValueError(f'{path}: corrupt cache ZIP/CHECKSUM SHA mismatch')
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.namelist() != [path.stem + '.csv'] or archive.testzip() is not None:
                raise ValueError(f'{path}: corrupt ZIP or unexpected CSV member')
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError(f'{path}: unreadable ZIP: {exc}') from exc
    if sha256(path) != fields[0] or sha256(checksum) != checksum_before:
        raise ValueError(f'{path}: cache changed during verification')
    return {'kind': obj['kind'], 'path': str(path.resolve()), 'checksum': str(checksum.resolve()),
            'official_url': obj['official_url'], 'sha256': fields[0]}


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith(ORIGIN):
            raise ValueError('acquire: refusing non-official redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, target, timeout=30, attempts=2):
    """Full GET only. Socket timeout bounds connect and each blocking read."""
    opener = urllib.request.build_opener(OfficialRedirect())
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'qfs-official-archives/1', 'Accept-Encoding': 'identity'})
            with opener.open(req, timeout=timeout) as response:
                if response.status != 200 or response.headers.get('Content-Range'):
                    raise ValueError(f'acquire: require full HTTP 200 response for {url}')
                size = 0
                # Overall wall bound also prevents an indefinitely trickling response.
                deadline = time.monotonic() + timeout * 4
                with target.open('wb') as file:
                    # read1 returns available bytes instead of waiting to fill a
                    # megabyte; a trickling peer cannot bypass the wall deadline.
                    while block := response.read1(1024 * 1024):
                        size += len(block)
                        file.write(block)
                        if time.monotonic() > deadline:
                            raise TimeoutError('acquire: total transfer deadline exceeded')
                length = response.headers.get('Content-Length')
                if length is not None and size != int(length):
                    raise ValueError(f'acquire: incomplete Content-Length for {url}')
            return
        except (OSError, ValueError, http.client.HTTPException) as exc:
            target.unlink(missing_ok=True)
            # Permanent missing/denied objects are not retried.
            if attempt + 1 == attempts or isinstance(exc, urllib.error.HTTPError) and exc.code < 500:
                raise ValueError(f'acquire: {url}: {type(exc).__name__}: {exc}; attempt {attempt + 1}/{attempts}') from exc


def acquire(start, end, cache, output, reuse=(), offline=False):
    cache, output = Path(cache).resolve(), Path(output).resolve()
    roots = [Path(p).resolve() for p in reuse]
    if output.exists() or output.is_relative_to(cache) or any(output.is_relative_to(r) for r in roots):
        raise ValueError('acquire: output must be new and outside cache/source trees')
    if any(cache.is_relative_to(r) for r in roots):
        raise ValueError('acquire: writable cache must be outside read-only reuse trees')
    requested = required_objects(start, end)
    obtained, failures, records = [], [], []
    for obj in requested:
        relative = object_path(obj['kind'], obj['month'])
        destination = cache / obj['kind'] / obj['month']
        name = Path(relative).name
        candidates = [destination / name] + [r / relative for r in roots] + [r / obj['kind'] / obj['month'] / name for r in roots]
        staging = None
        try:
            existing = next((p for p in candidates if p.exists() or p.with_name(p.name + '.CHECKSUM').exists()), None)
            if existing is not None:
                entry = checked_pair(existing, obj)  # fail closed on damaged cache, never overwrite
                status = 'reused'
            elif destination.exists():
                raise ValueError(f'{destination}: incomplete cache directory; refusing overwrite')
            elif offline:
                raise ValueError('acquire: absent from verified local caches; offline requested')
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                staging = Path(tempfile.mkdtemp(prefix='.qfs-download-', dir=destination.parent))
                download(obj['official_url'] + '.CHECKSUM', staging / (name + '.CHECKSUM'))
                download(obj['official_url'], staging / name)
                checked_pair(staging / name, obj)
                if destination.exists():
                    raise ValueError('acquire: cache appeared concurrently; refusing overwrite')
                staging.rename(destination)
                staging = None
                entry = checked_pair(destination / name, obj)
                status = 'downloaded'
            obtained.append(entry)
            records.append(obj | {'status': status, **entry, 'checksum_sha256': sha256(entry['checksum'])})
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            failures.append(obj | {'error': f'{type(exc).__name__}: {exc}'})
        finally:
            if staging is not None:
                shutil.rmtree(staging)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.qfs-acquire-', dir=output.parent))
    try:
        write_json(staging / 'manifest.json', {'symbol': 'BTCUSDT', 'archives': obtained})
        record = {'version': 'qfs-acquire-1', 'requested_range': {'start': utc(start).isoformat(), 'end': utc(end).isoformat()},
                  'requested_objects': requested, 'obtained_objects': records, 'failed_objects': failures,
                  'manifest_sha256': sha256(staging / 'manifest.json'), 'offline': offline,
                  'coverage_note': 'Object availability, not validated continuous minute coverage; scan required. CHECKSUM is not a signature.'}
        write_json(staging / 'acquisition.json', record)
        if output.exists():
            raise ValueError('acquire: output appeared concurrently')
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return record
