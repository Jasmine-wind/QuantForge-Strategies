# V1 / V2 验收记录

## V2 第一阶段验收（基线 ae72a73）

本轮从已验收并已推送的 `ae72a73efa0887077c17156b4082be65290ddf79` 的干净 main 开始；fetch确认远端相同。保留用户修改，不reset，旧QuantForge只读。先新增 `V2_SPEC.md`、更新AGENTS授权范围，再实现；V1_SPEC.md、Funding日程/容差、策略信号、账户/成交顺序和风险采样未放松。

### 功能验收映射

| 项目 | 实现 / 验证 | 状态 |
|---|---|---|
| 公共比较配置 / 固定4成员×3场景 | `compare.py` / CLI；公共四文件、区间、权益、仓位，固定EMA20/50与布林20/2 | 完成 |
| 现金 / 永续多头基准 | `engine.py` 仅扩展目标方向，复用Account、事件时序、成本/Funding及end平仓；可重放配置 | 完成 |
| 全区间与月/年 | 复用V1 summary，`periods.py`截取连续曲线；局部峰值、实际长度、complete/partial | 完成 |
| 成本敏感性完整重跑 | 12个有效配置独立引擎运行；后续数量手算验证，不扣估算成本 | 完成 |
| 原始报告 / 可复核元数据 | 同一V1 report writer；12×4原报告＋4比较文件，稳定相对路径及完整SHA | 完成 |
| 成员失败 / 原子输出 / 确定性 | 非正权益及文件系统失败非零；清理staging，无子集成功；52文件重复 | 完成 |
| V1/Funding回归 | 全部原165测试保留；2020-02财务和CSV与ae72a73输出完全一致 | 完成 |
| 最小CI | `.github/workflows/tests.yml`，Python3.12 / uv.lock / pytest及编译，不依赖行情 | 已配置，本地同命令通过，未声称远端已运行 |
| 本机2020-02 / 较长完整区间 | 全部24组真实账本和分期核账；按数据质量事先选择366天 | 完成，探索性而非独立OOS |

### 自动测试与新增模块

全套 **199 passed，0 failed，0 skipped**，编译 `src tools`、CLI help及`git diff --check`通过；锁定环境沿用V1，未加运行依赖。

- `test_benchmarks.py`：手算quantity/fill/双边费用/滑点/Funding/期末余额；0/1/47ms与费率正负、永续持仓不跟随EMA反向或再平衡、现金零收益、基准参数拒绝。
- `test_compare.py`：CLI及实际子进程端到端、公共输入和场景、全部成员配置可重放、文件SHA/52文件字节确定性、成本影响下一笔quantity的独立手算值、跨月持有及边界Funding归属、真实早期/末场景非正权益、文件系统失败/运行中输入变化清理、非法配置/缺口拒绝。业务测试通过公开接口；失败注入仅在文件系统边界，不mock账户或策略。
- `test_periods.py`：跨月/跨年边界共享、首尾partial、完整闰年12个月、局部峰值、终点双样本/费用、缺失边界失败、月/年复合对应全区间。
- `test_selection.py`：数据质量固定选择规则，12月上限/最早块/同长最早/缺月断块/无长期条件，不以策略结果选择。
- `tools/ledger.py`：提取旧真实验证器的独立现金事件账本并加强实际1m参考价/Mark/费用/滑点/时间网格校验，V1/V2验证工具共用；不是生产回测或另一份账户引擎。
- `tools/verify_comparison.py`：不调用Account/engine/metric_summary/period_rows，从实际报告与价格重建账户/完整日Sharpe/回撤、所有边界和收益复合；在CI合成CLI测试中也实际调用。

运行：

```bash
uv sync --locked --extra test
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src tools
.venv/bin/qfs --help
.venv/bin/python tools/verify_real.py --config-prefix .local/funding-ms \
  --baseline .local/funding-ms-verify-clean.json --output .local/v2-v1-regression.json
.venv/bin/python tools/verify_comparison.py --config .local/v2-compare-feb.json \
  --output .local/v2-feb-verification.json
.venv/bin/python tools/verify_comparison.py --config .local/v2-compare-long.json \
  --output .local/v2-long-verification.json
```

