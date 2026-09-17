# -*- coding: utf-8 -*-
"""Аналитика месяца, сводка ленты, агрегаты для выгрузки (ARCHITECTURE §5.7, §5.5, §9).

Потоки за период считаются по снимку курсов операции, а не по сегодняшнему курсу (§4.4)."""
from __future__ import annotations

import sqlite3

from backend.contracts import EntryFilters
from backend.ledger.common import money_dict, snapshot_of, to_view
from backend.money import share_bp, spread_shares
from backend.tz import days_between, month_bounds, shift_month, today_dubai


def _rows(conn: sqlite3.Connection, where: str, args: list) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT p.account_id AS account_id, p.amount AS amount, p.currency AS currency,"
        " p.project AS project, e.id AS entry_id, e.rates_snapshot AS snap, e.kind AS kind,"
        " e.op_date AS op_date, a.type AS type, a.name AS name, a.slug AS slug, a.icon AS icon"
        " FROM postings p JOIN entries e ON e.id = p.entry_id"
        " JOIN accounts a ON a.id = p.account_id"
        f" WHERE e.status = 'posted' AND e.sealed = 1 AND {where}", args).fetchall()


def _snapshots(conn: sqlite3.Connection, rows) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for row in rows:
        entry_id = int(row["entry_id"])
        if entry_id not in out:
            out[entry_id] = snapshot_of(conn, row["snap"])
    return out


def _colors(conn: sqlite3.Connection) -> dict[int, str]:
    out = {}
    for row in conn.execute("SELECT account_id, color FROM categories").fetchall():
        out[int(row["account_id"])] = row["color"]
    for row in conn.execute("SELECT account_id, color FROM income_sources").fetchall():
        out[int(row["account_id"])] = row["color"]
    return out


def period_flows(conn: sqlite3.Connection, date_from: str, date_to: str,
                 currency_view: str = "RUB", *, extra_where: str = "", extra_args: list | None = None
                 ) -> dict:
    """Расходы по категориям и доходы по источникам за период, в валюте показа."""
    where = "e.op_date >= ? AND e.op_date <= ? AND a.type IN ('expense','income')"
    args = [date_from, date_to]
    if extra_where:
        where += f" AND {extra_where}"
        args += list(extra_args or [])
    rows = _rows(conn, where, args)
    snaps = _snapshots(conn, rows)
    colors = _colors(conn)

    expenses: dict[int, dict] = {}
    incomes: dict[int, dict] = {}
    for row in rows:
        snapshot = snaps[int(row["entry_id"])]
        amount = int(row["amount"])
        value = to_view(abs(amount), row["currency"], currency_view, snapshot)
        account_id = int(row["account_id"])
        if row["type"] == "expense":
            bucket = expenses.setdefault(account_id, {
                "category_id": account_id, "name": row["name"], "icon": row["icon"],
                "color": colors.get(account_id), "amount": 0, "count": 0})
            bucket["amount"] += value if amount > 0 else -value
            bucket["count"] += 1
        else:
            bucket = incomes.setdefault(account_id, {
                "source_id": account_id, "name": row["name"], "icon": row["icon"],
                "color": colors.get(account_id), "amount": 0, "count": 0, "projects": {},
                "tax_accrued": 0})
            bucket["amount"] += value if amount < 0 else -value
            bucket["count"] += 1
            project = row["project"]
            if project:
                bucket["projects"][project] = bucket["projects"].get(project, 0) + \
                    (value if amount < 0 else -value)

    # начисленный налог по источникам: налоговая проводка живёт в той же операции
    tax_rows = _rows(conn, "e.op_date >= ? AND e.op_date <= ? AND a.slug = 'tax_npd'"
                     + (f" AND {extra_where}" if extra_where else ""),
                     [date_from, date_to] + list(extra_args or []))
    for row in tax_rows:
        amount = int(row["amount"])
        if amount >= 0:
            continue                      # уплата налога, а не начисление
        snapshot = snaps.get(int(row["entry_id"])) or snapshot_of(conn, row["snap"])
        value = to_view(-amount, row["currency"], currency_view, snapshot)
        source_row = conn.execute(
            "SELECT p.account_id AS id FROM postings p JOIN accounts a ON a.id = p.account_id"
            " WHERE p.entry_id = ? AND a.type = 'income' LIMIT 1", (int(row["entry_id"]),)).fetchone()
        if source_row and int(source_row["id"]) in incomes:
            incomes[int(source_row["id"])]["tax_accrued"] += value

    expense_total = sum(b["amount"] for b in expenses.values())
    income_total = sum(b["amount"] for b in incomes.values())
    return {"expenses": expenses, "incomes": incomes,
            "expense_total": expense_total, "income_total": income_total}


