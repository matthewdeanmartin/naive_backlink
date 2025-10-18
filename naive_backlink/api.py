# naive_backlink/api.py
# The primary, programmer-facing API for the library.

from __future__ import annotations

import logging
from typing import List

from naive_backlink.config import load_config  # Import the new config loader
from naive_backlink.crawler import Crawler as HttpxCrawler
from naive_backlink.models import EvidenceRecord, Result
from naive_backlink.playwright_crawler import Crawler as PlaywrightCrawler
from naive_backlink.scoring import calculate_score

log = logging.getLogger(__name__)


async def crawl_and_score(
    origin_url: str,
    *,
    seed_urls: List[str] | None = None,
    trusted_overrides: list[str] | None = None,
    blacklist_overrides: list[str] | None = None,
    whitelist_overrides: list[str] | None = None,
    max_hops: int | None = None,
    only_whitelist: bool | None = None,
    only_rel_me: bool | None = None,
) -> Result:
    """
    The main API function. Orchestrates the crawling and scoring process.

    Args:
        origin_url: The starting URL to verify.
        seed_urls: A pre-scraped list of candidate URLs to check.
        trusted_overrides: A list of domains to add to the trusted list.
        blacklist_overrides: A list of domains to add to the blacklist.
        whitelist_overrides: A list of domains to add to the whitelist.
        max_hops: Override the default maximum number of hops.
        only_whitelist: If True, only crawl URLs in the whitelist.
        only_rel_me: If True, only count rel="me" links as evidence.

    Returns:
        A Result object containing the score, label, and evidence.
    """
    log.info("Starting new crawl and score process for: %s", origin_url)

    # Load base config from defaults + pyproject.toml
    config = load_config()
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
    if whitelist_overrides:
        config["whitelist"].extend(whitelist_overrides)
        log.info("Applied override - added whitelist domains: %s", whitelist_overrides)
    if only_whitelist is not None:
        config["only_whitelist"] = only_whitelist
        log.info("Applied override - only_whitelist set to: %s", only_whitelist)
    if only_rel_me is not None:
        config["only_rel_me"] = only_rel_me
        log.info("Applied override - only_rel_me set to: %s", only_rel_me)

    # Crawl for evidence, with fallback from httpx to Playwright
    evidence: list[EvidenceRecord] = []
    errors: list[str] = []
    try:
        # Stage 1: Attempt crawl with lightweight HTTP client
        log.info("Step 1a: Crawling with lightweight HTTP client (httpx).")
        async with HttpxCrawler(origin_url, config, seed_urls=seed_urls) as crawler:
            await crawler.crawl()
            evidence, errors = crawler.get_results()

        # Stage 2: If no evidence, fall back to full browser crawl
        if not evidence and config["use_playwright_as_fallback"]:
            log.warning(
                "No evidence found with httpx. Falling back to full browser (Playwright)."
            )
            # Clear any errors from the first attempt before retrying
            errors.clear()
            async with PlaywrightCrawler(
                origin_url, config, seed_urls=seed_urls
            ) as playwright_crawler:
                await playwright_crawler.crawl()
                evidence, errors = playwright_crawler.get_results()

        log.info(
            "Evidence collection complete. Found %d evidence records and %d errors.",
            len(evidence),
            len(errors),
        )
    except Exception as e:
        log.critical(
            "An unrecoverable error occurred during the crawl: %s", e, exc_info=True
        )
        errors.append(f"Fatal crawler error: {e}")
        raise

    # Calculate score
    log.info("Step 2: Calculating score based on collected evidence.")
    score, label = calculate_score(evidence)
    log.info("Score calculated. Final score: %.2f (%s)", score, label)

    # Return the final result object
    log.info("Step 3: Assembling final result.")
    return Result(
        origin_url=origin_url,
        score=score,
        label=label,
        evidence=evidence,
        errors=errors,
    )
