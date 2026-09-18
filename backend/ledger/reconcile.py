# -*- coding: utf-8 -*-
"""Сверка скрина и выписки с учётом (ARCHITECTURE §4.5).

Сопоставление строго один-к-одному и жадное: иначе два одинаковых кофе, из которых голосом назван
один, оба «совпадут» и вторая операция не появится никогда (грабля 11 журнала)."""
from __future__ import annotations

import hashlib
import json
import sqlite3

from backend import db
from backend.contracts import LedgerError, ParsedOperation, ReconcileDecision, ScreenBatch
from backend.ledger.common import account_row, audit, money_dict, resolve_account, warn
from backend.ledger.balances import account_balance, effects as build_effects
from backend.money import fmt_amount
from backend.tz import days_between, today_dubai, utc_now

# §4.5 п. 1б задаёт «≤ 10 % или ≤ 100 минорных единиц», но тут же требует, чтобы 34 против 43
# (расшифровка не расслышала число) давала вопрос, а не тихий дубль — это 21 %. Берём коридор
# пошире: лишний вопрос безопаснее молчаливой второй траты. Расхождение записано в ЖУРНАЛ_НАХОДОК.
NEAR_RATIO_BP = 3000          # 30 %
NEAR_ABS = 100                # или 100 минорных единиц


def _conn() -> sqlite3.Connection:
    return db.get_conn()


def _fingerprint(slug: str, op_date: str, amount: int, raw_text: str, ordinal: int) -> str:
    raw = f"{slug}|{op_date}|{amount}|{raw_text}|{ordinal}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _last_version(conn: sqlite3.Connection, entry: sqlite3.Row) -> sqlite3.Row:
    cursor = entry
    while cursor["replaced_by_entry_id"]:
        nxt = conn.execute("SELECT * FROM entries WHERE id = ?",
                           (int(cursor["replaced_by_entry_id"]),)).fetchone()
        if nxt is None:
            break
        cursor = nxt
    return cursor


