import json
from pathlib import Path
import subprocess

import pandas as pd
import pytest

from conftest import save
from qfs.config import Config
from qfs.data import load_data, sha256
from qfs.engine import Result, TRADE_COLUMNS, run_backtest
from qfs.report import metric_summary, write_reports


def metric_result(times, equities, trades=None):
    return Result(pd.DataFrame(trades or [], columns=TRADE_COLUMNS),
                  pd.DataFrame({"time": [t.isoformat() for t in times], "equity": equities}), None, None)


def test_calendar_annualization_and_full_day_sharpe(dataset):
    config, _, _ = dataset(minutes=3 * 1440)
    times = pd.date_range(config.start, config.end, freq="D")
    result = metric_result(times, [10000, 11000, 9900, 10890])
    report = metric_summary(config, result)
    assert report["total_return"] == pytest.approx(.089)
    assert report["annualized_return"] == pytest.approx(1.089 ** (365 / 3) - 1)
    # Hand-audited daily returns +10%, -10%, +10%; sample std=0.1154700538.
    assert report["sharpe"] == pytest.approx(5.515130702591431)
    assert report["sharpe_daily_returns"] == 3
    assert report["maximum_drawdown"] == pytest.approx(.1)


def test_sharpe_excludes_partial_days(dataset):
    config, _, _ = dataset(minutes=4 * 1440)
    raw = config.as_dict() | {"start": "2020-01-26T12:00:00Z", "end": "2020-01-29T12:00:00Z"}
    config = Config.from_dict(raw)
    times = [config.start, pd.Timestamp("2020-01-27T00:00:00Z"), pd.Timestamp("2020-01-28T00:00:00Z"),
             pd.Timestamp("2020-01-29T00:00:00Z"), config.end]
    report = metric_summary(config, metric_result(times, [10000, 9000, 9900, 8910, 15000]))
    assert report["sharpe_daily_returns"] == 2
    assert report["sharpe"] == pytest.approx(0, abs=1e-12)
    assert report["calendar_days"] == 3


@pytest.mark.parametrize("values", [[10000, 10000, 10000], [10000, 0, -100]])
def test_zero_variance_and_nonpositive_annualization(dataset, values):
    config, _, _ = dataset(minutes=2 * 1440)
    report = metric_summary(config, metric_result(pd.date_range(config.start, config.end, freq="D"), values))
    assert report["sharpe"] is None
    if values[-1] <= 0:
        assert report["annualized_return"] is None


def test_trade_metric_definitions_and_initial_peak_drawdown(dataset):
    config, _, _ = dataset()
    net = [100, -50, 0, 200]
    trades = [{"net_pnl": val, "gross_pnl": val + 3, "fees": 5, "slippage": 2,
               "funding": 2, "holding_hours": i + 1} for i, val in enumerate(net)]
    report = metric_summary(config, metric_result([config.start, config.end], [10000, 10250], trades))
    assert report["trade_count"] == 4
    assert report["win_rate"] == .5  # flat transaction is not a winner
    assert report["profit_factor"] == 6
    assert report["average_win_loss_ratio"] == 3
    assert report["average_holding_hours"] == 2.5
    assert report["net_pnl"] == 250
    assert report["gross_pnl"] == 262
    assert report["fees"] == 20
    assert report["slippage_cost"] == 8
    assert report["funding_net"] == 8
    report = metric_summary(config, metric_result([config.start, config.end], [10000, 9000]))
    assert report["maximum_drawdown"] == pytest.approx(.1)
    assert report["win_rate"] is None
    assert report["sharpe"] is None
    assert report["profit_factor"] is None


