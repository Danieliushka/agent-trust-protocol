"""Tests for A2A Trust Extension — Layer 4."""

import json
import time

from trustscore.score import AgentProfile, Interaction, PeerEndorsement, compute_trust_score
from trustscore.tiers import Tier, TierPolicy, evaluate_tier
from trustscore.a2a import (
    TrustAgentCard,
    TrustVerifier,
    TrustGatekeeper,
    VerificationResult,
    GatekeeperDecision,
    trust_card_to_json,
    trust_card_from_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rich_profile(agent_id: str = "agent:alice", now: float = None) -> AgentProfile:
    """Profile with enough history to get a decent score."""
    now = now or time.time()
    interactions = [
        Interaction(timestamp=now - i * 3600, success=True, weight=1.0, context=f"task-{i}")
        for i in range(10)
    ]
    endorsements = [
        PeerEndorsement(
            endorser_id=f"agent:peer-{i}",
            endorser_trust=0.7,
            timestamp=now - i * 7200,
            strength=0.8,
        )
        for i in range(3)
    ]
    return AgentProfile(
        agent_id=agent_id,
        created_at=now - 90 * 86400,
        interactions=interactions,
        endorsements=endorsements,
        attestation_count=5,
        last_attestation=now - 3600,
    )


def _empty_profile(agent_id: str = "agent:nobody") -> AgentProfile:
    return AgentProfile(agent_id=agent_id)


# ---------------------------------------------------------------------------
# TrustAgentCard tests
# ---------------------------------------------------------------------------

class TestTrustAgentCard:
    def test_create_minimal(self):
        card = TrustAgentCard(agent_id="agent:x")
        assert card.agent_id == "agent:x"
        assert card.trust_score is None
        assert card.tier is None

    def test_from_profile(self):
        now = time.time()
        profile = _rich_profile(now=now)
        policy = TierPolicy.default("svc:test")
        card = TrustAgentCard.from_profile(
            profile, name="Alice", tier_policy=policy, now=now,
        )
        assert card.trust_score is not None
        assert card.trust_score > 0
        assert card.tier is not None
        assert card.attestation_count == 5
        assert card.name == "Alice"

    def test_from_profile_no_policy(self):
        now = time.time()
        profile = _rich_profile(now=now)
        card = TrustAgentCard.from_profile(profile, now=now)
        assert card.trust_score is not None
        assert card.tier is None  # no policy → no tier

    def test_to_a2a_extension(self):
        now = time.time()
        card = TrustAgentCard.from_profile(_rich_profile(now=now), now=now)
        ext = card.to_a2a_extension()
        assert "trust_protocol" in ext
        assert "score" in ext["trust_protocol"]
        assert "attestation_count" in ext["trust_protocol"]


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_dict_roundtrip(self):
        now = time.time()
        card = TrustAgentCard.from_profile(
            _rich_profile(now=now),
            name="Alice",
            capabilities=["code_review", "deploy"],
            tier_policy=TierPolicy.default("svc:x"),
            now=now,
        )
        d = card.to_dict()
        restored = TrustAgentCard.from_dict(d)

        assert restored.agent_id == card.agent_id
        assert restored.trust_score == card.trust_score
        assert restored.tier == card.tier
        assert restored.capabilities == card.capabilities

    def test_json_roundtrip(self):
        now = time.time()
        card = TrustAgentCard.from_profile(_rich_profile(now=now), now=now)
        j = trust_card_to_json(card)
        restored = trust_card_from_json(j)
        assert restored.agent_id == card.agent_id
        assert restored.trust_score == card.trust_score

    def test_json_includes_profile_when_requested(self):
        now = time.time()
        card = TrustAgentCard.from_profile(_rich_profile(now=now), now=now)
        d = card.to_dict(include_profile=True)
        assert "profile" in d
        assert d["profile"]["agent_id"] == card.agent_id

    def test_json_is_valid(self):
        card = TrustAgentCard(agent_id="agent:z", trust_score=0.5, tier=Tier.BASIC)
        parsed = json.loads(card.to_json())
        assert parsed["trust"]["tier"] == "basic"


# ---------------------------------------------------------------------------
# TrustVerifier
# ---------------------------------------------------------------------------

class TestTrustVerifier:
    def test_pass_all(self):
        card = TrustAgentCard(
            agent_id="agent:a", trust_score=0.6, tier=Tier.VERIFIED,
            attestation_count=5, issued_at=time.time(),
        )
        v = TrustVerifier(min_score=0.3, min_tier=Tier.BASIC, min_attestations=2)
        report = v.verify(card)
        assert report.passed

    def test_fail_score(self):
        card = TrustAgentCard(agent_id="agent:a", trust_score=0.1, tier=Tier.BASIC)
        v = TrustVerifier(min_score=0.5)
        report = v.verify(card)
        assert not report.passed
        assert report.result == VerificationResult.FAIL_SCORE

    def test_fail_tier(self):
        card = TrustAgentCard(agent_id="agent:a", trust_score=0.8, tier=Tier.BASIC)
        v = TrustVerifier(min_tier=Tier.TRUSTED)
        report = v.verify(card)
        assert not report.passed
        assert report.result == VerificationResult.FAIL_TIER

    def test_fail_attestations(self):
        card = TrustAgentCard(agent_id="agent:a", trust_score=0.5, attestation_count=1)
        v = TrustVerifier(min_attestations=5)
        report = v.verify(card)
        assert report.result == VerificationResult.FAIL_ATTESTATIONS

    def test_fail_expired(self):
        card = TrustAgentCard(agent_id="agent:a", trust_score=0.5, issued_at=1000.0)
        v = TrustVerifier(max_card_age=3600)
        report = v.verify(card, now=time.time())
        assert report.result == VerificationResult.FAIL_EXPIRED

    def test_fail_missing_score(self):
        card = TrustAgentCard(agent_id="agent:a")
        v = TrustVerifier()
        report = v.verify(card)
        assert report.result == VerificationResult.FAIL_MISSING


# ---------------------------------------------------------------------------
# TrustGatekeeper
# ---------------------------------------------------------------------------

class TestTrustGatekeeper:
    def test_accept(self):
        card = TrustAgentCard(
            agent_id="agent:good", trust_score=0.7, tier=Tier.TRUSTED,
            attestation_count=10, capabilities=["deploy"],
        )
        gk = TrustGatekeeper(min_score=0.5, min_tier=Tier.VERIFIED, required_capabilities=["deploy"])
        result = gk.evaluate(card)
        assert result.accepted

    def test_reject_missing_capability(self):
        card = TrustAgentCard(agent_id="agent:a", trust_score=0.9, capabilities=["read"])
        gk = TrustGatekeeper(required_capabilities=["deploy"])
        result = gk.evaluate(card)
        assert not result.accepted
        assert "Missing capabilities" in result.reason

    def test_reject_low_score(self):
        card = TrustAgentCard(agent_id="agent:a", trust_score=0.1, tier=Tier.UNVERIFIED)
        gk = TrustGatekeeper(min_score=0.5)
        result = gk.evaluate(card)
        assert result.decision == GatekeeperDecision.REJECT

    def test_reject_unknown_tier(self):
        card = TrustAgentCard(agent_id="agent:a", trust_score=0.9, tier=None)
        gk = TrustGatekeeper(min_tier=Tier.BASIC, allow_unknown_tier=False)
        result = gk.evaluate(card)
        assert not result.accepted

    def test_allow_unknown_tier_flag(self):
        card = TrustAgentCard(agent_id="agent:a", trust_score=0.9, tier=None)
        gk = TrustGatekeeper(allow_unknown_tier=True)
        result = gk.evaluate(card)
        assert result.accepted
