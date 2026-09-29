# -*- coding: utf-8 -*-
"""Остатки, личный итог, свободные рубли, долг семье (ARCHITECTURE §4.4, §5.4, §5.6)."""
from __future__ import annotations

import sqlite3

from backend import rates, settings_store
from backend.ledger.common import (VIEW_CURRENCIES, account_row, money_dict, natural_sign,
                                   resolve_account, role_of, to_view)
from backend.money import fmt_rate
from backend.tz import human_date, iso_utc
from backend.ledger.tranches import (frozen_by_account, frozen_total, frozen_total_aed,
                                     move_rows, move_view, open_rows as open_tranche_rows,
                                     view as tranche_view)

GROUP_TITLES = {"RUB": "Рубли", "AED": "Дирхамы", "USDT": "USDT", "FAMILY": "Семейные"}
GROUP_ORDER = ("RUB", "AED", "USDT")


def balance_rows(conn: sqlite3.Connection, *, as_of: str | None = None) -> list[sqlite3.Row]:
    if as_of is None:
        return conn.execute("SELECT account_id, currency, balance FROM v_balances").fetchall()
    return conn.execute(
        "SELECT p.account_id AS account_id, p.currency AS currency, SUM(p.amount) AS balance"
        " FROM postings p JOIN entries e ON e.id = p.entry_id"
        " WHERE e.status = 'posted' AND e.sealed = 1 AND e.op_date <= ?"
        " GROUP BY p.account_id, p.currency", (as_of,)).fetchall()


def balance_map(conn: sqlite3.Connection, *, as_of: str | None = None) -> dict[tuple[int, str], int]:
    return {(int(r["account_id"]), r["currency"]): int(r["balance"])
            for r in balance_rows(conn, as_of=as_of)}


def account_balance(conn: sqlite3.Connection, account_id: int, currency: str,
                    *, as_of: str | None = None) -> int:
    return balance_map(conn, as_of=as_of).get((int(account_id), currency), 0)


def account_vector(conn: sqlite3.Connection, account_id: int,
                   *, as_of: str | None = None) -> dict[str, int]:
    out: dict[str, int] = {}
    for (acc, cur), amount in balance_map(conn, as_of=as_of).items():
        if acc == int(account_id) and amount:
            out[cur] = amount
    return out


def account_view(conn: sqlite3.Connection, account, *, currency_view: str = "RUB",
                 as_of: str | None = None, snapshot: dict | None = None,
                 bmap: dict | None = None, frozen: dict | None = None) -> dict:
    row = resolve_account(conn, account)
    snapshot = snapshot if snapshot is not None else rates.snapshot(conn=conn)
    bmap = bmap if bmap is not None else balance_map(conn, as_of=as_of)
    frozen = frozen if frozen is not None else frozen_by_account(conn)
    cur = row["currency"]
    if cur:
        balance = bmap.get((int(row["id"]), cur), 0)
    else:                                   # мультивалютный счёт: в валюту показа сводится вектор
        balance = sum(to_view(amount, c, currency_view, snapshot)
                      for (acc, c), amount in bmap.items() if acc == int(row["id"]))
        cur = currency_view
    sign = natural_sign(row["type"])
    frozen_amount = frozen.get(int(row["id"]))
    out = {
        "id": int(row["id"]), "slug": row["slug"], "name": row["name"], "type": row["type"],
        "role": role_of(row["type"]), "currency": cur, "icon": row["icon"],
        "balance": money_dict(balance, cur),
        "natural": money_dict(balance * sign, cur),
        "in_view": money_dict(to_view(balance, cur, currency_view, snapshot), currency_view),
        "frozen": money_dict(frozen_amount, cur) if frozen_amount else None,
        "archived": bool(row["archived"]),
    }
    return out


