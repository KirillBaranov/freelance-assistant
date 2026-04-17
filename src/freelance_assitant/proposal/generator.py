"""LLM-powered proposal generation."""

from __future__ import annotations

import logging

from freelance_assitant.domain.schemas import JobCandidateRead
from freelance_assitant.proposal.cases import find_relevant_cases, format_case_for_prompt
from freelance_assitant.proposal.templates import (
    QUALIFIED_BID_TEMPLATE,
    QUICK_BID_TEMPLATE,
    SYSTEM_PROMPT,
)
from freelance_assitant.scoring.profile import load_profile
from freelance_assitant.services.llm import chat_completion

logger = logging.getLogger("fa.proposal")


async def generate_proposal(
    candidate: JobCandidateRead,
    mode: str = "auto",
    temperature: float = 0.7,
) -> str:
    """Generate a proposal draft for a candidate.

    Modes:
    - "quick" — short bid for small/fast jobs
    - "qualified" — detailed bid for larger projects
    - "auto" — choose based on budget and complexity
    """
    profile = load_profile()

    # Auto-detect mode
    if mode == "auto":
        mode = _detect_mode(candidate)

    # Find relevant cases
    text = f"{candidate.title} {candidate.description or ''}"
    cases = find_relevant_cases(text, profile.get("primary_skills", []))

    # Format cases for prompt
    if cases:
        cases_text = "Релевантные кейсы разработчика:\n\n" + "\n\n".join(
            format_case_for_prompt(c) for c in cases
        )
    else:
        cases_text = "Кейсы: нет подходящих, используй общий опыт Python-разработки"

    # Format budget
    budget_str = "не указан"
    if candidate.budget_min or candidate.budget_max:
        bmin = candidate.budget_min or candidate.budget_max
        bmax = candidate.budget_max or candidate.budget_min
        budget_str = f"{bmin:,} — {bmax:,} руб." if bmin != bmax else f"{bmin:,} руб."

    # Choose template
    if mode == "quick":
        template = QUICK_BID_TEMPLATE
    else:
        template = QUALIFIED_BID_TEMPLATE

    user_prompt = template.format(
        title=candidate.title,
        description=candidate.description or "нет подробного описания",
        budget=budget_str,
        category=candidate.category or "не указана",
        cases_section=cases_text,
        skills=", ".join(profile.get("primary_skills", [])),
    )

    draft = await chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=800,
    )

    logger.info(f"Generated {mode} proposal for '{candidate.title[:50]}' ({len(draft)} chars)")
    return draft.strip()


def _detect_mode(candidate: JobCandidateRead) -> str:
    """Auto-detect proposal mode based on job characteristics."""
    budget = candidate.budget_max or candidate.budget_min or 0

    # Quick bid for small/fast jobs
    if budget > 0 and budget <= 5000:
        return "quick"

    text = f"{candidate.title} {candidate.description or ''}".lower()
    quick_signals = ["срочно", "быстро", "простой", "скрипт", "фикс", "мелк", "парсер"]
    if any(s in text for s in quick_signals):
        return "quick"

    return "qualified"
