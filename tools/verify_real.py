"""Local acceptance check of real CLI outputs; no performance/inference claim."""
import argparse
import json
from pathlib import Path
import subprocess

from qfs.config import Config
from qfs.data import sha256
from ledger import reconcile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config-prefix', default='.local/real', help='Read <prefix>-ema.json and <prefix>-bollinger.json')
parser.add_argument('--output', default='.local/verification.json')
parser.add_argument('--baseline', help='Prior verification JSON; assert fixed-input financial results/CSV bytes unchanged')
args = parser.parse_args()
baseline = json.loads(Path(args.baseline).read_text()) if args.baseline else None
results = {}
for name in ('ema', 'bollinger'):
    path = Path(f'{args.config_prefix}-{name}.json')
    config = Config.load(path)
    runs = []
    for _ in range(2):
        command = ['.venv/bin/qfs', 'backtest', '--config', str(path)]
        proc = subprocess.run(command, text=True, capture_output=True)
        assert proc.returncode == 0, proc.stderr
        output = Path(proc.stdout.strip())
        runs.append(output)
        print(' '.join(command), '=>', output)
    for file in runs[0].iterdir():
        assert file.read_bytes() == (runs[1] / file.name).read_bytes(), file.name
    output = runs[0]
    summary, manifest, trades, curve = reconcile(config, output)
    assert manifest['data_source']['independent_out_of_sample'] is False
    if baseline:
        previous = Path(baseline[name]['outputs'][0])
        for file in ('trades.csv', 'equity.csv'):
            assert (output / file).read_bytes() == (previous / file).read_bytes(), f'{name}: baseline {file} changed'
        prior_summary = json.loads((previous / 'summary.json').read_text())
        for key in prior_summary.keys() - {'contract_version', 'limitations', 'metric_definitions', 'funding_validation'}:
            assert prior_summary[key] == summary[key], f'{name}: baseline {key} changed'
        print(name, 'baseline financial results and both CSV files unchanged')
    results[name] = {'outputs': [str(p) for p in runs], 'code': manifest['code'],
                     'trade_count': len(trades), 'equity_rows': len(curve),
                     'byte_determinism': '4/4 files identical', 'ledger_reconciliation': 'all trades and every equity row passed',
                     'artifact_sha256': {p.name: sha256(p) for p in output.iterdir()}}
    print(name, 'PASS:', len(trades), 'trades /', len(curve), 'equity rows; deterministic and independently reconciled')
Path(args.output).write_text(json.dumps(results, sort_keys=True, indent=2) + '\n', encoding='utf-8')