def balances_by_currency(conn: sqlite3.Connection, row: sqlite3.Row,
                         bmap: dict | None = None) -> list[dict] | None:
    """Остаток мультивалютного счёта вектором по валютам, натуральный знак (§5.5, журнал 21).

    Одновалютному счёту вектор не нужен — его остаток целиком в `balance`, поэтому None."""
    if row["currency"]:
        return None
    bmap = bmap if bmap is not None else balance_map(conn)
    sign = natural_sign(row["type"])
    out = []
    for (acc, cur), amount in sorted(bmap.items(), key=lambda kv: kv[0][1]):
        if acc == int(row["id"]) and amount:
            out.append(money_dict(amount * sign, cur))
    return out


def net_worth(conn: sqlite3.Connection, *, currency_view: str = "RUB",
              as_of: str | None = None, snapshot: dict | None = None,
              bmap: dict | None = None) -> int:
    """Личный итог = Σ активы + Σ обязательства со знаками (§4.4)."""
    snapshot = snapshot if snapshot is not None else rates.snapshot(conn=conn)
    bmap = bmap if bmap is not None else balance_map(conn, as_of=as_of)
    types = {int(r["id"]): r["type"] for r in conn.execute("SELECT id, type FROM accounts").fetchall()}
    # Складываем сначала внутри валюты и только потом пересчитываем: иначе «взял 500 AED из
    # семейного» сдвигает итог на копейку округления, а по ТЗ 11.2 он обязан остаться прежним.
    by_currency: dict[str, int] = {}
    for (acc, cur), amount in bmap.items():
        if types.get(acc) in ("asset_personal", "asset_family", "liability"):
            by_currency[cur] = by_currency.get(cur, 0) + amount
    return sum(to_view(amount, cur, currency_view, snapshot)
               for cur, amount in by_currency.items())


def rub_personal_total(conn: sqlite3.Connection, *, as_of: str | None = None,
                       bmap: dict | None = None) -> int:
    bmap = bmap if bmap is not None else balance_map(conn, as_of=as_of)
    rows = conn.execute(
        "SELECT id FROM accounts WHERE type = 'asset_personal' AND is_money = 1"
        " AND currency = 'RUB'").fetchall()
    ids = {int(r["id"]) for r in rows}
    return sum(amount for (acc, cur), amount in bmap.items() if acc in ids and cur == "RUB")


def credit_debt_rub(conn: sqlite3.Connection, *, as_of: str | None = None,
                    bmap: dict | None = None) -> int:
    """Долг по рублёвым кредиткам (положительное число, если должен банку)."""
    bmap = bmap if bmap is not None else balance_map(conn, as_of=as_of)
    ids = {int(r["id"]) for r in conn.execute(
        "SELECT id FROM accounts WHERE type = 'liability' AND is_money = 1"
        " AND currency = 'RUB'").fetchall()}
    return -sum(amount for (acc, cur), amount in bmap.items() if acc in ids and cur == "RUB")


def free_rub(conn: sqlite3.Connection, *, as_of: str | None = None,
             bmap: dict | None = None) -> dict:
    """Свободные рубли = рубли на личных счетах − заморозка под семью − долг по кредитке.

    29.09 Артём: «12 000 свободных, а по кредитке долг 13 518 — свободных ноль». Может уйти в минус.
    Нехватка (shortfall) по-прежнему сравнивает только рубли с заморозкой: кредитка не повод
    переносить заморозку в дирхамы."""
    bmap = bmap if bmap is not None else balance_map(conn, as_of=as_of)
    total = rub_personal_total(conn, as_of=as_of, bmap=bmap)
    frozen = frozen_total(conn)
    credit = max(0, credit_debt_rub(conn, bmap=bmap))
    free = total - frozen - credit
    return {"rub_total": money_dict(total, "RUB"), "frozen": money_dict(frozen, "RUB"),
            "credit": money_dict(credit, "RUB"),
            "free": money_dict(free, "RUB"),
            "shortfall": money_dict(frozen - total, "RUB") if frozen > total else None}


def aed_personal_total(conn: sqlite3.Connection, *, as_of: str | None = None,
                       bmap: dict | None = None) -> int:
    bmap = bmap if bmap is not None else balance_map(conn, as_of=as_of)
    ids = {int(r["id"]) for r in conn.execute(
        "SELECT id FROM accounts WHERE type = 'asset_personal' AND is_money = 1"
        " AND currency = 'AED'").fetchall()}
    return sum(amount for (acc, cur), amount in bmap.items() if acc in ids and cur == "AED")


