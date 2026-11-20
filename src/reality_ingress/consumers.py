"""Example of agent-relative references; no sensor mutation or delivery service."""
from __future__ import annotations


def agent_evidence_ref(agent_id: str, observation_id: str) -> dict:
    if not agent_id or not observation_id.startswith("obs_"):
        raise ValueError("Both agent_id and observation_id are required")
    return {
        "agent_id_str": agent_id,
        "evidence_observation_id_str": observation_id,
        "type_str": "external_observation_ref",
        "status_str": "UNRESOLVED_CHRONOGRAF_ANCHOR",
    }
