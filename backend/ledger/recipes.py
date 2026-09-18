# -*- coding: utf-8 -*-
"""Рецепты проводок — по одному на каждый kind (ARCHITECTURE §4.2).

Здесь же живут умолчания ядра: категория, счёт и дата не переспрашиваются, а подставляются."""
from __future__ import annotations

import sqlite3

from backend import money, settings_store
from backend.contracts import LedgerError, ParsedOperation
from backend.ledger.common import (account_row, ensure_counterparty, freeze_account_slug,
                                   minor_amount, resolve_account, warn)
from backend.tz import today_dubai

MONEY_KINDS = {"expense", "income", "transfer", "exchange", "tax_payment"}
OPENING_FORBIDDEN = ("family_fund", "eq_opening", "eq_exchange", "eq_correction")


def last_account_slug(conn: sqlite3.Connection, currency: str) -> str | None:
    """Последний использованный денежный счёт этой валюты, иначе — с наименьшим sort."""
    row = conn.execute(
        "SELECT a.slug FROM postings p"
        " JOIN accounts a ON a.id = p.account_id"
        " JOIN entries e ON e.id = p.entry_id"
        " WHERE a.is_money = 1 AND a.type = 'asset_personal' AND a.currency = ?"
        "   AND e.status = 'posted' AND e.sealed = 1"
        " ORDER BY e.id DESC, p.id DESC LIMIT 1", (currency,)).fetchone()
    if row:
        return row["slug"]
    row = conn.execute(
        "SELECT slug FROM accounts WHERE is_money = 1 AND type = 'asset_personal'"
        " AND currency = ? AND archived = 0 ORDER BY sort, id LIMIT 1", (currency,)).fetchone()
    return row["slug"] if row else None


def _need(op: ParsedOperation, field: str, value):
    if value in (None, ""):
        raise LedgerError("bad_request", f"Не хватает поля: {field}",
                          {"field": field, "kind": op.kind})
    return value


def _acc(conn: sqlite3.Connection, ref, field: str) -> sqlite3.Row:
    return resolve_account(conn, ref, field=field)


def _posting(account: sqlite3.Row, amount: int, currency: str, *,
             counterparty_id: int | None = None, project: str | None = None,
             memo: str | None = None) -> dict:
    return {"account_id": int(account["id"]), "amount": int(amount), "currency": currency,
            "counterparty_id": counterparty_id, "project": project, "memo": memo}


def _money_account(conn: sqlite3.Connection, ref, field: str, op: ParsedOperation) -> sqlite3.Row:
    row = _acc(conn, _need(op, field, ref), field)
    if not row["is_money"] and row["type"] not in ("asset_personal", "asset_family", "liability"):
        raise LedgerError("bad_request", f"Счёт {row['slug']} не денежный", {"field": field})
    return row


def defaults(conn: sqlite3.Connection, op: ParsedOperation) -> ParsedOperation:
    """Подставляет умолчания вместо null от LLM (§4.2)."""
    if not op.op_date:
        op.op_date = today_dubai()
    if not op.currency:
        for ref in (op.from_account, op.to_account):
            row = account_row(conn, ref)
            if row is not None and row["currency"]:
                op.currency = row["currency"]
                break
    if op.kind in ("family_withdrawal", "family_repayment", "family_topup_by_parents",
                   "own_contribution_to_family", "family_spent_own", "paid_for_family_from_own"):
        op.currency = op.currency or "AED"
    if op.kind == "tax_payment":
        op.currency = op.currency or "RUB"
    if not op.currency:
        raise LedgerError("bad_request", "Не ясна валюта операции", {"field": "currency"})

    if op.kind == "expense" and not op.category:
        op.category = "exp_other"
    if op.kind == "income" and not op.income_source:
        op.income_source = "inc_other"
    if op.kind in ("expense", "transfer", "exchange", "loan_given", "loan_repaid_by_me",
                   "tax_payment", "paid_for_family_from_own") and not op.from_account:
        op.from_account = last_account_slug(conn, op.currency)
    if op.kind in ("income", "transfer", "loan_repaid_to_me", "loan_taken") and not op.to_account:
        op.to_account = last_account_slug(conn, op.currency)
    if op.kind == "family_withdrawal":
        op.from_account = op.from_account or "mashreq_family"
        op.to_account = op.to_account or "mashreq_personal"
    if op.kind == "family_repayment":
        op.to_account = op.to_account or "mashreq_family"
        op.from_account = op.from_account or last_account_slug(conn, op.currency) or "mashreq_personal"
    if op.kind == "family_topup_by_parents":
        op.to_account = op.to_account or "mashreq_family"
    if op.kind == "family_spent_own":
        op.from_account = op.from_account or "mashreq_family"
    if op.kind == "own_contribution_to_family":
        op.to_account = op.to_account or "mashreq_family"
        op.from_account = op.from_account or last_account_slug(conn, op.currency) or "mashreq_personal"
    if op.kind == "paid_for_family_from_own":
        op.from_account = op.from_account or last_account_slug(conn, "AED") or "mashreq_personal"
    if op.kind == "family_withdrawal" and not op.freeze_account:
        op.freeze_account = freeze_account_slug(conn)
    return op


