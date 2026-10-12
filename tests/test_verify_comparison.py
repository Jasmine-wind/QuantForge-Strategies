"""Public CLI regressions; synthetic prices test correctness, not profitability."""
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from conftest import save
from qfs.data import sha256


VERIFIER = Path(__file__).parents[1] / "tools/verify_comparison.py"


def profitable_short_comparison(dataset, tmp_path, closing_price):
    config, frames, _ = dataset()
    frames["trade_1m"].loc[2, ["high", "low", "close"]] = [max(100, closing_price), min(100, closing_price), closing_price]
    frames["mark_1m"].loc[2, ["mark_high", "mark_low", "mark_close"]] = [max(100, closing_price), min(100, closing_price), closing_price]
    save(config, frames)
    raw = config.as_dict()
    del raw["strategy"]
    path = tmp_path / "compare.json"
    path.write_text(json.dumps(raw))
    proc = subprocess.run([sys.executable, "-m", "qfs.cli", "compare", "--config", str(path)],
                          text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    return Path(proc.stdout.strip())


def verify_cli(output, audit):
    return subprocess.run([sys.executable, str(VERIFIER), "--run", str(output), "--output", str(audit)],
                          text=True, capture_output=True)


def test_short_positive_return_overflow_full_comparison_verifies(dataset, tmp_path):
    output = profitable_short_comparison(dataset, tmp_path, 110)
    payload = json.loads((output / "comparison.json").read_text())
    # Hand calculation: 50 contracts * (110 - 100) => 10500; three minutes.
    # 1.05 ** 175200 - 1 is not representable as float64, but the run is valid.
    assert len(payload["members"]) == 12
    for member in payload["members"]:
        summary = member["summary"]
        assert summary["status"] == "completed"
        if member["member"] in {"ema_20_50", "btcusdt_perpetual_long_hold"}:
            assert summary["final_equity"] == 10500
            assert summary["annualized_return"] is None
        elif member["member"] == "usdt_cash":
            assert summary["annualized_return"] == 0
        else:
            assert summary["final_equity"] == 9500
            assert summary["annualized_return"] == -1  # negative log-growth underflow is valid
    audit = tmp_path / "verification.json"
    checked = verify_cli(output, audit)
    assert checked.returncode == 0, checked.stderr
    evidence = json.loads(audit.read_text())
    assert len(evidence["members"]) == 12
    assert len(evidence["artifact_sha256"]) == 52
    assert all(row["period_rows"] == 2 for row in evidence["members"])


def replace_reported_annualized(output, value):
    """Corrupt only the reported metric, refreshing integrity hashes so the
    verifier must reject the metric itself, not a stale checksum or copy.
    """
    payload = json.loads((output / "comparison.json").read_text())
    member = payload["members"][0]  # base EMA
    path = output / member["raw_report"] / "summary.json"
    summary = json.loads(path.read_text())
    summary["annualized_return"] = value
    path.write_text(json.dumps(summary))
    member["summary"] = summary
    member["artifact_sha256"]["summary.json"] = sha256(path)
    csv_path = output / "comparison.csv"
    rows = pd.read_csv(csv_path, float_precision="round_trip")
    rows.loc[0, "annualized_return"] = float("nan") if value is None else value
    rows.to_csv(csv_path, index=False, float_format="%.17g", lineterminator="\n")
    payload["artifact_sha256"]["comparison.csv"] = sha256(csv_path)
    (output / "comparison.json").write_text(json.dumps(payload))


@pytest.mark.parametrize("closing_price", [100.1, 100, 99.9])
def test_representable_annualized_cannot_be_reported_as_null(dataset, tmp_path, closing_price):
    output = profitable_short_comparison(dataset, tmp_path, closing_price)
    summary = json.loads((output / "comparison.json").read_text())["members"][0]["summary"]
    assert summary["annualized_return"] is not None
    # First accept the intact, numerically computed report for every member.
    intact = verify_cli(output, tmp_path / "intact.json")
    assert intact.returncode == 0, intact.stderr
    replace_reported_annualized(output, None)
    audit = tmp_path / "corrupted.json"
    rejected = verify_cli(output, audit)
    assert rejected.returncode != 0
    assert "unexpected null for representable annualized_return" in rejected.stderr
    assert not audit.exists()


def test_overflow_requires_null_not_a_finite_reported_number(dataset, tmp_path):
    output = profitable_short_comparison(dataset, tmp_path, 110)
    replace_reported_annualized(output, 123.0)
    audit = tmp_path / "corrupted.json"
    rejected = verify_cli(output, audit)
    assert rejected.returncode != 0
    assert "annualized_return must be null for float64 overflow" in rejected.stderr
    assert not audit.exists()


def test_representable_annualized_still_compares_the_numeric_value(dataset, tmp_path):
    output = profitable_short_comparison(dataset, tmp_path, 100)
    replace_reported_annualized(output, 123.0)  # exact expected value is zero
    audit = tmp_path / "corrupted.json"
    rejected = verify_cli(output, audit)
    assert rejected.returncode != 0
    assert "AssertionError: (123.0, 0.0)" in rejected.stderr
    assert not audit.exists()
