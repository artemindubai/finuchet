# -*- coding: utf-8 -*-
"""Главная и карточка счёта (ARCHITECTURE §5.4, §5.6)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, Request

from backend import db, ledger, settings_store
from backend.api.deps import currency_param, require_user, run
from backend.contracts import EntryFilters
from backend.ledger import planned as planned_mod
from backend.ledger.checks import check_view, enter_fact
from backend.ledger import kopilka as kopilka_mod
from backend.ledger.analytics import analytics_month, period_flows
from backend.ledger.common import money_dict, resolve_account
from backend.tz import month_bounds, today_dubai
from backend.ledger.balances import account_view as account_view_of, balances as balances_of
from backend.ledger.tranches import (freeze_account_id, move_rows, move_view,
                                     open_rows as open_tranche_rows, view as tranche_view)

router = APIRouter(prefix="/api", tags=["home"])


def _month_block(currency_view: str) -> dict:
    month = today_dubai()[:7]
    date_from, date_to = month_bounds(month)
    conn = db.get_conn()
    flows = period_flows(conn, date_from, date_to, currency_view)
    top = sorted(flows["expenses"].values(), key=lambda b: -b["amount"])[:3]
    total = flows["expense_total"]
    return {
        "month": month,
        "expense_total": money_dict(flows["expense_total"], currency_view),
        "income_total": money_dict(flows["income_total"], currency_view),
        "top_categories": [{
            "category_id": item["category_id"], "name": item["name"], "icon": item["icon"],
            "color": item["color"], "amount": money_dict(item["amount"], currency_view),
            "share_bp": (item["amount"] * 10_000 + (total // 2 if total else 0)) // total
            if total else 0} for item in top],
    }


def _home(currency_view: str) -> dict:
    conn = db.get_conn()
    data = balances_of(conn, currency_view=currency_view)
    data["family"]["visible"] = bool(settings_store.get("family_block_visible", True, conn=conn))
    feed = ledger.list_entries(EntryFilters(limit=7, currency_view=currency_view))
    data["recent"] = feed["items"]
    data["upcoming"] = planned_mod.upcoming(3)
    data["month"] = _month_block(currency_view)
    data["warnings"] = []
    data["kopilka"] = kopilka_mod.view(conn, with_items=False)
    data.pop("accounts", None)
    return data


@router.get("/home")
async def home(request: Request, currency: str | None = None, user: int = Depends(require_user)):
    return await run(_home, currency_param(currency))


def _account(account_ref, currency_view: str, limit: int, cursor: str | None) -> dict:
    conn = db.get_conn()
    row = resolve_account(conn, account_ref)
    view = account_view_of(conn, row, currency_view=currency_view)
    frozen = view["frozen"]["amount"] if view["frozen"] else 0
    view["free"] = money_dict(view["balance"]["amount"] - frozen, view["currency"])
    default_freeze = freeze_account_id(conn)
    tranche_rows = [t for t in open_tranche_rows(conn)
                    if (int(t["account_id"]) if t["account_id"] is not None else default_freeze)
                    == int(row["id"])]
    feed = ledger.list_entries(EntryFilters(account_id=int(row["id"]), currency_view=currency_view,
                                            limit=limit, cursor=cursor))
    month = today_dubai()[:7]
    date_from, date_to = month_bounds(month)
    flows = conn.execute(
        "SELECT SUM(CASE WHEN p.amount > 0 THEN p.amount ELSE 0 END) AS inflow,"
        " SUM(CASE WHEN p.amount < 0 THEN -p.amount ELSE 0 END) AS outflow"
        " FROM postings p JOIN entries e ON e.id = p.entry_id"
        " WHERE p.account_id = ? AND e.status = 'posted' AND e.sealed = 1"
        "   AND e.op_date >= ? AND e.op_date <= ?", (int(row["id"]), date_from, date_to)).fetchone()
    currency = row["currency"] or currency_view
    return {
        "account": view,
        "check": check_view(conn, row),
        "kopilka": kopilka_mod.view(conn) if row["slug"] == kopilka_mod.rule(conn)["account"] else None,
        "tranches": [tranche_view(conn, t) for t in tranche_rows]
        + [move_view(conn, m) for m in move_rows(conn) if int(m["account_id"]) == int(row["id"])],
        "entries": {"items": feed["items"], "days": feed["days"],
                    "next_cursor": feed["next_cursor"], "has_more": feed["has_more"]},
        "month": {"in": money_dict(int(flows["inflow"] or 0), currency),
                  "out": money_dict(int(flows["outflow"] or 0), currency)},
    }


@router.get("/accounts/{account_ref}")
async def account(account_ref: str, currency: str | None = None,
                  limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
                  user: int = Depends(require_user)):
    return await run(_account, account_ref, currency_param(currency), limit, cursor)


@router.get("/kopilka")
async def kopilka(user: int = Depends(require_user)):
    """Копилка 10 %: сколько начислено с поступлений, сколько переведено, сколько ещё перевести."""
    return await run(lambda: kopilka_mod.view(db.get_conn()))


@router.post("/accounts/{account_ref}/check_fact")
async def check_fact(account_ref: str, body: dict = Body(default={}),
                     user: int = Depends(require_user)):
    """Артём пересчитал наличку: {"amount": минорные единицы, "note": "…"} → выравнивание и запись факта."""
    try:
        amount = int(body.get("amount"))
    except (TypeError, ValueError):
        from backend.contracts import LedgerError
        raise LedgerError("bad_request", "Нужна сумма факта в минорных единицах", {"amount": body.get("amount")})
    return await run(enter_fact, account_ref, amount, note=body.get("note"))


@router.get("/analytics/month")
async def analytics(month: str | None = None, currency: str | None = None,
                    user: int = Depends(require_user)):
    return await run(analytics_month, month or today_dubai()[:7],
                     currency_view=currency_param(currency))


@router.get("/analytics/category")
async def analytics_category(category_id: int, month: str | None = None,
                             currency: str | None = None, limit: int = Query(50, ge=1, le=200),
                             cursor: str | None = None, user: int = Depends(require_user)):
    return await run(ledger.category_entries, category_id, month=month,
                     currency_view=currency_param(currency), limit=limit, cursor=cursor)


@router.get("/debts")
async def debts(currency: str | None = None, user: int = Depends(require_user)):
    return await run(ledger.debts, currency_view=currency_param(currency))


@router.get("/family/freeze_moves")
async def freeze_moves(status: str = "all", user: int = Depends(require_user)):
    return await run(lambda: {"items": ledger.freeze_moves(status=status)})


@router.post("/family/freeze_move")
async def freeze_move(body: dict = Body(default={}), user: int = Depends(require_user)):
    """Перенос заморозки в дирхамы. Тело: rub_amount (копейки; нет — вся нехватка покрытия),
    account (по умолчанию mashreq_personal), rate_e6 (нет — курс траншей), op_date, note."""
    return await run(lambda: ledger.freeze_move(
        rub_amount=body.get("rub_amount"), account=body.get("account") or "mashreq_personal",
        rate_e6=body.get("rate_e6"), op_date=body.get("op_date"), note=body.get("note")))


@router.post("/family/freeze_move/{move_id}/void")
async def void_freeze_move(move_id: int, body: dict = Body(default={}),
                           user: int = Depends(require_user)):
    return await run(lambda: ledger.void_freeze_move(move_id, reason=body.get("reason")))
