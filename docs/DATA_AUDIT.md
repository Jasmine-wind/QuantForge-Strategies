# V1 本地数据核验

## 独立官方补充研究（固定2024-03～2026-08）

本轮不使用canonical扫描或身份：官方ZIP/CHECKSUM构成新的路径无关对象身份，完整保留URL、ZIP/校验文件摘要、市场及转换契约。只读复用88个已核验原始对象（合约2024-02预热＋29月×3），无新下载/损坏/缺对象；对象可得性不等于连续分钟质量。acquisition记录 `.local/independent/acquisition/`。

先写V2_SPEC第9节规则，再完整扫描29个月（含请求尾部，不因窗数早停），选择记录 `.local/independent/selection.json`，SHA `91d0b50af74bc3f0a28ce5109908a3bec51d8aed261809e5c2b6c75de6185d65`。重复scan全部JSON字节相同。2024-08因Mark缺2024-08-12 10:02排除；2026-06因Funding实际分钟Mark缺2026-06-29 00:00排除。其余27个月通过含600小时预热、原生Funding/Mark边界的prepare及严格loader。请求范围和逐对象实际首末/行数分开记录，未把请求假冒连续覆盖。

固定最早6连续月规则选得：

| 标签 | UTC [start,end) | 选择原因 |
|---|---|---|
| window-01 | [2024-09-01,2025-03-01) | 2024-03～07仅5月，被8月缺口打断；之后最早6月 |
| window-02 | [2025-03-01,2025-09-01) | 从上窗末尾继续，连续合格6月 |
| window-03 | [2025-09-01,2026-03-01) | 从上窗末尾继续，连续合格6月 |

不足第四窗：2026-03～05只有3月，6月缺口打断，7月只1月；不缩短、不拼接。不是按收益排除。新三窗不重叠旧四窗；仍为探索性历史，不是独立OOS或独立统计样本。

`data/independent-window-{01,02,03}`及`-repeat`各5文件完全一致。干净代码6f6516b运行两次study：`runs/study-nk39lxqo` / `study-cs9jwldu`，各159文件全字节相同；36组全部独立交易/分钟账户/分期/年化null及选择来源核账通过。每窗独立10000初始、50%名义仓位、1倍上限、base fee/slippage各0.0005，固定四成员三场景。证据/manifest/配置/日志 `.local/independent/`，旧数据/报告/选择保留不覆盖，所有生成文件Git忽略。

仅在 QuantForge-Strategies 写入。旧仓库 `../QuantForge` 只读；检查时 Git HEAD 为 `d0e6a5d1ad1e18a711767709d5b827be8af38f7e`，工作区干净。没有复制其研究架构、模型、标签或合成模拟器。

## 找到的真实数据

旧 README、数据契约、canonical manifest 和实际 CSV/ZIP 表明：

- 市场 Binance BTCUSDT USDⓈ-M perpetual，UTC。
- canonical schema 7：`data/versions/e8510e8a3f00fd5d`。
- 总覆盖 `[2020-01-01T00:00:00Z, 2026-08-10T12:00:00Z)`；1m 3,475,440 行，派生 4H 14,481 行，Funding 7,241 行。
- 1m、4H CSV 字段 `open_time_utc,open,high,low,close,volume`；4H 从 240 根完整合约 1m 聚合，而非直接 4H 归档。
- Funding 字段 `funding_time_ms,funding_time_utc,funding_rate,mark_price,mark_price_source`。7,214 个 Mark 来自官方 1m Mark Open，27 个明确 missing；不把 missing 变为零或合约价。
- analytics mirror 有 `decision_4h/path_1m/funding.parquet`，没有完整分钟 Mark 估值表，且旧文档明确其为非正式派生镜像。本次不直接使用镜像。
- 完整 Mark OHLC 在 `data/raw/binance/futures/um/monthly/markPriceKlines/BTCUSDT/1m/*.zip`，12 列 Binance 原始 Kline。旧 Funding manifest 记录源对象路径和 SHA-256；本地还有 `.CHECKSUM`。

以下 canonical 身份及**全文件** SHA-256 已实际核对；身份是去除 `version_id/sha256` 后的 canonical JSON 哈希，不是 manifest 文件字节哈希：

