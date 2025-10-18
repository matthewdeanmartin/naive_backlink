# naive_backlink/crawler.py
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
from __future__ import annotations
import asyncio
from urllib.parse import urlparse

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


# --- NEW: domain grouping helper ------------------------------------------------
def _domain_group(url: str, use_registrable: bool) -> str:
    """
    Return the concurrency bucket key for a URL.
    If use_registrable is True and tldextract is available, group by registrable domain.
    Otherwise group by host (netloc without port normalization).
    """
    host = urlparse(url).hostname or ""
    if not host:
        return ""  # unknown -> serialized anyway under empty key
    if use_registrable:
        try:
            import tldextract  # type: ignore
            ext = tldextract.extract(host)
            if ext.registered_domain:
                return ext.registered_domain.lower()
        except Exception:
            # Log once per process would be ideal; keep it cheap:
            log.debug("tldextract unavailable/failure; falling back to host for %s", host)
    return host.lower()


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


    # --- NEW: encapsulate per-URL processing (was inline in crawl loop) -------------

    async def _process_url(
            self,
            current_url: str,
            hops: int,
            cfg: LogicConfig,
            only_rel_me: bool,
            max_hops: int,
    ) -> None:
        # Whitelist handled in link_logic queue_*; enforce blacklist early:
        if is_blacklisted(current_url, cfg):
            log.info("Skipping blacklisted URL: %s", current_url)
            return

        if hops >= max_hops:
            return

        soup = await self._fetch_and_parse(current_url)
        if not soup:
            return

        elements = extract_href_elements(soup)
        is_origin_page = current_url == self.normalized_origin_url

        if is_origin_page:
            # A → B candidates
            next_candidates = queue_candidates_from_origin(
                current_url=current_url,
                origin_url=self.normalized_origin_url,
                elements=elements,
                cfg=cfg,
                already_queued=(u for (u, _) in self._queued_urls),  # NEW
                visited=self.visited_urls,
            )
            for url in next_candidates:
                self._enqueue(url, hops + 1)  # NEW
            return

        # B → A direct backlink?
        tag = detect_backlink_element(
            current_url=current_url,
            origin_url=self.normalized_origin_url,
            elements=elements,
        )

        if tag is not None and only_rel_me:
            rels = _rel_list(tag)
            if "me" not in rels:
                log.info("Found backlink, but ignoring (not rel=me) in only-rel-me mode: %s", current_url)
                tag = None

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

            # B → C fan-out only if B ↔ A established
            next_neighbors = queue_candidates_from_pivot(
                current_url=current_url,
                pivot_url=current_url,
                origin_url=self.normalized_origin_url,
                elements=elements,
                cfg=cfg,
                already_queued=(u for (u, _) in self._queued_urls),  # NEW
                visited=self.visited_urls,
            )
            if next_neighbors:
                self.pivot_outlinked.setdefault(current_url, set()).update(next_neighbors)
                for c in next_neighbors:
                    if c not in self.parent:
                        self.parent[c] = current_url
                    self._enqueue(c, hops + 1)  # NEW

        # Indirect C ↔ B (only if we already queued C from B)
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

            if tag_to_pivot is not None and pivot_url in self.pivot_has_backlink_to_origin:
                if not only_rel_me:
                    ev_ind = make_indirect_evidence(
                        origin_url=self.normalized_origin_url,
                        pivot_url=pivot_url,
                        neighbor_url=current_url,
                        hops=hops,
                        ordinal=len(self.evidence) + 1,
                    )
                    self.evidence.append(ev_ind)
                    self.evidence_producing_urls.add(current_url)
                else:
                    log.debug("Skipping indirect evidence in only-rel-me mode.")

    # --- NEW: enqueue helper that avoids double-scheduling --------------------------
    def _enqueue(self, url: str, hops: int) -> None:
        url = normalize_url(url)
        if url in self.visited_urls:
            return
        if url in self._scheduled_urls:
            return
        self.queue.append((url, hops))
        # `_queued_urls` mirrors `queue` but as a set for O(1) lookups
        self._queued_urls.add((url, hops))

    # --- REPLACED: crawl() with per-domain parallelism ------------------------------
    async def crawl(self) -> None:
        """
        Parallel crawl with per-domain concurrency=1.
        Cross-domain requests run concurrently; same-domain requests are serialized.
        """

        cfg = LogicConfig(
            max_outlinks=self.config.get("max_outlinks", 50),
            trusted_domains=self.config.get("trusted", []),
            same_domain_policy=self.config.get("same_domain_policy", "no-self-domain"),
            use_registrable_domain=self.config.get("use_registrable_domain", False),
            blacklist_patterns=self.config.get("blacklist", []),
            whitelist_patterns=self.config.get("whitelist", []),
            only_whitelist=self.config.get("only_whitelist", False),
        )
        only_rel_me = self.config.get("only_rel_me", False)
        max_hops = self.config.get("max_hops", 3)

        # Scheduler state
        max_global = int(self.config.get("max_global_concurrency", 16))
        domain_sems: dict[str, asyncio.Semaphore] = {}
        waiting_by_domain: dict[str, Deque[tuple[str, int]]] = {}
        in_flight: set[asyncio.Task] = set()

        # De-dup helpers
        self._scheduled_urls: Set[str] = set()
        self._queued_urls: Set[tuple[str, int]] = set()
        for item in list(self.queue):
            self._queued_urls.add(item)

        queue_event = asyncio.Event()

        def ensure_domain_structs(key: str) -> None:
            if key not in domain_sems:
                domain_sems[key] = asyncio.Semaphore(1)
            if key not in waiting_by_domain:
                waiting_by_domain[key] = deque()

        async def run_one(url: str, hops: int) -> None:
            key = _domain_group(url, cfg.use_registrable_domain)
            ensure_domain_structs(key)
            sem = domain_sems[key]
            async with sem:
                try:
                    await self._process_url(url, hops, cfg, only_rel_me, max_hops)
                finally:
                    queue_event.set()  # always nudge the scheduler

        def start_task(url: str, hops: int) -> None:
            """Start a task immediately (assumes domain semaphore currently available)."""
            self._scheduled_urls.add(url)
            t = asyncio.create_task(run_one(url, hops))
            in_flight.add(t)

            def _done_cb(task: asyncio.Task, u=url) -> None:
                in_flight.discard(task)
                self._scheduled_urls.discard(u)
                # After a domain task finishes, if that domain has waiting items, start one now.
                key = _domain_group(u, cfg.use_registrable_domain)
                dq = waiting_by_domain.get(key)
                if dq:
                    sem = domain_sems[key]
                    if dq and not sem.locked():
                        nxt_url, nxt_hops = dq.popleft()
                        start_task(nxt_url, nxt_hops)
                queue_event.set()

            t.add_done_callback(_done_cb)

        def promote_waiting() -> int:
            """
            Start tasks directly from per-domain waiting queues whenever a domain
            has capacity and global capacity allows. Returns #tasks started.
            """
            started = 0
            if len(in_flight) >= max_global:
                return 0

            # Simple fairness: round-robin domains with waiting work.
            for key, dq in list(waiting_by_domain.items()):
                if not dq or len(in_flight) >= max_global:
                    continue
                sem = domain_sems[key]
                while dq and not sem.locked() and len(in_flight) < max_global:
                    url, hops = dq.popleft()
                    if url in self.visited_urls or url in self._scheduled_urls:
                        continue
                    start_task(url, hops)
                    started += 1
            return started

        def drain_global_queue() -> int:
            """
            Start tasks from the global BFS queue while respecting domain and global limits.
            Items that hit a locked domain are staged into waiting_by_domain.
            Returns #tasks started.
            """
            started = 0
            while self.queue and len(in_flight) < max_global:
                url, hops = self.queue.popleft()
                self._queued_urls.discard((url, hops))
                if url in self.visited_urls or url in self._scheduled_urls:
                    continue
                key = _domain_group(url, cfg.use_registrable_domain)
                ensure_domain_structs(key)
                sem = domain_sems[key]
                if sem.locked():
                    waiting_by_domain[key].append((url, hops))
                    continue
                start_task(url, hops)
                started += 1
            return started

        # Bootstrap once
        drain_global_queue()
        promote_waiting()

        # Main scheduling loop
        try:
            while in_flight or self.queue or any(waiting_by_domain.values()):
                # Try to make progress greedily before sleeping
                made_progress = False
                if self.queue:
                    if drain_global_queue() > 0:
                        made_progress = True
                if promote_waiting() > 0:
                    made_progress = True

                if made_progress:
                    continue

                # Nothing to start right now → wait for any task to finish or new URLs enqueued
                queue_event.clear()
                await queue_event.wait()
        finally:
            # Ensure all tasks are done; cancel stragglers if any remain (defensive)
            if in_flight:
                for t in list(in_flight):
                    t.cancel()
                await asyncio.gather(*in_flight, return_exceptions=True)

    def get_results(self) -> tuple[List[EvidenceRecord], List[str]]:
        """Return accumulated evidence and errors."""
        return self.evidence, self.errors
