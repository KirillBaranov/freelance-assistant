from __future__ import annotations

import pytest

from freelance_assitant.collectors.workspace import WorkspaceCollector
from freelance_assitant.config import Settings, WorkspaceSectionConfig
from freelance_assitant.storage.source_state import MemorySourceStateStore, make_state_key


@pytest.fixture
def collector() -> WorkspaceCollector:
    return WorkspaceCollector(
        Settings(
            telegram_bot_token="test",
            telegram_owner_id=1,
            llm_api_key="test",
            enabled_sources=["workspace"],
        ),
        state_store=MemorySourceStateStore(),
    )


def _mock_sources(monkeypatch, sections, poll_seconds: int = 600):
    fake_sources = type(
        "Sources",
        (),
        {
            "workspace": type(
                "WorkspaceSource",
                (),
                {"sections": sections, "poll_seconds": poll_seconds},
            )()
        },
    )()
    monkeypatch.setattr(
        "freelance_assitant.collectors.workspace.load_sources_config",
        lambda: fake_sources,
    )


def test_extract_cards_parses_budget_and_dates():
    html = """
    <div class="vacancies__card _tender" data-tender-card>
      <div class="b-tender__block--title">
        <div class="b-tender__title _wide">
          <a href="/tenders/chat-bot-dlya-avtomatizacii-18463/">Чат-бот для автоматизации</a>
        </div>
        <div class="b-tender__info-item-text">100 000 - 300 000 <span class="rub _bold"></span></div>
      </div>
      <div class="b-tender__info">
        <div class="b-tender__info-item"><div class="b-tender__info-item-text">13 апреля 2026</div></div>
        <div class="b-tender__info-item"><div class="b-tender__info-item-text">20 апреля 2026</div></div>
      </div>
    </div>
    """
    section = WorkspaceSectionConfig(url="https://workspace.ru/tenders/crm/", label="crm")
    cards = WorkspaceCollector._extract_cards(html, section)

    assert len(cards) == 1
    assert cards[0]["source_id"] == "18463"
    assert cards[0]["budget_min"] == 100000
    assert cards[0]["budget_max"] == 300000
    assert cards[0]["published_at"] == "13 апреля 2026"
    assert cards[0]["deadline"] == "20 апреля 2026"


def test_extract_detail_returns_description():
    html = """
    <div class="tendercart__shot-description-top">
      Нужен Telegram-бот с админкой.
      Поддержка aiogram и PostgreSQL.
    </div>
    <div class="specialization-section"><span>Разработка чат-ботов и Mini Apps</span></div>
    """
    description, category = WorkspaceCollector._extract_detail(html)

    assert "Telegram-бот" in description
    assert "aiogram" in description
    assert category == "Разработка чат-ботов и Mini Apps"


@pytest.mark.asyncio
async def test_collect_section_stops_after_known_streak(httpx_mock, monkeypatch):
    list_html = """
    <div class="vacancies__card _tender" data-tender-card>
      <div class="b-tender__block--title">
        <div class="b-tender__title _wide"><a href="/tenders/new-bot-2001/">Новый бот</a></div>
        <div class="b-tender__info-item-text">до 120 000 <span class="rub _bold"></span></div>
      </div>
      <div class="b-tender__info">
        <div class="b-tender__info-item"><div class="b-tender__info-item-text">16 апреля 2026</div></div>
        <div class="b-tender__info-item"><div class="b-tender__info-item-text">25 апреля 2026</div></div>
      </div>
    </div>
    <div class="vacancies__card _tender" data-tender-card>
      <div class="b-tender__block--title">
        <div class="b-tender__title _wide"><a href="/tenders/new-parser-2002/">Новый парсер</a></div>
        <div class="b-tender__info-item-text">100 000 - 300 000 <span class="rub _bold"></span></div>
      </div>
      <div class="b-tender__info">
        <div class="b-tender__info-item"><div class="b-tender__info-item-text">16 апреля 2026</div></div>
        <div class="b-tender__info-item"><div class="b-tender__info-item-text">27 апреля 2026</div></div>
      </div>
    </div>
    <div class="vacancies__card _tender" data-tender-card>
      <div class="b-tender__block--title">
        <div class="b-tender__title _wide"><a href="/tenders/old-1-1003/">Старый 1</a></div>
      </div>
    </div>
    <div class="vacancies__card _tender" data-tender-card>
      <div class="b-tender__block--title">
        <div class="b-tender__title _wide"><a href="/tenders/old-2-1004/">Старый 2</a></div>
      </div>
    </div>
    <div class="vacancies__card _tender" data-tender-card>
      <div class="b-tender__block--title">
        <div class="b-tender__title _wide"><a href="/tenders/old-3-1005/">Старый 3</a></div>
      </div>
    </div>
    <div class="vacancies__card _tender" data-tender-card>
      <div class="b-tender__block--title">
        <div class="b-tender__title _wide"><a href="/tenders/ignored-1006/">Ignored</a></div>
      </div>
    </div>
    """
    detail_html = """
    <div class="tendercart__shot-description-top">Нужно сделать Telegram-бота и backend.</div>
    <div class="specialization-section"><span>Разработка чат-ботов и Mini Apps</span></div>
    """
    section = WorkspaceSectionConfig(
        url="https://workspace.ru/tenders/crm/",
        label="crm",
        category_hint="CRM, 1C, ПО, чат-боты, администрирование",
    )
    _mock_sources(monkeypatch, [section])
    state_store = MemorySourceStateStore()
    await state_store.set_json(
        make_state_key("workspace", section.url),
        {"recent_source_ids": ["1003", "1004", "1005", "1006"]},
    )
    collector = WorkspaceCollector(
        Settings(
            telegram_bot_token="test",
            telegram_owner_id=1,
            llm_api_key="test",
            enabled_sources=["workspace"],
        ),
        state_store=state_store,
    )

    httpx_mock.add_response(url=section.url, text=list_html)
    httpx_mock.add_response(url="https://workspace.ru/tenders/new-bot-2001/", text=detail_html)
    httpx_mock.add_response(url="https://workspace.ru/tenders/new-parser-2002/", text=detail_html)

    candidates = await collector.collect()

    assert [candidate.source_id for candidate in candidates] == ["2001", "2002"]
    assert candidates[0].raw_data["source_quality"] == "high"
    assert candidates[0].raw_data["ingest_variant"] == "html_tender_list"
