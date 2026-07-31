"""Thin entry point: fetch or refresh cached fundamentals for the whole universe.

Calls into src/loaders/fundamentals.py and decides what to run and where
output goes; the module itself holds no argument parsing or top level side
effects, per the src/scripts separation described in the README.

Usage:
    python -m scripts.build_fundamentals            # load if present, else build
    python -m scripts.build_fundamentals --refresh   # force a full rebuild
"""

import argparse
import logging

from src.loaders.fundamentals import (
    FUNDAMENTALS_COVERAGE_PATH,
    FUNDAMENTALS_RAW_DIR,
    build_fundamentals,
)


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

    coverage = build_fundamentals(force_refresh=args.refresh)

    print(f"fundamentals cached under: {FUNDAMENTALS_RAW_DIR}")
    print(f"coverage report: {coverage.shape} -> {FUNDAMENTALS_COVERAGE_PATH}")
    print(f"  fetched: {int(coverage['fetched'].sum())} / {len(coverage)}")


if __name__ == "__main__":
    main()
