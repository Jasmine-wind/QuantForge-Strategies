"""Full fixed-range data-only scan; never imports or runs strategies."""
import json
import os
from pathlib import Path
import tempfile
import zipfile

import pandas as pd

from .acquire import required_objects
from .data import sha256
from .official import SCAN_SCOPE, SCAN_START, SCAN_END, source_identity
from .prepare import prepare, read_archive
from .report import write_json
from .study import STUDY_POLICY, choose_study_windows


def scan(manifest, output):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(manifest.parent):
        raise ValueError('scan: output must be new and outside source manifest directory')
    digest = sha256(manifest)
    raw = json.loads(manifest.read_text(encoding='utf-8'))
    if set(raw) != {'symbol', 'archives'} or raw['symbol'] != 'BTCUSDT' or not isinstance(raw['archives'], list):
        raise ValueError('scan: require official BTCUSDT archive manifest')
    wanted = {o['official_url'] for o in required_objects(SCAN_START, SCAN_END)}
    entries, verified, failed, coverage = {}, [], {}, []
    previous = {}
    for entry in raw['archives']:
        url = entry['official_url']
        if url not in wanted or url in entries:
            raise ValueError('scan: duplicate or out-of-request object')
        kind = entry['kind']
        if kind in previous and url <= previous[kind]:
            raise ValueError('scan: out-of-order archive months')
        previous[kind] = url
        entries[url] = {**entry, **{k: str((manifest.parent / entry[k]).resolve()) for k in ('path', 'checksum')}}
        if any(output.is_relative_to(Path(entries[url][k]).parent) for k in ('path', 'checksum')):
            raise ValueError('scan: output inside source tree')
        try:
            frame, source = read_archive(entry, manifest.parent)
            verified.append(source)
            coverage.append({'official_url': url, 'kind': kind, 'rows': len(frame),
                             'first_actual': frame.index[0].isoformat(), 'last_actual': frame.index[-1].isoformat()})
        except (ValueError, TypeError, OSError, zipfile.BadZipFile) as exc:
            failed[url] = f'{type(exc).__name__}: {exc}'
    months = []
    with tempfile.TemporaryDirectory(prefix='qfs-quality-') as temporary:
        root = Path(temporary)
        for i, left in enumerate(pd.date_range(SCAN_START, SCAN_END, freq='MS', inclusive='left')):
            right = left + pd.DateOffset(months=1)
            required = required_objects(left, right)
            errors = [failed.get(o['official_url'], 'missing official object: ' + o['official_url'])
                      for o in required if o['official_url'] not in entries or o['official_url'] in failed]
            row = {'start': left.isoformat(), 'end': right.isoformat(), 'errors': errors,
                   'required_objects': required, 'warmup_start': (left - pd.Timedelta(hours=600)).isoformat()}
            if not errors:
                month_manifest = root / 'manifests' / f'{i}.json'
                month_manifest.parent.mkdir(exist_ok=True)
                write_json(month_manifest, {'symbol': 'BTCUSDT', 'archives': [entries[o['official_url']] for o in required]})
                try:
                    source = prepare(month_manifest, root / f'prepared-{i}', left, right)
                    row['normalized_row_counts'] = {k: v['row_count'] for k, v in source['normalized_files'].items()}
                except (ValueError, TypeError, OSError, zipfile.BadZipFile) as exc:
                    errors.append(f'{type(exc).__name__}: {exc}')
            row['valid'] = not errors
            months.append(row)
    if sha256(manifest) != digest:
        raise ValueError('scan: manifest changed during scan')
    for source in verified:
        if sha256(source['path']) != source['sha256'] or sha256(source['checksum']) != source['checksum_sha256']:
            raise ValueError('scan: official source changed during scan')
    windows = choose_study_windows(months)
    result = {'mode': 'study', 'scan_version': 'qfs-official-full-scan-1', 'scan_scope': SCAN_SCOPE,
              'policy': STUDY_POLICY, 'strategy_results_used': False, 'independent_out_of_sample': False,
              'manifest_path': str(manifest), 'manifest_sha256': digest,
              'source_identity': source_identity(verified), 'source_files': verified,
              'actual_source_coverage': coverage, 'failed_objects': failed,
              'months': months, 'windows': windows, 'multiwindow_validation_available': len(windows) >= 2,
              'stop_reason': 'all 29 requested UTC months inspected; earliest four windows retained' if len(windows) == 4
                             else f'all 29 requested UTC months inspected; only {len(windows)} full six-month windows; no shortened windows',
              'coverage_note': 'scan_scope is a request, not source coverage. Per-object actual times/rows do not imply continuity. Warmup/boundary objects are auxiliary.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.qfs-scan-', dir=output.parent)
    os.close(fd)
    try:
        write_json(temporary, result)
        os.link(temporary, output)
    finally:
        Path(temporary).unlink()
    return result
