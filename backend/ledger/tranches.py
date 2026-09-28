# -*- coding: utf-8 -*-
"""Заморозка за балансом (рубли; с 28.09 и перенос в дирхамы): транши и FIFO-разморозка (ARCHITECTURE §4.3).

Ключевое правило: возврат, гасящий транш целиком, забирает ВЕСЬ остаток рублей транша — иначе
на пропорции теряются копейки (грабля 4 журнала).

Второе ключевое правило (грабля 28): состояние траншей — функция ЖУРНАЛА, а не истории кликов.
Любая отмена/возврат/правка погашения пересчитывает FIFO заново по всем живым операциям
(`rebuild_releases`), иначе отмена «заплатил за семью» воскрешает заморозку, которую нечем гасить."""
from __future__ import annotations

import sqlite3

from backend import money
from backend.contracts import LedgerError, RateQuote
from backend.ledger.common import account_row, freeze_account_slug, money_dict, warn
from backend.money import fmt_amount, fmt_rate
from backend.tz import human_date, utc_now

# Виды операций, которые гасят долг семье и потому размораживают рубли (§4.3, грабля 13).
RELEASE_KINDS = ("family_repayment", "paid_for_family_from_own")
FREEZE_KINDS = ("family_withdrawal",) + RELEASE_KINDS


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
    """Сколько заморожено на каждом счёте в ЕГО валюте: рублёвые транши (без привязки — на
    freeze_account) и блоки в дирхамах от переносов заморозки."""
    default_id = freeze_account_id(conn)
    out: dict[int, int] = {}
    rows = conn.execute(
        "SELECT account_id, rub_left FROM family_tranches WHERE status = 'open'").fetchall()
    for row in rows:
        acc = int(row["account_id"]) if row["account_id"] is not None else default_id
        if acc is None:
            continue
        out[acc] = out.get(acc, 0) + int(row["rub_left"])
    for row in conn.execute(
            "SELECT account_id, locked_left FROM freeze_moves WHERE status = 'open'").fetchall():
        acc = int(row["account_id"])
        out[acc] = out.get(acc, 0) + int(row["locked_left"])
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


def release_amount_of(conn: sqlite3.Connection, entry_id: int) -> int:
    """Сколько AED эта операция гасит из долга семье: её положительная проводка в семейный контур."""
    row = conn.execute(
        "SELECT p.amount AS amount FROM postings p JOIN accounts a ON a.id = p.account_id"
        " WHERE p.entry_id = ? AND p.amount > 0 AND p.currency = 'AED'"
        "   AND (a.type = 'asset_family' OR a.slug = 'family_fund')"
        " ORDER BY p.seq LIMIT 1", (entry_id,)).fetchone()
    return int(row["amount"]) if row is not None else 0


