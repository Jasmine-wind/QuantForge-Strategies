# QuantForge-Strategies

BTCUSDT Binance U 本位永续的**本地离线历史回测 / 比较 CLI**。V1 成交、账户及数据契约：[docs/V1_SPEC.md](docs/V1_SPEC.md)；本轮比较扩展：[docs/V2_SPEC.md](docs/V2_SPEC.md)。支持 4H EMA 交叉与布林带均值回归，共用单仓、1m 执行与 Mark Price 估值引擎；回测离线，独立acquire可访问公开官方存档，不连接账户、不下单。

## 安装与运行

Python 3.11+；本次验证使用 Python 3.12。运行依赖仅 Pandas、NumPy、PyArrow（Parquet），测试使用 pytest。

```bash
uv venv --python 3.12
uv sync --locked --extra test
# 或 python -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
.venv/bin/qfs backtest --config configs/ema.json
.venv/bin/qfs backtest --config configs/bollinger.json
.venv/bin/qfs compare --config configs/compare.json
```

示例配置需要先准备下述真实本地文件；可用独立官方原始存档prepare或可选旧canonical适配。仓库不包含大体量行情；独立acquire只获取指定官方存档，不用合成数据演示盈利。`uv.lock` 固定依赖解析结果。

## V2：统一探索性历史比较 / 分期验证

`compare` 配置见 [`configs/compare.json`](configs/compare.json)：沿用 V1 公共字段，但**没有 strategy 字段**；不允许自定义成员参数、不同输入或新增场景。固定比较 EMA20/50、布林20/2、USDT 现金（不计息、零持仓/收益）和 **BTCUSDT U 本位永续多头持有基准（不是现货）**。四个账户共享输入、初始权益和仓位比例，不是策略组合。

永续基准在 start 的 1m Open 按统一仓位比例开多，经过同一账户/成交/费用/Funding/Mark 引擎，持仓不再平衡，end 按 V1 末分钟 close 平仓。EMA/布林原规则与 Funding 严格契约不变。成员原始配置可用 `backtest` 重放；两基准策略名为 `cash` / `btc_perpetual_long_hold`、参数为空。

三个固定成本假设：`base` 原 fee/slippage；`slippage_x2` fee不变、滑点×2；`fee_and_slippage_x2` 两者×2。**每组完整重跑**，费用改变后续权益和数量，不只是减估算成本。Funding 原始时点/费率/Mark不变，但金额随持仓变化。倍增后不满足费率范围则整体失败；不是交易所实际费率。

独立 `runs/compare-*` 原子目录内有：

- `comparison.json`：版本、共享及12个成员有效配置、数据/代码/依赖信息、成本场景、全区间/分期口径、原报告相对链接与哈希。
- `comparison.csv`：12组全区间净收益、年化、分钟收盘最大回撤、完整日 Sharpe、交易数与 costs。
- `periods.csv`：UTC月/年、实际起止/有效长度、complete/partial、边界权益/权益收益、局部分钟收盘回撤。
- `report.md`：探索性比较摘要与原报告链接；不按收益删选成员或给失败子集排名。
- `reports/<scenario>/<member>/`：完整 V1 summary/trades/equity/manifest。

分期截取同一连续账户曲线，**跨月持仓不重置、不月末平仓**。边界为完成分钟的状态，同点 Funding/订单影响后续片段；实际运行 end 使用最终平仓后权益。首尾不完整期间只计实际片段，不年化。分期回撤峰值从左边界重新计，不继承更早月份峰值，也不扩展分钟内风险采样。分期不输出整笔交易盈亏/Funding/成本的退出月归属。分期收益复合可核对全区间。

任何成员失败（包括非正权益）整体非零退出，清理私有 staging，不发布部分成功比较。输入先统一严格校验；随机外层目录名不写入报告，固定配置/数据/代码下全部52份文件可重复。

