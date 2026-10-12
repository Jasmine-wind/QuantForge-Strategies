"""Reproduce the fixed Funding policy evidence, read-only and entirely offline.

Writes only aggregate audit metadata, never rates, prices or machine paths.
"""
import argparse
from collections import Counter
from decimal import Decimal
from pathlib import Path
import zipfile

import pandas as pd

from qfs.data import sha256
from qfs.funding import VERIFIED_START, VERIFIED_END, MAX_DELAY, funding_policy
from qfs.import_quantforge import verified_manifest
from qfs.report import write_json


def audit(dataset, raw_root, cache=None):
    dataset, raw_root = Path(dataset), Path(raw_root)
    manifest = verified_manifest(dataset)
    source = dataset / "funding.csv"
    if sha256(source) != manifest["files"]["funding"]["sha256"]:
        raise ValueError(f"{source}: canonical checksum mismatch")
    canonical = pd.read_csv(source, dtype=str)
    times = pd.to_datetime(canonical.funding_time_ms.astype("int64"), unit="ms", utc=True)
    keep = (times >= VERIFIED_START) & (times < VERIFIED_END)
    expected = {int(r.funding_time_ms): Decimal(r.funding_rate) for r in canonical[keep].itertuples()}
    if len(expected) != int(keep.sum()):
        raise ValueError("duplicate canonical native Funding time")
    native, objects, intervals = {}, [], Counter()
    for obj in manifest["funding_authority"]["provenance"]["funding_objects"]:
        if pd.Timestamp(obj["start_utc_inclusive"]) >= VERIFIED_END or pd.Timestamp(obj["end_utc_exclusive"]) <= VERIFIED_START:
            continue
        path = raw_root / obj["path"].removeprefix("/data/")
        if not path.exists() and cache is not None:
            path = Path(cache) / (obj["sha256"] + ".zip")
        if not path.exists() or sha256(path) != obj["sha256"]:
            raise ValueError(f"{obj['path']}: missing or checksum-invalid native Funding ZIP")
        checksum = path.with_name(path.name + ".CHECKSUM")
        if checksum.exists() and checksum.read_text(encoding="utf-8").split()[0] != obj["sha256"]:
            raise ValueError(f"{checksum}: native CHECKSUM mismatch")
        with zipfile.ZipFile(path) as z:
            if len(z.namelist()) != 1:
                raise ValueError(f"{path}: expected one native CSV")
            frame = pd.read_csv(z.open(z.namelist()[0]), dtype=str)
        count = 0
        for row in frame.itertuples():
            actual = pd.Timestamp(int(row.calc_time), unit="ms", tz="UTC")
            if not VERIFIED_START <= actual < VERIFIED_END:
                continue
            if row.funding_interval_hours != "8":
                raise ValueError(f"{path}: non-8H native interval at {actual}")
            timestamp = int(row.calc_time)
            if timestamp in native:
                raise ValueError(f"{path}: repeated native settlement {actual}")
            native[timestamp] = Decimal(row.last_funding_rate)
            intervals[row.funding_interval_hours] += 1
            count += 1
        objects.append({"official_path": obj["path"], "sha256": obj["sha256"], "selected_rows": count})
    if native != expected:
        raise ValueError("native calc_time/rate rows do not exactly match canonical funding_time_ms/rate")
    actual = pd.DatetimeIndex(pd.to_datetime(sorted(native), unit="ms", utc=True))
    nominal = actual.round("8h")
    if not nominal.equals(pd.date_range(VERIFIED_START, VERIFIED_END, freq="8h", inclusive="left")):
        raise ValueError("native settlement calendar is not one-to-one complete UTC 00/08/16")
    delays = actual - nominal
    if (delays < pd.Timedelta(0)).any() or (delays > MAX_DELAY).any():
        raise ValueError("native time offsets exceed the FIXED [0,47]ms policy")
    loss = times[keep] != pd.to_datetime(canonical.loc[keep, "funding_time_utc"], utc=True)
    return {"policy": funding_policy(), "canonical_sha256": manifest["files"]["funding"]["sha256"],
            "native_objects": objects, "native_event_count": len(native),
            "native_interval_hours_counts": dict(intervals), "raw_canonical_time_rate_equality": True,
            "display_column_precision_loss_rows": int(loss.sum()),
            "delay_ms_counts": dict(sorted(Counter(d.value // 1_000_000 for d in delays).items())),
            "maximum_delay_actual_time": actual[delays.argmax()].isoformat()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--cache")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(args.dataset, args.raw_root, args.cache)
    output = Path(args.output)
    if output.exists():
        parser.error("audit output must be new; no overwriting existing evidence")
    write_json(output, result)
    print(f"PASS: {len(result['native_objects'])} native objects / {result['native_event_count']} settlements; {output}")
