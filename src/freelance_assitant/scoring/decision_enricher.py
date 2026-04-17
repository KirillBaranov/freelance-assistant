"""LLM-based decision enrichment for shortlist leads."""

from __future__ import annotations

import json
import logging
from typing import Any

from freelance_assitant.domain.schemas import JobCandidateRead
from freelance_assitant.services.llm import chat_completion

logger = logging.getLogger("fa.scoring.decision_enricher")

BRIEF_SYSTEM_PROMPT = """Ты помощник фрилансера. Подготовь structured decision brief
по shortlisted-заказу, чтобы исполнитель быстро решил, брать ли заказ и как отвечать.

Профиль исполнителя:
- автоматизации
- Telegram-боты
- Telegram Mini Apps
- parsing / scraping
- backend / fullstack
- интеграции / внутренние бизнес-инструменты

Избегает:
- крипта
- казино
- серые схемы
- дизайн
- размытые долгие проекты без четкого scope

Ответь строго JSON:
{
  "deliverable_type": "telegram_bot | mini_app | parser | automation | integration | backend_module | website | dashboard | other",
  "scope_size": "tiny | small | medium | large",
  "scope_clarity_reason": "кратко почему scope понятный или нет",
  "repeatability_fit": "high | medium | low",
  "manual_load_risk": "low | medium | high",
  "recommended_mode": "take_now | take_with_questions | take_only_with_margin | skip",
  "reply_strategy": "send_direct_offer | send_offer_with_questions | ask_scope_first | skip",
  "first_milestone": "первый разумный этап работ",
  "what_to_offer": "что именно предложить клиенту в отклике",
  "questions_to_client": ["..."],
  "agent_brief": "короткий brief для исполнителя/агента: что делать и на что смотреть"
}

Правила:
- Поля должны быть короткими и практичными.
- `questions_to_client` — максимум 4 вопроса.
- Если scope уже ясный, не задавай лишние вопросы.
- `agent_brief` должен быть пригоден для быстрой передачи в работу.
"""

EXECUTION_SYSTEM_PROMPT = """Ты помощник фрилансера. Подготовь structured execution review
по shortlisted-заказу, чтобы исполнитель быстро понял сложность, скрытые риски
и мог одним кликом передать проверку своему агенту.

Профиль исполнителя:
- автоматизации
- Telegram-боты
- Telegram Mini Apps
- parsing / scraping
- backend / fullstack
- интеграции / внутренние бизнес-инструменты

Избегает:
- крипта
- казино
- серые схемы
- дизайн
- размытые долгие проекты без четкого scope

Ответь строго JSON:
{
  "execution_complexity": "low | medium | high",
  "complexity_reason": "почему задача настолько сложная в исполнении",
  "blocking_risks": ["cloudflare", "payments", "fiscalization"],
  "compliance_risk": "low | medium | high",
  "failure_cost": "low | medium | high",
  "agent_check_prompt": "готовый prompt для делегирования агенту техпроверки"
}

Правила:
- `blocking_risks` — максимум 5 коротких рисков.
- Учитывай подводные камни вроде Cloudflare, Telegram moderation, касс/фискализации,
  эквайринга, PII, интеграций, rate limits, сторонних API, развёртывания и поддержки.
- `agent_check_prompt` должен просить агента оценить реализуемость, скрытые риски,
  сложность, вопросы к клиенту и предложить короткий план проверки.
"""


