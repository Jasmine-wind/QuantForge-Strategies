import json
from pathlib import Path

import pandas as pd
import pytest

from qfs.browse import load_view
from qfs.cli import main
from qfs.compare import run_comparison
from qfs.data import sha256
from qfs.diagnose import diagnose, load_diagnostics, trade_diagnostics


def trade_case(net=(10., -3., -2., 0., 20., -4.)):
    frame = pd.DataFrame({'direction': ['long', 'short'] * 3, 'entry_time': ['2024-03-01T00:00Z'] * 6,
                          'exit_time': pd.date_range('2024-03-02', periods=6, tz='UTC').map(str),
                          'exit_reason': ['signal'] * 5 + ['end_of_test'], 'net_pnl': net,
                          'gross_pnl': [n + 2 - .5 for n in net], 'fees': 2., 'funding': .5, 'slippage': 3.,
                          'entry_fee': 1., 'exit_fee': 1., 'entry_slippage': 1., 'exit_slippage': 2.})
    summary = dict(trade_count=6, gross_pnl=sum(net) + 9, net_pnl=sum(net), fees=12., funding_net=3., slippage_cost=18.,
                   win_rate=sum(n > 0 for n in net)/6,
                   average_win_loss_ratio=None, profit_factor=None)
    wins, losses = [n for n in net if n > 0], [n for n in net if n < 0]
    summary['profit_factor'] = sum(wins)/abs(sum(losses)) if losses else None
    summary['average_win_loss_ratio'] = (sum(wins)/len(wins))/(abs(sum(losses))/len(losses)) if wins and losses else None
    return frame, summary


def test_direction_totals_loss_sequence_concentration_and_terminal_close():
    frame, summary = trade_case()
    d = trade_diagnostics(frame, summary)
    assert d['directions']['long']['net_pnl'] == 28
    assert d['directions']['short']['net_pnl'] == -7
    assert d['overall']['max_consecutive_losses'] == 2  # zero breaks streak
    assert d['directions']['long']['trade_count'] == d['directions']['short']['trade_count'] == 3
    assert d['overall']['average_win'] == 15 and d['overall']['average_loss'] == -3
    assert d['overall']['profit_factor'] == pytest.approx(30/9)
    assert [t['completion_number'] for t in d['top_profitable_trades']] == [5, 1]
    assert d['top5_positive_profit_share'] == 1
    assert d['top5_total_net_share'] == pytest.approx(30/21)
    assert d['terminal_trades'][0]['completion_number'] == 6
    assert d['terminal_trades'][0]['terminal_close']
    # All attribution is interval-wide, with no exit-month buckets.
    assert 'months' not in d


@pytest.mark.parametrize('net', [(-1.,)*6, (1.,)*6, (0.,)*6, (1.,1.,1.,1.,1.,1.)])
def test_n_a_and_fixed_top_five(net):
    frame, summary = trade_case(net)
    d = trade_diagnostics(frame, summary)
    assert d['overall']['average_win_loss_ratio'] is None
    if net[0] > 0:
        assert d['overall']['profit_factor'] is None
        assert [t['completion_number'] for t in d['top_profitable_trades']] == [1,2,3,4,5]
        assert d['top5_positive_profit_share'] == pytest.approx(5/6)
    else:
        assert d['top5_total_net_share'] is None and not d['top_profitable_trades']
        assert d['overall']['profit_factor'] == (0 if net[0] < 0 else None)


@pytest.mark.parametrize('damage', ['direction', 'fees', 'funding', 'net', 'slippage', 'count', 'order', 'nan'])
def test_grouping_refuses_mismatch(damage):
    trades, summary = trade_case()
    if damage == 'direction':
        trades.loc[0, 'direction'] = 'flat'
    elif damage == 'order':
        trades = trades.iloc[::-1]
    elif damage == 'count':
        summary['trade_count'] = 5
    elif damage == 'nan':
        trades.loc[0, 'net_pnl'] = float('nan')
    else:
        key = {'net': 'net_pnl', 'funding': 'funding_net', 'slippage': 'slippage_cost'}.get(damage, damage)
        summary[key] += 1
    with pytest.raises(ValueError, match='diagnose'):
        trade_diagnostics(trades, summary)


def test_diagnose_cli_all_groups_cost_results_and_repeatability(dataset, tmp_path):
    config, _, _ = dataset(minutes=480, fee=.0005, slip=.0005)
    run = run_comparison(config)
    before = {str(p.relative_to(run)): sha256(p) for p in run.rglob('*') if p.is_file()}
    first, repeat = tmp_path / 'diagnostic', tmp_path / 'repeat'
    assert main(['diagnose', '--run', str(run), '--output', str(first)]) == 0
    diagnose(run, repeat)
    assert {p.name: sha256(p) for p in first.iterdir()} == {p.name: sha256(p) for p in repeat.iterdir()}
    payload = load_diagnostics(first, load_view(run))
    markdown = (first / 'report.md').read_text()
    assert '终点强制平仓' in markdown and '终点强平' not in markdown
    records = payload['records']
    assert len(records) == 12
    assert len(pd.read_csv(first / 'diagnostics.csv')) == 12
    for r in records:
        b = next(b for b in records if b['scenario'] == 'base' and b['member'] == r['member'])
        assert r['cost_change_from_base']['return_pp'] == 100*(r['summary']['total_return'] - b['summary']['total_return'])
        assert r['overall']['trade_count'] == r['summary']['trade_count']
    assert before == {str(p.relative_to(run)): sha256(p) for p in run.rglob('*') if p.is_file()}
    assert main(['diagnose', '--run', str(run), '--output', str(first)]) == 1
    with pytest.raises(ValueError):
        diagnose(run, run / 'diagnostic')


@pytest.mark.parametrize('damage', ['source', 'hash_missing', 'record_missing', 'direction', 'csv', 'file_missing'])
def test_diagnostic_binding_and_inventory_rejection(dataset, tmp_path, damage):
    config, _, _ = dataset()
    run = run_comparison(config)
    output = diagnose(run, tmp_path / 'diagnostic')
    file = output / 'diagnostics.json'
    d = json.loads(file.read_text())
    if damage == 'source':
        d['source_sha256']['comparison.json'] = '0'*64
    elif damage == 'hash_missing':
        del d['artifact_sha256']['diagnostics.csv']
    elif damage == 'record_missing':
        d['records'].pop()
    elif damage == 'direction':
        d['records'][0]['directions']['long']['fees'] += 1
    elif damage == 'csv':
        (output / 'diagnostics.csv').write_text('tampered')
        d['artifact_sha256']['diagnostics.csv'] = sha256(output / 'diagnostics.csv')
    else:
        (output / 'report.md').unlink()
    file.write_text(json.dumps(d))
    with pytest.raises(ValueError):
        load_diagnostics(output, load_view(run))


def test_failure_cleans_private_directory_and_original_inventory_checked(dataset, tmp_path, monkeypatch):
    config, _, _ = dataset()
    run = run_comparison(config)
    def fail(*args, **kwargs):
        raise OSError('fixture disk full')
    monkeypatch.setattr(pd.DataFrame, 'to_csv', fail)
    with pytest.raises(OSError):
        diagnose(run, tmp_path / 'failed')
    assert not (tmp_path / 'failed').exists() and not list(tmp_path.glob('.qfs-diagnose-*'))
    file = run / 'comparison.json'
    d = json.loads(file.read_text())
    del d['members'][0]['artifact_sha256']['equity.csv']
    file.write_text(json.dumps(d))
    with pytest.raises(ValueError, match='hash manifest'):
        diagnose(run, tmp_path / 'failed')
