"""Synthetic legacy-format fixtures exercise conversion, not historical profits."""
import hashlib
import json
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from qfs.config import Config
from qfs.data import load_data, sha256
from qfs.import_quantforge import checked_mark_zip, convert, verified_manifest


def signed_manifest(folder, identity):
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    value = identity | {"sha256": digest, "version_id": digest[:16]}
    (folder / "manifest.json").write_text(json.dumps(value))
    return value


def legacy_fixture(tmp_path, frames, config):
    folder = tmp_path / "legacy"
    raw = tmp_path / "raw"
    folder.mkdir()
    files = {}
    for key, name in [("bars_4h", "decision_4h"), ("trade_1m", "path_1m"), ("funding", "funding")]:
        frame = frames[key].copy()
        if key == "funding":
            frame = frame.rename(columns={"funding_time": "funding_time_utc", "funding_mark_price": "mark_price"})
            frame["mark_price_source"] = "funding_record"
        else:
            frame = frame.rename(columns={"open_time": "open_time_utc"})
        frame.to_csv(folder / f"{name}.csv", index=False)
        files[name] = {"path": f"{name}.csv", "sha256": sha256(folder / f"{name}.csv")}
    archive_path = "/data/futures/um/monthly/markPriceKlines/BTCUSDT/1m/BTCUSDT-1m-2020-01.zip"
    archive = raw / archive_path.removeprefix("/data/")
    archive.parent.mkdir(parents=True)
    data = []
    for row in frames["mark_1m"].itertuples():
        data.append([int(row.open_time.timestamp() * 1000), row.mark_open, row.mark_high,
                     row.mark_low, row.mark_close, 0, 0, 0, 0, 0, 0, 0])
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("BTCUSDT-1m-2020-01.csv", pd.DataFrame(data).to_csv(index=False, header=False))
    digest = sha256(archive)
    archive.with_name(archive.name + ".CHECKSUM").write_text(f"{digest}  {archive.name}\n")
    identity = {"schema_version": 7, "symbol": "BTCUSDT", "contract_type": "PERPETUAL", "timezone": "UTC",
                "source": "Binance USDⓈ-M public klines", "files": files,
                "request_range": {"start_utc_inclusive": config.start.isoformat(), "end_utc_exclusive": config.end.isoformat()},
                "funding_authority": {"provenance": {"mark_price_objects": [
                    {"path": archive_path, "sha256": digest, "start_utc_inclusive": "2020-01-01T00:00:00Z",
                     "end_utc_exclusive": "2020-02-01T00:00:00Z"}]}}}
    signed_manifest(folder, identity)
    return folder, raw, archive


def test_readonly_conversion_provenance_and_backtest_inputs(dataset, tmp_path):
    config, frames, _ = dataset()
    folder, raw, _ = legacy_fixture(tmp_path, frames, config)
    before = {p: sha256(p) for p in folder.iterdir()}
    output = tmp_path / "normalized"
    source = convert(folder, raw, output, config.start, config.end)
    assert before == {p: sha256(p) for p in folder.iterdir()}
    assert source["independent_out_of_sample"] is False
    assert source["dataset_identity_sha256"] == verified_manifest(folder)["sha256"]
    assert (output / "provenance.json").exists()
    new = Config.from_dict(config.as_dict() | {"data": {k: str(output / f"{k}.parquet") for k in config.data}})
    data = load_data(new)
    assert len(data.trade) == 3
    assert data.mark.iloc[0].mark_close == 100
    for key, info in source["normalized_files"].items():
        assert info["sha256"] == sha256(info["path"])
    with pytest.raises(ValueError, match="new and outside"):
        convert(folder, raw, output, config.start, config.end)


@pytest.mark.parametrize("damage", ["manifest", "canonical", "zip", "missing_mark", "minute_gap", "legacy_columns"])
def test_converter_rejects_tampering_and_missing_data(dataset, tmp_path, damage):
    config, frames, _ = dataset()
    if damage == "minute_gap":
        frames["mark_1m"] = frames["mark_1m"].iloc[1:]
    folder, raw, archive = legacy_fixture(tmp_path, frames, config)
    if damage == "manifest":
        value = json.loads((folder / "manifest.json").read_text())
        value["timezone"] = "Asia/Shanghai"
        (folder / "manifest.json").write_text(json.dumps(value))
    elif damage == "canonical":
        with (folder / "path_1m.csv").open("a") as f:
            f.write("corrupted\n")
    elif damage == "zip":
        with archive.open("ab") as f:
            f.write(b"corrupted")
    elif damage in {"missing_mark", "legacy_columns"}:
        frame = pd.read_csv(folder / "funding.csv")
        if damage == "missing_mark":
            frame["mark_price_source"] = "missing"
            frame["mark_price"] = float("nan")
        else:
            frame = frame.drop(columns="mark_price_source")
        frame.to_csv(folder / "funding.csv", index=False)
        value = json.loads((folder / "manifest.json").read_text())
        value["files"]["funding"]["sha256"] = sha256(folder / "funding.csv")
        signed_manifest(folder, {k: v for k, v in value.items() if k not in {"sha256", "version_id"}})
    output = tmp_path / "normalized"
    with pytest.raises(ValueError):
        convert(folder, raw, output, config.start, config.end)
    assert not output.exists()
    assert not list(tmp_path.glob(".qfs-import-*"))


def test_converter_cannot_write_inside_source(dataset, tmp_path):
    config, frames, _ = dataset()
    folder, raw, _ = legacy_fixture(tmp_path, frames, config)
    for path in [folder / "new", raw / "new"]:
        with pytest.raises(ValueError, match="outside"):
            convert(folder, raw, path, config.start, config.end)
        assert not path.exists()


def test_zip_header_supported_but_checksum_must_match(dataset, tmp_path):
    config, frames, _ = dataset()
    _, _, archive = legacy_fixture(tmp_path, frames, config)
    with zipfile.ZipFile(archive) as z:
        body = z.read(z.namelist()[0]).decode()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("BTCUSDT.csv", "open_time,open,high,low,close,volume,close_time,q,n,t,v,i\n" + body)
    digest = sha256(archive)
    archive.with_name(archive.name + ".CHECKSUM").write_text(f"{digest} {archive.name}")
    frame = checked_mark_zip(archive, digest)
    assert len(frame) == 3
    assert frame.iloc[0].open_time == config.start
    with pytest.raises(ValueError, match="checksum"):
        checked_mark_zip(archive, "0" * 64)