def free_aed(conn: sqlite3.Connection, *, as_of: str | None = None,
             bmap: dict | None = None) -> dict:
    """Свободные дирхамы = личные AED-счета − блок от переносов заморозки (28.09)."""
    total = aed_personal_total(conn, as_of=as_of, bmap=bmap)
    frozen = frozen_total_aed(conn)
    return {"aed_total": money_dict(total, "AED"), "frozen": money_dict(frozen, "AED"),
            "free": money_dict(total - frozen, "AED"),
            "shortfall": money_dict(frozen - total, "AED") if frozen > total else None}


def family_debt(conn: sqlite3.Connection, *, as_of: str | None = None,
                snapshot: dict | None = None, bmap: dict | None = None) -> dict:
    """Долг семье = Семейный фонд − Σ семейных активов, в AED. Может быть отрицательным."""
    snapshot = snapshot if snapshot is not None else rates.snapshot(conn=conn)
    bmap = bmap if bmap is not None else balance_map(conn, as_of=as_of)
    fund = account_row(conn, "family_fund")
    fund_natural = 0
    if fund is not None:
        fund_natural = -sum(amount for (acc, cur), amount in bmap.items()
                            if acc == int(fund["id"]))
    family_ids = {int(r["id"]) for r in conn.execute(
        "SELECT id FROM accounts WHERE type = 'asset_family'").fetchall()}
    assets = sum(amount for (acc, cur), amount in bmap.items() if acc in family_ids)
    debt = fund_natural - assets
    frozen = frozen_total(conn)
    open_tranches = open_tranche_rows(conn)
    moves = move_rows(conn)
    today_repay = None
    if debt > 0:
        today_repay = money_dict(to_view(debt, "AED", "RUB", snapshot), "RUB")
    return {
        "debt": money_dict(debt, "AED"),
        "direction": "i_owe" if debt >= 0 else "family_owes",
        "fund": money_dict(fund_natural, "AED"),
        "family_assets": money_dict(assets, "AED"),
        "frozen_rub": money_dict(frozen if debt > 0 else frozen, "RUB"),
        "frozen_aed": money_dict(frozen_total_aed(conn), "AED"),
        "today_repay_rub": today_repay,
        "tranches": [tranche_view(conn, row) for row in open_tranches]
        + [move_view(conn, row) for row in moves],
    }


def frozen_note(conn: sqlite3.Connection) -> str | None:
    rows = open_tranche_rows(conn)
    if not rows:
        return None
    if len(rows) == 1:
        row = rows[0]
        return f"по {fmt_rate(int(row['rate_e6']))} от {human_date(row['op_date'])}"
    word = "транша" if 2 <= len(rows) <= 4 else "траншей"
    return f"{len(rows)} {word}, самый ранний от {human_date(rows[0]['op_date'])}"


def _group_of(row: sqlite3.Row) -> str:
    return row["group_key"] or (row["currency"] or "RUB")


