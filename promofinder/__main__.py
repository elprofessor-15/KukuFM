from __future__ import annotations

import argparse
import json
import sys

from .config import load_config
from .llm import list_models
from .pipeline import run_pipeline
from .preflight import preflight


def main() -> None:
    parser = argparse.ArgumentParser(prog="promofinder")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--data", default=None)
    run.add_argument("--output", default=None)
    run.add_argument("--heuristics-only", action="store_true")
    run.add_argument("--resume", action="store_true")
    commands.add_parser("models")
    args = parser.parse_args()
    config = load_config()
    if args.command == "models":
        for item in list_models(config):
            marker = "chat" if item["chat"] else "not a chat model"
            print(f'{item["id"]}: {marker}')
        return
    directory = args.data or config["DATA_DIR"]
    result = preflight(directory)
    print(json.dumps({key: value for key, value in result.items() if key != "files_parsed"},
                     ensure_ascii=False, indent=2))
    if not result["files_parsed"]:
        sys.exit("Preflight found no valid episodes.")
    outcome = run_pipeline(directory, args.output, args.heuristics_only, args.resume)
    print(json.dumps(outcome["report"], indent=2))


if __name__ == "__main__":
    main()
