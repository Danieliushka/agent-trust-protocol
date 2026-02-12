"""
TrustScore serialization — JSON import/export for agent profiles and scores.

Supports:
- AgentProfile → JSON (for storage/transmission)
- JSON → AgentProfile (for loading)
- TrustScore result → portable JSON format
- Batch serialization for multi-agent networks
"""

import json
from typing import Union
from .score import AgentProfile, Interaction, PeerEndorsement, compute_trust_score


# --- Schema version for forward compatibility ---
SCHEMA_VERSION = "0.1.0"


def profile_to_dict(profile: AgentProfile) -> dict:
    """Serialize an AgentProfile to a JSON-compatible dict."""
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "agent_profile",
        "agent_id": profile.agent_id,
        "created_at": profile.created_at,
        "attestation_count": profile.attestation_count,
        "last_attestation": profile.last_attestation,
        "interactions": [
            {
                "timestamp": ix.timestamp,
                "success": ix.success,
                "weight": ix.weight,
                "context": ix.context,
            }
            for ix in profile.interactions
        ],
        "endorsements": [
            {
                "endorser_id": e.endorser_id,
                "endorser_trust": e.endorser_trust,
                "timestamp": e.timestamp,
                "strength": e.strength,
            }
            for e in profile.endorsements
        ],
    }


def dict_to_profile(data: dict) -> AgentProfile:
    """Deserialize a dict to an AgentProfile."""
    profile = AgentProfile(
        agent_id=data["agent_id"],
        created_at=data.get("created_at", 0),
        attestation_count=data.get("attestation_count", 0),
        last_attestation=data.get("last_attestation"),
    )
    profile.interactions = [
        Interaction(
            timestamp=ix["timestamp"],
            success=ix["success"],
            weight=ix.get("weight", 1.0),
            context=ix.get("context", ""),
        )
        for ix in data.get("interactions", [])
    ]
    profile.endorsements = [
        PeerEndorsement(
            endorser_id=e["endorser_id"],
            endorser_trust=e["endorser_trust"],
            timestamp=e["timestamp"],
            strength=e.get("strength", 1.0),
        )
        for e in data.get("endorsements", [])
    ]
    return profile


def profile_to_json(profile: AgentProfile, indent: int = 2) -> str:
    """Serialize an AgentProfile to a JSON string."""
    return json.dumps(profile_to_dict(profile), indent=indent)


def profile_from_json(json_str: str) -> AgentProfile:
    """Deserialize a JSON string to an AgentProfile."""
    return dict_to_profile(json.loads(json_str))


def score_to_dict(score_result: dict) -> dict:
    """Wrap a trust score result with schema metadata."""
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "trust_score",
        **score_result,
    }


def score_to_json(score_result: dict, indent: int = 2) -> str:
    """Serialize a trust score result to JSON."""
    return json.dumps(score_to_dict(score_result), indent=indent)


def export_network(profiles: list[AgentProfile], compute_scores: bool = True, now: float = None) -> dict:
    """Export a full trust network (multiple agents) to JSON-compatible dict."""
    network = {
        "schema_version": SCHEMA_VERSION,
        "type": "trust_network",
        "agent_count": len(profiles),
        "agents": {},
    }
    for p in profiles:
        entry = profile_to_dict(p)
        if compute_scores:
            entry["trust_score"] = compute_trust_score(p, now=now)
        network["agents"][p.agent_id] = entry
    return network


def export_network_json(profiles: list[AgentProfile], compute_scores: bool = True, now: float = None, indent: int = 2) -> str:
    """Export a full trust network to JSON string."""
    return json.dumps(export_network(profiles, compute_scores, now), indent=indent)


def import_network(data: Union[dict, str]) -> list[AgentProfile]:
    """Import a trust network from dict or JSON string."""
    if isinstance(data, str):
        data = json.loads(data)
    return [dict_to_profile(agent_data) for agent_data in data.get("agents", {}).values()]
