import json
from pathlib import Path

from freelance_assitant.services.llm import (
    DEFAULT_KBLABS_CREDENTIALS_PATH,
    gateway_root_url,
    jwt_exp,
    load_kblabs_credentials,
    normalize_llm_base_url,
    normalize_llm_model,
    resolve_kblabs_credentials_path,
)


def test_normalize_kblabs_root_url() -> None:
    assert normalize_llm_base_url("https://api.kblabs.ru") == "https://api.kblabs.ru/llm/v1"


def test_normalize_kblabs_legacy_v1_url() -> None:
    assert normalize_llm_base_url("https://api.kblabs.ru/v1") == "https://api.kblabs.ru/llm/v1"


def test_leave_non_kblabs_url_unchanged() -> None:
    assert normalize_llm_base_url("https://example.com/v1") == "https://example.com/v1"


def test_gateway_root_url_from_llm_path() -> None:
    assert gateway_root_url("https://api.kblabs.ru/llm/v1") == "https://api.kblabs.ru"


def test_normalize_kblabs_model_alias() -> None:
    assert normalize_llm_model("https://api.kblabs.ru", "gpt-4o-mini") == "small"


def test_leave_non_kblabs_model_unchanged() -> None:
    assert normalize_llm_model("https://example.com/v1", "gpt-4o-mini") == "gpt-4o-mini"


def test_default_credentials_path_when_not_configured() -> None:
    assert resolve_kblabs_credentials_path() == DEFAULT_KBLABS_CREDENTIALS_PATH


def test_jwt_exp_parses_payload() -> None:
    assert jwt_exp("header.eyJleHAiOjE3MDAwMDAwMDB9.signature") == 1700000000


def test_load_kblabs_credentials_from_file(monkeypatch, tmp_path: Path) -> None:
    creds_path = tmp_path / "agent.json"
    creds_path.write_text(
        json.dumps({"clientId": "clt_test", "clientSecret": "cs_test"}),
    )
    monkeypatch.setattr("freelance_assitant.services.llm.settings.llm_client_id", "")
    monkeypatch.setattr("freelance_assitant.services.llm.settings.llm_client_secret", "")
    monkeypatch.setattr(
        "freelance_assitant.services.llm.settings.llm_credentials_path",
        str(creds_path),
    )

    assert load_kblabs_credentials() == ("clt_test", "cs_test")


def test_load_kblabs_credentials_prefers_env_settings(monkeypatch) -> None:
    monkeypatch.setattr("freelance_assitant.services.llm.settings.llm_client_id", "clt_env")
    monkeypatch.setattr("freelance_assitant.services.llm.settings.llm_client_secret", "cs_env")
    monkeypatch.setattr("freelance_assitant.services.llm.settings.llm_credentials_path", "")

    assert load_kblabs_credentials() == ("clt_env", "cs_env")