def _with_shares(buckets: list[dict], total: int, currency_view: str) -> list[dict]:
    buckets = sorted(buckets, key=lambda b: -b["amount"])
    shares = spread_shares([b["amount"] for b in buckets], total)
    out = []
    for bucket, share in zip(buckets, shares):
        item = dict(bucket)
        item["amount"] = money_dict(bucket["amount"], currency_view)
        item["share_bp"] = share
        out.append(item)
    return out


def analytics_month(month: str, *, currency_view: str = "RUB") -> dict:
    from backend import db, rates
    conn = db.get_conn()
    snapshot_now = rates.snapshot(conn=conn)
    date_from, date_to = month_bounds(month)
    flows = period_flows(conn, date_from, date_to, currency_view)
    prev_month = shift_month(month, -1)
    prev_from, prev_to = month_bounds(prev_month)
    prev = period_flows(conn, prev_from, prev_to, currency_view)

    limits = {int(row["category_id"]): row for row in conn.execute(
        "SELECT * FROM limits WHERE active = 1").fetchall()}

    categories = []
    for bucket in flows["expenses"].values():
        item = dict(bucket)
        prev_bucket = prev["expenses"].get(bucket["category_id"])
        item["prev_amount"] = money_dict(prev_bucket["amount"] if prev_bucket else 0, currency_view)
        limit_row = limits.get(bucket["category_id"])
        if limit_row:
            limit_value = to_view(int(limit_row["amount"]), limit_row["currency"], currency_view,
                                  snapshot_now)
            item["limit"] = money_dict(limit_value, currency_view)
            item["limit_used_bp"] = share_bp(bucket["amount"], limit_value) if limit_value else 0
        else:
            item["limit"] = None
            item["limit_used_bp"] = None
        categories.append(item)
    categories = _with_shares(categories, flows["expense_total"], currency_view)

    sources = []
    for bucket in flows["incomes"].values():
        item = dict(bucket)
        projects = [{"project": name, "amount": amount}
                    for name, amount in sorted(bucket["projects"].items(), key=lambda kv: -kv[1])]
        project_shares = spread_shares([p["amount"] for p in projects], bucket["amount"]) \
            if projects else []
        item["projects"] = [{"project": p["project"], "amount": money_dict(p["amount"], currency_view),
                             "share_bp": share} for p, share in zip(projects, project_shares)]
        item["tax_accrued"] = money_dict(bucket["tax_accrued"], currency_view) \
            if bucket["tax_accrued"] else None
        item.pop("count", None)
        sources.append(item)
    sources = _with_shares(sources, flows["income_total"], currency_view)

    by_month = []
    for offset in range(11, -1, -1):
        point = shift_month(month, -offset)
        point_from, point_to = month_bounds(point)
        point_flows = period_flows(conn, point_from, point_to, currency_view)
        by_month.append({"month": point,
                         "income": money_dict(point_flows["income_total"], currency_view),
                         "expense": money_dict(point_flows["expense_total"], currency_view)})

    today = today_dubai()
    limits_view = []
    for category_id, row in limits.items():
        spent = flows["expenses"].get(category_id, {}).get("amount", 0)
        account = conn.execute("SELECT name FROM accounts WHERE id = ?", (category_id,)).fetchone()
        limit_value = int(row["amount"])
        left_days = max(0, days_between(today, date_to)) if date_from <= today <= date_to else 0
        limits_view.append({
            "category_id": category_id, "name": account["name"] if account else "",
            "limit": money_dict(limit_value, row["currency"]),
            "spent": money_dict(spent, currency_view),
            "used_bp": share_bp(spent, limit_value) if limit_value else 0,
            "left_days": left_days})

    next_month = shift_month(month, 1)
    has_next = conn.execute(
        "SELECT 1 FROM entries WHERE status = 'posted' AND op_date >= ? LIMIT 1",
        (month_bounds(next_month)[0],)).fetchone()

    return {
        "month": month, "currency": currency_view,
        "prev_month": prev_month, "next_month": next_month if has_next else None,
        "income_total": money_dict(flows["income_total"], currency_view),
        "expense_total": money_dict(flows["expense_total"], currency_view),
        "net": money_dict(flows["income_total"] - flows["expense_total"], currency_view),
        "categories": categories,
        "by_month": by_month,
        "income_sources": sources,
        "limits": limits_view,
    }


