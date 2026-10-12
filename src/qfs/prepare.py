"""Read-only official monthly archives -> the existing offline input contract."""
from decimal import Decimal
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

import numpy as np
import pandas as pd

from .config import Config, utc
from .data import load_data, require_grid, sha256, validate_frame
from .funding import MAX_DELAY, VERIFIED_END, VERIFIED_START, funding_policy, validate_funding_schedule
from .report import write_json


KINDS = {'trade_1m': 'klines', 'mark_1m': 'markPriceKlines', 'funding': 'fundingRate'}


def read_archive(entry, base):
    if set(entry) != {'kind', 'path', 'checksum', 'official_url', 'sha256'} or entry['kind'] not in KINDS:
        raise ValueError('prepare: archive requires kind/path/checksum/official_url/sha256')
    kind = entry['kind']
    category = KINDS[kind]
    prefix = f'https://data.binance.vision/data/futures/um/monthly/{category}/BTCUSDT/'
    prefix += '' if kind == 'funding' else '1m/'
    stem = 'BTCUSDT-fundingRate-' if kind == 'funding' else 'BTCUSDT-1m-'
    match = re.fullmatch(re.escape(prefix + stem) + r'(\d{4}-\d{2})\.zip', entry['official_url'])
    if not match or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']):
        raise ValueError('prepare: require official BTCUSDT monthly URL and SHA-256')
    month = utc(match[1] + '-01')
    name = stem + match[1] + '.zip'
    path, checksum = (base / entry['path']).resolve(), (base / entry['checksum']).resolve()
    if checksum.read_text(encoding='utf-8').split() != [entry['sha256'], name] or sha256(path) != entry['sha256']:
        raise ValueError(f'{path}: ZIP/CHECKSUM/declaration mismatch')
    checksum_sha = sha256(checksum)
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != [name[:-4] + '.csv']:
            raise ValueError(f'{path}: expected exactly the corresponding native CSV member')
        with archive.open(archive.namelist()[0]) as file:
            frame = pd.read_csv(file, dtype=str, header=0 if kind == 'funding' else None)
    if kind == 'funding':
        if list(frame.columns) != ['calc_time', 'funding_interval_hours', 'last_funding_rate']:
            raise ValueError(f'{path}: invalid native Funding fields')
        if not frame.funding_interval_hours.eq('8').all():
            raise ValueError(f'{path}: non-8H native Funding')
        epochs = frame.calc_time
    else:
        if frame.shape[1] != 12:
            raise ValueError(f'{path}: expected native 12-column klines')
        if len(frame) and frame.iloc[0, 0] == 'open_time':
            if frame.iloc[0, :7].tolist() != ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time']:
                raise ValueError(f'{path}: ambiguous kline header')
            frame = frame.iloc[1:].reset_index(drop=True)
        epochs = frame.iloc[:, 0]
    if not len(frame) or not epochs.str.fullmatch(r'\d+').fillna(False).all():
        raise ValueError(f'{path}: require nonempty integer epoch milliseconds')
    times = pd.DatetimeIndex(pd.to_datetime(epochs.astype('int64'), unit='ms', utc=True))
    if times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError(f'{path}: duplicate/out-of-order native timestamp')
    if (times < month).any() or (times >= month + pd.DateOffset(months=1)).any():
        raise ValueError(f'{path}: timestamps disagree with official archive month / milliseconds')
    if kind == 'funding':
        rate = pd.to_numeric(frame.last_funding_rate, errors='coerce').to_numpy(dtype=float)
        if not np.isfinite(rate).all():
            raise ValueError(f'{path}: non-finite Funding rate')
        normalized = pd.DataFrame({'funding_rate': rate}, index=times.rename('funding_time'))
    else:
        close_epochs = frame.iloc[:, 6]
        if (not close_epochs.str.fullmatch(r'\d+').fillna(False).all()
                or not close_epochs.astype('int64').eq(epochs.astype('int64') + 59999).all()):
            raise ValueError(f'{path}: invalid native minute close_time')
        columns = ['open', 'high', 'low', 'close', 'volume']
        result = frame.iloc[:, 1:6].copy()
        result.columns = columns
        result.insert(0, 'open_time', times)
        if kind == 'mark_1m':
            result = result.rename(columns={c: 'mark_' + c for c in columns[:4]})
        normalized = validate_frame(result, kind, str(path))
        if kind == 'trade_1m':
            # Preserve decimal volume until aggregation, not a float sum of 240 inputs.
            normalized['decimal_volume'] = [Decimal(v) for v in frame.iloc[:, 5]]
    if sha256(path) != entry['sha256'] or sha256(checksum) != checksum_sha:
        raise ValueError(f'{path}: raw source changed during reading')
    return normalized, entry | {'path': str(path), 'checksum': str(checksum), 'checksum_sha256': checksum_sha}


