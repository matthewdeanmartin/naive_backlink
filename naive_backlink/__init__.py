# Entrypoint for the naive_backlink package.
# This file makes the public API available to programmers.

from __future__ import annotations

from naive_backlink.api import crawl_and_score
from naive_backlink.models import EvidenceRecord, Result

# The __all__ variable defines the public API of the package.
# When a user writes `from naive_backlink import *`, only these names will be imported.
__all__ = [
    "crawl_and_score",
    "EvidenceRecord",
    "Result",
]
__version__ = "0.1.0"