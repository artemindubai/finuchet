# -*- coding: utf-8 -*-
"""Ядро учёта. Единственная точка входа для API и бота (ARCHITECTURE §4.1).

Все функции синхронные: зовущий код оборачивает их в asyncio.to_thread."""
from __future__ import annotations

from backend import db
from backend.contracts import EntryFilters, ScreenBatch
import backend.ledger.analytics as _analytics
import backend.ledger.balances as _balances
import backend.ledger.goals as _goals
import backend.ledger.limits as _limits
import backend.ledger.planned as _planned
import backend.ledger.reconcile as _reconcile
import backend.ledger.tranches as _tranches
from backend.ledger.api import (amend_entry, check_invariants, get_entry, list_entries,  # noqa: F401
                                freeze_move, freeze_moves, void_freeze_move,
                                post_opening_balances, post_operation, unvoid_entry, void_entry)
from backend.ledger.bot_bridge import (ai_quota_take, bot_hints, pending_clear,  # noqa: F401
                                       pending_get, pending_set, refs, transcript_find,
                                       transcript_put)

analytics_month = _analytics.analytics_month
category_entries = _analytics.category_entries
goals_view = _goals.goals_view
goal_allocate = _goals.goal_allocate
limits_view = _limits.limits_view
set_limit = _limits.set_limit
delete_limit = _limits.delete_limit
calendar = _planned.calendar
mark_planned_paid = _planned.mark_planned_paid
apply_reconcile = _reconcile.apply_reconcile
inbox = _reconcile.inbox


def balances(*, as_of: str | None = None, currency_view: str = "RUB") -> dict:
    return _balances.balances(db.get_conn(), as_of=as_of, currency_view=currency_view)


def account_view(account, *, currency_view: str = "RUB", as_of: str | None = None) -> dict:
    return _balances.account_view(db.get_conn(), account, currency_view=currency_view, as_of=as_of)


def family_debt(*, as_of: str | None = None) -> dict:
    return _balances.family_debt(db.get_conn(), as_of=as_of)


def free_rub(*, as_of: str | None = None) -> dict:
    return _balances.free_rub(db.get_conn(), as_of=as_of)


def debts(*, currency_view: str = "RUB") -> dict:
    return _balances.debts(db.get_conn(), currency_view=currency_view)


def tranches(*, status: str = "open") -> list[dict]:
    conn = db.get_conn()
    return [_tranches.view(conn, row) for row in _tranches.open_rows(conn, status=status)]


def reconcile(batch: ScreenBatch) -> dict:
    return _reconcile.reconcile(batch)


def entries(f: EntryFilters) -> dict:
    return list_entries(f)
