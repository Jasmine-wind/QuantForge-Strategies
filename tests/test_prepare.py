"""Official-format synthetic archives test correctness, not performance."""
import json
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from qfs.config import Config
from qfs.data import load_data, sha256


def raw_fixture(root):
    root.mkdir()
    start, end = '2020-01-26T00:00:00Z', '2020-01-26T04:00:00Z'
    times = pd.date_range('2020-01-01T00:00Z', end, freq='min', inclusive='left')
    ms = times.as_unit('ms').asi8
    rows = pd.DataFrame({0: ms, 1: '100.10', 2: '102.20', 3: '99.30', 4: '101.40', 5: '0.1',
                         6: ms + 59999, 7: '0', 8: '1', 9: '0', 10: '0', 11: '0'})
    marks = rows[rows[0] >= pd.Timestamp(start).value // 1000000].copy()
    funding = pd.DataFrame({'calc_time': [pd.Timestamp(start).value // 1000000 + 47],
                            'funding_interval_hours': ['8'], 'last_funding_rate': ['0.0001']})
    entries = []
    for kind, category, frame in [('trade_1m', 'klines', rows), ('mark_1m', 'markPriceKlines', marks),
                                   ('funding', 'fundingRate', funding)]:
        name = f"BTCUSDT-{'fundingRate' if kind == 'funding' else '1m'}-2020-01.zip"
        path = root / kind / name
        path.parent.mkdir()
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name[:-4] + '.csv', frame.to_csv(index=False, header=kind == 'funding'))
        digest = sha256(path)
        checksum = path.with_name(name + '.CHECKSUM')
        checksum.write_text(f'{digest}  {name}\n')
        url = f"https://data.binance.vision/data/futures/um/monthly/{category}/BTCUSDT/"
        if kind != 'funding':
            url += '1m/'
        entries.append({'kind': kind, 'path': str(path), 'checksum': str(checksum),
                         'official_url': url + name, 'sha256': digest})
    manifest = root / 'manifest.json'
    manifest.write_text(json.dumps({'symbol': 'BTCUSDT', 'archives': entries}))
    return manifest, start, end


def test_prepare_raw_archives_without_canonical_preserves_contract(tmp_path):
    from qfs.prepare import prepare
    manifest, start, end = raw_fixture(tmp_path / 'raw')
    before = {str(p): sha256(p) for p in manifest.parent.rglob('*') if p.is_file()}
    output = tmp_path / 'prepared'
    source = prepare(manifest, output, start, end)
    assert before == {str(p): sha256(p) for p in manifest.parent.rglob('*') if p.is_file()}
    assert set(p.name for p in output.iterdir()) == {'bars_4h.parquet', 'trade_1m.parquet', 'mark_1m.parquet', 'funding.parquet', 'provenance.json'}
    bars = pd.read_parquet(output / 'bars_4h.parquet')
    assert len(bars) == 151 and bars.iloc[0].volume == 24.0
    assert bars.iloc[0]['open'] == 100.10 and bars.iloc[0].high == 102.20 and bars.iloc[-1].close == 101.40
    funding = pd.read_parquet(output / 'funding.parquet')
    assert funding.iloc[0].funding_time == pd.Timestamp(start) + pd.Timedelta(milliseconds=47)
    assert funding.iloc[0].funding_mark_price == 100.10
    config = Config.from_dict({'strategy': {'name': 'ema'}, 'symbol': 'BTCUSDT', 'start': start, 'end': end,
                              'data': {k: str(output / f'{k}.parquet') for k in ('bars_4h', 'trade_1m', 'mark_1m', 'funding')},
                              'initial_equity': 10000, 'position_fraction': .5, 'maximum_leverage': 1,
                              'taker_fee_rate': .0005, 'slippage_rate': .0005, 'output_dir': str(tmp_path / 'runs')})
    assert len(load_data(config).trade) == 240
    assert source['independent_out_of_sample'] is False and len(source['source_files']) == 3
    with pytest.raises(ValueError, match='new'):
        prepare(manifest, output, start, end)
    repeat = tmp_path / 'repeat'
    prepare(manifest, repeat, start, end)
    assert {p.name: sha256(p) for p in output.iterdir()} == {p.name: sha256(p) for p in repeat.iterdir()}


@pytest.mark.parametrize('damage', ['checksum', 'checksum_name', 'url', 'sha', 'member', 'gap', 'duplicate',
                                    'order', 'ohlc', 'fractional_ms', 'off_schedule', 'mark_missing', 'close_time'])
def test_prepare_rejects_corruption_even_with_refreshed_hashes(tmp_path, damage):
    from qfs.prepare import prepare
    manifest, start, end = raw_fixture(tmp_path / 'raw')
    raw = json.loads(manifest.read_text())
    entry = raw['archives'][2 if damage in {'fractional_ms', 'off_schedule'} else 1 if damage == 'mark_missing' else 0]
    archive = Path(entry['path'])
    checksum = Path(entry['checksum'])
    if damage == 'checksum':
        checksum.write_text('0' * 64 + '  ' + archive.name)
    elif damage == 'checksum_name':
        checksum.write_text(entry['sha256'] + '  another.zip')
    elif damage == 'url':
        entry['official_url'] = entry['official_url'].replace('data.binance.vision', 'example.com')
    elif damage == 'sha':
        entry['sha256'] = '0' * 64
    else:
        with zipfile.ZipFile(archive) as z:
            name = z.namelist()[0]
            frame = pd.read_csv(z.open(name), dtype=str, header=0 if entry['kind'] == 'funding' else None)
        if damage in {'gap', 'mark_missing'}:
            frame = frame.iloc[1:]
        elif damage == 'duplicate':
            frame = pd.concat([frame.iloc[:1], frame], ignore_index=True)
        elif damage == 'order':
            frame.iloc[[0, 1]] = frame.iloc[[1, 0]].to_numpy()
        elif damage == 'ohlc':
            frame.iloc[0, 2] = '1'
        elif damage == 'close_time':
            frame.iloc[0, 6] = '0'
        elif damage == 'fractional_ms':
            frame.loc[0, 'calc_time'] += '.5'
        elif damage == 'off_schedule':
            frame.loc[0, 'calc_time'] = str(int(frame.loc[0, 'calc_time']) + 1)
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('wrong.csv' if damage == 'member' else name,
                       frame.to_csv(index=False, header=entry['kind'] == 'funding'))
        entry['sha256'] = sha256(archive)
        checksum.write_text(entry['sha256'] + '  ' + archive.name)
    manifest.write_text(json.dumps(raw))
    output = tmp_path / 'failed'
    with pytest.raises(ValueError):
        prepare(manifest, output, start, end)
    assert not output.exists() and not list(tmp_path.glob('.qfs-prepare-*'))


def test_prepare_cli_and_private_write_failure_cleanup(tmp_path, monkeypatch):
    import subprocess
    import sys
    from qfs.prepare import prepare
    manifest, start, end = raw_fixture(tmp_path / 'raw')
    output = tmp_path / 'cli'
    proc = subprocess.run([sys.executable, '-m', 'qfs.cli', 'prepare', '--manifest', str(manifest),
                           '--start', start, '--end', end, '--output', str(output)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert Path(proc.stdout.strip()) == output
    def fail(*args, **kwargs):
        raise OSError('filesystem unavailable')
    monkeypatch.setattr(pd.DataFrame, 'to_parquet', fail)
    with pytest.raises(OSError, match='filesystem unavailable'):
        prepare(manifest, tmp_path / 'failed', start, end)
    assert not (tmp_path / 'failed').exists() and not list(tmp_path.glob('.qfs-prepare-*'))
    with pytest.raises(ValueError, match='outside'):
        prepare(manifest, manifest.parent / 'unsafe', start, end)