def rebuild_releases(conn: sqlite3.Connection) -> dict[int, int]:
    """Пересчитывает транши, переносы и разморозку заново по живому журналу (§4.3, грабля 28).

    Транш жив ровно пока жива операция-основание; погашения (возвраты и «заплатил за семью»)
    применяются по FIFO в порядке `op_date, id`. Перенос заморозки (freeze_moves) в свою дату
    забирает рубли у траншей по FIFO и блокирует дирхамы; погашение сначала снимает блок в
    дирхамах — ими и возвращают семье, — потом рублёвые транши. Возвращает {entry_id: сколько AED
    не нашло транша} — это те самые «вернул больше, чем брал»."""
    conn.execute("DELETE FROM tranche_releases")
    conn.execute("DELETE FROM freeze_move_parts")
    conn.execute("DELETE FROM freeze_move_releases")
    live: list[dict] = []
    for row in conn.execute(
            "SELECT t.id AS id, t.aed_taken AS aed_taken, t.rub_frozen AS rub_frozen,"
            " e.status AS entry_status FROM family_tranches t JOIN entries e ON e.id = t.entry_id"
            " ORDER BY t.op_date, t.id").fetchall():
        if row["entry_status"] != "posted":
            conn.execute(
                "UPDATE family_tranches SET aed_left = ?, rub_left = ?, status = 'void' WHERE id = ?",
                (int(row["aed_taken"]), int(row["rub_frozen"]), int(row["id"])))
            continue
        live.append({"id": int(row["id"]), "aed_left": int(row["aed_taken"]),
                     "rub_left": int(row["rub_frozen"])})

    events: list[tuple] = []
    moves: list[dict] = []
    for row in conn.execute("SELECT * FROM freeze_moves ORDER BY op_date, id").fetchall():
        if row["status"] == "void":
            conn.execute("UPDATE freeze_moves SET rub_moved = 0, aed_taken = 0, aed_left = 0,"
                         " locked = 0, locked_left = 0 WHERE id = ?", (int(row["id"]),))
            continue
        move = {"id": int(row["id"]), "rub_requested": int(row["rub_requested"]),
                "rate_e6": int(row["rate_e6"]) if row["rate_e6"] else None,
                "rub_moved": 0, "aed_taken": 0, "aed_left": 0, "locked": 0, "locked_left": 0}
        moves.append(move)
        events.append((row["op_date"], int(row["created_at"]), "move", move))

    marks = ",".join("?" * len(RELEASE_KINDS))
    for row in conn.execute(
            f"SELECT id, op_date, created_at FROM entries WHERE status = 'posted' AND sealed = 1"
            f" AND kind IN ({marks}) ORDER BY op_date, id", RELEASE_KINDS).fetchall():
        events.append((row["op_date"], int(row["created_at"]), "release", int(row["id"])))
    events.sort(key=lambda ev: (ev[0], ev[1]))   # sort стабилен: внутри секунды порядок id

    now = utc_now()
    shortfall: dict[int, int] = {}
    for _, _, what, obj in events:
        if what == "move":
            _apply_move(conn, obj, live, now)
            continue
        entry_id = obj
        left = release_amount_of(conn, entry_id)
        for move in moves:
            if left <= 0:
                break
            take = min(left, move["aed_left"])
            if take <= 0:
                continue
            if take == move["aed_left"]:
                lock = move["locked_left"]
            else:
                lock = move["locked_left"] * take // move["aed_left"]
            move["aed_left"] -= take
            move["locked_left"] -= lock
            conn.execute(
                "INSERT INTO freeze_move_releases (move_id, entry_id, aed_released, locked_released,"
                " created_at) VALUES (?,?,?,?,?)", (move["id"], entry_id, take, lock, now))
            left -= take
        for tranche in live:
            if left <= 0:
                break
            take = min(left, tranche["aed_left"])
            if take <= 0:
                continue
            if take == tranche["aed_left"]:
                rub = tranche["rub_left"]        # закрываем целиком — отдаём весь остаток рублей
            else:
                rub = tranche["rub_left"] * take // tranche["aed_left"]
            tranche["aed_left"] -= take
            tranche["rub_left"] -= rub
            conn.execute(
                "INSERT INTO tranche_releases (tranche_id, entry_id, aed_released, rub_released,"
                " created_at) VALUES (?,?,?,?,?)", (tranche["id"], entry_id, take, rub, now))
            left -= take
        if left > 0:
            shortfall[entry_id] = left
    for tranche in live:
        conn.execute(
            "UPDATE family_tranches SET aed_left = ?, rub_left = ?, status = ? WHERE id = ?",
            (tranche["aed_left"], tranche["rub_left"],
             "closed" if tranche["aed_left"] == 0 else "open", tranche["id"]))
    for move in moves:
        conn.execute(
            "UPDATE freeze_moves SET rub_moved = ?, aed_taken = ?, aed_left = ?, locked = ?,"
            " locked_left = ?, status = ? WHERE id = ?",
            (move["rub_moved"], move["aed_taken"], move["aed_left"], move["locked"],
             move["locked_left"], "open" if move["aed_left"] > 0 else "closed", move["id"]))
    return shortfall


def _apply_move(conn: sqlite3.Connection, move: dict, live: list[dict], now: int) -> None:
    """Перенос: забрать рубли у траншей по FIFO и заблокировать дирхамы.

    Курс не задан — блокируется ровно та часть долга семье, что стояла за рублями (курс траншей).
    Задан — дирхамы = перенесённые рубли / курс."""
    left_rub = move["rub_requested"]
    for tranche in live:
        if left_rub <= 0:
            break
        take_rub = min(left_rub, tranche["rub_left"])
        if take_rub <= 0:
            continue
        if take_rub == tranche["rub_left"]:
            aed = tranche["aed_left"]            # весь остаток транша — без потери копеек
        else:
            aed = tranche["aed_left"] * take_rub // tranche["rub_left"]
        tranche["aed_left"] -= aed
        tranche["rub_left"] -= take_rub
        conn.execute(
            "INSERT INTO freeze_move_parts (move_id, tranche_id, aed_moved, rub_moved, created_at)"
            " VALUES (?,?,?,?,?)", (move["id"], tranche["id"], aed, take_rub, now))
        move["rub_moved"] += take_rub
        move["aed_taken"] += aed
        left_rub -= take_rub
    if move["rate_e6"]:
        locked = money.round_half_up(move["rub_moved"] * 1_000_000, move["rate_e6"])
    else:
        locked = move["aed_taken"]
    move["aed_left"] = move["aed_taken"]
    move["locked"] = move["locked_left"] = locked


