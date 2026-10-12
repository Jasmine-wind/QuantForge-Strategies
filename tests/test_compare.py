"""Comparison CLI/behavior tests using fixed synthetic correctness data only."""
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from conftest import save
from qfs import compare
from qfs.cli import main
from qfs.config import Config
from qfs.data import load_data, sha256
from qfs.engine import run_backtest
from qfs.report import write_report_files


def comparison_config(config, path):
    raw = config.as_dict()
    del raw["strategy"]
    path.write_text(json.dumps(raw))
    return path


def test_cli_shared_inputs_replayable_members_hashes_and_deterministic_tree(dataset, capsys, tmp_path):
    config, _, _ = dataset(fee=.001, slip=.01)
    path = comparison_config(config, tmp_path / "compare.json")
    outputs = []
    for _ in range(2):
        assert main(["compare", "--config", str(path)]) == 0
        outputs.append(Path(capsys.readouterr().out.strip()))
    trees = [{str(p.relative_to(o)): p.read_bytes() for p in o.rglob("*") if p.is_file()} for o in outputs]
    assert trees[0] == trees[1]
    assert len(trees[0]) == 4 + 12 * 4
    output = outputs[0]
    payload = json.loads((output / "comparison.json").read_text())
    assert payload["status"] == "completed"
    assert len(payload["members"]) == 12
    assert [m["member"] for m in payload["members"][:4]] == [m for m, _ in compare.MEMBERS]
    assert [s["name"] for s in payload["scenarios"]] == [s for s, _, _ in compare.SCENARIOS]
    assert "strategy" not in payload["shared_config"]
    for member in payload["members"]:
        actual = Config.from_dict(member["config"])
        for key in ("data", "symbol", "start", "end", "initial_equity", "position_fraction", "maximum_leverage", "output_dir"):
            assert member["config"][key] == config.as_dict()[key]
        costs = next(s for s in payload["scenarios"] if s["name"] == member["scenario"])
        assert actual.taker_fee_rate == costs["taker_fee_rate"]
        assert actual.slippage_rate == costs["slippage_rate"]
        raw = output / member["raw_report"]
        for file, digest in member["artifact_sha256"].items():
            assert sha256(raw / file) == digest
        # Fully reconstructible configuration, including each benchmark.
        replay = tmp_path / "replay" / member["scenario"] / member["member"]
        write_report_files(actual, load_data(actual), run_backtest(actual, load_data(actual)), replay)
        assert (replay / "trades.csv").read_bytes() == (raw / "trades.csv").read_bytes()
        assert (replay / "equity.csv").read_bytes() == (raw / "equity.csv").read_bytes()
    for key, info in payload["data_files"].items():
        assert info["sha256"] == sha256(config.data[key])
    for file, digest in payload["artifact_sha256"].items():
        assert sha256(output / file) == digest
    rows = pd.read_csv(output / "comparison.csv")
    assert len(rows) == 12
    cash = rows[rows.member == "usdt_cash"]
    assert (cash[["net_pnl", "total_return", "fees", "slippage_cost", "funding_net", "maximum_drawdown"]] == 0).all().all()
    assert cash.sharpe.isna().all()
    assert "探索性历史比较 / 分期验证" in (output / "report.md").read_text()
    assert not list(config.output_dir.glob(".qfs-compare-*"))


def test_complete_cost_scenarios_change_future_sizing_not_just_final_cost(dataset):
    config, _, _ = dataset(minutes=242, closes={150: 50}, fee=.001, slip=.01)
    output = compare.run_comparison(config)
    payload = json.loads((output / "comparison.json").read_text())
    assert len(payload["members"]) == 12
    for member in payload["members"]:
        raw = output / member["raw_report"]
        manifest = json.loads((raw / "manifest.json").read_text())
        assert manifest["data_files"] == payload["data_files"]
    def trades_for(scene):
        member = next(m for m in payload["members"] if m["scenario"] == scene and m["member"] == "ema_20_50")
        return pd.read_csv(output / member["raw_report"] / "trades.csv", float_precision="round_trip")
    base, slip, both = [trades_for(s) for s in ("base", "slippage_x2", "fee_and_slippage_x2")]
    for trades, slippage, fee in ((base, .01, .001), (slip, .02, .001), (both, .02, .002)):
        assert len(trades) == 2
        first, second = trades.iloc[0], trades.iloc[1]
        expected_wallet = 10000 + first.gross_pnl - first.fees + first.funding
        assert second.quantity * second.entry_fill == pytest.approx(expected_wallet * .5)
        assert second.entry_fill == 100 * (1 - slippage)
        assert second.entry_fee == pytest.approx(second.quantity * second.entry_fill * fee)
    assert base.iloc[1].quantity == pytest.approx(49.95499549954995)
    assert slip.iloc[1].quantity == pytest.approx(49.96998799519808)
    assert both.iloc[1].quantity == pytest.approx(49.91996798719488)
    assert both.iloc[1].quantity != slip.iloc[1].quantity
    assert slip.iloc[1].quantity != base.iloc[1].quantity
    # Fee/slippage change quantities and subsequent P&L, not just a deducted estimate.
    assert both.iloc[1].gross_pnl != slip.iloc[1].gross_pnl