输出JSON要求新路径；不覆盖既有记录。最后两命令各完整比较两次并核账；最终干净提交SHA写入本机记录与每份manifest，不在受其管理的文档硬编码自身SHA。

### 真实输入 / 分期边界

2020-02先完整跑通。随后质量扫描检查50个月，先保存 `.local/v2-window-selection.json`，按最早连续12完整月固定规则选择 **[2023-03-01,2024-03-01) UTC**，不是收益挑选。缺口、排除理由、所选输入SHA/覆盖详见 `DATA_AUDIT.md`。未检查的后续月份及2026-08没有被当作合格。

| 运行 | 天数 | 月 / 年片段（每成员每场景） | 权益行数（现金 / 其余终点仍持仓） | 分期CSV总行数 |
|---|---:|---|---:|---:|
| 2020-02-01～03-01 | 29 | 1完整月 / 1部分年 | 41761 / 41762 | 24 |
| 2023-03-01～2024-03-01 | 366 | 12完整月 / 2部分年 | 527041 / 527042 | 168 |

长区间2023年片段306天，2024年片段60天，首尾不是完整年度；不按365天补全。持续持仓跨月不退出，原报告保留整个交易，分期只归属实际权益变动，12个月复合及2年片段复合都对应原全区间净收益。

### 真实结果（不是盈利判据）

| 区间 / 成员 | base期末权益USDT | base净收益 | 分钟收盘最大回撤 | base交易数 | 滑点×2期末 | 两成本×2期末 |
|---|---:|---:|---:|---:|---:|---:|
| 2020-02 EMA | 10109.549173 | 1.0955% | 7.7588% | 3 | 10095.056755 | 10080.255640 |
| 2020-02 布林 | 9896.089673 | −1.0391% | 5.6706% | 6 | 9867.001262 | 9837.645786 |
| 2020-02 USDT现金 | 10000 | 0 | 0 | 0 | 10000 | 10000 |
| 2020-02 永续多头持有 | 9312.539878 | −6.8746% | 11.2755% | 1 | 9308.110181 | 9303.336986 |
| 366天 EMA | 12946.852523 | 29.4685% | 16.9269% | 35 | 12717.906525 | 12495.530434 |
| 366天 布林 | 6076.262151 | −39.2374% | 41.8720% | 79 | 5835.207608 | 5605.527984 |
| 366天 USDT现金 | 10000 | 0 | 0 | 0 | 10000 | 10000 |
| 366天 永续多头持有 | 17493.295123 | 74.9330% | 15.0714% | 1 | 17480.448152 | 17471.346141 |

四个独立账户均初始10000、名义比例50%、maximum_leverage1；base fee/slippage各0.0005。永续并非100%资金现货基准。完整年化/Sharpe/成本/Funding见生成文件；例如长区间base Sharpe EMA约1.2890、布林−2.4250、永续2.2204、现金null；base Funding净额分别−209.287851、77.740172、−714.829360及0。费用改变后续数量，所以场景Funding金额可变；不误称历史费率被修改。

成功标准是契约、完整成员、数据完整性、独立账本、所有分期及确定性检查，不是哪个成员盈利。布林在该区间明显亏损也完整保留，没有删掉或换月份。

### 交付边界 / 未完成项

本轮所有可完成的功能、测试、真实运行及核账均完成；唯一尚未实际执行的是**远端GitHub Actions**，因为本轮按要求只本地提交、不推送，不能伪造CI记录。12个月是预先固定的资源上限，不代表验证全部2020～2026。仍是旧已见数据、有限窗口、常数成本/1m成交、float64及不完整保证金模型，非独立OOS、非显著性或盈利证明；分钟内风险仍可能漏采样。

行情、报告、本机配置和质量/核账JSON留在Git忽略目录，不提交。旧仓库HEAD及工作区未变；本轮仅本地代码提交，等待验收后再决定推送。

## V1 交付范围（历史记录）

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

本地数据、生成报告和 `.local` 验证记录均未提交；保留在本机用于验收。V1初始交付 `fa45603` 及后续 Funding修复 `ae72a73` 均已按用户要求推送；以上V1历史验证已完成。V2新工作仅本地提交，等待本轮验收；旧仓库未修改。
