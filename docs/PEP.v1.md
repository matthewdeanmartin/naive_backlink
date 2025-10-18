Of course. Based on the detailed analysis of the implementation and its divergence from the original spec, here is a revised PEP draft that incorporates the real-world lessons learned. This version formalizes the successful patterns from the code, such as the JS-rendering fallback, caching, and a more extensible model for evidence detection.

-----

# PEP: Naive Backlink Checker (Revision 1)

  - **PEP**: TBD
  - **Title**: Naive Backlink Checker for Non‑Cryptographic Identity Linking
  - **Author**: Matthew D. Martin [matthewdeanmartin@gmail.com](mailto:matthewdeanmartin@gmail.com)
  - **Status**: Draft (Revision 1)
  - **Type**: Standards Track (Library/API/CLI)
  - **Created**: 2025‑10‑13
  - **Last-Updated**: 2025-10-16
  - **Python-Version**: 3.10+

## Abstract

This PEP specifies a minimal, auditable method for detecting, classifying, and scoring *backlinks* among public web resources to infer soft identity control without cryptography. A *backlink* exists when **Page A** links to **Page B**, and **Page B** links back to **Page A**. This revision incorporates lessons from a reference implementation, specifying a more robust two-stage crawl strategy, a configurable and extensible "Recognizer" model for discovering evidence in diverse content types (HTML, JSON, XML), and a corrected scoring function aligned with practical test cases.

## Motivation

Package ecosystems (e.g., PyPI) frequently depend on social proofs. Maintainers embed outbound links—social profiles, blogs, code forges—that may in turn link back. Detecting such backlink structures produces a practical, explainable identity signal where cryptographic attestations are unavailable. This revision aims to create a more resilient and adaptable specification that can handle modern, JavaScript-heavy websites and structured data feeds, moving beyond the limitations of a simple HTML-only approach.

## Terminology

  - **Origin Page (OP)**: The page for which identity corroboration is sought.
  - **Candidate Page (CP)**: A page linked from OP or discovered via link expansion.
  - **Backlink**: A link from CP returning to OP.
  - **Strong Backlink**: A backlink using robust semantics, e.g. `<a rel="me" href=...>`.
  - **Weak Backlink**: A simple hyperlink lacking strong semantics.
  - **Indirect Backlink**: A corroboration path requiring intermediate pages (e.g., OP → GitHub repo → GitHub user profile → OP).
  - **Trusted Surface**: A site plausibly controlled by the claimed user.
  - **Untrusted Surface**: Aggregators, mirrors, or search results.

## Non‑Goals

  - This PEP does not specify any cryptographic verification (PGP, sigstore).
  - While a compliant implementation may use a JavaScript-rendering engine, it is not required as the primary crawl method. The specification recommends a performance-oriented fallback strategy.

## Specification

### 1\. Evidence Model

The checker emits structured *Evidence Records*. The model remains unchanged from the original draft.

```json
{
  "id": "e-backlink-001",
  "kind": "backlink",
  "source": { "url": "...", "context": "origin-page" },
  "target": { "url": "...", "context": "candidate-page" },
  "link": { "html": "<a rel=\"me\" ...>", "rel": ["me"], "nofollow": false },
  "classification": "strong",
  "hops": 1,
  "trusted_surface": true,
  "observed_at": "2025-10-16T16:20:00Z",
  "notes": "Direct rel=me backlink"
}
```

### 2\. Backlink Classes

The classification of backlinks as **Strong**, **Weak**, and **Indirect** remains a core principle. A strong backlink provides a high-confidence signal, while weak and indirect links provide corroborating evidence.

### 3\. Trusted/Untrusted Surfaces

The checker maintains configurable lists of trusted and untrusted surfaces.

  - **Trusted (examples)**: `github.com/<user>`, `*.mastodon.social`, personal domains.
  - **Untrusted (blacklist examples)**: `google.com`, `libraries.io`, `grep.app`.
  - **Policy**: Patterns MUST support matching against both the full hostname and specific host+path combinations (e.g., `github.com/topics/*`) to filter out noisy sections of trusted sites.

### 4\. Content Types and Recognizers

To handle the modern web, this PEP moves beyond a purely `rel="me"` HTML model to a configurable **Recognizer** system. Recognizers are rules for extracting links from different content types.

  - **HTML Recognizers**:

      - `rel_me`: The default recognizer for strong backlinks, finding `<a>` or `<link>` tags with `rel="me"`.
      - `css_selector`: Extracts a URL from the `href` attribute of an element matching a specific CSS selector. This is for trusted sites with idiosyncratic but stable markup for profile links.

  - **Structured Data Recognizers**:

      - `json_path`: Extracts a URL from a JSON document using a JSONPath expression.
      - `xpath`: Extracts a URL from an XML document (e.g., RSS/Atom feeds) using an XPath expression.

A compliant implementation MUST check the `Content-Type` of a response and apply the appropriate configured recognizer. See §15 for the configuration format.

### 5\. Heuristics for Control and Canonicalization

  - **User Control**: User control is presumed for well-known profile paths and personal domains corroborated by another trusted surface. The `use_registrable_domain` policy (using a library like `tldextract`) is RECOMMENDED for intelligently comparing domains and subdomains.
  - **Canonicalization**: URL normalization and redirect-following (up to `MAX_REDIRECTS`) remain as specified.

