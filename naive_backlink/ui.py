# naive_backlink/ui.py
# Presentation-only utilities for CLI output.
from __future__ import annotations

from typing import IO, Iterable

from naive_backlink.models import Result


def _writeln(text: str = "", *, file: IO[str]) -> None:
    file.write(text + "\n")


def render_verify_header(url: str, *, file: IO[str]) -> None:
    _writeln(f"Verifying backlinks for: {url}...", file=file)


def render_score_line(result: Result, *, file: IO[str]) -> None:
    _writeln(f"\nScore: {result.score} ({result.label})", file=file)


def render_evidence_section(result: Result, *, file: IO[str]) -> None:
    if not result.evidence:
        return
    _writeln("\n--- Evidence Found ---", file=file)
    for ev in result.evidence:
        cls = (ev.classification or "").upper()
        _writeln(f"- [{cls:<8}] on: {ev.target.url}", file=file)


def render_link_graph_section(
    origin: str | None,
    direct: Iterable[str],
    edges: dict[str, list[str]],
    *,
    file: IO[str],
) -> None:
    if not origin:
        return
    _writeln("\n--- Link Graph ---", file=file)
    _writeln(f"{origin}", file=file)
    for b in sorted(set(direct)):
        _writeln(f"├─ {b}  [direct]", file=file)
        for c in sorted(edges.get(b, [])):
            _writeln(f"│  └─ {c}  [indirect via {b}]", file=file)


def render_errors_section(errors: Iterable[str], *, file: IO[str]) -> None:
    errs = list(errors)
    if not errs:
        return
    _writeln("\n--- Errors Encountered ---", file=file)
    for e in errs:
        _writeln(f"- {e}", file=file)
