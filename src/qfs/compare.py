"""Four fixed members, three cost hypotheses, one validated market snapshot."""
import json
from pathlib import Path
import shutil
import tempfile

import pandas as pd

from . import CONTRACT_VERSION
from .config import Config
from .data import load_data, sha256
from .engine import run_backtest
from .periods import PERIOD_DEFINITIONS, period_rows
from .report import LIMITATIONS, code_identity, write_json, write_report_files


COMPARE_VERSION = "qfs-compare-v2-stage1.0"
MEMBERS = (
    ("ema_20_50", {"name": "ema", "params": {"fast": 20, "slow": 50}}),
    ("bollinger_20_2", {"name": "bollinger", "params": {"window": 20, "std_multiplier": 2.0}}),
    ("usdt_cash", {"name": "cash", "params": {}}),
    ("btcusdt_perpetual_long_hold", {"name": "btc_perpetual_long_hold", "params": {}}),
)
SCENARIOS = (("base", 1, 1), ("slippage_x2", 1, 2), ("fee_and_slippage_x2", 2, 2))
METRICS = ("status", "initial_equity", "final_equity", "net_pnl", "total_return", "annualized_return",
           "maximum_drawdown", "sharpe", "sharpe_daily_returns", "calendar_days", "trade_count",
           "gross_pnl", "fees", "slippage_cost", "funding_net")


def load_compare_config(path):
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "strategy" in raw:
        raise ValueError("compare config: expected shared configuration without strategy; members are fixed")
    return Config.from_dict(raw | {"strategy": MEMBERS[0][1]}, path.parent)


def member_configs(shared):
    """Validate all effective costs/configurations before running any member."""
    runs = []
    for scenario, fee_multiple, slip_multiple in SCENARIOS:
        for member, strategy in MEMBERS:
            try:
                config = Config.from_dict(shared.as_dict() | {
                    "strategy": strategy, "taker_fee_rate": shared.taker_fee_rate * fee_multiple,
                    "slippage_rate": shared.slippage_rate * slip_multiple})
            except (ValueError, TypeError) as exc:
                raise ValueError(f"compare {scenario}/{member}: {exc}") from exc
            runs.append((scenario, member, config))
    return runs