真实复核可先从已有完整本机 EMA 配置创建**新**比较配置（不覆盖），然后运行：

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
raw = json.loads(Path('.local/funding-ms-ema.json').read_text())
del raw['strategy']
with Path('.local/v2-compare-feb.json').open('x') as f:
    json.dump(raw, f, indent=2)
PY
.venv/bin/qfs compare --config .local/v2-compare-feb.json
.venv/bin/python tools/verify_comparison.py --config .local/v2-compare-feb.json \
  --output .local/v2-feb-acceptance.json
```

验证工具独立从成交/Funding/价格建立现金事件账本，核对每笔交易、每分钟状态、所有分期边界和复合收益，并重复CLI两次比对52个文件。支持 `--run <已有目录>` 单次核账，但明确不声称该次已验证重复性。输出要求新文件，不覆盖证据。

已完成 **2020-02** 及按事先固定质量规则选择的 **[2023-03-01,2024-03-01) UTC（366天）**。不是选最好收益：只读扫描从2020-01开始的完整月，优先最早连续12完整月，失败则按规格取最早最长完整月块；不插值、不绕过 Mark/Funding。2020-12、2021-07、2022-07/10、2023-02 等缺口打断较早候选；2021-06因转换边界证据缺少 Funding Mark 同样排除。完整质量记录保留在本机，汇总见 [DATA_AUDIT.md](docs/DATA_AUDIT.md)。质量选择工具：

```bash
.venv/bin/python tools/select_comparison_window.py \
  --dataset ../QuantForge/data/versions/e8510e8a3f00fd5d \
  --raw-root ../QuantForge/data/raw/binance --output .local/v2-window-selection.json
```

旧数据依旧已见；所有结果仅为探索性历史比较 / 分期验证，既无独立 OOS，也不证明盈利。最小 GitHub Actions 使用 uv.lock + 固定合成正确性 fixtures，不需要本机行情；尚未推送的新工作不能声称远端 CI 已执行。

## V2 第二阶段：固定策略多窗口 study

```bash
.venv/bin/qfs study --config configs/study.json
```

先按纯数据质量规则选窗口，再运行策略：最早连续6个合格完整UTC月、选定后从结束月继续，缺口打断、不拼接；最多最早4个、不因收益差而替换。少于4个保存实际数量和原因，不缩短凑数；少于2个明确多窗口真实验证不足。默认12月选择及 `compare` 保持兼容。实际已选窗口见 `docs/DATA_AUDIT.md`。

配置 [`configs/study.json`](configs/study.json) 是**准备模板**：先创建自己的选择记录及SHA，替换占位哈希、核对所选全部窗口并注入完整本机provenance，再保存到新的本机配置路径；不能直接将占位配置视为已核验数据。公共资金/仓位/成本字段只在顶层定义，每窗口只有label/start/end/data/data_source。重叠、错序、非6完整月、重复/不安全标签、公共假设覆盖或与选择记录不一致均拒绝，不能手选子集。

```bash
# 只读质量检查，无策略计算；输出要求不存在的新路径
.venv/bin/python tools/select_comparison_window.py --mode study \
  --dataset ../QuantForge/data/versions/e8510e8a3f00fd5d \
  --raw-root ../QuantForge/data/raw/binance --output .local/v2-study-selection.json
# 计算该记录SHA；按其windows逐个用原import_quantforge转换到新的目录
# 配置selection_evidence.path/sha256与完整窗口来源后执行
.venv/bin/qfs study --config .local/v2-study.json
.venv/bin/python tools/verify_study.py --config .local/v2-study.json \
  --output .local/v2-study-verification.json
