"""Financial audit assertions must never silently disappear in optimized Python."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_verify_comparison import profitable_short_comparison, replace_reported_annualized


TOOLS = Path(__file__).resolve().parents[1] / 'tools'


def optimized(mode, args, **kwargs):
    env = os.environ.copy()
    env.pop('PYTHONOPTIMIZE', None)
    flags = [] if mode == 'env' else [mode]
    if mode == 'env':
        env['PYTHONOPTIMIZE'] = '1'
    return subprocess.run([sys.executable, *flags, *args], env=env, text=True, capture_output=True, **kwargs)


@pytest.mark.parametrize('mode', ['-O', '-OO', 'env'])
def test_optimized_verifier_cannot_accept_false_financial_metric(dataset, tmp_path, mode):
    output = profitable_short_comparison(dataset, tmp_path, 100)
    replace_reported_annualized(output, 123.0)  # actual return is exactly zero; all copies/SHA refreshed
    before = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob('*') if p.is_file()}
    ordinary = subprocess.run([sys.executable, str(TOOLS / 'verify_comparison.py'), '--run', str(output),
                               '--output', str(tmp_path / 'normal.json')], text=True, capture_output=True)
    assert ordinary.returncode != 0 and '(123.0, 0.0)' in ordinary.stderr
    audit = tmp_path / 'unsafe.json'
    proc = optimized(mode, [str(TOOLS / 'verify_comparison.py'), '--run', str(output), '--output', str(audit)])
    assert proc.returncode != 0, proc.stdout
    assert 'optimized Python' in proc.stderr
    assert not audit.exists()
    assert before == {str(p.relative_to(output)): p.read_bytes() for p in output.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mode', ['-O', '-OO', 'env'])
@pytest.mark.parametrize('module,call', [
    ('ledger', 'close(1, 2)'),
    ('ledger', 'reconcile(None, None)'),
    ('verify_comparison', 'verify(None)'),
    ('verify_study', 'verify(None)'),
    ('verify_study', 'official_identity(None)'),
    ('verify_study', 'verify_official_link(None, None)'),
    ('verify_study', 'selected_from_months(None)'),
])
def test_direct_audit_api_rejects_optimization_before_reading_inputs(tmp_path, mode, module, call):
    audit = tmp_path / 'unsafe.json'
    script = (f'import sys; from pathlib import Path; sys.path.insert(0, {str(TOOLS)!r}); '
              f'import {module}; {module}.{call}; Path({str(audit)!r}).write_text("success")')
    proc = optimized(mode, ['-c', script], cwd=tmp_path)
    assert proc.returncode != 0
    assert 'optimized Python' in proc.stderr
    assert not audit.exists()


@pytest.mark.parametrize('mode', ['-O', '-OO', 'env'])
@pytest.mark.parametrize('script,flag', [('verify_comparison.py', '--config'), ('verify_study.py', '--config'),
                                       ('verify_real.py', '--config-prefix')])
def test_cli_refuses_optimization_before_any_replay_or_output(tmp_path, mode, script, flag):
    protected = tmp_path / 'existing.json'
    protected.write_text('existing evidence')
    audit = tmp_path / 'unsafe.json'
    proc = optimized(mode, [str(TOOLS / script), flag, str(tmp_path / 'missing'), '--output', str(audit)], cwd=tmp_path)
    assert proc.returncode != 0
    assert 'optimized Python' in proc.stderr
    assert not audit.exists() and protected.read_text() == 'existing evidence'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['existing.json']
