"""Send lead notifications to the bot owner."""

from __future__ import annotations

import logging

from aiogram import Bot

from freelance_assitant.bot.keyboard import lead_keyboard
from freelance_assitant.domain.enums import LeadTier
from freelance_assitant.domain.schemas import JobCandidateRead

logger = logging.getLogger("fa.bot.notify")

TIER_EMOJI = {
    LeadTier.A: "🅰",
    LeadTier.B: "🅱",
    LeadTier.C: "©",
}

SOURCE_NAMES = {
    "fl_ru": "FL.ru",
    "kwork": "Kwork",
    "workspace": "Workspace",
    "telegram": "Telegram",
    "freelance_ru": "Freelance.ru",
}


def format_lead_message(candidate: JobCandidateRead) -> str:
    tier_emoji = TIER_EMOJI.get(candidate.tier, "❓")
    source_name = SOURCE_NAMES.get(candidate.source, candidate.source)
    score_str = f"{candidate.score:.2f}" if candidate.score else "?"

    lines = [
        f"{tier_emoji} <b>{candidate.tier}-лид</b> · {source_name} · score {score_str}",
        "",
        f"<b>{_esc(candidate.title)}</b>",
    ]

    if candidate.budget_min or candidate.budget_max:
        bmin = f"{candidate.budget_min:,}" if candidate.budget_min else "?"
        bmax = f"{candidate.budget_max:,}" if candidate.budget_max else "?"
        budget_str = bmin if bmin == bmax else f"{bmin} — {bmax}"
        lines.append(f"💰 {budget_str} ₽")

    if candidate.category:
        lines.append(f"🏷 {_esc(candidate.category)}")

    if candidate.description:
        desc = candidate.description[:300].strip()
        if len(candidate.description) > 300:
            desc += "..."
        lines.append(f"\n{_esc(desc)}")

    if candidate.score_details:
        details = candidate.score_details
        parts: list[str] = []
        for key in ("skill_fit", "money_fit", "fast_close_fit", "llm_advisory"):
            val = details.get(key)
            if isinstance(val, float):
                label = key.replace("_fit", "").replace("llm_", "")
                parts.append(f"{label}: {val:.2f}")
        if parts:
            lines.append(f"\n📊 {' · '.join(parts)}")

        enrich = details.get("decision_enrichment")
        if isinstance(enrich, dict):
            brief = str(enrich.get("agent_brief") or "").strip()
            if brief:
                lines.append(f"\n💡 {_esc(brief[:250])}")
            risks = enrich.get("blocking_risks") or []
            if isinstance(risks, list) and risks:
                lines.append(f"⚠️ {_esc(', '.join(str(r) for r in risks[:2]))}")

    return "\n".join(lines)


async def send_lead_notification(
    bot: Bot,
    owner_id: int,
    candidate: JobCandidateRead,
) -> int | None:
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


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
