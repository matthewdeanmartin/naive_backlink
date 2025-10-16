# naive_backlink/playwright_crawler.py
"""
Playwright-based crawler.

Goals:
- Stay faithful to original behavior (render JS, single tab, BFS, hop limits).
- Centralize all tag/URL logic via link_logic.py.
- Support both <a href=...> and <link href=...> for outlinks/backlinks.
- Preserve and clarify logging.

Config keys consumed:
  - user_agent: str
  - timeout: float (seconds)
  - max_content_bytes: int (applies to rendered HTML length)
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
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Set

from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page, Playwright, async_playwright

from naive_backlink.link_logic import _rel_list  # Import for rel="me" check
from naive_backlink.link_logic import (
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
    Manages the crawling process using a headless browser to render JavaScript.
    Delegates all link parsing and policy to link_logic.py.
    """

    origin_url: str
    config: Dict[str, Any]
    seed_urls: List[str] | None = None

    # Internal BFS state
    queue: Deque[tuple[str, int]] = field(default_factory=deque)
    visited_urls: Set[str] = field(default_factory=set)
    evidence_producing_urls: Set[str] = field(default_factory=set)
    evidence: List[EvidenceRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    # second-degree tracking
    parent: Dict[str, str] = field(default_factory=dict)  # C -> B
    pivot_has_backlink_to_origin: Set[str] = field(default_factory=set)  # B with B→A
    pivot_outlinked: Dict[str, Set[str]] = field(default_factory=dict)  # B -> {C}

    # Playwright state
    _playwright: Playwright = field(init=False, repr=False)
    _browser: Browser = field(init=False, repr=False)
    _page: Page = field(init=False, repr=False)

    # Derived
    normalized_origin_url: str = field(init=False)

    async def __aenter__(self) -> "Crawler":
        """Starts Playwright, launches Chromium, creates a page, sets UA, initializes queue."""
        log.info("Starting headless browser session...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch()
        self._page = await self._browser.new_page()

        user_agent = self.config.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36",
        )
        await self._page.set_extra_http_headers({"User-Agent": user_agent})
        log.info("Browser User-Agent set.")

        self.normalized_origin_url = normalize_url(self.origin_url)

        # Initialize BFS queue
        if self.seed_urls:
            # Treat seeds as first-hop candidates; mark origin as visited
            self.visited_urls.add(self.normalized_origin_url)
            for url in self.seed_urls:
                self.queue.append((normalize_url(url), 1))
            log.info("Queue initialized with %d seed URL(s).", len(self.seed_urls))
        else:
            self.queue.append((self.normalized_origin_url, 0))
            log.info("Queue initialized with origin: %s", self.normalized_origin_url)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Tears down the browser cleanly."""
        log.info("Closing headless browser session...")
        try:
            await self._browser.close()
        finally:
            await self._playwright.stop()
        log.info("Browser session closed.")

    async def _fetch_and_parse(self, url: str) -> tuple[str, BeautifulSoup] | None:
        """
        Navigate to `url`, wait for DOMContentLoaded, and return (final_url, soup).
        Records errors for network/HTTP failures and non-HTML content.
        """
        if not is_fetchable_url(url):
            log.info("Skipping non-fetchable URL (scheme not http/https): %s", url)
            return None
        if not is_probably_html_url(url):
            log.info("Skip non-HTML by extension: %s", url)
            return None
        if url in self.visited_urls:
            log.debug("Skipping already visited URL: %s", url)
            return None
        self.visited_urls.add(url)

        try:
            timeout_ms = int(self.config.get("timeout", 10.0) * 1000)
            log.debug("Navigating to %s (timeout=%sms)...", url, timeout_ms)
            response = await self._page.goto(
                url, wait_until="domcontentloaded", timeout=timeout_ms
            )

            if response is None:
                msg = f"No response from {url}"
                log.error(msg)
                self.errors.append(msg)
                return None

            status = response.status
            if status != 200:
                log.warning("URL returned non-200 status: %s (%d)", url, status)
            if status >= 400:
                msg = f"HTTP error {status} for {url}"
                log.error(msg)
                self.errors.append(msg)
                return None

            # Attempt to filter non-HTML when the header is present.
            try:
                ctype = (response.headers or {}).get("content-type", "").lower()
            except Exception:
                ctype = ""
            if ctype and ("text/html" not in ctype):
                log.info("Skipping non-HTML content at %s (%s)", url, ctype)
                return None

            html = await self._page.content()
            max_bytes = self.config.get("max_content_bytes", 1024 * 1024)
            if len(html) > max_bytes:
                msg = f"Content too large at {url} ({len(html)} > {max_bytes})"
                log.warning(msg)
                self.errors.append(msg)
                return None

            final_url = normalize_url(self._page.url or url)
            if final_url != normalize_url(url):
                log.info("Navigation redirected: %s -> %s", url, final_url)

            soup = BeautifulSoup(html, "html.parser")
            return final_url, soup

        except Exception as e:
            msg = f"An exception occurred while fetching {url}: {e}"
            log.error(msg, exc_info=True)
            self.errors.append(msg)
            return None

    async def crawl(self) -> None:
        """
        BFS crawl. On origin page: discover next-hop candidates.
        On candidate pages: detect the first backlink to origin and record evidence.
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

        log.info(
            "Crawl start. max_hops=%d, max_outlinks=%d, same_domain_policy=%s",
            max_hops,
            cfg.max_outlinks,
            cfg.same_domain_policy,
        )

        while self.queue:
            log.debug(
                "Queue=%d, Visited=%d, Evidence=%d, Errors=%d",
                len(self.queue),
                len(self.visited_urls),
                len(self.evidence),
                len(self.errors),
            )
            current_url, hops = self.queue.popleft()

            # 🔒 Skip blacklisted before any network I/O
            if is_blacklisted(current_url, cfg):
                log.info("Skipping blacklisted URL: %s", current_url)
                continue

            # Whitelist logic is handled in queue_candidates_*

            if hops >= max_hops:
                log.debug("Max hops reached (%d) for %s; skipping.", hops, current_url)
                continue

            fetched = await self._fetch_and_parse(current_url)
            if not fetched:
                continue

            final_url_on_page, soup = fetched
            elements = extract_href_elements(soup)
            log.info(
                "Found %d link element(s) on %s.", len(elements), final_url_on_page
            )

            is_origin_page = final_url_on_page == self.normalized_origin_url

            if is_origin_page:
                # A → B
                # On the origin, select outbound candidates respecting policy and limits.
                next_candidates = queue_candidates_from_origin(
                    current_url=final_url_on_page,
                    origin_url=self.normalized_origin_url,
                    elements=elements,
                    cfg=cfg,
                    already_queued=(q[0] for q in self.queue),
                    visited=self.visited_urls,
                )
                for url in next_candidates:
                    log.debug("Queueing candidate (%d -> %d): %s", hops, hops + 1, url)
                    self.queue.append((url, hops + 1))
                log.info(
                    "Queued %d candidate URL(s) from origin.", len(next_candidates)
                )
            else:
                # B → A
                # On a candidate page, detect a backlink (first match only).
                tag = detect_backlink_element(
                    current_url=final_url_on_page,
                    origin_url=self.normalized_origin_url,
                    elements=elements,
                )

                # --- NEW: Check for only_rel_me mode ---
                if tag is not None and only_rel_me:
                    rels = _rel_list(tag)
                    if "me" not in rels:
                        log.info(
                            "Found backlink, but ignoring (not rel=me) in only-rel-me mode: %s",
                            final_url_on_page,
                        )
                        tag = None  # Discard the tag, skipping evidence creation
                # --- End new check ---

                if tag is not None:
                    ev = make_evidence(
                        source_url=final_url_on_page,
                        origin_url=self.normalized_origin_url,
                        hops=hops,
                        tag=tag,
                        cfg=cfg,
                        ordinal=len(self.evidence) + 1,
                    )
                    self.evidence.append(ev)
                    self.evidence_producing_urls.add(final_url_on_page)
                    self.pivot_has_backlink_to_origin.add(final_url_on_page)
                    log.info(
                        "Backlink detected from %s (classification=%s).",
                        final_url_on_page,
                        ev.classification,
                    )

                    # BUGFIX: Only queue this page's outlinks (B->C) if it links back to origin (B->A).
                    next_neighbors = queue_candidates_from_pivot(
                        current_url=final_url_on_page,
                        pivot_url=final_url_on_page,
                        origin_url=self.normalized_origin_url,
                        elements=elements,
                        cfg=cfg,
                        already_queued=(q[0] for q in self.queue),
                        visited=self.visited_urls,
                    )
                    if next_neighbors:
                        self.pivot_outlinked.setdefault(
                            final_url_on_page, set()
                        ).update(next_neighbors)
                        for c in next_neighbors:
                            if c not in self.parent:
                                self.parent[c] = final_url_on_page
                            self.queue.append((c, hops + 1))
                else:
                    log.info("No backlink to origin found on %s.", final_url_on_page)

                # C → B validation (strict mutual chain)
                if final_url_on_page in self.parent:
                    pivot_url = self.parent[final_url_on_page]
                    tag_to_pivot = detect_backlink_element(
                        current_url=final_url_on_page,
                        origin_url=pivot_url,
                        elements=elements,
                    )
                    if (
                        tag_to_pivot is not None
                        and pivot_url in self.pivot_has_backlink_to_origin
                    ):
                        ev_ind = make_indirect_evidence(
                            origin_url=self.normalized_origin_url,
                            pivot_url=pivot_url,
                            neighbor_url=final_url_on_page,
                            hops=hops,
                            ordinal=len(self.evidence) + 1,
                        )
                        # Do not add indirect evidence if in only_rel_me mode
                        if not only_rel_me:
                            self.evidence.append(ev_ind)
                            self.evidence_producing_urls.add(final_url_on_page)
                        else:
                            log.debug("Skipping indirect evidence in only-rel-me mode.")

        log.info(
            "Crawl finished. Evidence=%d, Errors=%d.",
            len(self.evidence),
            len(self.errors),
        )

    def get_results(self) -> tuple[List[EvidenceRecord], List[str]]:
        """Expose collected evidence and errors."""
        return self.evidence, self.errors
