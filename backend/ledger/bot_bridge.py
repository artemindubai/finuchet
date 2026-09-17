# -*- coding: utf-8 -*-
"""Мост ядра для бота (ARCHITECTURE §4.1). Бот в БД не ходит — всё, что ему нужно, здесь.

Справочник, подсказки для промпта, состояние «Поправить», транскрипты, дневной лимит вызовов ИИ."""
from __future__ import annotations

import json
import os
import sqlite3

from backend import db, settings_store
from backend.ledger.common import freeze_account_slug
from backend.tz import today_dubai, utc_now


def _conn() -> sqlite3.Connection:
    return db.get_conn()


def refs() -> dict:
    """Ровно тело §5.11: счета, категории, источники дохода, контрагенты, валюты, виды операций."""
    from backend.ledger.api import KINDS
    conn = _conn()
    accounts = [{"id": int(r["id"]), "slug": r["slug"], "name": r["name"], "type": r["type"],
                 "currency": r["currency"], "is_money": bool(r["is_money"]),
                 "group_key": r["group_key"], "icon": r["icon"], "sort": int(r["sort"]),
                 "archived": bool(r["archived"])}
                for r in conn.execute("SELECT * FROM accounts ORDER BY sort, id").fetchall()]
    categories = [{"id": int(r["id"]), "slug": r["slug"], "name": r["name"], "icon": r["icon"],
                   "color": r["color"], "sort": int(r["sort"]), "archived": bool(r["archived"])}
                  for r in conn.execute(
                      "SELECT a.id, a.slug, a.name, a.icon, c.color, c.sort, a.archived"
                      " FROM categories c JOIN accounts a ON a.id = c.account_id"
                      " ORDER BY c.sort, a.id").fetchall()]
    sources = [{"id": int(r["id"]), "slug": r["slug"], "name": r["name"],
                "tax_rate_bp": int(r["tax_rate_bp"]), "tax_account_id": r["tax_account_id"],
                "color": r["color"], "icon": r["icon"], "sort": int(r["sort"]),
                "archived": bool(r["archived"])}
               for r in conn.execute(
                   "SELECT a.id, a.slug, a.name, s.tax_rate_bp, s.tax_account_id, s.color,"
                   " COALESCE(s.icon, a.icon) AS icon, s.sort, a.archived"
                   " FROM income_sources s JOIN accounts a ON a.id = s.account_id"
                   " ORDER BY s.sort, a.id").fetchall()]
    counterparties = [{"id": int(r["id"]), "name": r["name"], "kind": r["kind"],
                       "archived": bool(r["archived"])}
                      for r in conn.execute(
                          "SELECT * FROM counterparties ORDER BY name").fetchall()]
    return {"accounts": accounts, "categories": categories, "income_sources": sources,
            "counterparties": counterparties, "currencies": ["RUB", "AED", "USDT", "USD"],
            "kinds": [{"key": key, "title": title} for key, title in KINDS]}


def bot_hints() -> dict:
    """Хвост промпта (§6.2): дата, последние счета по валютам, последняя операция."""
    from backend.ledger.recipes import last_account_slug
    conn = _conn()
    last_by_currency = {}
    for currency in ("AED", "RUB", "USDT"):
        slug = last_account_slug(conn, currency)
        if slug:
            last_by_currency[currency] = slug
    row = conn.execute(
        "SELECT id, op_date, kind, description FROM entries WHERE status = 'posted'"
        " ORDER BY id DESC LIMIT 1").fetchone()
    last_entry = None
    if row is not None:
        from backend.ledger.api import KIND_TITLE
        title = row["description"] or KIND_TITLE.get(row["kind"], row["kind"])
        last_entry = {"id": int(row["id"]), "title": title, "op_date": row["op_date"]}
    return {"today": today_dubai(), "last_account_by_currency": last_by_currency,
            "last_entry": last_entry, "freeze_account": freeze_account_slug(conn)}


def pending_get(chat_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM bot_pending WHERE chat_id = ?", (int(chat_id),)).fetchone()
    if row is None:
        return None
    if int(row["expires_at"]) < utc_now():
        pending_clear(chat_id)
        return None
    try:
        payload = json.loads(row["payload"])
    except json.JSONDecodeError:
        payload = {}
    return {"chat_id": int(row["chat_id"]), "state": row["state"], "entry_id": row["entry_id"],
            "payload": payload, "expires_at": int(row["expires_at"])}


def pending_set(chat_id: int, state: str, entry_id: int | None, payload: dict,
                ttl_sec: int = 1800) -> None:
    conn = _conn()
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO bot_pending (chat_id, state, entry_id, payload, expires_at, created_at)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET state = excluded.state,"
            " entry_id = excluded.entry_id, payload = excluded.payload,"
            " expires_at = excluded.expires_at",
            (int(chat_id), state, entry_id, json.dumps(payload or {}, ensure_ascii=False),
             utc_now() + int(ttl_sec), utc_now()))


def pending_clear(chat_id: int) -> None:
    conn = _conn()
    with db.transaction(conn):
        conn.execute("DELETE FROM bot_pending WHERE chat_id = ?", (int(chat_id),))


def transcript_put(*, chat_id: int, provider: str, text: str | None, status: str = "ready",
                   file_unique_id: str | None = None, sent_at: int | None = None,
                   duration: int | None = None) -> int:
    conn = _conn()
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT INTO voice_transcripts (chat_id, file_unique_id, duration, sent_at, text,"
            " provider, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (int(chat_id), file_unique_id, duration, int(sent_at or utc_now()), text, provider,
             status, utc_now()))
        return int(cur.lastrowid)


def transcript_find(*, chat_id: int | None = None, file_unique_id: str | None = None,
                    sent_at: int | None = None, duration: int | None = None) -> dict | None:
    """Мост Telethon ↔ бот: сначала по file_unique_id, иначе по времени ±3 с и длительности ±1 (§8.1)."""
    conn = _conn()
    if file_unique_id:
        row = conn.execute(
            "SELECT * FROM voice_transcripts WHERE file_unique_id = ? AND status = 'ready'"
            " ORDER BY id DESC LIMIT 1", (file_unique_id,)).fetchone()
        if row is not None:
            return dict(row)
    if chat_id is None or sent_at is None:
        return None
    rows = conn.execute(
        "SELECT * FROM voice_transcripts WHERE chat_id = ? AND status = 'ready'"
        " AND ABS(sent_at - ?) <= 3 ORDER BY id", (int(chat_id), int(sent_at))).fetchall()
    if not rows:
        return None
    if duration is not None:
        exact = [r for r in rows if r["duration"] is not None and abs(int(r["duration"]) - int(duration)) <= 1]
        if exact:
            rows = exact
    rows = sorted(rows, key=lambda r: (abs(int(r["sent_at"]) - int(sent_at)), int(r["id"])))
    return dict(rows[0])


def ai_quota_take(n: int = 1) -> bool:
    """Дневной предохранитель на платные вызовы (§8.1). False — лимит исчерпан."""
    conn = _conn()
    try:
        cap = int(os.environ.get("AI_DAILY_CAP", "300"))
    except ValueError:
        cap = 300
    key = f"ai_calls_{today_dubai()}"
    with db.transaction(conn):
        used = int(settings_store.get(key, 0, conn=conn) or 0)
        if used + int(n) > cap:
            return False
        settings_store.set(key, used + int(n), conn=conn)
    return True
