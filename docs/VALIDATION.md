# V1 / V2 验收记录

## 独立官方研究四阶段（基线324acadd，本轮进行中）

初始HEAD为用户指定基线，工作区干净，旧仓库HEAD d0e6a5d/干净且只读。先在V2_SPEC第9节固定29个月完整扫描规则，再实现，无策略参数/账户/Funding变更、不自动推送。

阶段一：新增acquire独立官方月度ZIP/CHECKSUM入口，仅标准库网络；缓存SHA/文件名/member/CRC通过才发布，复用不覆盖，损坏拒绝并记录，有限超时/重试且拒绝206/Content-Range/短Content-Length，不拼接残片。请求/实际/失败独立记录。11项新增固定fixtures测试＋15项prepare测试共26通过。自审覆盖只读源目录保护、HTTP永久错误不重试、临时缓存失败清理和合法重复字节一致。

官方README通过curl有限超时取得（web工具因本机fake-IP保护拒绝，未无限重试），确认USD-M毫秒Kline字段及相邻.CHECKSUM约定；原Funding/Mark格式沿用已核验原始存档。本机证据 `.local/independent/binance-public-data-README.md`。实际acquire固定范围请求88对象（29月×3＋合约2024-02预热），88均复用已核验原始ZIP，无缺失/无新下载；记录 `.local/independent/acquisition/`，不意味着分钟连续，待完整质量扫描。新工作尚未推送，基线CI不是新提交CI。

## HTML哈希清单完整性补修（基线7355eb2）

本轮仅补修browse完整性校验，基线 `7355eb25b2a438af779d5bd19c5f6ac049b5e4a3` 已由用户授权推送。初始main及旧QuantForge工作区干净；无新功能/依赖/数据准备或策略重跑，保留全部269测试、V1/Funding/财务口径和compare/study原52/211产物。新修复仅本地提交，不自动推送。

### 失败回归与修复

先添加公开CLI回归：删去首成员artifact_sha256的equity.csv，仅修改曲线中间权益为1，保留首尾与所有仍声明的哈希及行情。修复前 qfs browse 返回0并发布HTML，曲线回撤明显大于原maximum_drawdown；回归确实在成功发布断言处失败。测试初稿曾误用max_drawdown字段，按实际summary字段maximum_drawdown纠正后才取得有效失败证据，不将初稿字段错误冒充缺陷复现。

根因是check_files只遍历已给条目，没有验证其覆盖集合。现按已支持版本和固定目录推导必需清单，不从输入清单/当前磁盘文件猜覆盖：comparison自身的comparison.csv/periods.csv/report.md三项；每个固定成员summary.json/trades.csv/equity.csv/manifest.json四项；study窗口完整52项；study顶层study.csv/report.md两项＋每窗口52项。JSON本身只在父层有摘要，不要求自哈希。各清单必须是精确固定路径集合的对象，空/缺失/非对象/缺必需项/额外路径拒绝；摘要必须是64位小写十六进制字符串，null/bool/数值/错长/非hex/尾换行/数组等拒绝。成员/窗口链接也必须指向版本定义的固定目录，不能以别名绕开清单。

自审补充了一条先失败再修的校验顺序回归：在study后窗成员删equity哈希并改中间权益，保留外层曲线旧摘要。初修会先报旧外层hash mismatch，未能明确指出内层缺项。最终分两阶段：遍历所有窗口/comparison/成员清单，先检查覆盖与摘要格式，然后核对文件摘要与原复制值；完整性错误明确含hash manifest及缺失路径。没有重建/补齐声明摘要，没有用独立核账代替校验；读取前后实际SHA快照仅用于并发修改检测和来源展示，不作为缺失清单的替代。所有失败在发布前终止，无HTML或.qfs-browse-*临时残留。

新增47项回归覆盖主要篡改、其他各必需项、空/非法类型/非法摘要、study四层与后窗嵌套缺项（包括清单字段本身被删）、旧外层摘要遮蔽边界、合法完整两窗study正常/字节确定性/原报告不变。study用既有真实长度合成网格生成，不mock引擎，不作为历史表现。除最初主缺陷和后续顺序回归的现场red→green外，扩展用例还在隔离的7355eb2代码快照下复核：45失败、1合法导出通过（当时46项）；快照/失败日志在.local，未reset工作区。嵌套测试按需同步仍声明的父层JSON摘要以消除旧摘要混淆，只修改测试副本，不代表生产修复会重建清单。