def balances(conn: sqlite3.Connection, *, as_of: str | None = None,
             currency_view: str = "RUB") -> dict:
    snapshot = rates.snapshot(conn=conn)
    bmap = balance_map(conn, as_of=as_of)
    frozen = frozen_by_account(conn)

    money_rows = conn.execute(
        "SELECT * FROM accounts WHERE is_money = 1 AND type IN ('asset_personal','liability')"
        " AND archived = 0 ORDER BY sort, id").fetchall()
    family_rows = conn.execute(
        "SELECT * FROM accounts WHERE type = 'asset_family' AND archived = 0 ORDER BY sort, id"
    ).fetchall()

    hidden_slugs = set(settings_store.get("hidden_accounts", [], conn=conn) or [])
    views: dict[int, dict] = {}
    groups: dict[str, list[dict]] = {}
    hidden_views: list[dict] = []
    for row in money_rows:
        view = account_view(conn, row, currency_view=currency_view, as_of=as_of,
                            snapshot=snapshot, bmap=bmap, frozen=frozen)
        views[int(row["id"])] = view
        if row["slug"] in hidden_slugs:
            hidden_views.append(view)       # копилка и т.п.: не в группах и не в «Моих деньгах»
            continue
        groups.setdefault(_group_of(row), []).append(view)

    ordered = [key for key in GROUP_ORDER if key in groups] + \
              [key for key in groups if key not in GROUP_ORDER]
    group_list = []
    for key in ordered:
        accounts = groups[key]
        total = sum(a["in_view"]["amount"] for a in accounts)
        group_list.append({"key": key, "title": GROUP_TITLES.get(key, key),
                           "total": money_dict(total, currency_view), "accounts": accounts})

    family_views = [account_view(conn, row, currency_view=currency_view, as_of=as_of,
                                 snapshot=snapshot, bmap=bmap, frozen=frozen)
                    for row in family_rows]
    debt = family_debt(conn, as_of=as_of, snapshot=snapshot, bmap=bmap)
    free = free_rub(conn, as_of=as_of, bmap=bmap)
    free_d = free_aed(conn, as_of=as_of, bmap=bmap)
    total_nw = net_worth(conn, currency_view=currency_view, as_of=as_of,
                         snapshot=snapshot, bmap=bmap)

    family_block = {
        "visible": True,
        "total": money_dict(sum(v["in_view"]["amount"] for v in family_views), currency_view),
        "accounts": family_views,
        "debt": debt["debt"],
        "direction": debt["direction"],
        "frozen_rub": debt["frozen_rub"] if debt["debt"]["amount"] > 0
        else money_dict(frozen_total(conn), "RUB"),
        "frozen_aed": free_d["frozen"],
        "frozen_note": frozen_note(conn),
        "today_repay_rub": debt["today_repay_rub"],
    }
    if debt["debt"]["amount"] < 0:
        family_block["frozen_rub"] = money_dict(0, "RUB")
        family_block["frozen_aed"] = money_dict(0, "AED")
        family_block["frozen_note"] = None
        family_block["today_repay_rub"] = None

    nw_by_view, groups_by_view = totals_by_view(conn, group_list, total_nw, currency_view, snapshot)

    # «Мои деньги» (25.09, Артём): видимые личные счета и кредитки минус рубли, замороженные под взятые
    # из семейного дирхамы. Семейный фонд и «долг» сюда не входят: пока рубли покрывают, это взаимозачёт.
    visible_rub = sum(to_view(a["in_view"]["amount"], currency_view, "RUB", snapshot)
                      for g in group_list for a in g["accounts"])
    my_rub = visible_rub - free["frozen"]["amount"] \
        - to_view(free_d["frozen"]["amount"], "AED", "RUB", snapshot)
    my_by_view = {v: money_dict(to_view(my_rub, "RUB", v, snapshot), v) for v in VIEW_CURRENCIES}
    hidden_total_rub = sum(to_view(a["in_view"]["amount"], currency_view, "RUB", snapshot)
                           for a in hidden_views)

    return {
        "currency": currency_view,
        "as_of": iso_utc(),
        "net_worth": money_dict(total_nw, currency_view),
        "free_rub": free["free"],
        "frozen_rub": free["frozen"],
        "groups": group_list,
        "totals_by_view": {"net_worth": nw_by_view, "groups": groups_by_view, "my_money": my_by_view},
        "my_money": my_by_view.get(currency_view, money_dict(my_rub, "RUB")),
        "shortfall_rub": free["shortfall"],
        "free_aed": free_d["free"],
        "frozen_aed": free_d["frozen"],
        "shortfall_aed": free_d["shortfall"],
        "hidden": {"accounts": hidden_views,
                   "total": {v: money_dict(to_view(hidden_total_rub, "RUB", v, snapshot), v)
                             for v in VIEW_CURRENCIES}},
        "family": family_block,
        "accounts": list(views.values()) + family_views,
        "rates": {"at": snapshot.get("at"), "source": snapshot.get("source"),
                  "rub_per_aed_e6": snapshot.get("rub_per_aed_e6"),
                  "rub_per_usd_e6": snapshot.get("rub_per_usd_e6"),
                  "rub_per_usdt_e6": snapshot.get("rub_per_usdt_e6")},
    }