def markdown_report(shared, full_rows, periods):
    def number(value, percent=False):
        if value is None:
            return "n/a"
        return f"{value * 100:.3f}%" if percent else f"{value:.4f}"

    lines = ["# 探索性历史比较 / 分期验证", "",
             f"UTC [{shared.start.isoformat()}, {shared.end.isoformat()})；初始 {shared.initial_equity:g} USDT，仓位比例 {shared.position_fraction:g}。",
             "四个独立账户，不是组合；旧 QuantForge 已见数据，不是独立样本外或盈利证明。",
             "BTCUSDT perpetual long hold 是 U 本位永续多头持有（不是现货）；USDT cash 不计利息。", "",
             "## 全区间 / 固定成本假设", "",
             "base 使用原配置；slippage_x2 仅滑点×2；fee_and_slippage_x2 两者×2。每组完整重跑，Funding 原始事件不变，金额随持仓变化。不是交易所实际费率。", "",
             "| 场景 | 成员 / 原始报告 | 净收益 | 年化 | 最大回撤 | Sharpe | 交易 | 费用 | 滑点 | Funding净额 |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in full_rows:
        metrics = [number(row[k], k in {"total_return", "annualized_return", "maximum_drawdown"})
                   for k in ("total_return", "annualized_return", "maximum_drawdown", "sharpe", "trade_count",
                             "fees", "slippage_cost", "funding_net")]
        lines.append(f"| {row['scenario']} | [{row['member']}]({row['raw_report']}/summary.json) | " + " | ".join(metrics) + " |")
    lines += ["", "## 基准费用场景的月 / 年片段", "",
              "所有场景的完整分期见 [periods.csv](periods.csv)。账户不重置、不因月末平仓。首尾 partial 只计实际长度、不年化。",
              "边界权益为已完成分钟状态；运行 end 包含终点平仓费用。回撤使用该片段局部峰值和分钟收盘采样，可能遗漏分钟内波动。",
              "不把整笔交易或 Funding 归入平仓月份。", "",
              "| 成员 | 频率 / 期间 | 完整期 | 有效天数 | 净权益变动 | 收益 | 局部回撤 |",
              "|---|---|---|---:|---:|---:|---:|"]
    for row in periods:
        if row["scenario"] == "base":
            lines.append(f"| {row['member']} | {row['frequency']} {row['period']} | "
                         f"{'complete' if row['complete'] else 'partial'} | {row['calendar_days']:.6g} | "
                         f"{number(row['equity_change'])} | {number(row['return'], True)} | {number(row['maximum_drawdown'], True)} |")
    lines += ["", "## 可复核信息及限制", "",
              "[comparison.json](comparison.json) 记录共享配置、12个有效配置、数据/原报告哈希、代码/依赖版本和口径；没有按收益筛掉失败成员。",
              *[f"- {text}" for text in LIMITATIONS], ""]
    return "\n".join(lines)


def write_comparison(shared, data, directory):
    """Run/write into a caller-owned empty private directory; never publish.

    The caller validates the fixed EMA preload via load_data before this seam.
    Stable effective config paths are independent of the private destination.
    """
    configs = member_configs(shared)
    identity = code_identity()
    staging = Path(directory)
    staging.mkdir(parents=True, exist_ok=True)
    if any(staging.iterdir()):
        raise ValueError(f"{staging}: comparison destination must be empty")
    full_rows, periods, members = [], [], []
    try:
        for scenario, member, config in configs:
            try:
                result = run_backtest(config, data)
                if result.invalid_time:
                    raise ValueError(f"invalid at {result.invalid_time}: {result.invalid_reason}")
                raw_report = f"reports/{scenario}/{member}"
                summary, manifest = write_report_files(config, data, result, staging / raw_report)
                if manifest["code"] != identity:
                    raise ValueError("code identity changed during comparison")
                full_rows.append({"scenario": scenario, "member": member,
                                  "taker_fee_rate": config.taker_fee_rate, "slippage_rate": config.slippage_rate,
                                  **{k: summary[k] for k in METRICS}, "raw_report": raw_report})
                slices = [{"scenario": scenario, "member": member, **r}
                          for r in period_rows(result.equity, config.start, config.end)]
                periods.extend(slices)
                members.append({"scenario": scenario, "member": member, "config": config.as_dict(),
                                "summary": summary, "raw_report": raw_report,
                                "artifact_sha256": {p.name: sha256(p) for p in sorted((staging / raw_report).iterdir())}})
                del result  # retain only small metadata, not twelve full minute curves
            except Exception as exc:
                raise ValueError(f"compare {scenario}/{member}: {type(exc).__name__}: {exc}") from exc
        for key, path in shared.data.items():
            if sha256(path) != data.files[key]["sha256"]:
                raise ValueError(f"compare: {path}: input changed during comparison")
        if code_identity() != identity:
            raise ValueError("compare: code identity changed during comparison")
        shared_config = shared.as_dict()
        del shared_config["strategy"]
        comparison = {"comparison_version": COMPARE_VERSION, "execution_contract_version": CONTRACT_VERSION,
                      "status": "completed", "description": "探索性历史比较 / 分期验证", "market": manifest["market"],
                      "shared_config": shared_config, "data_files": data.files, "data_source": shared.data_source,
                      "code": identity, "runtime": manifest["runtime"],
                      "scenarios": [{"name": s, "fee_multiplier": f, "slippage_multiplier": p,
                                     "taker_fee_rate": shared.taker_fee_rate * f, "slippage_rate": shared.slippage_rate * p}
                                    for s, f, p in SCENARIOS],
                      "members": members, "full_interval_metric_definitions": summary["metric_definitions"],
                      "period_definitions": PERIOD_DEFINITIONS, "periods": periods,
                      "limitations": LIMITATIONS,
                      "benchmark_definitions": {"usdt_cash": "USDT cash, no position or interest; zero return/costs",
                                                "btcusdt_perpetual_long_hold": "BTCUSDT USD-M perpetual long, NOT spot; shared fraction, no rebalance, historical Funding, terminal close"}}
        pd.DataFrame(full_rows).to_csv(staging / "comparison.csv", index=False, float_format="%.17g", lineterminator="\n")
        pd.DataFrame(periods).to_csv(staging / "periods.csv", index=False, float_format="%.17g", lineterminator="\n")
        (staging / "report.md").write_text(markdown_report(shared, full_rows, periods), encoding="utf-8", newline="\n")
        comparison["artifact_sha256"] = {f: sha256(staging / f) for f in ("comparison.csv", "periods.csv", "report.md")}
        write_json(staging / "comparison.json", comparison)
        return comparison
    except BaseException:
        shutil.rmtree(staging)
        raise


def run_comparison(shared):
    # Preserve standalone fail-before-output validation and the fixed EMA preload.
    shared = Config.from_dict(shared.as_dict() | {"strategy": MEMBERS[0][1]})
    member_configs(shared)
    data = load_data(shared)
    shared.output_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".qfs-compare-", dir=shared.output_dir))
    try:
        write_comparison(shared, data, staging)
        output = staging.with_name("compare-" + staging.name.removeprefix(".qfs-compare-"))
        staging.rename(output)
        return output
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
