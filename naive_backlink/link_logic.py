# naive_backlink/link_logic.py
from __future__ import annotations

import fnmatch
import logging  # Added logging
import os
from dataclasses import dataclass
from typing import Iterable, List, Literal
from urllib.parse import urljoin, urlparse

import tldextract  # optional dependency
from bs4 import BeautifulSoup, Tag

from naive_backlink.models import EvidenceRecord, LinkDetails, URLContext

log = logging.getLogger(__name__)  # Added logger

SameDomainPolicy = Literal["follow", "no-self-domain", "no-self-domain-or-subdomain"]

# Add near top
EXTENSION_DENYLIST = {
    # images
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".svg",
    ".avif",
    # video/audio
    ".mp4",
    ".m4v",
    ".mov",
    ".webm",
    ".ogg",
    ".ogv",
    ".mp3",
    ".wav",
    ".flac",
    ".aac",
    # docs/binaries/archives
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".exe",
    ".msi",
    ".dmg",
    ".iso",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    # styles/scripts (rarely identity pages)
    ".css",
    ".js",
    ".mjs",
    ".map",
}

# rel values that indicate assets, not pages
NON_HTML_REL = {
    "icon",
    "shortcut icon",
    "apple-touch-icon",
    "mask-icon",
    "manifest",
    "preload",
    "prefetch",
    "dns-prefetch",
    "modulepreload",
    "stylesheet",  # we don't crawl CSS
}


ALLOWED_SCHEMES = {"http", "https"}


def _path_ext(u: str) -> str:
    try:
        p = urlparse(u)
        # strip query/fragment; use os.path splitext on the path
        _, ext = os.path.splitext(p.path.lower())
        return ext
    except Exception:
        return ""


def is_probably_html_url(u: str) -> bool:
    """
    Heuristic: http/https AND path extension NOT in a denylist.
    Allows extensionless paths and 'clean URLs'. Blocks obvious assets (png, ico, etc.).
    """
    if not is_fetchable_url(u):
        return False
    ext = _path_ext(u)
    if ext and ext in EXTENSION_DENYLIST:
        return False
    return True


def _rel_list(tag: Tag) -> List[str]:
    rel = tag.get("rel", None)
    if not rel:
        return []
    if isinstance(rel, str):
        string_rel = rel.split()
        [r.strip().lower() for r in string_rel if isinstance(r, str)]

    return [r.strip().lower() for r in rel if isinstance(r, str)]


def _is_asset_rel(tag: Tag) -> bool:
    rels = set(_rel_list(tag))
    # treat any intersection as asset-ish
    return any(r in NON_HTML_REL for r in rels)


def _scheme(u: str) -> str:
    try:
        return urlparse(u).scheme.lower()
    except Exception:
        return ""


def is_fetchable_url(u: str) -> bool:
    """Return True iff URL uses a scheme we can actually fetch (http/https)."""
    return _scheme(u) in ALLOWED_SCHEMES


@dataclass(frozen=True)
class LogicConfig:
    """Updated LogicConfig to hold new policy settings."""

    max_outlinks: int
    trusted_domains: List[str]
    same_domain_policy: SameDomainPolicy = "no-self-domain"
    # Optional: if True and tldextract is installed, use registrable domain to
    # decide subdomain relationships; otherwise fall back to naive suffix match.
    use_registrable_domain: bool = False
    # Lists
    blacklist_patterns: List[str] | None = None
    whitelist_patterns: List[str] | None = None
    # Modes
    only_whitelist: bool = False


def _host_and_hostpath(u: str) -> tuple[str, str]:
    """
    Returns (host, host+path) both lowercased and normalized:
      ("github.com", "github.com/sponsors?page=2" -> "github.com/sponsors")
    Query/fragment are ignored for matching.
    """
    try:
        p = urlparse(normalize_url(u))
        host = (p.netloc or "").lower()
        path = (p.path or "").lstrip("/").lower()
        hostpath = f"{host}/{path}" if path else host  # "host" alone if no path
        return host, hostpath
    except Exception:
        return "", ""


