"""Extensible workflow state machine for job candidates."""

from __future__ import annotations

from typing import Any

import yaml

from freelance_assitant.config import CONFIG_DIR
from freelance_assitant.domain.enums import JobStatus

# Default transitions — can be overridden by config/workflow.yaml
DEFAULT_TRANSITIONS: dict[str, list[str]] = {
    JobStatus.NEW: [JobStatus.SHORTLISTED, JobStatus.ARCHIVED],
    JobStatus.SHORTLISTED: [JobStatus.DRAFT_READY, JobStatus.ARCHIVED],
    JobStatus.DRAFT_READY: [JobStatus.APPROVED, JobStatus.SHORTLISTED, JobStatus.ARCHIVED],
    JobStatus.APPROVED: [JobStatus.APPLIED, JobStatus.ARCHIVED],
    JobStatus.APPLIED: [JobStatus.CLIENT_REPLIED, JobStatus.FOLLOWUP_DUE, JobStatus.LOST, JobStatus.ARCHIVED],
    JobStatus.CLIENT_REPLIED: [JobStatus.WON, JobStatus.LOST, JobStatus.FOLLOWUP_DUE],
    JobStatus.FOLLOWUP_DUE: [JobStatus.CLIENT_REPLIED, JobStatus.LOST, JobStatus.ARCHIVED],
    JobStatus.WON: [],
    JobStatus.LOST: [],
    JobStatus.ARCHIVED: [JobStatus.NEW],  # allow reactivation
}


class WorkflowMachine:
    def __init__(self, transitions: dict[str, list[str]] | None = None):
        self.transitions = transitions or self._load_transitions()

    def can_transition(self, from_status: str, to_status: str) -> bool:
        allowed = self.transitions.get(from_status, [])
        return to_status in allowed

    def allowed_transitions(self, from_status: str) -> list[str]:
        return self.transitions.get(from_status, [])

    def _load_transitions(self) -> dict[str, list[str]]:
        config_path = CONFIG_DIR / "workflow.yaml"
        if config_path.exists():
            with open(config_path) as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
            return data.get("transitions", DEFAULT_TRANSITIONS)
        return DEFAULT_TRANSITIONS


workflow = WorkflowMachine()
