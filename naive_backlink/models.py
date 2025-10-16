# Defines the data structures used throughout the application, as specified in the PEP.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Type definitions for clarity, matching the PEP specification.
Classification = Literal["strong", "weak", "indirect"]
Kind = Literal[
    "backlink", "mention", "redirect", "profile", "rel-me", "platform-verified"
]
Context = Literal["origin-page", "candidate-page"]
ScoreLabel = Literal["high", "medium", "low"]


@dataclass
class URLContext:
    """Represents a URL within a specific context."""

    url: str
    context: Context


@dataclass
class LinkDetails:
    """Contains details about the HTML link element."""

    html: str
    rel: list[str] = field(default_factory=list)
    nofollow: bool = False


@dataclass
class EvidenceRecord:
    """
    A structured record of a piece of evidence found during the crawl.
    This directly corresponds to the Evidence Model in the PEP.
    """

    id: str
    kind: Kind
    source: URLContext
    target: URLContext
    link: LinkDetails | None = None
    classification: Classification | None = None
    hops: int = 0
    trusted_surface: bool = False
    observed_at: str | None = None  # ISO 8601 format
    notes: str = ""


@dataclass
class Result:
    """The final result of a crawl_and_score operation."""

    origin_url: str
    score: int
    label: ScoreLabel
    evidence: list[EvidenceRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