# def is_blacklisted(u: str, cfg: LogicConfig) -> bool:
#     """
#     Match against blacklist patterns using fnmatch (supports '*' and '?').
#
#     Patterns are compared against:
#       1) host          e.g., 'joinmastodon.org'
#       2) host+path     e.g., 'github.com/sponsors', 'github.com/solutions/xyz'
#     Also try with an added '/*' suffix normalization for domain-wide patterns.
#
#     Patterns are compared against multiple normalized variants of the URL:
#       - host (e.g., 'github.com')
#       - host + '/' and host + '/*'
#       - host + path (e.g., 'github.com/sponsors')
#       - host + path + '/' and host + path + '/*'
#     This ensures that a pattern like 'github.com/sponsors/*' matches both
#     'https://github.com/sponsors' and deeper paths such as
#     'https://github.com/sponsors/pypa'.
#     """
#     patterns = (cfg.blacklist_patterns or [])
#     if not patterns:
#         return False
#
#     host, hostpath = _host_and_hostpath(u)
#     if not host:
#         return False  # Can't match on an empty host
#
#     # Build candidate forms to test against
#     candidates = {
#         host,
#         f"{host}/",
#         f"{host}/*",
#         hostpath,
#         f"{hostpath}/",
#         f"{hostpath}/*",
#     }
#
#     for pat in patterns:
#         p = pat.lower().strip()
#         # direct fnmatch against all candidates
#         if any(fnmatch.fnmatchcase(c, p) for c in candidates):
#             return True
#
#         # handle leading '*.' wildcard for subdomain rules like '*.example.com/*'
#         if p.startswith("*."):
#             suffix = p[2:].replace("/*", "").rstrip("/")
#             # require that host is a subdomain of suffix, not equal to it
#             if host.endswith(suffix) and host != suffix:
#                 return True
#
#     return False


def _match_url_against_patterns(u: str, patterns: list[str]) -> bool:
    """Generic fnmatch helper used by is_blacklisted and is_whitelisted."""
    if not patterns:
        return False

    host, hostpath = _host_and_hostpath(u)
    if not host:
        return False  # Can't match on an empty host

    # Build candidate forms to test against
    candidates = {
        host,
        f"{host}/",
        f"{host}/*",
        hostpath,
        f"{hostpath}/",
        f"{hostpath}/*",
    }

    for pat in patterns:
        p = pat.lower().strip()
        # direct fnmatch against all candidates
        if any(fnmatch.fnmatchcase(c, p) for c in candidates):
            return True

        # handle leading '*.' wildcard for subdomain rules like '*.example.com/*'
        if p.startswith("*."):
            suffix = p[2:].replace("/*", "").rstrip("/")
            # require that host is a subdomain of suffix, not equal to it
            if host.endswith(suffix) and host != suffix:
                return True

    return False


def is_blacklisted(u: str, cfg: LogicConfig) -> bool:
    """Uses the generic matcher against the blacklist."""
    return _match_url_against_patterns(u, cfg.blacklist_patterns or [])


def is_whitelisted(u: str, cfg: LogicConfig) -> bool:
    """Uses the generic matcher against the whitelist."""
    return _match_url_against_patterns(u, cfg.whitelist_patterns or [])


# ---------- URL helpers ----------


def normalize_url(url: str) -> str:
    """
    Normalize scheme/netloc to lowercase, drop fragment, and trim trailing slash.
    - Trim trailing "/" for *any* path, including root ("/").
    - Robust to malformed URLs (returns input on failure).
    """
    try:
        p = urlparse(url)
        # Normalize path:
        # - if root "/", make it empty
        # - else strip a single trailing "/" (but leave "/" inside the path)
        if p.path == "/":
            path = ""
        elif p.path.endswith("/") and len(p.path) > 1:
            path = p.path[:-1]
        else:
            path = p.path

        return p._replace(
            scheme=(p.scheme or "").lower(),
            netloc=(p.netloc or "").lower(),
            path=path,
            fragment="",
        ).geturl()
    except Exception:
        return url


def _netloc(host_url: str) -> str:
    return urlparse(host_url).netloc.lower()


def _registrable_domain_or(host: str, fallback_to_host: bool = True) -> str:
    """
    Returns eTLD+1 if tldextract is available and host looks valid.
    Falls back to host (minus a leading 'www.') if not.
    """
    try:
        ext = tldextract.extract(host)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}".lower()
    except Exception:
        pass  # no qa # nosec
    if fallback_to_host:
        return host[4:] if host.startswith("www.") else host
    return host