@pytest.mark.parametrize("name", ["ema", "bollinger"])
def test_cli_config_end_to_end_determinism_manifest(dataset, name):
    strategy = {"name": "ema"} if name == "ema" else {"name": "bollinger", "params": {"window": 3, "std_multiplier": 1}}
    config, _, path = dataset(strategy=strategy, closes={149: 90})
    outputs = []
    command = [str(Path(".venv/bin/qfs").resolve()), "backtest", "--config", str(path)]
    for _ in range(2):
        process = subprocess.run(command, capture_output=True, text=True)
        assert process.returncode == 0, process.stderr
        output = Path(process.stdout.strip())
        assert {p.name for p in output.iterdir()} == {"summary.json", "manifest.json", "trades.csv", "equity.csv"}
        outputs.append(output)
    assert outputs[0] != outputs[1]
    for file in outputs[0].iterdir():
        assert file.read_bytes() == (outputs[1] / file.name).read_bytes()
    manifest = json.loads((outputs[0] / "manifest.json").read_text())
    summary = json.loads((outputs[0] / "summary.json").read_text())
    assert summary["status"] == "completed"
    assert summary["trade_count"] == 1
    assert summary["config"] == config.as_dict()
    assert manifest["config"] == config.as_dict()
    assert len(manifest["code"]["git_commit"]) == 40
    assert manifest["market"] == "Binance BTCUSDT USD-M perpetual"
    assert manifest["data_source"]["independent_out_of_sample"] is False
    for key, file in manifest["data_files"].items():
        assert file["path"] == str(config.data[key])
        assert file["sha256"] == sha256(config.data[key])
        assert file["row_count"] > 0
    equity = pd.read_csv(outputs[0] / "equity.csv")
    trades = pd.read_csv(outputs[0] / "trades.csv")
    assert len(equity) == 5  # initial + 3 minutes + terminal settlement
    assert equity.iloc[-1].equity == pytest.approx(10000 + trades.net_pnl.sum())
    assert "not independent" in manifest["out_of_sample_boundary"]
    assert summary["metric_definitions"]
    assert summary["limitations"]


@pytest.mark.parametrize("failure", ["missing_minute", "insolvency", "bad_json"])
def test_cli_failure_is_nonzero_without_partial_success(dataset, failure):
    config, frames, path = dataset(closes={149: 90})
    if failure == "missing_minute":
        frames["trade_1m"] = frames["trade_1m"].iloc[1:]
        save(config, frames)
    elif failure == "insolvency":
        frames["mark_1m"].loc[0, ["mark_high", "mark_close"]] = 400
        save(config, frames)
    else:
        path.write_text("{ broken JSON")
    process = subprocess.run([str(Path(".venv/bin/qfs").resolve()), "backtest", "--config", str(path)], capture_output=True, text=True)
    assert process.returncode != 0
    assert process.stderr.startswith("qfs:")
    assert not process.stdout
    if failure == "insolvency":
        outputs = list(config.output_dir.glob("run-*"))
        assert len(outputs) == 1
        summary = json.loads((outputs[0] / "summary.json").read_text())
        manifest = json.loads((outputs[0] / "manifest.json").read_text())
        assert summary["status"] == manifest["status"] == "invalid"
        assert summary["invalid_reason"] == "non_positive_equity"
        assert summary["annualized_return"] is None
        assert summary["sharpe"] is None
        assert summary["invalid_time"] == (config.start + pd.Timedelta(minutes=1)).isoformat()
    else:
        assert not config.output_dir.exists()


@pytest.mark.parametrize("net,pf,winrate", [([-10, -20], 0, 0), ([10, 20], None, 1)])
def test_profit_factor_zero_or_undefined_denominator(dataset, net, pf, winrate):
    config, _, _ = dataset()
    trades = [{"net_pnl": n, "gross_pnl": n, "fees": 0, "slippage": 0, "funding": 0,
               "holding_hours": 1} for n in net]
    report = metric_summary(config, metric_result([config.start, config.end], [10000, 10000 + sum(net)], trades))
    assert report["profit_factor"] == pf
    assert report["win_rate"] == winrate
    assert report["average_win_loss_ratio"] is None


def test_flat_strategy_produces_valid_empty_trade_csv(dataset):
    config, frames, _ = dataset(closes={149: 100})
    save(config, frames)
    data = load_data(config)
    output = write_reports(config, data, run_backtest(config, data))
    assert pd.read_csv(output / "trades.csv").empty
    report = json.loads((output / "summary.json").read_text())
    assert report["trade_count"] == 0
    assert report["total_return"] == 0
    assert report["fees"] == 0
