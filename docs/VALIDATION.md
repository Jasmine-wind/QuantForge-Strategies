# V1 验收记录

## 交付范围

本记录包含对已审查 `fa45603910da3fa9343ff0375f2c2a5b5815379a` 的 Funding 验收修复。该提交随后按用户要求推送；本轮开始于同一提交的干净 `main`，fetch 确认无后续远端提交。在原代码上复现两个反例及额外发现的毫秒转换缺陷后已修复，所有可完成的本轮验收项均通过。唯一业务规格 `V1_SPEC.md` 与根目录 `AGENTS.md` 未改，未 reset、未覆盖用户修改，旧仓库只读。本轮仅做本地提交，不推送。

| V1 验收项 | 实现 / 验证 | 状态 |
|---|---|---|
| Python 项目、CLI、JSON 配置 | `pyproject.toml`、`uv.lock`、`src/qfs/config.py`、`cli.py`、`configs/*.json` | 完成 |
| 四类本地 Parquet 读取/校验 | `data.py` / `funding.py`；UTC、重复/错序、OHLC、覆盖、Funding 固定计划/一对一/容差/缺失/边界 | 完成 |
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

**165 passed，0 failed，0 skipped**。验证环境：Python 3.12.13、Pandas 3.0.6、NumPy 2.5.4、PyArrow 24.0.0、pytest 9.1.1。声明 Python 3.11+，但没有声称所有 Python/OS 组合均实测。

- `test_strategies.py`：EMA 相等边界与逐步递推；布林总体标准差、轨道穿越、中轨退出、持仓忽略相反入场、窗口失效；未来追加数据不改变已有指标。
- `test_data.py`：四输入重复、缺失、错序、坏时间、非有限数值；无效 OHLC/Mark/Funding、负 volume、UTC 转换、分钟/4H 对齐、预热、配置限制与相对路径的调用时目录解析。开发时发现后者使用导入时目录的问题，新增失败回归测试后已修复。
- `test_engine.py`：按手算金额验证双向滑点/双边手续费、Funding 四种符号组合，Mark 浮盈与最大回撤、结束平仓、入场前 Funding、反向前 Funding、下一分钟反向、毫秒 Funding、重新定量、预热不入场、未来未完成 K 线不改变结果、失效锁定、两方向布林退出。
- `test_event_boundaries.py`：4H 完成前不成交、缺失确切成交分钟不向后寻找、end 左闭右开、末分钟反向不越界开仓、四次反向成交费用、下一分钟入场后的 Funding 与带时间的错误信息。
- `test_reports_cli.py`：日历年化、完整日 Sharpe 与部分日剔除、零标准差/非正/失效 null、胜率/盈亏比/PF（含全亏/全赢）、平均持仓、毛净账本、初始峰值；两策略通过配置 CLI 运行及四文件一致、完整 manifest/hash、空交易 CSV、非零失败、明确 invalid 完整报告且不伪装成功。
- `test_importer.py`：只读转换、完整来源、输出不可覆盖/不可写入源数据、manifest/canonical/ZIP 篡改、Mark/Funding 缺失、原始 schema 列缺失、ZIP header、失败无半成品；另验证原始整数毫秒保留、UTC 显示矛盾/非整数/缺失 epoch 拒绝、边界旁重复不能被转换切片隐藏。
- `test_funding_schedule.py`：**44 个**加载器/CLI/账户顺序回归，覆盖近时标重复、移动 7H/8H、缺失、0/1/15/46/47ms 合法值、提前/48ms/1s/4H/亚毫秒非法值、未知历史范围、区间外重复、边界证据、已有仓位/开仓/平仓/延迟反向顺序、CLI 非零无报告；并锁定分钟收盘回撤可能遗漏分钟内 Funding 波动的既定口径。

所有上述合成 fixtures 仅验证正确性，不作为策略收益证据。原有需人为安排 04:00/04:01 额外 Funding 的两个账户测试保留，改为直接通过 `tests/conftest.py::engine_data` 向公共引擎接口提供明确的 synthetic-only 事件，而非要求历史加载器接受不合法的日程；没有删测、跳过或放宽真实校验。另一个终点集成测试改用合法 08:00 边界，继续通过真实加载器验证。

## 真实数据与 CLI

转换命令见 README。保留首次交付的 `data/binance-2020-02` 与 `-check` 原样用于对照；新版实际使用 `data/binance-2020-02-ms`，不覆盖旧行情或本机配置。新 Funding 文件保留 88 条（87 条执行事件 + 1 条 end 边界证据），88/88 原始毫秒时间/rate/Mark 逐条核对，2 月 15 条非零毫秒全部保留。其他三份 Parquet 哈希不变。官方原始计划、来源、哈希及 Decimal 核验详见 `DATA_AUDIT.md`。

完成 README 中完整 `provenance.json` 注入配置后：

```bash
.venv/bin/qfs backtest --config .local/funding-ms-ema.json
.venv/bin/qfs backtest --config .local/funding-ms-bollinger.json
.venv/bin/python tools/verify_real.py --config-prefix .local/funding-ms \
  --output .local/funding-ms-verify.json
# 原始固定输入对照（使用保留的原配置/先前验证记录）
.venv/bin/python tools/verify_real.py --baseline .local/funding-fix-baseline.json \
  --output .local/funding-original-verify.json
```

两策略均正常退出 0，生成完整 summary/trades/equity/manifest：

| 策略 | 完成交易数 | 权益行数（含初始和终点平仓后） | 重复运行 | 独立核账 |
|---|---:|---:|---|---|
| EMA20/50 | 3 | 41,762 | 4/4 报告字节一致 | 全部交易与权益行通过 |
| Bollinger20/2 | 6 | 41,762 | 4/4 报告字节一致 | 全部交易与权益行通过 |