def move_rows(conn: sqlite3.Connection, *, status: str = "open") -> list[sqlite3.Row]:
    if status == "all":
        return conn.execute("SELECT * FROM freeze_moves ORDER BY op_date, id").fetchall()
    return conn.execute("SELECT * FROM freeze_moves WHERE status = ? ORDER BY op_date, id",
                        (status,)).fetchall()


def frozen_total_aed(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(SUM(locked_left), 0) AS total FROM freeze_moves"
                       " WHERE status = 'open'").fetchone()
    return int(row["total"])


def move_view(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """Перенос в форме транша: рядом с рублёвыми траншами на экранах счёта и семьи.

    rub_frozen/rub_left здесь несут дирхамы (валюта в самой сумме) — так их без правок рисует
    та же строка транша в мини-аппе; frozen_currency говорит, что это блок в AED."""
    account = account_row(conn, int(row["account_id"]))
    cur = row["currency"]
    rate = f" по курсу {fmt_rate(int(row['rate_e6']))}" if row["rate_e6"] else ""
    return {
        "id": int(row["id"]),
        "move_id": int(row["id"]),
        "kind": "freeze_move",
        "op_date": row["op_date"],
        "frozen_currency": cur,
        "rub_requested": money_dict(int(row["rub_requested"]), "RUB"),
        "rub_moved": money_dict(int(row["rub_moved"]), "RUB"),
        "aed_taken": money_dict(int(row["aed_taken"]), "AED"),
        "aed_left": money_dict(int(row["aed_left"]), "AED"),
        "rub_frozen": money_dict(int(row["locked"]), cur),
        "rub_left": money_dict(int(row["locked_left"]), cur),
        "rate_e6": int(row["rate_e6"]) if row["rate_e6"] else (
            money.round_half_up(int(row["rub_moved"]) * 1_000_000, int(row["aed_taken"]))
            if int(row["aed_taken"]) else 0),
        "rate_source": "freeze_move",
        "account_id": int(account["id"]) if account is not None else None,
        "account_name": account["name"] if account is not None else None,
        "status": row["status"],
        "note": row["note"],
        "label": (f"заблокировано вместо рублей {fmt_amount(int(row['rub_moved']), 'RUB')}"
                  f" (перенос от {human_date(row['op_date'])}{rate})"),
    }


def shortfall_warning(kind: str, extra: int) -> dict | None:
    """Погашение не нашло транша. Для возврата это «вернул больше, чем брал»; для «заплатил за
    семью» никакого возврата не было — врать про возврат нельзя (грабля 35)."""
    if extra <= 0:
        return None
    if kind == "paid_for_family_from_own":
        return warn("family_owes_you",
                    f"Долг семье закрыт, теперь семья должна вам {fmt_amount(extra, 'AED')}",
                    {"extra": money_dict(extra, "AED")})
    return warn("repaid_more_than_taken",
                f"Вернули больше, чем брали, на {fmt_amount(extra, 'AED')}",
                {"extra": money_dict(extra, "AED")})


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


def touches_freeze(conn: sqlite3.Connection, entry_id: int) -> bool:
    """Задевает ли операция заморозку — чтобы не перетряхивать транши на каждой покупке кофе."""
    row = conn.execute("SELECT kind FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return row is not None and row["kind"] in FREEZE_KINDS


def tranche_of_entry(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM family_tranches WHERE entry_id = ? ORDER BY id LIMIT 1",
                        (entry_id,)).fetchone()


def releases_of_entry(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT r.*, t.op_date AS tranche_date, t.rate_e6 AS rate_e6 FROM tranche_releases r"
        " JOIN family_tranches t ON t.id = r.tranche_id WHERE r.entry_id = ?"
        " ORDER BY t.op_date, t.id", (entry_id,)).fetchall()
    return [{"tranche_id": int(row["tranche_id"]),
             "aed": money_dict(int(row["aed_released"]), "AED"),
             "rub": money_dict(int(row["rub_released"]), "RUB"),
             "op_date": row["tranche_date"], "rate_e6": int(row["rate_e6"])} for row in rows]


def unlocks_of_entry(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    """Сколько дирхамов разблокировало погашение (блоки от переносов заморозки)."""
    rows = conn.execute(
        "SELECT r.*, m.op_date AS move_date, m.currency AS currency, m.account_id AS account_id"
        " FROM freeze_move_releases r JOIN freeze_moves m ON m.id = r.move_id"
        " WHERE r.entry_id = ? ORDER BY m.op_date, m.id", (entry_id,)).fetchall()
    return [{"move_id": int(row["move_id"]), "account_id": int(row["account_id"]),
             "aed": money_dict(int(row["aed_released"]), "AED"),
             "unlocked": money_dict(int(row["locked_released"]), row["currency"]),
             "op_date": row["move_date"]} for row in rows]