def _is_same_domain_blocked(candidate: str, origin: str, cfg: LogicConfig) -> bool:
    """
    Decide whether to block candidate based on same-domain policy.
    """
    if cfg.same_domain_policy == "follow":
        return False

    cand = candidate
    orig = origin

    if cfg.same_domain_policy == "no-self-domain":
        return cand == orig

    # "no-self-domain-or-subdomain"
    if cfg.use_registrable_domain:
        c_root = _registrable_domain_or(cand)
        o_root = _registrable_domain_or(orig)
        # block if registrable roots match
        return c_root == o_root
    else:
        # naive: block exact host or any child subdomain of origin host
        return cand == orig or cand.endswith("." + orig)


# ---------- Link extraction & filtering ----------


def extract_href_elements(soup: BeautifulSoup) -> List[Tag]:
    """
    Return all elements with href among the set {<a>, <link>}.
    This supports Mastodon and other sites that expose identity via <link>.
    """
    anchors = soup.find_all("a", href=True)
    links = soup.find_all("link", href=True)
    # Maintain document order as best-effort by concatenation; strict order
    # isn’t required for correctness (we only need presence).
    return list(anchors) + list(links)


def queue_candidates_from_origin(
    current_url: str,
    origin_url: str,
    elements: Iterable[Tag],
    cfg: LogicConfig,
    already_queued: Iterable[str],
    visited: Iterable[str],
) -> List[str]:
    """
    From the origin page, choose outbound candidate URLs to crawl next hop.
    Considers both <a href> and <link href>.

    Applies blacklist and (if enabled) whitelist logic.
    """
    out: List[str] = []
    # origin_domain = urlparse(origin_url).netloc

    queued_set = set(already_queued)
    visited_set = set(visited)

    origin_host = _netloc(origin_url)

    for el in elements:
        if len(out) >= cfg.max_outlinks:
            break
        href = el.get("href")
        if not href:
            continue

        # Skip obvious non-HTML assets by rel
        if _is_asset_rel(el):
            continue

        resolved = urljoin(current_url, href)  # type: ignore[arg-type,type-var]
        norm = normalize_url(resolved)  # type: ignore[arg-type]

        # only follow http/https
        if not is_fetchable_url(norm):
            continue

        # --- NEW: Whitelist Mode Check ---
        if cfg.only_whitelist and not is_whitelisted(norm, cfg):
            log.debug("[Whitelist Mode] Skipping non-whitelisted URL: %s", norm)
            continue

        # --- Blacklist Mode Check (default) ---
        if not cfg.only_whitelist and is_blacklisted(norm, cfg):
            log.debug("[Blacklist Mode] Skipping blacklisted URL: %s", norm)
            continue

        # Only follow likely-HTML targets (blocks .png/.ico/.svg/... before GET)
        if not is_probably_html_url(resolved):  # type: ignore[arg-type]
            continue

        cand_host = _netloc(norm)

        # same-domain policy gate
        if _is_same_domain_blocked(cand_host, origin_host, cfg):
            continue

        if norm in visited_set or norm in queued_set or norm in out:
            continue

        out.append(norm)

    return out


def queue_candidates_from_pivot(
    current_url: str,
    pivot_url: str,
    origin_url: str,
    elements: Iterable[Tag],
    cfg: LogicConfig,
    already_queued: Iterable[str],
    visited: Iterable[str],
) -> List[str]:
    """
    Select pivot→neighbor candidates (B → C) from a non-origin page.
    Constraints:
      - http/https only
      - exclude origin URL/host (we already tested B ↔ A separately)
      - dedupe against visited/queued
      - respect max_outlinks
      - allow same-domain as pivot; the "no-self-domain*" policy is relative to ORIGIN,
        not the pivot (keeps exploration focused on distinct surfaces from A).

    Applies blacklist and (if enabled) whitelist logic.
    """
    out: List[str] = []
    queued_set = set(already_queued)
    visited_set = set(visited)
    origin_host = _netloc(origin_url)

    for el in elements:
        if len(out) >= cfg.max_outlinks:
            break
        href = el.get("href")
        if not href:
            continue
        if _is_asset_rel(el):
            continue
        resolved = normalize_url(urljoin(current_url, href))  # type: ignore[arg-type,type-var]
        if not is_fetchable_url(resolved):
            continue

        # --- NEW: Whitelist Mode Check ---
        if cfg.only_whitelist and not is_whitelisted(resolved, cfg):
            log.debug("[Whitelist Mode] Skipping non-whitelisted URL: %s", resolved)
            continue

        # --- Blacklist Mode Check (default) ---
        if not cfg.only_whitelist and is_blacklisted(resolved, cfg):
            log.debug("[Blacklist Mode] Skipping blacklisted URL: %s", resolved)
            continue
        if not is_probably_html_url(resolved):
            continue
        if resolved == origin_url or _netloc(resolved) == origin_host:
            continue  # do not chase back into A here
        if resolved in visited_set or resolved in queued_set or resolved in out:
            continue
        out.append(resolved)
    return out


