"""Thin entry point: build or refresh the point in time S&P 500 universe.

Calls into src/universe/point_in_time.py and decides what to run and where
output goes; the module itself holds no argument parsing or top level side
effects, per the src/scripts separation described in the README.

Usage:
    python -m scripts.build_universe            # load if present, else build
    python -m scripts.build_universe --refresh   # force a full rebuild
"""

import argparse
import logging

from src.universe.point_in_time import (
    TICKER_HISTORY_PATH,
    UNIVERSE_SPANS_PATH,
    build_universe,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh", action="store_true",
        help="force a full rebuild rather than loading existing parquet files",
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

    universe_spans, ticker_history = build_universe(force_refresh=args.refresh)

    print(f"universe_spans: {universe_spans.shape} -> {UNIVERSE_SPANS_PATH}")
    print(f"ticker_history: {ticker_history.shape} -> {TICKER_HISTORY_PATH}")
    print(f"  verified: {int(ticker_history['verified'].sum())} / {len(ticker_history)}")


if __name__ == "__main__":
    main()
