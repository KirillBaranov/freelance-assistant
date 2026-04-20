from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class FlRuFeedConfig(BaseModel):
    url: str
    label: str
    category_hint: str | None = None
    source_quality: str = "medium"
    source_bucket: str = "broad_feed"
    enabled: bool = True


class FlRuSourceConfig(BaseModel):
    enabled: bool = True
    poll_seconds: int = 180
    feeds: list[FlRuFeedConfig] = Field(
        default_factory=lambda: [
            FlRuFeedConfig(
                url="https://www.fl.ru/rss/all.xml",
                label="all",
                source_quality="low",
                source_bucket="broad_feed",
            )
        ]
    )


class KworkCategoryConfig(BaseModel):
    id: int
    label: str
    source_quality: str = "high"
    source_bucket: str = "programming_marketplace"
    enabled: bool = True


class KworkSourceConfig(BaseModel):
    enabled: bool = False
    poll_seconds: int = 300
    categories: list[KworkCategoryConfig] = Field(
        default_factory=lambda: [
            KworkCategoryConfig(id=41, label="Программирование"),
            KworkCategoryConfig(id=79, label="Боты и чат-боты"),
        ]
    )


class TelegramChannelConfig(BaseModel):
    handle: str
    label: str | None = None
    quality: str = "medium"
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class TelegramSourceConfig(BaseModel):
    enabled: bool = False
    channels: list[TelegramChannelConfig] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class WorkspaceSectionConfig(BaseModel):
    url: str
    label: str
    category_hint: str | None = None
    source_quality: str = "high"
    source_bucket: str = "structured_tender"
    enabled: bool = True


class WorkspaceSourceConfig(BaseModel):
    enabled: bool = False
    poll_seconds: int = 600
    sections: list[WorkspaceSectionConfig] = Field(
        default_factory=lambda: [
            WorkspaceSectionConfig(
                url="https://workspace.ru/tenders/crm/",
                label="crm-bots-admin",
                category_hint="CRM, 1C, ПО, чат-боты, администрирование",
                source_quality="high",
                source_bucket="structured_tender",
            ),
            WorkspaceSectionConfig(
                url="https://workspace.ru/tenders/apps-development/",
                label="apps-development",
                category_hint="Мобильные приложения и сервисы",
                source_quality="medium",
                source_bucket="structured_tender",
            ),
        ]
    )


class FreelanceRuSourceConfig(BaseModel):
    enabled: bool = False
    poll_seconds: int = 600


class SourcesConfig(BaseModel):
    fl_ru: FlRuSourceConfig = Field(default_factory=FlRuSourceConfig)
    kwork: KworkSourceConfig = Field(default_factory=KworkSourceConfig)
    workspace: WorkspaceSourceConfig = Field(default_factory=WorkspaceSourceConfig)
    telegram: TelegramSourceConfig = Field(default_factory=TelegramSourceConfig)
    freelance_ru: FreelanceRuSourceConfig = Field(default_factory=FreelanceRuSourceConfig)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FA_")

    # Database
    database_url: str = "postgresql+asyncpg://fa:fa@localhost:5432/freelance_assistant"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Telegram Bot
    telegram_bot_token: str = ""
    telegram_owner_id: int = 0

    # LLM
    llm_base_url: str = "https://api.kblabs.ru"
    llm_api_key: str = ""
    llm_client_id: str = ""
    llm_client_secret: str = ""
    llm_credentials_path: str = ""
    llm_model: str = "gpt-4o-mini"

    # Agent handoff
    agent_webhook_url: str = ""
    agent_webhook_token: str = ""
    agent_webhook_timeout_seconds: int = 20

    # Polling intervals (seconds)
    fl_poll_seconds: int = 180
    kwork_poll_seconds: int = 300
    workspace_poll_seconds: int = 600

    # Scoring thresholds
    score_a_threshold: float = 0.7
    score_b_threshold: float = 0.4

    # Enabled sources
    enabled_sources: list[str] = Field(default_factory=lambda: ["fl_ru"])

    # Telegram channels (for Telethon, Phase 6)
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_channels: list[str] = Field(default_factory=list)


settings = Settings()


class UserProfile(BaseModel):
    primary_skills: list[str] = Field(default_factory=list)
    secondary_skills: list[str] = Field(default_factory=list)
    preferred_categories: list[str] = Field(default_factory=list)
    avoid_keywords: list[str] = Field(default_factory=list)
    min_budget_rub: int = 2000
    preferred_max_duration_days: int = 14
    sales_style: str = "short_confident"
    languages: list[str] = Field(default_factory=lambda: ["ru"])
    a_threshold: float | None = None          # override global A-tier threshold
    shortlist_threshold: float | None = None  # override global shortlist threshold


class UserConfig(BaseModel):
    telegram_id: int
    name: str = "User"
    profile: UserProfile = Field(default_factory=UserProfile)


@lru_cache(maxsize=1)
def load_users() -> list[UserConfig]:
    users_dir = CONFIG_DIR / "users"
    if not users_dir.exists():
        return []
    users = []
    for path in sorted(users_dir.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        users.append(UserConfig.model_validate(data))
    return users


@lru_cache(maxsize=1)
def load_sources_config() -> SourcesConfig:
    config_path = CONFIG_DIR / "sources.yaml"
    if not config_path.exists():
        return SourcesConfig()

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    return SourcesConfig.model_validate(data.get("sources", {}))