`tools/verify_real.py` 从 CLI 输出和本地 Funding 数据独立建立现金事件账本，核对每笔持仓 Funding、参考/成交价、双边费用、开仓权益定量，以及每一行钱包/浮盈/权益与期末归属。不是仅检查文件存在，也不直接调用引擎内部重新得到同一个结果。该工具记录运行目录、commit/dirty、报告哈希到 Git 忽略的 `.local/verification.json`。本轮工具增加可选 config-prefix/output/baseline 参数，便于保留旧本机配置、记录和报告；默认入口兼容。最终在本地干净提交上复跑；具体 commit SHA 在每份 manifest 和验证记录中，不将新 SHA 硬编码进受该 SHA 管理的文档。

## Funding 修复规则、反例与真实前后对照

固定规则为 `btc-usdt-native-8h-2020-2026-r1`，回测口径版本 `qfs-v1.1`。只适用 `[2020-01-01,2026-08-01)` UTC BTCUSDT，UTC 00/08/16 计划，整数毫秒延迟 `[0,+47]ms`，每个应有事件恰好一条；数据中每条记录均匹配合法事件，未知时期拒绝。依据为 79 个原始 ZIP / 7,212 条完整日程、原始字段 `funding_interval_hours=8` 和原始 `calc_time/rate` 与 canonical 的精确重放，不从候选输入调容差。2026-08 原始 ZIP 本机不可用，故该月明确在支持范围外，不用 canonical 显示列替代核验。

两个加载器回归最初均失败（`DID NOT RAISE`），额外的时间转换回归也先失败后修复。读取 Git 中审查版加载器到内存，未切换或覆盖工作区，复现了原始金额：

| 合成反例（只检验错误） | 审查版错误结果 | 修复后 |
|---|---|---|
| 08:00 与 08:00.047 同一次结算 | Funding −100、期末 9900（正常为 −50/9950） | duplicate Funding settlement；CLI 1，无报告 |
| 应在 00:00 的记录移动至 07:00 | 错误给新持仓收费 −50、期末 9950（正常为 0/10000） | off-schedule Funding；CLI 1，无报告 |

错误均包含文件、expected 候选时点及 actual 原记录；缺失则提供预期及附近实际记录。整个输入文件先校验，不先丢弃边界/区间外异常。执行只按原始实际时间 `[start,end)`，不去重、移动时间或补零。匹配函数要求有与区间相交的 `[T,T+47ms]` 窗口证据；证据在区间外时不收费，缺证据也不猜为零。0ms 在同点订单前结算；合法 +ms 可能位于订单后，测试区分其持仓归属。

**固定输入对照：**用原 2020-02 Parquet 与原配置运行严格加载器，两个策略的 `trades.csv`、`equity.csv` 逐字节等于 `fa45603` 的先前真实输出，所有原财务指标不变；summary/manifest 的契约说明、代码 SHA 和校验元数据按新版更新，不要求跨代码版本这两份元数据文件字节相同。

**原始时间恢复对照：**旧适配器把 `funding_time_utc` 显示列当作实际时间；新适配器使用权威整数 `funding_time_ms`。这不是同一输入文件，因此不能伪称财务结果不变。账本复核值如下（不是盈利证据）：

| 策略 | 原截秒输入期末权益 | 原生毫秒输入期末权益 | 原 Funding 净额 → 原生毫秒 Funding 净额 |
|---|---:|---:|---:|
| EMA | 10109.05654113648 | 10109.549172679623 | 50.57148921366685 → 51.038900584913485 |
| Bollinger | 9898.984062621224 | 9896.08967291409 | 25.774464602698917 → 22.8590027356865 |

原因可逐笔追踪：2020-02-20 00:00:00.004 的结算发生在平仓后，旧输入错误在 00:00 给旧持仓记账；2020-02-25 16:00:00.001 则发生在布林开仓后，旧输入漏掉该新持仓费用。随后权益定量、费用/净额会传递变化。两种新输入各重复两次，四份报告字节一致，全部交易及 41,762 行权益独立核账通过。真实回撤数值可因正确 Funding 归属变化而改变，但采样算法未变。

## 仍有的模型限制 / 非验收目标

- 已探索的旧历史区间不是独立样本外；一个月工程运行不是盈利、显著性或稳健性证明。
- 全量旧数据有 27 条缺失 Funding Mark，1 月 Mark 归档有缺口；没有声称全量 2020–2026 均已回测。
- 常数不利滑点、显式假定的 taker fee、1m Open 与终点 close 近似，没有盘口/流动性/部分成交。
- 没有数量步进、最小名义金额、完整保证金/维持保证金/强平价格与费用，不具备实盘保证金风险精度。
- float64 舍入；Funding 计划与整数 `[0,+47]ms` 延迟只限于原始已核验时期，2019 和 2026-08 及以后不受支持，需要另行核验才能扩展，不能从待校验数据自动放宽。
- 最大回撤仍为初始 + 分钟 Mark close + 终点结算采样，可能遗漏分钟内 Funding/价格事件波动；本轮未扩展风险引擎或添加事件级峰谷采样。
- 没有添加 ML、参数搜索、多资产、Web、数据库、联网下载、账户连接或实盘下单。这些不是未完成 V1，而是明确不在范围内。

本地数据、生成报告和 `.local` 验证记录均未提交；保留在本机用于验收。上一版 `fa45603` 已按用户要求推送；本轮代码、通用相对路径示例配置、测试、说明与审计工具仅本地提交，等待用户验收后决定推送；旧仓库未修改。
