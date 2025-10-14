# The primary, programmer-facing API for the library.

from __future__ import annotations

import logging
from typing import List

from naive_backlink.models import Result
from naive_backlink.crawler import Crawler as HttpxCrawler
from naive_backlink.playwright_crawler import Crawler as PlaywrightCrawler
from naive_backlink.scoring import calculate_score

log = logging.getLogger(__name__)


# Placeholder for a function to load configuration from pyproject.toml
def _load_config() -> dict:
    # In a real implementation, this would read and parse pyproject.toml
    return {
        "max_hops": 3,
        "max_redirects": 5,
        "max_outlinks": 50,
        "timeout": 10.0,
        "max_content_bytes": 1048576,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
        "trusted": [],
        "blacklist": [],
    }

async def crawl_and_score(
    origin_url: str,
    *,
    seed_urls: List[str] | None = None,
    trusted_overrides: list[str] | None = None,
    blacklist_overrides: list[str] | None = None,
    max_hops: int | None = None,
) -> Result:
    """
    The main API function. Orchestrates the crawling and scoring process.

    Args:
        origin_url: The starting URL to verify.
        seed_urls: A pre-scraped list of candidate URLs to check.
        trusted_overrides: A list of domains to add to the trusted list.
        blacklist_overrides: A list of domains to add to the blacklist.
        max_hops: Override the default maximum number of hops.

    Returns:
        A Result object containing the score, label, and evidence.
    """
    log.info("Starting new crawl and score process for: %s", origin_url)
    config = _load_config()
    log.debug("Loaded base configuration.")

    # Apply overrides if provided
    if max_hops is not None:
        config["max_hops"] = max_hops
        log.info("Applied override - max_hops set to: %d", max_hops)
    if trusted_overrides:
        config["trusted"].extend(trusted_overrides)
        log.info("Applied override - added trusted domains: %s", trusted_overrides)
    if blacklist_overrides:
        config["blacklist"].extend(blacklist_overrides)
        log.info("Applied override - added blacklist domains: %s", blacklist_overrides)


    # 1. Crawl for evidence, with fallback from httpx to Playwright
    evidence = []
    errors = []
    try:
        # Stage 1: Attempt crawl with lightweight HTTP client
        log.info("Step 1a: Crawling with lightweight HTTP client (httpx).")
        async with HttpxCrawler(origin_url, config, seed_urls=seed_urls) as crawler:
            await crawler.crawl()
            evidence, errors = crawler.get_results()

        # Stage 2: If no evidence, fall back to full browser crawl
        if not evidence:
            log.warning("No evidence found with httpx. Falling back to full browser (Playwright).")
            # Clear any errors from the first attempt before retrying
            errors.clear()
            async with PlaywrightCrawler(origin_url, config, seed_urls=seed_urls) as playwright_crawler:
                await playwright_crawler.crawl()
                evidence, errors = playwright_crawler.get_results()

        log.info(
            "Evidence collection complete. Found %d evidence records and %d errors.",
            len(evidence),
            len(errors),
        )
    except Exception as e:
        log.critical("An unrecoverable error occurred during the crawl: %s", e, exc_info=True)
        errors.append(f"Fatal crawler error: {e}")

    # 2. Calculate score
    log.info("Step 2: Calculating score based on collected evidence.")
    score, label = calculate_score(evidence)
    log.info("Score calculated. Final score: %.2f (%s)", score, label)

    # 3. Return the final result object
    log.info("Step 3: Assembling final result.")
    return Result(
        origin_url=origin_url,
        score=score,
        label=label,
        evidence=evidence,
        errors=errors,
    )
