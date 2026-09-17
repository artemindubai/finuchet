# -*- coding: utf-8 -*-
"""Календарь, цели, лимиты, сверка и выгрузка (ARCHITECTURE §5.9, §5.10, §5.13)."""
from __future__ import annotations

import logging
import os
import secrets

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import FileResponse

from backend import db, ledger, settings_store
from backend.api.deps import currency_param, require_user, run
from backend.contracts import LedgerError, ReconcileDecision
from backend.export import xlsx as xlsx_export
from backend.ledger import goals as goals_mod
from backend.ledger import limits as limits_mod
from backend.ledger import planned as planned_mod
from backend.tz import today_dubai, utc_now
from backend.ledger.reconcile import align as align_batch, apply_reconcile, inbox as inbox_view

log = logging.getLogger("finuchet.api.reports")
router = APIRouter(prefix="/api", tags=["reports"])
TOKEN_TTL_SEC = 900


@router.get("/calendar")
async def calendar(date_from: str | None = None, date_to: str | None = None,
                   user: int = Depends(require_user)):
    return await run(planned_mod.calendar, date_from=date_from, date_to=date_to)


@router.post("/calendar")
async def create_planned(body: dict = Body(...), user: int = Depends(require_user)):
    return await run(planned_mod.create, body or {})


@router.patch("/calendar/{planned_id}")
async def patch_planned(planned_id: int, body: dict = Body(default={}),
                        user: int = Depends(require_user)):
    return await run(planned_mod.patch, planned_id, body or {})


@router.delete("/calendar/{planned_id}")
async def delete_planned(planned_id: int, user: int = Depends(require_user)):
    return await run(planned_mod.deactivate, planned_id)


@router.post("/calendar/{planned_id}/paid")
async def planned_paid(planned_id: int, body: dict = Body(default={}),
                       currency: str | None = None, user: int = Depends(require_user)):
    data = body or {}
    return await run(planned_mod.mark_planned_paid, planned_id, op_date=data.get("op_date"),
                     amount=data.get("amount"), account=data.get("account"), actor="api",
                     currency_view=currency_param(currency))


@router.get("/goals")
async def goals(user: int = Depends(require_user)):
    return await run(goals_mod.goals_view)


@router.post("/goals")
async def create_goal(body: dict = Body(...), user: int = Depends(require_user)):
    return await run(goals_mod.create, body or {})


@router.patch("/goals/{goal_id}")
async def patch_goal(goal_id: int, body: dict = Body(default={}),
                     user: int = Depends(require_user)):
    return await run(goals_mod.patch, goal_id, body or {})


@router.post("/goals/{goal_id}/allocate")
async def allocate_goal(goal_id: int, body: dict = Body(...), user: int = Depends(require_user)):
    data = body or {}
    return await run(goals_mod.goal_allocate, goal_id, int(data["amount"]), data["currency"],
                     data.get("op_date"), data.get("note", ""))


@router.post("/goals/{goal_id}/archive")
async def archive_goal(goal_id: int, user: int = Depends(require_user)):
    return await run(goals_mod.archive, goal_id)


@router.get("/limits")
async def limits(month: str | None = None, user: int = Depends(require_user)):
    return await run(limits_mod.limits_view, month)


@router.put("/limits/{category_id}")
async def put_limit(category_id: int, body: dict = Body(...), user: int = Depends(require_user)):
    data = body or {}
    return await run(limits_mod.set_limit, category_id, int(data["amount"]),
                     data.get("currency", "RUB"), bool(data.get("active", True)))


@router.delete("/limits/{category_id}")
async def delete_limit(category_id: int, user: int = Depends(require_user)):
    return await run(limits_mod.delete_limit, category_id)


@router.get("/inbox")
async def inbox(batch_id: str | None = None, user: int = Depends(require_user)):
    return await run(inbox_view, batch_id)


@router.post("/inbox/{inbox_id}/resolve")
async def resolve_inbox(inbox_id: int, body: dict = Body(...), currency: str | None = None,
                        user: int = Depends(require_user)):
    data = body or {}
    decision = ReconcileDecision(inbox_id=inbox_id, decision=data.get("decision", "skip"),
                                 match_entry_id=data.get("match_entry_id"),
                                 category=data.get("category"))
    return await run(apply_reconcile, [decision], actor="api",
                     currency_view=currency_param(currency))


@router.post("/inbox/{batch_id}/align")
async def align_inbox(batch_id: str, body: dict = Body(default={}), currency: str | None = None,
                      user: int = Depends(require_user)):
    data = body or {}
    return await run(align_batch, batch_id, bank_balance=data.get("bank_balance"),
                     actor="api", currency_view=currency_param(currency))


def _build_export(body: dict) -> dict:
    period = body.get("period")
    date_from = body.get("date_from")
    date_to = body.get("date_to")
    sheets = body.get("sheets")
    path, filename = xlsx_export.build(period=period, date_from=date_from, date_to=date_to,
                                       sheets=sheets)
    return {"path": path, "filename": filename}


def _issue_token(path: str, filename: str) -> str:
    token = secrets.token_hex(16)
    settings_store.set(f"export_token_{token}",
                       {"path": path, "filename": filename,
                        "expires_at": utc_now() + TOKEN_TTL_SEC},
                       conn=db.get_conn())
    return token


@router.post("/export/xlsx")
async def export_xlsx(body: dict = Body(default={}), user: int = Depends(require_user)):
    built = await run(_build_export, body or {})
    path, filename = built["path"], built["filename"]
    try:
        from backend.bot.runner import send_document_to_owner
        sent = await send_document_to_owner(path, f"Выгрузка {filename}")
    except ImportError:
        sent = False
    except Exception as exc:                       # бот не поднялся — отдадим ссылкой
        log.warning("не удалось отправить файл через бота: %s", exc)
        sent = False
    if sent:
        return {"ok": True, "delivery": "bot", "message": "Файл придёт в чат"}
    token = await run(_issue_token, path, filename)
    return {"ok": True, "delivery": "link", "url": f"/api/export/download/{token}"}


@router.get("/export/download/{token}")
async def download_export(token: str):
    """Токен вместо initData: ссылку открывает браузер без заголовков (§5.13)."""
    def _take() -> dict:
        key = f"export_token_{token}"
        data = settings_store.get(key, None, conn=db.get_conn())
        if not data:
            raise LedgerError("not_found", "Ссылка не найдена или устарела")
        if int(data.get("expires_at", 0)) < utc_now():
            settings_store.delete(key, conn=db.get_conn())
            raise LedgerError("not_found", "Ссылка не найдена или устарела")
        settings_store.delete(key, conn=db.get_conn())
        if not os.path.exists(data["path"]):
            raise LedgerError("not_found", "Файл уже забрали")
        return data

    data = await run(_take)
    return FileResponse(
        data["path"], filename=data["filename"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/health/invariants")
async def invariants(user: int = Depends(require_user)):
    """Служебная проверка сходимости — то же, что смотрит приёмка."""
    problems = await run(ledger.check_invariants)
    return {"ok": not problems, "problems": problems, "checked_at": today_dubai()}
