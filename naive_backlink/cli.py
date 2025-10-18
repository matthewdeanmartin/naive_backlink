# naive_backlink/cli.py
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
from naive_backlink.cache import FileCache, CacheConfig

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


def _human_bytes(n: int) -> str:
    # Compact human-readable bytes
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    v = float(n)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    # max 2 decimals, strip trailing zeros
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{s} {units[i]}"


def _init_file_cache(cache_dir: str | None, os_default: bool) -> FileCache:
    cfg = CacheConfig()
    if os_default:
        cfg.directory = "os-default"
    if cache_dir:
        cfg.directory = cache_dir
    return FileCache(cfg)


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

    # --- cache (new command group) ---
    cache_parser = subparsers.add_parser(
        "cache", help="Manage the on-disk HTTP cache."
    )
    cache_parser.add_argument(
        "--dir",
        dest="cache_dir",
        metavar="PATH",
        default=None,
        help="Cache directory to operate on (defaults to library default).",
    )
    cache_parser.add_argument(
        "--os-default",
        dest="cache_os_default",
        action="store_true",
        help="Use the OS-specific default cache directory.",
    )
    cache_sub = cache_parser.add_subparsers(dest="cache_cmd", required=True)

    cache_clear = cache_sub.add_parser("clear", help="Wipe the entire cache directory.")
    # no extra args

    cache_stats = cache_sub.add_parser(
        "stats", help="Show total items and size on disk."
    )
    # no extra args

    cache_inspect = cache_sub.add_parser(
        "inspect", help="Dump the cached record for a specific URL."
    )
    cache_inspect.add_argument("url", help="The exact URL key to inspect in cache.")

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    # ---- cache command handling (synchronous paths) -------------------------
    if args.command == "cache":
        fc = _init_file_cache(args.cache_dir, args.cache_os_default)

        if args.cache_cmd == "clear":
            fc.clear_all()
            d = fc.directory or "(disabled)"
            print(f"Cache cleared at: {d}", file=stdout)
            return 0

        if args.cache_cmd == "stats":
            st = fc.stats()
            items = int(st.get("items", 0))
            bytes_on_disk = int(st.get("bytes", 0))
            directory = st.get("directory", "")
            out = {
                "directory": directory,
                "items": items,
                "bytes": bytes_on_disk,
                "human_bytes": _human_bytes(bytes_on_disk),
            }
            print(json.dumps(out, indent=2), file=stdout)
            return 0

        if args.cache_cmd == "inspect":
            data = fc.get(args.url)
            if data is None:
                print("Cache miss", file=stdout)
                return 2
            print(json.dumps(data, indent=2, default=_json_default), file=stdout)
            return 0

        # Should not reach
        print("Unknown cache subcommand", file=stdout)
        return 2

    # ---- normal crawl/verify flows ------------------------------------------
    try:
        seed_urls = _load_seed_urls(getattr(args, "links_file", None))
    except FileNotFoundError:
        return 1

    # Collect API arguments
    api_kwargs = {
        "origin_url": getattr(args, "url", None),
        "seed_urls": seed_urls,
        "only_whitelist": getattr(args, "only_well_known_id_sites", False),
        "only_rel_me": getattr(args, "only_rel_me", False),
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
