"""Fixed metric definitions and atomic, deterministic report artifacts."""
import json
import math
import platform
from importlib.metadata import version
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
import pandas as pd

from . import CONTRACT_VERSION
from .config import Config
from .engine import Result
from .funding import funding_policy


LIMITATIONS = [
    "Exploratory historical backtest; previously examined QuantForge periods are not independent out-of-sample evidence.",
    "Synthetic fixtures verify correctness only and are never evidence of historical strategy profitability.",
    "1m open/terminal close market-fill approximation; constant adverse slippage and taker fees, no liquidity or queue model.",
    "No exchange quantity step, minimum notional, partial fills or complete margin/liquidation model; not live margin-risk accuracy.",
    "Float64 arithmetic; Funding calendar is limited to audited [2020-01-01,2026-08-01) BTCUSDT UTC 00/08/16, fixed integer-ms delay [0,47]ms; actual timestamps are preserved.",
    "Maximum drawdown is sampled at 1m Mark closes (plus initial and terminal settlement); intraminute Funding/price equity swings can be missed.",
]


def metric_summary(config: Config, result: Result):
    eq = result.equity
    values = eq.equity.to_numpy(dtype=float)
    final = float(values[-1])
    ratio = final / config.initial_equity
    days = (config.end - config.start).total_seconds() / 86400
    annualized = None
    if ratio > 0 and days > 0 and result.invalid_time is None:
        log_growth = math.log(ratio) * 365 / days
        if log_growth <= math.log(np.finfo(float).max):
            annualized = math.expm1(log_growth)
    peaks = np.maximum.accumulate(values)
    drawdown = float(np.max(1 - values / peaks))
    timed = eq.assign(timestamp=pd.to_datetime(eq.time, utc=True)).set_index("timestamp")
    # Times label completed minute boundaries. Last event wins at the terminal boundary.
    boundary = timed[~timed.index.duplicated(keep="last")].equity
    full_days = pd.date_range(config.start.ceil("D"), config.end.floor("D"), freq="D")
    daily_returns = []
    for left, right in zip(full_days[:-1], full_days[1:]):
        if left in boundary.index and right in boundary.index and boundary.loc[left] > 0:
            daily_returns.append(float(boundary.loc[right] / boundary.loc[left] - 1))
    sharpe = None
    if len(daily_returns) >= 2 and result.invalid_time is None:
        std = float(np.std(daily_returns, ddof=1))
        if std > 0:
            sharpe = float(np.mean(daily_returns) / std * math.sqrt(365))
    trades = result.trades
    winners = trades.loc[trades.net_pnl > 0, "net_pnl"]
    losers = trades.loc[trades.net_pnl < 0, "net_pnl"]
    total = lambda col: float(trades[col].sum())
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "invalid" if result.invalid_time else "completed",
        "invalid_time": result.invalid_time, "invalid_reason": result.invalid_reason,
        "initial_equity": config.initial_equity, "final_equity": final,
        "total_return": ratio - 1, "annualized_return": annualized,
        "calendar_days": days, "sharpe": sharpe, "sharpe_daily_returns": len(daily_returns),
        "maximum_drawdown": drawdown, "trade_count": len(trades),
        "win_rate": float(len(winners) / len(trades)) if len(trades) else None,
        "average_win_loss_ratio": float(winners.mean() / abs(losers.mean())) if len(winners) and len(losers) else None,
        "profit_factor": float(winners.sum() / abs(losers.sum())) if len(losers) else None,
        "average_holding_hours": float(trades.holding_hours.mean()) if len(trades) else None,
        "gross_pnl": total("gross_pnl"), "net_pnl": total("net_pnl"),
        "fees": total("fees"), "slippage_cost": total("slippage"), "funding_net": total("funding"),
        "config": config.as_dict(), "limitations": LIMITATIONS, "funding_validation": funding_policy(),
        "metric_definitions": {
            "gross_pnl": "signed_quantity * (exit_fill - entry_fill); adverse slippage already included",
            "net_pnl": "gross_pnl - entry_fee - exit_fee + holding Funding; slippage is NOT deducted twice",
            "annualized_return": "(final_equity / initial_equity) ** (365 / calendar_days) - 1; non-positive, invalid run or overflow => null",
            "sharpe": "full UTC day boundary returns only; sample std ddof=1; sqrt(365), risk-free=0; <2 returns or zero std => null",
            "maximum_drawdown": "max(1 - equity / running_peak), initial + every 1m Mark close + terminal settlement; intraminute event swings are not sampled",
            "equity_timestamps": "initial at start, completed minute at open_time+1m; optional terminal fill at end after last Mark snapshot",
        },
    }


def code_identity():
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True))
        from .data import sha256
        return {"git_commit": sha, "git_dirty": dirty,
                "source_sha256": {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}}
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_dirty": None}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
                          encoding="utf-8", newline="\n")


def write_reports(config, data, result):
    summary = metric_summary(config, result)
    manifest = {"contract_version": CONTRACT_VERSION, "status": summary["status"],
                "invalid_time": result.invalid_time, "invalid_reason": result.invalid_reason,
                "config": config.as_dict(),
                "market": "Binance BTCUSDT USD-M perpetual", "data_files": data.files,
                "coverage": {"start_inclusive": config.start.isoformat(), "end_exclusive": config.end.isoformat()},
                "data_source": config.data_source, "code": code_identity(),
                "runtime": {"python": platform.python_version(),
                            **{name: version(name) for name in ("pandas", "numpy", "pyarrow")}},
                "out_of_sample_boundary": LIMITATIONS[0]}
    config.output_dir.mkdir(parents=True, exist_ok=True)
    # Directory name is deliberately excluded from artifact content. Identical inputs have identical bytes.
    staging = Path(tempfile.mkdtemp(prefix=".qfs-", dir=config.output_dir))
    try:
        write_json(staging / "summary.json", summary)
        write_json(staging / "manifest.json", manifest)
        result.trades.to_csv(staging / "trades.csv", index=False, float_format="%.17g", lineterminator="\n")
        result.equity.to_csv(staging / "equity.csv", index=False, float_format="%.17g", lineterminator="\n")
        output = staging.with_name("run-" + staging.name.removeprefix(".qfs-"))
        staging.rename(output)
        return output
    except Exception:
        shutil.rmtree(staging)
        raise