# ---------- Backlink detection & classification ----------


def detect_backlink_element(
    current_url: str,
    origin_url: str,
    elements: Iterable[Tag],
) -> Tag | None:
    """
    Return the first tag (either <a> or <link>) on current_url that links back to origin_url.
    """
    norm_origin = normalize_url(origin_url)
    for el in elements:
        href = el.get("href")
        if not href:
            continue
        resolved = normalize_url(urljoin(current_url, href))  # type: ignore[arg-type,type-var]

        # ignore non-fetchable links (mailto:, tel:, javascript:, data:, etc.)
        if not is_fetchable_url(resolved):
            continue

        if resolved == norm_origin:
            return el
    return None


def classify_backlink(
    tag: Tag, source_url: str, cfg: LogicConfig
) -> tuple[str, str, bool]:
    """
    Returns (kind, classification, trusted_surface).
    - classification: 'strong' iff rel~="me" (works for both <a> and <link>)
    - kind: 'rel-me' when strong, otherwise 'backlink'
    - trusted_surface: domain substring match against cfg.trusted_domains
    """
    rel = _rel_list(tag)
    is_strong = "me" in rel
    kind = "rel-me" if is_strong else "backlink"
    classification = "strong" if is_strong else "weak"

    source_domain = _netloc(source_url)
    trusted_surface = any(d in source_domain for d in (cfg.trusted_domains or []))
    return kind, classification, trusted_surface


def make_evidence(
    source_url: str,
    origin_url: str,
    hops: int,
    tag: Tag,
    cfg: LogicConfig,
    ordinal: int,
) -> EvidenceRecord:
    kind, classification, trusted_surface = classify_backlink(tag, source_url, cfg)
    rel_vals = _rel_list(tag)
    return EvidenceRecord(
        id=f"e-backlink-{ordinal}",
        kind=kind,  # type: ignore[arg-type]
        source=URLContext(url=normalize_url(origin_url), context="origin-page"),
        target=URLContext(url=normalize_url(source_url), context="candidate-page"),
        link=LinkDetails(
            html=str(tag),
            rel=rel_vals,
            nofollow=(
                "nofollow" in rel_vals
            ),  # applies if present on either <a> or <link>
        ),
        classification=classification,  # type: ignore[arg-type]
        hops=hops,
        trusted_surface=trusted_surface,
    )


def make_indirect_evidence(
    origin_url: str,
    pivot_url: str,
    neighbor_url: str,
    hops: int,
    ordinal: int,
) -> EvidenceRecord:
    """
    Record A ↔ B ↔ C where:
      - A(origin) ↔ B(direct mutual)
      - B ↔ C (mutual)
    Classification = 'indirect'. Kind kept as 'backlink' for scoring simplicity.
    """
    return EvidenceRecord(
        id=f"e-indirect-{ordinal}",
        kind="backlink",
        source=URLContext(url=normalize_url(origin_url), context="origin-page"),
        target=URLContext(url=normalize_url(neighbor_url), context="candidate-page"),
        link=None,
        classification="indirect",
        hops=hops,
        trusted_surface=False,
        notes=f"INDIRECT via pivot={normalize_url(pivot_url)} chain={normalize_url(origin_url)}<->{normalize_url(pivot_url)}<->{normalize_url(neighbor_url)}",
    )