```

每个窗口都是独立实验，使用相同初始权益；窗口内部沿用完整4成员×3成本场景、连续账户和月/年分期。没有合并账户、拼接收益、连续净值或跨窗口年化，也不把几个窗口当作独立统计样本。

`runs/study-*` 内有 `study.json`、`study.csv`、`report.md` 及 `windows/<label>/` 的52文件完整comparison。顶层保留全部逐窗口指标和同窗口同场景相对现金/永续基准的**收益差（百分点 = 100×收益率之差）**，固定顺序展示，不排名/淘汰。完整配置、预先选择证据、数据/代码/依赖版本及原报告相对链接/哈希都记录。整个study只有一次原子发布，后续窗口失败也清理全部私有staging，不发布成功子集。

独立 `verify_study.py` 复用已验收账本核验器，逐窗口核对交易、分钟权益、分期、年化null及顶层指标/百分点差/哈希；`--config` 完整运行两次并逐文件比较，`--run` 仅核账已有目录、不声称重复性。测试使用完整6个月合成分钟网格，不mock账户/引擎，CI无真实行情依赖；全套运行约数分钟。

当前实际4窗为 `[2020-02,2020-08)`、`[2021-08,2022-02)`、`[2023-03,2023-09)`、`[2023-09,2024-03)` UTC。第一窗包含原2020-02，后两窗拆分原366天区间；全部仍是旧已见历史，不是独立OOS或盈利证明。

## 独立离线HTML浏览

```bash
.venv/bin/qfs browse --run runs/compare-7hi8o5v_ --output .local/html/official-feb.html
.venv/bin/qfs browse --run runs/study-g5jo08cs --output .local/html/study.html
```

`--run`选择自己的已有完整comparison/study目录；`--output`必须是新的HTML路径且在原报告目录之外。生成后用浏览器直接打开文件即可，无服务器、CDN、账号或在线资源。原compare/study默认产物及52/211文件契约不变。页面内嵌全部窗口/三场景/四成员切换数据，不读取本机行情，不重跑策略。

精确全区间指标/费用/Funding和月度表来自原报告，n/a保留不可计算含义；同窗同场景相对现金/永续以**百分点**显示。每窗独立账户，曲线不拼接。图形每桶保留首尾、权益/完整曲线回撤极值，标明原点数和显示点数；回撤在完整曲线峰值上生成展示数据，**不从抽样重算财务指标**。显示数值最多6位小数，悬停指标可见未舍入原值；页面嵌入JSON保留完整精度。

导出先按固定报告版本验证各层必需哈希条目齐全及SHA-256摘要格式，再核对文件、原summary及JSON/CSV复制值；空/缺项/非法清单明确拒绝，不自动补哈希。检查**不等同独立账本核验**，使用者应先用verify_comparison/verify_study核账真实报告。页面明确已见历史、执行假设及风险限制，并展示数据来源/版本/哈希。输出原子且拒绝覆盖，原始报告不变；生成HTML/截图留在Git忽略目录，不作为新增默认报告提交。

## 收益与风险诊断（不重跑策略）

```bash
.venv/bin/qfs diagnose --run <已独立核账的comparison或study目录> --output .local/diagnostics-new
```

独立新目录仅`diagnostics.json`、`diagnostics.csv`和`report.md`，不改变原52/211产物。先复用浏览完整性检查，再按原trades完成顺序计算全区间和Long/Short笔数、净盈亏、fees/slippage/Funding、胜率、均盈/均亏、盈亏比/PF、连续亏损（零打断）；所有方向可加总项与原summary核对。null为n/a，不重复扣滑点，不把跨月交易归入退出月。

固定展示本组**正净盈利最高前5笔**（不足5全列），占全部正交易利润及正总净盈亏的比例；后者总净盈亏非正时n/a，可大于100%表示其他交易抵消。终点强平另列，保留原退出原因。三场景成本差直接来自各次完整重跑结果，不扣估算成本；相对现金/永续差单位为百分点。JSON/CSV保留全部窗口、成员、成本场景和逐笔集中度，不排名选窗。来源全文件SHA、配置、UTC区间、原/诊断代码身份完整保存；这不是独立财务核账或因果/盈利证明。

## 数据与配置

每个 Parquet 一行一个事件；时间可为带时区的 datetime 或可解析的 ISO 字符串，转换为 UTC；无时区时间明确按 UTC 处理。**不接受无单位的数字 epoch**。必须已经严格递增，无重复。规范化列：

| 输入配置键 | 列 |
|---|---|
| `bars_4h` | `open_time, open, high, low, close, volume` |
| `trade_1m` | `open_time, open, high, low, close, volume` |
| `mark_1m` | `open_time, mark_open, mark_high, mark_low, mark_close` |
| `funding` | `funding_time, funding_rate, funding_mark_price` |

价格正且有限，费率有限（允许负值），volume 非负，OHLC 有效；K 线按 UTC 4H / 分钟边界对齐。4H 完成时间是 `open_time + 4h`，不是 Binance 原始 `close_time` 的毫秒末点。

- 区间 `[start,end)`，起止必须是分钟边界；所需合约价与 Mark Price 每分钟完整。4H 预热到信号区间连续。任何错误直接指出文件与时间，不排序修复、不插值、不寻找更晚成交价、不用合约价替代 Mark。
- EMA 至少 150 根已完成 pre-start 4H；布林带至少 `window+1` 根。指标使用全部提供的已完成预热历史，EMA seed 因而也是输入的一部分。预热不交易；EMA 初始 Flat，只在区间内交叉时入场。
- Funding 使用**已核验的固定计划**，不从待校验输入推断周期或放宽容差：仅支持 `[2020-01-01,2026-08-01)` UTC 的 BTCUSDT。79 个官方原始存档的 7,212 次结算均为 UTC 00/08/16、`funding_interval_hours=8`，原始时间偏差为 **0～+47ms（含端点，整数毫秒）**；不允许提前、亚毫秒或更大偏差，范围外失败而不沿用计划。证据及复核命令见 `docs/DATA_AUDIT.md`。
- 每条 Funding 必须匹配一个合法结算，每个应有结算恰好一条；同一次结算的不同毫秒记录也视为重复。文件整体先校验、再按**实际**时间取 `[start,end)`；错误包含文件、预期与实际记录，不去重、不移动时间、不补零、不丢弃异常。
- 匹配只确定事件身份，不改变账户时间。`T` 的 Funding 发生在同点订单之前；`T+1ms` 可能发生在订单之后。合法边界旁的记录可作为覆盖证据，但区间外的实际事件不收费。缺少可能与区间相交的结算窗口证据时失败，不猜测为零。CLI 起止仍要求分钟对齐。

配置示例见 [`configs/ema.json`](configs/ema.json)、[`configs/bollinger.json`](configs/bollinger.json)。所有文件路径（包括 output_dir）**相对配置所在目录**解析。EMA 参数 `fast/slow` 默认 20/50；布林参数 `window/std_multiplier` 默认 20/2，总体标准差 ddof=0。

资金、position_fraction、maximum_leverage、fee/slippage 显式配置。默认 10000 USDT、50%、1 倍、每边手续费/滑点各 0.0005。要求 `0 < position_fraction <= maximum_leverage <= 1`；矛盾配置失败，不暗自改仓位。Binance 实际手续费依账户等级/优惠变化：[官方费率](https://www.binance.com/en/fee/futureFee)。`data_source` 可携带完整来源对象，原样保存；没有来源时明确记为未核验，不凭文件名认证来源。

## 独立官方原始存档准备

不需要旧canonical目录。`qfs prepare` 只读取本地官方BTCUSDT月度合约1m、Mark1m、Funding ZIP和CHECKSUM，校验来源路径/市场/月份/字段/整数毫秒/时序及SHA；从240根完整1m聚合4H，Decimal精确求volume后转float64，保留150根4H预热，Funding关联实际所在分钟的Mark Open（包括边界证据）。最后通过原严格loader，整个5文件目录原子发布，不覆盖或写入源目录。

```bash
.venv/bin/qfs prepare --manifest .local/raw-feb-manifest.json \
  --start 2020-02-01T00:00:00Z --end 2020-03-01T00:00:00Z \
  --output data/official-feb