### 验证与边界

- 锁定 `uv sync --locked --extra test`；全套 **316 passed / 0 failed / 0 skipped**（269原有＋47新增），528.68秒；src/tools/tests编译、qfs/browse CLI/help、diff检查通过。源改动仅browse.py，生产执行/账户/指标/Funding/选择/比较/study写入代码、HTML模板及uv.lock未变。
- 离线wheel构建到 `.local/browse-hash-fix/dist`；实际从wheel加载qfs CLI和内置模板，合法报告导出成功，缺equity哈希返回1并明确hash manifest/equity.csv，无失败输出或临时文件。验证不局限于editable安装。
- 只读复核原study两树 `study-g5jo08cs` / `study-6hsj7a9v`（各211文件）、原2月 `compare-aaadgj0m` 和本轮前已存准备输入比较 `compare-7hi8o5v_`（各52文件）。四树均与原独立核账证据SHA完全相同，浏览完整性/复制值检查及新目录导出通过；同源study/准备比较HTML还与基线交付HTML字节完全相同。新页面与保全记录在 `.local/browse-hash-fix/real-check/`，全套测试日志为 `.local/browse-hash-fix/full-tests.txt`，未覆盖历史证据、未新增独立账本核验或真实策略重复性声明。
- 基线CI [38272646398](https://github.com/Jasmine-wind/QuantForge-Strategies/actions/runs/38272646398) 首查in_progress，最终API确认headSha=7355eb25b2a438af779d5bd19c5f6ac049b5e4a3、completed/success；不能把它称为本轮尚未推送修复的远端CI。

限制：仅支持既有comparison/study报告版本与固定结构，未来版本需显式适配；SHA与自报清单不是来源签名，不能阻止攻击者同时一致改写全部报告和摘要，不证明财务正确性，独立核账仍独立存在。本轮不扩展到账本检查/新UI/优化，不改变图形采样或任何指标；合法HTML字节未变，因此未另声称新增浏览器视觉验收。全部历史仍已见，旧仓库只读且保持原HEAD/干净状态；行情、报告、HTML、本机配置和.local证据不提交。提交SHA以Git记录为准，不在管理其自身的文档内自引用。

## 独立数据准备与离线浏览（基线 a335702，本轮完成）

用户授权本轮自主实现/测试/审查/修复/分阶段本地提交，不自动推送。初始工作区干净；先补充既有V2_SPEC第8节及AGENTS授权范围，保持V1、Funding、245既有测试、年化溢出与study扫描完整性和默认产物契约。旧QuantForge只读。基线CI [38266056056](https://github.com/Jasmine-wind/QuantForge-Strategies/actions/runs/38266056056) 初查in_progress，后API确认headSha=a335702、completed/success；这不是尚未推送新代码的远端CI。

### 阶段一：独立官方原始存档准备

新增小型 `prepare.py` 与 `qfs prepare`，显式manifest无需canonical或旧代码，复用validate_frame/require_grid/load_data及既定Funding政策。240完整分钟OHLC/Decimal volume聚合150根预热；整数ms和实际分钟Mark Open含边界证据；5文件原子发布、禁止覆盖/源内写入，来源SHA与CHECKSUM在发布前再次校验。规范文件路径记录为bundle内相对路径，不受输出目录名影响。

先写公开prepare接口失败回归（模块尚不存在），实现后新增15个准备测试：原序/预热/Decimal volume/47ms/Mark/loader、5文件重复、错误URL/SHA/CHECKSUM文件名/CSV member、warm缺口/重复/乱序/无效OHLC/close_time、非整数/48ms Funding、缺Mark，以及CLI/文件系统失败staging清理。全部15通过；既有245测试在本轮最终全套运行中全部通过。合成存档只用于正确性。

真实准备先2月，再6月window-01（2020-02～08），读取本机已核验官方ZIP/CHECKSUM，不用网络或canonical运行路径。新输入与旧四类时间/数值逐列精确相同；发现合约和4H的Parquet时间物理单位ms/us差异，经精确UTC时刻比较和下述金融字节对照证明无行为差异，不为匹配物理编码改策略/引擎。每组4成员×3成本的完整财务指标和24份交易/权益CSV与原输入报告完全相同，periods.csv也相同。每区间新的比较重复两次，52/52文件一致，全部交易、分钟状态、分期、年化null独立核账通过。准备重复各5/5文件一致。

实际位置：`data/official-feb`、`data/official-six`，重复各`-repeat`；新比较 `runs/compare-7hi8o5v_` / `compare-6qe4xhey`（2月）、`runs/compare-l1rttnce` / `compare-dji53bpy`（六个月）；新证据 `.local/official-{feb,six}-verification.json`，配置/清单 `.local/official-*-compare.json` / `raw-*-manifest.json`。这些均不提交。原 `compare-aaadgj0m` 与 `study-g5jo08cs/windows/window-01` 用于只读金融对照，未覆盖。

自审修复：原始ZIP member/close_time/月身份必须与官方对象一致，不能只验HASH后按位置猜格式；全文件先校验、后切片，不能把外部重复/异常丢掉；volume保留Decimal避免float逐项求和差异；输出在发布前再次拒绝并发出现的目标。数据准备仍离线、仅固定已核验Funding范围，CHECKSUM/URL不伪称来源独立签名或新OOS。

### 阶段二：独立离线HTML浏览

新增 `browse.py`、单个内嵌模板 `browser.html` 和 `qfs browse --run ... --output ...`。只读原comparison/study（原52/211文件不变），无前端工程/运行依赖/服务器/在线字体或网络调用。检查支持版本、固定成员/场景、原文件SHA、summary/config、JSON/CSV复制值，显示准确窗口范围/来源/成本假设/限制；自包含HTML嵌入完整原指标/分期/百分点差及各窗口独立采样曲线。明确区分“报告完整性检查”与“独立核账”，没有在浏览代码重复交易/年化引擎。窗口不拼接、不排名。

图形采样只压缩显示，每160桶保留首尾、权益min/max和完整曲线峰值回撤min/max，包含初态/终点；不根据采样重新计算原summary或月度指标。指标原始数值在嵌入JSON及title中保留，显示最多6位小数；表内月度数值仍来自原periods。现金平曲线/Sharpe null正常展示。source文本转义`<`避免闭合script，再用textContent显示，不注入任意HTML。临时文件与目标位于同一目录，独占hard-link发布避免并发覆盖；失败清理临时文件。

先新增公开浏览接口失败回归（模块不存在），共9项浏览测试通过：全部12切换数据/原summary/period/首尾/原文件不变与HTML字节确定性；hash/CSV复制值/summary/缺成员/逃逸路径/空曲线拒绝；极值采样、恶意script文本转义、CLI及发布失败清理。包装配置仅增加HTML package-data，uv.lock及运行依赖不变；实际 `uv build --offline --wheel --out-dir .local/dist` 确认模板包含在wheel，非只验证editable环境。

实际自包含HTML：`.local/html/official-feb-delivery.html` 和 `.local/html/study-delivery.html`（开发检查页保留`*-final.html`），来源分别是本轮2月新比较与此前已独立核账四窗study。另有不同新路径的重复HTML用于字节比对，不覆盖原页面。真实Chromium直接file://检查桌面1440×1000、小屏390×844，全部4×3×4=48切换、672个原指标title及月度标签与原JSON逐项严格相等；键盘选择、无页面水平溢出、0外部resource请求、控制台0错误/警告。浏览器工具初始禁止file://，通过本机显式配置启用本轮文件检查，不需要服务器。脚本/截图/工具记录在`.local`，不提交。

UI自审为主线程审查（当前工具无独立子代理），不是外部设计审查；用户明确禁止新文档体系，设计约束记入既有规格及模板说明，无新增PRODUCT/DESIGN。机械检测工具因缺HTML解析模块降级regex并返回空列表，**不宣称完整CSS/对比度检测通过**。实际首轮截图发现小屏SVG固定viewBox使标签过小，改用容器宽度画布/日期短标签；对现金窄区间刻度保留小数避免重复零标签。桌面/小屏和数据交互已复核，不进行无限视觉调整。

### 最终检查与交付边界

锁定安装、全套 **269 passed / 0 failed / 0 skipped**（245既有＋15准备＋9浏览），编译src/tools/tests，qfs/prepare/browse CLI/help、diff检查及离线wheel构建通过。原Funding计划/毫秒顺序/年化null/study不足四窗扫描回归保留。第一阶段12月选择工具、执行/账户/指标生产代码没有修改；原报告/选择记录/输入不覆盖，最终SHA树另复核：两个原study各211文件及原2月52文件均与旧证据完全相同，12月选择JSON字节不变；交付HTML同源重复字节相同，保全记录 `.local/html/delivery-integrity.json`。交付页面又经file://全部48切换/672原指标检查通过，0外部resources。

阶段一已本地提交 `7fb0418`；阶段二提交SHA由Git记录（不在受其管理文档硬编码自身SHA）。新工作未推送，不能把a335702的远端CI success算作新提交CI。全部本轮范围完成，等待用户最终验收；没有资源阻塞。本轮仅验证2月和window-01 raw准备，不宣称全范围准备完好；只支持BTCUSDT官方monthly与原已审计Funding范围，数据仍已见。导出HTML不能替代独立核账/保证来源真实性，未验证所有浏览器/OS，hard-link原子发布依赖目标文件系统支持。旧仓库只读；无行情、报告、HTML、本机配置、密钥或进度记录进入提交。

## V2 第二阶段选择证据完整性补修（基线 e492f0f）

本轮从 `e492f0f24116bb0a41ddb10443686c8ad2f18962` 干净工作区开始，只修生产配置和独立核账的月度扫描完整性。没有改变策略/账户/成本/指标、已验Funding范围、第一阶段12月选择或四窗选择规则；没有新增依赖、功能或文档体系。本轮仅本地提交，不自动推送，由用户最终验收。

### 失败回归 → 修复

先新增 `tests/test_study_evidence.py` 的4个失败回归：将两窗证据截为首窗的连续月前缀，同时减少证据windows和配置windows、重算SHA，保留声明覆盖结束点及“扫描耗尽”说明。旧 `StudyConfig.load` 和独立 `selected_from_months` 均未拒绝；公开study CLI进入行情读取后才因缺分钟失败，独立核账CLI进入后续报告字段读取。测试要求失败必须来自月度证据完整性，不能依靠旧哈希、行情缺失或缺报告。4项修复前确实失败，修复后通过。

生产端独立于停止说明，从source_coverage与固定Funding范围交集计算首个完整UTC月的起点（下界向上取月首）和最后完整UTC月的结束点（上界向下取月首）。月证据必须从规定起点连续覆盖，不能越过完整月范围；重新计算最早窗口后，若不足4窗，实际扫描结束必须等于最后完整月结束，否则报 `incomplete complete-month scan`。找到最早4窗后仍允许提前停止，不以声称的窗口数量、stop_reason或SHA代替完成性判断。

独立核账只复用既定Funding范围常量，自行枚举交集内完整UTC月、验证证据是从首月开始的连续前缀，再用原独立6月规则计算窗口；不足4窗须覆盖全部枚举月份。没有导入/调用生产study选择器、配置校验器或引擎来替代验证。边界回归还发现初次枚举会保留来源下界的非午夜时分/纳秒，先失败后改为从UTC月首午夜枚举并按实际上下界过滤，避免把部分月误当完整月。

### 验证

- 全套 **245 passed、0 failed、0 skipped**，原228测试全部保留；新增17项覆盖同步截短拒绝、两类CLI失败原因、完整扫描但仅1/2/3窗接受、最早4窗提前停止接受、漏首月/中间月、Funding前月份/尾部部分月拒绝，以及源首尾部分月、±1ns、UTC时区换算、Funding首尾截断。
- `uv sync --locked --extra test`、编译src/tools/tests、qfs及study CLI/help、核账CLI/help、`git diff --check`通过；uv.lock与第一阶段选择工具未变。
- `StudyConfig.load('.local/v2-study.json')`仍接受原最早4窗及原选择SHA。只读复核 `runs/study-g5jo08cs` 全部4窗48组交易、分钟权益、分期、年化null和顶层汇总/差值；新证据为 `.local/v2-study-evidence-fix-verification.json`，未覆盖旧证据。
- 复核前后 `runs/study-g5jo08cs`、`runs/study-6hsj7a9v` 各211文件SHA树均与旧证据完全一致；原12月选择JSON保持字节相同。快照另存 `.local/v2-study-evidence-fix-report-snapshots.json`。本轮**未重跑真实策略或新增真实重复性验证**，新核账记录明确repeatability未检查；历史重复性事实仍来自原轮。

限制：这里只验证已记录source_coverage和月度质量证据的日历完整性，不重新扫描原始行情或证明所有来源声明可信；SHA不是质量/预存时间的独立证明。原全部已见历史与执行近似限制不变。旧仓库只读，无行情/报告/本机配置进入提交，无自动推送。

## V2 第二阶段：固定多窗口验证（基线 e280dba）

从已推送 `e280dba9897680d6271e86e0ba9e39591222c75d` 的干净main开始，保留修改、不reset，旧QuantForge只读。初始fetch/CI查询出现连接/TLS错误；随后fetch成功确认远端无新代码，CI API复核 [Offline tests run 38252438955](https://github.com/Jasmine-wind/QuantForge-Strategies/actions/runs/38252438955) 的headSha及completed/success。本阶段只本地提交，不把基线CI成功当作新提交CI已运行。

先补充现有V2_SPEC第二阶段及AGENTS，再实现固定6月选择。没有新增文档体系/运行依赖/策略或参数搜索；V1_SPEC、Account/engine、Funding规则、分期及年化null契约未修改。

### 实现与验收映射

| 项目 | 实现 / 验证 | 状态 |
|---|---|---|
| 固定6月/最多4窗，缺口断块，最早非重叠 | `study.py::choose_study_windows`，旧只读选择工具新增 `--mode study`；默认12月JSON与旧证据字节相同 | 完成 |
| 公共假设 / 严格配置 / 预存选择记录 | `StudyConfig`：全列表身份、SHA/固定policy/有序月质量、6完整月/标签/次序/来源/覆盖与倍增成本 | 完成 |
| 单体CLI / 独立窗口账户 | `qfs study`，各窗口独立初始权益，完整4×3重跑，窗口内连续分期 | 完成 |
| 复用比较，无第二套引擎 | compare仅抽出caller-owned空私有目录writer；原compare CLI前置失败与原子发布保留 | 完成 |
| 全结果 / 百分点差 / 元数据 | 顶层study.json/csv/report.md，完整comparison相对路径及哈希，无合并净值/收益/年化 | 完成 |
| 整体原子发布 / 后续失败清理 | 一个study staging；后续窗口真实缺Mark输入失败，先前完整结果也删除，无成功子集 | 完成 |
| CLI/确定性/独立核账 | 完整6月网格合成两窗CLI重复，107文件一致，工具核账；真实4窗重复211文件 | 完成 |
| 旧205回归 / 无新增依赖 | V1/Funding/年化null测试保留，uv.lock不变；原2月账本对照 | 完成 |

### 自动测试

全套 **228 passed，0 failed，0 skipped**。新增19个study行为测试（含4个新增配置负例）和4个固定窗口选择测试。CLI集成使用两段真实长度的6个月**合成分钟网格**，运行4成员×3场景、重复两次并通过独立核账，不mock生产引擎；后续窗口缺文件通过公开CLI失败并清空整个staging。全套约6分钟，无本机行情依赖，现有GitHub Actions自动包含新测试。

配置/选择负例覆盖重叠、错序、非月首、非6月、重复/不安全标签、超过4窗、空窗、公共成本覆盖/未知字段、来源不一致、证据哈希/固定policy错误、质量记录缺月、结果参与选择及手选子集。固定规则覆盖最早4窗/缺口/缺月/不足2～3窗不凑数。原205测试全部保留。汇总/单位/初始权益与原比较结果核对；不可计算年化仍必须正确为null，不能跳过。

```bash
uv sync --locked --extra test
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src tools tests
.venv/bin/qfs study --help
.venv/bin/python tools/verify_study.py --config .local/v2-study.json \
  --output .local/v2-study-verification-clean.json
```

`tools/verify_study.py`不导入生产study/selector或调用引擎：独立重放固定选择标记，复用 `verify_comparison` / `ledger` 核对所有交易/分钟/Mark/Funding/费用/滑点/完整日Sharpe/年化null/分期，再核对顶层JSON/CSV指标、独立初始权益和同窗口同场景百分点差及全部SHA。`--config`执行两次比对整个目录；`--run`只核账，不伪称重复验证。输出必须为新文件，不覆盖既有证据。

### 真实窗口与选择原因

先保存纯质量JSON/SHA（见DATA_AUDIT），再转换到4个新目录并用严格loader校验，最后运行策略。共核验50个月；选到最早4窗后停止。2020-08～11、2021-01～05、2022-02～06等不足6月候选被Mark/Funding缺口打断，原有缺口未补、未缩短、未替换差窗口。

| label / UTC [start,end) | 天数 | 与此前真实验证交集 | 原始comparison文件 / 分期行 |
|---|---:|---|---:|
| window-01 2020-02-01～2020-08-01 | 182 | 包含2020-02整月 | 52 / 84 |
| window-02 2021-08-01～2022-02-01 | 184 | 不交原29天/366天；仍是旧已见数据 | 52 / 96 |
| window-03 2023-03-01～2023-09-01 | 184 | 原366天前半 | 52 / 84 |
| window-04 2023-09-01～2024-03-01 | 182 | 原366天后半 | 52 / 96 |

不同窗口各自10000初始权益、50%名义仓位、maximum_leverage1，base费用/滑点各0.0005。后两窗即使相邻也不继承账户或拼接为原年账户；资金/策略Flat初态与窗口结束处理是独立实验。4窗共48组，全部结果保留。

### 真实base结果（不作为成功或盈利判据）

| 窗口 | EMA净收益 / 回撤 / 交易 | 布林净收益 / 回撤 / 交易 | USDT现金净收益 | 永续多头净收益 / 回撤 |
|---|---|---|---:|---|
| 01 | −15.6669% / 37.7473% / 28 | −19.8634% / 30.5999% / 40 | 0 | 6.1736% / 35.2791% |
| 02 | −9.3946% / 22.4548% / 21 | 3.7707% / 15.1339% / 42 | 0 | −8.9093% / 34.6583% |
| 03 | 1.0041% / 12.9948% / 21 | −11.5299% / 18.1184% / 45 | 0 | 3.9919% / 12.5575% |
| 04 | 28.4867% / 16.9269% / 14 | −31.3185% / 34.3252% / 34 | 0 | 63.1860% / 14.3112% |

完整48行含Sharpe/年化/交易/fees/slippage/Funding及相对现金/永续的百分点差。例如base EMA相对永续在4窗分别约−21.8405、−0.4853、−2.9878、−34.6994 **百分点**，不是相对比例。成本场景都重跑、Funding原始事件不变；没有只扣估算成本。没有按窗口收益排名、淘汰、独立样本显著性或盈利结论，也无跨窗汇总收益。

### 实际复核 / 交付边界

四窗48组独立核账全部通过，真实study完整重复两次，**211/211文件一致**；各窗口52原文件＋顶层3文件，全部路径稳定、无随机staging内容。选择记录、输入、provenance及旧报告/证据保留，不覆盖；新本机验证JSON及报告留在忽略目录。最终干净提交SHA和目录记录在报告与新证据中，不在受其管理文档硬编码自身SHA。

所有可完成的阶段验收完成。最初网络错误已恢复，无数据条件阻塞；远端新阶段CI仍待用户批准推送。限制不变：这些是旧已见数据、4个固定窗口及常数费用/1m近似，不能当独立OOS/独立统计样本或盈利证明；分钟内风险/保证金模型仍不完整。模板selection SHA须由用户预存本机质量记录计算，不能将占位配置当可运行/已认证资料。只提交代码/通用模板/既有说明，不提交行情、报告、本机配置或密钥；旧仓库未修改。

## V2 第一阶段验收补修（基线 9e4508b）

本轮开始于已推送的 `9e4508b87779f6c564006e3c6a99bdcc5ddd40a0`，fetch确认远端相同、工作区干净。只修 `tools/verify_comparison.py` 的独立年化核验，新增 `tests/test_verify_comparison.py`，更新本记录；生产指标/报告、账户、策略、Funding及V1/V2规格均未修改，不扩展功能，不reset，旧仓库只读。

### 复现 → 回归 → 修复

通过公开 `python -m qfs.cli compare --config ...` 创建完整12组报告，再通过公开 `tools/verify_comparison.py --run ... --output ...` 核账。最小合成fixture为3分钟、初始10000、50%仓位、价格100→110：EMA/永续的期末10500合法，年化 `1.05^175200−1` 超出float64，生产正确输出null。修复前命令

```bash
.venv/bin/pytest -q tests/test_verify_comparison.py::test_short_positive_return_overflow_full_comparison_verifies
```

失败于核账第50行：`OverflowError: math range error`。完成公开CLI复现及失败回归后才修改；独立账本权益/实际长度对应log-growth约8548.036762，float64 log上限约709.782713，排除时长单位/读取错误，原因是无条件调用expm1。

核账现在从已复核权益及配置初始权益、实际日历长度独立计算log-growth，用 `sys.float_info.max` 判定可表示范围：溢出必须报告为null；否则禁止null并严格比较 `expm1(log_growth)` 数值。负log-growth下溢至−1仍可计算，现金年化零也必须为数值。没有看到null就跳过，没有调用生产 `metric_summary`。

6个新增CLI回归：完整12成员/场景溢出报告通过全部账本/分期核验；正/零/负可表示年化被误写null时拒绝；应溢出却给有限数值时拒绝；可表示但数值错误仍拒绝。篡改测试同步更新原summary、comparison副本/CSV及所有相关SHA，确保失败确实由独立指标判断而不是旧哈希/复制不一致引起。原199个测试全部保留。合成fixture仅检验正确性，不是盈利证据。

### 验证与历史证据保护

锁定安装 `uv sync --locked --extra test` 后全套 **205 passed，0 failed，0 skipped**；`compileall src tools`、qfs/compare/核账工具CLI help与 `git diff --check` 通过。

现成真实报告只读复核：2020-02的 `runs/compare-aaadgj0m/` 与366天的 `runs/compare-6k7ms7fi/`，全部24组交易、每分钟账户、完整日Sharpe/年化/回撤及分期核账通过。两目录全部52文件SHA与9e4508b先前记录逐个相等，历史报告/输入/验证JSON均不覆盖；新证据仅保存于忽略目录 `.local/v2-annualized-fix-{feb,long}-verification.json`。本次只是重新核账现有报告，不把单次核账伪称新一轮重复性验证。

### 基线远端 CI

基线 `9e4508b87779f6c564006e3c6a99bdcc5ddd40a0` 推送后 **Offline tests 已成功**：[GitHub Actions run 38249983169](https://github.com/Jasmine-wind/QuantForge-Strategies/actions/runs/38249983169)。本轮通过GitHub CLI核对headSha、completed/success及锁定安装、pytest、编译、CLI步骤均成功。这更新了下文初次交付时“远端尚未运行”的历史状态；**新补修仅本地提交，未推送，不能将基线CI成功当作新提交远端CI已运行**。

所有可完成补修及复核已完成，等待用户最终验收。无新增依赖/文档体系，不提交行情、生成报告或本机配置。仍保留float64/分钟采样/不完整保证金模型和旧已见数据非独立OOS的限制；年化null只表达无法在既定数值范围表示，不代表策略或账本失败。

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
| 最小CI | `.github/workflows/tests.yml`，Python3.12 / uv.lock / pytest及编译，不依赖行情 | 基线9e4508b远端CI已成功，链接见补修记录；新补修尚未推送 |
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

初次本地交付时功能、测试、真实运行及核账完成，远端CI尚未执行。此后9e4508b已按用户要求推送且GitHub Actions成功（链接见补修记录）；本次新补修仍按要求只本地提交、不推送。12个月是预先固定的资源上限，不代表验证全部2020～2026。仍是旧已见数据、有限窗口、常数成本/1m成交、float64及不完整保证金模型，非独立OOS、非显著性或盈利证明；分钟内风险仍可能漏采样。

行情、报告、本机配置和质量/核账JSON留在Git忽略目录，不提交。旧仓库HEAD及工作区未变；原V2交付9e4508b已获准推送，新补修仅本地提交，等待用户最终验收。

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