def test_cross_month_hold_boundary_funding_and_no_period_liquidation(dataset, tmp_path):
    config, frames, _ = dataset(minutes=4, fee=.001)
    start = pd.Timestamp("2020-01-31T23:58Z")
    end = start + pd.Timedelta(minutes=4)
    shift = start - config.start
    for key in ("trade_1m", "mark_1m"):
        frames[key]["open_time"] += shift
    frames["bars_4h"]["open_time"] += pd.Timedelta(days=6)
    earlier = frames["bars_4h"].iloc[[0]].copy()
    earlier["open_time"] -= pd.Timedelta(hours=4)
    frames["bars_4h"] = pd.concat([earlier, frames["bars_4h"]], ignore_index=True)
    frames["funding"] = pd.DataFrame({"funding_time": [pd.Timestamp("2020-02-01T00:00Z")],
                                      "funding_rate": [.01], "funding_mark_price": [100]})
    config = Config.from_dict(config.as_dict() | {"start": start, "end": end})
    save(config, frames)
    output = compare.run_comparison(config)
    payload = json.loads((output / "comparison.json").read_text())
    member = next(m for m in payload["members"] if m["scenario"] == "base" and m["member"] == "btcusdt_perpetual_long_hold")
    trades = pd.read_csv(output / member["raw_report"] / "trades.csv")
    assert len(trades) == 1 and trades.iloc[0].holding_hours == pytest.approx(4 / 60)
    assert trades.iloc[0].exit_time == end.isoformat()
    assert trades.iloc[0].funding == -50
    slices = [r for r in payload["periods"] if r["scenario"] == "base" and r["member"] == member["member"] and r["frequency"] == "month"]
    jan, feb = slices
    assert jan["equity_change"] == -5  # entry fee belongs to January
    assert jan["end_equity"] == feb["start_equity"] == 9995  # before Feb 00:00 Funding
    assert feb["equity_change"] == -55  # Feb Funding + terminal exit fee
    assert not jan["complete"] and not feb["complete"]
    assert (1 + jan["return"]) * (1 + feb["return"]) == pytest.approx(9940 / 10000)


@pytest.mark.parametrize("failure", ["write", "changed_input"])
def test_filesystem_failure_aborts_cleans_staging_and_cli_nonzero(dataset, monkeypatch, capsys, tmp_path, failure):
    config, _, _ = dataset()
    path = comparison_config(config, tmp_path / "compare.json")
    original_open, original_write = Path.open, Path.write_text
    reads = 0
    def open_file(self, mode="r", *args, **kwargs):
        nonlocal reads
        if self == config.data["funding"] and mode == "rb":
            reads += 1
            if failure == "changed_input" and reads == 3:
                with original_open(self, "ab") as f:
                    f.write(b"changed")
        return original_open(self, mode, *args, **kwargs)
    def write_file(self, *args, **kwargs):
        if failure == "write" and "usdt_cash" in self.parts and self.name == "summary.json":
            raise OSError("deliberate filesystem write failure")
        return original_write(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(Path, "write_text", write_file)
    assert main(["compare", "--config", str(path)]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert ("base/usdt_cash" if failure == "write" else "input changed") in captured.err
    assert not list(config.output_dir.iterdir())


@pytest.mark.parametrize("change", [{"strategy": {"name": "ema"}}, {"members": []}, {"scenarios": []}, {"slippage_rate": .5}, {"taker_fee_rate": .5}])
def test_invalid_comparison_configuration_fails_before_publication(dataset, tmp_path, capsys, change):
    config, _, _ = dataset()
    raw = config.as_dict()
    del raw["strategy"]
    path = tmp_path / "compare.json"
    path.write_text(json.dumps(raw | change))
    assert main(["compare", "--config", str(path)]) == 1
    assert "qfs:" in capsys.readouterr().err
    assert not config.output_dir.exists()


@pytest.mark.parametrize("rate,expected_scene", [(100, "base"), (1.997, "fee_and_slippage_x2")])
def test_real_account_failure_no_success_subset(dataset, tmp_path, capsys, rate, expected_scene):
    config, frames, _ = dataset(fee=.001)
    frames["funding"].loc[0, "funding_time"] += pd.Timedelta(milliseconds=1)
    frames["funding"].loc[0, "funding_rate"] = rate
    save(config, frames)
    path = comparison_config(config, tmp_path / "compare.json")
    assert main(["compare", "--config", str(path)]) == 1
    error = capsys.readouterr().err
    assert f"{expected_scene}/ema_20_50" in error
    assert "non_positive_equity" in error
    assert (config.end.isoformat() if rate == 1.997 else "00:00:00.001") in error
    assert not list(config.output_dir.iterdir())


def test_subprocess_cli_with_relative_paths_and_no_machine_data(dataset, tmp_path):
    config, _, _ = dataset()
    raw = config.as_dict()
    del raw["strategy"]
    raw["data"] = {k: Path(v).name for k, v in raw["data"].items()}
    raw["output_dir"] = "relative-runs"
    path = tmp_path / "compare.json"
    path.write_text(json.dumps(raw))
    proc = subprocess.run([sys.executable, "-m", "qfs.cli", "compare", "--config", str(path)],
                          cwd=tmp_path, text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    output = Path(proc.stdout.strip())
    assert output.parent == tmp_path / "relative-runs"
    assert len(pd.read_csv(output / "comparison.csv")) == 12
    assert (output / "report.md").is_file()
    verifier = Path(__file__).parents[1] / "tools/verify_comparison.py"
    audit = tmp_path / "audit.json"
    checked = subprocess.run([sys.executable, str(verifier), "--run", str(output), "--output", str(audit)],
                             cwd=tmp_path, text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr
    assert len(json.loads(audit.read_text())["members"]) == 12


def test_source_gap_fails_comparison_not_just_active_strategies(dataset, tmp_path, capsys):
    config, frames, _ = dataset()
    frames["mark_1m"] = frames["mark_1m"].drop(index=1)
    save(config, frames)
    path = comparison_config(config, tmp_path / "compare.json")
    assert main(["compare", "--config", str(path)]) == 1
    assert "missing required timestamp" in capsys.readouterr().err
    assert not config.output_dir.exists()