def feed_summary(conn: sqlite3.Connection, f: EntryFilters) -> dict:
    """Плитки «Траты / Доходы» на экране «Операции» — по тем же фильтрам, по всему периоду (§5.5)."""
    date_from = f.date_from or "0000-01-01"
    date_to = f.date_to or "9999-12-31"
    extra, args = [], []
    if f.kind:
        extra.append("e.kind = ?")
        args.append(f.kind)
    if f.account_id:
        extra.append("EXISTS (SELECT 1 FROM postings x WHERE x.entry_id = e.id AND x.account_id = ?)")
        args.append(int(f.account_id))
    if f.category_id:
        extra.append("p.account_id = ?")
        args.append(int(f.category_id))
    if f.q:
        like = f"%{f.q.strip()}%"
        extra.append("(e.description LIKE ? OR e.raw_input LIKE ? OR e.project LIKE ?)")
        args.extend([like, like, like])
    flows = period_flows(conn, date_from, date_to, f.currency_view,
                         extra_where=" AND ".join(extra), extra_args=args)
    out_breakdown = _with_shares(list(flows["expenses"].values()), flows["expense_total"],
                                 f.currency_view)
    in_breakdown = _with_shares(list(flows["incomes"].values()), flows["income_total"],
                                f.currency_view)
    return {
        "currency": f.currency_view,
        "out": money_dict(flows["expense_total"], f.currency_view),
        "in": money_dict(flows["income_total"], f.currency_view),
        "out_breakdown": [{"category_id": b["category_id"], "name": b["name"], "color": b["color"],
                           "amount": b["amount"], "share_bp": b["share_bp"]} for b in out_breakdown],
        "in_breakdown": [{"source_id": b["source_id"], "name": b["name"], "color": b["color"],
                          "amount": b["amount"], "share_bp": b["share_bp"]} for b in in_breakdown],
    }


def category_entries(category_id: int, *, month: str | None = None, currency_view: str = "RUB",
                     limit: int = 50, cursor: str | None = None) -> dict:
    from backend.ledger import api
    date_from = date_to = None
    if month:
        date_from, date_to = month_bounds(month)
    filters = EntryFilters(category_id=int(category_id), date_from=date_from, date_to=date_to,
                           currency_view=currency_view, limit=limit, cursor=cursor)
    page = api.list_entries(filters)
    summary = page.get("summary") or feed_summary(api._conn(), filters)
    total = next((b["amount"] for b in summary["out_breakdown"]
                  if b["category_id"] == int(category_id)), money_dict(0, currency_view))
    return {"items": page["items"], "total": total, "next_cursor": page["next_cursor"],
            "has_more": page["has_more"]}


def money_flows(conn: sqlite3.Connection, date_from: str, date_to: str) -> list[sqlite3.Row]:
    """Все проводки по денежным личным счетам за период — основа листа ДДС (§9)."""
    return conn.execute(
        "SELECT p.*, e.kind AS kind, e.op_date AS op_date, e.rates_snapshot AS snap,"
        " a.slug AS slug, a.name AS name FROM postings p"
        " JOIN entries e ON e.id = p.entry_id JOIN accounts a ON a.id = p.account_id"
        " WHERE e.status = 'posted' AND e.sealed = 1 AND e.op_date >= ? AND e.op_date <= ?"
        "   AND a.is_money = 1 AND a.type = 'asset_personal'"
        " ORDER BY e.op_date, e.id, p.seq", (date_from, date_to)).fetchall()
