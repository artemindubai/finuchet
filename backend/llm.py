# -*- coding: utf-8 -*-
"""Единственная точка вызова модели: разбор фразы, скрина, выписки (ARCHITECTURE §6, §8.3).

Провайдер выбирается переменной LLM_PROVIDER (anthropic | openai). Форма возвращаемого dict от
провайдера не зависит — это условие контракта: конвейер и тесты не должны знать, к кому мы ходили.

В лог пишем провайдера, модель, токены и длительность. Текст фразы в лог не попадает никогда.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from backend.prompts.schemas import (
    clean_parse_result,
    clean_screen_result,
    schema_for,
)

log = logging.getLogger("finuchet.llm")

_PROMPTS = Path(__file__).resolve().parent / "prompts"
_REFERENCE_MARK = "{REFERENCE}"

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

_MAX_TOKENS = 4096
_TIMEOUT = 90.0


class LLMError(RuntimeError):
    """Модель не ответила или ответила не по схеме."""


_LAST_CALL: dict[str, Any] = {}


def last_call() -> dict[str, Any]:
    """Провайдер, модель, токены и секунды последнего вызова — для приёмки и сравнения моделей.

    Фраза сюда не попадает, только счётчики. Читает `tools/offline_check.py`.
    """
    return dict(_LAST_CALL)


# ---------------------------------------------------------------- настройки

def provider() -> str:
    value = (os.getenv("LLM_PROVIDER") or "anthropic").strip().lower()
    return "openai" if value == "openai" else "anthropic"


def _model(kind: str) -> str:
    if provider() == "openai":
        if kind == "vision":
            return os.getenv("LLM_MODEL_VISION_OPENAI") or "gpt-4o"
        # gpt-5.4-mini: 53 верных разбора из 54 против 45 у gpt-4o-mini (сравнение 18.09, грабля 39)
        return os.getenv("LLM_MODEL_PARSE_OPENAI") or "gpt-5.4-mini"
    if kind == "vision":
        return os.getenv("LLM_MODEL_VISION") or "claude-opus-5"
    return os.getenv("LLM_MODEL_PARSE") or "claude-haiku-4-5"


def _api_key() -> str:
    key = os.getenv("OPENAI_API_KEY") if provider() == "openai" else os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("не задан ключ ИИ для выбранного провайдера")
    return key.strip()


def _prompt(name: str) -> str:
    return (_PROMPTS / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- справочник

_FALLBACK_REFERENCE = """Счета (slug · имя · валюта · тип):
mashreq_personal · Mashreq личный · AED · личный актив
cash_aed · Наличные AED · AED · личный актив
cash_rub · Наличные ₽ · RUB · личный актив
bybit · Bybit · USDT · личный актив
tbank · Т-Банк · RUB · личный актив
sber · Сбер · RUB · личный актив
receivable · Мне должны · любая · личный актив (нужен контрагент)
mashreq_family · Mashreq семейный · AED · семейный актив
cash_aed_family · Наличные AED семейные · AED · семейный актив
family_fund · Семейный фонд · AED · обязательство
sber_credit · Кредитка Сбер · RUB · обязательство
tax_npd · Налог НПД · RUB · обязательство
payable · Я должен · любая · обязательство (нужен контрагент)

Категории расходов (slug · имя):
exp_cafe · Кафе и рестораны; exp_groceries · Продукты; exp_transport · Транспорт; exp_housing · Жильё;
exp_home · Дом и быт; exp_comm · Связь и подписки; exp_fun · Развлечения; exp_clothes · Одежда;
exp_health · Здоровье; exp_edu · Учёба; exp_visa · Виза и документы; exp_travel · Путешествия;
exp_charity · Благотворительность; exp_gifts · Подарки; exp_taxes · Налоги;
exp_family_contrib · Взнос в семейный фонд; exp_other · Прочее

Источники дохода (slug · имя · ставка налога):
inc_projects · Проекты · 6 %; inc_parents · Родители · 0 %; inc_uae_job · Подработка ОАЭ · 0 %;
inc_other · Прочее · 0 %

