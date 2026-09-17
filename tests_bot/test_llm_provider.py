# -*- coding: utf-8 -*-
"""Переключатель LLM_PROVIDER: форма ответа от провайдера не зависит (ARCHITECTURE §8.3)."""
from __future__ import annotations

import asyncio
import json

import pytest

from backend import llm
from backend.prompts.schemas import PARSE_SCHEMA, adapt_for_openai

MODEL_JSON = {
    "mode": "create",
    "needs_clarification": False,
    "clarification_question": None,
    "note": None,
    "operations": [{
        "kind": "expense", "amount": 4300, "currency": "AED", "from_account": "mashreq_personal",
        "to_account": None, "category": "exp_cafe", "income_source": None, "counterparty": None,
        "project": None, "op_date": None, "due_date": None, "amount_to": None, "currency_to": None,
        "rate": None, "rate_named_by_voice": False, "no_tax": False, "freeze": True,
        "freeze_account": None, "description": "обед в кафе", "target_entry_id": None,
        "confidence": 0.94,
    }],
}


class FakeResponse:
    def __init__(self, data):
        self._data = data
        self.status_code = 200
        self.text = json.dumps(data, ensure_ascii=False)

    def json(self):
        return self._data


class FakeClient:
    sent: list[tuple[str, dict]] = []

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        FakeClient.sent.append((url, kwargs.get("json") or {}))
        body = json.dumps(MODEL_JSON, ensure_ascii=False)
        if "anthropic" in url:
            return FakeResponse({"content": [{"type": "text", "text": body}],
                                 "usage": {"input_tokens": 900, "output_tokens": 60,
                                           "cache_read_input_tokens": 800}})
        return FakeResponse({"choices": [{"message": {"content": body}}],
                             "usage": {"prompt_tokens": 900, "completion_tokens": 60}})


@pytest.fixture
def fake_http(monkeypatch):
    FakeClient.sent = []
    monkeypatch.setattr("backend.llm.httpx.AsyncClient", FakeClient)
    return FakeClient


def parse(text="Сходил в кафе, поел на 43 дирхама"):
    return asyncio.run(llm.parse_phrase(
        text, today="2026-09-17", reference="СПРАВОЧНИК",
        hints={"today": "2026-09-17", "last_account_by_currency": {"AED": "mashreq_personal"}},
    ))


def test_both_providers_return_same_dict(fake_http, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    from_anthropic = parse()
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    from_openai = parse()
    assert from_anthropic == from_openai
    assert from_anthropic["operations"][0]["amount"] == 4300
    assert from_anthropic["operations"][0]["currency"] == "AED"


def test_anthropic_caches_reference_in_system(fake_http, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    parse()
    url, body = fake_http.sent[-1]
    assert "anthropic" in url
    system = body["system"]
    assert isinstance(system, list) and system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "СПРАВОЧНИК" in system[0]["text"]
    assert body["output_config"]["format"]["type"] == "json_schema"


def test_openai_uses_strict_schema_without_null_enums(fake_http, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    parse()
    url, body = fake_http.sent[-1]
    assert "openai" in url
    spec = body["response_format"]["json_schema"]
    assert spec["strict"] is True
    props = spec["schema"]["properties"]["operations"]["items"]["properties"]
    assert "enum" not in props["currency"]          # enum с null у OpenAI ненадёжен
    assert "enum" not in props["currency_to"]
    assert props["kind"]["enum"][0] == "expense"    # обычные перечисления остаются
    assert spec["schema"]["additionalProperties"] is False
    # справочник — первым блоком system, он же стабильный префикс кэша
    assert body["messages"][0]["role"] == "system"
    assert "СПРАВОЧНИК" in body["messages"][0]["content"]


def test_schema_adaptation_does_not_touch_original():
    adapted = adapt_for_openai(PARSE_SCHEMA)
    assert "enum" in PARSE_SCHEMA["properties"]["operations"]["items"]["properties"]["currency"]
    assert "enum" not in adapted["properties"]["operations"]["items"]["properties"]["currency"]


def test_bad_currency_from_model_is_dropped(fake_http, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    MODEL_JSON["operations"][0]["currency"] = "дирхам"
    try:
        result = parse()
    finally:
        MODEL_JSON["operations"][0]["currency"] = "AED"
    assert result["operations"][0]["currency"] is None


def test_no_key_is_clear_error(fake_http, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(llm.LLMError):
        parse()
