# -*- coding: utf-8 -*-
"""Общие заглушки тестов бота: ядро, LLM и STT живыми не бывают.

Ядро (агент A) подменяется FakeLedger — объект с теми же именами функций, что в §4.1.
"""
from __future__ import annotations

import os
from typing import Any

import pytest

from backend.pipeline import ledger_ref

ALL_OP_FIELDS = {
    "kind": "expense", "amount": None, "currency": None, "from_account": None, "to_account": None,
    "category": None, "income_source": None, "counterparty": None, "project": None, "op_date": None,
    "due_date": None, "amount_to": None, "currency_to": None, "rate": None,
    "rate_named_by_voice": False, "no_tax": False, "freeze": True, "freeze_account": None,
    "description": None, "target_entry_id": None, "confidence": 0.9,
}


def op(**kw: Any) -> dict[str, Any]:
    """Одна операция в форме ответа модели (§6.1)."""
    data = dict(ALL_OP_FIELDS)
    data.update(kw)
    return data


def parse_out(*operations: dict, mode: str = "create", needs: bool = False,
              question: str | None = None) -> dict[str, Any]:
    return {
        "mode": mode,
        "needs_clarification": needs,
        "clarification_question": question,
        "note": None,
        "operations": list(operations),
    }


class FakeLedger:
    """Ядро учёта на время теста: запоминает, что ему передали, и отвечает по форме §5.5."""

    def __init__(self) -> None:
        self.posted: list[Any] = []
        self.amended: list[tuple[int, Any]] = []
        self.voided: list[int] = []
        self.unvoided: list[int] = []
        self.pending: dict[int, dict] = {}
        self.transcripts: list[dict] = []
        self.quota_left = 100
        self.next_id = 500
        self.raise_on_post: Exception | None = None

    # --- справочники и подсказки ---
    def refs(self) -> dict:
        return {
            "accounts": [
                {"id": 1, "slug": "mashreq_personal", "name": "Mashreq личный", "type": "asset_personal",
                 "currency": "AED", "is_money": True, "group_key": "AED", "icon": "bank", "sort": 10,
                 "archived": False},
                {"id": 5, "slug": "tbank", "name": "Т-Банк", "type": "asset_personal", "currency": "RUB",
                 "is_money": True, "group_key": "RUB", "icon": "card", "sort": 20, "archived": False},
            ],
            "categories": [{"id": 18, "slug": "exp_cafe", "name": "Кафе и рестораны", "icon": "cafe",
                            "color": "#FF7A45", "sort": 10, "archived": False}],
            "income_sources": [{"id": 14, "slug": "inc_projects", "name": "Проекты", "tax_rate_bp": 600,
                                "tax_account_id": 13, "color": "#3E7BFA", "icon": "briefcase",
                                "sort": 10, "archived": False}],
            "counterparties": [{"id": 3, "name": "Маша", "kind": "person", "archived": False}],
            "currencies": ["RUB", "AED", "USDT", "USD"],
            "kinds": [{"key": "expense", "title": "Расход"}],
        }

    def bot_hints(self) -> dict:
        return {
            "today": "2026-09-17",
            "last_account_by_currency": {"AED": "mashreq_personal", "RUB": "tbank", "USDT": "bybit"},
            "last_entry": {"id": 431, "title": "Взял из семейного 500 AED", "op_date": "2026-09-17"},
        }

    def ai_quota_take(self, n: int = 1) -> bool:
        if self.quota_left < n:
            return False
        self.quota_left -= n
        return True

    # --- короткая память диалога ---
    def pending_get(self, chat_id: int):
        return self.pending.get(chat_id)

    def pending_set(self, chat_id: int, state: str, entry_id: int | None, payload: dict,
                    ttl_sec: int = 1800) -> None:
        self.pending[chat_id] = {"chat_id": chat_id, "state": state, "entry_id": entry_id,
                                 "payload": payload}

    def pending_clear(self, chat_id: int) -> None:
        self.pending.pop(chat_id, None)

    # --- расшифровки ---
    def transcript_put(self, *, chat_id: int, provider: str, text: str | None, status: str = "ready",
                       file_unique_id: str | None = None, sent_at: int | None = None,
                       duration: int | None = None) -> int:
        self.transcripts.append({"chat_id": chat_id, "provider": provider, "text": text,
                                 "status": status, "file_unique_id": file_unique_id,
                                 "sent_at": sent_at, "duration": duration})
        return len(self.transcripts)

    def transcript_find(self, *, chat_id=None, file_unique_id=None, sent_at=None, duration=None):
        from backend.stt.telethon_provider import pick_transcript

        return pick_transcript(self.transcripts, chat_id=chat_id, sent_at=sent_at,
                               duration=duration, file_unique_id=file_unique_id)

    # --- запись ---
    def post_operation(self, operation, *, actor: str = "bot") -> dict:
        if self.raise_on_post is not None:
            raise self.raise_on_post
        self.posted.append(operation)
        self.next_id += 1
        return self._entry(self.next_id, operation)

    def amend_entry(self, entry_id: int, patch, *, actor: str = "bot") -> dict:
        self.amended.append((entry_id, patch))
        self.next_id += 1
        return {
            "id": self.next_id, "kind": "expense", "version": 2,
            "amount": {"amount": patch.amount or 3400, "currency": "AED"},
            "title": "Кафе и рестораны", "status": "posted",
            "postings": [
                {"seq": 1, "account_id": 18, "account_slug": "exp_cafe", "account_name": "Кафе и рестораны",
                 "side": "debit", "amount": {"amount": patch.amount or 3400, "currency": "AED"}},
                {"seq": 2, "account_id": 1, "account_slug": "mashreq_personal",
                 "account_name": "Mashreq личный", "side": "credit",
                 "amount": {"amount": patch.amount or 3400, "currency": "AED"}},
            ],
            "versions": [{"id": self.next_id, "version": 2, "status": "posted",
                          "created_at": "2026-09-17T09:30:00Z", "changed": ["сумма 43 → 34 AED"]}],
            "effects": {"accounts": [{"id": 1, "slug": "mashreq_personal", "name": "Mashreq личный",
                                      "role": "asset", "balance": {"amount": 185150, "currency": "AED"},
                                      "natural": {"amount": 185150, "currency": "AED"},
                                      "in_view": {"amount": 4341768, "currency": "RUB"}, "frozen": None}],
                        "net_worth": {"amount": 22291642, "currency": "RUB"},
                        "free_rub": {"amount": 14315000, "currency": "RUB"},
                        "frozen_rub": {"amount": 1225000, "currency": "RUB"},
                        "family_debt": {"amount": 50000, "currency": "AED"},
                        "family_direction": "i_owe", "tranche": None, "released": []},
            "warnings": [],
        }

    def void_entry(self, entry_id: int, *, actor: str = "bot", reason: str | None = None) -> dict:
        self.voided.append(entry_id)
        return {"id": entry_id, "kind": "expense", "status": "void",
                "amount": {"amount": 4300, "currency": "AED"}, "title": "Кафе и рестораны",
                "postings": [], "effects": {"accounts": []}, "warnings": []}

    def unvoid_entry(self, entry_id: int, *, actor: str = "bot") -> dict:
        self.unvoided.append(entry_id)
        return {"id": entry_id, "kind": "expense", "status": "posted",
                "amount": {"amount": 4300, "currency": "AED"}, "title": "Кафе и рестораны",
                "postings": [], "effects": {"accounts": []}, "warnings": []}

    # --- вспомогательное ---
    def _entry(self, entry_id: int, operation) -> dict:
        money = {"amount": operation.amount, "currency": operation.currency}
        return {
            "id": entry_id, "kind": operation.kind, "amount": money, "title": "Операция",
            "status": "posted", "version": 1, "op_date": operation.op_date or "2026-09-17",
            "counterparty": operation.counterparty, "project": operation.project,
            "due_date": operation.due_date,
            "postings": [
                {"seq": 1, "account_id": 99, "account_slug": "exp_other", "account_name": "Прочее",
                 "side": "debit", "amount": money},
                {"seq": 2, "account_id": 1, "account_slug": "mashreq_personal",
                 "account_name": "Mashreq личный", "side": "credit", "amount": money},
            ],
            "effects": {
                "accounts": [{"id": 1, "slug": "mashreq_personal", "name": "Mashreq личный",
                              "role": "asset", "balance": {"amount": 184250, "currency": "AED"},
                              "natural": {"amount": 184250, "currency": "AED"},
                              "in_view": {"amount": 4320663, "currency": "RUB"}, "frozen": None}],
                "net_worth": {"amount": 22291642, "currency": "RUB"},
                "free_rub": {"amount": 14315000, "currency": "RUB"},
                "frozen_rub": {"amount": 1225000, "currency": "RUB"},
                "family_debt": {"amount": 50000, "currency": "AED"},
                "family_direction": "i_owe", "tranche": None, "released": [],
            },
            "warnings": [],
        }


@pytest.fixture
def ledger() -> FakeLedger:
    fake = FakeLedger()
    ledger_ref.set_ledger(fake)
    yield fake
    ledger_ref.set_ledger(None)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("OWNER_TG_ID", "100000001")
    monkeypatch.setenv("PUBLIC_URL", "https://finuchet.example")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("TELETHON_SESSION", "")
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("STT_FALLBACK", "groq")
    monkeypatch.delenv("STT_API_KEY", raising=False)
    monkeypatch.delenv("STT_API_KEY_GROQ", raising=False)
    yield


@pytest.fixture
def llm_answer(monkeypatch):
    """Подменяет единственную точку вызова модели: сеть в тестах не трогаем."""
    box: dict[str, Any] = {"data": parse_out(), "calls": []}

    async def fake_json_call(schema_name, system, user, images=None, *, model_kind="parse"):
        box["calls"].append({"schema": schema_name, "system": system, "user": user, "images": images})
        data = box["data"]
        return data(user) if callable(data) else data

    monkeypatch.setattr("backend.llm._json_call", fake_json_call)
    return box
