from __future__ import annotations

import uuid
from typing import Any

import httpx

from freelance_assitant.config import settings
from freelance_assitant.domain.schemas import JobCandidateRead


def agent_handoff_enabled() -> bool:
    return bool(settings.agent_webhook_url.strip())


def build_agent_handoff_payload(candidate: JobCandidateRead) -> dict[str, Any]:
    score_details = candidate.score_details or {}
    enrich = score_details.get("decision_enrichment") or {}
    raw_data = candidate.raw_data or {}

    return {
        "event": "freelance_lead_handoff",
        "lead": {
            "id": str(candidate.id),
            "source": str(candidate.source),
            "source_id": candidate.source_id,
            "source_url": candidate.source_url,
            "title": candidate.title,
            "description": candidate.description,
            "budget_min": candidate.budget_min,
            "budget_max": candidate.budget_max,
            "currency": candidate.currency,
            "category": candidate.category,
            "client_name": candidate.client_name,
            "skills_required": candidate.skills_required,
            "status": str(candidate.status),
            "tier": str(candidate.tier) if candidate.tier else None,
            "score": candidate.score,
            "created_at": candidate.created_at.isoformat(),
            "updated_at": candidate.updated_at.isoformat(),
        },
        "source_context": {
            "source_quality": raw_data.get("source_quality"),
            "source_bucket": raw_data.get("source_bucket"),
            "category_hint": raw_data.get("category_hint"),
            "feed_label": raw_data.get("feed_label"),
            "matched_feeds": raw_data.get("matched_feeds"),
            "ingest_variant": raw_data.get("ingest_variant"),
        },
        "scoring": {
            "llm_advisory": score_details.get("llm_advisory"),
            "llm_scope_clarity": score_details.get("llm_scope_clarity"),
            "llm_automation_leverage": score_details.get("llm_automation_leverage"),
            "llm_repeatability": score_details.get("llm_repeatability"),
            "llm_grey_risk": score_details.get("llm_grey_risk"),
            "llm_delivery_risk": score_details.get("llm_delivery_risk"),
            "llm_reasoning": score_details.get("llm_reasoning"),
            "llm_decisive_signals": score_details.get("llm_decisive_signals"),
            "llm_reject_reasons": score_details.get("llm_reject_reasons"),
            "shortlist_fit": score_details.get("shortlist_fit"),
            "hard_reject": score_details.get("hard_reject"),
        },
        "decision": enrich,
        "agent": {
            "check_prompt": enrich.get("agent_check_prompt"),
            "brief": enrich.get("agent_brief"),
        },
    }


async def send_candidate_to_agent(candidate: JobCandidateRead) -> dict[str, Any]:
    webhook_url = settings.agent_webhook_url.strip()
    if not webhook_url:
        raise RuntimeError("Agent webhook URL is not configured")

    payload = build_agent_handoff_payload(candidate)
    headers = {"Content-Type": "application/json"}
    if settings.agent_webhook_token.strip():
        headers["Authorization"] = f"Bearer {settings.agent_webhook_token.strip()}"
        headers["X-Agent-Webhook-Token"] = settings.agent_webhook_token.strip()
    headers["X-Freelance-Lead-Id"] = str(candidate.id)
    headers["X-Freelance-Event-Id"] = str(uuid.uuid4())

    async with httpx.AsyncClient(timeout=settings.agent_webhook_timeout_seconds) as client:
        response = await client.post(webhook_url, json=payload, headers=headers)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            body: Any = response.json()
        else:
            body = response.text[:2000]

    return {
        "ok": True,
        "target": webhook_url,
        "status_code": response.status_code,
        "response": body,
        "lead_id": str(candidate.id),
    }
