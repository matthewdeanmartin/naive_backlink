# tests/test_link_logic.py
from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from naive_backlink.link_logic import (
    LogicConfig,
    normalize_url,
    extract_href_elements,
    detect_backlink_element,
    queue_candidates_from_origin,
    classify_backlink,
    make_evidence,
    _registrable_domain_or,   # private but deterministic enough for fallback tests
    _netloc,                  # private helper
    _is_same_domain_blocked,  # private helper; exercised for policy behavior
    is_fetchable_url,
)
from naive_backlink.models import URLContext, LinkDetails


# ---------- normalize_url / scheme/host handling ----------

@pytest.mark.parametrize(
    "inp, exp",
    [
        ("HTTP://EXAMPLE.COM/Path/#frag", "http://example.com/Path"),
        ("https://Example.com/", "https://example.com"),
        ("https://example.com/a/b/", "https://example.com/a/b"),
        ("https://example.com/", "https://example.com"),
        ("https://example.com", "https://example.com"),
    ],
)
def test_normalize_url_basic(inp, exp):
    assert normalize_url(inp) == exp


def test_normalize_url_malformed_returns_input():
    # urlparse will accept odd inputs; this checks we don't crash
    bad = "::::not_a_url###"
    assert normalize_url(bad) == "::::not_a_url"


# ---------- fetchability filter ----------

@pytest.mark.parametrize(
    "u, ok",
    [
        ("http://example.com", True),
        ("https://example.com/x", True),
        ("mailto:user@example.com", False),
        ("tel:+123456", False),
        ("javascript:alert(1)", False),
        ("data:text/html,hi", False),
        ("ftp://example.com/file", False),
        ("about:blank", False),
        ("", False),
    ],
)
def test_is_fetchable_url(u, ok):
    assert is_fetchable_url(u) is ok


# ---------- _netloc helper ----------

def test__netloc_extracts_host():
    assert _netloc("https://Sub.Example.com/a") == "sub.example.com"


# ---------- registrable domain helper ----------

def test__registrable_domain_or_fallback_strips_www_when_no_tldextract():
    # Behavior without tldextract: returns host minus a leading www.
    host = "www.example.com"
    assert _registrable_domain_or(host, fallback_to_host=True) == "example.com"


def test__registrable_domain_or_with_tldextract_if_available():
    # Deterministic only if tldextract is installed; skip otherwise.
    pytest.importorskip("tldextract")
    assert _registrable_domain_or("sub.example.co.uk") == "example.co.uk"


# ---------- same-domain policy gates ----------

@pytest.mark.parametrize(
    "policy,cand,orig,blocked",
    [
        ("follow", "a.example.com", "example.com", False),
        ("no-self-domain", "example.com", "example.com", True),
        ("no-self-domain", "a.example.com", "example.com", False),
        ("no-self-domain-or-subdomain", "example.com", "example.com", True),
        ("no-self-domain-or-subdomain", "a.example.com", "example.com", True),
        ("no-self-domain-or-subdomain", "other.com", "example.com", False),
    ],
)
def test__is_same_domain_blocked_naive(policy, cand, orig, blocked):
    cfg = LogicConfig(
        max_outlinks=10,
        trusted_domains=[],
        same_domain_policy=policy,
        use_registrable_domain=False,
    )
    assert _is_same_domain_blocked(cand, orig, cfg) is blocked


# @pytest.mark.skipif(pytest.importorskip.__self__ is None, reason="placeholder")
def test__is_same_domain_blocked_registrable_domain(monkeypatch):
    # Skip if tldextract missing
    tldextract = pytest.importorskip("tldextract")
    cfg = LogicConfig(
        max_outlinks=10,
        trusted_domains=[],
        same_domain_policy="no-self-domain-or-subdomain",
        use_registrable_domain=True,
    )
    # Registrable roots match -> blocked
    assert _is_same_domain_blocked("sub.example.co.uk", "example.co.uk", cfg) is True
    # Different roots -> not blocked
    assert _is_same_domain_blocked("news.bbc.co.uk", "example.co.uk", cfg) is False


# ---------- extract_href_elements ----------

def test_extract_href_elements_includes_a_and_link_only_with_href():
    html = """
    <html><head>
      <link rel="me" href="https://example.com/u/me">
      <link rel="stylesheet" href="/css/x.css">
      <link rel="preload"> <!-- no href -->
    </head><body>
      <a href="/one">one</a>
      <a>nope</a>
      <div href="/not-a-link">x</div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    els = extract_href_elements(soup)
    hrefs = [e.get("href") for e in els]
    assert hrefs == ['/one', 'https://example.com/u/me', '/css/x.css']


# ---------- detect_backlink_element ----------

def test_detect_backlink_element_matches_resolved_and_normalized():
    current = "https://site.example/path/page.html"
    origin = "https://origin.example/"
    html = """
    <a href="mailto:someone@origin.example">not real</a>
    <a href="//origin.example">proto-relative host</a>
    <a href="https://ORIGIN.example">exact strong candidate</a>
    """
    soup = BeautifulSoup(html, "html.parser")
    tag = detect_backlink_element(current_url=current, origin_url=origin, elements=soup.find_all(["a", "link"]))
    assert tag is not None
    assert tag.get("href") in {"//origin.example", "https://ORIGIN.example"}


def test_detect_backlink_element_ignores_non_fetchable():
    current = "https://site.example/"
    origin = "https://origin.example/"
    html = """
      <a href="mailto:admin@origin.example">no</a>
      <a href="javascript:void(0)">no</a>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert detect_backlink_element(current, origin, soup.find_all("a")) is None


