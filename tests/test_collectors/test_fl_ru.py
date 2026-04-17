"""Tests for FL.ru RSS collector."""

from __future__ import annotations

from pathlib import Path

import pytest

from freelance_assitant.collectors.fl_ru import FlRuCollector
from freelance_assitant.config import FlRuFeedConfig, Settings
from freelance_assitant.domain.enums import SourcePlatform
from freelance_assitant.storage.source_state import MemorySourceStateStore, make_state_key

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def config() -> Settings:
    return Settings(
        telegram_bot_token="test",
        telegram_owner_id=1,
        llm_api_key="test",
        enabled_sources=["fl_ru"],
    )


@pytest.fixture
def collector(config: Settings) -> FlRuCollector:
    return FlRuCollector(config, state_store=MemorySourceStateStore())


def _mock_sources(monkeypatch, feeds, poll_seconds: int = 180):
    fake_sources = type(
        "Sources",
        (),
        {
            "fl_ru": type(
                "FlRuSource",
                (),
                {"feeds": feeds, "poll_seconds": poll_seconds},
            )()
        },
    )()
    monkeypatch.setattr(
        "freelance_assitant.collectors.fl_ru.load_sources_config",
        lambda: fake_sources,
    )


@pytest.fixture
def rss_xml() -> str:
    return (FIXTURES / "fl_ru_rss.xml").read_text()


@pytest.mark.asyncio
async def test_collect_parses_rss(
    collector: FlRuCollector,
    rss_xml: str,
    httpx_mock,
    monkeypatch,
):
    _mock_sources(
        monkeypatch,
        [
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/all.xml",
                label="all",
                source_quality="low",
                source_bucket="broad_feed",
            )
        ],
    )
    collector = FlRuCollector(collector.config, state_store=collector.state_store)
    httpx_mock.add_response(url="https://www.fl.ru/rss/all.xml", text=rss_xml)

    candidates = await collector.collect()

    assert len(candidates) == 4


@pytest.mark.asyncio
async def test_budget_extraction(collector: FlRuCollector, rss_xml: str, httpx_mock, monkeypatch):
    _mock_sources(
        monkeypatch,
        [
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/all.xml",
                label="all",
                source_quality="low",
                source_bucket="broad_feed",
            )
        ],
    )
    collector = FlRuCollector(collector.config, state_store=collector.state_store)
    httpx_mock.add_response(url="https://www.fl.ru/rss/all.xml", text=rss_xml)

    candidates = await collector.collect()

    # "Бюджет: 15 000 ₽"
    tg_bot = next(c for c in candidates if "5500100" in c.source_id)
    assert tg_bot.budget_min == 15000
    assert tg_bot.budget_max == 15000

    # "для всех" — no budget
    uber = next(c for c in candidates if "5500300" in c.source_id)
    assert uber.budget_min is None
    assert uber.budget_max is None


@pytest.mark.asyncio
async def test_title_cleaned(collector: FlRuCollector, rss_xml: str, httpx_mock, monkeypatch):
    _mock_sources(
        monkeypatch,
        [
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/all.xml",
                label="all",
                source_quality="low",
                source_bucket="broad_feed",
            )
        ],
    )
    collector = FlRuCollector(collector.config, state_store=collector.state_store)
    httpx_mock.add_response(url="https://www.fl.ru/rss/all.xml", text=rss_xml)

    candidates = await collector.collect()

    tg_bot = next(c for c in candidates if "5500100" in c.source_id)
    assert "Бюджет" not in tg_bot.title
    assert "Telegram-бота" in tg_bot.title

    uber = next(c for c in candidates if "5500300" in c.source_id)
    assert "(для всех)" not in uber.title


@pytest.mark.asyncio
async def test_source_id_extraction(
    collector: FlRuCollector,
    rss_xml: str,
    httpx_mock,
    monkeypatch,
):
    _mock_sources(
        monkeypatch,
        [
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/all.xml",
                label="all",
                source_quality="low",
                source_bucket="broad_feed",
            )
        ],
    )
    collector = FlRuCollector(collector.config, state_store=collector.state_store)
    httpx_mock.add_response(url="https://www.fl.ru/rss/all.xml", text=rss_xml)

    candidates = await collector.collect()

    assert candidates[0].source_id == "5500100"
    assert candidates[0].source == SourcePlatform.FL_RU
    assert candidates[0].source_url.startswith("https://www.fl.ru/projects/")


@pytest.mark.asyncio
async def test_category_parsed(
    collector: FlRuCollector,
    rss_xml: str,
    httpx_mock,
    monkeypatch,
):
    _mock_sources(
        monkeypatch,
        [
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/all.xml",
                label="all",
                source_quality="low",
                source_bucket="broad_feed",
            )
        ],
    )
    collector = FlRuCollector(collector.config, state_store=collector.state_store)
    httpx_mock.add_response(url="https://www.fl.ru/rss/all.xml", text=rss_xml)

    candidates = await collector.collect()

    tg_bot = next(c for c in candidates if "5500100" in c.source_id)
    assert "Боты" in tg_bot.category or "Программирование" in tg_bot.category