def _candidates(conn: sqlite3.Connection, account_id: int, row_amount: int, currency: str,
                op_date: str | None) -> list[dict]:
    """Кандидаты — непогашенные операции с проводкой по тому же счёту (§4.5 правила 1 и 1б)."""
    rows = conn.execute(
        "SELECT e.id AS entry_id, e.op_date AS op_date, e.description AS description,"
        " e.kind AS kind, p.amount AS amount, p.currency AS currency"
        " FROM postings p JOIN entries e ON e.id = p.entry_id"
        " WHERE p.account_id = ? AND e.status = 'posted' AND e.sealed = 1 AND p.currency = ?",
        (account_id, currency)).fetchall()
    out = []
    for row in rows:
        if op_date and row["op_date"]:
            diff_days = abs(days_between(row["op_date"], op_date))
            if diff_days > 2:
                continue
        else:
            diff_days = 0
        theirs = abs(int(row["amount"]))
        mine = abs(int(row_amount))
        if theirs == mine:
            out.append({"entry_id": int(row["entry_id"]), "score": 100 - 10 * diff_days,
                        "why": "сумма и дата совпали"})
            continue
        delta = abs(theirs - mine)
        if delta <= NEAR_ABS or (mine and delta * 10_000 // mine <= NEAR_RATIO_BP):
            out.append({"entry_id": int(row["entry_id"]), "score": 60,
                        "why": f"сумма {theirs / 100:g} против {mine / 100:g}"})
    out.sort(key=lambda c: -c["score"])
    return out


def reconcile(batch: ScreenBatch) -> dict:
    """Ничего не пишет в журнал: только раскладывает строки по статусам и заводит inbox."""
    conn = _conn()
    account = resolve_account(conn, batch.account, field="account")
    account_id = int(account["id"])
    currency = batch.currency or account["currency"] or "RUB"
    batch_id = f"scr_{utc_now()}_{account['slug']}"

    prepared = []
    seen: dict[tuple, int] = {}
    for row in batch.rows:
        op_date = row.op_date or today_dubai()
        key = (op_date, int(row.amount), row.raw_text or "")
        seen[key] = seen.get(key, 0) + 1
        ordinal = seen[key]
        prepared.append({
            "row": row, "op_date": op_date, "currency": row.currency or currency,
            "amount": int(row.amount), "raw_text": row.raw_text or "",
            "external_ref": _fingerprint(account["slug"], op_date, int(row.amount),
                                         row.raw_text or "", ordinal),
            "status": None, "match_entry_id": None, "candidates": [],
        })

    # 1. дедупликация повторной загрузки того же скрина
    for item in prepared:
        rows = conn.execute("SELECT * FROM entries WHERE external_ref = ? ORDER BY id",
                            (item["external_ref"],)).fetchall()
        if not rows:
            continue
        last = _last_version(conn, rows[-1])
        if last["status"] == "posted":
            item["status"] = "matched"
            item["match_entry_id"] = int(last["id"])

    # 2. кандидаты и жадное сопоставление один-к-одному
    pairs = []
    for index, item in enumerate(prepared):
        if item["status"] == "matched":
            continue
        item["candidates"] = _candidates(conn, account_id, item["amount"], item["currency"],
                                         item["op_date"])
        for candidate in item["candidates"]:
            pairs.append((candidate["score"], index, candidate))
    pairs.sort(key=lambda p: (-p[0], p[1]))

    taken_entries: set[int] = set()
    for item in prepared:
        if item["status"] == "matched" and item["match_entry_id"]:
            taken_entries.add(item["match_entry_id"])

    for score, index, candidate in pairs:
        item = prepared[index]
        if item["status"] is not None:
            continue
        if candidate["entry_id"] in taken_entries:
            continue
        free_exact = [c for c in item["candidates"]
                      if c["score"] >= 90 and c["entry_id"] not in taken_entries]
        if score == 60 or len(free_exact) >= 2:
            item["status"] = "ambiguous"
            item["match_entry_id"] = candidate["entry_id"]
            continue
        item["status"] = "matched"
        item["match_entry_id"] = candidate["entry_id"]
        taken_entries.add(candidate["entry_id"])

    for item in prepared:
        if item["status"] is None:
            item["status"] = "new"

    # 3. запись в inbox
    created = {"matched": [], "new": [], "ambiguous": []}
    with db.transaction(conn):
        for item in prepared:
            row = item["row"]
            category = account_row(conn, row.suggested_category)
            status = "merged" if item["status"] == "matched" else "pending"
            cur = conn.execute(
                "INSERT INTO inbox (batch_id, source, account_id, op_date, amount, currency,"
                " raw_text, suggested_kind, suggested_category_id, match_status, match_entry_id,"
                " candidates, status, created_at, resolved_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (batch_id, batch.source, account_id, item["op_date"], item["amount"],
                 item["currency"], item["raw_text"], row.suggested_kind,
                 int(category["id"]) if category is not None else None,
                 item["status"], item["match_entry_id"],
                 json.dumps(item["candidates"], ensure_ascii=False), status, utc_now(),
                 utc_now() if status == "merged" else None))
            item["id"] = int(cur.lastrowid)
            created[item["status"]].append(_inbox_item(conn, item["id"]))
        audit(conn, "bot", "reconcile", "inbox", None,
              {"batch_id": batch_id, "rows": len(prepared)})
        if batch.balance is not None:
            from backend import settings_store
            settings_store.set(f"inbox_balance_{batch_id}",
                               {"balance": int(batch.balance), "account_id": account_id,
                                "currency": currency}, conn=conn)

    return {"batch_id": batch_id, "matched": created["matched"], "new": created["new"],
            "ambiguous": created["ambiguous"],
            "balance_check": balance_check(conn, account_id, batch.balance, currency)}


def balance_check(conn: sqlite3.Connection, account_id: int, bank: int | None,
                  currency: str) -> dict | None:
    if bank is None:
        return None
    ledger = account_balance(conn, account_id, currency)
    return {"bank": money_dict(int(bank), currency), "ledger": money_dict(ledger, currency),
            "diff": money_dict(int(bank) - ledger, currency)}


def _inbox_item(conn: sqlite3.Connection, inbox_id: int) -> dict:
    row = conn.execute("SELECT * FROM inbox WHERE id = ?", (inbox_id,)).fetchone()
    if row is None:
        raise LedgerError("not_found", "Строка сверки не найдена", {"id": inbox_id})
    return {
        "id": int(row["id"]), "batch_id": row["batch_id"], "op_date": row["op_date"],
        "amount": money_dict(int(row["amount"]), row["currency"]),
        "raw_text": row["raw_text"], "match_status": row["match_status"],
        "match_entry_id": row["match_entry_id"],
        "suggested_category_id": row["suggested_category_id"],
        "suggested_kind": row["suggested_kind"],
        "candidates": json.loads(row["candidates"] or "[]"),
        "status": row["status"], "entry_id": row["entry_id"],
    }


def inbox(batch_id: str | None = None) -> dict:
    conn = _conn()
    sql = "SELECT DISTINCT batch_id FROM inbox"
    args: list = []
    if batch_id:
        sql += " WHERE batch_id = ?"
        args.append(batch_id)
    batches = []
    for row in conn.execute(sql + " ORDER BY batch_id DESC", args).fetchall():
        rows = conn.execute("SELECT * FROM inbox WHERE batch_id = ? ORDER BY id",
                            (row["batch_id"],)).fetchall()
        if not rows:
            continue
        first = rows[0]
        batches.append({
            "batch_id": row["batch_id"], "source": first["source"],
            "account_id": first["account_id"],
            "created_at": int(first["created_at"]),
            "pending": sum(1 for r in rows if r["status"] == "pending"),
            "items": [_inbox_item(conn, int(r["id"])) for r in rows],
            "balance_check": balance_check(conn, int(first["account_id"]),
                                           _bank_balance_of_batch(conn, row["batch_id"]),
                                           first["currency"]),
        })
    return {"batches": batches}


