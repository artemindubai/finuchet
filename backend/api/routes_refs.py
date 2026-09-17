# -*- coding: utf-8 -*-
"""Справочники, курсы и настройки (ARCHITECTURE §5.11, §5.12)."""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, Depends

from backend import db, rates, settings_store
from backend.api.deps import require_user, run
from backend.contracts import LedgerError
from backend.ledger.bot_bridge import refs as refs_body
from backend.ledger.common import audit, resolve_account, warn
from backend.tz import iso_utc, utc_now

router = APIRouter(prefix="/api", tags=["refs"])

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
REF_KINDS = ("accounts", "categories", "income-sources", "counterparties")


def slugify(name: str, prefix: str = "") -> str:
    text = "".join(TRANSLIT.get(ch, ch) for ch in (name or "").lower())
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "item"
    return f"{prefix}{text}"[:40]


def unique_slug(conn, base: str) -> str:
    slug, index = base, 1
    while conn.execute("SELECT 1 FROM accounts WHERE slug = ?", (slug,)).fetchone():
        index += 1
        slug = f"{base}-{index}"
    return slug


@router.get("/refs")
async def get_refs(user: int = Depends(require_user)):
    return await run(refs_body)


def _create(ref: str, data: dict) -> dict:
    conn = db.get_conn()
    name = (data.get("name") or "").strip()
    if not name:
        raise LedgerError("bad_request", "Без названия не заводим", {"field": "name"})
    with db.transaction(conn):
        if ref == "counterparties":
            cur = conn.execute(
                "INSERT INTO counterparties (name, kind, note, archived, created_at)"
                " VALUES (?,?,?,0,?)",
                (name, data.get("kind", "person"), data.get("note"), utc_now()))
            audit(conn, "api", "ref_create", "counterparty", int(cur.lastrowid), data)
            return {"id": int(cur.lastrowid), "name": name, "kind": data.get("kind", "person"),
                    "archived": False}
        if ref == "accounts":
            type_ = data.get("type", "asset_personal")
            currency = data.get("currency")
            slug = unique_slug(conn, slugify(name))
            cur = conn.execute(
                "INSERT INTO accounts (slug, name, type, currency, is_money, needs_counterparty,"
                " group_key, icon, sort, archived, created_at) VALUES (?,?,?,?,?,0,?,?,?,0,?)",
                (slug, name, type_, currency, 1 if data.get("is_money", True) else 0,
                 data.get("group_key") or currency, data.get("icon"),
                 int(data.get("sort") or 100), utc_now()))
            account_id = int(cur.lastrowid)
        elif ref == "categories":
            slug = unique_slug(conn, slugify(name, "exp_"))
            cur = conn.execute(
                "INSERT INTO accounts (slug, name, type, currency, is_money, needs_counterparty,"
                " group_key, icon, sort, archived, created_at)"
                " VALUES (?,?, 'expense', NULL, 0, 0, NULL, ?, ?, 0, ?)",
                (slug, name, data.get("icon") or "dots", int(data.get("sort") or 100), utc_now()))
            account_id = int(cur.lastrowid)
            conn.execute("INSERT INTO categories (account_id, parent_id, color, sort)"
                         " VALUES (?, NULL, ?, ?)",
                         (account_id, data.get("color") or "#A0A7B0", int(data.get("sort") or 100)))
        elif ref == "income-sources":
            slug = unique_slug(conn, slugify(name, "inc_"))
            cur = conn.execute(
                "INSERT INTO accounts (slug, name, type, currency, is_money, needs_counterparty,"
                " group_key, icon, sort, archived, created_at)"
                " VALUES (?,?, 'income', NULL, 0, 0, NULL, ?, ?, 0, ?)",
                (slug, name, data.get("icon") or "dots", int(data.get("sort") or 100), utc_now()))
            account_id = int(cur.lastrowid)
            tax_account = conn.execute("SELECT id FROM accounts WHERE slug = 'tax_npd'").fetchone()
            rate_bp = int(data.get("tax_rate_bp") or 0)
            conn.execute(
                "INSERT INTO income_sources (account_id, tax_rate_bp, tax_account_id, color, icon, sort)"
                " VALUES (?,?,?,?,?,?)",
                (account_id, rate_bp,
                 int(tax_account["id"]) if (rate_bp and tax_account) else None,
                 data.get("color") or "#A0A7B0", data.get("icon") or "dots",
                 int(data.get("sort") or 100)))
        else:
            raise LedgerError("not_found", "Неизвестный справочник", {"ref": ref})
        audit(conn, "api", "ref_create", ref, account_id, data)
    return refs_body()


