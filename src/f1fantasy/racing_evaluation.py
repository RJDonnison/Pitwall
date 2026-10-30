"""Offline nested walk-forward racing evaluation; no prices or network required."""

import argparse
import json
from pathlib import Path

from . import public_history, racing_model


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=public_history.DEFAULT)
    parser.add_argument(
        "--output", type=Path, default=Path("data/racing-evaluation.json")
    )
    parser.add_argument("--simulations", type=int, default=600)
    args = parser.parse_args(argv)
    if args.simulations < 100:
        parser.error("At least 100 simulations are required for evaluation")
    with public_history.repository(args.history) as document:
        report = racing_model.evaluate(document["racing"], simulations=args.simulations)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in {"folds", "winner_reliability"}
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
