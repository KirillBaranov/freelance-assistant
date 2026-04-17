from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from freelance_assitant.config import settings
from freelance_assitant.domain.enums import JobStatus
from freelance_assitant.domain.schemas import JobCandidateRead
from freelance_assitant.services.agent_handoff import (
    agent_handoff_enabled,
    build_agent_handoff_payload,
    send_candidate_to_agent,
)
from freelance_assitant.storage.database import get_session
from freelance_assitant.storage.repo import JobCandidateRepo

app = FastAPI(title="Freelance Assistant", version="0.1.0")


def _repo(session: AsyncSession = Depends(get_session)) -> JobCandidateRepo:
    return JobCandidateRepo(session)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/jobs", response_model=list[JobCandidateRead])
async def list_jobs(
    status: str | None = None,
    tier: str | None = None,
    limit: int = 50,
    repo: JobCandidateRepo = Depends(_repo),
) -> list[JobCandidateRead]:
    if status:
        return await repo.get_by_status(status, limit=limit)
    return await repo.get_by_status(JobStatus.NEW, limit=limit)


@app.get("/jobs/{candidate_id}", response_model=JobCandidateRead)
async def get_job(
    candidate_id: uuid.UUID,
    repo: JobCandidateRepo = Depends(_repo),
) -> JobCandidateRead:
    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@app.post("/jobs/{candidate_id}/action")
async def job_action(
    candidate_id: uuid.UUID,
    action: str,
    repo: JobCandidateRepo = Depends(_repo),
) -> dict:
    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    status_map = {
        "skip": JobStatus.ARCHIVED,
        "approve": JobStatus.APPROVED,
        "applied": JobStatus.APPLIED,
        "replied": JobStatus.CLIENT_REPLIED,
        "won": JobStatus.WON,
        "lost": JobStatus.LOST,
    }
    new_status = status_map.get(action)
    if not new_status:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    await repo.update_status(candidate_id, new_status)
    return {"status": new_status, "candidate_id": str(candidate_id)}


@app.get("/jobs/{candidate_id}/agent-payload")
async def get_job_agent_payload(
    candidate_id: uuid.UUID,
    repo: JobCandidateRepo = Depends(_repo),
) -> dict:
    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    return {
        "enabled": agent_handoff_enabled(),
        "target": settings.agent_webhook_url.strip() or None,
        "payload": build_agent_handoff_payload(candidate),
    }


@app.post("/jobs/{candidate_id}/send-to-agent")
async def send_job_to_agent(
    candidate_id: uuid.UUID,
    repo: JobCandidateRepo = Depends(_repo),
) -> dict:
    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if not agent_handoff_enabled():
        raise HTTPException(status_code=412, detail="Agent webhook is not configured")

    try:
        return await send_candidate_to_agent(candidate)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent handoff failed: {exc}") from exc


# Late import: web admin routes register themselves on `app`
import freelance_assitant.web.app as _web_admin  # noqa: F401, E402
