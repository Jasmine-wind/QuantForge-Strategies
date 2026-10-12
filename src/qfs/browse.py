"""Standalone offline report view; checks artifact integrity, not a new ledger audit."""
from importlib.resources import files
import json
import math
from pathlib import Path
import os
import re
import tempfile

import numpy as np
import pandas as pd

from .compare import MEMBERS, METRICS, SCENARIOS
from .data import sha256


# Supported report versions have fixed inventories; never infer coverage from a
# supplied hash map or from the files currently present on disk.
RAW_FILES = {'summary.json', 'trades.csv', 'equity.csv', 'manifest.json'}
COMPARISON_HASH_FILES = {'comparison.csv', 'periods.csv', 'report.md'}
COMPARISON_FILES = COMPARISON_HASH_FILES | {'comparison.json'} | {
    f'reports/{scene}/{member}/{name}'
    for scene, _, _ in SCENARIOS for member, _ in MEMBERS for name in RAW_FILES
}


def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'browse: unsafe report path {relative}')
    return path


def check_hash_manifest(root, expected, required):
    if not isinstance(expected, dict) or set(expected) != required:
        missing = sorted(required - set(expected)) if isinstance(expected, dict) else sorted(required)
        unexpected = sorted(set(expected) - required) if isinstance(expected, dict) else []
        raise ValueError(f'browse: incomplete/invalid hash manifest {root}: '
                         f'missing={missing}, unexpected={unexpected}; require fixed object inventory')
    for relative, digest in expected.items():
        if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
            raise ValueError(f'browse: invalid hash manifest digest {root / relative}: require SHA-256 hex')


def check_files(root, expected, required):
    check_hash_manifest(root, expected, required)
    for relative, digest in expected.items():
        path = inside(root, relative)
        if sha256(path) != digest:
            raise ValueError(f'browse: report hash mismatch {path}')


def same(actual, expected, label):
    if expected is None:
        good = actual is None or pd.isna(actual)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        good = actual is not None and math.isclose(float(actual), expected, rel_tol=1e-12, abs_tol=1e-12)
    else:
        good = actual == expected
    if not good:
        raise ValueError(f'browse: copied report value disagrees: {label}')


def display_samples(curve, buckets=160):
    """Only chart compression; peaks use the full curve before selecting extrema."""
    equity = curve.equity.to_numpy(dtype=float)
    if not np.isfinite(equity).all() or (equity <= 0).any():
        raise ValueError('browse: completed report contains invalid equity')
    drawdown = 1 - equity / np.maximum.accumulate(equity)
    keep = {0, len(curve) - 1}
    for block in np.array_split(np.arange(len(curve)), min(buckets, len(curve))):
        keep.update((int(block[0]), int(block[-1]), int(block[equity[block].argmin()]),
                     int(block[equity[block].argmax()]), int(block[drawdown[block].argmin()]),
                     int(block[drawdown[block].argmax()])))
    return [[str(curve.time.iloc[i]), float(equity[i]), float(drawdown[i])] for i in sorted(keep)]


def comparison_payload(root):
    payload = json.loads((root / 'comparison.json').read_text(encoding='utf-8'))
    if payload['status'] != 'completed' or payload['comparison_version'] != 'qfs-compare-v2-stage1.0':
        raise ValueError('browse: require supported completed comparison')
    order = [(s, m) for s, _, _ in SCENARIOS for m, _ in MEMBERS]
    if [(m['scenario'], m['member']) for m in payload['members']] != order:
        raise ValueError('browse: incomplete or reordered member/scenario list')
    check_hash_manifest(root, payload.get('artifact_sha256'), COMPARISON_HASH_FILES)
    for member in payload['members']:
        relative = f"reports/{member['scenario']}/{member['member']}"
        if member['raw_report'] != relative:
            raise ValueError('browse: invalid hash manifest raw report path')
        check_hash_manifest(inside(root, relative), member.get('artifact_sha256'), RAW_FILES)
    return payload


