"""Prune unused public history and first forecasts without downloading inputs."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from . import forecast_archive, public_history


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--history", type=Path, default=public_history.DEFAULT)
    parser.add_argument("--forecasts", type=Path, default=forecast_archive.DEFAULT)
    args = parser.parse_args(argv)
    archive = forecast_archive.load(args.forecasts)
    with public_history.repository(args.history, update=True) as document:
        removed = public_history.prune(document, args.season)
    count = forecast_archive.prune(archive, args.season)
    if count:
        forecast_archive.save(archive, args.forecasts)
    print(
        f"Retaining {args.season - 2} onward; removed history rows: {removed}; forecasts: {count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