```

manifest为JSON：`{"symbol":"BTCUSDT","archives":[...]}`。每项仅有 `kind`（trade_1m/mark_1m/funding）、`path`、`checksum`（路径相对manifest）、`official_url`、`sha256`。例如合约对象URL为 `https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2020-02.zip`；Mark目录为markPriceKlines，Funding为fundingRate/BTCUSDT/BTCUSDT-fundingRate-2020-02.zip。列表按每类月份升序，不能靠排序去重修复。SHA须与该ZIP和CHECKSUM内的官方文件名同时相符。

2月完整输入需要合约1月/2月（1月7日起预热）、Mark及Funding的2月/3月（3月1日证据）；6月窗口需要相应全部月及end边界月。缺存档/缺分钟/重复/无效值/Funding Mark时失败，不补值或改策略。输出4个标准Parquet＋provenance.json，normalized_files.path相对新目录；将provenance完整注入自己的backtest/compare配置并按上述核账工具复核。

优先复用本机已核验官方原始存档，**无canonical运行依赖**。取数独立于prepare/回测：

```bash
.venv/bin/qfs acquire --start 2024-03-01T00:00:00Z --end 2026-08-01T00:00:00Z \
  --cache data/official-cache --output .local/acquisition
# 可选 --reuse <只读raw根目录>（其下futures/um/monthly/...）或 --offline
# manifest: .local/acquisition/manifest.json；请求/实际/失败: acquisition.json
```

自动请求600小时预热及范围内必要Funding/Mark结束边界，ZIP/CHECKSUM/SHA/CRC验证后才发布缓存。合法缓存只读复用；损坏缓存拒绝、不覆盖；缺对象才访问官方HTTPS，连接/每次读取30秒、总传输约120秒上限、最多两次完整下载，不续传。失败仍保存对象记录并返回非零；manifest只含实际取得对象，不能视作连续覆盖。CHECKSUM及URL是来源记录/完整性核验，不等于独立签名认证。支持范围仍为Funding `[2020-01-01,2026-08-01)`；旧已见历史属性不因独立准备而改变。真实对照及目录见DATA_AUDIT/VALIDATION。

## 独立质量选择与study（固定补充历史范围）

```bash
.venv/bin/qfs scan --manifest .local/acquisition/manifest.json --output .local/selection.json
sha256sum .local/selection.json
```

scan固定检查`[2024-03-01,2026-08-01)`全部29个月，包括缺失尾部；即使已有4窗也不早停。原canonical选择命令的早停行为不变。质量合格须通过prepare/严格loader的分钟连续、150根4H预热、Funding实际毫秒及Mark边界验证。按最早连续6月、最多4窗非重叠选择，缺口断块，少于2窗不能声称多窗口验证。`scan_scope`为研究请求；`actual_source_coverage`为实际对象首末/行数而非连续性承诺，缺对象留在逐月errors中。

选择JSON/SHA保存后、策略运行前，按**完整windows列表**准备输入。以下可复现脚本仅使用本仓库与显式manifest（不要求旧canonical）：

```python
import json
from pathlib import Path
from qfs.acquire import required_objects
from qfs.data import sha256
from qfs.prepare import prepare
from qfs.report import write_json

