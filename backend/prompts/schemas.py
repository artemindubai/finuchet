# -*- coding: utf-8 -*-
"""JSON-схемы structured outputs. Текст схем — ARCHITECTURE.md §6.1 и §6.3, менять нельзя.

Схема одна на обоих провайдеров. Единственная поправка под OpenAI: у него ненадёжен enum,
внутри которого лежит null, поэтому такие перечисления снимаются (`adapt_for_openai`),
а значение проверяется в коде после ответа (`clean_parse_result`).
"""
from __future__ import annotations

import copy
from typing import Any

CURRENCIES = ("RUB", "AED", "USDT", "USD")

KINDS = (
    "expense", "income", "transfer", "exchange",
    "family_withdrawal", "family_repayment", "family_topup_by_parents",
    "own_contribution_to_family", "family_spent_own", "paid_for_family_from_own",
    "loan_given", "loan_repaid_to_me", "loan_taken", "loan_repaid_by_me",
    "tax_payment", "opening_balance", "balance_correction",
)

PARSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mode", "operations", "needs_clarification", "clarification_question", "note"],
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["create", "amend"],
            "description": "amend — если фраза правит предыдущую операцию («не 43, а 34», «это с налички»)",
        },
        "needs_clarification": {"type": "boolean"},
        "clarification_question": {
            "type": ["string", "null"],
            "description": "ОДИН короткий вопрос по-русски, только если без ответа операцию записать нельзя",
        },
        "note": {"type": ["string", "null"], "description": "что модель не поняла, одной строкой; обычно null"},
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "kind", "amount", "currency", "from_account", "to_account", "category",
                    "income_source", "counterparty", "project", "op_date", "due_date", "amount_to",
                    "currency_to", "rate", "rate_named_by_voice", "no_tax", "freeze", "freeze_account",
                    "description", "target_entry_id", "confidence",
                ],
                "properties": {
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "amount": {
                        "type": ["integer", "null"],
                        "description": "МИНОРНЫЕ единицы: 43 дирхама = 4300, 12,5 тысяч рублей = 1250000",
                    },
                    "currency": {"type": ["string", "null"], "enum": [*CURRENCIES, None]},
                    "from_account": {"type": ["string", "null"], "description": "slug счёта-источника из справочника"},
                    "to_account": {"type": ["string", "null"], "description": "slug счёта-получателя"},
                    "category": {"type": ["string", "null"], "description": "slug категории расхода (exp_*)"},
                    "income_source": {"type": ["string", "null"], "description": "slug источника дохода (inc_*)"},
                    "counterparty": {"type": ["string", "null"], "description": "имя человека/клиента как в речи"},
                    "project": {"type": ["string", "null"], "description": "проект или клиент для дохода"},
                    "op_date": {"type": ["string", "null"], "description": "YYYY-MM-DD; «вчера», «12-го» уже посчитаны"},
                    "due_date": {
                        "type": ["string", "null"],
                        "description": "YYYY-MM-DD, если назван срок возврата долга или платежа («обещал вернуть до 30-го»)",
                    },
                    "amount_to": {"type": ["integer", "null"], "description": "для exchange: сколько получено, минорные"},
                    "currency_to": {"type": ["string", "null"], "enum": [*CURRENCIES, None]},
                    "rate": {"type": ["integer", "null"], "description": "курс × 1000000, если назван или следует из сумм"},
                    "rate_named_by_voice": {"type": "boolean", "description": "true — курс прозвучал в речи, он главнее рынка"},
                    "no_tax": {"type": "boolean", "description": "true — сказано «без налога»"},
                    "freeze": {"type": "boolean", "description": "для family_withdrawal: замораживать рубли (обычно true)"},
                    "freeze_account": {"type": ["string", "null"], "description": "slug рублёвого счёта заморозки"},
                    "description": {"type": ["string", "null"], "description": "короткое описание из речи, без выдумок"},
                    "target_entry_id": {"type": ["integer", "null"], "description": "для mode=amend: какую операцию правим"},
                    "confidence": {"type": "number", "description": "0..1, уверенность разбора"},
                },
            },
        },
    },
}

SCREEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["account_guess", "currency", "balance", "statement_period", "rows"],
    "properties": {
        "account_guess": {"type": ["string", "null"], "description": "slug счёта, если узнаётся по банку/логотипу"},
        "currency": {"type": ["string", "null"], "enum": [*CURRENCIES, None]},
        "balance": {"type": ["integer", "null"], "description": "остаток на экране, минорные единицы"},
        "statement_period": {"type": ["string", "null"], "description": "«2026-09-01..2026-09-30» если это выписка"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["op_date", "amount", "currency", "raw_text", "suggested_category", "suggested_kind"],
                "properties": {
                    "op_date": {"type": ["string", "null"]},
                    "amount": {"type": "integer", "description": "СО ЗНАКОМ глазами банка: − списание, + зачисление"},
                    "currency": {"type": "string", "enum": list(CURRENCIES)},
                    "raw_text": {"type": "string", "description": "описание операции как в банке, дословно"},
                    "suggested_category": {"type": ["string", "null"]},
                    "suggested_kind": {"type": ["string", "null"]},
                },
            },
        },
    },
}

SCHEMAS: dict[str, dict[str, Any]] = {"parse": PARSE_SCHEMA, "screen": SCREEN_SCHEMA}


def adapt_for_openai(schema: dict[str, Any]) -> dict[str, Any]:
    """Снимает перечисления, внутри которых есть null: strict-режим OpenAI их не держит.

    Значение потом проверяется в коде (clean_parse_result / clean_screen_result).
    """
    out = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            enum = node.get("enum")
            if isinstance(enum, list) and any(v is None for v in enum):
                node.pop("enum")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(out)
    return out


def schema_for(name: str, provider: str) -> dict[str, Any]:
    schema = SCHEMAS[name]
    return adapt_for_openai(schema) if provider == "openai" else copy.deepcopy(schema)


# ---------- проверка ответа модели (то, что схема гарантировать не может) ----------

_OP_DEFAULTS: dict[str, Any] = {
    "kind": "expense", "amount": None, "currency": None, "from_account": None, "to_account": None,
    "category": None, "income_source": None, "counterparty": None, "project": None, "op_date": None,
    "due_date": None, "amount_to": None, "currency_to": None, "rate": None,
    "rate_named_by_voice": False, "no_tax": False, "freeze": True, "freeze_account": None,
    "description": None, "target_entry_id": None, "confidence": 0.5,
}


def _currency(value: Any) -> str | None:
    if isinstance(value, str) and value.upper() in CURRENCIES:
        return value.upper()
    return None


def clean_parse_result(data: Any) -> dict[str, Any]:
    """Приводит ответ модели к форме §6.1: недостающие поля добираются умолчаниями,
    мусорные валюты и виды операций обнуляются. Форма одинакова у обоих провайдеров."""
    if not isinstance(data, dict):
        raise ValueError("ответ модели не объект")
    mode = data.get("mode")
    out: dict[str, Any] = {
        "mode": mode if mode in ("create", "amend") else "create",
        "needs_clarification": bool(data.get("needs_clarification")),
        "clarification_question": data.get("clarification_question") or None,
        "note": data.get("note") or None,
        "operations": [],
    }
    for raw in data.get("operations") or []:
        if not isinstance(raw, dict):
            continue
        op = dict(_OP_DEFAULTS)
        for key in _OP_DEFAULTS:
            if key in raw and raw[key] is not None:
                op[key] = raw[key]
        if op["kind"] not in KINDS:
            op["kind"] = "expense"
        op["currency"] = _currency(op["currency"])
        op["currency_to"] = _currency(op["currency_to"])
        op["no_tax"] = bool(op["no_tax"])
        op["freeze"] = bool(op["freeze"])
        op["rate_named_by_voice"] = bool(op["rate_named_by_voice"])
        try:
            op["confidence"] = float(op["confidence"])
        except (TypeError, ValueError):
            op["confidence"] = 0.5
        out["operations"].append(op)
    if not out["operations"] and not out["needs_clarification"]:
        out["needs_clarification"] = True
        out["clarification_question"] = out["clarification_question"] or "Не понял, что записать. Скажите одной фразой."
    return out


def clean_screen_result(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("ответ модели не объект")
    rows = []
    for raw in data.get("rows") or []:
        if not isinstance(raw, dict):
            continue
        cur = _currency(raw.get("currency")) or _currency(data.get("currency"))
        amount = raw.get("amount")
        if cur is None or not isinstance(amount, int):
            continue
        rows.append({
            "op_date": raw.get("op_date") or None,
            "amount": amount,
            "currency": cur,
            "raw_text": raw.get("raw_text") or "",
            "suggested_category": raw.get("suggested_category") or None,
            "suggested_kind": raw.get("suggested_kind") or None,
        })
    balance = data.get("balance")
    return {
        "account_guess": data.get("account_guess") or None,
        "currency": _currency(data.get("currency")),
        "balance": balance if isinstance(balance, int) else None,
        "statement_period": data.get("statement_period") or None,
        "rows": rows,
    }