@pytest.mark.asyncio
async def test_description_present(
    collector: FlRuCollector,
    rss_xml: str,
    httpx_mock,
    monkeypatch,
):
    _mock_sources(
        monkeypatch,
        [
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/all.xml",
                label="all",
                source_quality="low",
                source_bucket="broad_feed",
            )
        ],
    )
    collector = FlRuCollector(collector.config, state_store=collector.state_store)
    httpx_mock.add_response(url="https://www.fl.ru/rss/all.xml", text=rss_xml)

    candidates = await collector.collect()

    tg_bot = next(c for c in candidates if "5500100" in c.source_id)
    assert "aiogram" in tg_bot.description
    assert len(tg_bot.description) > 20


@pytest.mark.asyncio
async def test_collect_deduplicates_and_prefers_high_quality_feed(
    collector: FlRuCollector,
    rss_xml: str,
    httpx_mock,
    monkeypatch,
):
    programming_xml = rss_xml.replace(
        """    <item>
      <title><![CDATA[Нарисовать логотип для кафе (Бюджет: 2 000  &#8381;)]]></title>
      <link>https://www.fl.ru/projects/5500400/narisovat-logotip.html</link>
      <description><![CDATA[Нужен логотип для кафе. Минималистичный стиль.]]></description>
      <guid>https://www.fl.ru/projects/5500400/narisovat-logotip.html</guid>
      <category><![CDATA[Дизайн / Логотипы]]></category>
      <pubDate>Thu, 16 Apr 2026 11:30:00 GMT</pubDate>
    </item>
""",
        "",
    )
    _mock_sources(
        monkeypatch,
        [
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/all.xml",
                label="all",
                source_quality="low",
                source_bucket="broad_feed",
            ),
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/programming.xml",
                label="programming",
                category_hint="Программирование",
                source_quality="high",
                source_bucket="programming_feed",
            ),
        ],
    )
    collector = FlRuCollector(collector.config, state_store=collector.state_store)
    httpx_mock.add_response(url="https://www.fl.ru/rss/all.xml", text=rss_xml)
    httpx_mock.add_response(url="https://www.fl.ru/rss/programming.xml", text=programming_xml)

    candidates = await collector.collect()

    assert len(candidates) == 4
    tg_bot = next(c for c in candidates if c.source_id == "5500100")
    assert set(tg_bot.raw_data["matched_feeds"]) == {"all", "programming"}
    assert tg_bot.raw_data["source_quality"] == "high"
    assert tg_bot.raw_data["source_bucket"] == "programming_feed"


@pytest.mark.asyncio
async def test_collect_filters_noise_from_broad_feed(
    collector: FlRuCollector,
    rss_xml: str,
    httpx_mock,
    monkeypatch,
):
    _mock_sources(
        monkeypatch,
        [
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/all.xml",
                label="all",
                source_quality="low",
                source_bucket="broad_feed",
            )
        ],
    )
    collector = FlRuCollector(collector.config, state_store=collector.state_store)
    httpx_mock.add_response(url="https://www.fl.ru/rss/all.xml", text=rss_xml)

    candidates = await collector.collect()

    assert all(c.source_id != "5500400" for c in candidates)


@pytest.mark.asyncio
async def test_collect_stops_on_known_source_id(
    rss_xml: str,
    httpx_mock,
    monkeypatch,
    config: Settings,
):
    _mock_sources(
        monkeypatch,
        [
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/all.xml",
                label="all",
                source_quality="low",
                source_bucket="broad_feed",
            )
        ],
    )
    state_store = MemorySourceStateStore()
    await state_store.set_json(
        make_state_key("fl_ru", "https://www.fl.ru/rss/all.xml"),
        {"recent_source_ids": ["5500200"]},
    )
    collector = FlRuCollector(config, state_store=state_store)
    httpx_mock.add_response(url="https://www.fl.ru/rss/all.xml", text=rss_xml)

    candidates = await collector.collect()

    assert [candidate.source_id for candidate in candidates] == ["5500100"]


@pytest.mark.asyncio
async def test_collect_uses_conditional_headers(httpx_mock, monkeypatch, config: Settings):
    _mock_sources(
        monkeypatch,
        [
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/all.xml",
                label="all",
                source_quality="low",
                source_bucket="broad_feed",
            )
        ],
    )
    state_store = MemorySourceStateStore()
    await state_store.set_json(
        make_state_key("fl_ru", "https://www.fl.ru/rss/all.xml"),
        {"etag": "etag-1", "last_modified": "Wed, 15 Apr 2026 10:00:00 GMT"},
    )
    collector = FlRuCollector(config, state_store=state_store)
    httpx_mock.add_response(
        url="https://www.fl.ru/rss/all.xml",
        status_code=304,
        match_headers={
            "If-None-Match": "etag-1",
            "If-Modified-Since": "Wed, 15 Apr 2026 10:00:00 GMT",
        },
    )

    candidates = await collector.collect()

    assert candidates == []