selection = Path('.local/selection.json').resolve()
proof = json.loads(selection.read_text())
print('Preselected evidence SHA:', sha256(selection))  # 保存此值后再运行任何策略
assert proof['windows'], 'No six-month window; keep missing-data evidence'
plans = Path('.local/window-manifests').resolve()
plans.mkdir(parents=True, exist_ok=False)
config = dict(symbol='BTCUSDT', initial_equity=10000, position_fraction=.5,
              maximum_leverage=1, taker_fee_rate=.0005, slippage_rate=.0005,
              output_dir=str(Path('runs').resolve()),
              selection_evidence=dict(path=str(selection), sha256=sha256(selection)), windows=[])
for window in proof['windows']:
    urls = {o['official_url'] for o in required_objects(window['start'], window['end'])}
    entries = [{k: o[k] for k in ('kind', 'path', 'checksum', 'official_url', 'sha256')}
               for o in proof['source_files'] if o['official_url'] in urls]
    manifest = plans / (window['label'] + '.json')
    write_json(manifest, dict(symbol='BTCUSDT', archives=entries))
    output = Path('data') / ('independent-' + window['label'])
    source = prepare(manifest, output, window['start'], window['end'])
    config['windows'].append({k: window[k] for k in ('label', 'start', 'end')} | dict(
        data={k: str((output / v['path']).resolve()) for k, v in source['normalized_files'].items()},
        data_source=source))
