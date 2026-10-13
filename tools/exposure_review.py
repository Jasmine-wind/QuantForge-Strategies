"""Read-only time exposure alongside existing, source-bound return diagnostics."""
import argparse
import hashlib
from importlib.metadata import version
from io import BytesIO
import json
from numbers import Number
from pathlib import Path
import platform
import re
import shutil
import tempfile

import pandas as pd

from qfs.browse import inside, load_view
from qfs.data import sha256
from qfs.diagnose import load_diagnostics
from qfs.report import code_identity, write_json


VERSION = 'qfs-exposure-review-1'
COLUMNS = tuple(('source window scenario member start end raw_report window_minutes long_minutes short_minutes '
                 'flat_minutes holding_minutes long_fraction short_fraction flat_fraction participation_rate '
                 'long_trade_count short_trade_count long_average_holding_hours short_average_holding_hours '
                 'end_of_test_count initial_equity total_return maximum_drawdown trade_count net_pnl long_net_pnl '
                 'short_net_pnl fees slippage_cost funding_net top5_net_pnl top5_positive_profit_share '
                 'top5_total_net_share max_consecutive_losses return_minus_cash_pp return_minus_perpetual_pp '
                 'cost_return_change_pp').split())
DEFINITIONS = {
    'intervals': 'UTC integer minutes; window [start,end), holdings [entry,exit); never sort, clip or round trades',
    'flat': 'initial, between-trade and trailing gaps; includes the actual one-minute reversal gap',
    'partition': 'long_minutes + short_minutes + flat_minutes = window_minutes; holding = long + short',
    'fractions': 'direction/flat minutes divided by window_minutes; participation_rate = holding_minutes/window_minutes',
    'averages': 'direction minutes / 60 / direction trade count; no trades => null',
    'terminal': 'end_of_test count; terminal reason iff exit equals window end',
    'financials': 'copied validated summary/diagnostics; cost differences are actual full-rerun results, not estimates',
    'units': 'PnL/costs in USDT; return/fractions are ratios; *_pp already in percentage points; null is n/a',
    'order': 'source argument order, original windows, original scenario/member order; no filtering or ranking',
}
LIMITATIONS = [
    '合成来源仅用于正确性验证、不是历史绩效；历史来源也是已见历史，不是独立OOS、显著性检验或未来盈利证明。',
    '仅按持仓时间衡量参与，不按资金、名义金额、杠杆或风险加权；不是资金利用率。',
    '仓位参与、方向盈亏与基准差并列描述，不构成因果关系；不能把收益除以参与率外推满仓收益。',
    '不拼接跨窗净值、不合并或年化跨窗收益；跨月持仓不按退出月份归集。',
    '前5仅指原诊断的正净盈利交易，不足5笔全列；净盈亏占比分母非正时n/a，可超过100%。',
    '滑点已在成交盈亏内，不重复扣款；成本场景来自原完整重跑，不是实际交易所费率承诺。',
    '这里只校验报告/诊断完整性及时间分配，不重新执行信号、账户或独立财务核账，也不重读行情。',
    'SHA为文件绑定而非真实性签名；原分钟采样、成交近似及无完整保证金模型的限制仍有效。',
]
NAMES = {'ema_20_50': 'EMA20/50', 'bollinger_20_2': '布林20/2', 'usdt_cash': 'USDT现金',
         'btcusdt_perpetual_long_hold': '永续多头基准'}
SCENES = {'base': '基准成本', 'slippage_x2': '滑点×2', 'fee_and_slippage_x2': '手续费/滑点×2'}
TIME_FIELDS = ('entry_time', 'exit_time', 'direction', 'exit_reason')


def _minute(value, label):
    if value is None or isinstance(value, Number):
        raise ValueError(f'exposure: invalid {label} timestamp')
    try:
        time = pd.Timestamp(value)
        if pd.isna(time):
            raise ValueError('NaT')
        time = time.tz_localize('UTC') if time.tzinfo is None else time.tz_convert('UTC')
        if time.value % 60_000_000_000:
            raise ValueError('not minute aligned')
        return time.value // 60_000_000_000
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'exposure: invalid/minute-unaligned {label}: {value}') from exc


