# Unit tests for the scoring function using pytest.

from __future__ import annotations

from naive_backlink.models import EvidenceRecord, LinkDetails, URLContext
from naive_backlink.scoring import calculate_score


# PEP Test Vector 1: Strong backlink should result in a high score.
def test_score_with_one_strong_signal():
    """
    Tests that a single strong backlink produces a 'high' score.
    Corresponds to PEP Test Vector #1.
    """
    evidence = [
        EvidenceRecord(
            id="e-backlink-001",
            kind="rel-me",
            source=URLContext(
                url="https://pypi.org/project/foo/", context="origin-page"
            ),
            target=URLContext(
                url="https://mastodon.social/@alice", context="candidate-page"
            ),
            link=LinkDetails(html='<a rel="me" href="...">', rel=["me"]),
            classification="strong",
            hops=1,
            trusted_surface=True,
        )
    ]
    score, label = calculate_score(evidence)
    assert score >= 80
    assert label == "high"


# PEP Test Vector 2: A few weak backlinks should result in a medium score.
def test_score_with_weak_signals():
    """
    Tests that weak backlinks produce a 'medium' score.
    Corresponds to PEP Test Vector #2.
    """
    evidence = [
        EvidenceRecord(
            id="e-1",
            kind="backlink",
            classification="weak",
            source=URLContext("", "origin-page"),
            target=URLContext("", "candidate-page"),
        ),
        EvidenceRecord(
            id="e-2",
            kind="backlink",
            classification="weak",
            source=URLContext("", "origin-page"),
            target=URLContext("", "candidate-page"),
        ),
    ]
    score, label = calculate_score(evidence)
    assert 50 <= score < 80
    assert label == "medium"


def test_score_with_no_evidence():
    """Tests that no evidence results in a score of 0 and a 'low' label."""
    score, label = calculate_score([])
    assert score == 0
    assert label == "low"
