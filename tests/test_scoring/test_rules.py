"""Tests for rule-based scorers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from freelance_assitant.domain.enums import JobStatus, SourcePlatform
from freelance_assitant.domain.schemas import JobCandidateRead
from freelance_assitant.scoring.rules import (
    FastCloseFitScorer,
    MoneyFitScorer,
    RiskScorer,
    SkillFitScorer,
    SourceFitScorer,
)

PROFILE = {
    "primary_skills": ["python", "fastapi", "telegram bot", "парсинг", "api", "автоматизация"],
    "secondary_skills": ["docker", "postgresql", "redis"],
    "avoid_keywords": ["1С", "битрикс", "wordpress", "php", "ios", "android"],
    "min_budget_rub": 3000,
    "preferred_max_duration_days": 14,
}

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


# --- SkillFitScorer ---

@pytest.mark.asyncio
async def test_skill_fit_high():
    scorer = SkillFitScorer()
    c = _make_candidate(
        title="Разработка Telegram-бота на Python",
        description="Нужен бот на aiogram + FastAPI + PostgreSQL",
        raw_data={"source_quality": "high", "category_hint": "Программирование"},
    )
    score = await scorer.evaluate(c, PROFILE)
    assert score >= 0.5


@pytest.mark.asyncio
async def test_skill_fit_low():
    scorer = SkillFitScorer()
    c = _make_candidate(
        title="Разработка iOS приложения",
        description="Нужно приложение на Swift для iPhone",
    )
    score = await scorer.evaluate(c, PROFILE)
    assert score < 0.3


# --- MoneyFitScorer ---

@pytest.mark.asyncio
async def test_money_fit_good_budget():
    scorer = MoneyFitScorer()
    c = _make_candidate(budget_min=10000, budget_max=15000)
    score = await scorer.evaluate(c, PROFILE)
    assert score >= 0.7


@pytest.mark.asyncio
async def test_money_fit_no_budget():
    scorer = MoneyFitScorer()
    c = _make_candidate(budget_min=None, budget_max=None)
    score = await scorer.evaluate(c, PROFILE)
    assert score == 0.5


@pytest.mark.asyncio
async def test_money_fit_low_budget():
    scorer = MoneyFitScorer()
    c = _make_candidate(budget_min=500, budget_max=500)
    score = await scorer.evaluate(c, PROFILE)
    assert score < 0.4


# --- FastCloseFitScorer ---

@pytest.mark.asyncio
async def test_fast_close_quick_job():
    scorer = FastCloseFitScorer()
    c = _make_candidate(
        title="Срочно нужен парсер",
        description="Простой скрипт для парсинга, за 1-2 дня",
    )
    score = await scorer.evaluate(c, PROFILE)
    assert score > 0.5


@pytest.mark.asyncio
async def test_fast_close_big_project():
    scorer = FastCloseFitScorer()
    c = _make_candidate(
        title="Разработка мобильного приложения с нуля",
        description="Полноценное приложение, долгосрочный проект, нужна команда",
    )
    score = await scorer.evaluate(c, PROFILE)
    assert score < 0.5


# --- RiskScorer ---

@pytest.mark.asyncio
async def test_risk_avoid_keywords():
    scorer = RiskScorer()
    c = _make_candidate(
        title="Доработать сайт на WordPress + 1С интеграция",
        description="Нужна интеграция с битрикс",
    )
    score = await scorer.evaluate(c, PROFILE)
    assert score >= 0.5  # high risk


@pytest.mark.asyncio
async def test_risk_red_flags():
    scorer = RiskScorer()
    c = _make_candidate(
        title="Сделать сайт как Uber",
        description="Аналог Uber для доставки. Бюджет обсуждаем.",
    )
    score = await scorer.evaluate(c, PROFILE)
    assert score >= 0.4  # flagged


@pytest.mark.asyncio
async def test_risk_clean():
    scorer = RiskScorer()
    c = _make_candidate(
        title="Разработка Telegram-бота",
        description="Нужен бот для уведомлений",
        budget_min=5000,
        budget_max=10000,
        raw_data={"source_quality": "high", "source_bucket": "programming_feed"},
    )
    score = await scorer.evaluate(c, PROFILE)
    assert score < 0.2  # low risk


# --- SourceFitScorer ---

@pytest.mark.asyncio
async def test_source_fit_prefers_high_signal_source():
    scorer = SourceFitScorer()
    high_signal = _make_candidate(
        title="Разработка Telegram-бота",
        description="Python backend",
        raw_data={
            "source_quality": "high",
            "source_bucket": "programming_feed",
            "category_hint": "Программирование",
        },
    )
    low_signal = _make_candidate(
        title="Разработка Telegram-бота",
        description="Python backend",
        raw_data={
            "source_quality": "low",
            "source_bucket": "broad_feed",
            "category_hint": "Общий поток",
        },
    )

    assert await scorer.evaluate(high_signal, PROFILE) > await scorer.evaluate(low_signal, PROFILE)