def exposure(trades, start, end):
    """Partition [start,end) from ordered [entry,exit) trades, in exact UTC minutes.

    No sorting, clipping, signal/price reading or capital weighting. Adjacent
    intervals share no time; actual reversal gaps belong to Flat. The caller
    separately establishes report integrity and diagnostic/source binding.
    """
    left, right = _minute(start, 'start'), _minute(end, 'end')
    if right <= left or not set(TIME_FIELDS) <= set(trades.columns):
        raise ValueError('exposure: require a positive window and complete trade time fields')
    minutes = {'long': 0, 'short': 0}
    counts = {'long': 0, 'short': 0}
    cursor, flat, terminal = left, 0, 0
    for i, (entry, exit, direction, reason) in enumerate(trades[list(TIME_FIELDS)].itertuples(index=False, name=None), 1):
        a, b = _minute(entry, f'trade {i} entry'), _minute(exit, f'trade {i} exit')
        if not left <= a < b <= right:
            raise ValueError(f'exposure: trade {i} outside window or non-positive duration')
        if a < cursor:
            raise ValueError(f'exposure: trade {i} overlaps or precedes previous exit')
        if direction not in counts or reason not in {'reverse_signal', 'strategy_exit', 'end_of_test'}:
            raise ValueError(f'exposure: trade {i} invalid direction/exit reason')
        if (reason == 'end_of_test') != (b == right):
            raise ValueError(f'exposure: trade {i} terminal reason/time mismatch')
        flat += a - cursor
        minutes[direction] += b - a
        counts[direction] += 1
        terminal += int(reason == 'end_of_test')
        cursor = b
    flat += right - cursor
    window, held = right - left, sum(minutes.values())
    if held + flat != window:
        raise ValueError('exposure: time partition does not cover window')
    return {'window_minutes': window, **{s + '_minutes': minutes[s] for s in counts},
            'flat_minutes': flat, 'holding_minutes': held,
            **{s + '_fraction': minutes[s] / window for s in counts},
            'flat_fraction': flat / window, 'participation_rate': held / window,
            **{s + '_trade_count': counts[s] for s in counts},
            **{s + '_average_holding_hours': minutes[s] / 60 / counts[s] if counts[s] else None for s in counts},
            'end_of_test_count': terminal}


def _snapshot(root):
    return {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob('*')) if p.is_file()}


def _code():
    return {'script_sha256': sha256(__file__), 'qfs': code_identity()}


def _record(label, diagnostic, times):
    d, s = diagnostic, diagnostic['summary']
    if (times['long_trade_count'] + times['short_trade_count'] != s['trade_count'] or
            times['end_of_test_count'] != len(d['terminal_trades'])):
        raise ValueError('exposure: trade counts disagree with bound diagnostics')
    return {'source': label, **{k: d[k] for k in ('window', 'scenario', 'member', 'start', 'end', 'raw_report')},
            **times, **{k: s[k] for k in ('initial_equity', 'total_return', 'maximum_drawdown', 'trade_count',
                                         'net_pnl', 'fees', 'slippage_cost', 'funding_net')},
            **{side + '_net_pnl': d['directions'][side]['net_pnl'] for side in ('long', 'short')},
            **{k: d[k] for k in ('top5_net_pnl', 'top5_positive_profit_share', 'top5_total_net_share',
                                'return_minus_cash_pp', 'return_minus_perpetual_pp')},
            'max_consecutive_losses': d['overall']['max_consecutive_losses'],
            'cost_return_change_pp': d['cost_change_from_base']['return_pp'], 'diagnostic_record': d}


def _overlaps(sources):
    spans = [(s['label'], w['label'], _minute(w['config']['start'], 'start'), _minute(w['config']['end'], 'end'))
             for s in sources for w in s['windows']]
    overlaps = []
    for i, (label, window, start, end) in enumerate(spans):
        for other, other_window, a, b in spans[i + 1:]:
            left, right = max(start, a), min(end, b)
            if left < right:
                overlaps.append({'source': label, 'window': window, 'other_source': other, 'other_window': other_window,
                                 'start': pd.Timestamp(left, unit='m', tz='UTC').isoformat(),
                                 'end': pd.Timestamp(right, unit='m', tz='UTC').isoformat()})
    return overlaps


