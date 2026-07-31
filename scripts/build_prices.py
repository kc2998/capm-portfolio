"""Thin entry point: fetch or refresh cached prices for the whole universe.

Calls into src/loaders/prices.py and decides what to run and where output
goes; the module itself holds no argument parsing or top level side
effects, per the src/scripts separation described in the README.

Usage:
    python -m scripts.build_prices            # load if present, else build
    python -m scripts.build_prices --refresh   # force a full rebuild
"""

import argparse
import logging

from src.loaders.prices import PRICES_COVERAGE_PATH, PRICES_RAW_DIR, build_prices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh", action="store_true",
        help="force a full rebuild rather than loading the existing coverage report",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="show progress from the underlying fetch",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    coverage = build_prices(force_refresh=args.refresh)

    print(f"prices cached under: {PRICES_RAW_DIR}")
    print(f"coverage report: {coverage.shape} -> {PRICES_COVERAGE_PATH}")
    print(f"  non-empty: {int((coverage['rows'] > 0).sum())} / {len(coverage)}")


if __name__ == "__main__":
    main()