### 6\. Crawl Strategy & Limits

  - **Two-Stage Crawl Strategy (RECOMMENDED)**: To balance performance and robustness, a checker SHOULD implement a two-stage process:

    1.  **Lightweight Fetch**: First, attempt to fetch and parse the content using a simple HTTP client (e.g., `httpx`). This is fast and sufficient for static sites, RSS feeds, and JSON APIs.
    2.  **Full-Render Fallback**: If, and only if, the lightweight fetch yields no evidence, the checker MAY fall back to a full, JavaScript-rendering browser engine (e.g., Playwright, Selenium) to analyze client-side rendered applications. This strategy should be configurable.

  - **Caching (RECOMMENDED)**: To improve performance, especially for repeated checks in CI environments, a compliant implementation SHOULD use a persistent, time-aware cache for HTTP responses.

  - **Defensive Filtering**: The crawler SHOULD filter out links to obvious non-identity assets (e.g., images, CSS, binary files) based on file extension or link `rel` attributes *before* adding them to the crawl queue.

### 7\. Scoring Function

The scoring function from the reference implementation is adopted, as it correctly aligns with the test vectors' intent.

```
score = 85 * S + 50 * W + 10 * I - P
where
  S = min(1, strong_count / 1.0)
  W = min(1, weak_count   / 2.0)      # Saturates at 2 weak signals for "medium"
  I = min(1, indirect_count / 5.0)
  P = penalties (defined as needed)
```

  - **Labels**: `score ≥ 80 → "high"`, `50–79 → "medium"`, `<50 → "low"`.

### 8\. API

The API signature is expanded to allow for runtime policy overrides.

```python
from naive_backlink import crawl_and_score, Result

res: Result = crawl_and_score(
    origin_url="https://pypi.org/project/foo/",
    # Overrides
    trusted_overrides=["https://example.com"],
    # Mode flags
    only_whitelist=False,
    only_rel_me=False, # If true, ignores other recognizers
)
```

### 9\. CLI

The CLI is specified with CI/automation as a primary use case.

```
# Crawl and print a human-readable summary
$ naive_backlink verify https://pypi.org/project/foo/

# Crawl and output the full evidence as a JSON object
$ naive_backlink crawl https://pypi.org/project/foo/ --json out.json
```

**Exit Codes**:

  - `0`: Success. Evidence was found (strong, weak, or indirect). This is a non-failure for CI usage even if only weak links are present.
  - `1`: Usage or internal error.
  - `100`: Completed successfully, but no backlinks of any kind were detected.

### 10\. Reference Implementation (RI)

The RI should be configurable via a `pyproject.toml` file with an expanded schema.

```toml
[tool.naive_backlink]
max_hops = 3
use_playwright_as_fallback = true
trusted = ["mastodon.social", "github.com"]
blacklist = ["google.com", "github.com/sponsors/*"]

# Recommended caching configuration
[tool.naive_backlink.cache]
enabled = true
directory = ".naive_backlink_cache"
expire_seconds = 86400 # 1 day

# Extensible Recognizer configuration
[tool.naive_backlink.recognizers]
"github.com" = { type = "css_selector", selector = "a[data-test-id='profile-website-link']", classification = "strong" }
"blog.example.com" = { type = "xpath", expression = "//channel/link/text()", classification = "weak" }
"api.example.com" = { type = "json_path", expression = "$.user.profileUrl", classification = "weak" }
```

### 11\. Test Vectors (Revised)

1.  **Strong**: `OP` ↔ `mastodon.social/@alice` with `rel="me"` → `score ~85 (high)`.
2.  **Weak (x2)**: `OP` ↔ `github.com/alice/blog` README + `OP` ↔ `alice.com` → `score ~50 (medium)`.
3.  **Indirect**: `OP` → `github.com/alice/foo` → `github.com/alice` → `OP` → `score ~10-20 (low)`.
4.  **Aggregator only**: `OP` ↔ `libraries.io/...` → `score 0 (low)` with potential penalty.

### 12\. Rationale

This revision shifts the PEP from a rigid, HTML-centric specification to a flexible framework. The introduction of the **Two-Stage Crawl Strategy** acknowledges the reality of the modern web without sacrificing performance. The **Recognizer Model** is the most significant change, making the tool adaptable to new platforms and content types via configuration alone, ensuring its long-term relevance. The adjustments to scoring and CLI exit codes reflect a maturity gained from a real-world implementation, prioritizing correctness and utility for automation.

### 13\. Revision History

  - **2025-10-16**:
      - Introduced the **Recognizer** model to support non-HTML content (JSON, XML) and CSS selectors.
      - Specified a **Two-Stage Crawl Strategy** (lightweight fetch with a JS-render fallback).
      - Added **Caching** as a recommended feature.
      - Updated the **Scoring Function** to `85*S + 50*W` to align with test vectors.
      - Revised **CLI exit codes** to be CI-friendly (`0` for any found evidence).
      - Expanded the `pyproject.toml` specification to include cache and recognizer configuration.