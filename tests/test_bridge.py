"""Tests for isnad→TrustScore bridge."""

import sys
import os
import time

ISNAD_PATH = os.path.expanduser("~/projects/isnad-ref-impl")
if ISNAD_PATH not in sys.path:
    sys.path.insert(0, ISNAD_PATH)

from isnad import AgentIdentity, Attestation, TrustChain
from trustscore.bridge import IsnadBridge, BridgeConfig, _iso_to_epoch


def _make_signed_attestation(subject_id, witness_identity, task="test task"):
    """Helper: create and sign an attestation."""
    att = Attestation(
        subject=subject_id,
        witness=witness_identity.agent_id,
        task=task,
        evidence="https://example.com/proof",
    )
    att.sign(witness_identity)
    return att


class TestIsoBridge:
    def test_iso_to_epoch(self):
        ts = "2026-02-12T12:00:00+00:00"
        epoch = _iso_to_epoch(ts)
        assert epoch > 0
        assert abs(epoch - 1770897600.0) < 2

    def test_iso_to_epoch_fallback(self):
        epoch = _iso_to_epoch("garbage")
        assert abs(epoch - time.time()) < 5


class TestAttestationToInteraction:
    def test_verified_attestation(self):
        alice = AgentIdentity()
        bob = AgentIdentity()
        att = _make_signed_attestation(alice.agent_id, bob)

        bridge = IsnadBridge()
        interaction = bridge.attestation_to_interaction(att)

        assert interaction.success is True
        assert interaction.weight > 0
        assert "isnad:" in interaction.context

    def test_unverified_attestation(self):
        alice = AgentIdentity()
        bob = AgentIdentity()
        att = Attestation(
            subject=alice.agent_id,
            witness=bob.agent_id,
            task="unsigned task",
        )
        # Not signed — will fail verify

        bridge = IsnadBridge()
        interaction = bridge.attestation_to_interaction(att)
        assert interaction.success is False

    def test_explicit_verified_flag(self):
        alice = AgentIdentity()
        bob = AgentIdentity()
        att = _make_signed_attestation(alice.agent_id, bob)

        bridge = IsnadBridge()
        interaction = bridge.attestation_to_interaction(att, verified=False)
        assert interaction.success is False  # overridden


class TestEndorsements:
    def test_single_attestation_no_endorsement(self):
        alice = AgentIdentity()
        bob = AgentIdentity()
        att = _make_signed_attestation(alice.agent_id, bob)

        bridge = IsnadBridge()
        endorsements = bridge.attestations_to_endorsements([att])
        assert len(endorsements) == 0  # need min 2

    def test_multiple_witnesses_produce_endorsements(self):
        alice = AgentIdentity()
        bob = AgentIdentity()
        carol = AgentIdentity()

        att1 = _make_signed_attestation(alice.agent_id, bob, "task 1")
        att2 = _make_signed_attestation(alice.agent_id, carol, "task 2")

        bridge = IsnadBridge()
        endorsements = bridge.attestations_to_endorsements([att1, att2])
        assert len(endorsements) == 2
        assert endorsements[0].endorser_id == bob.agent_id
        assert endorsements[1].endorser_id == carol.agent_id

    def test_duplicate_witness_deduplicated(self):
        alice = AgentIdentity()
        bob = AgentIdentity()

        att1 = _make_signed_attestation(alice.agent_id, bob, "task 1")
        att2 = _make_signed_attestation(alice.agent_id, bob, "task 2")

        bridge = IsnadBridge()
        endorsements = bridge.attestations_to_endorsements([att1, att2])
        assert len(endorsements) == 1  # same witness, only one endorsement

    def test_endorser_trust_cache(self):
        alice = AgentIdentity()
        bob = AgentIdentity()
        carol = AgentIdentity()

        att1 = _make_signed_attestation(alice.agent_id, bob, "task 1")
        att2 = _make_signed_attestation(alice.agent_id, carol, "task 2")

        bridge = IsnadBridge()
        bridge.set_endorser_trust(bob.agent_id, 0.9)

        endorsements = bridge.attestations_to_endorsements([att1, att2])
        assert endorsements[0].endorser_trust == 0.9
        assert endorsements[1].endorser_trust == 0.5  # default


class TestChainToProfile:
    def test_basic_chain_profile(self):
        alice = AgentIdentity()
        bob = AgentIdentity()
        carol = AgentIdentity()

        chain = TrustChain()
        chain.add(_make_signed_attestation(alice.agent_id, bob, "built API"))
        chain.add(_make_signed_attestation(alice.agent_id, carol, "fixed bug"))

        bridge = IsnadBridge()
        profile = bridge.chain_to_profile(chain, alice.agent_id)

        assert profile.agent_id == alice.agent_id
        assert len(profile.interactions) == 2
        assert profile.attestation_count == 2
        assert all(i.success for i in profile.interactions)

    def test_witness_activity_counted(self):
        alice = AgentIdentity()
        bob = AgentIdentity()

        chain = TrustChain()
        chain.add(_make_signed_attestation(bob.agent_id, alice, "reviewed code"))

        bridge = IsnadBridge()
        profile = bridge.chain_to_profile(chain, alice.agent_id)

        # Alice witnessed bob's work — counts as witness interaction
        assert len(profile.interactions) == 1
        assert "witness" in profile.interactions[0].context


class TestEndToEnd:
    def test_compute_trust_from_chain(self):
        alice = AgentIdentity()
        bob = AgentIdentity()
        carol = AgentIdentity()
        dave = AgentIdentity()

        chain = TrustChain()
        chain.add(_make_signed_attestation(alice.agent_id, bob, "shipped feature"))
        chain.add(_make_signed_attestation(alice.agent_id, carol, "code review"))
        chain.add(_make_signed_attestation(alice.agent_id, dave, "deployed prod"))

        bridge = IsnadBridge()
        bridge.set_endorser_trust(bob.agent_id, 0.8)
        bridge.set_endorser_trust(carol.agent_id, 0.7)

        result = bridge.compute_trust_from_chain(chain, alice.agent_id)

        assert "trust_score" in result
        assert 0 < result["trust_score"] <= 1.0
        assert result["interactions_count"] == 3
        assert result["attestation_count"] == 3
        assert result["components"]["interaction"] > 0

    def test_compare_agents(self):
        alice = AgentIdentity()
        bob = AgentIdentity()
        carol = AgentIdentity()

        chain = TrustChain()
        # Alice has 3 attestations, Bob has 1
        chain.add(_make_signed_attestation(alice.agent_id, bob, "task 1"))
        chain.add(_make_signed_attestation(alice.agent_id, carol, "task 2"))
        chain.add(_make_signed_attestation(alice.agent_id, carol, "task 3"))
        chain.add(_make_signed_attestation(bob.agent_id, alice, "task 4"))

        bridge = IsnadBridge()
        results = bridge.compare_agents(chain, [alice.agent_id, bob.agent_id])

        assert len(results) == 2
        # Alice should score higher (more attestations)
        assert results[0]["agent_id"] == alice.agent_id

    def test_empty_chain(self):
        chain = TrustChain()
        bridge = IsnadBridge()
        result = bridge.compute_trust_from_chain(chain, "agent:nobody")
        # Age component gives minimal score even with no interactions
        assert result["trust_score"] < 0.1
