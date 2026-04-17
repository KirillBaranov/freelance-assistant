"""Load case snippets from config/cases/ YAML files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from freelance_assitant.config import CONFIG_DIR

logger = logging.getLogger("fa.proposal.cases")

_cases: list[dict[str, Any]] | None = None


def load_cases() -> list[dict[str, Any]]:
    """Load all case snippets from config/cases/*.yaml."""
    global _cases
    if _cases is not None:
        return _cases

    cases_dir = CONFIG_DIR / "cases"
    if not cases_dir.exists():
        _cases = []
        return _cases

    _cases = []
    for path in sorted(cases_dir.glob("*.yaml")):
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
                if data:
                    data["_file"] = path.stem
                    _cases.append(data)
        except Exception:
            logger.exception(f"Failed to load case: {path}")

    logger.info(f"Loaded {len(_cases)} case snippets")
    return _cases


def find_relevant_cases(
    text: str,
    stack: list[str] | None = None,
    max_cases: int = 3,
) -> list[dict[str, Any]]:
    """Find the most relevant case snippets for a job description."""
    cases = load_cases()
    if not cases:
        return []

    text_lower = text.lower()
    stack_lower = {s.lower() for s in (stack or [])}

    scored: list[tuple[float, dict]] = []
    for case in cases:
        score = 0.0

        # Match by stack overlap
        case_stack = {s.lower() for s in case.get("stack", [])}
        overlap = case_stack & stack_lower
        if overlap:
            score += len(overlap) * 2.0

        # Match by domain keywords in text
        for domain in case.get("domain", []):
            if domain.lower() in text_lower:
                score += 1.5

        # Match by project_type
        if case.get("project_type", "").lower() in text_lower:
            score += 2.0

        # Match by title keywords
        title_words = case.get("title", "").lower().split()
        for w in title_words:
            if w in text_lower and len(w) > 3:
                score += 0.5

        if score > 0:
            scored.append((score, case))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:max_cases]]


def format_case_for_prompt(case: dict[str, Any]) -> str:
    """Format a case snippet for inclusion in LLM prompt."""
    lines = [f"**{case.get('title', 'Case')}**"]
    if case.get("problem"):
        lines.append(f"Задача: {case['problem']}")
    if case.get("solution"):
        lines.append(f"Решение: {case['solution']}")
    if case.get("outcome"):
        lines.append(f"Результат: {case['outcome']}")
    if case.get("proof_points"):
        for point in case["proof_points"][:2]:
            lines.append(f"- {point}")
    return "\n".join(lines)
