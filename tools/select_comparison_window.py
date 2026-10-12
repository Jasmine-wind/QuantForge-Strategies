"""Data-only, read-only selection under docs/V2_SPEC.md; no strategy results.

Default: earliest 12 complete months, otherwise earliest longest block.
Study: earliest four nonoverlapping six-month windows, no short-block fallback.
"""
import argparse
from pathlib import Path
import zipfile

import pandas as pd

from qfs.config import utc
from qfs.data import sha256, validate_frame, require_grid
from qfs.funding import VERIFIED_START, VERIFIED_END, MAX_DELAY, validate_funding_schedule
from qfs.import_quantforge import verified_manifest, checked_mark_zip
from qfs.report import write_json
from qfs.study import STUDY_POLICY, choose_study_windows


MAX_MONTHS = 12


def choose_window(rows):
    blocks, block = [], []
    for row in rows:
        if row['valid']:
            if block and block[-1]['end'] != row['start']:
                blocks.append(block)
                block = []
            block.append(row)
            if len(block) == MAX_MONTHS:
                return {'start': block[0]['start'], 'end': block[-1]['end'], 'months': MAX_MONTHS}
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    if not blocks:
        return None
    best = max(blocks, key=len)  # ordered input => earliest on ties
    return {'start': best[0]['start'], 'end': best[-1]['end'], 'months': len(best)}


