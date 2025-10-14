from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from playwright.async_api import Browser, Page, Playwright,async_playwright

from naive_backlink.models import EvidenceRecord, LinkDetails, URLContext

# Get a logger for this module. The level will be configured in the CLI.
log = logging.getLogger(__name__)


@dataclass
class Crawler:
    """
    Manages the crawling process using a headless browser to render JavaScript.
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

    # Browser automation state
    _playwright: Playwright = field(init=False, repr=False)
    _browser: Browser = field(init=False, repr=False)
    _page: Page = field(init=False, repr=False)
    normalized_origin_url: str = field(init=False)

    def __post_init__(self):
        """Logs the initial state of the crawler."""
        log.info("Crawler initialized for origin: %s", self.origin_url)
        log.debug("Crawler config: %s", self.config)

    async def __aenter__(self):
        """Starts the Playwright instance and launches the browser."""
        log.info("Starting headless browser session...")
        self._playwright = await async_playwright().start()
        log.debug("Playwright started.")
        self._browser = await self._playwright.chromium.launch()
        log.debug("Chromium browser launched.")
        self._page = await self._browser.new_page()
        log.debug("New browser page created.")

        # Set a common browser user-agent to avoid simple bot detection.
        user_agent = self.config.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36",
        )
        await self._page.set_extra_http_headers({"User-Agent": user_agent})
        log.info("Browser User-Agent set to: %s", user_agent)

        self.normalized_origin_url = self._normalize_url(self.origin_url)

        # Initialize the queue: either with seed URLs or the origin URL
        if self.seed_urls:
            log.info("Initializing queue with %d provided seed URLs.", len(self.seed_urls))
            self.visited_urls.add(self.normalized_origin_url)
            for url in self.seed_urls:
                # These are candidates for the first hop
                self.queue.append((self._normalize_url(url), 1))
        else:
            log.info("No seed URLs provided. Initializing queue with origin: %s", self.normalized_origin_url)
            self.queue.append((self.normalized_origin_url, 0))
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Closes the browser and stops Playwright."""
        log.info("Closing headless browser session...")
        await self._browser.close()
        log.debug("Browser closed.")
        await self._playwright.stop()
        log.debug("Playwright stopped.")

    def _normalize_url(self, url: str) -> str:
        """Normalizes a URL for consistent processing."""
        try:
            parsed = urlparse(url)
            path = parsed.path
            if path.endswith('/') and len(path) > 1:
                path = path[:-1]

            normalized = parsed._replace(
                scheme=parsed.scheme.lower(),
                netloc=parsed.netloc.lower(),
                path=path,
                fragment="",
            ).geturl()
            log.debug("Normalized URL '%s' -> '%s'", url, normalized)
            return normalized
        except Exception as e:
            log.warning("Could not normalize URL '%s': %s. Using original.", url, e)
            return url

    async def _fetch_and_parse(self, url: str) -> BeautifulSoup | None:
        """Fetches a URL using the headless browser and parses the rendered HTML."""
        if url in self.visited_urls:
            log.info("Skipping already visited URL: %s", url)
            return None

        log.info("Visiting page: %s", url)
        self.visited_urls.add(url)

        try:
            timeout_seconds = self.config.get("timeout", 10.0)
            log.debug("Navigating to %s (timeout: %ss)", url, timeout_seconds)
            response = await self._page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout_seconds * 1000
            )

            if not response:
                log.error("Failed to get a response from %s (response object is None)", url)
                self.errors.append(f"No response from {url}")
                return None

            log.info("Received HTTP %s for %s", response.status, url)
            if response.status != 200:
                log.warning("URL returned a non-200 status: %s", response.status)

            if response.status >= 400:
                error_msg = f"HTTP error {response.status} for {url}"
                log.error(error_msg)
                self.errors.append(error_msg)
                return None

            log.debug("Retrieving page content for %s", url)
            html_content = await self._page.content()
            log.debug("Page content received, parsing with BeautifulSoup...")
            log.debug(
                "--- Page content start for %s ---\n%s...\n--- Page content end ---",
                url,
                html_content[:500],
            )

            return BeautifulSoup(html_content, "html.parser")

        except Exception as e:
            error_msg = f"An exception occurred while fetching {url}: {e}"
            log.error(error_msg, exc_info=True)
            self.errors.append(error_msg)
            return None

    async def crawl(self):
        """Starts the crawling process."""
        log.info("Starting crawl...")
        while self.queue:
            log.debug(
                "Queue status: %d items. Visited: %d. Evidence: %d. Errors: %d.",
                len(self.queue),
                len(self.visited_urls),
                len(self.evidence),
                len(self.errors),
            )
            current_url, hops = self.queue.popleft()

            if hops >= self.config.get("max_hops", 3):
                log.info("Max hops (%d) reached for %s. Pruning this branch.", hops, current_url)
                continue

            soup = await self._fetch_and_parse(current_url)  # <--- Await the fetch
            if not soup:
                log.warning("Failed to fetch or parse %s, continuing to next in queue.", current_url)
                continue

            all_links = soup.find_all("a", href=True)
            log.info("Found %d link(s) on %s.", len(all_links), current_url)

            for a_tag in all_links:
                log.debug("  - Found link tag on %s: %s", current_url, a_tag.get('href'))

            final_url_on_page = self._normalize_url(self._page.url)
            if final_url_on_page != current_url:
                log.info("URL %s redirected to %s", current_url, final_url_on_page)

            is_origin_page = final_url_on_page == self.normalized_origin_url

            if is_origin_page:
                log.info("Processing page as ORIGIN: %s", final_url_on_page)
                self._process_origin_page_links(final_url_on_page, hops, all_links)
            else:
                log.info("Processing page as CANDIDATE: %s", final_url_on_page)
                self._process_candidate_page_links(final_url_on_page, hops, all_links)

        log.info(
            "Crawl finished. Found %d evidence records and encountered %d errors.",
            len(self.evidence),
            len(self.errors),
        )

    def _process_origin_page_links(self, current_url: str, hops: int, links: list[Tag]):
        """On the origin page, find and queue outgoing candidate links."""
        log.info("Searching for outgoing candidate links on origin page...")
        links_queued = 0
        max_outlinks = self.config.get("max_outlinks", 50)

        for a_tag in links:
            if links_queued >= max_outlinks:
                log.warning("Reached max_outlinks limit (%d), skipping remaining links on this page.", max_outlinks)
                break

            href = a_tag.get("href")
            if not href:
                log.debug("Skipping link tag with no href attribute: %s", a_tag)
                continue

            link_url = urljoin(current_url, href)
            normalized_link = self._normalize_url(link_url)
            is_in_queue = any(q[0] == normalized_link for q in self.queue)

            if normalized_link in self.visited_urls:
                log.debug("Skipping link to already visited URL: %s", normalized_link)
            elif is_in_queue:
                log.debug("Skipping link already in queue: %s", normalized_link)
            else:
                log.info("Queueing candidate for next hop (%d -> %d): %s", hops, hops + 1, normalized_link)
                self.queue.append((normalized_link, hops + 1))
                links_queued += 1

        log.info("Finished processing origin page. Queued %d new candidate links.", links_queued)

    def _process_candidate_page_links(self, current_url: str, hops: int, links: list[Tag]):
        """On a candidate page, search for backlinks to the origin."""
        log.info("Searching for backlinks to origin on candidate page: %s", current_url)
        backlinks_found_on_page = False
        for a_tag in links:
            href = a_tag.get("href")
            if not href:
                log.debug("Skipping link tag with no href attribute: %s", a_tag)
                continue

            backlink_url = urljoin(current_url, href)
            normalized_backlink = self._normalize_url(backlink_url)

            if normalized_backlink == self.normalized_origin_url:
                # This is the first backlink we've found on this page.
                log.info("SUCCESS: Found backlink to origin from %s!", current_url)
                self._create_evidence(current_url, a_tag, hops)
                self.evidence_producing_urls.add(current_url)
                backlinks_found_on_page = True
                # Optimization: We only need one, so we can stop processing this page.
                break

        if not links:
            log.warning("No hyperlinks found at all on candidate page: %s", current_url)
        elif not backlinks_found_on_page:
            log.info("Found %d links, but no backlinks to origin on candidate page: %s", len(links), current_url)
        else:
            log.info("Found 1 backlink on %s (and stopped processing page).", current_url)

    def _create_evidence(self, source_url: str, a_tag: Tag, hops: int):
        """Creates an EvidenceRecord from a found backlink."""
        log.debug("Creating evidence record for backlink from %s", source_url)
        rel_attr = a_tag.get("rel", [])
        if isinstance(rel_attr, str):
            rel_attr = rel_attr.split()

        is_strong = "me" in rel_attr
        classification = "strong" if is_strong else "weak"

        source_domain = urlparse(source_url).netloc
        trusted_domains = self.config.get("trusted", [])
        is_trusted = any(d in source_domain for d in trusted_domains)

        log.info(
            "Classifying backlink from %s as '%s' (rel='%s', trusted=%s)",
            source_url, classification, rel_attr, is_trusted
        )

        evidence = EvidenceRecord(
            id=f"e-backlink-{len(self.evidence) + 1}",
            kind="rel-me" if is_strong else "backlink",
            source=URLContext(url=self.normalized_origin_url, context="origin-page"),
            target=URLContext(url=source_url, context="candidate-page"),
            link=LinkDetails(
                html=str(a_tag),
                rel=rel_attr,
                nofollow="nofollow" in rel_attr,
            ),
            classification=classification,
            hops=hops,
            trusted_surface=is_trusted,
        )
        self.evidence.append(evidence)
        log.debug("Appended new evidence record: %s", evidence)

    def get_results(self) -> tuple[List[EvidenceRecord], List[str]]:
        """Returns the collected evidence and errors."""
        return self.evidence, self.errors