def _op_from_inbox(conn: sqlite3.Connection, row: sqlite3.Row, category=None) -> ParsedOperation:
    amount = int(row["amount"])
    account = account_row(conn, int(row["account_id"]))
    source = "statement" if row["source"] == "statement" else "screenshot"
    if amount < 0:
        return ParsedOperation(kind="expense", amount=-amount, currency=row["currency"],
                               from_account=int(account["id"]),
                               category=category or row["suggested_category_id"] or "exp_other",
                               op_date=row["op_date"], description=row["raw_text"] or "",
                               source=source, raw_input=row["raw_text"])
    return ParsedOperation(kind="income", amount=amount, currency=row["currency"],
                           to_account=int(account["id"]), income_source="inc_other",
                           op_date=row["op_date"], description=row["raw_text"] or "",
                           source=source, raw_input=row["raw_text"])


def _check_new_row(conn: sqlite3.Connection, row: sqlite3.Row, op: ParsedOperation) -> None:
    """Проверка строки ДО записи: пачка применяется целиком или никак (§4.5, грабля 38)."""
    if int(row["amount"]) == 0:
        raise LedgerError("bad_request", "Строка с нулевой суммой не заносится",
                          {"inbox_id": int(row["id"]), "raw_text": row["raw_text"] or ""})
    resolve_account(conn, op.from_account if op.kind == "expense" else op.to_account,
                    field="account")
    if op.kind == "expense" and op.category is not None:
        resolve_account(conn, op.category, field="category")


def apply_reconcile(decisions: list[ReconcileDecision], *, actor: str = "bot",
                    currency_view: str = "RUB") -> dict:
    """Порядок строгий: сначала все new, потом выравнивание остатка (§4.5).

    Пачка — одна единица: сначала проверяются ВСЕ строки, потом одна транзакция на весь занос.
    Иначе плохая строка в середине оставляла половину скрина в журнале, а пользователь видел
    только ошибку (грабля 38). Карточка §7.4 подводит итог всей пачки одним сообщением — значит
    и результат у пачки должен быть один."""
    from backend.ledger import api
    conn = _conn()
    applied: list[dict] = []
    warnings: list[dict] = []
    touched: list[int] = []
    aligns = [d for d in decisions if d.decision == "align"]
    others = [d for d in decisions if d.decision != "align"]

    prepared: list[tuple[ReconcileDecision, sqlite3.Row, ParsedOperation | None]] = []
    for decision in others:
        row = conn.execute("SELECT * FROM inbox WHERE id = ?", (int(decision.inbox_id),)).fetchone()
        if row is None:
            raise LedgerError("not_found", "Строка сверки не найдена", {"id": decision.inbox_id})
        if decision.decision not in ("new", "same", "skip"):
            raise LedgerError("bad_request", "Неизвестное решение сверки",
                              {"decision": decision.decision})
        op = None
        if row["status"] == "pending" and decision.decision == "new":
            op = _op_from_inbox(conn, row, decision.category)
            _check_new_row(conn, row, op)
        prepared.append((decision, row, op))
    for decision in aligns:
        row = conn.execute("SELECT * FROM inbox WHERE id = ?", (int(decision.inbox_id),)).fetchone()
        if row is None:
            raise LedgerError("not_found", "Строка сверки не найдена", {"id": decision.inbox_id})

    with db.transaction(conn):
        for decision, row, op in prepared:
            if row["status"] != "pending":
                applied.append({"inbox_id": int(row["id"]), "status": row["status"],
                                "skipped": True})
                continue
            if decision.decision == "new":
                result = api.post_operation(op, actor=actor, currency_view=currency_view,
                                            external_ref=_ref_for_inbox(conn, row))
                conn.execute("UPDATE inbox SET status = 'accepted', entry_id = ?, resolved_at = ?"
                             " WHERE id = ?", (result["id"], utc_now(), int(row["id"])))
                warnings.extend(result.get("warnings") or [])
                touched.extend(a["id"] for a in result["effects"]["accounts"])
                applied.append({"inbox_id": int(row["id"]), "status": "accepted",
                                "entry_id": result["id"]})
            elif decision.decision == "same":
                conn.execute("UPDATE inbox SET status = 'merged', match_entry_id = COALESCE(?,"
                             " match_entry_id), resolved_at = ? WHERE id = ?",
                             (decision.match_entry_id, utc_now(), int(row["id"])))
                applied.append({"inbox_id": int(row["id"]), "status": "merged"})
            else:
                conn.execute("UPDATE inbox SET status = 'skipped', resolved_at = ? WHERE id = ?",
                             (utc_now(), int(row["id"])))
                applied.append({"inbox_id": int(row["id"]), "status": "skipped"})

        for decision in aligns:
            row = conn.execute("SELECT * FROM inbox WHERE id = ?",
                               (int(decision.inbox_id),)).fetchone()
            result = align(row["batch_id"], bank_balance=None, actor=actor,
                           currency_view=currency_view)
            warnings.extend(result.get("warnings") or [])
            applied.append({"batch_id": row["batch_id"], "status": "aligned",
                            "entry_id": result.get("entry_id")})

    return {"applied": applied,
            "effects": build_effects(conn, account_ids=touched, currency_view=currency_view),
            "warnings": warnings}


