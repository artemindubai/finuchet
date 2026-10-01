# -*- coding: utf-8 -*-
"""Ядро учёта: запись операций, версии, отмена, чтение журнала (ARCHITECTURE §4.1).

Ядро — единственное место, где рождаются проводки. Его зовут и API, и бот; бот в БД не ходит."""
from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import asdict, fields

from backend import db, rates
from backend.contracts import (EntryFilters, LedgerError, OpeningBalanceItem, OperationPatch,
                               ParsedOperation)
from backend.ledger.common import (account_row, audit, counterparty_name, money_dict,
                                   resolve_account, snapshot_of, to_view, warn)
from backend.ledger.recipes import build as build_recipe
from backend.money import fmt_amount
from backend.tz import human_day, iso_utc, today_dubai, utc_now
from backend.ledger.balances import effects as build_effects, family_debt as family_debt_of
from backend.ledger.tranches import (RELEASE_KINDS, guard_no_releases,
                                     open_rows as open_tranche_rows, open_tranche,
                                     rebuild_releases, releases_of_entry, shortfall_warning,
                                     touches_freeze, tranche_of_entry, unlocks_of_entry,
                                     move_rows, move_view, view as tranche_view)

DIRECTION = {
    "expense": "out", "income": "in", "transfer": "neutral", "exchange": "neutral",
    "family_withdrawal": "neutral", "family_repayment": "out",
    "family_topup_by_parents": "in", "own_contribution_to_family": "out",
    "family_spent_own": "neutral", "paid_for_family_from_own": "out",
    "loan_given": "out", "loan_repaid_to_me": "in", "loan_taken": "in",
    "loan_repaid_by_me": "out", "tax_payment": "out",
    "opening_balance": "neutral", "balance_correction": "neutral",
}

KIND_TITLE = {
    "transfer": "Перевод", "exchange": "Обмен",
    "family_withdrawal": "Взял из семейного", "family_repayment": "Вернул в семейный",
    "family_topup_by_parents": "Пополнение семейного",
    "own_contribution_to_family": "Внёс своих в семейный",
    "family_spent_own": "Семья потратила из семейного",
    "paid_for_family_from_own": "Заплатил за семью",
    "loan_given": "Дал в долг", "loan_repaid_to_me": "Вернули долг",
    "loan_taken": "Взял в долг", "loan_repaid_by_me": "Вернул долг",
    "tax_payment": "Уплата налога", "opening_balance": "Начальный остаток",
    "balance_correction": "Выравнивание остатка",
}

KIND_STYLE = {
    "transfer": ("swap", "#7B8794"), "exchange": ("swap", "#00A88F"),
    "family_withdrawal": ("family", "#34B37E"), "family_repayment": ("family", "#34B37E"),
    "family_topup_by_parents": ("family", "#34B37E"), "family_spent_own": ("family", "#34B37E"),
    "own_contribution_to_family": ("family", "#1FA855"),
    "paid_for_family_from_own": ("family", "#1FA855"),
    "loan_given": ("person", "#5B6CD9"), "loan_repaid_to_me": ("person", "#5B6CD9"),
    "loan_taken": ("person", "#5B6CD9"), "loan_repaid_by_me": ("person", "#5B6CD9"),
    "tax_payment": ("tax", "#6E7781"), "opening_balance": ("adjust", "#A0A7B0"),
    "balance_correction": ("adjust", "#A0A7B0"),
}

KINDS = [
    ("expense", "Расход"), ("income", "Доход"), ("transfer", "Перевод"), ("exchange", "Обмен"),
    ("family_withdrawal", "Взял из семейного"), ("family_repayment", "Вернул в семейный"),
    ("family_topup_by_parents", "Пополнение семейного"),
    ("own_contribution_to_family", "Внёс своих в семейный"),
    ("family_spent_own", "Семья потратила"), ("paid_for_family_from_own", "Заплатил за семью"),
    ("loan_given", "Дал в долг"), ("loan_repaid_to_me", "Вернули долг"),
    ("loan_taken", "Взял в долг"), ("loan_repaid_by_me", "Вернул долг"),
    ("tax_payment", "Уплата налога"), ("opening_balance", "Начальный остаток"),
    ("balance_correction", "Выравнивание остатка"),
]

PLANNED_KINDS = ("loan_given", "loan_taken", "loan_repaid_to_me", "loan_repaid_by_me", "tax_payment")


# --------------------------------------------------------------------------------------
# служебное


def _conn() -> sqlite3.Connection:
    return db.get_conn()


def _styles(conn: sqlite3.Connection) -> dict[int, tuple[str | None, str | None]]:
    out: dict[int, tuple[str | None, str | None]] = {}
    for row in conn.execute(
            "SELECT c.account_id AS id, a.icon AS icon, c.color AS color"
            " FROM categories c JOIN accounts a ON a.id = c.account_id").fetchall():
        out[int(row["id"])] = (row["icon"], row["color"])
    for row in conn.execute(
            "SELECT s.account_id AS id, COALESCE(s.icon, a.icon) AS icon, s.color AS color"
            " FROM income_sources s JOIN accounts a ON a.id = s.account_id").fetchall():
        out[int(row["id"])] = (row["icon"], row["color"])
    return out