def build(conn: sqlite3.Connection, op: ParsedOperation) -> dict:
    """Возвращает {'postings': [...], 'warnings': [...], 'meta': {...}} по рецепту вида операции."""
    op = defaults(conn, op)
    amount = minor_amount(op.amount, field="amount") or 0
    op.amount = amount
    cur = op.currency
    warnings: list[dict] = []
    meta: dict = {}

    if op.kind != "balance_correction" and amount <= 0:
        raise LedgerError("bad_request", "Сумма должна быть больше нуля", {"field": "amount"})
    if op.kind == "balance_correction" and amount == 0:
        raise LedgerError("bad_request", "Нулевое выравнивание не записывается", {"field": "amount"})

    cp_id = ensure_counterparty(conn, op.counterparty)
    postings: list[dict] = []

    if op.kind == "expense":
        src = _money_account(conn, op.from_account, "from_account", op)
        cat = _acc(conn, _need(op, "category", op.category), "category")
        if cat["type"] != "expense":
            raise LedgerError("bad_request", "Категория должна быть расходным счётом",
                              {"field": "category", "value": cat["slug"]})
        postings = [_posting(cat, +amount, cur, project=op.project, memo=op.description),
                    _posting(src, -amount, cur)]

    elif op.kind == "income":
        dst = _money_account(conn, op.to_account, "to_account", op)
        source = _acc(conn, _need(op, "income_source", op.income_source), "income_source")
        if source["type"] != "income":
            raise LedgerError("bad_request", "Источник дохода должен быть доходным счётом",
                              {"field": "income_source", "value": source["slug"]})
        postings = [_posting(dst, +amount, cur),
                    _posting(source, -amount, cur, counterparty_id=cp_id, project=op.project)]
        row = conn.execute("SELECT * FROM income_sources WHERE account_id = ?",
                           (int(source["id"]),)).fetchone()
        rate_bp = int(row["tax_rate_bp"]) if row else 0
        tax_acc_id = row["tax_account_id"] if row else None
        if rate_bp > 0 and not op.no_tax and tax_acc_id:
            tax_acc = _acc(conn, int(tax_acc_id), "tax_account")
            if tax_acc["currency"] and tax_acc["currency"] != cur:
                warnings.append(warn(
                    "tax_currency_mismatch",
                    f"Доход в {cur}: налог не начислен, налоговый счёт ведётся в {tax_acc['currency']}",
                    {"income_currency": cur, "tax_currency": tax_acc["currency"]}))
            else:
                tax = money.round_half_up(amount * rate_bp, 10_000)
                if tax > 0:
                    exp_tax = _acc(conn, "exp_taxes", "tax_category")
                    postings.append(_posting(exp_tax, +tax, cur, memo="Налог НПД"))
                    postings.append(_posting(tax_acc, -tax, cur, memo="Начислен налог НПД"))
                    meta["tax"] = {"amount": tax, "currency": cur, "rate_bp": rate_bp}

    elif op.kind == "transfer":
        src = _money_account(conn, op.from_account, "from_account", op)
        dst = _money_account(conn, op.to_account, "to_account", op)
        for row in (src, dst):
            if row["currency"] and row["currency"] != cur:
                raise LedgerError("currency_mismatch",
                                  "Перевод между счетами разных валют — это обмен",
                                  {"account": row["slug"], "expected": row["currency"], "got": cur})
        postings = [_posting(dst, +amount, cur), _posting(src, -amount, cur, memo=op.description)]

    elif op.kind == "exchange":
        src = _money_account(conn, op.from_account, "from_account", op)
        dst = _money_account(conn, op.to_account, "to_account", op)
        amount_to = minor_amount(_need(op, "amount_to", op.amount_to), field="amount_to")
        if amount_to <= 0:
            # Без этой проверки «обменял 10 000 ₽ и получил 0» падает CHECK-ом БД (HTTP 500),
            # а «получил −5 000 ₽» ЗАПИСЫВАЕТСЯ и сжигает обе стороны обмена (грабля 27).
            raise LedgerError("bad_request", "Полученная сумма должна быть больше нуля",
                              {"field": "amount_to"})
        op.amount_to = amount_to
        cur_to = _need(op, "currency_to", op.currency_to)
        swap = _acc(conn, "eq_exchange", "exchange")
        postings = [_posting(dst, +amount_to, cur_to),
                    _posting(swap, -amount_to, cur_to),
                    _posting(swap, +amount, cur),
                    _posting(src, -amount, cur, memo=op.description)]
        if amount and amount_to:
            # Курс показываем «сколько рублей за единицу», как в карточке бота (§7.2).
            if cur == "RUB":
                meta["rate_pair"] = f"{cur_to}/RUB"
                meta["rate_e6"] = money.round_half_up(amount * 1_000_000, amount_to)
            elif cur_to == "RUB":
                meta["rate_pair"] = f"{cur}/RUB"
                meta["rate_e6"] = money.round_half_up(amount_to * 1_000_000, amount)
            else:
                meta["rate_pair"] = f"{cur}/{cur_to}"
                meta["rate_e6"] = money.round_half_up(amount_to * 1_000_000, amount)

    elif op.kind == "family_withdrawal":
        src = _acc(conn, _need(op, "from_account", op.from_account), "from_account")
        if src["type"] != "asset_family":
            raise LedgerError("bad_request", "Брать можно только с семейного счёта",
                              {"field": "from_account", "value": src["slug"]})
        dst = _acc(conn, _need(op, "to_account", op.to_account), "to_account")
        if dst["type"] not in ("asset_personal", "expense"):
            raise LedgerError("bad_request", "Взятое ложится на личный счёт или сразу в расход",
                              {"field": "to_account", "value": dst["slug"]})
        postings = [_posting(dst, +amount, cur, memo=op.description),
                    _posting(src, -amount, cur)]
        meta["freeze"] = bool(op.freeze) and cur == "AED"
        meta["freeze_account"] = op.freeze_account

    elif op.kind == "family_repayment":
        dst = _acc(conn, _need(op, "to_account", op.to_account), "to_account")
        if dst["type"] != "asset_family":
            raise LedgerError("bad_request", "Вернуть можно только на семейный счёт",
                              {"field": "to_account", "value": dst["slug"]})
        src = _money_account(conn, op.from_account, "from_account", op)
        postings = [_posting(dst, +amount, cur), _posting(src, -amount, cur, memo=op.description)]
        meta["release"] = amount

    elif op.kind == "family_topup_by_parents":
        dst = _acc(conn, _need(op, "to_account", op.to_account), "to_account")
        fund = _acc(conn, "family_fund", "family_fund")
        postings = [_posting(dst, +amount, cur), _posting(fund, -amount, cur, memo=op.description)]

    elif op.kind == "own_contribution_to_family":
        dst = _acc(conn, _need(op, "to_account", op.to_account), "to_account")
        src = _money_account(conn, op.from_account, "from_account", op)
        fund = _acc(conn, "family_fund", "family_fund")
        contrib = _acc(conn, "exp_family_contrib", "category")
        postings = [_posting(dst, +amount, cur), _posting(src, -amount, cur),
                    _posting(contrib, +amount, cur, memo=op.description),
                    _posting(fund, -amount, cur)]

    elif op.kind == "family_spent_own":
        src = _acc(conn, _need(op, "from_account", op.from_account), "from_account")
        if src["type"] != "asset_family":
            raise LedgerError("bad_request", "Семья тратит с семейного счёта",
                              {"field": "from_account", "value": src["slug"]})
        fund = _acc(conn, "family_fund", "family_fund")
        postings = [_posting(fund, +amount, cur, memo=op.description),
                    _posting(src, -amount, cur)]

    elif op.kind == "paid_for_family_from_own":
        src = _money_account(conn, op.from_account, "from_account", op)
        if src["type"] != "asset_personal":
            raise LedgerError("bad_request", "Платить за семью можно со своего счёта",
                              {"field": "from_account", "value": src["slug"]})
        fund = _acc(conn, "family_fund", "family_fund")
        postings = [_posting(fund, +amount, cur, memo=op.description),
                    _posting(src, -amount, cur)]
        meta["release"] = amount

    elif op.kind in ("loan_given", "loan_repaid_to_me", "loan_taken", "loan_repaid_by_me"):
        if not cp_id:
            raise LedgerError("counterparty_required", "Долг без контрагента не записывается",
                              {"field": "counterparty"})
        receivable = _acc(conn, "receivable", "receivable")
        payable = _acc(conn, "payable", "payable")
        if op.kind == "loan_given":
            src = _money_account(conn, op.from_account, "from_account", op)
            postings = [_posting(receivable, +amount, cur, counterparty_id=cp_id, memo=op.description),
                        _posting(src, -amount, cur)]
        elif op.kind == "loan_repaid_to_me":
            dst = _money_account(conn, op.to_account, "to_account", op)
            postings = [_posting(dst, +amount, cur),
                        _posting(receivable, -amount, cur, counterparty_id=cp_id, memo=op.description)]
        elif op.kind == "loan_taken":
            dst = _money_account(conn, op.to_account, "to_account", op)
            postings = [_posting(dst, +amount, cur),
                        _posting(payable, -amount, cur, counterparty_id=cp_id, memo=op.description)]
        else:
            src = _money_account(conn, op.from_account, "from_account", op)
            postings = [_posting(payable, +amount, cur, counterparty_id=cp_id, memo=op.description),
                        _posting(src, -amount, cur)]

    elif op.kind == "tax_payment":
        src = _money_account(conn, op.from_account, "from_account", op)
        tax_acc = _acc(conn, "tax_npd", "tax_npd")
        postings = [_posting(tax_acc, +amount, cur, memo=op.description),
                    _posting(src, -amount, cur)]

    elif op.kind == "opening_balance":
        target = _acc(conn, _need(op, "to_account", op.to_account or op.from_account), "to_account")
        if target["slug"] in OPENING_FORBIDDEN or target["type"] in ("income", "expense"):
            raise LedgerError("opening_balance_not_allowed",
                              "Начальный остаток на этом счёте не вводится",
                              {"account": target["slug"]})
        opening = _acc(conn, "eq_opening", "eq_opening")
        if target["type"] == "asset_family":
            fund = _acc(conn, "family_fund", "family_fund")
            postings = [_posting(target, +amount, cur), _posting(fund, -amount, cur)]
        elif target["type"] == "liability":
            postings = [_posting(target, -amount, cur, counterparty_id=cp_id),
                        _posting(opening, +amount, cur)]
        else:
            postings = [_posting(target, +amount, cur, counterparty_id=cp_id),
                        _posting(opening, -amount, cur)]

    elif op.kind == "balance_correction":
        target = _acc(conn, _need(op, "to_account", op.to_account or op.from_account), "to_account")
        corr_slug = "family_fund" if target["type"] == "asset_family" else "eq_correction"
        corr = _acc(conn, corr_slug, "correction")
        delta = amount
        if delta > 0:
            postings = [_posting(target, +delta, cur, memo=op.description),
                        _posting(corr, -delta, cur)]
        else:
            postings = [_posting(target, delta, cur, memo=op.description),
                        _posting(corr, -delta, cur)]
    else:
        raise LedgerError("bad_request", f"Неизвестный вид операции: {op.kind}", {"kind": op.kind})

    return {"postings": postings, "warnings": warnings, "meta": meta,
            "counterparty_id": cp_id, "op": op}


def default_tax_rate_bp(conn: sqlite3.Connection) -> int:
    try:
        return int(settings_store.get("tax_rate_default_bp", 600, conn=conn))
    except (TypeError, ValueError):
        return 600