def _patch(ref: str, item_id: int, data: dict) -> dict:
    conn = db.get_conn()
    with db.transaction(conn):
        if ref == "counterparties":
            sets, args = [], []
            for key in ("name", "kind", "note"):
                if data.get(key) is not None:
                    sets.append(f"{key} = ?")
                    args.append(data[key])
            if sets:
                conn.execute(f"UPDATE counterparties SET {', '.join(sets)} WHERE id = ?",
                             args + [item_id])
            audit(conn, "api", "ref_patch", "counterparty", item_id, data)
            return refs_body()

        account = conn.execute("SELECT * FROM accounts WHERE id = ?", (item_id,)).fetchone()
        if account is None:
            raise LedgerError("not_found", "Не найдено", {"id": item_id})
        if data.get("type") or data.get("currency"):
            used = conn.execute("SELECT 1 FROM postings WHERE account_id = ? LIMIT 1",
                                (item_id,)).fetchone()
            if used:
                raise LedgerError("bad_request",
                                  "Тип и валюту счёта нельзя менять после первой проводки",
                                  {"account": account["slug"]})
        sets, args = [], []
        for key in ("name", "icon", "group_key", "type", "currency"):
            if data.get(key) is not None:
                sets.append(f"{key} = ?")
                args.append(data[key])
        if data.get("sort") is not None:
            sets.append("sort = ?")
            args.append(int(data["sort"]))
        if sets:
            conn.execute(f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?", args + [item_id])
        if ref == "categories" and data.get("color"):
            conn.execute("UPDATE categories SET color = ? WHERE account_id = ?",
                         (data["color"], item_id))
        if ref == "income-sources":
            if data.get("color"):
                conn.execute("UPDATE income_sources SET color = ? WHERE account_id = ?",
                             (data["color"], item_id))
            if data.get("icon"):
                conn.execute("UPDATE income_sources SET icon = ? WHERE account_id = ?",
                             (data["icon"], item_id))
            if data.get("tax_rate_bp") is not None:
                tax_account = conn.execute(
                    "SELECT id FROM accounts WHERE slug = 'tax_npd'").fetchone()
                rate_bp = int(data["tax_rate_bp"])
                conn.execute("UPDATE income_sources SET tax_rate_bp = ?, tax_account_id = ?"
                             " WHERE account_id = ?",
                             (rate_bp, int(tax_account["id"]) if (rate_bp and tax_account) else None,
                              item_id))
        audit(conn, "api", "ref_patch", ref, item_id, data)
    return refs_body()


def _archive(ref: str, item_id: int, archived: bool) -> dict:
    conn = db.get_conn()
    warnings = []
    with db.transaction(conn):
        table = "counterparties" if ref == "counterparties" else "accounts"
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise LedgerError("not_found", "Не найдено", {"id": item_id})
        if table == "accounts" and archived:
            total = conn.execute(
                "SELECT COALESCE(SUM(balance), 0) AS total FROM v_balances WHERE account_id = ?",
                (item_id,)).fetchone()["total"]
            if int(total or 0) != 0:
                warnings.append(warn("archived_with_balance",
                                     "Счёт архивирован с ненулевым остатком",
                                     {"account": row["slug"], "balance": int(total)}))
        conn.execute(f"UPDATE {table} SET archived = ? WHERE id = ?",
                     (1 if archived else 0, item_id))
        audit(conn, "api", "ref_archive" if archived else "ref_unarchive", ref, item_id, None)
    out = refs_body()
    out["warnings"] = warnings
    return out


@router.post("/{ref}")
async def create_ref(ref: str, body: dict = Body(...), user: int = Depends(require_user)):
    if ref not in REF_KINDS:
        raise LedgerError("not_found", "Неизвестный справочник", {"ref": ref})
    return await run(_create, ref, body or {})


@router.patch("/{ref}/{item_id}")
async def patch_ref(ref: str, item_id: int, body: dict = Body(default={}),
                    user: int = Depends(require_user)):
    if ref not in REF_KINDS:
        raise LedgerError("not_found", "Неизвестный справочник", {"ref": ref})
    return await run(_patch, ref, item_id, body or {})


@router.post("/{ref}/{item_id}/archive")
async def archive_ref(ref: str, item_id: int, user: int = Depends(require_user)):
    if ref not in REF_KINDS:
        raise LedgerError("not_found", "Неизвестный справочник", {"ref": ref})
    return await run(_archive, ref, item_id, True)


@router.post("/{ref}/{item_id}/unarchive")
async def unarchive_ref(ref: str, item_id: int, user: int = Depends(require_user)):
    if ref not in REF_KINDS:
        raise LedgerError("not_found", "Неизвестный справочник", {"ref": ref})
    return await run(_archive, ref, item_id, False)


def _rates_body() -> dict:
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM rate_cache ORDER BY pair").fetchall()
    now = utc_now()
    return {
        "at": iso_utc(max([int(r["at"]) for r in rows], default=now)),
        "rates": [{"pair": r["pair"], "rate_e6": int(r["rate_e6"]), "source": r["source"],
                   "at": iso_utc(int(r["at"])), "stale": now - int(r["at"]) > 900} for r in rows],
        "markup_rub_per_aed_e6": rates.provider.markup_e6(conn),
    }


@router.get("/rates")
async def get_rates(user: int = Depends(require_user)):
    return await run(_rates_body)


@router.post("/rates/refresh")
async def refresh_rates(user: int = Depends(require_user)):
    def _refresh():
        rates.refresh_all(conn=db.get_conn())
        return _rates_body()
    return await run(_refresh)


@router.get("/rates/at")
async def rate_at(pair: str, date: str, user: int = Depends(require_user)):
    def _at():
        quote = rates.at_date(pair, date, conn=db.get_conn())
        return {"pair": quote.pair, "rate_e6": quote.rate_e6, "source": quote.source,
                "at": iso_utc(quote.at), "stale": quote.stale}
    return await run(_at)


def _settings_body() -> dict:
    conn = db.get_conn()
    import os
    out = settings_store.all_public(conn=conn)
    out["version"] = os.environ.get("APP_VERSION", "1.0.0")
    try:
        import os.path
        out["db_size_bytes"] = os.path.getsize(db.db_path())
    except OSError:
        out["db_size_bytes"] = 0
    row = conn.execute("SELECT at FROM backups WHERE ok = 1 ORDER BY at DESC LIMIT 1").fetchone()
    out["last_backup_at"] = iso_utc(int(row["at"])) if row else None
    return out


@router.get("/settings")
async def get_settings(user: int = Depends(require_user)):
    return await run(_settings_body)


@router.put("/settings")
async def put_settings(body: dict = Body(default={}), user: int = Depends(require_user)):
    def _put():
        conn = db.get_conn()
        allowed = set(settings_store.PUBLIC_KEYS) | set(settings_store.SECRET_KEYS)
        with db.transaction(conn):
            for key, value in (body or {}).items():
                if key in allowed:
                    settings_store.set(key, value, conn=conn)
            audit(conn, "api", "settings", None, None,
                  {"keys": [k for k in (body or {}) if k in allowed]})
        return _settings_body()
    return await run(_put)
