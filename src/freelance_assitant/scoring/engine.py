"""Composite scoring engine — orchestrates scorer pipeline."""

from __future__ import annotations

import logging
from typing import Any

import yaml

from freelance_assitant.config import CONFIG_DIR
from freelance_assitant.domain.enums import LeadTier
from freelance_assitant.domain.schemas import JobCandidateRead, ScoringResult
from freelance_assitant.scoring.base import BaseScorer
from freelance_assitant.scoring.decision_enricher import DecisionEnricher
from freelance_assitant.scoring.llm_scorer import LLMAdvisoryScorer
from freelance_assitant.scoring.profile import load_profile
from freelance_assitant.scoring.rules import (
    FastCloseFitScorer,
    MoneyFitScorer,
    RiskScorer,
    SkillFitScorer,
    SourceFitScorer,
)

logger = logging.getLogger("fa.scoring")


def _load_scoring_config() -> dict[str, Any]:
    path = CONFIG_DIR / "scoring.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


class ScoringEngine:
    """Pipeline of scorers with configurable weights.

    To add a new scorer:
    1. Create a BaseScorer subclass
    2. Add it to `_build_scorers()` or register dynamically
    3. Add weight in config/scoring.yaml
    """

    def __init__(
        self,
        scorers: list[BaseScorer] | None = None,
        weights: dict[str, float] | None = None,
        a_threshold: float = 0.7,
        b_threshold: float = 0.4,
        llm_min_threshold: float = 0.5,
        llm_blend_weight: float = 0.35,
    ):
        config = _load_scoring_config()
        self.scorers = scorers or self._build_default_scorers()
        self.weights = weights or config.get("weights", {
            "skill_fit": 0.35,
            "money_fit": 0.30,
            "fast_close_fit": 0.20,
            "source_fit": 0.15,
            "risk_score": 0.15,
        })
        thresholds = config.get("thresholds", {})
        self.a_threshold = thresholds.get("a_lead", a_threshold)
        self.b_threshold = thresholds.get("b_lead", b_threshold)
        self.llm_min_threshold = config.get("llm_score_min_threshold", llm_min_threshold)
        self.llm_blend_weight = config.get("llm_blend_weight", llm_blend_weight)
        self.shortlist_score_threshold = config.get("shortlist_score_threshold", 0.64)
        self.shortlist_scope_threshold = config.get("shortlist_scope_threshold", 0.60)
        self.shortlist_grey_risk_max = config.get("shortlist_grey_risk_max", 0.30)
        self.hard_reject_llm_max = config.get("hard_reject_llm_max", 0.20)
        self.hard_reject_grey_risk = config.get("hard_reject_grey_risk", 0.70)
        self._llm_scorer = LLMAdvisoryScorer()
        self._decision_enricher = DecisionEnricher()

    async def score(
        self,
        candidate: JobCandidateRead,
        profile: dict[str, Any] | None = None,
    ) -> ScoringResult:
        if profile is None:
            profile = load_profile()
        details: dict[str, float] = {}
        reasons: list[str] = []

        # Run rule-based scorers
        for scorer in self.scorers:
            value = await scorer.evaluate(candidate, profile)
            details[scorer.name] = round(value, 3)

        # Compute composite
        composite = self._compute_composite(details)

        # LLM ranking for borderline/high-potential or high-signal leads
        if composite >= self.llm_min_threshold or details.get("source_fit", 0) >= 0.8:
            try:
                llm_assessment = await self._llm_scorer.assess(candidate, profile)
                llm_score = float(llm_assessment.get("fit", 0.5))
                details["llm_advisory"] = round(llm_score, 3)
                details["llm_scope_clarity"] = round(
                    float(llm_assessment.get("scope_clarity", 0.5)), 3
                )
                details["llm_automation_leverage"] = round(
                    float(llm_assessment.get("automation_leverage", 0.5)), 3
                )
                details["llm_repeatability"] = round(
                    float(llm_assessment.get("repeatability", 0.5)), 3
                )
                details["llm_grey_risk"] = round(float(llm_assessment.get("grey_risk", 0.5)), 3)
                details["llm_delivery_risk"] = round(
                    float(llm_assessment.get("delivery_risk", 0.5)), 3
                )
                details["llm_reasoning"] = llm_assessment.get("reasoning", "")
                details["llm_decisive_signals"] = llm_assessment.get("decisive_signals", [])
                details["llm_reject_reasons"] = llm_assessment.get("reject_reasons", [])
                composite = (
                    composite * (1 - self.llm_blend_weight)
                    + llm_score * self.llm_blend_weight
                )
            except Exception:
                logger.debug("LLM scoring skipped (error)")

        composite = round(max(0.0, min(1.0, composite)), 3)
        tier = self._classify(composite)
        shortlist = self._should_shortlist(composite, tier, details)
        details["shortlist_fit"] = shortlist
        details["hard_reject"] = self._is_hard_reject(details)
        if shortlist and not details["hard_reject"]:
            try:
                details["decision_enrichment"] = await self._decision_enricher.enrich(
                    candidate, profile
                )
            except Exception:
                logger.debug("Decision enrichment skipped (error)")

        # Build human-readable reasons
        if details.get("risk_score", 0) > 0.5:
            reasons.append("High risk signals detected")
        if details.get("skill_fit", 0) > 0.7:
            reasons.append("Strong skill match")
        if details.get("money_fit", 0) > 0.7:
            reasons.append("Good budget")
        if details.get("source_fit", 0) > 0.7:
            reasons.append("High-signal source")
        if details.get("llm_scope_clarity", 0) > 0.7:
            reasons.append("Clear scope")
        if details.get("llm_grey_risk", 0) > 0.6:
            reasons.append("Grey-risk topic")
        if tier == LeadTier.A:
            reasons.append("A-lead: push to Telegram")
        elif shortlist:
            reasons.append("Shortlist-worthy B lead")

        return ScoringResult(
            score=composite,
            tier=tier,
            shortlist=shortlist,
            details=details,
            reasons=reasons,
        )

    def _compute_composite(self, details: dict[str, float]) -> float:
        score = 0.0
        for name, weight in self.weights.items():
            value = details.get(name, 0.0)
            if name == "risk_score":
                score -= weight * value
            else:
                score += weight * value
        return score

    def _classify(self, score: float) -> LeadTier:
        if score >= self.a_threshold:
            return LeadTier.A
        if score >= self.b_threshold:
            return LeadTier.B
        return LeadTier.C

    def _should_shortlist(self, score: float, tier: LeadTier, details: dict[str, Any]) -> bool:
        if self._is_hard_reject(details):
            return False
        if tier == LeadTier.A:
            return True
        if score < self.shortlist_score_threshold:
            return False
        llm_clarity = float(details.get("llm_scope_clarity", 0.0) or 0.0)
        llm_grey_risk = float(details.get("llm_grey_risk", 0.0) or 0.0)
        llm_fit = float(details.get("llm_advisory", 0.0) or 0.0)
        return (
            llm_fit > self.hard_reject_llm_max
            and llm_clarity >= self.shortlist_scope_threshold
            and llm_grey_risk <= self.shortlist_grey_risk_max
        )

    def _is_hard_reject(self, details: dict[str, Any]) -> bool:
        llm_fit = float(details.get("llm_advisory", 1.0) or 1.0)
        llm_grey_risk = float(details.get("llm_grey_risk", 0.0) or 0.0)
        return llm_fit <= self.hard_reject_llm_max or llm_grey_risk >= self.hard_reject_grey_risk

    @staticmethod
    def _build_default_scorers() -> list[BaseScorer]:
        return [
            SkillFitScorer(),
            MoneyFitScorer(),
            FastCloseFitScorer(),
            SourceFitScorer(),
            RiskScorer(),
        ]