def comparison_view(root, label):
    # Preflight every member before comparing any file digest, including outer
    # digests which could otherwise mask a missing nested manifest entry.
    payload = comparison_payload(root)
    order = [(s, m) for s, _, _ in SCENARIOS for m, _ in MEMBERS]
    check_files(root, payload.get('artifact_sha256'), COMPARISON_HASH_FILES)
    full = pd.read_csv(root / 'comparison.csv', float_precision='round_trip')
    if list(zip(full.scenario, full.member)) != order:
        raise ValueError('browse: comparison CSV order disagrees')
    periods = pd.read_csv(root / 'periods.csv', float_precision='round_trip', dtype={'period': str})
    if len(periods) != len(payload['periods']):
        raise ValueError('browse: periods CSV length disagrees')
    for csv, period in zip(periods.to_dict('records'), payload['periods']):
        for key, value in period.items():
            same(csv[key], value, f'period {key}')
    members = []
    for i, member in enumerate(payload['members']):
        raw = inside(root, member['raw_report'])
        check_files(raw, member.get('artifact_sha256'), RAW_FILES)
        summary = json.loads((raw / 'summary.json').read_text(encoding='utf-8'))
        if member['summary'] != summary or summary['config'] != member['config'] or summary['status'] != 'completed':
            raise ValueError('browse: original summary/config disagrees')
        for key in ('symbol', 'start', 'end', 'data', 'initial_equity', 'position_fraction',
                    'maximum_leverage', 'output_dir', 'data_source'):
            if member['config'][key] != payload['shared_config'][key]:
                raise ValueError(f'browse: member/shared config disagrees: {key}')
        for key in METRICS:
            same(full.iloc[i][key], summary[key], key)
        curve = pd.read_csv(raw / 'equity.csv', usecols=['time', 'equity'], float_precision='round_trip')
        times = pd.DatetimeIndex(pd.to_datetime(curve.time, utc=True))
        if not len(curve) or not times.is_monotonic_increasing:
            raise ValueError('browse: empty/out-of-order equity curve')
        same(curve.equity.iloc[0], summary['initial_equity'], 'initial equity')
        same(curve.equity.iloc[-1], summary['final_equity'], 'final equity')
        scene = member['scenario']
        benchmarks = {r['member']: r['summary']['total_return'] for r in payload['members'] if r['scenario'] == scene}
        members.append({'scenario': scene, 'member': member['member'], 'summary': summary,
                        'periods': [r for r in payload['periods'] if r['scenario'] == scene and r['member'] == member['member']],
                        'return_minus_cash_pp': 100 * (summary['total_return'] - benchmarks['usdt_cash']),
                        'return_minus_perpetual_pp': 100 * (summary['total_return'] - benchmarks['btcusdt_perpetual_long_hold']),
                        'curve_rows': len(curve), 'samples': display_samples(curve)})
    return {'label': label, 'config': payload['shared_config'], 'data_source': payload['data_source'],
            'data_files': payload['data_files'], 'code': payload['code'], 'runtime': payload['runtime'],
            'limitations': payload['limitations'], 'metric_definitions': payload['full_interval_metric_definitions'],
            'period_definitions': payload['period_definitions'], 'members': members}


def load_view(run):
    root = Path(run).resolve()
    before = {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob('*')) if p.is_file()}
    if (root / 'study.json').exists():
        study = json.loads((root / 'study.json').read_text(encoding='utf-8'))
        if study['status'] != 'completed' or study['study_version'] != 'qfs-study-v2-stage2.0':
            raise ValueError('browse: require supported completed study')
        labels = [f'window-{i+1:02d}' for i in range(len(study['windows']))]
        if not 1 <= len(labels) <= 4 or [w['label'] for w in study['windows']] != labels:
            raise ValueError('browse: invalid hash manifest study window paths')
        required = {'study.csv', 'report.md'} | {
            f'windows/{label}/{name}' for label in labels for name in COMPARISON_FILES
        }
        check_hash_manifest(root, study.get('artifact_sha256'), required)
        for record in study['windows']:
            relative = f"windows/{record['label']}"
            if record['comparison_path'] != relative:
                raise ValueError('browse: invalid hash manifest window report path')
            child = inside(root, relative)
            check_hash_manifest(child, record.get('artifact_sha256'), COMPARISON_FILES)
            comparison_payload(child)
        check_files(root, study.get('artifact_sha256'), required)
        if len(study['windows']) != len(study['config']['windows']) or len(study['rows']) != 12 * len(study['windows']):
            raise ValueError('browse: inconsistent study window/row counts')
        csv_rows = pd.read_csv(root / 'study.csv', float_precision='round_trip').to_dict('records')
        if len(csv_rows) != len(study['rows']):
            raise ValueError('browse: study CSV row count disagrees')
        for csv, row in zip(csv_rows, study['rows']):
            for key, value in row.items():
                same(csv[key], value, f'study CSV {key}')
        windows = []
        for record, config in zip(study['windows'], study['config']['windows']):
            if any(record[k] != config[k] for k in ('label', 'start', 'end')):
                raise ValueError('browse: study window metadata disagrees')
            child = inside(root, record['comparison_path'])
            check_files(child, record.get('artifact_sha256'), COMPARISON_FILES)
            view = comparison_view(child, record['label'])
            if any(view['config'][k] != config[k] for k in ('start', 'end', 'data', 'data_source')):
                raise ValueError('browse: study/comparison config disagrees')
            rows = [r for r in study['rows'] if r['window'] == record['label']]
            if [(r['scenario'], r['member']) for r in rows] != [(m['scenario'], m['member']) for m in view['members']]:
                raise ValueError('browse: study switches disagree')
            for row, member in zip(rows, view['members']):
                for key in METRICS:
                    same(row[key], member['summary'][key], key)
                for key in ('return_minus_cash_pp', 'return_minus_perpetual_pp'):
                    same(row[key], member[key], key)
            windows.append(view)
    else:
        windows = [comparison_view(root, 'comparison')]
    after = {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob('*')) if p.is_file()}
    if after != before:
        raise ValueError('browse: report changed while reading')
    return {'view_version': 'qfs-offline-view-1.0', 'source_directory': str(root), 'source_sha256': before,
            'verification': '报告SHA和内部复制值一致性检查，不等同独立核账；展示指标来自原报告',
            'sampling': '每桶保留首尾、权益/全曲线峰值回撤各极值；只压缩显示，不重算财务指标', 'windows': windows}


def export_html(run, output):
    root, output = Path(run).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError('browse: output must be new and outside original report directory')
    view = load_view(root)
    encoded = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    template = files('qfs').joinpath('browser.html').read_text(encoding='utf-8')
    page = template.replace('/*__REPORT_DATA__*/null', encoded)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.qfs-browse-', dir=output.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file:
            file.write(page)
        # Exclusive hard-link publication; never replace a concurrently created file.
        os.link(temporary, output)
    finally:
        Path(temporary).unlink()
    return output
