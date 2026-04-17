from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from freelance_assitant.domain.enums import JobStatus, LeadTier, SourcePlatform
from freelance_assitant.domain.schemas import JobCandidateRead
from freelance_assitant.scoring.base import BaseScorer
from freelance_assitant.scoring.engine import ScoringEngine

NOW = datetime.now(UTC)


def _make_candidate(**kwargs) -> JobCandidateRead:
    defaults = {
        "id": uuid.uuid4(),
        "source": SourcePlatform.FL_RU,
        "source_id": "123",
        "source_url": "https://fl.ru/projects/123/",
        "title": "Test job",
        "description": "Test description",
        "budget_min": None,
        "budget_max": None,
        "currency": "RUB",
        "client_name": None,
        "category": None,
        "skills_required": [],
        "raw_data": {},
        "status": JobStatus.NEW,
        "score": None,
        "score_details": None,
        "tier": None,
        "proposal_draft": None,
        "notified_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    defaults.update(kwargs)
    return JobCandidateRead(**defaults)


class ConstantScorer(BaseScorer):
    def __init__(self, name: str, value: float):
        self._name = name
        self._value = value

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, candidate: JobCandidateRead, profile: dict) -> float:
        return self._value


class FakeLLMScorer:
    def __init__(self, assessment: dict):
        self.assessment = assessment

    async def assess(self, candidate: JobCandidateRead, profile: dict) -> dict:
        return self.assessment


class FakeDecisionEnricher:
    def __init__(self, payload: dict):
        self.payload = payload

    async def enrich(self, candidate: JobCandidateRead, profile: dict) -> dict:
        return self.payload


@pytest.mark.asyncio
async def test_engine_shortlists_strong_b_with_good_llm_signals():
    engine = ScoringEngine(
        scorers=[
            ConstantScorer("skill_fit", 0.4),
            ConstantScorer("money_fit", 0.9),
            ConstantScorer("fast_close_fit", 0.8),
            ConstantScorer("source_fit", 0.9),
            ConstantScorer("risk_score", 0.0),
        ]
    )
    engine._llm_scorer = FakeLLMScorer(
        {
            "fit": 0.85,
            "scope_clarity": 0.8,
            "automation_leverage": 0.8,
            "repeatability": 0.7,
            "grey_risk": 0.0,
            "delivery_risk": 0.2,
            "reasoning": "Strong fit",
            "decisive_signals": ["telegram"],
            "reject_reasons": [],
        }
    )
    engine._decision_enricher = FakeDecisionEnricher(
        {
            "deliverable_type": "mini_app",
            "scope_size": "medium",
            "scope_clarity_reason": "Есть понятный deliverable.",
            "repeatability_fit": "high",
            "manual_load_risk": "medium",
            "execution_complexity": "medium",
            "complexity_reason": "Нужна доработка существующего продукта.",
            "blocking_risks": ["auth"],
            "compliance_risk": "low",
            "failure_cost": "medium",
            "recommended_mode": "take_with_questions",
            "reply_strategy": "send_direct_offer",
            "first_milestone": "Поднять MVP.",
            "what_to_offer": "Собрать Mini App и админку.",
            "questions_to_client": [],
            "agent_brief": "Сделать MVP по существующему примеру.",
            "agent_check_prompt": "Проверь риски и план MVP.",
        }
    )

    result = await engine.score(_make_candidate(title="Telegram Mini App"))

    assert result.tier == LeadTier.A
    assert result.shortlist is True
    assert result.details["shortlist_fit"] is True
    assert result.details["hard_reject"] is False
    assert result.details["decision_enrichment"]["deliverable_type"] == "mini_app"
    assert result.details["decision_enrichment"]["execution_complexity"] == "medium"


@pytest.mark.asyncio
async def test_engine_hard_rejects_grey_topic_even_if_rules_are_high():
    engine = ScoringEngine(
        scorers=[
            ConstantScorer("skill_fit", 0.5),
            ConstantScorer("money_fit", 1.0),
            ConstantScorer("fast_close_fit", 0.8),
            ConstantScorer("source_fit", 0.9),
            ConstantScorer("risk_score", 0.0),
        ]
    )
    engine._llm_scorer = FakeLLMScorer(
        {
            "fit": 0.0,
            "scope_clarity": 0.0,
            "automation_leverage": 0.0,
            "repeatability": 0.0,
            "grey_risk": 1.0,
            "delivery_risk": 1.0,
            "reasoning": "Grey topic",
            "decisive_signals": [],
            "reject_reasons": ["crypto"],
        }
    )

    result = await engine.score(_make_candidate(title="Binance bot"))

    assert result.shortlist is False
    assert result.details["hard_reject"] is True