| 项目 | SHA-256 |
|---|---|
| Dataset identity | `e8510e8a3f00fd5d1f9bfd51a331a02c4e2c934b81717acc3e3a53d3870ee21b` |
| manifest 文件 | `e27e61d77ec0b01f452bd9f2a2c67e7021ce71958549351772c1feef59e6b908` |
| decision_4h.csv | `e8036055ee4c7488077dc81a75df247f3ec72721f7907b30d06b58156e6db42b` |
| path_1m.csv | `26d74faf6d841546689fad5c7c624f77f8a0ace299f11609173f2d6b25d2962e` |
| funding.csv | `44d13c1b09ba8cb5cb6b4029cbb052e356d1abb24e5cff1eb3ea3edad8d9f2f8` |

这是对本地存档与已有官方来源记录的核验，没有联网重新下载或把本地 CHECKSUM 当作新的独立来源认证。

## 选择的真实运行区间

`[2020-02-01T00:00:00Z, 2020-03-01T00:00:00Z)`，29 天。

- 官方源：`https://data.binance.vision/data/futures/um/monthly/markPriceKlines/BTCUSDT/1m/BTCUSDT-1m-2020-02.zip`。
- ZIP SHA-256：`8e99768235c8bd120ee25e7020ad3106488440eb41bbabe2935324dc1632a3db`，同时匹配 canonical source object 与本地官方 CHECKSUM。
- 2 月 41,760 分钟 Mark，首末为 02-01 00:00 / 02-29 23:59 UTC，最大相邻差 1 分钟，无缺口/重复。1 月只有 44,611 行（应 44,640），在 01-19 13:38 前有缺口，故不能声称 1 月完整可回测。3 月原始 Mark 44,640 行、分钟连续，仅检查，不作为本次策略区间。
- 4H 预热从 2020-01-07 00:00 UTC 起；转换保留 324 根 4H 和 77,760 根合约 1m（含预热）。有效交易区间合约 1m 为 41,760 根。
- 2 月 Funding 87 条，价格齐全，来自 Mark 1m Open。逐条按事件所在分钟与官方原始 Mark Open 做 **Decimal 精确比较，87/87 一致**。
- 另从 canonical CSV 对预热+运行区间独立重放 `1m → 4H`，检查每个块 240 根唯一连续分钟及 Decimal OHLCV 聚合，**324/324 一致，0 mismatch**。并非只依赖旧文档宣称的重放结果。

## 首次交付的本地输入（保留用于对照，不作为修复后的原生时间输入）

`data/binance-2020-02`（Git 忽略）。没有插值、补价或价格替代，但本轮确认旧转换使用 `funding_time_utc` 显示列，丢失了 2 月 15 条记录的毫秒。这是 `fa45603` 的相关缺陷，不能继续声称它保留原始实际结算时间。该目录原样保留用于固定输入前后比较，不覆盖用户已有数据；新版目录及生成命令见下文和 README。

| 文件 | 行数 | SHA-256 |
|---|---:|---|
| bars_4h.parquet | 324 | `e8e852defb60f3f0fdfc975e7f7ec8cee6a704b90ffd1fe8ac0988960d0356fa` |
| trade_1m.parquet | 77,760 | `7716e8e0466daca73bb03d5bdba9733c13bdcf05d0c233b04d69c39857022c34` |
| mark_1m.parquet | 41,760 | `bce19a572f384bab10046b3c085a732eb47a4d01df351c4c5e6c959aeb3045b1` |
| funding.parquet | 87 | `d55b42479dddd7e553ea9b6dd52eab7cc75b7bfa52ba87ab84acd53bc227f9d3` |

`provenance.json` 的本地文件 SHA-256 为 `c103a33ec8446b67d684a591d4d217a31b11750bd0a3716ece66772bfe1daa2b`（包含本机绝对路径，在其他路径转换后此哈希会变化）。另一次转换到新的 `data/binance-2020-02-check` 验证不覆盖行为及相同四份 Parquet 内容。

## 本轮 Funding 原始计划与时间容差核验

核验范围明确限制为 **`[2020-01-01T00:00:00Z,2026-08-01T00:00:00Z)`**，不是默认套用所有 BTCUSDT 历史。只读重读 79 个 Binance 官方原始 Funding ZIP，逐对象匹配旧 provenance 的 SHA-256；本地 CHECKSUM 存在时另行核对。原始字段为 `calc_time,funding_interval_hours,last_funding_rate`：

