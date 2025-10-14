# Defines the command-line interface using argparse.

from __future__ import annotations

import argparse
import asyncio  # Import the asyncio library
import json
import logging
import sys
from typing import Sequence

from naive_backlink import __version__
from naive_backlink.api import crawl_and_score
from naive_backlink.models import Result


async def async_main(argv: Sequence[str] | None = None) -> int:
    """Async entry point for the command-line interface."""
    parser = argparse.ArgumentParser(
        description="A naive backlink checker for non-cryptographic identity linking.",
        prog="naive_backlink",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    # Add a verbose flag to control logging output.
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging output to stderr.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- `verify` command ---
    verify_parser = subparsers.add_parser(
        "verify", help="Crawl a URL and print a summary of the backlink score."
    )
    verify_parser.add_argument("url", help="The origin URL to start crawling from.")
    verify_parser.add_argument(
        "--links-file",
        metavar="FILEPATH",
        help="A file containing a list of candidate URLs to check, one per line."
    )

    # --- `crawl` command ---
    crawl_parser = subparsers.add_parser(
        "crawl", help="Crawl a URL and output the full evidence as JSON."
    )
    crawl_parser.add_argument("url", help="The origin URL to start crawling from.")
    crawl_parser.add_argument(
        "--links-file",
        metavar="FILEPATH",
        help="A file containing a list of candidate URLs to check, one per line."
    )
    crawl_parser.add_argument(
        "--json",
        dest="json_output",
        metavar="FILEPATH",
        help="Path to write the JSON output file.",
        required=True,
    )

    args = parser.parse_args(argv)

    # Configure logging based on the verbose flag.
    # Logs will go to stderr.
    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    # Read the seed URLs from the file if provided
    seed_urls = []
    if args.links_file:
        try:
            with open(args.links_file, 'r') as f:
                seed_urls = [line.strip() for line in f if line.strip()]
            logging.info(f"Loaded {len(seed_urls)} candidate URLs from {args.links_file}")
        except FileNotFoundError:
            logging.error(f"Error: The file specified could not be found: {args.links_file}")
            return 1

    if args.command == "verify":
        print(f"Verifying backlinks for: {args.url}...")
        # ✅ Use await to call the async function ONCE
        result = await crawl_and_score(origin_url=args.url, seed_urls=seed_urls)

        print(f"\nScore: {result.score} ({result.label})")

        if result.evidence:
            print("\n--- Evidence Found ---")
            for ev in result.evidence:
                print(
                    f"- [{ev.classification.upper():<6}] Backlink found on page: {ev.target.url}"
                )
        if result.errors:
            print("\n--- Errors Encountered ---")
            for error in result.errors:
                print(f"- {error}")

        # Return specific exit codes based on results.
        if not result.evidence and not result.errors:
            return 100  # No backlinks found
        if all(e.classification == "weak" for e in result.evidence):
            return 101  # Only weak backlinks

    elif args.command == "crawl":
        result = await crawl_and_score(args.url, seed_urls=seed_urls)

        # We need a custom JSON encoder to handle dataclasses.
        class DataclassJSONEncoder(json.JSONEncoder):
            def default(self, o):
                if isinstance(o, Result):
                    return o.__dict__
                # This can be expanded for other dataclasses if needed.
                return super().default(o)

        with open(args.json_output, "w") as f:
            json.dump(result, f, cls=DataclassJSONEncoder, indent=2)
        print(f"Full evidence report written to {args.json_output}")

    return 0



def main(argv: Sequence[str] | None = None) -> int:
    """Synchronous wrapper for the CLI entry point."""
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    # This still works for direct execution, but now calls the sync wrapper
    sys.exit(main())