with Path('.local/independent-study.json').open('x') as f:
    json.dump(config, f, indent=2)
```

```bash
.venv/bin/qfs study --config .local/independent-study.json
.venv/bin/python tools/verify_study.py --config .local/independent-study.json --output .local/independent-verification.json
# --config核账入口完整执行两次并比较；--run <已完成study>只核账，不声称重复性
```

官方身份记录市场/转换契约、已核验URL/ZIP SHA/CHECKSUM SHA；不会硬填canonical dataset_identity。窗口规范文件摘要和所需原对象必须与选择证据关联。独立核账自行验证全29月完整性和来源关联，不调用生产选择器。SHA不是来源签名或预存时间的独立证明。各窗独立初始账户，不拼接或合并年化；固定成员、成本场景与策略参数不变。

## 从旧 QuantForge 只读转换

检查结果及核验哈希见 [docs/DATA_AUDIT.md](docs/DATA_AUDIT.md)。旧 schema-7 CSV、归档 ZIP、Parquet analytics mirror 都只读检查；不复用旧研究架构或合成执行器。实际使用 canonical CSV，而不是非正式 analytics mirror；逐文件 SHA-256、manifest 身份及官方 Mark ZIP 的本地 CHECKSUM 均核验。

假设旧仓库在 `../QuantForge`：

```bash
.venv/bin/python -m qfs.import_quantforge \
  --dataset ../QuantForge/data/versions/e8510e8a3f00fd5d \
  --raw-root ../QuantForge/data/raw/binance \
  --output data/binance-2020-02-ms \
  --start 2020-02-01T00:00:00Z --end 2020-03-01T00:00:00Z
```

输出必须是**不存在的新目录**；不覆盖旧转换，不在源数据内写入。输出四个 Parquet 和 `provenance.json`，包含原始/规范化文件哈希、覆盖、Funding 契约与转换说明。4H 和合约价含 150 根 4H 预热；Mark 取运行区间；Funding 在已核验范围内另保留起止旁最多 47ms 的边界证据，仅区间内实际事件用于结算。

**时间精度修复：**旧 schema-7 的 `funding_time_utc` 是可能截秒的显示列，`funding_time_ms` 才是原始整数时间。转换器使用后者，检查显示列只能为原时刻或截秒显示，绝不拿显示列/计划时点替代实际事件。旧版 `data/binance-2020-02` 不覆盖；应重新转换到 `-ms` 新目录。归档缺失/校验失败/缺口/Funding Mark 缺失即失败；转换不下载、不补值。

将完整来源带入实际运行配置（可重复执行；仅更新本仓库 `.local`）：

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from qfs.data import sha256
source = json.loads(Path('data/binance-2020-02-ms/provenance.json').read_text())
source['provenance_file_sha256'] = sha256('data/binance-2020-02-ms/provenance.json')
Path('.local').mkdir(exist_ok=True)
for name in ('ema', 'bollinger'):
    config = json.loads(Path(f'configs/{name}.json').read_text())
    config['data_source'] = source
    with Path(f'.local/funding-ms-{name}.json').open('x', encoding='utf-8') as f:
        json.dump(config, f, indent=2)
PY
.venv/bin/qfs backtest --config .local/funding-ms-ema.json
.venv/bin/qfs backtest --config .local/funding-ms-bollinger.json
# 可选验收：两策略各运行两次，逐字节比较四份报告，并逐笔/逐分钟独立核账
.venv/bin/python tools/verify_real.py --config-prefix .local/funding-ms \
  --output .local/funding-ms-verification.json
```