- 7,212 条原始记录，`funding_interval_hours` 全为 **8**。
- 原始 `calc_time` 是整数 epoch 毫秒；按最近 UTC 00/08/16 候选点核对，7,212 个计划结算全部一对一，0 缺失、0 重复。
- 原始 `calc_time/rate` 与 canonical `funding_time_ms/funding_rate` 逐条相等（rate 使用 Decimal，不拿显示时间作实际时间）。
- 3,988 条延迟 0ms，3,224 条非零；全部非负，最大 **47ms**，位于 `2021-09-17T08:00:00.047Z`。因此规则固定为 **整数毫秒延迟 `[0,+47]ms`（两端包含）**，不允许提前或亚毫秒，不从待校验文件的最大值自动放宽。
- 2020-02 的原始 87 条：0ms×72、1ms×11、2/4/9/15ms 各 1 条。
- 本机缺少 provenance 引用的 **2026-08 月原始 Funding ZIP**。canonical 虽有该月前 29 条，本轮没有拿未经原始重放核验的时期扩展计划；2019、2026-08 及之后一律不在本规则范围。

相关官方原始对象 SHA-256：

| Funding ZIP | SHA-256 |
|---|---|
| 2020-02（87 条） | `6599466d108d120c64a078824326c063ed2d4335b3292e52c5e572f79166533a` |
| 2021-09（含最大 47ms） | `03f25a7c25eef18d5f5b5b7bb0b664cab7a210b409f37e95a54e141808a0752d` |
| 2026-07（93 条） | `e36fcc66f493d7d9ec348c852fc22e9f318c79cf7adae17398a3994ae0adc41e` |

可复核命令（输出必须选择新文件；不修改源仓库）：

```bash
.venv/bin/python tools/audit_funding_schedule.py \
  --dataset ../QuantForge/data/versions/e8510e8a3f00fd5d \
  --raw-root ../QuantForge/data/raw/binance \
  --cache ../QuantForge/data/archive-object-cache/binance-public-data \
  --output .local/funding-schedule-audit.json
```

结果包含 79 个官方路径/哈希和偏差频数，保留在本机，不提交行情、费率、报告或本机配置。加载器使用固定契约 `btc-usdt-native-8h-2020-2026-r1`：整个输入文件先验证每条匹配及唯一性，再检查运行所需结算窗口是否有记录，最后按实际时间 `[start,end)` 取执行事件。错误中的 `expected` 是最近候选名义时点；无法凭错时记录推断它原本来自哪一笔。未知范围、不合法时间、同结算的不同毫秒记录均失败，不静默修复。

### 边界规则与精度修复

`[T,T+47ms]` 与运行 `[start,end)` 有交集时，需要该结算的实际记录作为证据；有证据且实际时间在区间外时不收费。CLI 仍只接受分钟对齐的区间，底层匹配函数也测试了毫秒边界。合法延迟可能落在同点开仓/平仓之后，匹配不会舍入或改变账户事件顺序。文件中区间外的异常也不会因先切片而被隐藏。

旧 CSV 的 UTC 显示列在全部 7,241 行中有 3,235 行截掉毫秒；在原始已核验 7,212 行中为 3,224 行。新版适配器明确使用原始 `funding_time_ms`，同时检查显示列只能等于该原时点或其截秒显示，矛盾/缺失/非整数 epoch 时失败。

修复后的本地目录：**`data/binance-2020-02-ms`**。4H / 合约 1m / Mark 的哈希与上表相同；Funding 保留原始时间并含边界证据：

| 文件 | 行数 | SHA-256 |
|---|---:|---|
| funding.parquet（执行 87 条 + 03-01 00:00 的区间外证据 1 条） | 88 | `428c78b6ac96b93417ace589f09df9cfd49096faccef0088a9e9d7b67a6df2a5` |

88/88 的原始时间、rate、Mark 都与 canonical 原始列逐条核对；运行实际使用 87 条，其中 15 条非零毫秒完整保留。新版 `provenance.json` 本机文件哈希为 `ce0c91b44fbe4737d3c14c57383782855bd1095a7173cf25fb496a6c41bf3e10`（随本机路径改变），另记录原始时间列权威性、边界证据和固定验证契约。修复结果及旧固定输入对照见 `VALIDATION.md`。

## V2 数据质量选择与较长区间

