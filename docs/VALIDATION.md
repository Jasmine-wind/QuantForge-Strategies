# V1 验收记录

## 交付范围

所有可完成的 V1 验收项已完成，没有因数据/环境阻塞而留下的 V1 项。唯一业务规格 `V1_SPEC.md` 与根目录 `AGENTS.md` 未改。开始时本地 main 只有首个提交、工作区干净；只用 fast-forward 同步已有远端规格到 `dd5cade`，未 reset、未覆盖用户修改，未推送。

| V1 验收项 | 实现 / 验证 | 状态 |
|---|---|---|
| Python 项目、CLI、JSON 配置 | `pyproject.toml`、`uv.lock`、`src/qfs/config.py`、`cli.py`、`configs/*.json` | 完成 |
| 四类本地 Parquet 读取/校验 | `data.py`；UTC、重复/错序、有限数值、OHLC、覆盖、对齐、Funding 缺失 | 完成 |
| 旧源核验与小型只读适配 | `import_quantforge.py`；manifest 身份、canonical SHA、ZIP/CHECKSUM、来源记录 | 完成 |
| EMA20/50 和布林带，无前视 | `strategies.py`；递推 EMA、ddof=0、穿越相等边界、Flat 初态、预热、未完成 K 线不入信号 | 完成 |
| 单仓、1m 执行及账户 | `engine.py`；close_time→Open、Long/Short 不利滑点、双边费用、反手延迟、重新定量 | 完成 |
| Funding/Mark 权益/回撤/终点 | Funding-before-entry/exit、毫秒事件、方向正负、Mark 浮盈、初始峰值、终点平仓、非正权益失效 | 完成 |
| 绩效、交易、权益与运行清单 | `report.py`；固定口径、null 情况、来源、成本、代码/依赖版本、原子目录 | 完成 |
| 固定输入确定性与 CLI 验证 | 合成 CLI 集成及真实 CLI，两策略逐字节重复验证 | 完成 |
| 来源与限制、README 使用说明 | `README.md`、`DATA_AUDIT.md`，完整参数与限制进入报告 | 完成 |
| 已核验真实历史数据端到端 | Binance 存档，2020-02-01 至 2020-03-01 UTC | 完成（探索性，非独立 OOS） |

## 自动测试

```bash
uv sync --locked --extra test
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src tools
.venv/bin/qfs --help
git diff --check
```

**116 passed，0 failed，0 skipped**。验证环境：Python 3.12.13、Pandas 3.0.6、NumPy 2.5.4、PyArrow 24.0.0、pytest 9.1.1。声明 Python 3.11+，但没有声称所有 Python/OS 组合均实测。

- `test_strategies.py`：EMA 相等边界与逐步递推；布林总体标准差、轨道穿越、中轨退出、持仓忽略相反入场、窗口失效；未来追加数据不改变已有指标。
- `test_data.py`：四输入重复、缺失、错序、坏时间、非有限数值；无效 OHLC/Mark/Funding、负 volume、UTC 转换、分钟/4H 对齐、预热、配置限制与相对路径的调用时目录解析。开发时发现后者使用导入时目录的问题，新增失败回归测试后已修复。
- `test_engine.py`：按手算金额验证双向滑点/双边手续费、Funding 四种符号组合，Mark 浮盈与最大回撤、结束平仓、入场前 Funding、反向前 Funding、下一分钟反向、毫秒 Funding、重新定量、预热不入场、未来未完成 K 线不改变结果、失效锁定、两方向布林退出。
- `test_event_boundaries.py`：4H 完成前不成交、缺失确切成交分钟不向后寻找、end 左闭右开、末分钟反向不越界开仓、四次反向成交费用、下一分钟入场后的 Funding 与带时间的错误信息。
- `test_reports_cli.py`：日历年化、完整日 Sharpe 与部分日剔除、零标准差/非正/失效 null、胜率/盈亏比/PF（含全亏/全赢）、平均持仓、毛净账本、初始峰值；两策略通过配置 CLI 运行及四文件一致、完整 manifest/hash、空交易 CSV、非零失败、明确 invalid 完整报告且不伪装成功。
- `test_importer.py`：只读转换、完整来源、输出不可覆盖/不可写入源数据、manifest/canonical/ZIP 篡改、Mark/Funding 缺失、原始 schema 列缺失、ZIP header、失败无半成品。

所有上述合成 fixtures 仅验证正确性，不作为策略收益证据。

## 真实数据与 CLI

转换命令见 README；首次输出 `data/binance-2020-02`，再次转换到 `data/binance-2020-02-check` 的四份 Parquet 哈希相同。哈希、字段、覆盖与额外 Decimal 核验详见 `DATA_AUDIT.md`。

完成 README 中完整 `provenance.json` 注入配置后：

```bash
.venv/bin/qfs backtest --config .local/real-ema.json
.venv/bin/qfs backtest --config .local/real-bollinger.json
.venv/bin/python tools/verify_real.py
```

两策略均正常退出 0，生成完整 summary/trades/equity/manifest：

| 策略 | 完成交易数 | 权益行数（含初始和终点平仓后） | 重复运行 | 独立核账 |
|---|---:|---:|---|---|
| EMA20/50 | 3 | 41,762 | 4/4 报告字节一致 | 全部交易与权益行通过 |
| Bollinger20/2 | 6 | 41,762 | 4/4 报告字节一致 | 全部交易与权益行通过 |

`tools/verify_real.py` 从 CLI 输出和本地 Funding 数据独立建立现金事件账本，核对每笔持仓 Funding、参考/成交价、双边费用、开仓权益定量，以及每一行钱包/浮盈/权益与期末归属。不是仅检查文件存在，也不直接调用引擎内部重新得到同一个结果。该工具记录运行目录、commit/dirty、报告哈希到 Git 忽略的 `.local/verification.json`。最终在本地干净提交上复跑；具体 commit SHA 在每份 manifest 和该记录中，不将新 SHA 硬编码进受该 SHA 管理的文档。

## 仍有的模型限制 / 非验收目标

- 已探索的旧历史区间不是独立样本外；一个月工程运行不是盈利、显著性或稳健性证明。
- 全量旧数据有 27 条缺失 Funding Mark，1 月 Mark 归档有缺口；没有声称全量 2020–2026 均已回测。
- 常数不利滑点、显式假定的 taker fee、1m Open 与终点 close 近似，没有盘口/流动性/部分成交。
- 没有数量步进、最小名义金额、完整保证金/维持保证金/强平价格与费用，不具备实盘保证金风险精度。
- float64 舍入；Funding 缺失覆盖校验假设 BTCUSDT 的 UTC 00/08/16 结算桶，实际结算保留毫秒时点。
- 没有添加 ML、参数搜索、多资产、Web、数据库、联网下载、账户连接或实盘下单。这些不是未完成 V1，而是明确不在范围内。

本地数据、生成报告和 `.local` 验证记录均未提交；保留在本机用于验收。代码、配置、测试、使用说明与核验记录已本地提交，未推送；旧仓库未修改。
