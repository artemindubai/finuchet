# -*- coding: utf-8 -*-
"""Операции: лента, карточка, ручной ввод, правка, отмена (ARCHITECTURE §5.5)."""
from __future__ import annotations

from dataclasses import fields

from fastapi import APIRouter, Body, Depends, Query

from backend import ledger
from backend.api.deps import currency_param, require_user, run
from backend.contracts import (EntryFilters, LedgerError, OpeningBalanceItem, OperationPatch,
                               ParsedOperation)
from backend.tz import today_dubai

router = APIRouter(prefix="/api", tags=["entries"])

PARSED_FIELDS = {f.name for f in fields(ParsedOperation)}
PATCH_FIELDS = {f.name for f in fields(OperationPatch)}


def _parsed_from_body(body: dict) -> ParsedOperation:
    if not isinstance(body, dict):
        raise LedgerError("bad_request", "Ожидался объект операции")
    data = {key: value for key, value in body.items() if key in PARSED_FIELDS}
    if "kind" not in data:
        raise LedgerError("bad_request", "Не указан вид операции", {"field": "kind"})
    if data.get("amount") is None:
        raise LedgerError("bad_request", "Не указана сумма", {"field": "amount"})
    data["source"] = "manual"          # поле source в теле игнорируется (§5.5)
    data["raw_input"] = None
    data["confidence"] = None
    return ParsedOperation(**data)


@router.get("/entries")
async def list_entries(q: str | None = None, account_id: int | None = None,
                       category_id: int | None = None, kind: str | None = None,
                       status: str = "posted", date_from: str | None = None,
                       date_to: str | None = None, currency: str | None = None,
                       limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
                       user: int = Depends(require_user)):
    filters = EntryFilters(q=q, account_id=account_id, category_id=category_id, kind=kind,
                           status=status, date_from=date_from, date_to=date_to,
                           currency_view=currency_param(currency), limit=limit, cursor=cursor)
    return await run(ledger.list_entries, filters)


@router.get("/entries/{entry_id}")
async def get_entry(entry_id: int, currency: str | None = None,
                    user: int = Depends(require_user)):
    return await run(ledger.get_entry, entry_id, currency_view=currency_param(currency))


@router.post("/entries")
async def create_entry(body: dict = Body(...), currency: str | None = None,
                       user: int = Depends(require_user)):
    op = _parsed_from_body(body)
    return await run(ledger.post_operation, op, actor="api",
                     currency_view=currency_param(currency))


@router.post("/entries/{entry_id}/amend")
async def amend_entry(entry_id: int, body: dict = Body(default={}), currency: str | None = None,
                      user: int = Depends(require_user)):
    data = {key: value for key, value in (body or {}).items() if key in PATCH_FIELDS}
    patch = OperationPatch(**data)
    return await run(ledger.amend_entry, entry_id, patch, actor="api",
                     currency_view=currency_param(currency))


@router.post("/entries/{entry_id}/void")
async def void_entry(entry_id: int, body: dict = Body(default={}), currency: str | None = None,
                     user: int = Depends(require_user)):
    reason = (body or {}).get("reason")
    return await run(ledger.void_entry, entry_id, actor="api", reason=reason,
                     currency_view=currency_param(currency))


@router.post("/entries/{entry_id}/unvoid")
async def unvoid_entry(entry_id: int, currency: str | None = None,
                       user: int = Depends(require_user)):
    return await run(ledger.unvoid_entry, entry_id, actor="api",
                     currency_view=currency_param(currency))


@router.post("/opening-balances")
async def opening_balances(body: dict = Body(...), currency: str | None = None,
                           user: int = Depends(require_user)):
    items = (body or {}).get("items") or []
    if not items:
        raise LedgerError("bad_request", "Пустой список остатков", {"field": "items"})
    op_date = (body or {}).get("op_date") or today_dubai()
    parsed = [OpeningBalanceItem(account=item["account"], amount=int(item["amount"]),
                                 currency=item["currency"], op_date=item.get("op_date") or op_date)
              for item in items]
    return await run(ledger.post_opening_balances, parsed, actor="manual", op_date=op_date,
                     currency_view=currency_param(currency))