先跑通2020-02全比较后，按事先写入 `V2_SPEC.md` 的规则扫描：完整UTC月、4H至少150根预热且连续、合约/Mark每分钟唯一递增/无缺口/有效OHLC、Funding计划/原始毫秒/价格/费率及转换边界证据完整，所有canonical SHA及官方Mark ZIP/CHECKSUM匹配。首选最早连续12完整月（固定最多12个月的资源边界），否则取最早最长完整块；只用数据质量，不用收益。

`tools/select_comparison_window.py` 只读复核canonical完整文件哈希、按chunk验证合约数据，并逐月核验Mark/Funding/4H。质量证据先保存 `.local/v2-window-selection.json`，再转换并运行比较。共检查 **2020-01～2024-02的50个月**，找到首个12完整月块后停止Mark月扫描；没有声称其后月份均完整。

| 排除月 | Mark缺失分钟 | 首个Mark缺口UTC / 其他原因 |
|---|---:|---|
| 2020-01 | 29 | 01-19 13:09；另无2019-12-07开始的150根4H预热 |
| 2020-12 | 24 | 12-17 07:32 |
| 2021-06 | 0 | 转换保留的07-01 00:00边界证据缺Funding Mark；保守拒绝，不丢弃该异常 |
| 2021-07 | 7200 | 07-01 00:00；Funding Mark亦缺失 |
| 2022-07 | 1440 | 07-31 00:00；Funding原始时点00:00:00.022缺Mark |
| 2022-10 | 1440 | 10-02 00:00；Funding Mark亦缺失 |
| 2023-02 | 1440 | 02-24 00:00；Funding原始时点00:00:00.015缺Mark |

选定 **[2023-03-01,2024-03-01) UTC，366天**，12个月都完整，年度片段是2023年3～12月和2024年1～2月（两个partial年），不当作两个完整年度。此前2020-02～11、2021-01～05、2021-08～2022-06等较早块不足12个月；不是因为其收益而排除。2026-08超出原始已核验Funding范围且源coverage尾端为部分月，不参与选择。

只读转换到新的 `data/binance-2023-03_2024-03-ms`，V1严格加载器再次通过，没有修改旧数据或补缺口。来源仍是同一schema-7身份，原始UTC显示不作为执行时点。四份标准输入：

| 文件 | 行数 | SHA-256 |
|---|---:|---|
| bars_4h.parquet | 2346（含150根预热） | `f7e41837740dbc98315f1392b70ca63e34927b0089b3c0fc1498cc709d6b06a5` |
| trade_1m.parquet | 563040（含36000预热分钟） | `78e2e66461e16fcd095d85f428150b842cbec8fce07530e956d6fe381bed105d` |
| mark_1m.parquet | 527040 | `c0054b16f0246b6061e20613688458e150e2aff494f2124ac239c649e07345e1` |
| funding.parquet | 1099（1098执行＋1边界证据） | `0d3adc506306fd470c9139f4284c831c0e672b681c1d6678800eae48961c38d1` |

本机provenance含12个Mark官方对象及CHECKSUM哈希、3个canonical文件哈希、原manifest哈希/身份、运行及预热coverage；真实比较配置还链接质量选择JSON及其哈希。所有原始报告记录各输入SHA，发布前再次检查数据未变化。

## V2 第二阶段：预先固定6个月窗口

在V2_SPEC第二阶段规则写入后，使用同一只读工具 `--mode study`，从最早完整月顺序重新核验至首个4窗完成（2020-01～2024-02，共50个月）。只按质量选6连续完整月，选定后清空候选继续向后；没有策略结果输入。既有默认12月选择另写新证据重新执行，与第一阶段JSON **逐字节相同**。

预先保存 `.local/v2-study-selection.json`（SHA-256 `48050bf134d98d6d70a41e2039ee1d5943862b3859e90c495775923568d6662d`；包含本机来源路径，其他机器须重算），然后转换4个新目录 `data/study-window-{01,02,03,04}-ms` 并保存完整provenance，最后才运行study。没有覆盖旧2月/366天输入或证据。

