import pytest

from naive_backlink.models import EvidenceRecord, URLContext
from naive_backlink.scoring import calculate_score

# --- helpers ---------------------------------------------------------------


def _ev(classification: str, idx: int = 1) -> EvidenceRecord:
    """
    Build a minimal EvidenceRecord with the requested classification.
    kind/context/link fields are not used by scoring; keep them simple.
    """
    return EvidenceRecord(
        id=f"e-{classification}-{idx}",
        kind="backlink",
        source=URLContext(url="https://origin.example", context="origin-page"),
        target=URLContext(url=f"https://t{idx}.example", context="candidate-page"),
        classification=classification,  # "strong" | "weak" | "indirect"
        hops=1,
    )


# --- tests ----------------------------------------------------------------


def test_empty_evidence_scores_low():
    score, label = calculate_score([])
    assert score == 0
    assert label == "low"


def test_strong_alone_scores_high():
    ev = [_ev("strong")]
    score, label = calculate_score(ev)
    # s = 1.0 -> 85 points
    assert score == 85
    assert label == "high"


@pytest.mark.parametrize(
    "weak_count, expected_score, expected_label",
    [
        (1, 25, "low"),  # w = 0.5 -> 25
        (2, 50, "medium"),  # w = 1.0 -> 50 (boundary)
        (3, 50, "medium"),  # saturation at 2
        (10, 50, "medium"),  # still saturated
    ],
)
def test_weak_only_progression(weak_count, expected_score, expected_label):
    ev = [_ev("weak", i + 1) for i in range(weak_count)]
    score, label = calculate_score(ev)
    assert score == expected_score
    assert label == expected_label


@pytest.mark.parametrize(
    "indirect_count, expected_score, expected_label",
    [
        (1, 2, "low"),  # i = 0.2 -> 2
        (4, 8, "low"),  # i = 0.8 -> 8
        (5, 10, "low"),  # i = 1.0 -> 10 (saturation)
        (12, 10, "low"),  # still saturated
    ],
)
def test_indirect_only_progression(indirect_count, expected_score, expected_label):
    ev = [_ev("indirect", i + 1) for i in range(indirect_count)]
    score, label = calculate_score(ev)
    assert score == expected_score
    assert label == expected_label


def test_strong_plus_weak_saturates_and_clamps_to_100():
    # strong (85) + three weak (w=1.0 -> +50) => 135 -> clamped to 100
    ev = [_ev("strong")] + [_ev("weak", i + 1) for i in range(3)]
    score, label = calculate_score(ev)
    assert score == 100
    assert label == "high"


def test_strong_plus_indirect_adds_small_bonus():
    # strong (85) + 5 indirect (i=1.0 -> +10) => 95
    ev = [_ev("strong")] + [_ev("indirect", i + 1) for i in range(5)]
    score, label = calculate_score(ev)
    assert score == 95
    assert label == "high"


def test_two_weak_plus_indirect_is_medium_not_high():
    # two weak -> 50, + five indirect -> +10 => 60 (medium)
    ev = [_ev("weak", 1), _ev("weak", 2)] + [_ev("indirect", i + 1) for i in range(5)]
    score, label = calculate_score(ev)
    assert score == 60
    assert label == "medium"


def test_one_weak_plus_indirect_stays_low():
    # one weak -> 25, + five indirect -> +10 => 35 (low)
    ev = [_ev("weak", 1)] + [_ev("indirect", i + 1) for i in range(5)]
    score, label = calculate_score(ev)
    assert score == 35
    assert label == "low"
