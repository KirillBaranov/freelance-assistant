from __future__ import annotations

from enum import StrEnum


class SourcePlatform(StrEnum):
    FL_RU = "fl_ru"
    KWORK = "kwork"
    WORKSPACE = "workspace"
    FREELANCE_RU = "freelance_ru"
    TELEGRAM = "telegram"


class JobStatus(StrEnum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    DRAFT_READY = "draft_ready"
    APPROVED = "approved"
    APPLIED = "applied"
    CLIENT_REPLIED = "client_replied"
    FOLLOWUP_DUE = "followup_due"
    WON = "won"
    LOST = "lost"
    ARCHIVED = "archived"


class LeadTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