def _accounts(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {int(row["id"]): row for row in conn.execute("SELECT * FROM accounts").fetchall()}


def _postings_of(conn: sqlite3.Connection, entry_ids: list[int]) -> dict[int, list[sqlite3.Row]]:
    if not entry_ids:
        return {}
    marks = ",".join("?" * len(entry_ids))
    rows = conn.execute(
        f"SELECT * FROM postings WHERE entry_id IN ({marks}) ORDER BY entry_id, seq",
        entry_ids).fetchall()
    out: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        out.setdefault(int(row["entry_id"]), []).append(row)
    return out


def _headline(kind: str, postings: list[sqlite3.Row], accounts: dict[int, sqlite3.Row]) -> tuple[int, str]:
    """Сумма и валюта, которые видит человек в строке операции."""
    if not postings:
        return 0, "RUB"
    if kind == "exchange":
        for row in postings:
            account = accounts.get(int(row["account_id"]))
            if int(row["amount"]) < 0 and account is not None and account["slug"] != "eq_exchange":
                return abs(int(row["amount"])), row["currency"]
    if kind == "balance_correction":
        for row in postings:
            account = accounts.get(int(row["account_id"]))
            if account is not None and account["slug"] not in ("eq_correction", "family_fund"):
                return int(row["amount"]), row["currency"]
    first = postings[0]
    return abs(int(first["amount"])), first["currency"]


def _title_subtitle(conn: sqlite3.Connection, entry: sqlite3.Row, postings: list[sqlite3.Row],
                    accounts: dict[int, sqlite3.Row]) -> tuple[str, str, int | None]:
    kind = entry["kind"]
    money_ins = [accounts[int(p["account_id"])] for p in postings
                 if int(p["amount"]) > 0 and int(p["account_id"]) in accounts]
    money_outs = [accounts[int(p["account_id"])] for p in postings
                  if int(p["amount"]) < 0 and int(p["account_id"]) in accounts]

    if kind == "expense":
        cat = next((a for a in money_ins if a["type"] == "expense"), None)
        src = next((a for a in money_outs if a["type"] in ("asset_personal", "liability")), None)
        return (cat["name"] if cat else "Расход", src["name"] if src else "",
                int(cat["id"]) if cat else None)
    if kind == "income":
        source = next((a for a in money_outs if a["type"] == "income"), None)
        dst = next((a for a in money_ins if a["type"] == "asset_personal"), None)
        return (source["name"] if source else "Доход", dst["name"] if dst else "",
                int(source["id"]) if source else None)
    if kind in ("transfer", "exchange", "family_withdrawal", "family_repayment",
                "own_contribution_to_family"):
        def pick(rows):
            candidates = [a for a in rows if a["slug"] not in ("eq_exchange", "family_fund")
                          and a["type"] != "expense"]
            money = [a for a in candidates if a["is_money"]]
            pool = money or candidates or [a for a in rows if a["slug"] != "eq_exchange"]
            return pool[0] if pool else None
        src = pick(money_outs)
        dst = pick(money_ins)
        src_name = src["name"] if src is not None else ""
        dst_name = dst["name"] if dst is not None else ""
        return KIND_TITLE.get(kind, kind), f"{src_name} → {dst_name}".strip(" →"), None
    title = KIND_TITLE.get(kind, kind)
    if kind in ("loan_given", "loan_repaid_to_me", "loan_taken", "loan_repaid_by_me"):
        name = counterparty_name(conn, entry["counterparty_id"])
        if name:
            title = f"{title} · {name}"
    account = next((a for a in money_ins + money_outs
                    if a["is_money"] or a["slug"] in ("tax_npd", "family_fund")), None)
    return title, account["name"] if account else "", None


def entry_short(conn: sqlite3.Connection, entry: sqlite3.Row, *, postings: list[sqlite3.Row],
                accounts: dict[int, sqlite3.Row], styles: dict, currency_view: str = "RUB") -> dict:
    amount, currency = _headline(entry["kind"], postings, accounts)
    title, subtitle, style_id = _title_subtitle(conn, entry, postings, accounts)
    icon, color = KIND_STYLE.get(entry["kind"], ("dots", "#A0A7B0"))
    if style_id and style_id in styles:
        icon, color = styles[style_id][0] or icon, styles[style_id][1] or color
    snapshot = snapshot_of(conn, entry["rates_snapshot"])
    return {
        "id": int(entry["id"]), "kind": entry["kind"], "direction": DIRECTION.get(entry["kind"], "neutral"),
        "amount": money_dict(amount, currency),
        "amount_in_view": money_dict(to_view(abs(amount), currency, currency_view, snapshot),
                                     currency_view),
        "title": title, "subtitle": subtitle,
        "category_id": style_id, "icon": icon, "color": color,
        "version": int(entry["version"]),
        "op_date": entry["op_date"], "created_at": iso_utc(int(entry["created_at"])),
        "status": entry["status"], "source": entry["source"],
        "description": entry["description"] or "",
        "counterparty": counterparty_name(conn, entry["counterparty_id"]),
        "project": entry["project"],
    }


def _versions(conn: sqlite3.Connection, entry: sqlite3.Row) -> list[dict]:
    chain: list[sqlite3.Row] = [entry]
    cursor = entry
    while cursor["replaces_entry_id"]:
        cursor = conn.execute("SELECT * FROM entries WHERE id = ?",
                              (int(cursor["replaces_entry_id"]),)).fetchone()
        if cursor is None:
            break
        chain.insert(0, cursor)
    cursor = entry
    while cursor is not None and cursor["replaced_by_entry_id"]:
        cursor = conn.execute("SELECT * FROM entries WHERE id = ?",
                              (int(cursor["replaced_by_entry_id"]),)).fetchone()
        if cursor is None:
            break
        chain.append(cursor)
    out = []
    for row in chain:
        changed = []
        audit_row = conn.execute(
            "SELECT payload FROM audit_log WHERE action = 'amend' AND object_id = ?"
            " ORDER BY id DESC LIMIT 1", (int(row["id"]),)).fetchone()
        if audit_row and audit_row["payload"]:
            try:
                changed = json.loads(audit_row["payload"]).get("changed", [])
            except json.JSONDecodeError:
                changed = []
        out.append({"id": int(row["id"]), "version": int(row["version"]), "status": row["status"],
                    "created_at": iso_utc(int(row["created_at"])), "changed": changed})
    return out


def entry_full(conn: sqlite3.Connection, entry_id: int, *, currency_view: str = "RUB",
               warnings: list[dict] | None = None) -> dict:
    entry = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if entry is None:
        raise LedgerError("not_found", "Операция не найдена", {"entry_id": entry_id})
    accounts = _accounts(conn)
    styles = _styles(conn)
    postings = _postings_of(conn, [entry_id]).get(entry_id, [])
    short = entry_short(conn, entry, postings=postings, accounts=accounts, styles=styles,
                        currency_view=currency_view)
    snapshot = snapshot_of(conn, entry["rates_snapshot"])
    posting_list = []
    for row in postings:
        account = accounts.get(int(row["account_id"]))
        posting_list.append({
            "seq": int(row["seq"]), "account_id": int(row["account_id"]),
            "account_slug": account["slug"] if account else None,
            "account_name": account["name"] if account else None,
            "side": "debit" if int(row["amount"]) > 0 else "credit",
            "amount": money_dict(abs(int(row["amount"])), row["currency"]),
            "counterparty": counterparty_name(conn, row["counterparty_id"]),
            "project": row["project"],
        })
    rate = None
    if snapshot.get("used_rate_e6"):
        rate = {"pair": snapshot.get("used_pair"), "rate_e6": snapshot.get("used_rate_e6"),
                "source": snapshot.get("used_source"), "at": snapshot.get("at")}
    tranche_row = tranche_of_entry(conn, entry_id)
    short.update({
        "replaces_entry_id": entry["replaces_entry_id"],
        "replaced_by_entry_id": entry["replaced_by_entry_id"],
        "voided_at": iso_utc(int(entry["voided_at"])) if entry["voided_at"] else None,
        "void_reason": entry["void_reason"],
        "due_date": entry["due_date"],
        "raw_input": entry["raw_input"],
        "confidence": entry["confidence"],
        "postings": posting_list,
        "rate": rate,
        "rates_snapshot": snapshot,
        "tranche": tranche_view(conn, tranche_row) if tranche_row is not None else None,
        "versions": _versions(conn, entry),
        "warnings": warnings or [],
    })
    return short


# --------------------------------------------------------------------------------------
# запись


def _validate_postings(conn: sqlite3.Connection, postings: list[dict],
                       accounts: dict[int, sqlite3.Row], *, source: str = "manual") -> list[dict]:
    """Проверки перед записью. Возвращает предупреждения (архивный счёт при заносе истории)."""
    warnings: list[dict] = []
    by_currency: dict[str, int] = {}
    for posting in postings:
        account = accounts.get(int(posting["account_id"]))
        if account is None:
            raise LedgerError("unknown_account", "Счёт не найден", {"id": posting["account_id"]})
        if account["archived"]:
            # Занос истории (скрин, выписка) на архивный счёт — это прошлое, его пропускаем
            # с предупреждением. Новая операция руками или голосом — ошибка (§5.11, грабля 37).
            if source in ("screenshot", "statement"):
                warnings.append(warn(
                    "archived_account_used",
                    f"Счёт {account['name']} в архиве — операция занесена как есть",
                    {"account": account["slug"]}))
            else:
                raise LedgerError("account_archived",
                                  f"Счёт {account['name']} в архиве: операции по нему не заносятся",
                                  {"account": account["slug"]})
        if account["currency"] and account["currency"] != posting["currency"]:
            raise LedgerError("currency_mismatch",
                              f"Счёт {account['name']} ведётся в {account['currency']}",
                              {"account": account["slug"], "expected": account["currency"],
                               "got": posting["currency"]})
        if account["needs_counterparty"] and not posting.get("counterparty_id"):
            raise LedgerError("counterparty_required", "Долговая проводка без контрагента",
                              {"account": account["slug"]})
        by_currency[posting["currency"]] = by_currency.get(posting["currency"], 0) + int(posting["amount"])
    for currency, total in by_currency.items():
        if total != 0:
            raise LedgerError("unbalanced_entry", f"Проводки не сходятся по {currency}: {total}",
                              {"currency": currency, "diff": total})
    return warnings


def _rate_for_freeze(conn: sqlite3.Connection, op: ParsedOperation, amount: int,
                     warnings: list[dict]):
    from backend.contracts import RateQuote
    if op.rate_e6:
        return RateQuote("AED/RUB", int(op.rate_e6), op.rate_source or "voice", utc_now())
    quote = rates.get("AED/RUB", amount_minor=amount, conn=conn)
    if quote.stale:
        warnings.append(warn("rate_from_cache",
                             f"Курс взят из кэша от {iso_utc(quote.at)}",
                             {"pair": quote.pair, "at": iso_utc(quote.at)}))
    return quote


def _write_entry(conn: sqlite3.Connection, op: ParsedOperation, *, actor: str,
                 external_ref: str | None = None, version: int = 1,
                 replaces_entry_id: int | None = None) -> dict:
    built = build_recipe(conn, op)
    op = built["op"]
    postings = built["postings"]
    warnings = list(built["warnings"])
    meta = built["meta"]
    accounts = _accounts(conn)
    warnings.extend(_validate_postings(conn, postings, accounts, source=op.source))

    snapshot = rates.snapshot(conn=conn)
    quote = None
    if op.kind == "family_withdrawal" and meta.get("freeze"):
        quote = _rate_for_freeze(conn, op, int(op.amount), warnings)
        snapshot["used_rate_e6"] = int(quote.rate_e6)
        snapshot["used_pair"] = "AED/RUB"
        snapshot["used_source"] = quote.source
    elif op.kind == "exchange" and meta.get("rate_e6"):
        snapshot["used_rate_e6"] = int(meta["rate_e6"])
        snapshot["used_pair"] = meta.get("rate_pair")
        snapshot["used_source"] = op.rate_source or ("voice" if op.rate_e6 else "manual")

    cursor = conn.execute(
        "INSERT INTO entries (kind, op_date, created_at, description, source, status, version,"
        " replaces_entry_id, rates_snapshot, raw_input, confidence, counterparty_id, project,"
        " external_ref, due_date, sealed)"
        " VALUES (?,?,?,?,?,'posted',?,?,?,?,?,?,?,?,?,0)",
        (op.kind, op.op_date, utc_now(), op.description or "", op.source, version,
         replaces_entry_id, json.dumps(snapshot, ensure_ascii=False), op.raw_input,
         op.confidence, built["counterparty_id"], op.project, external_ref, op.due_date))
    entry_id = int(cursor.lastrowid)

    for seq, posting in enumerate(postings, start=1):
        conn.execute(
            "INSERT INTO postings (entry_id, seq, account_id, amount, currency, counterparty_id,"
            " project, memo) VALUES (?,?,?,?,?,?,?,?)",
            (entry_id, seq, posting["account_id"], posting["amount"], posting["currency"],
             posting.get("counterparty_id"), posting.get("project"), posting.get("memo")))
    conn.execute("UPDATE entries SET sealed = 1 WHERE id = ?", (entry_id,))

    tranche_block = None
    released: list[dict] = []
    unlocked: list[dict] = []
    tranche_id = None
    if op.kind == "family_withdrawal" and meta.get("freeze") and quote is not None:
        tranche_id, freeze_warnings = open_tranche(
            conn, entry_id=entry_id, op_date=op.op_date, aed_taken=int(op.amount),
            quote=quote, account_ref=op.freeze_account)
        warnings.extend(freeze_warnings)
    if tranche_id is not None or op.kind in RELEASE_KINDS:
        # Транши пересчитываются целиком: их состояние — функция журнала (§4.3, грабля 28).
        shortfall = rebuild_releases(conn)
        if tranche_id is not None:
            row = conn.execute("SELECT * FROM family_tranches WHERE id = ?",
                               (tranche_id,)).fetchone()
            tranche_block = tranche_view(conn, row)
        if op.kind in RELEASE_KINDS:
            released = releases_of_entry(conn, entry_id)
            unlocked = unlocks_of_entry(conn, entry_id)
            extra = shortfall_warning(op.kind, shortfall.get(entry_id, 0))
            if extra:
                warnings.append(extra)

    if op.due_date and op.kind in PLANNED_KINDS:
        _ensure_planned_from_due(conn, entry_id, op)

    audit(conn, actor, "post", "entry", entry_id,
          {"op": {key: value for key, value in asdict(op).items() if value is not None},
           "kind": op.kind})

    touched = [int(p["account_id"]) for p in postings]
    if tranche_block and tranche_block.get("account_id"):
        touched.append(int(tranche_block["account_id"]))
    for release in released:
        row = conn.execute("SELECT account_id FROM family_tranches WHERE id = ?",
                           (release["tranche_id"],)).fetchone()
        if row is not None and row["account_id"]:
            touched.append(int(row["account_id"]))
    touched.extend(item["account_id"] for item in unlocked)
    return {"entry_id": entry_id, "warnings": warnings, "tranche": tranche_block,
            "released": released, "unlocked": unlocked, "accounts": touched}


def _ensure_planned_from_due(conn: sqlite3.Connection, entry_id: int, op: ParsedOperation) -> None:
    """Названный срок = строка календаря платежей (§4.2). Единственный случай напоминания."""
    title = KIND_TITLE.get(op.kind, "Платёж")
    name = op.counterparty
    if name:
        title = f"{title} · {name}"
    account = account_row(conn, op.from_account or op.to_account)
    conn.execute(
        "INSERT INTO planned_payments (title, amount, currency, account_id, category_id,"
        " counterparty_id, repeat, next_date, remind_days_before, active, created_at)"
        " VALUES (?,?,?,?,NULL,NULL,'once',?,1,1,?)",
        (title, int(op.amount), op.currency, int(account["id"]) if account is not None else None,
         op.due_date, utc_now()))


def _result(conn: sqlite3.Connection, written: dict, *, currency_view: str = "RUB") -> dict:
    out = entry_full(conn, written["entry_id"], currency_view=currency_view,
                     warnings=written["warnings"])
    out["effects"] = build_effects(conn, account_ids=written["accounts"],
                                          currency_view=currency_view,
                                          tranche=written.get("tranche"),
                                          released=written.get("released"),
                                          unlocked=written.get("unlocked"))
    if out.get("kind") == "income":
        from backend.ledger.kopilka import for_entry as kopilka_for_entry
        out["kopilka"] = kopilka_for_entry(conn, int(written["entry_id"]))
    return out


def post_operation(op: ParsedOperation, *, actor: str = "bot", currency_view: str = "RUB",
                   external_ref: str | None = None) -> dict:
    conn = _conn()
    with db.transaction(conn):
        written = _write_entry(conn, op, actor=actor, external_ref=external_ref)
    return _result(conn, written, currency_view=currency_view)


def post_opening_balances(items: list[OpeningBalanceItem], *, actor: str = "manual",
                          op_date: str | None = None, currency_view: str = "RUB") -> dict:
    conn = _conn()
    created = []
    warnings: list[dict] = []
    touched: list[int] = []
    with db.transaction(conn):
        for item in items:
            account = resolve_account(conn, item.account, field="account")
            op = ParsedOperation(kind="opening_balance", amount=int(item.amount),
                                 currency=item.currency, to_account=int(account["id"]),
                                 op_date=item.op_date or op_date or today_dubai(),
                                 source="manual", description="Начальный остаток")
            written = _write_entry(conn, op, actor=actor)
            warnings.extend(written["warnings"])
            touched.extend(written["accounts"])
            created.append({"entry_id": written["entry_id"], "account": account["slug"]})
    return {"created": created,
            "effects": build_effects(conn, account_ids=touched, currency_view=currency_view),
            "warnings": warnings}


def void_entry(entry_id: int, *, actor: str = "bot", reason: str | None = None,
               currency_view: str = "RUB") -> dict:
    conn = _conn()
    with db.transaction(conn):
        entry = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if entry is None:
            raise LedgerError("not_found", "Операция не найдена", {"entry_id": entry_id})
        if entry["status"] == "void":
            raise LedgerError("already_void", "Операция уже отменена", {"entry_id": entry_id})
        guard_no_releases(conn, entry_id)        # §4.3 б: сначала отменяется возврат
        conn.execute("UPDATE entries SET status = 'void', void_reason = ?, voided_at = ? WHERE id = ?",
                     (reason, utc_now(), entry_id))
        if touches_freeze(conn, entry_id):
            rebuild_releases(conn)
        accounts = [int(row["account_id"]) for row in
                    conn.execute("SELECT account_id FROM postings WHERE entry_id = ?",
                                 (entry_id,)).fetchall()]
        audit(conn, actor, "void", "entry", entry_id, {"reason": reason})
    out = entry_full(conn, entry_id, currency_view=currency_view)
    out["effects"] = build_effects(conn, account_ids=accounts, currency_view=currency_view)
    return out


def unvoid_entry(entry_id: int, *, actor: str = "api", currency_view: str = "RUB") -> dict:
    conn = _conn()
    with db.transaction(conn):
        entry = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if entry is None:
            raise LedgerError("not_found", "Операция не найдена", {"entry_id": entry_id})
        if entry["status"] != "void":
            raise LedgerError("not_voided", "Операция не отменена", {"entry_id": entry_id})
        if entry["replaced_by_entry_id"]:
            raise LedgerError("entry_is_old_version",
                              "Эту операцию заменила правка — отмените сначала новую версию",
                              {"entry_id": entry_id,
                               "replaced_by": int(entry["replaced_by_entry_id"])})
        conn.execute("UPDATE entries SET status = 'posted', void_reason = NULL, voided_at = NULL"
                     " WHERE id = ?", (entry_id,))
        if touches_freeze(conn, entry_id):
            rebuild_releases(conn)
        accounts = [int(row["account_id"]) for row in
                    conn.execute("SELECT account_id FROM postings WHERE entry_id = ?",
                                 (entry_id,)).fetchall()]
        audit(conn, actor, "unvoid", "entry", entry_id, None)
    out = entry_full(conn, entry_id, currency_view=currency_view)
    out["effects"] = build_effects(conn, account_ids=accounts, currency_view=currency_view)
    return out


def _op_of_entry(conn: sqlite3.Connection, entry_id: int) -> ParsedOperation:
    """Исходная операция из журнала действий — по ней строится новая версия при правке."""
    row = conn.execute(
        "SELECT payload FROM audit_log WHERE action = 'post' AND object_type = 'entry'"
        " AND object_id = ? ORDER BY id DESC LIMIT 1", (entry_id,)).fetchone()
    if row is None or not row["payload"]:
        raise LedgerError("bad_request", "Нет исходных данных операции для правки",
                          {"entry_id": entry_id})
    data = json.loads(row["payload"]).get("op") or {}
    known = {f.name for f in fields(ParsedOperation)}
    return ParsedOperation(**{k: v for k, v in data.items() if k in known})


def _changes(conn: sqlite3.Connection, old: ParsedOperation, new: ParsedOperation) -> list[str]:
    out = []
    if old.amount != new.amount or old.currency != new.currency:
        out.append(f"сумма {fmt_amount(int(old.amount or 0), old.currency)} → "
                   f"{fmt_amount(int(new.amount or 0), new.currency)}")
    for field, label in (("from_account", "счёт"), ("to_account", "счёт получателя"),
                         ("category", "категория"), ("income_source", "источник")):
        before, after = getattr(old, field), getattr(new, field)
        if before != after and after is not None:
            before_row = account_row(conn, before)
            after_row = account_row(conn, after)
            out.append(f"{label} {before_row['name'] if before_row is not None else '—'} → "
                       f"{after_row['name'] if after_row is not None else '—'}")
    if old.op_date != new.op_date:
        out.append(f"дата {old.op_date} → {new.op_date}")
    if old.kind != new.kind:
        out.append(f"вид операции {old.kind} → {new.kind}")
    return out


def amend_entry(entry_id: int, patch: OperationPatch, *, actor: str = "bot",
                currency_view: str = "RUB") -> dict:
    conn = _conn()
    with db.transaction(conn):
        entry = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if entry is None:
            raise LedgerError("not_found", "Операция не найдена", {"entry_id": entry_id})
        if entry["replaced_by_entry_id"]:
            raise LedgerError("entry_is_old_version", "Это не последняя версия операции",
                              {"entry_id": entry_id,
                               "replaced_by": int(entry["replaced_by_entry_id"])})
        guard_no_releases(conn, entry_id)

        old_op = _op_of_entry(conn, entry_id)
        new_op = ParsedOperation(**asdict(old_op))
        for field in fields(OperationPatch):
            value = getattr(patch, field.name)
            if value is not None:
                setattr(new_op, field.name, value)
        if patch.raw_input:
            new_op.raw_input = f"{old_op.raw_input or ''} | {patch.raw_input}".strip(" |")
        new_op.source = old_op.source

        changed = _changes(conn, old_op, new_op)
        conn.execute("UPDATE entries SET status = 'void', voided_at = ?, void_reason = 'amend'"
                     " WHERE id = ?", (utc_now(), entry_id))
        if touches_freeze(conn, entry_id):
            rebuild_releases(conn)               # старая версия ушла из журнала
        written = _write_entry(conn, new_op, actor=actor,
                               external_ref=entry["external_ref"],
                               version=int(entry["version"]) + 1, replaces_entry_id=entry_id)
        conn.execute("UPDATE entries SET replaced_by_entry_id = ? WHERE id = ?",
                     (written["entry_id"], entry_id))
        if entry["counterparty_id"] and not new_op.counterparty:
            conn.execute("UPDATE entries SET counterparty_id = ? WHERE id = ?",
                         (int(entry["counterparty_id"]), written["entry_id"]))
        audit(conn, actor, "amend", "entry", written["entry_id"],
              {"changed": changed, "from_entry": entry_id})
        written["accounts"].extend(
            int(row["account_id"]) for row in
            conn.execute("SELECT account_id FROM postings WHERE entry_id = ?", (entry_id,)).fetchall())
    return _result(conn, written, currency_view=currency_view)


# --------------------------------------------------------------------------------------
# чтение


def get_entry(entry_id: int, *, currency_view: str = "RUB") -> dict:
    return entry_full(_conn(), entry_id, currency_view=currency_view)


def _encode_cursor(op_date: str, entry_id: int) -> str:
    return base64.b64encode(f"{op_date}|{entry_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        raw = base64.b64decode(cursor.encode()).decode()
        op_date, entry_id = raw.split("|")
        return op_date, int(entry_id)
    except Exception as exc:
        raise LedgerError("bad_request", "Битый курсор", {"cursor": cursor}) from exc


def _filters_sql(f: EntryFilters) -> tuple[str, list]:
    where = ["1=1"]
    args: list = []
    if f.status == "posted":
        where.append("e.status = 'posted'")
    elif f.status == "void":
        where.append("e.status = 'void'")
    if f.kind:
        where.append("e.kind = ?")
        args.append(f.kind)
    if f.date_from:
        where.append("e.op_date >= ?")
        args.append(f.date_from)
    if f.date_to:
        where.append("e.op_date <= ?")
        args.append(f.date_to)
    if f.account_id:
        where.append("EXISTS (SELECT 1 FROM postings p WHERE p.entry_id = e.id AND p.account_id = ?)")
        args.append(int(f.account_id))
    if f.category_id:
        where.append("EXISTS (SELECT 1 FROM postings p WHERE p.entry_id = e.id AND p.account_id = ?)")
        args.append(int(f.category_id))
    if f.q:
        like = f"%{f.q.strip()}%"
        where.append("(e.description LIKE ? OR e.raw_input LIKE ? OR e.project LIKE ?"
                     " OR EXISTS (SELECT 1 FROM counterparties c WHERE c.id = e.counterparty_id"
                     "            AND c.name LIKE ?))")
        args.extend([like, like, like, like])
    return " AND ".join(where), args


def list_entries(f: EntryFilters) -> dict:
    conn = _conn()
    where, args = _filters_sql(f)
    limit = max(1, min(int(f.limit or 50), 200))
    page_args = list(args)
    page_where = where
    if f.cursor:
        op_date, entry_id = _decode_cursor(f.cursor)
        page_where += " AND (e.op_date < ? OR (e.op_date = ? AND e.id < ?))"
        page_args.extend([op_date, op_date, entry_id])

    rows = conn.execute(
        f"SELECT * FROM entries e WHERE {page_where} ORDER BY e.op_date DESC, e.id DESC LIMIT ?",
        page_args + [limit + 1]).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    total = int(conn.execute(f"SELECT COUNT(*) AS n FROM entries e WHERE {where}",
                             args).fetchone()["n"])

    accounts = _accounts(conn)
    styles = _styles(conn)
    postings = _postings_of(conn, [int(r["id"]) for r in rows])
    items = [entry_short(conn, row, postings=postings.get(int(row["id"]), []), accounts=accounts,
                         styles=styles, currency_view=f.currency_view) for row in rows]

    days: list[dict] = []
    index: dict[str, dict] = {}
    today = today_dubai()
    for item in items:
        day = index.get(item["op_date"])
        if day is None:
            day = {"date": item["op_date"], "title": human_day(item["op_date"], today=today),
                   "total_out": money_dict(0, f.currency_view),
                   "total_in": money_dict(0, f.currency_view), "ids": []}
            index[item["op_date"]] = day
            days.append(day)
        day["ids"].append(item["id"])
        if item["status"] != "posted":
            continue
        if item["direction"] == "out":
            day["total_out"]["amount"] += item["amount_in_view"]["amount"]
        elif item["direction"] == "in":
            day["total_in"]["amount"] += item["amount_in_view"]["amount"]

    out = {"items": items, "days": days,
           "next_cursor": _encode_cursor(items[-1]["op_date"], items[-1]["id"]) if items and has_more
           else None,
           "has_more": has_more, "total": total}
    if not f.cursor:
        from backend.ledger import analytics
        out["summary"] = analytics.feed_summary(conn, f)
    return out


def account_entries(account_id: int, *, currency_view: str = "RUB", limit: int = 50,
                    cursor: str | None = None) -> dict:
    return list_entries(EntryFilters(account_id=account_id, currency_view=currency_view,
                                     limit=limit, cursor=cursor))


def check_invariants() -> list[str]:
    """[] = всё сходится. Шесть проверок из §4.1."""
    conn = _conn()
    problems: list[str] = []

    rows = conn.execute(
        "SELECT p.entry_id AS entry_id, p.currency AS currency, SUM(p.amount) AS total"
        " FROM postings p JOIN entries e ON e.id = p.entry_id"
        " GROUP BY p.entry_id, p.currency HAVING SUM(p.amount) <> 0").fetchall()
    for row in rows:
        problems.append(f"операция {row['entry_id']} не сходится по {row['currency']}: {row['total']}")

    rows = conn.execute(
        "SELECT p.currency AS currency, SUM(p.amount) AS total FROM postings p"
        " JOIN entries e ON e.id = p.entry_id WHERE e.status = 'posted' AND e.sealed = 1"
        " GROUP BY p.currency HAVING SUM(p.amount) <> 0").fetchall()
    for row in rows:
        problems.append(f"сумма всех проводок по {row['currency']} = {row['total']}, а должна быть 0")

    rows = conn.execute("SELECT id FROM entries WHERE status = 'posted' AND sealed = 0").fetchall()
    for row in rows:
        problems.append(f"операция {row['id']} не запечатана, но участвует в журнале")

    rows = conn.execute(
        "SELECT p.id AS id, a.slug AS slug, a.currency AS acc_cur, p.currency AS cur"
        " FROM postings p JOIN accounts a ON a.id = p.account_id"
        " WHERE a.currency IS NOT NULL AND a.currency <> p.currency").fetchall()
    for row in rows:
        problems.append(f"проводка {row['id']}: счёт {row['slug']} в {row['acc_cur']},"
                        f" а проводка в {row['cur']}")

    for row in conn.execute("SELECT * FROM family_tranches WHERE status != 'void'").fetchall():
        released = conn.execute(
            "SELECT COALESCE(SUM(r.aed_released), 0) AS aed, COALESCE(SUM(r.rub_released), 0) AS rub"
            " FROM tranche_releases r JOIN entries e ON e.id = r.entry_id"
            " WHERE r.tranche_id = ? AND e.status = 'posted'", (int(row["id"]),)).fetchone()
        moved = conn.execute(
            "SELECT COALESCE(SUM(p.aed_moved), 0) AS aed, COALESCE(SUM(p.rub_moved), 0) AS rub"
            " FROM freeze_move_parts p JOIN freeze_moves m ON m.id = p.move_id"
            " WHERE p.tranche_id = ? AND m.status != 'void'", (int(row["id"]),)).fetchone()
        if int(row["aed_left"]) != int(row["aed_taken"]) - int(released["aed"]) - int(moved["aed"]):
            problems.append(f"транш {row['id']}: aed_left не сходится с релизами")
        if int(row["rub_left"]) != int(row["rub_frozen"]) - int(released["rub"]) - int(moved["rub"]):
            problems.append(f"транш {row['id']}: rub_left не сходится с релизами")

    for row in move_rows(conn, status="all"):
        if row["status"] == "void":
            continue
        released = conn.execute(
            "SELECT COALESCE(SUM(r.aed_released), 0) AS aed,"
            " COALESCE(SUM(r.locked_released), 0) AS locked FROM freeze_move_releases r"
            " JOIN entries e ON e.id = r.entry_id WHERE r.move_id = ? AND e.status = 'posted'",
            (int(row["id"]),)).fetchone()
        if int(row["aed_left"]) != int(row["aed_taken"]) - int(released["aed"]) \
                or int(row["locked_left"]) != int(row["locked"]) - int(released["locked"]):
            problems.append(f"перенос заморозки {row['id']}: остаток не сходится с погашениями")

    debt = family_debt_of(conn)["debt"]["amount"]
    open_aed = sum(int(row["aed_left"]) for row in open_tranche_rows(conn)) \
        + sum(int(row["aed_left"]) for row in move_rows(conn))
    # Взятое «без заморозки» увеличивает долг, но не заморозку: его вычитаем ЧИСЛОМ, а не
    # выключаем проверку флагом — иначе одно такое взятие глушит её навсегда (грабля 29).
    unfrozen = -int(conn.execute(
        "SELECT COALESCE(SUM(p.amount), 0) AS aed FROM entries e"
        " JOIN postings p ON p.entry_id = e.id JOIN accounts a ON a.id = p.account_id"
        " WHERE e.kind = 'family_withdrawal' AND e.status = 'posted' AND e.sealed = 1"
        "   AND a.type = 'asset_family' AND p.currency = 'AED' AND NOT EXISTS"
        "   (SELECT 1 FROM family_tranches t WHERE t.entry_id = e.id AND t.status != 'void')"
    ).fetchone()["aed"])
    if debt >= 0 and open_aed != debt - unfrozen:
        problems.append(f"заморозка {open_aed} AED не равна долгу семье {debt} AED"
                        + (f" за вычетом взятого без заморозки {unfrozen} AED" if unfrozen else ""))

    rows = conn.execute(
        "SELECT e.id AS id FROM entries e WHERE e.status = 'void'"
        " AND NOT EXISTS (SELECT 1 FROM postings p WHERE p.entry_id = e.id)").fetchall()
    for row in rows:
        problems.append(f"отменённая операция {row['id']} потеряла проводки")
    return problems


# --------------------------------------------------------------------------------------
# перенос заморозки в дирхамы (28.09, Артём: потраченные замороженные рубли — «в зачёт моих
# дирхамов, заблокировать эти суммы на дирхамовском счёте»). Забалансовая запись без проводок.


def freeze_move(*, rub_amount: int | None = None, account="mashreq_personal",
                rate_e6: int | None = None, op_date: str | None = None, note: str | None = None,
                actor: str = "api") -> dict:
    """Закрывает часть рублёвой заморозки и блокирует дирхамы на счёте.

    rub_amount не задан — переносится ровно нехватка покрытия (рублей заморожено больше, чем
    есть). rate_e6 не задан — блокируется та часть долга семье, что стояла за рублями."""
    from backend.ledger.balances import free_rub as free_rub_of
    from backend.ledger.common import minor_amount
    conn = _conn()
    with db.transaction(conn):
        acc = resolve_account(conn, account, field="account")
        if acc["currency"] != "AED" or acc["type"] != "asset_personal":
            raise LedgerError("bad_request", "Блокировать можно только на личном счёте в дирхамах",
                              {"field": "account", "value": acc["slug"]})
        if rub_amount is None:
            short = free_rub_of(conn)["shortfall"]
            if not short:
                raise LedgerError("nothing_to_move", "Рублей хватает, переносить нечего", {})
            rub = int(short["amount"])
        else:
            rub = minor_amount(rub_amount, field="rub_amount") or 0
        if rub <= 0:
            raise LedgerError("bad_request", "Сумма должна быть больше нуля", {"field": "rub_amount"})
        if rate_e6 is not None and int(rate_e6) <= 0:
            raise LedgerError("bad_request", "Курс должен быть больше нуля", {"field": "rate_e6"})
        open_rub = int(conn.execute(
            "SELECT COALESCE(SUM(rub_left), 0) AS s FROM family_tranches WHERE status = 'open'"
        ).fetchone()["s"])
        if rub > open_rub:
            raise LedgerError("bad_request",
                              f"Заморожено всего {fmt_amount(open_rub, 'RUB')}, больше не перенести",
                              {"field": "rub_amount", "open_rub": money_dict(open_rub, "RUB")})
        cur = conn.execute(
            "INSERT INTO freeze_moves (op_date, rub_requested, rate_e6, account_id, currency, note,"
            " created_at) VALUES (?,?,?,?,'AED',?,?)",
            (op_date or today_dubai(), rub, int(rate_e6) if rate_e6 else None, int(acc["id"]),
             note, utc_now()))
        move_id = int(cur.lastrowid)
        rebuild_releases(conn)
        audit(conn, actor, "freeze_move", "freeze_move", move_id,
              {"rub": rub, "rate_e6": rate_e6, "account": acc["slug"]})
        row = conn.execute("SELECT * FROM freeze_moves WHERE id = ?", (move_id,)).fetchone()
        out = {"move": move_view(conn, row)}
    out["effects"] = build_effects(conn, account_ids=[int(acc["id"])])
    return out


def void_freeze_move(move_id: int, *, reason: str | None = None, actor: str = "api") -> dict:
    conn = _conn()
    with db.transaction(conn):
        row = conn.execute("SELECT * FROM freeze_moves WHERE id = ?", (move_id,)).fetchone()
        if row is None:
            raise LedgerError("not_found", "Перенос не найден", {"move_id": move_id})
        if row["status"] == "void":
            raise LedgerError("already_void", "Перенос уже отменён", {"move_id": move_id})
        conn.execute("UPDATE freeze_moves SET status = 'void', voided_at = ?, void_reason = ?"
                     " WHERE id = ?", (utc_now(), reason, move_id))
        rebuild_releases(conn)
        audit(conn, actor, "void", "freeze_move", move_id, {"reason": reason})
        row = conn.execute("SELECT * FROM freeze_moves WHERE id = ?", (move_id,)).fetchone()
        out = {"move": move_view(conn, row)}
    out["effects"] = build_effects(conn, account_ids=[int(row["account_id"])])
    return out


def freeze_moves(*, status: str = "all") -> list[dict]:
    conn = _conn()
    return [move_view(conn, row) for row in move_rows(conn, status=status)]