def prepare(manifest, output, start, end):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    start, end = utc(start), utc(end)
    if not VERIFIED_START <= start < end <= VERIFIED_END or start != start.floor('min') or end != end.floor('min'):
        raise ValueError('prepare: require minute-aligned interval within audited Funding scope')
    before = sha256(manifest)
    raw = json.loads(manifest.read_text(encoding='utf-8'))
    if set(raw) != {'symbol', 'archives'} or raw['symbol'] != 'BTCUSDT' or not isinstance(raw['archives'], list):
        raise ValueError('prepare: manifest requires BTCUSDT symbol and ordered archives')
    pieces = {k: [] for k in KINDS}
    sources = []
    for entry in raw['archives']:
        for key in ('path', 'checksum'):
            source_path = (manifest.parent / entry[key]).resolve()
            if output.is_relative_to(source_path.parent):
                raise ValueError('prepare: output must be new and outside source directories')
        frame, source = read_archive(entry, manifest.parent)
        pieces[entry['kind']].append(frame)
        sources.append(source)
    if output.exists() or output.is_relative_to(manifest.parent):
        raise ValueError('prepare: output must be new and outside source directories')
    frames = {}
    for kind, parts in pieces.items():
        if not parts:
            raise ValueError(f'prepare: missing {kind} archives')
        frame = pd.concat(parts)
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            raise ValueError(f'prepare {kind}: duplicate/out-of-order archive boundary')
        frames[kind] = frame
    warm = start.floor('4h') - pd.Timedelta(hours=600)
    trade = frames['trade_1m'].loc[(frames['trade_1m'].index >= warm) & (frames['trade_1m'].index < end)]
    require_grid(trade, pd.date_range(warm, end, freq='min', inclusive='left'), 'prepare trade_1m warmup/execution')
    bars = []
    for time, block in trade.groupby(trade.index.floor('4h'), sort=False):
        if time + pd.Timedelta(hours=4) > end:
            continue  # partial final bar is not completed history
        if len(block) != 240:
            raise ValueError(f'prepare: incomplete 240-minute 4H block {time}')
        bars.append({'open_time': time, 'open': block.open.iloc[0], 'high': block.high.max(),
                     'low': block.low.min(), 'close': block.close.iloc[-1],
                     'volume': float(sum(block.decimal_volume, Decimal(0)))})
    native = frames['funding']
    validate_funding_schedule(native, start, end, 'prepare native Funding')
    selected = native[(native.index >= max(start - MAX_DELAY, VERIFIED_START)) &
                      (native.index < min(end + MAX_DELAY + pd.Timedelta(nanoseconds=1), VERIFIED_END))].copy()
    marks = frames['mark_1m']
    minutes = selected.index.floor('min')
    require_grid(marks, minutes, 'prepare Funding Mark Open / boundary evidence')
    selected['funding_mark_price'] = marks.loc[minutes, 'mark_open'].to_numpy()
    selected = validate_frame(selected.reset_index(), 'funding', 'prepare funding')
    execution_marks = marks[(marks.index >= start) & (marks.index < end)]
    require_grid(execution_marks, pd.date_range(start, end, freq='min', inclusive='left'), 'prepare mark_1m')
    normalized = {'bars_4h': validate_frame(pd.DataFrame(bars), 'bars_4h', 'prepare bars_4h').reset_index(),
                  'trade_1m': trade.drop(columns='decimal_volume').reset_index(),
                  'mark_1m': execution_marks.reset_index(), 'funding': selected.reset_index()}
    source = {'description': 'Verified local official Binance monthly archives; independent of QuantForge canonical',
              'official_source': 'https://data.binance.vision/', 'independent_out_of_sample': False,
              'manifest_path': str(manifest), 'manifest_sha256': before, 'source_files': sources,
              'conversion': 'complete 240-minute UTC OHLC; exact Decimal volume sum then float64; native integer-ms Funding; actual-minute Mark Open; no interpolation',
              'funding_validation': funding_policy(), 'warmup_start': warm.isoformat(),
              'run_coverage': {'start': start.isoformat(), 'end': end.isoformat()}}
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.qfs-prepare-', dir=output.parent))
    try:
        for key, frame in normalized.items():
            frame.to_parquet(staging / f'{key}.parquet', index=False)
        config = Config.from_dict({'strategy': {'name': 'ema'}, 'symbol': 'BTCUSDT', 'start': start, 'end': end,
                                  'data': {k: str(staging / f'{k}.parquet') for k in normalized},
                                  'initial_equity': 10000, 'position_fraction': .5, 'maximum_leverage': 1,
                                  'taker_fee_rate': .0005, 'slippage_rate': .0005, 'output_dir': str(staging / 'unused')})
        load_data(config)
        source['normalized_files'] = {k: {'path': f'{k}.parquet', 'sha256': sha256(staging / f'{k}.parquet'),
                                          'row_count': len(v)} for k, v in normalized.items()}
        for obj in sources:
            if sha256(obj['path']) != obj['sha256'] or sha256(obj['checksum']) != obj['checksum_sha256']:
                raise ValueError(f"{obj['path']}: raw input changed during preparation")
        if sha256(manifest) != before:
            raise ValueError('prepare: manifest changed during preparation')
        write_json(staging / 'provenance.json', source)
        if output.exists():
            raise ValueError('prepare: output appeared during preparation; refusing overwrite')
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return source
