"""Rule-based scorers."""

from __future__ import annotations

from freelance_assitant.domain.schemas import JobCandidateRead
from freelance_assitant.scoring.base import BaseScorer


def _candidate_text(candidate: JobCandidateRead) -> str:
    raw = candidate.raw_data or {}
    parts = [
        candidate.title,
        candidate.description or "",
        candidate.category or "",
        str(raw.get("category_hint", "")),
        str(raw.get("matched_channel", "")),
    ]
    return " ".join(part for part in parts if part).lower()


def _source_quality_bonus(candidate: JobCandidateRead) -> float:
    quality = str((candidate.raw_data or {}).get("source_quality", "medium")).lower()
    return {
        "high": 0.15,
        "medium": 0.05,
        "low": -0.05,
    }.get(quality, 0.0)


class SkillFitScorer(BaseScorer):
    """Scores how well the job matches the freelancer's skills."""

    name = "skill_fit"

    async def evaluate(self, candidate: JobCandidateRead, profile: dict) -> float:
        primary = [s.lower() for s in profile.get("primary_skills", [])]
        secondary = [s.lower() for s in profile.get("secondary_skills", [])]
        if not primary and not secondary:
            return 0.5

        text = _candidate_text(candidate)

        # Primary skills: full weight
        primary_hits = sum(1 for s in primary if s in text)
        # Secondary skills: half weight
        secondary_hits = sum(1 for s in secondary if s in text)

        total_weight = len(primary) + len(secondary) * 0.5
        if total_weight == 0:
            return 0.5

        score = (primary_hits + secondary_hits * 0.5) / total_weight
        score = min(score * 1.5, 1.0)  # boost so 2-3 skill hits already score high
        return max(0.0, min(1.0, score + _source_quality_bonus(candidate)))


class MoneyFitScorer(BaseScorer):
    """Scores budget attractiveness."""

    name = "money_fit"

    async def evaluate(self, candidate: JobCandidateRead, profile: dict) -> float:
        min_budget = profile.get("min_budget_rub", 3000)

        # No budget stated — neutral
        if candidate.budget_min is None and candidate.budget_max is None:
            return 0.5

        budget = candidate.budget_max or candidate.budget_min or 0

        if budget < min_budget:
            # Below minimum — penalize proportionally
            return max(0.1, budget / min_budget * 0.4)

        if budget >= min_budget * 3:
            return 1.0  # great budget
        if budget >= min_budget * 2:
            return 0.9
        if budget >= min_budget:
            return 0.7

        return 0.5


class FastCloseFitScorer(BaseScorer):
    """Scores likelihood of quick completion and payment."""

    name = "fast_close_fit"

    async def evaluate(self, candidate: JobCandidateRead, profile: dict) -> float:
        text = _candidate_text(candidate)

        score = 0.5  # default neutral

        # Positive signals for fast close
        fast_signals = [
            "срочно", "быстро", "за день", "за 2 дня", "за неделю",
            "простой", "небольш", "мелк", "фикс", "багфикс", "доработ",
            "скрипт", "бот", "парсер",
        ]
        fast_hits = sum(1 for s in fast_signals if s in text)
        if fast_hits > 0:
            score += min(fast_hits * 0.15, 0.4)

        # Negative signals — large/complex projects
        slow_signals = [
            "с нуля", "полноценн", "приложение", "мобильн",
            "масштаб", "долгосроч", "команд", "fullstack",
        ]
        slow_hits = sum(1 for s in slow_signals if s in text)
        if slow_hits > 0:
            score -= min(slow_hits * 0.15, 0.3)

        return max(0.0, min(1.0, score))


class SourceFitScorer(BaseScorer):
    """Rewards leads coming from higher-signal sources and categories."""

    name = "source_fit"

    async def evaluate(self, candidate: JobCandidateRead, profile: dict) -> float:
        raw = candidate.raw_data or {}
        quality = str(raw.get("source_quality", "medium")).lower()
        bucket = str(raw.get("source_bucket", "")).lower()
        text = _candidate_text(candidate)

        score = {
            "high": 0.85,
            "medium": 0.65,
            "low": 0.35,
        }.get(quality, 0.55)

        if bucket in {"programming_feed", "programming_marketplace", "telegram_channel"}:
            score += 0.1
        elif bucket == "broad_feed":
            score -= 0.1

        programming_hints = (
            "программ",
            "бот",
            "python",
            "backend",
            "api",
            "автоматизац",
            "парс",
        )
        if any(hint in text for hint in programming_hints):
            score += 0.05

        return max(0.0, min(1.0, score))


class RiskScorer(BaseScorer):
    """Detects red flags and risks."""

    name = "risk_score"

    async def evaluate(self, candidate: JobCandidateRead, profile: dict) -> float:
        text = _candidate_text(candidate)
        avoid = [kw.lower() for kw in profile.get("avoid_keywords", [])]

        risk = 0.0

        # Avoid keywords match
        avoid_hits = sum(1 for kw in avoid if kw in text)
        if avoid_hits > 0:
            risk += min(avoid_hits * 0.3, 0.8)

        # Red flag phrases
        red_flags = [
            "как uber", "как авито", "как wildberries", "аналог",
            "бюджет обсуждаем", "бюджет минимальный",
            "бесплатно", "за отзыв", "тестовое задание",
            "нужен вчера",
        ]
        flag_hits = sum(1 for f in red_flags if f in text)
        risk += min(flag_hits * 0.25, 0.6)

        # Unrealistically low budget for programming
        if candidate.budget_max and candidate.budget_max < 1000:
            risk += 0.3

        raw = candidate.raw_data or {}
        quality = str(raw.get("source_quality", "medium")).lower()
        bucket = str(raw.get("source_bucket", "")).lower()
        if quality == "low":
            risk += 0.1
        if bucket == "broad_feed":
            risk += 0.05

        return min(risk, 1.0)
