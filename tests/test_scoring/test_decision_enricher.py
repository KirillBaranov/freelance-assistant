from __future__ import annotations

import pytest

from freelance_assitant.scoring.decision_enricher import _fallback_agent_prompt, _load_json_response


def test_load_json_response_accepts_plain_json_object():
    data = _load_json_response('{"recommended_mode":"take_now","blocking_risks":["cloudflare"]}')
    assert data["recommended_mode"] == "take_now"
    assert data["blocking_risks"] == ["cloudflare"]


def test_load_json_response_extracts_json_object_from_wrapped_text():
    data = _load_json_response(
        '```json\n{"execution_complexity":"medium","blocking_risks":["payments"]}\n```'
    )
    assert data["execution_complexity"] == "medium"
    assert data["blocking_risks"] == ["payments"]


def test_load_json_response_rejects_empty_response():
    with pytest.raises(ValueError):
        _load_json_response("")


def test_fallback_agent_prompt_contains_required_review_fields():
    prompt = _fallback_agent_prompt(
        type("Candidate", (), {"title": "Test lead", "description": "Need Telegram bot"})()
    )
    assert "feasibility" in prompt
    assert "execution_complexity" in prompt
    assert "questions_to_client" in prompt
