"""Post-report attribution, not a backtest or an independent financial audit."""
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np
import pandas as pd

from .browse import check_files, inside, load_view
from .data import sha256
from .report import code_identity, write_json

VERSION = 'qfs-diagnostics-1'
TOTALS = {'gross_pnl': 'gross_pnl', 'net_pnl': 'net_pnl', 'fees': 'fees',
          'slippage_cost': 'slippage', 'funding_net': 'funding'}
LIMITATIONS = [
    '探索性已见历史，不是独立OOS；窗口不是独立统计样本，不作显著性或盈利证明。',
    '方向归属为完整交易；不把跨月整笔盈亏归入退出月，月度表现仍以原连续权益分期为准。',
    '滑点已在成交盈亏内，单列但不重复扣款；成本差来自完整重跑，不是估算成本相减。',
    '前5笔仅在本组正净盈亏交易内按净利润降序，平手按完成序；不挑选研究窗口。',
    '正利润占比的分母是全部正净盈亏交易之和；净盈亏占比仅当总净盈亏>0时适用，可超过100%（其他交易抵消）。',
    '报告完整性与方向加总核对不等同独立逐分钟财务核账；应另运行verify_comparison/verify_study。',
]


def close(a, b, label):
    if not math.isfinite(float(a)) or not math.isfinite(float(b)) or not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError(f'diagnose: ledger grouping mismatch {label}: {a} != {b}')


def statistics(trades):
    net = trades.net_pnl
    winners, losers = net[net > 0], net[net < 0]
    streak = maximum = 0
    for value in net:
        streak = streak + 1 if value < 0 else 0
        maximum = max(maximum, streak)
    return {'trade_count': len(trades), **{k: float(trades[v].sum()) for k, v in TOTALS.items()},
            'win_rate': len(winners) / len(net) if len(net) else None,
            'average_win': float(winners.mean()) if len(winners) else None,
            'average_loss': float(losers.mean()) if len(losers) else None,
            'average_win_loss_ratio': float(winners.mean() / abs(losers.mean())) if len(winners) and len(losers) else None,
            'profit_factor': float(winners.sum() / abs(losers.sum())) if len(losers) else None,
            'max_consecutive_losses': maximum}


def trade_diagnostics(trades, summary):
    required = {'direction', 'entry_time', 'exit_time', 'exit_reason', 'entry_fee', 'exit_fee', 'entry_slippage', 'exit_slippage', *TOTALS.values()}
    if not required <= set(trades.columns) or not trades.direction.isin(['long', 'short']).all():
        raise ValueError('diagnose: invalid completed trade fields/directions')
    numeric = list(TOTALS.values()) + ['entry_fee', 'exit_fee', 'entry_slippage', 'exit_slippage']
    if not np.isfinite(trades[numeric].to_numpy(dtype=float)).all():
        raise ValueError('diagnose: non-finite trade values')
    exits = pd.DatetimeIndex(pd.to_datetime(trades.exit_time, utc=True))
    entries = pd.DatetimeIndex(pd.to_datetime(trades.entry_time, utc=True))
    if not exits.is_monotonic_increasing or (exits < entries).any():
        raise ValueError('diagnose: trades not in actual completion order')
    for i, t in trades.iterrows():
        close(t.fees, t.entry_fee + t.exit_fee, f'trade {i} fees')
        close(t.slippage, t.entry_slippage + t.exit_slippage, f'trade {i} slippage')
        close(t.net_pnl, t.gross_pnl - t.fees + t.funding, f'trade {i} net')
    overall = statistics(trades)
    directions = {side: statistics(trades[trades.direction == side]) for side in ('long', 'short')}
    for key in ('trade_count', *TOTALS):
        close(overall[key], summary[key], key)
        close(sum(d[key] for d in directions.values()), summary[key], 'directions ' + key)
    for key in ('win_rate', 'average_win_loss_ratio', 'profit_factor'):
        if overall[key] is None or summary[key] is None:
            if overall[key] != summary[key]:
                raise ValueError(f'diagnose: ledger statistics mismatch {key}')
        else:
            close(overall[key], summary[key], key)
    positive_total = float(trades.loc[trades.net_pnl > 0, 'net_pnl'].sum())
    def record(i):
        trade = trades.iloc[i]
        return {'completion_number': i + 1, **{k: trade[k] for k in ('direction', 'entry_time', 'exit_time', 'exit_reason')},
                **{k: float(trade[k]) for k in TOTALS.values()},
                'terminal_close': trade.exit_reason == 'end_of_test',
                'positive_profit_share': float(trade.net_pnl / positive_total) if trade.net_pnl > 0 and positive_total > 0 else None,
                'total_net_share': float(trade.net_pnl / overall['net_pnl']) if overall['net_pnl'] > 0 else None}
    top = sorted((i for i in range(len(trades)) if trades.net_pnl.iloc[i] > 0), key=lambda i: (-trades.net_pnl.iloc[i], i))[:5]
    top_net = float(sum(trades.net_pnl.iloc[i] for i in top))
    return {'overall': overall, 'directions': directions, 'top_profitable_trades': [record(i) for i in top],
            'top5_net_pnl': top_net, 'top5_positive_profit_share': top_net / positive_total if positive_total > 0 else None,
            'top5_total_net_share': top_net / overall['net_pnl'] if overall['net_pnl'] > 0 else None,
            'terminal_trades': [record(i) for i in range(len(trades)) if trades.exit_reason.iloc[i] == 'end_of_test']}