def totals_by_view(conn: sqlite3.Connection, group_list: list[dict], total_nw: int,
                   currency_view: str, snapshot: dict) -> tuple[dict, dict]:
    """Итог и итоги групп во всех трёх валютах — считаются от рублёвой величины (§5.4)."""
    nw_rub = to_view(total_nw, currency_view, "RUB", snapshot)
    nw = {cur: money_dict(total_nw if cur == currency_view else to_view(nw_rub, "RUB", cur, snapshot),
                          cur) for cur in VIEW_CURRENCIES}
    groups: dict[str, dict] = {}
    for group in group_list:
        rub = to_view(group["total"]["amount"], currency_view, "RUB", snapshot)
        groups[group["key"]] = {
            cur: money_dict(group["total"]["amount"] if cur == currency_view
                            else to_view(rub, "RUB", cur, snapshot), cur)
            for cur in VIEW_CURRENCIES}
    return nw, groups


def _people_debts(conn: sqlite3.Connection, slug: str, currency_view: str,
                  snapshot: dict) -> list[dict]:
    """Долги по людям: суммы вектором по валютам + пересчёт в валюту показа."""
    account = account_row(conn, slug)
    if account is None:
        return []
    rows = conn.execute(
        "SELECT p.counterparty_id AS cp, p.currency AS currency, SUM(p.amount) AS total,"
        " MIN(e.op_date) AS since, GROUP_CONCAT(e.id) AS entry_ids"
        " FROM postings p JOIN entries e ON e.id = p.entry_id"
        " WHERE p.account_id = ? AND e.status = 'posted' AND e.sealed = 1"
        " GROUP BY p.counterparty_id, p.currency", (int(account["id"]),)).fetchall()
    people: dict[int, dict] = {}
    sign = natural_sign(account["type"])
    for row in rows:
        total = int(row["total"]) * sign
        if total == 0:
            continue
        cp_id = int(row["cp"]) if row["cp"] is not None else 0
        name_row = conn.execute("SELECT name FROM counterparties WHERE id = ?", (cp_id,)).fetchone()
        item = people.setdefault(cp_id, {
            "counterparty_id": cp_id, "name": name_row["name"] if name_row else "Без имени",
            "amounts": [], "in_view": money_dict(0, currency_view), "due_date": None,
            "since": row["since"], "entry_ids": []})
        item["amounts"].append(money_dict(total, row["currency"]))
        item["in_view"]["amount"] += to_view(total, row["currency"], currency_view, snapshot)
        item["entry_ids"].extend(int(x) for x in (row["entry_ids"] or "").split(",") if x)
        if row["since"] and (item["since"] is None or row["since"] < item["since"]):
            item["since"] = row["since"]
    for cp_id, item in people.items():
        due = conn.execute(
            "SELECT MIN(due_date) AS due FROM entries WHERE counterparty_id = ? AND status = 'posted'"
            " AND due_date IS NOT NULL", (cp_id,)).fetchone()
        item["due_date"] = due["due"] if due else None
        item["entry_ids"] = sorted(set(item["entry_ids"]))
    return list(people.values())


