"""Offline CLI; all validation and computation finish before any report is published."""
import argparse
import sys

from .compare import load_compare_config, run_comparison
from .config import Config
from .data import load_data
from .engine import run_backtest
from .report import write_reports


def main(argv=None):
    parser = argparse.ArgumentParser(prog="qfs")
    sub = parser.add_subparsers(dest="command", required=True)
    backtest = sub.add_parser("backtest", help="Run a local Parquet historical backtest")
    backtest.add_argument("--config", required=True)
    compare = sub.add_parser("compare", help="Compare four fixed members and three cost scenarios offline")
    compare.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            output = run_comparison(load_compare_config(args.config))
            print(output)
            return 0
        config = Config.load(args.config)
        data = load_data(config)
        result = run_backtest(config, data)
        output = write_reports(config, data, result)
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        print(f"qfs: {exc}", file=sys.stderr)
        return 1
    if result.invalid_time:
        print(f"qfs: backtest invalid at {result.invalid_time}: {result.invalid_reason}; complete invalid report: {output}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
