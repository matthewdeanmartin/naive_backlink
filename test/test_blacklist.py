import pytest
from bs4 import BeautifulSoup

from naive_backlink.link_logic import (
    LogicConfig,
    is_blacklisted,
    normalize_url,
    queue_candidates_from_origin,
    queue_candidates_from_pivot,
)

# Base blacklist copied from api._load_config() docstring semantics
BASE_PATTERNS = [
    "joinmastodon.org/*",
    "*.joinmastodon.org/*",
    "github.com/sponsors/*",
    "github.com/trending/*",
    "github.com/readme/*",
    "github.com/topics/*",
    "github.com/collections/*",
    "github.com/partners/*",
    "github.com/solutions",
    "github.com/solutions/*",
    "github.com/site",
    "github.com/site/*",
    "github.com/features",
    "github.com/features/*",
    "github.com/enterprise",
    "github.com/enterprise/*",
    "github.com/resources",
    "github.com/resources/*",
    "github.com/marketplace",
    "skills.github.com",
    "*.stackoverflow.co/*",
    "stackoverflow.co",
    "stackoverflow.co/*",
    "stackoverflow.blog*",
    "api.stackexchange.com",
    "data.stackexchange.com",
    "stackoverflow.com/users/signup*",
    "*.forem.com",
    "twitter.com/*",
    "x.com/*",
    "linkedin.com/*",
    "reddit.com/*",
]

CFG = LogicConfig(
    max_outlinks=50,
    trusted_domains=[],
    same_domain_policy="no-self-domain-or-subdomain",
    use_registrable_domain=False,
    blacklist_patterns=BASE_PATTERNS,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        # domain-wide rule with /* suffix
        ("https://joinmastodon.org", True),
        ("https://joinmastodon.org/servers", True),
        ("https://news.joinmastodon.org", True),  # via *.joinmastodon.org/*
        ("https://docs.joinmastodon.org/admin/config", True),
        # github “attractive nuisances”
        ("https://github.com/sponsors", True),
        ("https://github.com/sponsors/pypa", True),
        ("https://github.com/trending/python?since=daily", True),
        ("https://github.com/features/code-security", True),
        ("https://github.com/resources/case-studies", True),
        ("https://github.com/marketplace", True),
        # NOT blacklisted: a normal user/org repo page
        ("https://github.com/pypa/pip", False),
        # stackoverflow.*
        ("https://stackoverflow.co/company", True),
        ("https://meta.stackoverflow.co/", True),
        ("https://stackoverflow.blog/inside-stack/", True),
        ("https://api.stackexchange.com/2.3/questions", True),
        # social anti-bot
        ("https://x.com/someuser/status/123", True),
        ("https://twitter.com/abc", True),
        ("https://linkedin.com/in/matthewdeanmartin", True),
        ("https://reddit.com/r/something", True),
        # not blacklisted
        ("https://example.org/about", False),
        ("https://pypi.org/project/requests/", False),
    ],
)
def test_is_blacklisted_matrix(url, expected):
    assert is_blacklisted(url, CFG) is expected


def test_queue_candidates_from_origin_respects_blacklist():
    origin = "https://origin.example/"
    html = """
    <a href="https://github.com/sponsors">GH sponsors</a>
    <a href="https://github.com/pypa/pip">pip</a>
    <link rel="me" href="https://joinmastodon.org/servers"/>
    """
    soup = BeautifulSoup(html, "html.parser")
    out = queue_candidates_from_origin(
        current_url=origin,
        origin_url=origin,
        elements=soup.find_all(True),
        cfg=CFG,
        already_queued=[],
        visited=[],
    )
    # blacklist removes sponsors and joinmastodon entries
    assert normalize_url("https://github.com/pypa/pip") in out
    assert all("sponsors" not in u for u in out)
    assert all("joinmastodon.org" not in u for u in out)


def test_queue_candidates_from_pivot_respects_blacklist_and_origin_exclusion():
    origin = "https://a.example/"
    pivot = "https://b.example/page"
    html = """
    <a href="https://x.com/someuser">blacklisted social</a>
    <a href="https://a.example/profile">goes back to origin host (should skip here)</a>
    <a href="https://c.example/page">neighbor ok</a>
    """
    soup = BeautifulSoup(html, "html.parser")
    out = queue_candidates_from_pivot(
        current_url=pivot,
        pivot_url=pivot,
        origin_url=origin,
        elements=soup.find_all(True),
        cfg=CFG,
        already_queued=[],
        visited=[],
    )
    assert normalize_url("https://c.example/page") in out
    # ensure neither blacklisted nor origin-host link is present
    assert all("x.com" not in u for u in out)
    assert all("a.example" not in u for u in out)