配置创建脚本仅用于首次创建，不覆盖已有本机配置；重复验证直接运行后续命令。新版契约为 `qfs-v1.1`，原固定输入的账本结果不变；恢复 2 月 15 条原始毫秒时间后，订单同点附近的 Funding 归属及结果有可解释变化，比较见 `docs/VALIDATION.md`，不伪称修复前后真实输入完全相同。

已完成真实数据端到端验证：**2020-02-01 至 2020-03-01 UTC（29 天）**。这是旧 QuantForge 已探索过的历史区间，**不是独立样本外、显著性或未来盈利证据**。1 月 Mark Price 有缺口，不能把全量旧数据无条件用于回测。合成 fixtures 只用于逻辑正确性测试。

## 执行、账户与报告

同一 UTC 时点：先对已有仓位结算 Funding，再处理已完成 4H 信号，再用同时间戳 1m Open 执行订单。分钟内带毫秒的 Funding 在其真实时点结算；分钟结束用 Mark close 估值。买入价格上浮、卖出下浮；每笔入场/出场均收 taker fee。

反向：信号时点先平仓，下一分钟 Open 才开反向仓，并按更新后的权益重新定量；不同时反手。布林持仓忽略相反入场，平仓后等新的轨道穿越。结束仍持仓时用最后有效合约 1m close 加滑点、手续费平仓，原因 `end_of_test`。

`wallet = initial + realized - fees + funding`；浮盈用 signed quantity 与 Mark；滑点已体现在成交盈亏内，单列成本而不重复扣款。每次运行原子发布一个独立 `output_dir/run-*`：

- `summary.json`：固定指标、完整配置、口径版本、状态与限制；不可计算项为 JSON `null`。
- `trades.csv`：方向、数量、入退场时点、参考/成交价、毛/净盈亏、双边费用、滑点、Funding、持仓小时、原因。
- `equity.csv`：初始权益、每个分钟结束的 Mark 权益、终点平仓后权益。UTC `time` 表示完成边界，非分钟 open_time；终点可能有两行，最后一行是平仓后的账户（`event` 区分）。
- `manifest.json`：配置、全部数据 SHA-256 与文件覆盖、来源、Git commit/dirty 状态、源代码 SHA-256、依赖版本、口径版本。

最大回撤保持**分钟 Mark close 采样**，包含初始权益及终点费用；可能遗漏分钟内 Funding/价格事件造成的权益波动。本轮不扩展风险引擎。年化按实际日历天数 / 365。Sharpe 仅完整 UTC 日的边界权益收益，sample std ddof=1、sqrt(365)、无风险收益为零；不足两个日收益/零标准差返回 null。胜率按净盈亏 > 0，净盈亏包括双边费用与持仓 Funding；平均盈亏比缺任一侧返回 null，Profit Factor 无亏损时返回 null，全亏时为 0。

正常完成退出 0 并打印目录；输入/计算/写入失败退出非零且不发布成功或部分报告。权益触及非正会锁定停止新增仓位，仍按既有退出规则完成记录，发布**完整且显式标为 invalid** 的报告，打印失效时间与原因并退出非零；不能把恢复后的余额视为有效成功回测。

固定输入、配置、代码和依赖环境下四份文件逐字节一致；随机独立目录名不进入报告内容。未提交代码仍记录 dirty 与源文件哈希，正式复核宜在干净提交上运行。

## 已知模型限制

1m 市价近似、常数滑点与显式假定的费率；没有订单簿、排队、流动性、部分成交。没有数量步进、最小名义金额、再平衡、完整保证金、维持保证金或强平费用；**不具备实盘保证金风险精度**。float64 计算会有舍入误差。Funding 计划与固定 0～+47ms 容差仅适用于上述已核验历史范围，其他时期必须另行核验，不能自动放宽。没有 ML、搜索、多资产、Web、数据库服务或实盘连接；仅独立acquire可下载限定的官方历史存档。

验收映射与验证结果见 [docs/VALIDATION.md](docs/VALIDATION.md)。
