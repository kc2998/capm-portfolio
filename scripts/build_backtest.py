"""Thin entry point: run the walk forward backtest across a date range and
cache the result.

Calls into src/backtest/engine.py and decides what to run and where output
goes; the module itself holds no argument parsing or top level side
effects, per the src/scripts separation described in the README.

Usage:
    python -m scripts.build_backtest             # load cached result if present, else run
    python -m scripts.build_backtest --refresh    # force a full rerun
    python -m scripts.build_backtest --start 2015-01-01 --end 2020-12-31
"""

import argparse
import logging

import pandas as pd
import yaml

from src.universe.point_in_time import build_universe
from src.loaders.fundamentals import build_fundamentals
from src.loaders.prices import build_prices
from src.loaders.market import build_market
from src.backtest.engine import BACKTEST_PANEL_PATH, BACKTEST_WEIGHTS_PATH, build_backtest
from src.backtest.metrics import information_coefficient

CONFIG_PATH = "configs/factors.yaml"

# 2010-01-01: safely past the 2009 XBRL mandate the fundamentals coverage
# caveat cites. 2026-07-31: the last date data/raw/prices actually reaches.
# Both explicit CLI defaults rather than a dynamic "today", so a run's
# result doesn't silently shift depending on what day it happens to be run.
DEFAULT_START = "2010-01-01"
DEFAULT_END = "2026-07-31"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start", default=DEFAULT_START,
        help="first rebalance date, inclusive (default: %(default)s)",
    )
    parser.add_argument(
        "--end", default=DEFAULT_END,
        help="last rebalance date, inclusive (default: %(default)s)",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="force a full rerun rather than loading a cached backtest result",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="show progress from the underlying fetch and build steps",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    universe_spans, ticker_history = build_universe()
    build_fundamentals()
    build_prices()
    market_prices = build_market()

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    dates = pd.date_range(args.start, args.end, freq=config["rebalance_freq"])
    panel_results, portfolio_weights = build_backtest(
        dates, universe_spans, ticker_history, market_prices, config["weights"],
        force_refresh=args.refresh,
    )

    ic_series = information_coefficient(panel_results).dropna()
    print(f"dates: {len(dates)} ({args.start} to {args.end}, freq={config['rebalance_freq']})")
    print(f"panel results cached -> {BACKTEST_PANEL_PATH}")
    print(f"portfolio weights cached -> {BACKTEST_WEIGHTS_PATH}")
    print(f"IC: mean {ic_series.mean():.4f}, std {ic_series.std():.4f}, n {len(ic_series)}")


if __name__ == "__main__":
    main()
