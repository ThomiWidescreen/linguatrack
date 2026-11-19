import argparse
import json
import logging
import time
from pathlib import Path

from linguatrack.jobs import dispatch_once
from linguatrack.reference import import_build


def main():
    parser = argparse.ArgumentParser(description="LinguaTrack local backend tools")
    sub = parser.add_subparsers(dest="command", required=True)
    dispatch = sub.add_parser("dispatch", help="Dispatch durable jobs and recover stale leases")
    dispatch.add_argument("--once", action="store_true")
    importer = sub.add_parser("import-reference", help="Import a reviewed lexicon build")
    importer.add_argument("directory", type=Path)
    importer.add_argument("--allow-nc", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.command == "import-reference":
        print(json.dumps(import_build(args.directory, args.allow_nc)))
        return
    while True:
        try:
            dispatch_once()
        except Exception as error:
            # Do not log connection strings, broker URLs or private payloads.
            logging.warning("dispatch_failed type=%s", type(error).__name__)
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            return
        time.sleep(1)


if __name__ == "__main__":
    main()
