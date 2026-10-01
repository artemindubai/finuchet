# -*- coding: utf-8 -*-
"""Копилка 10 % (01.10, Артём: «теперь и впредь с каждого поступления откладывай по 10 % в копилку,
чтобы я знал, сколько туда надо будет перевести»).

С каждого дохода (kind income, любой счёт и валюта) начисляется percent_bp «к переводу в копилку».
Переводы на счёт копилки (любой вид операции, кроме дохода, начального остатка и выравнивания)
гасят начисления по порядку — от старого поступления к новому. Считается всё в валюте копилки (AED).
Рубли переводятся в дирхамы по курсу последнего дня покупки дирхамов (обмены дня целиком, в том числе
цепочкой через Bybit: 01.10 137 800 ₽ → 1 593,74 USDT → 5 853 AED); обменов нет — по рыночному курсу.

Настройка `kopilka_rule`: {"account": slug копилки, "percent_bp": 1000, "start": "YYYY-MM-DD"}.
Поступления и переводы раньше start не считаются: правило началось 23.09 (первый перевод в копилку)."""
from __future__ import annotations

import sqlite3

from backend import money, rates, settings_store
from backend.ledger.common import account_row, money_dict

SETTING = "kopilka_rule"
DEFAULT_RULE = {"account": "kopilka_mashrek", "percent_bp": 1000, "start": "2026-09-23"}
NOT_COVER_KINDS = ("income", "opening_balance", "balance_correction")


def rule(conn: sqlite3.Connection) -> dict:
    cfg = settings_store.get(SETTING, None, conn=conn)
    out = dict(DEFAULT_RULE)
    if isinstance(cfg, dict):
        out.update({k: v for k, v in cfg.items() if v not in (None, "")})
    out["percent_bp"] = int(out["percent_bp"])
    return out


def _account(conn: sqlite3.Connection, cfg: dict) -> sqlite3.Row | None:
    return account_row(conn, cfg["account"])


def _exchanges(conn: sqlite3.Connection) -> list[dict]:
    """Обмены журнала: дата и стороны (валюта → сумма со знаком), без счёта «Обмен валют»."""
    rows = conn.execute(
        "SELECT e.id AS id, e.op_date AS op_date, p.currency AS currency, SUM(p.amount) AS amount"
        " FROM entries e JOIN postings p ON p.entry_id = e.id JOIN accounts a ON a.id = p.account_id"
        " WHERE e.kind = 'exchange' AND e.status = 'posted' AND e.sealed = 1 AND a.type != 'equity'"
        " GROUP BY e.id, p.currency ORDER BY e.op_date DESC, e.id DESC").fetchall()
    out: dict[int, dict] = {}
    for r in rows:
        out.setdefault(int(r["id"]), {"id": int(r["id"]), "op_date": r["op_date"], "legs": {}})[
            "legs"][r["currency"]] = int(r["amount"])
    return list(out.values())                          # по убыванию даты


def _pair(x: dict, give: str, get: str) -> tuple[int, int] | None:
    legs = x["legs"]
    if legs.get(give, 0) < 0 and legs.get(get, 0) > 0:
        return -legs[give], legs[get]
    return None


def exchange_rate(conn: sqlite3.Connection) -> dict:
    """Рублей за дирхам (×1e6) по последнему дню, когда покупались дирхамы: за рубли напрямую или
    через USDT (Bybit: ₽ → USDT → AED, тогда рубли за USDT — из покупок USDT того же или более раннего
    дня). Обменов нет — рыночный курс."""
    xs = _exchanges(conn)
    day = next((x["op_date"] for x in xs if _pair(x, "RUB", "AED") or _pair(x, "USDT", "AED")), None)
    rub = aed = 0
    ids: list[int] = []
    if day:
        usdt_rub_e6 = None
        buys = [x for x in xs if x["op_date"] <= day and _pair(x, "RUB", "USDT")]
        if buys:
            buy_day = buys[0]["op_date"]
            pairs = [_pair(x, "RUB", "USDT") for x in buys if x["op_date"] == buy_day]
            usdt_rub_e6 = money.round_half_up(sum(p[0] for p in pairs) * money.RATE_E6,
                                              sum(p[1] for p in pairs))
            ids += [x["id"] for x in buys if x["op_date"] == buy_day]
        if usdt_rub_e6 is None:
            snap = rates.snapshot(conn=conn, allow_network=False)
            usdt_rub_e6 = int(snap.get("rub_per_usdt_e6") or 0)
        for x in xs:
            if x["op_date"] != day:
                continue
            direct, via = _pair(x, "RUB", "AED"), _pair(x, "USDT", "AED")
            if direct:
                rub += direct[0]
                aed += direct[1]
                ids.append(x["id"])
            elif via:
                rub += money.convert_e6(via[0], usdt_rub_e6)
                aed += via[1]
                ids.append(x["id"])
    if aed > 0:
        return {"rub_per_aed_e6": money.round_half_up(rub * money.RATE_E6, aed), "source": "exchange",
                "op_date": day, "entry_ids": sorted(set(ids)),
                "rub": money_dict(rub, "RUB"), "aed": money_dict(aed, "AED")}
    snap = rates.snapshot(conn=conn, allow_network=False)
    return {"rub_per_aed_e6": int(snap.get("rub_per_aed_e6") or 0), "source": "market",
            "op_date": None, "entry_ids": []}


def _to_aed(amount: int, currency: str, rate_e6: int, snap: dict | None) -> int:
    if currency == "AED":
        return int(amount)
    if currency == "RUB":
        return money.round_half_up(int(amount) * money.RATE_E6, rate_e6) if rate_e6 else 0
    rub = money.convert(int(amount), currency, "RUB", snapshot=snap)   # USD/USDT — через рубль
    return money.round_half_up(rub * money.RATE_E6, rate_e6) if rate_e6 else 0