def _markdown(records, sources, overlaps):
    def n(value, percent=False):
        return 'n/a' if value is None else f'{value * (100 if percent else 1):.4f}'
    def row(cells):
        return '| ' + ' | '.join(map(str, cells)) + ' |'
    lines = ['# 仓位暴露与已有收益归因 · 只读研究', '', *['- ' + x for x in LIMITATIONS], '', '## 完整来源', '']
    for source in sources:
        lines += [f"- {source['label']}：原报告 <{Path(source['report_directory']).as_uri()}>；"
                  f"原诊断 <{Path(source['diagnostics_directory']).as_uri()}>。完整SHA见exposure.json。"]
    lines += ['', '## 窗口重叠', '']
    for overlap in overlaps:
        lines += [f"- {overlap['source']}/{overlap['window']} 与 {overlap['other_source']}/{overlap['other_window']} "
                  f"在 [{overlap['start']}, {overlap['end']}) 重叠，不能作为新增独立样本。"]
    if not overlaps:
        lines += ['本次来源间窗口无时间交集，但不因此成为独立统计样本或独立OOS。']
    for source in sources:
        for window in source['windows']:
            rows = [r for r in records if (r['source'], r['window']) == (source['label'], window['label'])]
            lines += ['', f"## {source['label']} / {window['label']} · [{rows[0]['start']}, {rows[0]['end']})", '',
                      '原来源description（仅披露原声明，不鉴定真实性；完整元数据见JSON）：', '', '```json',
                      json.dumps(window['data_source'].get('description', '未提供description，请核对JSON中的data_source'), ensure_ascii=False),
                      '```', '', '### 时间参与（分钟；括号为窗口占比）', '',
                      '| 成员 | 场景 | Long分钟(%) | Short分钟(%) | Flat分钟(%) | 参与率% | L/S笔数 | L/S均时h | 终点平仓笔数 |',
                      '|---|---|---:|---:|---:|---:|---:|---:|---:|']
            for r in rows:
                lines.append(row([NAMES[r['member']], SCENES[r['scenario']],
                    *[f"{r[side + '_minutes']} ({n(r[side + '_fraction'], True)})" for side in ('long', 'short', 'flat')],
                    n(r['participation_rate'], True), f"{r['long_trade_count']}/{r['short_trade_count']}",
                    f"{n(r['long_average_holding_hours'])}/{n(r['short_average_holding_hours'])}", r['end_of_test_count']]))
            lines += ['', '### 原收益、风险及方向/集中度诊断', '',
                      '| 成员 | 场景 | 净收益% | 最大回撤% | Long净USDT | Short净USDT | 前5正利润占比% | Δ现金百分点 | Δ永续百分点 |',
                      '|---|---|---:|---:|---:|---:|---:|---:|---:|']
            for r in rows:
                lines.append(row([NAMES[r['member']], SCENES[r['scenario']], n(r['total_return'], True),
                    n(r['maximum_drawdown'], True), n(r['long_net_pnl']), n(r['short_net_pnl']),
                    n(r['top5_positive_profit_share'], True), n(r['return_minus_cash_pp']), n(r['return_minus_perpetual_pp'])]))
            lines += ['', '### 实际完整成本重跑（并非重新估算）', '',
                      '| 成员 | 场景 | 手续费USDT | 滑点USDT(已在盈亏内) | Funding净USDT | 实际净收益% | Δbase收益百分点 |',
                      '|---|---|---:|---:|---:|---:|---:|']
            for r in rows:
                lines.append(row([NAMES[r['member']], SCENES[r['scenario']], n(r['fees']), n(r['slippage_cost']),
                                  n(r['funding_net']), n(r['total_return'], True), n(r['cost_return_change_pp'])]))
            lines += ['', '### 描述性观察（不作因果推断）', '']
            for name in ('ema_20_50', 'bollinger_20_2'):
                cases = [r for r in rows if r['member'] == name]
                base = cases[0]
                lines += [f"- {NAMES[name]}：base参与率 {n(base['participation_rate'], True)}%，"
                          f"Flat {n(base['flat_fraction'], True)}%（{'超过' if base['flat_fraction'] > .5 else '未超过'}一半时间空仓）；"
                          f"Long/Short净盈亏 {n(base['long_net_pnl'])}/{n(base['short_net_pnl'])} USDT。"
                          f"前5正利润占比 {n(base['top5_positive_profit_share'], True)}%，"
                          f"前5总净盈亏占比 {n(base['top5_total_net_share'], True)}%；"
                          f"相对永续 {n(base['return_minus_perpetual_pp'])} 百分点。",
                          '  三成本场景实际净收益依次为 ' + ' / '.join(n(r['total_return'], True) + '%' for r in cases) + '。']
                for key, label in (('return_minus_cash_pp', '相对现金收益差'), ('return_minus_perpetual_pp', '相对永续收益差')):
                    lost = [SCENES[r['scenario']] for r in cases[1:] if base[key] > 0 and r[key] <= 0]
                    if lost:
                        lines.append(f"  {label}在{'、'.join(lost)}下由正变为非正；仅描述原场景结果，不推断原因。")
            lines += ['', '参与率与基准差同时列出不表示前者导致后者；方向、具体持仓时段、资金数量和成本/Funding均可能相关，尚无控制反事实。']
    return '\n'.join(lines) + '\n'