Контрагенты: заводятся по имени из речи."""


def reference_text() -> str:
    """Справочник счетов, категорий и источников для system-части промпта.

    Берётся из ядра (`refs()`); ядра ещё нет — используется план счетов из ARCHITECTURE §3.2.
    Текст обязан быть стабильным между вызовами, иначе кэш промпта не попадёт.
    """
    try:
        from backend.pipeline import ledger_ref

        refs = ledger_ref.call_sync("refs")
    except Exception as exc:
        log.debug("справочник из ядра недоступен (%s), берём план счетов из архитектуры", exc)
        return _FALLBACK_REFERENCE
    try:
        return _render_reference(refs)
    except Exception as exc:
        log.warning("не разобрал справочник ядра: %s", exc)
        return _FALLBACK_REFERENCE


_TYPE_RU = {
    "asset_personal": "личный актив",
    "asset_family": "семейный актив",
    "liability": "обязательство",
    "income": "доход",
    "expense": "расход",
    "equity": "служебный",
}


def _render_reference(refs: dict[str, Any]) -> str:
    lines: list[str] = ["Счета (slug · имя · валюта · тип):"]
    for acc in refs.get("accounts", []):
        if acc.get("archived") or acc.get("type") in ("income", "expense"):
            continue
        cur = acc.get("currency") or "любая"
        lines.append(f"{acc['slug']} · {acc['name']} · {cur} · {_TYPE_RU.get(acc.get('type'), acc.get('type'))}")
    cats = [f"{c['slug']} · {c['name']}" for c in refs.get("categories", []) if not c.get("archived")]
    if cats:
        lines.append("")
        lines.append("Категории расходов (slug · имя): " + "; ".join(cats))
    srcs = []
    for s in refs.get("income_sources", []):
        if s.get("archived"):
            continue
        rate = int(s.get("tax_rate_bp") or 0) / 100
        srcs.append(f"{s['slug']} · {s['name']} · {rate:g} %")
    if srcs:
        lines.append("")
        lines.append("Источники дохода (slug · имя · ставка налога): " + "; ".join(srcs))
    cps = [c["name"] for c in refs.get("counterparties", []) if not c.get("archived")]
    lines.append("")
    lines.append("Контрагенты: " + (", ".join(cps) if cps else "пока нет, заводятся по имени из речи"))
    return "\n".join(lines)


def _system(name: str, reference: str) -> str:
    return _prompt(name).replace(_REFERENCE_MARK, reference.strip())


# ---------------------------------------------------------------- одна точка вызова

async def _json_call(
    schema_name: str,
    system: str,
    user: str,
    images: list[tuple[bytes, str]] | None = None,
    *,
    model_kind: str = "parse",
) -> dict[str, Any]:
    """Единственное место, которое знает, к какому провайдеру идти."""
    prov = provider()
    model = _model(model_kind)
    schema = schema_for(schema_name, prov)
    started = time.monotonic()
    last_error: Exception | None = None

    for attempt in (1, 2):  # один повтор на сетевую ошибку
        try:
            if prov == "openai":
                raw, usage = await _call_openai(model, schema_name, schema, system, user, images)
            else:
                raw, usage = await _call_anthropic(model, schema_name, schema, system, user, images)
            break
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_error = exc
            if attempt == 2:
                raise LLMError(f"сеть не дала ответа от модели: {exc}") from exc
            log.warning("сетевая ошибка обращения к модели, повтор: %s", exc)
    else:  # pragma: no cover
        raise LLMError(str(last_error))

    took = time.monotonic() - started
    log.info(
        "llm %s %s schema=%s in=%s out=%s cached=%s %.1fs",
        prov, model, schema_name,
        usage.get("input"), usage.get("output"), usage.get("cached"), took,
    )
    _LAST_CALL.clear()
    _LAST_CALL.update({"provider": prov, "model": model, "schema": schema_name,
                       "took_sec": round(took, 2), **usage})
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError("модель вернула не JSON") from exc
    return data


async def _call_anthropic(
    model: str,
    schema_name: str,
    schema: dict[str, Any],
    system: str,
    user: str,
    images: list[tuple[bytes, str]] | None,
) -> tuple[str, dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for blob, media_type in images or []:
        if media_type == "application/pdf":
            content.append({
                "type": "document",
                "source": {"type": "base64", "media_type": media_type,
                           "data": base64.b64encode(blob).decode("ascii")},
            })
        else:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type,
                           "data": base64.b64encode(blob).decode("ascii")},
            })
    content.append({"type": "text", "text": user})

    body = {
        "model": model,
        "max_tokens": _MAX_TOKENS,
        # справочник и правила — стабильный префикс, кэшируется на час
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        "messages": [{"role": "user", "content": content}],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }
    headers = {
        "x-api-key": _api_key(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(ANTHROPIC_URL, json=body, headers=headers)
    if resp.status_code >= 400:
        raise LLMError(f"модель ответила {resp.status_code}: {_short(resp.text)}")
    data = resp.json()
    text = next((b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"), "")
    usage = data.get("usage") or {}
    return text, {
        "input": usage.get("input_tokens"),
        "output": usage.get("output_tokens"),
        "cached": usage.get("cache_read_input_tokens"),
    }


async def _call_openai(
    model: str,
    schema_name: str,
    schema: dict[str, Any],
    system: str,
    user: str,
    images: list[tuple[bytes, str]] | None,
) -> tuple[str, dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": user}]
    for blob, media_type in images or []:
        # у OpenAI нет блока document: PDF приходит сюда уже текстом или картинками страниц
        uri = f"data:{media_type};base64," + base64.b64encode(blob).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": uri}})

    body = {
        "model": model,
        "messages": [
            # справочник первым блоком system: кэш у OpenAI автоматический, cache_control не существует
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        "max_tokens": _MAX_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": f"finuchet_{schema_name}", "strict": True, "schema": schema},
        },
    }
    headers = {"Authorization": f"Bearer {_api_key()}", "content-type": "application/json"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(OPENAI_URL, json=body, headers=headers)
        if resp.status_code == 400 and "max_completion_tokens" in (resp.text or ""):
            # модели, которые считают лимит вместе с рассуждением, называют его иначе
            body.pop("max_tokens", None)
            body["max_completion_tokens"] = _MAX_TOKENS
            resp = await client.post(OPENAI_URL, json=body, headers=headers)
    if resp.status_code >= 400:
        raise LLMError(f"модель ответила {resp.status_code}: {_short(resp.text)}")
    data = resp.json()
    choices = data.get("choices") or []
    text = (choices[0].get("message", {}).get("content") if choices else "") or ""
    usage = data.get("usage") or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    return text, {
        "input": usage.get("prompt_tokens"),
        "output": usage.get("completion_tokens"),
        "cached": cached,
    }


def _short(text: str, limit: int = 300) -> str:
    text = " ".join((text or "").split())
    return text[:limit]


# ---------------------------------------------------------------- публичный интерфейс §8.3

async def parse_phrase(text: str, *, today: str, reference: str, hints: dict) -> dict:
    """Фраза (голос или текст) → структура §6.1. Хвост промпта свежий на каждый вызов."""
    system = _system("system_parse.md", reference)
    user = _tail(today, hints) + f'\nФраза: "{text.strip()}"'
    data = await _json_call("parse", system, user, model_kind="parse")
    return clean_parse_result(data)


async def parse_screenshot(image: bytes, media_type: str, *, reference: str, hint: str = "") -> dict:
    """Скрин банка → строки и остаток §6.3."""
    system = _system("system_vision.md", reference)
    user = "Это скриншот банка. Извлеки строки операций и остаток."
    if hint:
        user += "\n" + hint
    data = await _json_call("screen", system, user, images=[(image, media_type)], model_kind="vision")
    return clean_screen_result(data)


async def parse_statement(pdf: bytes, *, password: str | None, reference: str) -> dict:
    """Выписка → те же строки §6.3.

    PDF расшифровывается паролем и превращается в текст: у OpenAI блока document нет, а текст
    выписки точнее картинки. Текст не извлекается (скан) — страницы уходят картинками.
    """
    from backend.pipeline.statement import pdf_to_text, pdf_to_images

    system = _system("system_vision.md", reference)
    text = pdf_to_text(pdf, password=password)
    if text and len(text.strip()) > 80:
        user = "Это выписка банка, текст ниже. Извлеки строки операций и остаток.\n\n" + text[:120_000]
        data = await _json_call("screen", system, user, model_kind="vision")
        return clean_screen_result(data)
    images = pdf_to_images(pdf, password=password)
    if not images:
        raise LLMError("из PDF не удалось достать ни текст, ни страницы")
    user = "Это выписка банка страницами-картинками. Извлеки строки операций и остаток."
    data = await _json_call("screen", system, user, images=images, model_kind="vision")
    return clean_screen_result(data)


def _tail(today: str, hints: dict) -> str:
    """Хвост промпта: дата, последние счета, последняя операция (считает ядро, §4.1 bot_hints)."""
    parts = [f"Сегодня {today} (Дубай)."]
    last = (hints or {}).get("last_account_by_currency") or {}
    if last:
        parts.append("Последние счета по валютам: " + ", ".join(f"{cur} — {slug}" for cur, slug in last.items()) + ".")
    entry = (hints or {}).get("last_entry")
    if entry:
        parts.append(f"Последняя операция: id {entry.get('id')}, «{entry.get('title')}», {entry.get('op_date')}.")
    mode = (hints or {}).get("mode")
    if mode == "amend":
        parts.append("Эта фраза — правка последней операции: mode должен быть amend.")
    return " ".join(parts)
