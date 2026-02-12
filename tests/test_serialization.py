"""Tests for TrustScore JSON serialization."""

import json
import time
import pytest
from trustscore.score import AgentProfile, Interaction, PeerEndorsement, compute_trust_score
from trustscore.serialization import (
    profile_to_json, profile_from_json,
    profile_to_dict, dict_to_profile,
    score_to_json, score_to_dict,
    export_network, import_network,
    SCHEMA_VERSION,
)

NOW = 1707700000.0  # fixed timestamp for reproducibility


@pytest.fixture
def sample_profile():
    p = AgentProfile(agent_id="agent-alice", created_at=NOW - 86400 * 60)
    p.interactions = [
        Interaction(timestamp=NOW - 3600, success=True, weight=1.0, context="trade"),
        Interaction(timestamp=NOW - 7200, success=False, weight=0.5, context="query"),
    ]
    p.endorsements = [
        PeerEndorsement(endorser_id="agent-bob", endorser_trust=0.8, timestamp=NOW - 1800, strength=0.9),
    ]
    p.attestation_count = 5
    p.last_attestation = NOW - 600
    return p


def test_roundtrip_profile(sample_profile):
    """Profile survives JSON roundtrip."""
    json_str = profile_to_json(sample_profile)
    restored = profile_from_json(json_str)
    
    assert restored.agent_id == sample_profile.agent_id
    assert restored.created_at == sample_profile.created_at
    assert restored.attestation_count == sample_profile.attestation_count
    assert restored.last_attestation == sample_profile.last_attestation
    assert len(restored.interactions) == 2
    assert len(restored.endorsements) == 1
    assert restored.interactions[0].success is True
    assert restored.interactions[1].context == "query"
    assert restored.endorsements[0].endorser_id == "agent-bob"


def test_schema_version_present(sample_profile):
    """Serialized output includes schema version."""
    d = profile_to_dict(sample_profile)
    assert d["schema_version"] == SCHEMA_VERSION
    assert d["type"] == "agent_profile"


def test_score_serialization(sample_profile):
    """Trust score result serializes with metadata."""
    score = compute_trust_score(sample_profile, now=NOW)
    json_str = score_to_json(score)
    parsed = json.loads(json_str)
    
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["type"] == "trust_score"
    assert "trust_score" in parsed
    assert "components" in parsed
    assert 0 <= parsed["trust_score"] <= 1


def test_empty_profile_roundtrip():
    """Empty profile (no interactions/endorsements) survives roundtrip."""
    p = AgentProfile(agent_id="agent-new", created_at=NOW)
    restored = profile_from_json(profile_to_json(p))
    
    assert restored.agent_id == "agent-new"
    assert len(restored.interactions) == 0
    assert len(restored.endorsements) == 0
    assert restored.attestation_count == 0


def test_network_export_import(sample_profile):
    """Multi-agent network export and import."""
    p2 = AgentProfile(agent_id="agent-bob", created_at=NOW - 86400 * 30)
    p2.attestation_count = 3
    
    network = export_network([sample_profile, p2], compute_scores=True, now=NOW)
    
    assert network["type"] == "trust_network"
    assert network["agent_count"] == 2
    assert "agent-alice" in network["agents"]
    assert "agent-bob" in network["agents"]
    assert "trust_score" in network["agents"]["agent-alice"]
    
    # Import back
    restored = import_network(network)
    assert len(restored) == 2
    ids = {p.agent_id for p in restored}
    assert ids == {"agent-alice", "agent-bob"}


def test_network_json_roundtrip(sample_profile):
    """Network survives full JSON string roundtrip."""
    from trustscore.serialization import export_network_json
    json_str = export_network_json([sample_profile], now=NOW)
    restored = import_network(json.loads(json_str))
    assert len(restored) == 1
    assert restored[0].agent_id == "agent-alice"


def test_valid_json_output(sample_profile):
    """All serialization outputs are valid JSON."""
    json.loads(profile_to_json(sample_profile))
    score = compute_trust_score(sample_profile, now=NOW)
    json.loads(score_to_json(score))
