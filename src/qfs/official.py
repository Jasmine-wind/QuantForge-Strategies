"""Path-independent identity of verified official objects, not canonical identity."""
import hashlib
import json
import re

CONVERSION = 'complete 240-minute UTC OHLC; exact Decimal volume sum then float64; native integer-ms Funding; actual-minute Mark Open; no interpolation'
MARKET = 'Binance BTCUSDT USD-M perpetual'
SOURCE_TYPE = 'official-monthly-v1'
SCAN_START = '2024-03-01T00:00:00+00:00'
SCAN_END = '2026-08-01T00:00:00+00:00'
SCAN_SCOPE = {'start_utc_inclusive': SCAN_START, 'end_utc_exclusive': SCAN_END}


def source_identity(sources):
    objects = []
    for obj in sources:
        record = {k: obj[k] for k in ('kind', 'official_url', 'sha256', 'checksum_sha256')}
        category = {'trade_1m': 'klines', 'mark_1m': 'markPriceKlines', 'funding': 'fundingRate'}.get(record['kind'])
        if category is None:
            raise ValueError('official identity: invalid kind')
        stem = 'fundingRate' if record['kind'] == 'funding' else '1m'
        prefix = f'https://data.binance.vision/data/futures/um/monthly/{category}/BTCUSDT/'
        prefix += '' if record['kind'] == 'funding' else '1m/'
        if not re.fullmatch(re.escape(prefix + f'BTCUSDT-{stem}-') + r'\d{4}-(0[1-9]|1[0-2])\.zip', record['official_url']):
            raise ValueError('official identity: invalid official object URL')
        if any(not isinstance(record[k], str) or not re.fullmatch('[0-9a-f]{64}', record[k]) for k in ('sha256', 'checksum_sha256')):
            raise ValueError('official identity: invalid digest')
        objects.append(record)
    objects.sort(key=lambda o: (o['kind'], o['official_url']))
    if len({o['official_url'] for o in objects}) != len(objects):
        raise ValueError('official identity: duplicate object')
    payload = {'type': SOURCE_TYPE, 'market': MARKET, 'conversion': CONVERSION, 'objects': objects}
    return payload | {'sha256': hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


def check_source_link(source, evidence, config):
    """Bind prepared normalized bytes and exact required raw objects to the scan."""
    from .acquire import required_objects
    from .data import sha256
    identity = source_identity(evidence['source_files'])
    actual = source_identity(source['source_files'])
    if (evidence.get('source_identity') != identity or source.get('source_identity') != actual
            or source.get('conversion') != CONVERSION or source.get('independent_out_of_sample') is not False
            or 'dataset_identity_sha256' in source):
        raise ValueError('study: official source identity / conversion disagrees')
    available = {o['official_url']: o for o in identity['objects']}
    needed = {o['official_url'] for o in required_objects(config.start, config.end)}
    if {o['official_url'] for o in actual['objects']} != needed or any(available.get(o['official_url']) != o for o in actual['objects']):
        raise ValueError('study: prepared official objects disagree with selection evidence / required boundaries')
    if source.get('run_coverage') != {'start': config.start.isoformat(), 'end': config.end.isoformat()}:
        raise ValueError('study: official prepared coverage disagrees')
    for key, path in config.data.items():
        if sha256(path) != source['normalized_files'][key]['sha256']:
            raise ValueError(f'study: official normalized hash mismatch {path}')
