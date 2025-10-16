# Defines the command-line interface using argparse.

from __future__ import annotations

import argparse
import asyncio  # Import the asyncio library
import json
import logging
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Sequence, Set

from naive_backlink import __version__
from naive_backlink.api import crawl_and_score
from naive_backlink.models import Result
from naive_backlink.ui import (
    render_errors_section,
    render_evidence_section,
    render_link_graph_section,
    render_score_line,
    render_verify_header,
)

log = logging.getLogger(__name__)


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _load_seed_urls(path: str | None) -> list[str]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        log.error(f"Error: The file specified could not be found: {path}")
        raise FileNotFoundError(path)
    with p.open("r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    log.info(f"Loaded {len(lines)} candidate URLs from {path}")
    return lines


def _json_default(o: Any) -> Any:
    # Minimal, safe encoder for dataclasses and datetimes.
    if isinstance(o, datetime):
        return o.isoformat()
    if is_dataclass(o):
        return asdict(o)  # type: ignore[arg-type]
    return str(o)


def _build_link_graph_inputs(
    result: Result,
) -> tuple[str | None, Set[str], dict[str, list[str]]]:
    origin = None
    if result.evidence:
        # all evidence shares same origin URL in this model
        origin = result.evidence[0].source.url

    direct: Set[str] = set()
    edges: dict[str, list[str]] = {}

    for ev in result.evidence:
        cls = (ev.classification or "").lower()
        if cls in ("strong", "weak"):
            direct.add(ev.target.url)
        elif cls == "indirect" and ev.notes:
            # expected note format includes "pivot=<B> chain=A<->B<->C"
            pivot = None
            try:
                parts = ev.notes.split("pivot=")[1]
                pivot_part, _ = parts.split(" chain=", 1)
                pivot = pivot_part.strip()
            except Exception:
                # keep silent but do not crash CLI; leave pivot as None
                pivot = None
            if pivot:
                edges.setdefault(pivot, []).append(ev.target.url)

    return origin, direct, edges


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments common to both 'verify' and 'crawl' commands."""
    parser.add_argument("url", help="The origin URL to start crawling from.")
    parser.add_argument(
        "--links-file",
        metavar="FILEPATH",
        help="A file containing a list of candidate URLs to check, one per line.",
    )

    # Add new policy flags
    policy_group = parser.add_argument_group("policy arguments")
    policy_group.add_argument(
        "--only-well-known-id-sites",
        action="store_true",
        help="Only crawl URLs matching the built-in 'whitelist'. (Default: use blacklist)",
    )
    policy_group.add_argument(
        "--only-rel-me",
        action="store_true",
        help='Only respect links explicitly marked with rel="me" as evidence.',
    )


async def async_main(
    argv: Sequence[str] | None = None, stdout: IO[str] | None = None
) -> int:
    """Async entry point for the command-line interface."""
    stdout = stdout or sys.stdout

    parser = argparse.ArgumentParser(
        description="A naive backlink checker for non-cryptographic identity linking.",
        prog="naive_backlink",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging output to stderr.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- verify ---
    verify_parser = subparsers.add_parser(
        "verify", help="Crawl a URL and print a summary of the backlink score."
    )
    _add_common_args(verify_parser)

    # --- crawl ---
    crawl_parser = subparsers.add_parser(
        "crawl", help="Crawl a URL and output the full evidence as JSON."
    )
    _add_common_args(crawl_parser)
    crawl_parser.add_argument(
        "--json",
        dest="json_output",
        metavar="FILEPATH",
        help="Path to write the JSON output file.",
        required=True,
    )

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    try:
        seed_urls = _load_seed_urls(args.links_file)
    except FileNotFoundError:
        return 1

    # Collect API arguments
    api_kwargs = {
        "origin_url": args.url,
        "seed_urls": seed_urls,
        "only_whitelist": args.only_well_known_id_sites,
        "only_rel_me": args.only_rel_me,
    }

    if args.command == "verify":
        render_verify_header(args.url, file=stdout)
        result = await crawl_and_score(**api_kwargs)  # type: ignore

        render_score_line(result, file=stdout)
        render_evidence_section(result, file=stdout)

        origin, direct, edges = _build_link_graph_inputs(result)
        render_link_graph_section(origin, direct, edges, file=stdout)

        if result.errors:
            render_errors_section(result.errors, file=stdout)

        # Return specific exit codes based on results.
        if not result.evidence and not result.errors:
            return 100  # No backlinks found
        if result.evidence and all(
            (e.classification or "").lower() == "weak" for e in result.evidence
        ):
            return 0  # Only weak backlinks (non-failure for CI usage)

        return 0

    # args.command == "crawl"
    result = await crawl_and_score(**api_kwargs)  # type: ignore
    out_path = Path(args.json_output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, default=_json_default, indent=2)
    print(f"Full evidence report written to {args.json_output}", file=stdout)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Synchronous wrapper for the CLI entry point."""
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    # This still works for direct execution, but now calls the sync wrapper
    sys.exit(main())