def review(sources, output):
    """Publish one deterministic, new three-file review of ALL supplied report groups."""
    sources = list(sources) if sources is not None else []
    output = Path(output)
    if output.exists() or output.is_symlink() or not sources:
        raise ValueError('exposure: require sources and a new output directory')
    output = output.resolve()
    identity, provenance, records = _code(), [], []
    labels, roots = set(), set()
    for label, run, diagnostic in sources:
        if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', label) or label in labels:
            raise ValueError('exposure: invalid/duplicate source label')
        root, diagnosis_root = Path(run).resolve(), Path(diagnostic).resolve()
        if root in roots or output.is_relative_to(root) or output.is_relative_to(diagnosis_root):
            raise ValueError('exposure: duplicate report or output inside protected source')
        if not root.is_dir() or not any((root / name).is_file() for name in ('comparison.json', 'study.json')):
            raise ValueError('exposure: require an existing comparison/study report')
        labels.add(label)
        roots.add(root)
        diagnostic_hashes = _snapshot(diagnosis_root)
        if set(diagnostic_hashes) != {'diagnostics.json', 'diagnostics.csv', 'report.md'}:
            raise ValueError('exposure: incomplete diagnostic inventory')
        view = load_view(root)
        if any(view['source_sha256'] == p['report_sha256'] for p in provenance):
            raise ValueError('exposure: duplicate source report content')
        diagnosis = load_diagnostics(diagnosis_root, view)
        last_end = None
        for window in view['windows']:
            start, end = _minute(window['config']['start'], 'start'), _minute(window['config']['end'], 'end')
            if end <= start or (last_end is not None and start < last_end):
                raise ValueError('exposure: overlapping/out-of-order windows within source')
            last_end = end
        for d in diagnosis['records']:
            relative = d['raw_report'] + '/trades.csv'
            blob = inside(root, relative).read_bytes()
            if hashlib.sha256(blob).hexdigest() != view['source_sha256'][relative]:
                raise ValueError(f'exposure: trade snapshot changed: {relative}')
            trades = pd.read_csv(BytesIO(blob), float_precision='round_trip')
            try:
                times = exposure(trades, d['start'], d['end'])
            except ValueError as exc:
                raise ValueError(f"{label}/{d['window']}/{d['scenario']}/{d['member']}: {exc}") from exc
            records.append(_record(label, d, times))
        provenance.append({'label': label, 'report_directory': str(root), 'diagnostics_directory': str(diagnosis_root),
            'report_sha256': view['source_sha256'], 'diagnostics_sha256': diagnostic_hashes,
            'diagnostic_code': diagnosis['diagnostic_code'],
            'windows': [{k: w[k] for k in ('label', 'config', 'data_source', 'data_files', 'code', 'runtime')}
                        for w in view['windows']]})
    overlaps = _overlaps(provenance)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.qfs-exposure-', dir=output.parent))
    try:
        pd.DataFrame(records, columns=COLUMNS).to_csv(staging / 'exposure.csv', index=False, float_format='%.17g', lineterminator='\n')
        (staging / 'report.md').write_text(_markdown(records, provenance, overlaps), encoding='utf-8', newline='\n')
        payload = {'exposure_version': VERSION, 'status': 'completed', 'definitions': DEFINITIONS, 'limitations': LIMITATIONS,
                   'research_code': identity, 'runtime': {'python': platform.python_version(),
                       **{name: version(name) for name in ('pandas', 'numpy', 'pyarrow')}},
                   'sources': provenance, 'records': records, 'overlaps': overlaps,
                   'artifact_sha256': {name: sha256(staging / name) for name in ('exposure.csv', 'report.md')}}
        write_json(staging / 'exposure.json', payload)
        for source in provenance:
            if (_snapshot(Path(source['report_directory'])) != source['report_sha256'] or
                    _snapshot(Path(source['diagnostics_directory'])) != source['diagnostics_sha256']):
                raise ValueError('exposure: source changed during review')
        if output.exists() or output.is_symlink() or _code() != identity:
            raise ValueError('exposure: output appeared or research code changed during review')
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', nargs=3, metavar=('LABEL', 'RUN', 'DIAGNOSTICS'), required=True)
    parser.add_argument('--output', required=True, help='New directory outside original reports/diagnostics')
    args = parser.parse_args()
    try:
        result = review(args.source, args.output)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f'exposure review: {exc}\n')
    print(result)


if __name__ == '__main__':
    main()
