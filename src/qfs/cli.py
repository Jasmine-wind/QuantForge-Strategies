"""Offline CLI; all validation and computation finish before any report is published."""
import argparse
import sys
from pathlib import Path
import zipfile

from .compare import load_compare_config, run_comparison
from .browse import export_html
from .config import Config
from .data import load_data
from .engine import run_backtest
from .report import write_reports
from .prepare import prepare
from .study import StudyConfig, run_study


def main(argv=None):
    parser = argparse.ArgumentParser(prog="qfs")
    sub = parser.add_subparsers(dest="command", required=True)
    backtest = sub.add_parser("backtest", help="Run a local Parquet historical backtest")
    backtest.add_argument("--config", required=True)
    compare = sub.add_parser("compare", help="Compare four fixed members and three cost scenarios offline")
    compare.add_argument("--config", required=True)
    study = sub.add_parser("study", help="Run fixed nonoverlapping six-month exploratory windows offline")
    study.add_argument("--config", required=True)
    preparation = sub.add_parser('prepare', help='Prepare checked official monthly archives offline')
    for name in ('manifest', 'start', 'end', 'output'):
        preparation.add_argument('--' + name, required=True)
    browser = sub.add_parser('browse', help='Export standalone offline HTML from existing reports')
    browser.add_argument('--run', required=True)
    browser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'browse':
            print(export_html(args.run, args.output))
            return 0
        if args.command == 'prepare':
            prepare(args.manifest, args.output, args.start, args.end)
            print(Path(args.output).resolve())
            return 0
        if args.command == "study":
            output = run_study(StudyConfig.load(args.config))
            print(output)
            return 0
        if args.command == "compare":
            output = run_comparison(load_compare_config(args.config))
            print(output)
            return 0
        config = Config.load(args.config)
        data = load_data(config)
        result = run_backtest(config, data)
        output = write_reports(config, data, result)
    except (ValueError, TypeError, KeyError, OSError, OverflowError, zipfile.BadZipFile) as exc:
        print(f"qfs: {exc}", file=sys.stderr)
        return 1
    if result.invalid_time:
        print(f"qfs: backtest invalid at {result.invalid_time}: {result.invalid_reason}; complete invalid report: {output}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
