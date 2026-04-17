from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .enums import JobStatus, LeadTier, SourcePlatform


class JobCandidateCreate(BaseModel):
    """Schema for creating a new job candidate from a collector."""

    source: SourcePlatform
    source_id: str
    source_url: str
    title: str
    description: str | None = None
    budget_min: int | None = None
    budget_max: int | None = None
    currency: str = "RUB"
    client_name: str | None = None
    category: str | None = None
    skills_required: list[str] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class JobCandidateRead(BaseModel):
    """Schema for reading a job candidate from DB."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    source: SourcePlatform
    source_id: str
    source_url: str
    title: str
    description: str | None
    budget_min: int | None
    budget_max: int | None
    currency: str
    client_name: str | None
    category: str | None
    skills_required: list[str]
    raw_data: dict[str, Any]
    status: JobStatus
    score: float | None
    score_details: dict[str, Any] | None
    tier: LeadTier | None
    proposal_draft: str | None
    notified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ScoringResult(BaseModel):
    """Result from the scoring engine."""

    score: float = Field(ge=0.0, le=1.0)
    tier: LeadTier
    shortlist: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