| 窗口（UTC左闭右开） | 天数 | Mark/执行合约分钟 | 含预热合约分钟 | 含预热4H | Funding执行/文件行 |
|---|---:|---:|---:|---:|---:|
| window-01 2020-02-01～2020-08-01 | 182 | 262080 | 298080 | 1242 | 546 / 547 |
| window-02 2021-08-01～2022-02-01 | 184 | 264960 | 300960 | 1254 | 552 / 553 |
| window-03 2023-03-01～2023-09-01 | 184 | 264960 | 300960 | 1254 | 552 / 553 |
| window-04 2023-09-01～2024-03-01 | 182 | 262080 | 298080 | 1242 | 546 / 547 |

各输入仍使用同一已核验schema-7身份、整数原始Funding时间、官方Mark ZIP/CHECKSUM，4H预热精确150根，另保留end Funding证据1条、只按实际[start,end)收费。四窗所有16个Parquet SHA、原CSV/ZIP/CHECKSUM、原manifest及provenance哈希在生成study.json/各comparison.json中完整保存；发布前再次验证输入与选择记录未变化。

第一个窗口后，2020-08～11仅4月，被2020-12缺口打断；2021-01～05仅5月，6月边界Funding证据及7月Mark缺口打断。第二窗后，2022-02～06仅5月、8～9仅2月、11～2023-01仅3月，分别被7月/10月/2023-02的缺口打断。缺口具体时间与数量沿用上表，本轮重新核实；不缩短凑窗、不从块尾拼接。2023-03起12个合格月自然拆为两个相邻6月窗，找到最早4窗后停止，不声称后续所有月份合格。

重叠关系：window-01完整包含先前2020-02；window-02与此前29天及366天验证区间不重叠，但仍是旧已见数据；window-03/04分别为原366天区间前后半段，两者间不重叠，不能称为新OOS。独立窗口各自重置相同初始权益/策略Flat状态，在不同实际入场/资金状态下不能把结果当成原年度连续账户或拼接收益。

## 独立官方原始存档准备（基线 a335702）

`qfs prepare` 不读取旧canonical或其manifest。仅以显式本机原始存档清单读取官方月度BTCUSDT合约1m、Mark1m、Funding ZIP及CHECKSUM。原始字段已实际检查：Kline12列、open_time整数毫秒、close_time=open_time+59999；Funding header为calc_time,funding_interval_hours,last_funding_rate。已检查旧隔离转换定义：4H由完整240分钟OHLC/Decimal volume汇总，Funding Mark为实际时间所在分钟的Mark Open。本轮不复制旧研究架构，不需要网络下载。

新的 `.local/raw-{feb,six}-manifest.json` 只声明对象URL/本机ZIP/CHECKSUM及SHA。2月读取2个合约月、2个Mark月、2个Funding月；六个月读取7个合约月、7个Mark月、7个Funding月。边界月为3月或8月，用于真实end Funding和Mark证据；所有输入保留原序，全文件验证字段/重复/时序/数值，所需区间另严格检查网格。原始存档来自旧只读raw目录，但运行不需要canonical身份、CSV或任何旧Python模块。

输出 `data/official-feb` / `data/official-six`，重复输出 `*-repeat`：各5文件（四Parquet＋provenance）逐字节一致。分别与原 `data/binance-2020-02-ms`、`data/study-window-01-ms` 逐列精确比较：324/1242根4H、77760/298080合约分钟、41760/262080 Mark分钟、88/547 Funding均在实际UTC时刻/数值上完全一致。唯一物理编码差异是合约/4H时间列：新原始epoch毫秒得到datetime64[ms]，旧ISO CSV转换为datetime64[us]；不是时刻变化、不损失原生毫秒。Mark和Funding物理类型也一致。

2区间共24组固定成员/成本场景：交易及分钟权益CSV均与原报告逐字节相等，全部财务指标与分期CSV相等，完整独立核账通过。新的比较每区间再运行两次、52文件一致；未修改/覆盖旧输入、原报告或旧证据。完整原始ZIP/CHECKSUM/清单SHA、聚合定义、Funding固定政策和新规范文件SHA在新provenance及新报告中保存；新来源不冒用旧canonical dataset identity。

## 证据边界

已验证2020-02及上述366天完整区间、第二阶段4个6月窗口，不声称全量旧数据均可回测。真实比较及分期核账均完成；这是工程端到端及探索性历史比较 / 分期验证，**不是独立样本外、参数选择、统计显著性或盈利能力证明**。旧仓库已探索数据的样本外属性不会因迁移目录改变。合成行情仅在 `tests/` 中用于业务正确性测试。