def records_from_view(view):
    root = Path(view['source_directory'])
    records = []
    for window in view['windows']:
        relative = '' if window['label'] == 'comparison' else 'windows/' + window['label'] + '/'
        lookup = {(m['scenario'], m['member']): m['summary'] for m in window['members']}
        for member in window['members']:
            report = relative + f"reports/{member['scenario']}/{member['member']}"
            trades = pd.read_csv(inside(root, report) / 'trades.csv', float_precision='round_trip')
            summary = member['summary']
            base = lookup[('base', member['member'])]
            record = {'window': window['label'], 'scenario': member['scenario'], 'member': member['member'],
                      'start': window['config']['start'], 'end': window['config']['end'], 'raw_report': report,
                      'summary': summary, 'config': summary['config'], 'source_code': window['code'],
                      **trade_diagnostics(trades, summary),
                      **{k: member[k] for k in ('return_minus_cash_pp', 'return_minus_perpetual_pp')},
                      'cost_change_from_base': {'return_pp': 100 * (summary['total_return'] - base['total_return']),
                                               **{k: summary[k] - base[k] for k in TOTALS}}}
            records.append(record)
    # Protect the binding against modifications after the shared reader completed.
    check_files(root, view['source_sha256'], set(view['source_sha256']))
    return records


def csv_rows(records):
    rows = []
    for record in records:
        row = {k: record[k] for k in ('window', 'scenario', 'member', 'start', 'end', 'raw_report', 'return_minus_cash_pp', 'return_minus_perpetual_pp',
                                     'top5_net_pnl', 'top5_positive_profit_share', 'top5_total_net_share')}
        row.update(record['overall'])
        for direction, values in record['directions'].items():
            row.update({direction + '_' + k: v for k, v in values.items()})
        row.update({'cost_change_' + k: v for k, v in record['cost_change_from_base'].items()})
        for key in ('top_profitable_trades', 'terminal_trades'):
            row[key] = json.dumps(record[key], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        rows.append(row)
    return rows


def markdown(records, run):
    def n(value, pct=False):
        return 'n/a' if value is None else f'{value * (100 if pct else 1):.4f}'
    lines = ['# 收益与风险诊断 · 探索性历史', '', f'原报告：{Path(run).as_uri()}（完整SHA/配置/代码身份见diagnostics.json）。', '', *['- ' + l for l in LIMITATIONS], '',
             '## 全部窗口 / 成员 / 完整成本重跑', '',
             '| 窗口 | 场景 | 成员 | 净收益% | Long净盈亏 | Short净盈亏 | 连亏笔数 | 前5正利润占比% | Δ永续百分点 | Δ现金百分点 | Δbase收益百分点 |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in records:
        lines.append('| ' + ' | '.join([r['window'], r['scenario'], r['member'], n(r['summary']['total_return'], True),
                    n(r['directions']['long']['net_pnl']), n(r['directions']['short']['net_pnl']), str(r['overall']['max_consecutive_losses']),
                    n(r['top5_positive_profit_share'], True), n(r['return_minus_perpetual_pp']), n(r['return_minus_cash_pp']),
                    n(r['cost_change_from_base']['return_pp'])]) + ' |')
    lines += ['', '## 逐组事实（不排名或淘汰窗口）', '']
    for r in records:
        if r['member'] in ('usdt_cash', 'btcusdt_perpetual_long_hold'):
            continue
        net, delta = r['overall']['net_pnl'], r['return_minus_perpetual_pp']
        lines.append(f"- {r['window']} / {r['scenario']} / {r['member']}：{'净盈利' if net > 0 else '净亏损' if net < 0 else '净持平'} {n(net)} USDT；"
                     f"相对永续{'落后' if delta < 0 else '领先' if delta > 0 else '持平'} {n(abs(delta))}百分点。"
                     f"前5笔占全部正利润 {n(r['top5_positive_profit_share'], True)}%；终点强平 {len(r['terminal_trades'])}笔。")
    lines += ['', '## 后续问题与证据边界', '',
              '对照各窗方向贡献、连亏与前5利润占比，检查趋势参与不足、逆势方向亏损、少数大交易依赖和成本敏感性；这些是后续研究问题，不是已经确认的因果解释。',
              '若相对永续差距持续为负，只能说明这些固定窗口/假设下落后该基准；不能据此证明未来盈利/亏损或交易可执行性。',
              '方向笔数、费用、滑点、Funding、均盈/均亏/PF、前5逐笔和终点逐笔在CSV/JSON中完整保留；null为n/a。不从图形样本推导财务指标。', '']
    return '\n'.join(lines)


def diagnose(run, output):
    root, output = Path(run).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError('diagnose: output must be new and outside original report directory')
    identity = code_identity()
    view = load_view(root)  # the existing mandatory inventory/hash/copy checks
    records = records_from_view(view)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.qfs-diagnose-', dir=output.parent))
    try:
        pd.DataFrame(csv_rows(records)).to_csv(staging / 'diagnostics.csv', index=False, float_format='%.17g', lineterminator='\n')
        (staging / 'report.md').write_text(markdown(records, root), encoding='utf-8', newline='\n')
        payload = {'diagnostics_version': VERSION, 'source_directory': str(root), 'source_sha256': view['source_sha256'],
                   'diagnostic_code': identity, 'records': records, 'limitations': LIMITATIONS,
                   'artifact_sha256': {name: sha256(staging / name) for name in ('diagnostics.csv', 'report.md')}}
        write_json(staging / 'diagnostics.json', payload)
        check_files(root, view['source_sha256'], set(view['source_sha256']))
        if output.exists() or code_identity() != identity:
            raise ValueError('diagnose: output appeared or code changed during generation')
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return output


def load_diagnostics(directory, view):
    root = Path(directory).resolve()
    before = {p.name: sha256(p) for p in root.iterdir() if p.is_file()}
    if set(before) != {'diagnostics.json', 'diagnostics.csv', 'report.md'}:
        raise ValueError('diagnose: incomplete diagnostic inventory')
    payload = json.loads((root / 'diagnostics.json').read_text(encoding='utf-8'))
    if (not isinstance(payload, dict) or set(payload) != {'diagnostics_version', 'source_directory', 'source_sha256', 'diagnostic_code', 'records', 'limitations', 'artifact_sha256'}
            or not isinstance(payload['diagnostic_code'], dict) or not {'git_commit', 'git_dirty'} <= set(payload['diagnostic_code'])
            or not isinstance(payload['source_directory'], str)):
        raise ValueError('diagnose: incomplete diagnostic metadata')
    if payload.get('diagnostics_version') != VERSION or payload.get('source_sha256') != view['source_sha256']:
        raise ValueError('diagnose: source report binding mismatch')
    check_files(root, payload.get('artifact_sha256'), {'diagnostics.csv', 'report.md'})
    # Recompute only trade grouping, not the account engine, from the bound report.
    records = records_from_view(view)
    if payload.get('records') != records or payload.get('limitations') != LIMITATIONS:
        raise ValueError('diagnose: incomplete or mismatched diagnostic records')
    expected_csv = pd.DataFrame(csv_rows(records)).to_csv(index=False, float_format='%.17g', lineterminator='\n')
    if (root / 'diagnostics.csv').read_text(encoding='utf-8') != expected_csv:
        raise ValueError('diagnose: diagnostic CSV disagrees')
    check_files(root, before, set(before))
    return payload
