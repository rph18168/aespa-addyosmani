"""Command-line entry point for one digest run."""

from __future__ import annotations

import argparse
import logging
import os

from .config import ConfigurationError, load_config
from .logging_utils import configure_logging, log_event
from .runner import RunError, run_once


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send the aespa daily news digest")
    parser.add_argument(
        "--sources",
        default=os.environ.get("SOURCES_PATH", "config/sources.json"),
        help="path to the RSS/Atom source configuration",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build and print the digest without sending email or writing state",
    )
    args = parser.parse_args(argv)
    logger = configure_logging()
    try:
        config = load_config(args.sources)
    except ConfigurationError as exc:
        log_event(logger, "configuration_failed", level=logging.ERROR, error_type=type(exc).__name__)
        return 2

    try:
        result = run_once(config, dry_run=args.dry_run, logger=logger)
    except RunError as exc:
        log_event(logger, "run_failed", level=logging.ERROR, error_type=type(exc).__name__)
        return 1
    if args.dry_run:
        print(result.digest.text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
