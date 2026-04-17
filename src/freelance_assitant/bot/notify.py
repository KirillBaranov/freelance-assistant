"""Send lead notifications to the bot owner."""

from __future__ import annotations

import logging

from aiogram import Bot

from freelance_assitant.bot.keyboard import lead_keyboard
from freelance_assitant.domain.enums import LeadTier
from freelance_assitant.domain.schemas import JobCandidateRead

logger = logging.getLogger("fa.bot.notify")

TIER_EMOJI = {
    LeadTier.A: "\ud83c\udd70\ufe0f",
    LeadTier.B: "\ud83c\udd71\ufe0f",
    LeadTier.C: "\u24b8",
}

SOURCE_NAMES = {
    "fl_ru": "FL.ru",
    "kwork": "Kwork",
    "workspace": "Workspace",
    "telegram": "Telegram",
    "freelance_ru": "Freelance.ru",
}


def format_lead_message(candidate: JobCandidateRead) -> str:
    """Format a lead notification message."""
    tier_emoji = TIER_EMOJI.get(candidate.tier, "\u2753")
    source_name = SOURCE_NAMES.get(candidate.source, candidate.source)
    score_str = f"{candidate.score:.2f}" if candidate.score else "?"

    lines = [
        f"{tier_emoji} <b>{candidate.tier}-Lead</b> | {source_name} | Score: {score_str}",
        "",
        f"\ud83d\udccb <b>{_escape_html(candidate.title)}</b>",
    ]

    # Budget
    if candidate.budget_min or candidate.budget_max:
        bmin = f"{candidate.budget_min:,}" if candidate.budget_min else "?"
        bmax = f"{candidate.budget_max:,}" if candidate.budget_max else "?"
        if bmin == bmax:
            lines.append(f"\ud83d\udcb0 {bmin} \u20bd")
        else:
            lines.append(f"\ud83d\udcb0 {bmin} \u2014 {bmax} \u20bd")

    # Category
    if candidate.category:
        lines.append(f"\ud83c\udff7 {_escape_html(candidate.category)}")

    # Description excerpt
    if candidate.description:
        desc = candidate.description[:200]
        if len(candidate.description) > 200:
            desc += "..."
        lines.append(f"\n{_escape_html(desc)}")

    if candidate.score_details:
        details = candidate.score_details
        summary_parts: list[str] = []
        for key in (
            "skill_fit",
            "money_fit",
            "fast_close_fit",
            "source_fit",
            "llm_advisory",
            "llm_scope_clarity",
            "llm_grey_risk",
        ):
            val = details.get(key)
            if isinstance(val, float):
                summary_parts.append(f"{key.replace('_fit', '').replace('_score', '')}: {val:.2f}")
        if summary_parts:
            lines.append(f"\n\ud83d\udcca {' | '.join(summary_parts)}")

        enrich = details.get("decision_enrichment")
        if isinstance(enrich, dict):
            lines.append("")
            lines.append("<b>Decision</b>")
            mode = enrich.get("recommended_mode")
            complexity = enrich.get("execution_complexity")
            if mode or complexity:
                lines.append(
                    f"mode: {_escape_html(str(mode or '—'))} | complexity: {_escape_html(str(complexity or '—'))}"
                )
            risks = enrich.get("blocking_risks") or []
            if isinstance(risks, list) and risks:
                lines.append(f"risks: {_escape_html(', '.join(str(r) for r in risks[:3]))}")
            brief = str(enrich.get("agent_brief") or "").strip()
            if brief:
                lines.append(_escape_html(brief[:220] + ("..." if len(brief) > 220 else "")))

    return "\n".join(lines)


async def send_lead_notification(
    bot: Bot,
    owner_id: int,
    candidate: JobCandidateRead,
) -> int | None:
    """Send a lead notification to the owner. Returns message_id or None."""
    try:
        text = format_lead_message(candidate)
        kb = lead_keyboard(str(candidate.id), candidate.source_url)
        msg = await bot.send_message(
            chat_id=owner_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logger.info(f"Sent notification for {candidate.id} ({candidate.title[:40]})")
        return msg.message_id
    except Exception:
        logger.exception(f"Failed to send notification for {candidate.id}")
        return None


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
