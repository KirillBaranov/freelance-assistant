"""Thin admin web UI — FastAPI + Jinja2 templates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from freelance_assitant.api.app import app
from freelance_assitant.domain.enums import JobStatus
from freelance_assitant.storage.database import get_session
from freelance_assitant.storage.models import JobCandidate
from freelance_assitant.storage.source_state import get_source_state_store

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "web"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
SessionDep = Annotated[AsyncSession, Depends(get_session)]

SOURCE_LABELS = {
    "fl_ru": "FL.ru",
    "kwork": "Kwork",
    "workspace": "Workspace",
    "telegram": "Telegram",
    "freelance_ru": "Freelance.ru",
}


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, session: SessionDep):
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Stats
    total_today = await _count(session, JobCandidate.created_at >= today_start)
    a_today = await _count(
        session, JobCandidate.created_at >= today_start, JobCandidate.tier == "A"
    )
    b_today = await _count(
        session, JobCandidate.created_at >= today_start, JobCandidate.tier == "B"
    )
    applied = await _count(session, JobCandidate.status == JobStatus.APPLIED)
    won_today = await _count(
        session, JobCandidate.status == JobStatus.WON, JobCandidate.updated_at >= today_start
    )

    # Earnings
    stmt = select(func.sum(JobCandidate.budget_max)).where(
        JobCandidate.status == JobStatus.WON,
        JobCandidate.updated_at >= today_start,
    )
    earnings = (await session.execute(stmt)).scalar() or 0

    # Recent A-leads
    stmt = (
        select(JobCandidate)
        .where(JobCandidate.tier == "A")
        .order_by(JobCandidate.created_at.desc())
        .limit(20)
    )
    a_leads = (await session.execute(stmt)).scalars().all()
    ingest_stats = await get_source_state_store().get_latest_ingest_stats()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "stats": {
                "total_today": total_today,
                "a_today": a_today,
                "b_today": b_today,
                "applied": applied,
                "won_today": won_today,
                "earnings": earnings,
            },
            "leads": [_candidate_card(lead) for lead in a_leads],
            "ingest_stats": ingest_stats,
        },
    )


@app.get("/admin/pipeline", response_class=HTMLResponse)
async def admin_pipeline(request: Request, session: SessionDep):
    active_statuses = [
        JobStatus.SHORTLISTED, JobStatus.DRAFT_READY, JobStatus.APPROVED,
        JobStatus.APPLIED, JobStatus.CLIENT_REPLIED, JobStatus.FOLLOWUP_DUE,
    ]
    stmt = (
        select(JobCandidate)
        .where(JobCandidate.status.in_(active_statuses))
        .order_by(JobCandidate.updated_at.desc())
        .limit(50)
    )
    candidates = (await session.execute(stmt)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="pipeline.html",
        context={
            "candidates": [_candidate_card(candidate) for candidate in candidates],
            "statuses": active_statuses,
        },
    )


@app.get("/admin/jobs", response_class=HTMLResponse)
async def admin_jobs(
    request: Request,
    session: SessionDep,
    status: str | None = None,
    tier: str | None = None,
    source: str | None = None,
):
    stmt = select(JobCandidate).order_by(JobCandidate.created_at.desc()).limit(100)
    if status:
        stmt = stmt.where(JobCandidate.status == status)
    if tier:
        stmt = stmt.where(JobCandidate.tier == tier)
    if source:
        stmt = stmt.where(JobCandidate.source == source)

    candidates = (await session.execute(stmt)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="jobs.html",
        context={
            "candidates": [_candidate_card(candidate) for candidate in candidates],
            "filter_status": status,
            "filter_tier": tier,
            "filter_source": source,
        },
    )


@app.get("/admin/jobs/{candidate_id}", response_class=HTMLResponse)
async def admin_job_detail(
    request: Request,
    candidate_id: uuid.UUID,
    session: SessionDep,
):
    stmt = select(JobCandidate).where(JobCandidate.id == candidate_id)
    candidate = (await session.execute(stmt)).scalar_one_or_none()
    if not candidate:
        return HTMLResponse("Not found", status_code=404)

    return templates.TemplateResponse(
        request=request,
        name="job_detail.html",
        context={
            "c": candidate,
        },
    )


async def _count(session, *filters) -> int:
    stmt = select(func.count()).select_from(JobCandidate).where(*filters)
    return (await session.execute(stmt)).scalar() or 0


def _candidate_card(candidate: JobCandidate) -> dict:
    score_details = candidate.score_details or {}
    raw_data = candidate.raw_data or {}
    enrich = score_details.get("decision_enrichment") or {}

    description = (candidate.description or "").strip()
    if description and len(description) > 240:
        description = description[:240].rstrip() + "..."

    matched_feeds = raw_data.get("matched_feeds") or []
    if not isinstance(matched_feeds, list):
        matched_feeds = []

    return {
        "id": candidate.id,
        "title": candidate.title,
        "description": description,
        "source": candidate.source,
        "source_label": SOURCE_LABELS.get(candidate.source, candidate.source),
        "source_url": candidate.source_url,
        "budget_max": candidate.budget_max,
        "budget_min": candidate.budget_min,
        "budget_label": _budget_label(candidate.budget_min, candidate.budget_max),
        "tier": candidate.tier,
        "score": candidate.score,
        "status": candidate.status,
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
        "category": candidate.category,
        "client_name": candidate.client_name,
        "source_quality": raw_data.get("source_quality"),
        "source_bucket": raw_data.get("source_bucket"),
        "category_hint": raw_data.get("category_hint"),
        "feed_label": raw_data.get("feed_label"),
        "matched_feeds": matched_feeds[:3],
        "llm_advisory": score_details.get("llm_advisory"),
        "llm_scope_clarity": score_details.get("llm_scope_clarity"),
        "llm_grey_risk": score_details.get("llm_grey_risk"),
        "shortlist_fit": score_details.get("shortlist_fit"),
        "hard_reject": score_details.get("hard_reject"),
        "llm_reasoning": score_details.get("llm_reasoning"),
        "delivery_risk": score_details.get("llm_delivery_risk"),
        "recommended_mode": enrich.get("recommended_mode"),
        "reply_strategy": enrich.get("reply_strategy"),
        "execution_complexity": enrich.get("execution_complexity"),
        "blocking_risks": enrich.get("blocking_risks") or [],
        "what_to_offer": enrich.get("what_to_offer"),
        "first_milestone": enrich.get("first_milestone"),
        "agent_brief": enrich.get("agent_brief"),
        "agent_check_prompt": enrich.get("agent_check_prompt"),
        "questions_to_client": enrich.get("questions_to_client") or [],
        "has_decision": bool(enrich),
        "needs_refresh": not bool(score_details.get("shortlist_fit") is not None or enrich),
    }


def _budget_label(budget_min: int | None, budget_max: int | None) -> str:
    if budget_min or budget_max:
        bmin = f"{budget_min:,}" if budget_min else "?"
        bmax = f"{budget_max:,}" if budget_max else "?"
        if bmin == bmax:
            return f"{bmin} ₽"
        return f"{bmin} — {bmax} ₽"
    return "—"