# ---------- queue_candidates_from_origin (no network) ----------

def test_queue_candidates_from_origin_skips_non_fetchable_and_duplicates_and_visited():
    origin = "https://origin.example/"
    current = origin
    html = """
      <a href="mailto:me@x">ignore</a>
      <a href="/a">rel a</a>
      <a href="https://other.example/b">abs b</a>
      <a href="/a">dup a</a>
      <link rel="me" href="https://trusted.example/u/me">profile</link>
    """
    soup = BeautifulSoup(html, "html.parser")
    cfg = LogicConfig(
        max_outlinks=10,
        trusted_domains=[],
        same_domain_policy="no-self-domain-or-subdomain",
        use_registrable_domain=False,
    )
    # Pretend we already queued "/a"
    already = ["https://origin.example/a"]
    visited = ["https://origin.example/seen"]

    out = queue_candidates_from_origin(
        current_url=current,
        origin_url=origin,
        elements=soup.find_all(["a", "link"]),
        cfg=cfg,
        already_queued=already,
        visited=visited,
    )
    # Should include other.example/b and trusted.example/u/me; not include mailto or duplicate /a
    assert out == [
        "https://other.example/b",
        "https://trusted.example/u/me",
    ]


def test_queue_candidates_from_origin_respects_max_outlinks():
    origin = "https://o.example/"
    current = origin
    html = """
      <a href="/a1">a1</a><a href="/a2">a2</a><a href="/a3">a3</a>
      <a href="/a4">a4</a><a href="/a5">a5</a>
    """
    soup = BeautifulSoup(html, "html.parser")
    cfg = LogicConfig(
        max_outlinks=3,
        trusted_domains=[],
        same_domain_policy="follow",
        use_registrable_domain=False,
    )
    out = queue_candidates_from_origin(
        current_url=current,
        origin_url=origin,
        elements=soup.find_all("a"),
        cfg=cfg,
        already_queued=[],
        visited=[],
    )
    assert len(out) == 3
    assert out == [
        "https://o.example/a1",
        "https://o.example/a2",
        "https://o.example/a3",
    ]


def test_queue_candidates_from_origin_policy_blocks_self_and_subdomains():
    origin = "https://origin.example/"
    current = origin
    html = """
      <a href="https://origin.example/self">self</a>
      <a href="https://sub.origin.example/child">child</a>
      <a href="https://other.example/x">other</a>
    """
    soup = BeautifulSoup(html, "html.parser")
    cfg = LogicConfig(
        max_outlinks=10,
        trusted_domains=[],
        same_domain_policy="no-self-domain-or-subdomain",
        use_registrable_domain=False,
    )
    out = queue_candidates_from_origin(
        current_url=current,
        origin_url=origin,
        elements=soup.find_all("a"),
        cfg=cfg,
        already_queued=[],
        visited=[],
    )
    assert out == ["https://other.example/x"]


# ---------- classify_backlink / make_evidence ----------

def _soup_tag(html: str):
    return BeautifulSoup(html, "html.parser").find(True)

def test_classify_backlink_rel_me_and_trusted_surface():
    tag = _soup_tag('<a rel="me nofollow" href="https://origin.example/">me</a>')
    cfg = LogicConfig(
        max_outlinks=10,
        trusted_domains=["trusted.example"],  # substring match on source host
        same_domain_policy="follow",
        use_registrable_domain=False,
    )
    kind, classification, trusted_surface = classify_backlink(tag, "https://sub.trusted.example/page", cfg)
    assert kind == "rel-me"
    assert classification == "strong"
    assert trusted_surface is True


def test_make_evidence_fields_populated():
    tag = _soup_tag('<link rel="me" href="https://origin.example/">')
    cfg = LogicConfig(max_outlinks=10, trusted_domains=[], same_domain_policy="follow", use_registrable_domain=False)
    ev = make_evidence(
        source_url="https://candidate.example/p",
        origin_url="https://origin.example",
        hops=2,
        tag=tag,
        cfg=cfg,
        ordinal=1,
    )
    assert ev.id == "e-backlink-1"
    assert ev.kind in {"rel-me", "backlink"}
    assert ev.source == URLContext(url="https://origin.example", context="origin-page")
    assert ev.target.url == "https://candidate.example/p"
    assert isinstance(ev.link, LinkDetails)
    assert "me" in (ev.link.rel or [])
    assert ev.hops == 2
