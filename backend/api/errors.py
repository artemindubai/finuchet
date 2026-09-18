# -*- coding: utf-8 -*-
"""Ошибки API: код ядра → HTTP-код и тело {"error": {...}} (ARCHITECTURE §5.2)."""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.contracts import LedgerError

log = logging.getLogger("finuchet.api")

HTTP_BY_CODE = {
    "auth_required": 401,
    "forbidden": 403,
    "not_found": 404,
    "bad_request": 400,
    "unknown_account": 400,
    "currency_mismatch": 400,
    "counterparty_required": 400,
    "opening_balance_not_allowed": 400,
    "account_archived": 400,
    "unbalanced_entry": 500,
    "already_void": 409,
    "not_voided": 409,
    "entry_is_old_version": 409,
    "tranche_has_releases": 409,
    "batch_has_pending": 409,
    "rate_unavailable": 503,
    "frontend_not_built": 503,
}


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def ledger_error_response(exc: LedgerError) -> JSONResponse:
    status = HTTP_BY_CODE.get(exc.code, 400)
    return JSONResponse(status_code=status,
                        content=error_body(exc.code, exc.message, exc.details))


def install(app) -> None:
    @app.exception_handler(LedgerError)
    async def _ledger_error(request: Request, exc: LedgerError):   # noqa: ANN001
        if HTTP_BY_CODE.get(exc.code, 400) >= 500:
            log.error("ошибка ядра %s: %s", exc.code, exc.message)
        return ledger_error_response(exc)

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):     # noqa: ANN001
        return JSONResponse(status_code=400,
                            content=error_body("bad_request", "Не разобрали запрос",
                                               {"reason": str(exc)}))
