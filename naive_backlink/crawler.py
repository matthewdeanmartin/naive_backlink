# naive_backlink/crawler.py
from __future__ import annotations

"""
HTTPX-based crawler.

Responsibilities:
- Fetch HTML over HTTP(S) with redirects and timeouts.
- Maintain BFS queue with hop limits and visited set.
- Delegate ALL link parsing, normalization, backlink detection, and
  same-domain filtering to link_logic.py.

Centralized behaviors (in link_logic.py):
- Handling of <a href=...> and <link href=...>
- URL normalization
- Same-domain policies: "follow", "no-self-domain", "no-self-domain-or-subdomain"
- Backlink detection (including rel="me" classification)
- Evidence construction
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Set

import httpx
from bs4 import BeautifulSoup

from naive_backlink.cache import CacheConfig, FileCache
from naive_backlink.link_logic import (
    _rel_list,
    LogicConfig,
    detect_backlink_element,
    extract_href_elements,
    is_blacklisted,
    is_fetchable_url,
    is_probably_html_url,
    make_evidence,
    make_indirect_evidence,
    normalize_url,
    queue_candidates_from_origin,
    queue_candidates_from_pivot,
)
from naive_backlink.models import EvidenceRecord

log = logging.getLogger(__name__)


@dataclass
class Crawler:
    """
    Crawl starting from an origin URL using httpx (no JS execution).

    Config keys consumed:
      - user_agent: str
      - timeout: float (seconds)
      - max_content_bytes: int
      - max_hops: int
      - max_outlinks: int
      - trusted: list[str]
      - same_domain_policy: "follow" | "no-self-domain" | "no-self-domain-or-subdomain"
      - use_registrable_domain: bool
      - only_whitelist: bool
      - only_rel_me: bool
      - whitelist: list[str]
      - blacklist: list[str]
      ...
    """

    origin_url: str
    config: Dict[str, Any]
    seed_urls: List[str] | None = None

    # Internal state
    queue: Deque[tuple[str, int]] = field(default_factory=deque)
    visited_urls: Set[str] = field(default_factory=set)
    evidence_producing_urls: Set[str] = field(default_factory=set)
    evidence: List[EvidenceRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    # second-degree tracking
    parent: Dict[str, str] = field(default_factory=dict)  # neighbor C -> pivot B
    pivot_has_backlink_to_origin: Set[str] = field(
        default_factory=set
    )  # B that link to A
    pivot_outlinked: Dict[str, Set[str]] = field(default_factory=dict)  # B -> {C}

    # HTTP client + derived
    _client: httpx.AsyncClient = field(init=False, repr=False)
    normalized_origin_url: str = field(init=False)
    _cache: FileCache | None = field(default=None, init=False, repr=False)

    async def __aenter__(self) -> "Crawler":
        headers = {
            "User-Agent": self.config.get(
                "user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36",
            )
        }

        cache_cfg_raw = self.config["cache"]
        cc = CacheConfig(
            enabled=bool(cache_cfg_raw["enabled"]),
            directory=str(cache_cfg_raw.get("directory", ".naive_backlink_cache")),
            expire_seconds=int(cache_cfg_raw.get("expire_seconds", 24 * 3600)),
            store_errors=bool(cache_cfg_raw.get("store_errors", False)),
        )
        self._cache = FileCache(cc)

        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=self.config.get("timeout", 10.0),
            headers=headers,
        )

        self.normalized_origin_url = normalize_url(self.origin_url)

        # Initialize BFS queue
        if self.seed_urls:
            # Treat provided seeds as first-hop candidates
            self.visited_urls.add(self.normalized_origin_url)
            for url in self.seed_urls:
                self.queue.append((normalize_url(url), 1))
        else:
            # Start at the origin page
            self.queue.append((self.normalized_origin_url, 0))

        log.info("httpx session initialized. Origin: %s", self.normalized_origin_url)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._client.aclose()
        if self._cache:
            self._cache.close()  # NEW
        log.info("httpx session closed.")

    async def _fetch_and_parse(self, url: str) -> BeautifulSoup | None:
        """
        Fetch a URL and return a BeautifulSoup tree, or None on error/non-HTML/too-large.
        Honors on-disk cache for successful 200 text/html responses.
        """
        if not is_fetchable_url(url):
            log.info("Skipping non-fetchable URL (scheme not http/https): %s", url)
            return None

        if not is_probably_html_url(url):
            log.info("Skip non-HTML by extension: %s", url)
            return None
        if url in self.visited_urls:
            return None
        self.visited_urls.add(url)

        # ---- NEW: cache lookup ----
        if self._cache:
            hit = self._cache.get(url)
            if (
                    hit
                    and hit.get("status") == 200
                    and "text/html" in hit.get("content_type", "")
            ):
                log.info("Cache hit for %s", url)
                text = hit.get("text", "")
                if not text:
                    log.debug("Cached entry missing body; ignoring.")
                else:
                    return BeautifulSoup(text, "html.parser")

        try:
            resp = await self._client.get(url)
            status = resp.status_code

            if status != 200:
                # Still raise_for_status for uniform handling of 4xx/5xx
                log.warning("Non-200 response for %s: %d", url, status)
            resp.raise_for_status()

            ctype = resp.headers.get("content-type", "").lower()
            if "text/html" not in ctype:
                log.info("Skipping non-HTML content at %s (%s)", url, ctype)
                return None

            # It's been downloaded. Might as well look at it.
            # max_bytes = self.config.get("max_content_bytes", 1024 * 1024)
            # if len(resp.content) > max_bytes:
            #     msg = f"Content too large at {url} ({len(resp.content)} > {max_bytes})"
            #     log.warning(msg)
            #     self.errors.append(msg)
            #     return None

            # ---- NEW: cache store (200 + text/html) ----

            if self._cache is not None:
                self._cache.set_html_ok(
                    url,
                    final_url=str(resp.url),
                    status=status,
                    headers=dict(resp.headers),
                    text=resp.text,
                    content_type=ctype,
                )

            return BeautifulSoup(resp.text, "html.parser")

        except httpx.HTTPStatusError as e:
            msg = f"HTTP error for {url}: {e}"
            log.error(msg)
            self.errors.append(msg)
            return None
        except httpx.RequestError as e:
            msg = f"Network error fetching {url}: {e}"
            log.error(msg)
            self.errors.append(msg)
            return None
        except Exception as e:
            msg = f"Error parsing {url}: {e}"
            log.error(msg)
            self.errors.append(msg)
            # Only return None on expected errors. Everything else is a bug.
            raise

    async def crawl(self) -> None:
        """
        BFS crawl honoring hop limits. On origin page, enqueue outbound candidates.
        On candidate pages, detect first backlink to origin and record evidence.
        """

        # Pass new config values to LogicConfig
        cfg = LogicConfig(
            max_outlinks=self.config.get("max_outlinks", 50),
            trusted_domains=self.config.get("trusted", []),
            same_domain_policy=self.config.get("same_domain_policy", "no-self-domain"),
            use_registrable_domain=self.config.get("use_registrable_domain", False),
            blacklist_patterns=self.config.get("blacklist", []),
            whitelist_patterns=self.config.get("whitelist", []),
            only_whitelist=self.config.get("only_whitelist", False),
        )

        # Get rel-me policy for use in this method
        only_rel_me = self.config.get("only_rel_me", False)

        max_hops = self.config.get("max_hops", 3)

        while self.queue:
            current_url, hops = self.queue.popleft()

            # 🔒 Whitelist check (if enabled)
            # This is now handled inside queue_candidates_* in link_logic.py
            # But we must check for blacklisting.

            # 🔒 Skip blacklisted before any network I/O
            if is_blacklisted(current_url, cfg):
                log.info("Skipping blacklisted URL: %s", current_url)
                continue

            # We skip whitelist check here because the origin (hops=0) should
            # always be allowed, and candidates (hops>0) are filtered
            # by link_logic.py *before* being added to the queue.

            if hops >= max_hops:
                # Prune this branch; do not fetch/parse
                continue

            soup = await self._fetch_and_parse(current_url)
            if not soup:
                continue

            elements = extract_href_elements(soup)
            is_origin_page = current_url == self.normalized_origin_url

            if is_origin_page:
                # A → B candidates
                # Choose outbound candidates according to policy and limits
                next_candidates = queue_candidates_from_origin(
                    current_url=current_url,
                    origin_url=self.normalized_origin_url,
                    elements=elements,
                    cfg=cfg,
                    already_queued=(q[0] for q in self.queue),
                    visited=self.visited_urls,
                )
                for url in next_candidates:
                    self.queue.append((url, hops + 1))
            else:
                # First: detect B → A (direct backlink). If present, record and mark pivot.
                # Find first backlink to origin (supports <a> and <link>)
                tag = detect_backlink_element(
                    current_url=current_url,
                    origin_url=self.normalized_origin_url,
                    elements=elements,
                )

                # --- NEW: Check for only_rel_me mode ---
                if tag is not None and only_rel_me:
                    rels = _rel_list(tag)
                    if "me" not in rels:
                        log.info(
                            "Found backlink, but ignoring (not rel=me) in only-rel-me mode: %s",
                            current_url,
                        )
                        tag = None  # Discard the tag, skipping evidence creation
                # --- End new check ---

                if tag is not None:
                    ev = make_evidence(
                        source_url=current_url,
                        origin_url=self.normalized_origin_url,
                        hops=hops,
                        tag=tag,
                        cfg=cfg,
                        ordinal=len(self.evidence) + 1,
                    )
                    self.evidence.append(ev)
                    self.evidence_producing_urls.add(current_url)
                    self.pivot_has_backlink_to_origin.add(current_url)

                    # BUGFIX: Only queue a page's outlinks if it has a backlink to origin.
                    # This prevents crawling unnecessary pages.
                    next_neighbors = queue_candidates_from_pivot(
                        current_url=current_url,
                        pivot_url=current_url,
                        origin_url=self.normalized_origin_url,
                        elements=elements,
                        cfg=cfg,
                        already_queued=(q[0] for q in self.queue),
                        visited=self.visited_urls,
                    )
                    if next_neighbors:
                        self.pivot_outlinked.setdefault(current_url, set()).update(
                            next_neighbors
                        )
                        for c in next_neighbors:
                            # remember parent (C -> B)
                            if c not in self.parent:
                                self.parent[c] = current_url
                            self.queue.append((c, hops + 1))

                # Third: if this page is a neighbor C (has a known parent B),
                # verify mutuality C → B. If so AND B ↔ A exists, record INDIRECT.
                if current_url in self.parent:
                    pivot_url = self.parent[current_url]
                    tag_to_pivot = detect_backlink_element(
                        current_url=current_url,
                        origin_url=pivot_url,
                        elements=elements,
                    )

                    # --- NEW: Check for only_rel_me mode (for indirect) ---
                    # We only apply rel-me logic to the *direct* B->A link,
                    # not the C->B link. The B->A check was already done above.
                    # We only care that the C->B link *exists*.
                    # The `only_rel_me` check on C->B is NOT applied, as
                    # indirect links are not `rel=me` by definition.
                    # However, we must respect that the B->A link
                    # was only established if it was `rel=me` (if in that mode).
                    # This is handled by checking `pivot_has_backlink_to_origin`.

                    if tag_to_pivot is not None:
                        # confirm B → C existed (we only queued C from B's outlinks)
                        # and B ↔ A has been established
                        if pivot_url in self.pivot_has_backlink_to_origin:
                            ev_ind = make_indirect_evidence(
                                origin_url=self.normalized_origin_url,
                                pivot_url=pivot_url,
                                neighbor_url=current_url,
                                hops=hops,  # typically 2
                                ordinal=len(self.evidence) + 1,
                            )
                            # Do not add indirect evidence if in only_rel_me mode
                            if not only_rel_me:
                                self.evidence.append(ev_ind)
                                self.evidence_producing_urls.add(current_url)
                            else:
                                log.debug(
                                    "Skipping indirect evidence in only-rel-me mode."
                                )

    def get_results(self) -> tuple[List[EvidenceRecord], List[str]]:
        """Return accumulated evidence and errors."""
        return self.evidence, self.errors