def _ref_for_inbox(conn: sqlite3.Connection, row: sqlite3.Row) -> str | None:
    """Отпечаток строки восстанавливается с тем же ordinal, что при разборе пачки."""
    same = conn.execute(
        "SELECT id FROM inbox WHERE batch_id = ? AND op_date IS ? AND amount = ?"
        " AND IFNULL(raw_text,'') = IFNULL(?,'') ORDER BY id",
        (row["batch_id"], row["op_date"], int(row["amount"]), row["raw_text"])).fetchall()
    ordinal = next((i + 1 for i, r in enumerate(same) if int(r["id"]) == int(row["id"])), 1)
    account = account_row(conn, int(row["account_id"]))
    return _fingerprint(account["slug"], row["op_date"], int(row["amount"]),
                        row["raw_text"] or "", ordinal)


def align(batch_id: str, *, bank_balance: int | None = None, actor: str = "bot",
          currency_view: str = "RUB") -> dict:
    """«Выровнять»: расхождение пересчитывается на момент нажатия (§4.5 п. 6)."""
    from backend.ledger import api
    conn = _conn()
    rows = conn.execute("SELECT * FROM inbox WHERE batch_id = ? ORDER BY id", (batch_id,)).fetchall()
    context = _batch_context(conn, batch_id)
    if not rows and context is None:
        raise LedgerError("not_found", "Пачка не найдена", {"batch_id": batch_id})
    if any(r["status"] == "pending" for r in rows):
        raise LedgerError("batch_has_pending", "В пачке остались неразобранные строки",
                          {"batch_id": batch_id})
    if rows:
        account_id = int(rows[0]["account_id"])
        currency = rows[0]["currency"]
    else:                                  # скрин без строк — только остаток на экране
        account_id = int(context["account_id"])
        currency = context["currency"]
    bank = bank_balance
    if bank is None:
        bank = _bank_balance_of_batch(conn, batch_id)
    if bank is None:
        raise LedgerError("bad_request", "Не известен остаток по банку для выравнивания",
                          {"batch_id": batch_id})
    ledger = account_balance(conn, account_id, currency)
    diff = int(bank) - ledger
    if diff == 0:
        return {"ok": True, "entry_id": None,
                "warnings": [warn("already_aligned", "Уже сходится, корректировка не нужна",
                                  {"batch_id": batch_id})],
                "effects": build_effects(conn, account_ids=[account_id],
                                         currency_view=currency_view)}
    op = ParsedOperation(kind="balance_correction", amount=diff, currency=currency,
                         to_account=account_id, source="screenshot",
                         description=f"Выравнивание по скрину {fmt_amount(diff, currency)}")
    result = api.post_operation(op, actor=actor, currency_view=currency_view)
    return {"ok": True, "entry_id": result["id"], "warnings": result.get("warnings") or [],
            "effects": result["effects"]}


def remember_bank_balance(batch_id: str, balance: int | None, *, account_id: int | None = None,
                          currency: str | None = None) -> None:
    """Остаток со скрина кладём в settings: отдельного поля в схеме нет, а пережить рестарт надо."""
    if balance is None:
        return
    from backend import settings_store
    settings_store.set(f"inbox_balance_{batch_id}",
                       {"balance": int(balance), "account_id": account_id, "currency": currency},
                       conn=_conn())


def _batch_context(conn: sqlite3.Connection, batch_id: str) -> dict | None:
    from backend import settings_store
    value = settings_store.get(f"inbox_balance_{batch_id}", None, conn=conn)
    if isinstance(value, dict):
        return value
    if value is not None:
        return {"balance": int(value), "account_id": None, "currency": None}
    return None


def _bank_balance_of_batch(conn: sqlite3.Connection, batch_id: str) -> int | None:
    context = _batch_context(conn, batch_id)
    return int(context["balance"]) if context else None
