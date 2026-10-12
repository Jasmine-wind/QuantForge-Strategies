"""Small read-only adapter for verified QuantForge schema-7 CSV + local Binance Mark ZIPs.

No old research modules are imported and nothing is written to the source repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

import pandas as pd

from .config import Config, utc
from .data import sha256, validate_frame, require_grid, load_data
from .funding import VERIFIED_START, VERIFIED_END, MAX_DELAY, funding_policy
from .report import write_json


LEGACY_FILES = {"bars_4h": "decision_4h", "trade_1m": "path_1m", "funding": "funding"}


def verified_manifest(dataset):
    path = Path(dataset) / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    identity = {k: v for k, v in manifest.items() if k not in {"version_id", "sha256"}}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != manifest.get("sha256") or manifest.get("version_id") != digest[:16]:
        raise ValueError(f"{path}: manifest identity mismatch")
    if (manifest.get("schema_version") != 7 or manifest.get("symbol") != "BTCUSDT"
            or manifest.get("contract_type") != "PERPETUAL" or manifest.get("timezone") != "UTC"
            or manifest.get("source") != "Binance USDⓈ-M public klines"):
        raise ValueError(f"{path}: require official BTCUSDT schema-7 UTC perpetual data")
    return manifest


def checked_mark_zip(path, expected_sha):
    path = Path(path)
    checksum = path.with_name(path.name + ".CHECKSUM")
    tokens = checksum.read_text(encoding="utf-8").split()
    if len(tokens) != 2 or tokens[0] != expected_sha or tokens[1] != path.name or sha256(path) != expected_sha:
        raise ValueError(f"{path}: Binance ZIP checksum/manifest mismatch")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 1 or not names[0].endswith(".csv"):
            raise ValueError(f"{path}: expected one CSV member")
        with archive.open(names[0]) as f:
            frame = pd.read_csv(f, header=None, dtype=str)
    if frame.iloc[0, 0] == "open_time":
        frame = frame.iloc[1:].reset_index(drop=True)
    if frame.shape[1] != 12:
        raise ValueError(f"{path}: expected Binance 12-column Kline CSV")
    frame = frame.iloc[:, :5].copy()
    frame.columns = ["open_time", "mark_open", "mark_high", "mark_low", "mark_close"]
    frame["open_time"] = pd.to_datetime(pd.to_numeric(frame.open_time, errors="raise"), unit="ms", utc=True)
    if sha256(path) != expected_sha:
        raise ValueError(f"{path}: input changed during reading")
    return frame


def convert(dataset, raw_root, output, start, end):
    dataset, raw_root, output = Path(dataset).resolve(), Path(raw_root).resolve(), Path(output).resolve()
    start, end = utc(start), utc(end)
    if start >= end or start != start.floor("min") or end != end.floor("min"):
        raise ValueError("conversion: require minute-aligned start < end")
    # Never let the adapter write inside the source datasets or raw tree.
    if output.is_relative_to(dataset) or output.is_relative_to(raw_root) or output.exists():
        raise ValueError(f"{output}: output must be new and outside source data")
    manifest = verified_manifest(dataset)
    warm_start = start.floor("4h") - pd.Timedelta(hours=150 * 4)
    normalized, source_files = {}, []
    for kind, key in LEGACY_FILES.items():
        info = manifest["files"][key]
        path = dataset / f"{key}.csv"
        if info["path"] != path.name or sha256(path) != info["sha256"]:
            raise ValueError(f"{path}: canonical file checksum mismatch")
        time_col = "funding_time_utc" if kind == "funding" else "open_time_utc"
        pieces = []
        for frame in pd.read_csv(path, dtype=str, chunksize=100000):
            columns = ({time_col, "funding_time_ms", "funding_rate", "mark_price", "mark_price_source"} if kind == "funding"
                       else {time_col, "open", "high", "low", "close", "volume"})
            if columns - set(frame.columns):
                raise ValueError(f"{path}: missing legacy columns {sorted(columns - set(frame.columns))}")
            times = pd.to_datetime(frame[time_col], utc=True, errors="raise")
            lower, upper = warm_start, end
            if kind == "funding":
                if not frame.funding_time_ms.str.fullmatch(r"\d+").fillna(False).all():
                    raise ValueError(f"{path}: funding_time_ms must be integer native epoch milliseconds")
                actual = pd.to_datetime(frame.funding_time_ms.astype("int64"), unit="ms", utc=True)
                bad = (times != actual) & (times != actual.dt.floor("s"))
                if bad.any():
                    i = bad[bad].index[0]
                    raise ValueError(f"{path}: funding_time_utc display disagrees with native funding_time_ms; "
                                     f"expected {actual.loc[i].isoformat()}, actual display {times.loc[i].isoformat()}")
                # The legacy UTC display loses milliseconds. The native integer,
                # NOT the display nor calendar matching, is execution authority.
                frame[time_col], times = actual, actual
                lower = max(start - MAX_DELAY, VERIFIED_START)
                upper = min(end + MAX_DELAY + pd.Timedelta(nanoseconds=1), VERIFIED_END)
            frame = frame[(times >= lower) & (times < upper)].copy()
            frame = frame.rename(columns={time_col: "funding_time" if kind == "funding" else "open_time",
                                          "mark_price": "funding_mark_price"})
            if kind == "funding":
                if (frame.mark_price_source == "missing").any():
                    bad = frame.loc[frame.mark_price_source == "missing", "funding_time"].iloc[0]
                    raise ValueError(f"{path}: missing Funding Mark Price at {bad}")
            pieces.append(frame)
        normalized[kind] = pd.concat(pieces, ignore_index=True)
        if sha256(path) != info["sha256"]:
            raise ValueError(f"{path}: input changed during conversion")
        source_files.append({"path": str(path), "sha256": info["sha256"]})
    marks = []
    for obj in manifest["funding_authority"]["provenance"]["mark_price_objects"]:
        if utc(obj["end_utc_exclusive"]) <= start or utc(obj["start_utc_inclusive"]) >= end:
            continue
        if "/markPriceKlines/BTCUSDT/1m/" not in obj["path"]:
            raise ValueError("conversion: non-BTCUSDT 1m Mark Price source")
        path = raw_root / obj["path"].removeprefix("/data/")
        frame = checked_mark_zip(path, obj["sha256"])
        marks.append(frame[(frame.open_time >= start) & (frame.open_time < end)])
        source_files.append({"path": str(path), "sha256": obj["sha256"],
                             "official_archive_path": obj["path"], "checksum_file_sha256": sha256(str(path) + ".CHECKSUM")})
    if not marks:
        raise ValueError("conversion: no matching official local Mark Price archives")
    normalized["mark_1m"] = pd.concat(marks, ignore_index=True)  # retain source order; never sort away damage
    for kind, frame in normalized.items():
        df = validate_frame(frame, kind, f"conversion {kind}")
        if kind in {"trade_1m", "mark_1m"}:
            require_grid(df, pd.date_range(start, end, freq="min", inclusive="left"), f"conversion {kind}")
        normalized[kind] = df.reset_index()
    provenance = {"description": "Binance public archives via verified QuantForge schema-7; local read-only conversion",
                  "official_source": "https://data.binance.vision/", "independent_out_of_sample": False,
                  "source_dataset": str(dataset), "dataset_identity_sha256": manifest["sha256"],
                  "source_manifest_file_sha256": sha256(dataset / "manifest.json"),
                  "original_dataset_coverage": manifest["request_range"], "source_files": source_files,
                  "conversion": "UTC columns renamed; decimal prices converted to float64; native funding_time_ms preserved (UTC display may truncate ms); no interpolation or price proxies",
                  "funding_validation": funding_policy(),
                  "funding_boundary_evidence": "retain up to 47ms around start/end within audited scope; execute only actual timestamps in [start,end)",
                  "run_coverage": {"start": start.isoformat(), "end": end.isoformat()},
                  "warmup_start": warm_start.isoformat()}
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".qfs-import-", dir=output.parent))
    try:
        for kind, frame in normalized.items():
            frame.to_parquet(staging / f"{kind}.parquet", index=False)
        provenance["normalized_files"] = {k: {"path": str(output / f"{k}.parquet"),
                                              "sha256": sha256(staging / f"{k}.parquet"), "row_count": len(v)}
                                          for k, v in normalized.items()}
        write_json(staging / "provenance.json", provenance)
        # Apply exactly the same complete coverage/warmup contract as a real run before publication.
        config = Config.from_dict({"strategy": {"name": "ema"}, "symbol": "BTCUSDT",
                                   "start": start, "end": end,
                                   "data": {k: str(staging / f"{k}.parquet") for k in normalized},
                                   "initial_equity": 10000, "position_fraction": .5, "maximum_leverage": 1,
                                   "taker_fee_rate": .0005, "slippage_rate": .0005, "output_dir": str(staging / "unused")})
        load_data(config)
        staging.rename(output)
    except Exception:
        shutil.rmtree(staging)
        raise
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--raw-root", required=True, help="Old data/raw/binance directory (read only)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    try:
        convert(args.dataset, args.raw_root, args.output, args.start, args.end)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"conversion: {exc}\n")
    print(Path(args.output).resolve())


if __name__ == "__main__":
    main()
