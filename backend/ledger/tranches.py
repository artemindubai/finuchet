# -*- coding: utf-8 -*-
"""Заморозка рублей за балансом: транши и FIFO-разморозка (ARCHITECTURE §4.3).

Ключевое правило: возврат, гасящий транш целиком, забирает ВЕСЬ остаток рублей транша — иначе
на пропорции теряются копейки (грабля 4 журнала)."""
from __future__ import annotations

import sqlite3

from backend import money
from backend.contracts import LedgerError, RateQuote
from backend.ledger.common import account_row, freeze_account_slug, money_dict, warn
from backend.money import fmt_amount, fmt_rate
from backend.tz import human_date, utc_now


def freeze_account_id(conn: sqlite3.Connection, ref=None) -> int | None:
    row = account_row(conn, ref) if ref is not None else None
    if row is None:
        row = account_row(conn, freeze_account_slug(conn))
    return int(row["id"]) if row is not None else None


def rub_balance(conn: sqlite3.Connection, account_id: int) -> int:
    row = conn.execute(
        "SELECT balance FROM v_balances WHERE account_id = ? AND currency = 'RUB'",
        (account_id,)).fetchone()
    return int(row["balance"]) if row else 0


def frozen_on_account(conn: sqlite3.Connection, account_id: int,
                      *, exclude_tranche: int | None = None) -> int:
    default_id = freeze_account_id(conn)
    rows = conn.execute(
        "SELECT id, account_id, rub_left FROM family_tranches WHERE status = 'open'").fetchall()
    total = 0
    for row in rows:
        if exclude_tranche and int(row["id"]) == exclude_tranche:
            continue
        acc = int(row["account_id"]) if row["account_id"] is not None else default_id
        if acc == account_id:
            total += int(row["rub_left"])
    return total


def frozen_by_account(conn: sqlite3.Connection) -> dict[int, int]:
    """Сколько заморожено на каждом рублёвом счёте; транш без привязки — на freeze_account."""
    default_id = freeze_account_id(conn)
    out: dict[int, int] = {}
    rows = conn.execute(
        "SELECT account_id, rub_left FROM family_tranches WHERE status = 'open'").fetchall()
    for row in rows:
        acc = int(row["account_id"]) if row["account_id"] is not None else default_id
        if acc is None:
            continue
        out[acc] = out.get(acc, 0) + int(row["rub_left"])
    return out


def frozen_total(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(rub_left), 0) AS total FROM family_tranches WHERE status = 'open'"
    ).fetchone()
    return int(row["total"])


def open_rows(conn: sqlite3.Connection, *, status: str = "open") -> list[sqlite3.Row]:
    if status == "all":
        return conn.execute(
            "SELECT * FROM family_tranches ORDER BY op_date, id").fetchall()
    return conn.execute(
        "SELECT * FROM family_tranches WHERE status = ? ORDER BY op_date, id", (status,)).fetchall()


def label_for(row: sqlite3.Row) -> str:
    return (f"заблокировано в счёт взятых {human_date(row['op_date'])} "
            f"{fmt_amount(int(row['aed_taken']), 'AED')} по курсу {fmt_rate(int(row['rate_e6']))}")


