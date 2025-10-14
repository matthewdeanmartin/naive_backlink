from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Set
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag


from naive_backlink.models import EvidenceRecord, LinkDetails, URLContext

# Get a logger for this module. The level will be configured in the CLI.
log = logging.getLogger(__name__)


@dataclass
class Crawler:
    """
    Manages the crawling process to find backlinks using httpx.
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

    # HTTP client
    _client: httpx.AsyncClient = field(init=False, repr=False)
    normalized_origin_url: str = field(init=False)

    async def __aenter__(self):
        """Initializes the async HTTP client."""
        log.info("Starting httpx session...")
        headers = {
            "User-Agent": self.config.get(
                "user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36",
            )
        }
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=self.config.get("timeout", 10.0),
            headers=headers,
        )
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
        """Closes the async HTTP client."""
        log.info("Closing httpx session.")
        await self._client.aclose()


    def _normalize_url(self, url: str) -> str:
        """
        Normalizes a URL for consistent processing.
        - Lowercases scheme and netloc.
        - Strips fragment.
        - Strips trailing slash from path unless it's the root.
        """
        try:
            parsed = urlparse(url)
            path = parsed.path
            if path.endswith('/') and len(path) > 1:
                path = path[:-1]

            return parsed._replace(
                scheme=parsed.scheme.lower(),
                netloc=parsed.netloc.lower(),
                path=path,
                fragment="",
            ).geturl()
        except Exception:
            # Fallback for malformed URLs
            return url

    async def _fetch_and_parse(self, url: str) -> BeautifulSoup | None:
        """Fetches a URL and parses it into a BeautifulSoup object with logging."""
        if url in self.visited_urls:
            log.info(f"Skipping already visited URL: {url}")
            return None

        log.info(f"Fetching: {url}")
        self.visited_urls.add(url)

        try:
            response = await self._client.get(url)
            log.info(f"Received status {response.status_code} for {url}")

            if response.status_code != 200:
                log.warning(f"URL returned non-200 status: {response.status_code}")

            response.raise_for_status()  # Raise an exception for 4xx/5xx statuses

            # Log the beginning of the page content for debugging purposes.
            log.debug(f"--- Page content start for {url} ---\n"
                      f"{response.text}...\n"
                      f"--- Page content end ---")

            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type:
                log.info(f"Skipping non-HTML content type '{content_type}' at {url}")
                return None

            if len(response.content) > self.config.get("max_content_bytes", 1024 * 1024):
                log.warning(f"Content at {url} exceeds max size, skipping.")
                self.errors.append(f"Content too large at {url}")
                return None

            # Using the robust built-in html.parser to avoid dependency issues.
            return BeautifulSoup(response.text, "html.parser")

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error for {url}: {e}"
            log.error(error_msg)
            # Log the response body at DEBUG level for troubleshooting.
            log.debug(f"Response body for failed request to {url}:\n{e.response.text}")
            self.errors.append(error_msg)
            return None
        except httpx.RequestError as e:
            error_msg = f"Network error fetching {url}: {e}"
            log.error(error_msg)
            self.errors.append(error_msg)
            return None
        except Exception as e:
            error_msg = f"Error parsing {url}: {e}"
            log.error(error_msg)
            self.errors.append(error_msg)
            return None

    async def crawl(self):
        """Starts the crawling process."""
        while self.queue:
            current_url, hops = self.queue.popleft()

            if hops >= self.config.get("max_hops", 3):
                log.info(f"Max hops reached for path starting from {current_url}, stopping branch.")
                continue

            soup = await self._fetch_and_parse(current_url)
            if not soup:
                continue

            all_links = soup.find_all("a", href=True)
            log.info(f"Found {len(all_links)} link(s) on {current_url}.")


            # Log every link found for verbose detail
            for a_tag in all_links:
                log.debug(f"  - Found link on {current_url}: {a_tag.get('href')}")

            # --- Process links based on page type (Origin vs. Candidate) ---
            is_origin_page = (current_url == self.normalized_origin_url)

            if is_origin_page:
                self._process_origin_page_links(current_url, hops, all_links)
            else:
                self._process_candidate_page_links(current_url, hops, all_links)

    def _process_origin_page_links(self, current_url: str, hops: int, links: list[Tag]):
        """On the origin page, find and queue outgoing candidate links."""
        links_queued = 0
        for a_tag in links:
            if links_queued >= self.config.get("max_outlinks", 50):
                log.info(f"Max outlinks reached on origin page, stopping link processing.")
                break

            link_url = urljoin(current_url, a_tag["href"])
            normalized_link = self._normalize_url(link_url)

            # Avoid re-queueing links we've already seen
            if normalized_link not in self.visited_urls and not any(q[0] == normalized_link for q in self.queue):
                log.info(f"Queueing candidate for next hop: {normalized_link}")
                self.queue.append((normalized_link, hops + 1))
                links_queued += 1

    def _process_candidate_page_links(self, current_url: str, hops: int, links: list[Tag]):
        """On a candidate page, search for backlinks to the origin."""
        backlinks_found_on_page = False
        for a_tag in links:
            backlink_url = urljoin(current_url, a_tag["href"])
            normalized_backlink = self._normalize_url(backlink_url)

            if normalized_backlink == self.normalized_origin_url:
                # This is the first backlink we've found on this page.
                log.warning(f"Found potential backlink from {current_url} to origin!")
                self._create_evidence(current_url, a_tag, hops)
                self.evidence_producing_urls.add(current_url)
                backlinks_found_on_page = True
                # Optimization: We only need one, so we can stop processing this page.
                break

        # Add warnings if no links or no backlinks were found.
        if not links:
            log.warning(f"No hyperlinks found at all on candidate page: {current_url}")
        elif not backlinks_found_on_page:
            log.warning(f"Found links, but no backlinks to origin on candidate page: {current_url}")

    def _create_evidence(self, source_url: str, a_tag: Tag, hops: int):
        """Creates an EvidenceRecord from a found backlink."""
        rel_attr = a_tag.get("rel", [])
        is_strong = "me" in rel_attr
        classification = "strong" if is_strong else "weak"

        source_domain = urlparse(source_url).netloc
        trusted_domains = self.config.get("trusted", [])
        is_trusted = any(d in source_domain for d in trusted_domains)

        log.info(
            f"Classifying backlink from {source_url} as '{classification}' "
            f"(rel='{rel_attr}', trusted_surface={is_trusted})"
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

    def get_results(self) -> tuple[List[EvidenceRecord], List[str]]:
        """Returns the collected evidence and errors."""
        return self.evidence, self.errors