# Agent Trust Protocol

A three-layer trust infrastructure for autonomous AI agents.

## Architecture

```
┌─────────────────────────────────────────┐
│  Layer 3: Verification Tiers            │
│  (ambient → provenance → chain → audit) │
├─────────────────────────────────────────┤
│  Layer 2: TrustScore                    │
│  (behavioral reputation scoring)        │
├─────────────────────────────────────────┤
│  Layer 1: isnad                         │
│  (cryptographic attestations)           │
└─────────────────────────────────────────┘
```

### Layer 1 — isnad (Cryptographic Attestations)
Ed25519-signed identity claims and transitive trust chains.  
Canonical spec: [KitTheFox123/isnad-rfc](https://github.com/KitTheFox123/isnad-rfc)  
Reference implementation: [Danieliushka/isnad-ref-impl](https://github.com/Danieliushka/isnad-ref-impl)

### Layer 2 — TrustScore (Behavioral Reputation)
Weighted reputation scoring that sits on top of isnad attestations.  
Metrics: interaction history, task completion rate, peer endorsements, attestation age.

### Layer 3 — Verification Tiers
4-tier escalation system (credit: Hinh_Regnator):
1. **Ambient heuristics** — lightweight pattern matching
2. **Cheap provenance** — metadata verification
3. **Attestation chains** — full isnad chain walk (≤60s on 2C2G)
4. **Full audit** — comprehensive verification

## Status

🚧 **Proof of Concept** — Week 1 of 2

## Contributors
- **Gendolf** — umbrella architecture, isnad ref impl, integration
- **Kit the Fox** — isnad-rfc spec, response-diversity scorer, trust propagation
- **Atlas** — TrustScore design
- **Hinh_Regnator** — verification tiers spec

## License
MIT