def _incomes(conn: sqlite3.Connection, cfg: dict, kop_id: int | None) -> list[sqlite3.Row]:
    """Доходы с даты старта: сумма — с доходного счёта (минус на нём = поступление)."""
    return conn.execute(
        "SELECT e.id AS id, e.op_date AS op_date, e.description AS description, p.currency AS currency,"
        " -SUM(p.amount) AS amount, a.name AS source_name,"
        " (SELECT p2.account_id FROM postings p2 JOIN accounts a2 ON a2.id = p2.account_id"
        "   WHERE p2.entry_id = e.id AND p2.amount > 0 AND a2.type != 'expense'"
        "   ORDER BY p2.seq LIMIT 1) AS money_account_id"
        " FROM entries e JOIN postings p ON p.entry_id = e.id JOIN accounts a ON a.id = p.account_id"
        " WHERE e.kind = 'income' AND e.status = 'posted' AND e.sealed = 1 AND a.type = 'income'"
        "   AND e.op_date >= ?"
        " GROUP BY e.id, p.currency ORDER BY e.op_date, e.id", (cfg["start"],)).fetchall()


def _transfers(conn: sqlite3.Connection, cfg: dict, kop: sqlite3.Row) -> list[sqlite3.Row]:
    marks = ",".join("?" * len(NOT_COVER_KINDS))
    return conn.execute(
        "SELECT e.id AS id, e.op_date AS op_date, e.kind AS kind, e.description AS description,"
        " SUM(p.amount) AS amount"
        " FROM entries e JOIN postings p ON p.entry_id = e.id"
        f" WHERE p.account_id = ? AND p.currency = ? AND e.status = 'posted' AND e.sealed = 1"
        f"   AND e.op_date >= ? AND e.kind NOT IN ({marks})"
        " GROUP BY e.id HAVING SUM(p.amount) != 0 ORDER BY e.op_date, e.id",
        (int(kop["id"]), kop["currency"] or "AED", cfg["start"], *NOT_COVER_KINDS)).fetchall()


def accrual(amount: int, percent_bp: int) -> int:
    return money.round_half_up(int(amount) * int(percent_bp), 10_000)


def view(conn: sqlite3.Connection, *, with_items: bool = True) -> dict | None:
    cfg = rule(conn)
    kop = _account(conn, cfg)
    if kop is None:
        return None
    cur = kop["currency"] or "AED"
    rate = exchange_rate(conn)
    rate_e6 = rate["rub_per_aed_e6"]
    snap = None
    items = []
    for r in _incomes(conn, cfg, int(kop["id"])):
        if r["money_account_id"] is not None and int(r["money_account_id"]) == int(kop["id"]):
            continue                                   # доход прямо в копилку уже отложен
        acc = accrual(int(r["amount"]), cfg["percent_bp"])
        if r["currency"] not in ("RUB", "AED") and snap is None:
            snap = rates.snapshot(conn=conn, allow_network=False)
        items.append({"entry_id": int(r["id"]), "op_date": r["op_date"],
                      "description": r["description"] or "", "source": r["source_name"],
                      "amount": money_dict(int(r["amount"]), r["currency"]),
                      "accrued": money_dict(acc, r["currency"]),
                      "accrued_aed": _to_aed(acc, r["currency"], rate_e6, snap)})
    transfers = [{"entry_id": int(t["id"]), "op_date": t["op_date"], "kind": t["kind"],
                  "description": t["description"] or "", "amount": money_dict(int(t["amount"]), cur)}
                 for t in _transfers(conn, cfg, kop)]
    pool = sum(t["amount"]["amount"] for t in transfers)
    covered_total = pool
    for i in items:
        take = max(0, min(pool, i["accrued_aed"]))
        pool -= take
        left = i["accrued_aed"] - take
        i["covered"] = money_dict(take, cur)
        i["left"] = money_dict(left, cur)
        i["status"] = "covered" if left == 0 else ("partial" if take else "open")
        i["accrued_aed"] = money_dict(i["accrued_aed"], cur)
    accrued = sum(i["accrued_aed"]["amount"] for i in items)
    due = sum(i["left"]["amount"] for i in items)
    out = {
        "account": {"id": int(kop["id"]), "slug": kop["slug"], "name": kop["name"]},
        "percent_bp": cfg["percent_bp"], "start": cfg["start"],
        "rate": rate,
        "accrued": money_dict(accrued, cur),
        "transferred": money_dict(covered_total, cur),
        "due": money_dict(due, cur),
        "due_rub": money_dict(money.round_half_up(due * rate_e6, money.RATE_E6), "RUB"),
        "surplus": money_dict(max(pool, 0), cur),
        "count": len(items),
    }
    if with_items:
        out["items"] = list(reversed(items))           # свежие сверху, как в ленте
        out["transfers"] = list(reversed(transfers))
    return out


def for_entry(conn: sqlite3.Connection, entry_id: int) -> dict | None:
    """Строка для ответа на занесённый доход: сколько начислено с него и сколько всего к переводу."""
    entry = conn.execute("SELECT kind, op_date, status FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if entry is None or entry["kind"] != "income" or entry["status"] != "posted":
        return None
    full = view(conn)
    if not full:
        return None
    item = next((i for i in full["items"] if i["entry_id"] == int(entry_id)), None)
    if item is None:
        return None
    return {"accrued": item["accrued"], "accrued_aed": item["accrued_aed"],
            "due": full["due"], "due_rub": full["due_rub"]}