def view(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    account = account_row(conn, int(row["account_id"])) if row["account_id"] is not None \
        else account_row(conn, freeze_account_slug(conn))
    return {
        "id": int(row["id"]),
        "entry_id": int(row["entry_id"]),
        "op_date": row["op_date"],
        "aed_taken": money_dict(int(row["aed_taken"]), "AED"),
        "aed_left": money_dict(int(row["aed_left"]), "AED"),
        "rub_frozen": money_dict(int(row["rub_frozen"]), "RUB"),
        "rub_left": money_dict(int(row["rub_left"]), "RUB"),
        "rate_e6": int(row["rate_e6"]),
        "rate_source": row["rate_source"],
        "account_id": int(account["id"]) if account is not None else None,
        "account_name": account["name"] if account is not None else None,
        "status": row["status"],
        "label": label_for(row),
    }


def open_tranche(conn: sqlite3.Connection, *, entry_id: int, op_date: str, aed_taken: int,
                 quote: RateQuote, account_ref=None) -> tuple[int, list[dict]]:
    """Открывает транш заморозки. Нехватка покрытия — предупреждение, а не отказ (ТЗ 4.3)."""
    warnings: list[dict] = []
    rub_frozen = money.round_half_up(int(aed_taken) * int(quote.rate_e6), 1_000_000)
    account_id = freeze_account_id(conn, account_ref)
    cur = conn.execute(
        "INSERT INTO family_tranches (entry_id, op_date, aed_taken, aed_left, rate_e6, rate_source,"
        " rate_at, rub_frozen, rub_left, account_id, status, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,'open',?)",
        (entry_id, op_date, int(aed_taken), int(aed_taken), int(quote.rate_e6), quote.source,
         int(quote.at), rub_frozen, rub_frozen, account_id, utc_now()))
    tranche_id = int(cur.lastrowid)

    if account_id:
        free = rub_balance(conn, account_id) - frozen_on_account(conn, account_id,
                                                                 exclude_tranche=tranche_id)
        shortfall = max(0, rub_frozen - free)
        if shortfall > 0:
            account = account_row(conn, account_id)
            warnings.append(warn(
                "freeze_not_covered",
                f"Не хватает покрытия {fmt_amount(shortfall, 'RUB')}",
                {"shortfall": money_dict(shortfall, "RUB"),
                 "account": account["slug"] if account is not None else None}))
    return tranche_id, warnings


def release_fifo(conn: sqlite3.Connection, *, entry_id: int, aed_amount: int) -> tuple[list[dict], list[dict]]:
    """Гасит открытые транши по FIFO. Возвращает (releases, warnings)."""
    left = int(aed_amount)
    releases: list[dict] = []
    warnings: list[dict] = []
    for row in open_rows(conn):
        if left <= 0:
            break
        take = min(left, int(row["aed_left"]))
        if take <= 0:
            continue
        if take == int(row["aed_left"]):
            rub = int(row["rub_left"])           # закрываем целиком — отдаём весь остаток рублей
        else:
            rub = int(row["rub_left"]) * take // int(row["aed_left"])
        aed_left = int(row["aed_left"]) - take
        rub_left = int(row["rub_left"]) - rub
        conn.execute(
            "UPDATE family_tranches SET aed_left = ?, rub_left = ?, status = ? WHERE id = ?",
            (aed_left, rub_left, "closed" if aed_left == 0 else "open", int(row["id"])))
        conn.execute(
            "INSERT INTO tranche_releases (tranche_id, entry_id, aed_released, rub_released, created_at)"
            " VALUES (?,?,?,?,?)", (int(row["id"]), entry_id, take, rub, utc_now()))
        releases.append({"tranche_id": int(row["id"]),
                         "aed": money_dict(take, "AED"), "rub": money_dict(rub, "RUB"),
                         "op_date": row["op_date"], "rate_e6": int(row["rate_e6"])})
        left -= take
    if left > 0:
        warnings.append(warn("repaid_more_than_taken",
                             f"Вернули больше, чем брали, на {fmt_amount(left, 'AED')}",
                             {"extra": money_dict(left, "AED")}))
    return releases, warnings


def active_releases_of_tranche(conn: sqlite3.Connection, tranche_id: int) -> list[int]:
    """Релизы транша, чья операция-основание не отменена."""
    rows = conn.execute(
        "SELECT r.entry_id FROM tranche_releases r JOIN entries e ON e.id = r.entry_id"
        " WHERE r.tranche_id = ? AND e.status = 'posted'", (tranche_id,)).fetchall()
    return [int(row["entry_id"]) for row in rows]


def guard_no_releases(conn: sqlite3.Connection, entry_id: int) -> None:
    """Нельзя отменять/править взятие, по которому уже был возврат (§4.3 а, б)."""
    for row in conn.execute("SELECT id FROM family_tranches WHERE entry_id = ? AND status != 'void'",
                            (entry_id,)).fetchall():
        releases = active_releases_of_tranche(conn, int(row["id"]))
        if releases:
            raise LedgerError(
                "tranche_has_releases",
                "Сначала отмените возврат — он привязан к этому взятию",
                {"tranche_id": int(row["id"]), "releases": releases})


def void_for_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    """Откат заморозки при отмене операции: свои транши в void, свои релизы — назад в транши."""
    guard_no_releases(conn, entry_id)
    conn.execute("UPDATE family_tranches SET status = 'void' WHERE entry_id = ?", (entry_id,))
    for row in conn.execute(
            "SELECT * FROM tranche_releases WHERE entry_id = ?", (entry_id,)).fetchall():
        tranche = conn.execute("SELECT * FROM family_tranches WHERE id = ?",
                               (int(row["tranche_id"]),)).fetchone()
        if tranche is None or tranche["status"] == "void":
            continue
        aed_left = int(tranche["aed_left"]) + int(row["aed_released"])
        rub_left = int(tranche["rub_left"]) + int(row["rub_released"])
        conn.execute("UPDATE family_tranches SET aed_left = ?, rub_left = ?, status = 'open'"
                     " WHERE id = ?", (aed_left, rub_left, int(tranche["id"])))


def unvoid_for_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    """Зеркало void_for_entry для кнопки «Вернуть» (§4.1)."""
    conn.execute("UPDATE family_tranches SET status = CASE WHEN aed_left = 0 THEN 'closed'"
                 " ELSE 'open' END WHERE entry_id = ? AND status = 'void'", (entry_id,))
    for row in conn.execute(
            "SELECT * FROM tranche_releases WHERE entry_id = ?", (entry_id,)).fetchall():
        tranche = conn.execute("SELECT * FROM family_tranches WHERE id = ?",
                               (int(row["tranche_id"]),)).fetchone()
        if tranche is None or tranche["status"] == "void":
            continue
        aed_left = int(tranche["aed_left"]) - int(row["aed_released"])
        rub_left = int(tranche["rub_left"]) - int(row["rub_released"])
        if aed_left < 0:
            raise LedgerError("tranche_has_releases",
                              "Транш уже погашен другими возвратами",
                              {"tranche_id": int(tranche["id"])})
        conn.execute("UPDATE family_tranches SET aed_left = ?, rub_left = ?, status = ?"
                     " WHERE id = ?",
                     (aed_left, rub_left, "closed" if aed_left == 0 else "open", int(tranche["id"])))


def tranche_of_entry(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM family_tranches WHERE entry_id = ? ORDER BY id LIMIT 1",
                        (entry_id,)).fetchone()


def releases_of_entry(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT r.*, t.op_date AS tranche_date, t.rate_e6 AS rate_e6 FROM tranche_releases r"
        " JOIN family_tranches t ON t.id = r.tranche_id WHERE r.entry_id = ?", (entry_id,)).fetchall()
    return [{"tranche_id": int(row["tranche_id"]),
             "aed": money_dict(int(row["aed_released"]), "AED"),
             "rub": money_dict(int(row["rub_released"]), "RUB"),
             "op_date": row["tranche_date"], "rate_e6": int(row["rate_e6"])} for row in rows]
