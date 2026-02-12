"""Tests for TrustScore v0.1."""

import time
import pytest
from trustscore.score import (
    AgentProfile, Interaction, PeerEndorsement,
    compute_trust_score, _time_decay, _interaction_score,
    _endorsement_score, _attestation_score, _age_score,
)

NOW = 1739400000.0  # Fixed time for deterministic tests


def test_empty_profile():
    """New agent with no history should have near-zero trust."""
    profile = AgentProfile(agent_id="new-agent", created_at=NOW)
    result = compute_trust_score(profile, now=NOW)
    assert result["trust_score"] < 0.1
    assert result["components"]["interaction"] == 0.0
    assert result["components"]["endorsement"] == 0.0
    assert result["components"]["attestation"] == 0.0


def test_time_decay():
    """Decay should halve over HALF_LIFE."""
    from trustscore.score import HALF_LIFE
    decay = _time_decay(NOW - HALF_LIFE, now=NOW)
    assert abs(decay - 0.5) < 0.01


def test_perfect_interactions():
    """All successful interactions should give high interaction score."""
    interactions = [
        Interaction(timestamp=NOW - i * 3600, success=True)
        for i in range(10)
    ]
    score = _interaction_score(interactions, now=NOW)
    assert score > 0.95


def test_mixed_interactions():
    """50/50 interactions should give ~0.5 score."""
    interactions = [
        Interaction(timestamp=NOW - i * 3600, success=(i % 2 == 0))
        for i in range(20)
    ]
    score = _interaction_score(interactions, now=NOW)
    assert 0.35 < score < 0.65


def test_endorsement_from_trusted_peer():
    """Endorsement from highly-trusted peer should give high score."""
    endorsements = [
        PeerEndorsement(
            endorser_id="trusted-agent",
            endorser_trust=0.9,
            timestamp=NOW - 3600,
            strength=1.0,
        )
    ]
    score = _endorsement_score(endorsements, now=NOW)
    assert score > 0.8


def test_attestation_scaling():
    """More attestations = higher score, with diminishing returns."""
    s1 = _attestation_score(1, NOW, now=NOW)
    s5 = _attestation_score(5, NOW, now=NOW)
    s10 = _attestation_score(10, NOW, now=NOW)
    s100 = _attestation_score(100, NOW, now=NOW)
    
    assert s1 < s5 < s10
    # Diminishing returns: gap between 10 and 100 < gap between 1 and 10
    assert (s100 - s10) < (s10 - s1)


def test_age_score_new_vs_old():
    """Older accounts should have higher age score."""
    new = _age_score(NOW, now=NOW)  # just created
    month_old = _age_score(NOW - 30 * 86400, now=NOW)
    year_old = _age_score(NOW - 365 * 86400, now=NOW)
    
    assert new < month_old < year_old
    assert year_old > 0.9


def test_full_profile():
    """Established agent should have high trust score."""
    profile = AgentProfile(
        agent_id="established-agent",
        created_at=NOW - 90 * 86400,  # 90 days old
        interactions=[
            Interaction(timestamp=NOW - i * 3600, success=True)
            for i in range(20)
        ],
        endorsements=[
            PeerEndorsement("peer-1", 0.8, NOW - 86400, 0.9),
            PeerEndorsement("peer-2", 0.7, NOW - 3600, 0.8),
        ],
        attestation_count=8,
        last_attestation=NOW - 3600,
    )
    result = compute_trust_score(profile, now=NOW)
    assert result["trust_score"] > 0.7
    assert result["agent_id"] == "established-agent"
    assert "components" in result


def test_score_range():
    """Trust score should always be in [0, 1]."""
    # Extreme profile
    profile = AgentProfile(
        agent_id="extreme",
        created_at=NOW - 365 * 86400,
        interactions=[
            Interaction(timestamp=NOW, success=True, weight=100.0)
            for _ in range(100)
        ],
        endorsements=[
            PeerEndorsement(f"p-{i}", 1.0, NOW, 1.0)
            for i in range(50)
        ],
        attestation_count=1000,
        last_attestation=NOW,
    )
    result = compute_trust_score(profile, now=NOW)
    assert 0.0 <= result["trust_score"] <= 1.0