def debts(conn: sqlite3.Connection, *, currency_view: str = "RUB") -> dict:
    """Экран «Долги» (§5.8). total_in_view — сумма экрана, а не слагаемое личного итога."""
    snapshot = rates.snapshot(conn=conn)
    bmap = balance_map(conn)
    owed = _people_debts(conn, "receivable", currency_view, snapshot)
    i_owe = _people_debts(conn, "payable", currency_view, snapshot)

    def liability_block(slug: str, note: str | None = None) -> dict | None:
        account = account_row(conn, slug)
        if account is None:
            return None
        amount = -sum(value for (acc, cur), value in bmap.items() if acc == int(account["id"]))
        due = conn.execute(
            "SELECT MIN(due_date) AS due FROM entries WHERE due_date IS NOT NULL"
            " AND status = 'posted' AND kind = 'tax_payment'").fetchone() if slug == "tax_npd" else None
        block = {"account_id": int(account["id"]), "name": account["name"],
                 "amount": money_dict(amount, account["currency"] or currency_view),
                 "due_date": due["due"] if due else None}
        if note:
            block["note"] = note
        return block

    tax = liability_block("tax_npd", "начислено по доходам проектов")
    credit = liability_block("sber_credit")
    family = family_debt(conn, snapshot=snapshot, bmap=bmap)

    total = sum(item["in_view"]["amount"] for item in owed)
    total -= sum(item["in_view"]["amount"] for item in i_owe)
    if tax:
        total -= to_view(tax["amount"]["amount"], tax["amount"]["currency"], currency_view, snapshot)
    if credit:
        total -= to_view(credit["amount"]["amount"], credit["amount"]["currency"], currency_view,
                         snapshot)
    total -= to_view(family["debt"]["amount"], "AED", currency_view, snapshot)

    family_block = {"debt": family["debt"], "direction": family["direction"],
                    "frozen_rub": family["frozen_rub"],
                    "frozen_aed": family["frozen_aed"],
                    "today_repay_rub": family["today_repay_rub"],
                    "tranches": family["tranches"]}
    if family["debt"]["amount"] < 0:
        family_block["frozen_rub"] = money_dict(0, "RUB")
        family_block["frozen_aed"] = money_dict(0, "AED")
        family_block["today_repay_rub"] = None
        family_block["tranches"] = []
    receivable = account_row(conn, "receivable")
    payable = account_row(conn, "payable")
    return {"owed_to_me": owed, "i_owe": i_owe, "tax": tax, "credit_card": credit,
            "family": family_block, "total_in_view": money_dict(total, currency_view),
            "owed_to_me_by_currency":
                balances_by_currency(conn, receivable, bmap) if receivable is not None else [],
            "i_owe_by_currency":
                balances_by_currency(conn, payable, bmap) if payable is not None else []}


def effects(conn: sqlite3.Connection, *, account_ids: list[int], currency_view: str = "RUB",
            tranche: dict | None = None, released: list[dict] | None = None,
            unlocked: list[dict] | None = None) -> dict:
    """Единый объект effects для ядра, API и карточек бота (§5.5)."""
    snapshot = rates.snapshot(conn=conn)
    bmap = balance_map(conn)
    frozen = frozen_by_account(conn)
    accounts = []
    seen = set()
    for account_id in account_ids:
        if account_id in seen:
            continue
        seen.add(account_id)
        row = account_row(conn, account_id)
        if row is None:
            continue
        view = account_view(conn, row, currency_view=currency_view, snapshot=snapshot,
                            bmap=bmap, frozen=frozen)
        by_currency = balances_by_currency(conn, row, bmap)
        by_counterparty = None
        if by_currency is not None and row["needs_counterparty"]:
            # долговые счета мультивалютные: карточке бота нужен итог именно по этому человеку
            by_counterparty = [{"counterparty_id": p["counterparty_id"], "name": p["name"],
                                "amounts": p["amounts"], "in_view": p["in_view"]}
                               for p in _people_debts(conn, row["slug"], currency_view, snapshot)]
        accounts.append({"id": view["id"], "slug": view["slug"], "name": view["name"],
                         "role": view["role"], "balance": view["balance"],
                         "natural": view["natural"], "in_view": view["in_view"],
                         "frozen": view["frozen"],
                         "balances_by_currency": by_currency,
                         "by_counterparty": by_counterparty})
    debt = family_debt(conn, snapshot=snapshot, bmap=bmap)
    free = free_rub(conn, bmap=bmap)
    free_d = free_aed(conn, bmap=bmap)
    return {
        "accounts": accounts,
        "net_worth": money_dict(net_worth(conn, currency_view=currency_view, snapshot=snapshot,
                                          bmap=bmap), currency_view),
        "free_rub": free["free"],
        "frozen_rub": free["frozen"],
        "free_aed": free_d["free"],
        "frozen_aed": free_d["frozen"],
        "family_debt": debt["debt"],
        "family_direction": debt["direction"],
        "tranche": tranche,
        "released": released or [],
        "unlocked": unlocked or [],
    }
