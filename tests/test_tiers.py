"""Tests for Verification Tiers (Layer 3)."""

import time
import pytest
from trustscore.score import AgentProfile, Interaction, PeerEndorsement, compute_trust_score
from trustscore.tiers import (
    Tier, TierPolicy, TierRequirement, evaluate_tier, format_tier_grant,
    DEFAULT_THRESHOLDS,
)


NOW = 1700000000.0


def _make_profile(
    agent_id="agent-001",
    n_interactions=0,
    success_rate=1.0,
    n_endorsements=0,
    endorser_trust=0.8,
    attestations=0,
    age_days=60,
) -> AgentProfile:
    """Helper to create profiles with controlled parameters."""
    created = NOW - age_days * 86400
    interactions = [
        Interaction(
            timestamp=NOW - i * 3600,
            success=(i / max(n_interactions, 1)) < success_rate,
            weight=1.0,
        )
        for i in range(n_interactions)
    ]
    endorsements = [
        PeerEndorsement(
            endorser_id=f"peer-{i}",
            endorser_trust=endorser_trust,
            timestamp=NOW - i * 86400,
            strength=0.8,
        )
        for i in range(n_endorsements)
    ]
    return AgentProfile(
        agent_id=agent_id,
        created_at=created,
        interactions=interactions,
        endorsements=endorsements,
        attestation_count=attestations,
        last_attestation=NOW - 3600 if attestations > 0 else None,
    )


def _score(profile):
    result = compute_trust_score(profile, now=NOW)
    result["created_at"] = profile.created_at
    return result


class TestDefaultPolicy:
    def test_new_agent_is_unverified(self):
        profile = _make_profile(n_interactions=0, attestations=0, age_days=1)
        result = _score(profile)
        grant = evaluate_tier(result, TierPolicy.default("svc-1"))
        assert grant.granted_tier == Tier.UNVERIFIED

    def test_basic_tier_reachable(self):
        profile = _make_profile(n_interactions=10, attestations=2, age_days=30)
        result = _score(profile)
        grant = evaluate_tier(result, TierPolicy.default("svc-1"))
        assert grant.granted_tier.value in ("basic", "verified", "trusted", "sovereign")
        assert grant.trust_score >= 0.2

    def test_high_trust_agent(self):
        profile = _make_profile(
            n_interactions=100, success_rate=0.95,
            n_endorsements=10, endorser_trust=0.9,
            attestations=15, age_days=180,
        )
        result = _score(profile)
        grant = evaluate_tier(result, TierPolicy.default("svc-1"))
        assert grant.granted_tier in (Tier.TRUSTED, Tier.SOVEREIGN)
        assert grant.trust_score >= 0.6


class TestStrictPolicy:
    def test_strict_blocks_low_interactions(self):
        profile = _make_profile(n_interactions=3, attestations=0, age_days=5)
        result = _score(profile)
        grant = evaluate_tier(result, TierPolicy.strict("svc-strict"))
        assert grant.granted_tier in (Tier.UNVERIFIED, Tier.BASIC)

    def test_strict_verified_needs_components(self):
        profile = _make_profile(
            n_interactions=25, success_rate=0.9,
            n_endorsements=3, attestations=4, age_days=14,
        )
        result = _score(profile)
        grant = evaluate_tier(result, TierPolicy.strict("svc-strict"))
        # Should reach at least BASIC, maybe VERIFIED
        assert grant.granted_tier.value != "sovereign"

    def test_strict_sovereign_hard_to_reach(self):
        profile = _make_profile(
            n_interactions=50, success_rate=0.9,
            n_endorsements=5, attestations=5, age_days=30,
        )
        result = _score(profile)
        grant = evaluate_tier(result, TierPolicy.strict("svc-strict"))
        assert grant.granted_tier != Tier.SOVEREIGN


class TestNextTierGap:
    def test_gap_shows_what_is_missing(self):
        profile = _make_profile(n_interactions=2, attestations=0, age_days=5)
        result = _score(profile)
        grant = evaluate_tier(result, TierPolicy.default("svc-1"))
        if grant.next_tier:
            assert grant.next_tier_gap is not None
            assert len(grant.next_tier_gap) > 0

    def test_sovereign_has_no_next(self):
        profile = _make_profile(
            n_interactions=200, success_rate=0.99,
            n_endorsements=20, endorser_trust=0.95,
            attestations=20, age_days=365,
        )
        result = _score(profile)
        grant = evaluate_tier(result, TierPolicy.default("svc-1"))
        if grant.granted_tier == Tier.SOVEREIGN:
            assert grant.next_tier is None


class TestCustomPolicy:
    def test_custom_two_tier(self):
        """Service with only two tiers: unverified and trusted."""
        policy = TierPolicy(service_id="simple-svc")
        policy.tiers = {
            Tier.UNVERIFIED: TierRequirement(min_score=0.0),
            Tier.TRUSTED: TierRequirement(min_score=0.5, min_interactions=10),
        }
        
        # Low trust
        profile = _make_profile(n_interactions=2, age_days=5)
        result = _score(profile)
        grant = evaluate_tier(result, policy)
        assert grant.granted_tier == Tier.UNVERIFIED
        
        # High trust
        profile = _make_profile(
            n_interactions=50, success_rate=0.9,
            n_endorsements=5, attestations=5, age_days=60,
        )
        result = _score(profile)
        grant = evaluate_tier(result, policy)
        assert grant.granted_tier == Tier.TRUSTED


class TestFormatting:
    def test_format_includes_key_info(self):
        profile = _make_profile(n_interactions=10, attestations=2, age_days=30)
        result = _score(profile)
        grant = evaluate_tier(result, TierPolicy.default("svc-1"))
        text = format_tier_grant(grant)
        assert "agent-001" in text
        assert "svc-1" in text
        assert "Trust Score" in text