def audit(dataset, raw_root, mode='compare'):
    if mode not in {'compare', 'study'}:
        raise ValueError('unknown selection mode')
    dataset, raw_root = Path(dataset).resolve(), Path(raw_root).resolve()
    manifest = verified_manifest(dataset)
    paths = {key: dataset / f'{key}.csv' for key in ('decision_4h', 'path_1m', 'funding')}
    for key, path in paths.items():
        if manifest['files'][key]['path'] != path.name or sha256(path) != manifest['files'][key]['sha256']:
            raise ValueError(f'{path}: canonical checksum mismatch')
    coverage = manifest['request_range']
    start = max(utc(coverage['start_utc_inclusive']), VERIFIED_START)
    end = min(utc(coverage['end_utc_exclusive']), VERIFIED_END)
    month = start.normalize().replace(day=1)
    if month < start:
        month += pd.offsets.MonthBegin(1)
    starts = list(pd.date_range(month, end, freq='MS', inclusive='left'))
    starts = [t for t in starts if t + pd.offsets.MonthBegin(1) <= end]
    states = {t.strftime('%Y-%m'): {'start': t.isoformat(), 'end': (t + pd.offsets.MonthBegin(1)).isoformat(),
                                   'errors': [], 'trade_rows': 0, 'trade_first': None, 'trade_last': None} for t in starts}
    # Stream canonical contract data, preserving order across chunks. Never sort.
    previous = None
    for frame in pd.read_csv(paths['path_1m'], dtype=str, chunksize=100000):
        times = pd.to_datetime(frame.open_time_utc, utc=True, errors='raise')
        if not times.is_monotonic_increasing or times.duplicated().any() or (previous is not None and times.iloc[0] <= previous):
            raise ValueError(f"{paths['path_1m']}: duplicate/out-of-order canonical timestamps")
        previous = times.iloc[-1]
        frame['open_time'] = times
        for label, group in frame.groupby(times.dt.strftime('%Y-%m'), sort=False):
            if label not in states:
                continue
            state = states[label]
            first, last = group.open_time.iloc[0], group.open_time.iloc[-1]
            try:
                checked = validate_frame(group, 'trade_1m', str(paths['path_1m']))
                require_grid(checked, pd.date_range(first, last, freq='min'), str(paths['path_1m']))
                if state['trade_last'] is not None and first != utc(state['trade_last']) + pd.Timedelta(minutes=1):
                    raise ValueError(f"{paths['path_1m']}: missing required timestamp {utc(state['trade_last']) + pd.Timedelta(minutes=1)}")
            except (ValueError, TypeError) as exc:
                state['errors'].append(str(exc))
            state['trade_rows'] += len(group)
            state['trade_first'] = state['trade_first'] or first.isoformat()
            state['trade_last'] = last.isoformat()
    bars_raw = pd.read_csv(paths['decision_4h'], dtype=str).rename(columns={'open_time_utc': 'open_time'})
    bars = validate_frame(bars_raw, 'bars_4h', str(paths['decision_4h']))
    fund = pd.read_csv(paths['funding'], dtype=str)
    if not fund.funding_time_ms.str.fullmatch(r'\d+').fillna(False).all():
        raise ValueError(f"{paths['funding']}: non-integer native epoch milliseconds")
    native = pd.to_datetime(fund.funding_time_ms.astype('int64'), unit='ms', utc=True)
    display = pd.to_datetime(fund.funding_time_utc, utc=True)
    if ((display != native) & (display != native.dt.floor('s'))).any():
        raise ValueError(f"{paths['funding']}: display/native timestamp disagreement")
    fund['funding_time'] = native
    fund = fund.rename(columns={'mark_price': 'funding_mark_price'})
    inspected, consecutive = [], 0
    for state in states.values():
        left, right = utc(state['start']), utc(state['end'])
        expected_minutes = int((right - left).total_seconds() / 60)
        if state['trade_rows'] != expected_minutes or state['trade_first'] != left.isoformat() or state['trade_last'] != (right - pd.Timedelta(minutes=1)).isoformat():
            state['errors'].append(f"{paths['path_1m']}: incomplete month; rows {state['trade_rows']}/{expected_minutes}")
        try:
            warm = left - pd.Timedelta(hours=600)
            last_signal_open = (right - pd.Timedelta(nanoseconds=1)).floor('4h') - pd.Timedelta(hours=4)
            require_grid(bars, pd.date_range(warm, last_signal_open, freq='4h'), str(paths['decision_4h']))
        except ValueError as exc:
            state['errors'].append(str(exc))
        try:
            keep = (native >= max(left - MAX_DELAY, VERIFIED_START)) & (native < min(right + MAX_DELAY + pd.Timedelta(nanoseconds=1), VERIFIED_END))
            subset = fund[keep]
            if (subset.mark_price_source == 'missing').any():
                bad = subset.loc[subset.mark_price_source == 'missing', 'funding_time'].iloc[0]
                raise ValueError(f"{paths['funding']}: missing Funding Mark Price at {bad.isoformat()}")
            checked = validate_frame(subset, 'funding', str(paths['funding']))
            validate_funding_schedule(checked, left, right, str(paths['funding']))
            state['funding_evidence_rows'] = len(checked)
        except (ValueError, TypeError) as exc:
            state['errors'].append(str(exc))
        state['mark_archives'] = []
        marks = []
        try:
            for obj in manifest['funding_authority']['provenance']['mark_price_objects']:
                if utc(obj['end_utc_exclusive']) <= left or utc(obj['start_utc_inclusive']) >= right:
                    continue
                if '/markPriceKlines/BTCUSDT/1m/' not in obj['path']:
                    raise ValueError('non-BTCUSDT 1m Mark source')
                path = raw_root / obj['path'].removeprefix('/data/')
                frame = checked_mark_zip(path, obj['sha256'])
                marks.append(frame[(frame.open_time >= left) & (frame.open_time < right)])
                state['mark_archives'].append({'official_path': obj['path'], 'sha256': obj['sha256'],
                                               'checksum_file_sha256': sha256(str(path) + '.CHECKSUM')})
            if not marks:
                raise ValueError(f'Mark Price: no local archives for {left.isoformat()}')
            checked = validate_frame(pd.concat(marks, ignore_index=True), 'mark_1m', f"Mark ZIPs {left.isoformat()}")
            state['mark_rows'] = len(checked)
            require_grid(checked, pd.date_range(left, right, freq='min', inclusive='left'), f"Mark ZIPs {left.isoformat()}")
        except (ValueError, TypeError, OSError, zipfile.BadZipFile) as exc:
            state['errors'].append(str(exc))
        state['valid'] = not state['errors']
        inspected.append(state)
        print(left.strftime('%Y-%m'), 'complete' if state['valid'] else 'EXCLUDED: ' + '; '.join(state['errors']), flush=True)
        consecutive = consecutive + 1 if state['valid'] else 0
        if (mode == 'compare' and consecutive == MAX_MONTHS) or (mode == 'study' and len(choose_study_windows(inspected)) == 4):
            break  # fixed earliest windows found; never inspect strategy results
    for key, path in paths.items():
        if sha256(path) != manifest['files'][key]['sha256']:
            raise ValueError(f'{path}: canonical input changed during audit')
    selected = choose_window(inspected)
    result = {'policy': 'V2_SPEC.md: earliest 12 consecutive complete UTC months; fallback earliest longest, max12',
            'dataset_identity_sha256': manifest['sha256'], 'source_coverage': coverage,
            'audited_funding_scope': {'start': VERIFIED_START.isoformat(), 'end': VERIFIED_END.isoformat()},
            'canonical_files': {k: {'path': str(p), 'sha256': sha256(p)} for k, p in paths.items()},
            'months': inspected, 'selected': selected,
            'selection_status': 'longer_interval_available' if selected and selected['months'] >= 2 else 'long_validation_unavailable',
            'uninspected': 'months after earliest 12-month block, if found; partial months and periods outside audited Funding scope',
            'independent_out_of_sample': False, 'strategy_results_used': False}
    if mode == 'study':
        windows = choose_study_windows(inspected)
        result.update(mode='study', policy=STUDY_POLICY, windows=windows, selected=None,
                      selection_status='complete_4_windows' if len(windows) == 4 else 'insufficient_windows',
                      multiwindow_validation_available=len(windows) >= 2,
                      stop_reason='earliest four found' if len(windows) == 4 else 'audited complete-month coverage exhausted; no shortened windows',
                      uninspected='months after fourth window if found; partial months and outside audited Funding scope')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--raw-root', required=True)
    parser.add_argument('--output', required=True, help='New audit JSON outside read-only source trees')
    parser.add_argument('--mode', choices=('compare', 'study'), default='compare')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists() or any(output.is_relative_to(Path(p).resolve()) for p in (args.dataset, args.raw_root)):
        parser.error('output must be new and outside source trees')
    result = audit(args.dataset, args.raw_root, args.mode)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, result)
    print('SELECTED:', result.get('windows', result['selected']), '=>', output)


if __name__ == '__main__':
    main()
