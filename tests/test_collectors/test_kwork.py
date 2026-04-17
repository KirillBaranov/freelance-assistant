"""Tests for Kwork collector."""

from __future__ import annotations

import pytest

from freelance_assitant.collectors.kwork import KworkCollector
from freelance_assitant.config import KworkCategoryConfig, Settings
from freelance_assitant.storage.source_state import MemorySourceStateStore, make_state_key


@pytest.fixture
def collector() -> KworkCollector:
    return KworkCollector(
        Settings(
            telegram_bot_token="test",
            telegram_owner_id=1,
            llm_api_key="test",
            enabled_sources=["kwork"],
        ),
        state_store=MemorySourceStateStore(),
    )


def test_extract_state_data_uses_raw_decode():
    html = """
    <html><body><script>
    window.stateData = {
        "wantsListData": {"pagination": {"data": [{"id": 123, "name": "API integration"}]}}
    };
    window.otherData = {"ok": true};
    </script></body></html>
    """

    data = KworkCollector._extract_state_data(html)

    assert data is not None
    assert data["wantsListData"]["pagination"]["data"][0]["id"] == 123


def test_extract_projects_handles_nested_state():
    state_data = {
        "pageData": {
            "foo": {
                "bar": {
                    "pagination": {
                        "data": [
                            {"id": 1, "title": "Нужен бот", "description": "aiogram"},
                            {"id": 2, "title": "Нужен парсер", "description": "python"},
                        ]
                    }
                }
            }
        }
    }

    projects = KworkCollector._extract_projects(state_data)

    assert len(projects) == 2
    assert projects[0]["id"] == 1


def test_parse_project_normalizes_source_metadata(collector: KworkCollector):
    project = {
        "id": 987,
        "name": "Интеграция Telegram и CRM",
        "description": "Нужен backend на Python",
        "price_limit": "25000",
        "user": {"username": "client42"},
    }
    category = KworkCategoryConfig(
        id=79,
        label="Боты и чат-боты",
        source_quality="high",
        source_bucket="programming_marketplace",
    )

    candidate = collector._parse_project(project, category)

    assert candidate.source_id == "987"
    assert candidate.budget_max == 25000
    assert candidate.category == "Боты и чат-боты"
    assert candidate.raw_data["source_quality"] == "high"
    assert candidate.raw_data["category_id"] == 79
    assert candidate.raw_data["ingest_variant"] == "embedded_state"


@pytest.mark.asyncio
async def test_collect_category_stops_after_known_streak(httpx_mock):
    html = """
    <html><body><script>
    window.stateData = {
        "wantsListData": {
            "pagination": {
                "data": [
                    {"id": 1001, "name": "Новый бот", "description": "aiogram"},
                    {"id": 1002, "name": "Новый парсер", "description": "python"},
                    {"id": 1003, "name": "Старый 1", "description": "legacy"},
                    {"id": 1004, "name": "Старый 2", "description": "legacy"},
                    {"id": 1005, "name": "Старый 3", "description": "legacy"},
                    {"id": 1006, "name": "Не должны дойти", "description": "legacy"}
                ]
            }
        }
    };
    </script></body></html>
    """
    state_store = MemorySourceStateStore()
    await state_store.set_json(
        make_state_key("kwork", "category:79"),
        {"recent_source_ids": ["1003", "1004", "1005", "1006"]},
    )
    collector = KworkCollector(
        Settings(
            telegram_bot_token="test",
            telegram_owner_id=1,
            llm_api_key="test",
            enabled_sources=["kwork"],
        ),
        state_store=state_store,
    )
    httpx_mock.add_response(url="https://kwork.ru/projects?c=79", text=html)
    category = KworkCategoryConfig(id=79, label="Боты и чат-боты")

    candidates = await collector._collect_category(category)

    assert [candidate.source_id for candidate in candidates] == ["1001", "1002"]