class DecisionEnricher:
    async def enrich(self, candidate: JobCandidateRead, profile: dict) -> dict[str, Any]:
        try:
            return await self._enrich_impl(candidate, profile)
        except Exception:
            logger.exception("Decision enrichment failed")
            return _default_enrichment()

    async def _enrich_impl(self, candidate: JobCandidateRead, profile: dict) -> dict[str, Any]:
        user_prompt = _build_user_prompt(candidate, profile)

        brief_raw = await chat_completion(
            messages=[
                {"role": "system", "content": BRIEF_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=420,
            response_format={"type": "json_object"},
        )
        brief_data = _load_json_response(brief_raw)

        execution_raw = await chat_completion(
            messages=[
                {"role": "system", "content": EXECUTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=380,
            response_format={"type": "json_object"},
        )
        execution_data = _load_json_response(execution_raw)

        enriched = _default_enrichment()
        enriched.update({
            "deliverable_type": _string_field(brief_data.get("deliverable_type"), "other"),
            "scope_size": _string_field(brief_data.get("scope_size"), "medium"),
            "scope_clarity_reason": _string_field(brief_data.get("scope_clarity_reason"), ""),
            "repeatability_fit": _string_field(brief_data.get("repeatability_fit"), "medium"),
            "manual_load_risk": _string_field(brief_data.get("manual_load_risk"), "medium"),
            "recommended_mode": _string_field(
                brief_data.get("recommended_mode"), "take_with_questions"
            ),
            "reply_strategy": _string_field(
                brief_data.get("reply_strategy"), "ask_scope_first"
            ),
            "first_milestone": _string_field(brief_data.get("first_milestone"), ""),
            "what_to_offer": _string_field(brief_data.get("what_to_offer"), ""),
            "questions_to_client": _string_list(brief_data.get("questions_to_client")),
            "agent_brief": _string_field(brief_data.get("agent_brief"), ""),
            "execution_complexity": _string_field(
                execution_data.get("execution_complexity"), "medium"
            ),
            "complexity_reason": _string_field(execution_data.get("complexity_reason"), ""),
            "blocking_risks": _string_list(execution_data.get("blocking_risks"), limit=5),
            "compliance_risk": _string_field(
                execution_data.get("compliance_risk"), "medium"
            ),
            "failure_cost": _string_field(execution_data.get("failure_cost"), "medium"),
            "agent_check_prompt": _string_field(
                execution_data.get("agent_check_prompt"),
                _fallback_agent_prompt(candidate),
            ),
        })
        return enriched


def _build_user_prompt(candidate: JobCandidateRead, profile: dict) -> str:
    budget_str = "не указан"
    if candidate.budget_min or candidate.budget_max:
        budget_str = f"{candidate.budget_min or '?'} — {candidate.budget_max or '?'} руб."

    source_meta = candidate.raw_data or {}
    return f"""Проект:
Название: {candidate.title}
Описание: {candidate.description or 'нет описания'}
Бюджет: {budget_str}
Категория: {candidate.category or 'не указана'}
Источник: {candidate.source}
Source quality: {source_meta.get('source_quality', 'unknown')}
Category hint: {source_meta.get('category_hint', 'unknown')}

Навыки исполнителя: {", ".join(profile.get("primary_skills", []))}
Вторичные навыки: {", ".join(profile.get("secondary_skills", []))}
"""


def _load_json_response(response: str) -> dict[str, Any]:
    text = (response or "").strip()
    if not text:
        raise ValueError("Empty JSON response")

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        snippet = text[start : end + 1]
        data = json.loads(snippet)
        if isinstance(data, dict):
            return data

    raise ValueError("Model did not return a JSON object")


def _default_enrichment() -> dict[str, Any]:
    return {
        "deliverable_type": "other",
        "scope_size": "medium",
        "scope_clarity_reason": "Не удалось построить enrichment.",
        "repeatability_fit": "medium",
        "manual_load_risk": "medium",
        "execution_complexity": "medium",
        "complexity_reason": "",
        "blocking_risks": [],
        "compliance_risk": "medium",
        "failure_cost": "medium",
        "recommended_mode": "ask_scope_first",
        "reply_strategy": "ask_scope_first",
        "first_milestone": "",
        "what_to_offer": "",
        "questions_to_client": [],
        "agent_brief": "",
        "agent_check_prompt": "",
    }


def _fallback_agent_prompt(candidate: JobCandidateRead) -> str:
    return (
        "Проверь этот заказ на реализуемость и скрытые риски.\n"
        f"Название: {candidate.title}\n"
        f"Описание: {candidate.description or 'нет описания'}\n"
        "Дай ответ в JSON с полями: feasibility, execution_complexity, key_risks, "
        "questions_to_client, proposed_plan, go_no_go."
    )


def _string_field(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _string_list(value: Any, limit: int = 4) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]
