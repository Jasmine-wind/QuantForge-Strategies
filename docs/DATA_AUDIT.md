# V1 本地数据核验

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

## 转换后的本地输入

`data/binance-2020-02`（Git 忽略；生成命令见 README）。没有插值、补价或 Funding 替代；保留原始来源文件和规范化文件哈希。规范化价格转为 float64，精度限制明确披露。

| 文件 | 行数 | SHA-256 |
|---|---:|---|
| bars_4h.parquet | 324 | `e8e852defb60f3f0fdfc975e7f7ec8cee6a704b90ffd1fe8ac0988960d0356fa` |
| trade_1m.parquet | 77,760 | `7716e8e0466daca73bb03d5bdba9733c13bdcf05d0c233b04d69c39857022c34` |
| mark_1m.parquet | 41,760 | `bce19a572f384bab10046b3c085a732eb47a4d01df351c4c5e6c959aeb3045b1` |
| funding.parquet | 87 | `d55b42479dddd7e553ea9b6dd52eab7cc75b7bfa52ba87ab84acd53bc227f9d3` |

`provenance.json` 的本地文件 SHA-256 为 `c103a33ec8446b67d684a591d4d217a31b11750bd0a3716ece66772bfe1daa2b`（包含本机绝对路径，在其他路径转换后此哈希会变化）。另一次转换到新的 `data/binance-2020-02-check` 验证不覆盖行为及相同四份 Parquet 内容。

## 证据边界

只跑上述已核验的完整月份，不声称全量旧数据均可回测。两种策略真实 CLI 均完成；这是工程端到端及探索性历史回测验证，**不是独立样本外、参数选择、统计显著性或盈利能力证明**。旧仓库已经探索过这一历史区间；迁移目录不改变其样本外属性。合成行情仅在 `tests/` 中用于业务正确性测试。
