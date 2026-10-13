"""Fixed six-month experiments; no cross-window account or return aggregation."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import tempfile

import pandas as pd

from .compare import MEMBERS, METRICS, member_configs, write_comparison
from .config import Config, utc
from .data import load_data, sha256
from .funding import VERIFIED_START, VERIFIED_END
from .report import LIMITATIONS, code_identity, write_json
from .official import SCAN_SCOPE, check_source_link, source_identity


STUDY_VERSION = "qfs-study-v2-stage2.0"
STUDY_POLICY = {"window_months": 6, "maximum_windows": 4,
                "selection": "earliest consecutive qualified UTC months, nonoverlapping; gaps reset candidates"}


def choose_study_windows(rows):
    selected, block = [], []
    for row in rows:
        left, right = utc(row['start']), utc(row['end'])
        if left != left.normalize().replace(day=1) or right != left + pd.DateOffset(months=1):
            raise ValueError(f"study selection: not a complete UTC month at {left}")
        if type(row['valid']) is not bool:
            raise ValueError('study selection: valid must be boolean')
        if not row['valid']:
            block = []
            continue
        if block and block[-1]['end'] != left.isoformat():
            block = []
        block.append({'start': left.isoformat(), 'end': right.isoformat()})
        if len(block) == 6:
            selected.append({'label': f'window-{len(selected) + 1:02d}', 'start': block[0]['start'],
                             'end': block[-1]['end'], 'months': 6})
            block = []
            if len(selected) == 4:
                break
    return selected


@dataclass(frozen=True)
class StudyConfig:
    windows: tuple
    selection_path: Path
    selection_sha256: str
    selection: dict

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        return cls.from_dict(json.loads(path.read_text(encoding='utf-8')), path.parent)

    @classmethod
    def from_dict(cls, raw, base=None):
        base = Path.cwd() if base is None else Path(base)
        common_keys = {'symbol', 'initial_equity', 'position_fraction', 'maximum_leverage',
                       'taker_fee_rate', 'slippage_rate', 'output_dir'}
        if not isinstance(raw, dict) or set(raw) != common_keys | {'selection_evidence', 'windows'}:
            raise ValueError('study config: require shared assumptions, selection_evidence and windows only')
        items = raw['windows']
        if not isinstance(items, list) or not 1 <= len(items) <= 4:
            raise ValueError('study config: require 1 to 4 windows; do not invent short windows')
        proof = raw['selection_evidence']
        if not isinstance(proof, dict) or set(proof) != {'path', 'sha256'}:
            raise ValueError('study: selection_evidence requires path/sha256')
        proof_path = (base / Path(proof['path'])).resolve()
        if sha256(proof_path) != proof['sha256']:
            raise ValueError(f'study: selection evidence hash mismatch: {proof_path}')
        evidence = json.loads(proof_path.read_text(encoding='utf-8'))
        if (evidence.get('mode') != 'study' or evidence.get('policy') != STUDY_POLICY
                or evidence.get('strategy_results_used') is not False or evidence.get('independent_out_of_sample') is not False):
            raise ValueError('study: require fixed data-only study policy and explicit seen-data boundary')
        rows = evidence.get('months', [])
        official = 'source_identity' in evidence
        coverage = evidence.get('scan_scope' if official else 'source_coverage', {})
        try:
            if official and (evidence.get('scan_version') != 'qfs-official-full-scan-1' or coverage != SCAN_SCOPE
                             or evidence['source_identity'] != source_identity(evidence['source_files'])
                             or 'dataset_identity_sha256' in evidence):
                raise ValueError('study: official full scan scope / identity disagrees')
            first = max(utc(coverage['start_utc_inclusive']), VERIFIED_START)
            first_month = first.normalize().replace(day=1)
            if first_month < first:
                first_month += pd.offsets.MonthBegin(1)
            last = min(utc(coverage['end_utc_exclusive']), VERIFIED_END)
            last_month_end = last.normalize().replace(day=1)
            if first_month >= last_month_end:
                raise ValueError('study: source/Funding intersection has no complete UTC month')
            previous = first_month
            for row in rows:
                left, right = utc(row['start']), utc(row['end'])
                if (left != previous or left != left.normalize().replace(day=1)
                        or right != left + pd.DateOffset(months=1) or type(row['valid']) is not bool
                        or row['valid'] != (not row['errors'])):
                    raise ValueError('study: missing/contradictory inspected month evidence')
                previous = right
            if previous > last_month_end:
                raise ValueError('study: evidence exceeds audited complete-month coverage')
            expected = choose_study_windows(rows)
            if (official or len(expected) < 4) and previous != last_month_end:
                raise ValueError(f'study: incomplete complete-month scan; expected through '
                                 f'{last_month_end.isoformat()}, inspected through {previous.isoformat()}')
        except (KeyError, TypeError) as exc:
            raise ValueError(f'study: incomplete selection evidence: {exc}') from exc
        if not expected or evidence.get('windows') != expected:
            raise ValueError('study: recorded windows do not match earliest fixed selection')
        windows, identities, labels, last_end = [], [], set(), None
        for item in items:
            if not isinstance(item, dict) or set(item) != {'label', 'start', 'end', 'data', 'data_source'}:
                raise ValueError('study: window may specify only label/start/end/data/data_source; no assumption overrides')
            label = item['label']
            if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', label) or label in labels:
                raise ValueError('study: unsafe or duplicate window label')
            labels.add(label)
            try:
                config = Config.from_dict({k: raw[k] for k in common_keys} | {
                    'strategy': MEMBERS[0][1], **{k: item[k] for k in ('start', 'end', 'data', 'data_source')}}, base)
                member_configs(config)  # all doubled fees/slippage must also be valid
            except (ValueError, TypeError) as exc:
                raise ValueError(f'study {label}: {exc}') from exc
            if (config.start != config.start.normalize().replace(day=1)
                    or config.end != config.start + pd.DateOffset(months=6)):
                raise ValueError(f'study {label}: require exactly six complete UTC months')
            if last_end is not None and config.start < last_end:
                raise ValueError(f'study {label}: windows overlap or are out of order')
            last_end = config.end
            if official:
                check_source_link(config.data_source, evidence, config)
            elif (not evidence.get('dataset_identity_sha256') or
                    config.data_source.get('dataset_identity_sha256') != evidence['dataset_identity_sha256'] or
                    config.data_source.get('independent_out_of_sample') is not False):
                raise ValueError(f'study {label}: source identity / seen-data declaration disagrees with selection evidence')
            identities.append({'label': label, 'start': config.start.isoformat(), 'end': config.end.isoformat(), 'months': 6})
            windows.append((label, config))
        if identities != expected:
            raise ValueError('study: configuration must contain the complete preselected window list, not a chosen subset')
        if sha256(proof_path) != proof['sha256']:
            raise ValueError('study: selection evidence changed while reading')
        return cls(tuple(windows), proof_path, proof['sha256'], evidence)

    def as_dict(self):
        common = self.windows[0][1].as_dict()
        for key in ('strategy', 'start', 'end', 'data', 'data_source'):
            del common[key]
        common['selection_evidence'] = {'path': str(self.selection_path), 'sha256': self.selection_sha256}
        common['windows'] = [{'label': label, **{k: config.as_dict()[k] for k in ('start', 'end', 'data', 'data_source')}}
                             for label, config in self.windows]
        return common


def study_markdown(study, rows):
    def number(value, percent=False):
        return 'n/a' if value is None else f'{value * 100 if percent else value:.4f}'
    lines = ['# 多窗口探索性历史验证', '',
             '各窗口是独立实验，均从相同初始权益开始；不是组合/连续净值，不拼接收益或合并年化。',
             '全部为旧已见历史数据；不把窗口当作独立统计样本，不排名、选最优、做显著性或盈利结论。',
             f'固定选择：最早非重叠6完整月，最多4窗口；实际{len(study.windows)}个。',
             '窗口内部复用连续账户与月/年分期。全部12组结果保留，成本场景完整重跑。',
             '相对现金/永续收益差单位为百分点（100×收益率之差），永续基准不是现货。', '',
             '| 窗口 / UTC区间 | 场景 | 成员 | 收益% | 回撤% | Sharpe | 交易 | fees | slippage | Funding净额 | Δ现金(百分点) | Δ永续(百分点) |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        values = [number(r[k], k in {'total_return', 'maximum_drawdown'})
                  for k in ('total_return', 'maximum_drawdown', 'sharpe', 'trade_count', 'fees', 'slippage_cost',
                            'funding_net', 'return_minus_cash_pp', 'return_minus_perpetual_pp')]
        lines.append(f"| [{r['window']}]({r['comparison_path']}/report.md) {r['start'][:10]}～{r['end'][:10]} | "
                     f"{r['scenario']} | {r['member']} | " + ' | '.join(values) + ' |')
    if len(study.windows) < 4:
        lines += ['', f"不足4窗原因：{study.selection.get('stop_reason', 'audited coverage exhausted')}。不缩短或凑数。"]
    if len(study.windows) < 2:
        lines += ['', '**不足2个窗口：无法完成多窗口真实验证。**']
    lines += ['', '[study.json](study.json) 含完整配置/选择证据/数据和报告哈希；各窗口原始comparison可独立复核。',
              *[f'- {text}' for text in LIMITATIONS], '']
    return '\n'.join(lines)


def run_study(study):
    identity = code_identity()
    base = study.windows[0][1].output_dir
    base.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.qfs-study-', dir=base))
    rows, records = [], []
    try:
        for label, config in study.windows:
            try:
                data = load_data(config)
                # Bind the actual loaded snapshot, not just the files seen when
                # StudyConfig was parsed (earlier windows may take a long time).
                if 'source_identity' in study.selection:
                    for key, info in data.files.items():
                        if info['sha256'] != config.data_source['normalized_files'][key]['sha256']:
                            raise ValueError(f'study: official normalized hash mismatch {config.data[key]}')
                relative = f'windows/{label}'
                comparison = write_comparison(config, data, staging / relative)
                if comparison['code'] != identity:
                    raise ValueError('code identity changed during study')
                by_id = {(m['scenario'], m['member']): m['summary'] for m in comparison['members']}
                for member in comparison['members']:
                    scene, summary = member['scenario'], member['summary']
                    cash = by_id[(scene, 'usdt_cash')]['total_return']
                    perpetual = by_id[(scene, 'btcusdt_perpetual_long_hold')]['total_return']
                    rows.append({'window': label, 'start': config.start.isoformat(), 'end': config.end.isoformat(),
                                 'scenario': scene, 'member': member['member'],
                                 'taker_fee_rate': member['config']['taker_fee_rate'], 'slippage_rate': member['config']['slippage_rate'],
                                 **{k: summary[k] for k in METRICS},
                                 'return_minus_cash_pp': 100 * (summary['total_return'] - cash),
                                 'return_minus_perpetual_pp': 100 * (summary['total_return'] - perpetual),
                                 'comparison_path': relative})
                records.append({'label': label, 'start': config.start.isoformat(), 'end': config.end.isoformat(),
                                'comparison_path': relative, 'data_files': data.files,
                                'artifact_sha256': {str(p.relative_to(staging / relative)): sha256(p)
                                                    for p in sorted((staging / relative).rglob('*')) if p.is_file()}})
                del data
            except Exception as exc:
                raise ValueError(f'study {label}: {type(exc).__name__}: {exc}') from exc
        if sha256(study.selection_path) != study.selection_sha256:
            raise ValueError('study: selection evidence changed during execution')
        for record, (_, config) in zip(records, study.windows):
            for key, path in config.data.items():
                if sha256(path) != record['data_files'][key]['sha256']:
                    raise ValueError(f"study {record['label']}: input changed during execution: {path}")
        if code_identity() != identity:
            raise ValueError('study: code identity changed during execution')
        pd.DataFrame(rows).to_csv(staging / 'study.csv', index=False, float_format='%.17g', lineterminator='\n')
        (staging / 'report.md').write_text(study_markdown(study, rows), encoding='utf-8', newline='\n')
        payload = {'study_version': STUDY_VERSION, 'status': 'completed', 'config': study.as_dict(),
                   'selection_evidence': study.selection, 'code': identity, 'runtime': comparison['runtime'],
                   'windows': records, 'rows': rows, 'window_count': len(records),
                   'multiwindow_validation_available': len(records) >= 2, 'policy': STUDY_POLICY,
                   'return_difference_unit': 'percentage points = 100 * (member return - same-window same-scenario benchmark return)',
                   'account_boundary': 'independent initial equity for each window; no cross-window compounding/annualization or pooled account',
                   'description': '多窗口探索性历史验证；已见数据，非独立OOS或独立统计样本', 'limitations': LIMITATIONS,
                   'artifact_sha256': {str(p.relative_to(staging)): sha256(p)
                                       for p in sorted(staging.rglob('*')) if p.is_file()}}
        write_json(staging / 'study.json', payload)
        output = staging.with_name('study-' + staging.name.removeprefix('.qfs-study-'))
        staging.rename(output)
        return output
    except BaseException:
        shutil.rmtree(staging)
        raise
