"""LLM-based ranking for shortlist-quality decisions."""

from __future__ import annotations

import json
import logging
from typing import Any

from freelance_assitant.domain.schemas import JobCandidateRead
from freelance_assitant.scoring.base import BaseScorer
from freelance_assitant.services.llm import chat_completion

logger = logging.getLogger("fa.scoring.llm")

SYSTEM_PROMPT = """Ты помощник senior-фрилансера и должен ранжировать входящие заказы.

Профиль исполнителя:
- Основной фокус: автоматизации, Telegram-боты, Telegram Mini Apps,
  backend/fullstack, парсинг, интеграции, внутренние бизнес-инструменты.
- Предпочтение задачам, которые можно быстро закрыть или поставить на поток.
- Любит четкий scope и понятный deliverable.
- Не хочет влезать в серые/сомнительные темы:
  крипта, казино, антиботщина, обходы ограничений, сомнительные схемы.
- Не любит дизайн и большие размытые проекты без конкретики.

Оцени не "насколько задача вообще хорошая", а
"насколько это правильный заказ именно для этого исполнителя".

Ответь строго JSON:
{
  "fit": 0.0,
  "scope_clarity": 0.0,
  "automation_leverage": 0.0,
  "repeatability": 0.0,
  "grey_risk": 0.0,
  "delivery_risk": 0.0,
  "reasoning": "краткое объяснение на русском",
  "decisive_signals": ["..."],
  "reject_reasons": ["..."]
}

Правила:
- Высокий fit: Telegram bots, Mini Apps, parsing, Python automation,
  integrations, internal business automation, backend/fullstack с понятным scope.
- Снижать fit, если задача размытая, слишком широкая, требует много ручного
  кастома, упирается в дизайн/визуалку или похожа на
  "давайте вместе придумаем продукт".
- Резко снижать fit, если есть крипта, казино, обходы ограничений,
  решения капчи, бронь слотов, серые схемы или иная сомнительная автоматизация.
- `fit` должен уже учитывать риски и полезность для исполнителя.
"""


class LLMAdvisoryScorer(BaseScorer):
    """LLM ranking for shortlist-quality leads."""

    name = "llm_advisory"

    async def evaluate(self, candidate: JobCandidateRead, profile: dict) -> float:
        assessment = await self.assess(candidate, profile)
        return float(assessment.get("fit", 0.5))

    async def assess(self, candidate: JobCandidateRead, profile: dict) -> dict[str, Any]:
        try:
            return await self._assess_impl(candidate, profile)
        except Exception:
            logger.exception("LLM scoring failed, returning neutral")
            return {
                "fit": 0.5,
                "scope_clarity": 0.5,
                "automation_leverage": 0.5,
                "repeatability": 0.5,
                "grey_risk": 0.5,
                "delivery_risk": 0.5,
                "reasoning": "LLM недоступен, использован нейтральный fallback.",
                "decisive_signals": [],
                "reject_reasons": [],
            }

    async def _assess_impl(self, candidate: JobCandidateRead, profile: dict) -> dict[str, Any]:
        budget_str = "не указан"
        if candidate.budget_min or candidate.budget_max:
            budget_str = f"{candidate.budget_min or '?'} — {candidate.budget_max or '?'} руб."

        source_meta = candidate.raw_data or {}
        user_prompt = f"""Проект:
Название: {candidate.title}
Описание: {candidate.description or 'нет описания'}
Бюджет: {budget_str}
Категория: {candidate.category or 'не указана'}
Источник: {candidate.source}
Source quality: {source_meta.get('source_quality', 'unknown')}
Source bucket: {source_meta.get('source_bucket', 'unknown')}

Навыки фрилансера: {", ".join(profile.get("primary_skills", []))}
Вторичные навыки: {", ".join(profile.get("secondary_skills", []))}
Избегаемые темы: {", ".join(profile.get("avoid_keywords", []))}
Предпочтительные категории: {", ".join(profile.get("preferred_categories", []))}
"""

        response = await chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        data = json.loads(response)
        assessment = {
            "fit": _clamp_score(data.get("fit", 0.5)),
            "scope_clarity": _clamp_score(data.get("scope_clarity", 0.5)),
            "automation_leverage": _clamp_score(data.get("automation_leverage", 0.5)),
            "repeatability": _clamp_score(data.get("repeatability", 0.5)),
            "grey_risk": _clamp_score(data.get("grey_risk", 0.5)),
            "delivery_risk": _clamp_score(data.get("delivery_risk", 0.5)),
            "reasoning": str(data.get("reasoning", "")).strip(),
            "decisive_signals": _string_list(data.get("decisive_signals")),
            "reject_reasons": _string_list(data.get("reject_reasons")),
        }
        logger.debug(
            "LLM assessment for '%s': fit=%s clarity=%s grey=%s",
            candidate.title[:60],
            assessment["fit"],
            assessment["scope_clarity"],
            assessment["grey_risk"],
        )
        return assessment


def _clamp_score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
