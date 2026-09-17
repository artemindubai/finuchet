# -*- coding: utf-8 -*-
"""Карточки бота — точный формат ARCHITECTURE §7.2.

Только чистый текст: parse_mode не задаётся нигде, а `plain_tg()` срезает разметку, если она
всё-таки просочилась из модели. Числа форматируются теми же правилами, что и в мини-аппе (§5.3),
чтобы цифры на экране и в чате совпадали глазами.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

NBSP = " "
MINUS = "−"

SYMBOL = {"RUB": "₽", "AED": "AED", "USDT": "USDT", "USD": "$"}

RATE_SOURCE_RU = {
    "voice": "названный курс",
    "bybit_p2p": "Bybit P2P",
    "er_api+markup": "курс дня плюс надбавка",
    "er_api": "курс дня",
    "cbr+markup": "ЦБ плюс надбавка",
    "cbr": "ЦБ",
    "cache": "курс из кэша",
    "manual": "вручную",
}

# «заморожено 12 250 ₽ на Т-Банке» — предложный падеж для счетов, которые реально бывают счётом
# заморозки; для всех прочих печатается «на счёте <имя>».
_PREPOSITIONAL = {
    "Т-Банк": "Т-Банке",
    "Сбер": "Сбере",
    "Наличные ₽": "наличных ₽",
}


@dataclass
class Reply:
    """Что бот отправляет в ответ: текст плюс кнопки (label, callback_data | web_app url)."""

    text: str
    buttons: list[Any] = field(default_factory=list)


def plain_tg(text: str) -> str:
    """Телеграм-боты Артёма пишут чистым текстом: срезаем markdown-мусор на всякий случай."""
    text = re.sub(r"\*{1,3}([^*]*)\*{1,3}", r"\1", text)
    text = re.sub(r"_{2,}([^_]*)_{2,}", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"`+", "", text)
    return text.strip()


# ---------------------------------------------------------------- числа и даты

def format_amount(money: Any, *, with_sign: bool = False) -> str:
    """{'amount': 184250, 'currency': 'AED'} → «1 842,50 AED»."""
    if money is None:
        return ""
    amount = int(money.get("amount", 0))
    currency = money.get("currency", "RUB")
    negative = amount < 0
    whole, frac = divmod(abs(amount), 100)
    groups = f"{whole:,}".replace(",", NBSP)
    text = groups if frac == 0 else f"{groups},{frac:02d}"
    out = f"{text}{NBSP}{SYMBOL.get(currency, currency)}"
    if negative:
        return MINUS + out
    return ("+" + out) if with_sign else out


def format_rate(rate_e6: int | None, pair: str | None = None) -> str:
    """24500000 → «24,50»."""
    if not rate_e6:
        return ""
    value = round(int(rate_e6) / 1_000_000, 2)
    text = f"{value:.2f}".replace(".", ",")
    if not pair:
        return text
    src, dst = pair.split("/") if "/" in pair else (pair, "")
    return f"{text}{NBSP}{SYMBOL.get(dst, dst)}/{SYMBOL.get(src, src)}"


def dubai(iso: str | None) -> dt.datetime | None:
    if not iso:
        return None
    try:
        stamp = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(dt.timezone(dt.timedelta(hours=4)))


def short_dt(iso: str | None) -> str:
    stamp = dubai(iso)
    return stamp.strftime("%d.%m %H:%M") if stamp else ""


def short_date(op_date: str | None) -> str:
    if not op_date:
        return ""
    try:
        return dt.date.fromisoformat(op_date).strftime("%d.%m")
    except ValueError:
        return op_date


def full_date(op_date: str | None) -> str:
    if not op_date:
        return ""
    try:
        return dt.date.fromisoformat(op_date).strftime("%d.%m.%Y")
    except ValueError:
        return op_date


# ---------------------------------------------------------------- разбор ответа ядра

def _effects(result: dict) -> dict:
    return result.get("effects") or {}


def _accounts(result: dict) -> list[dict]:
    return _effects(result).get("accounts") or []


def _account_by_id(result: dict, account_id: Any) -> dict | None:
    for acc in _accounts(result):
        if acc.get("id") == account_id:
            return acc
    return None


def _postings(result: dict, side: str) -> list[dict]:
    return [p for p in result.get("postings") or [] if p.get("side") == side]


def _money_account(result: dict, side: str) -> dict | None:
    """Денежный счёт операции с нужной стороны: тот, что ядро вернуло в effects.accounts.

    Служебные счета (Обмен валют, Начальные остатки, Корректировка) пропускаем: в обмене первой
    кредитовой проводкой идёт как раз «Обмен валют», а человеку нужен банк.
    """
    for posting in _postings(result, side):
        slug = posting.get("account_slug") or ""
        if slug.startswith("eq_") or slug == "family_fund":
            continue
        acc = _account_by_id(result, posting.get("account_id"))
        if acc is not None:
            return acc
    return None


def _account_named(result: dict, slug: str) -> dict | None:
    for acc in _accounts(result):
        if acc.get("slug") == slug:
            return acc
    return None


def _balance_line(acc: dict | None, *, prefix: str = "Остаток") -> str:
    if not acc:
        return ""
    if acc.get("role") == "liability":
        name = acc.get("name", "")
        title = "Долг по кредитке" if "редитк" in name else f"Долг: {name}"
        return f"{title}: {format_amount(acc.get('natural'))}"
    line = f"{prefix}: {format_amount(acc.get('balance'))}"
    frozen = acc.get("frozen")
    if frozen and int(frozen.get("amount", 0)) > 0:
        free = {"amount": int(acc["balance"]["amount"]) - int(frozen["amount"]),
                "currency": acc["balance"]["currency"]}
        line += f", свободно {format_amount(free)}"
    return line


def _balances_line(result: dict, accounts: list[dict | None]) -> str:
    parts = [f"{a['name']} {format_amount(a.get('natural') if a.get('role') == 'liability' else a.get('balance'))}"
             for a in accounts if a]
    return "Остатки: " + ", ".join(parts) if parts else ""


def _free_rub_part(result: dict) -> str:
    free = _effects(result).get("free_rub")
    return f"свободно в рублях {format_amount(free)}" if free else ""


def _is_name(word: str) -> bool:
    """Имя человека, которое можно склонять: одно слово кириллицей, не аббревиатура."""
    return bool(word) and word.isalpha() and word[:1].isupper() and not word.isupper()


def dative(name: str) -> str:
    """«Маша» → «Маше», «Иван» → «Ивану». Аббревиатуры и непонятное оставляем как есть."""
    if not _is_name(name):
        return name
    last = name[-1].lower()
    if last in "ая":
        return name[:-1] + "е"
    if last == "й":
        return name[:-1] + "ю"
    if last == "ь":
        return name[:-1] + "ю"
    return name + "у"


def genitive(name: str) -> str:
    """«Маша» → «Маши», «Иван» → «Ивана»."""
    if not _is_name(name):
        return name
    last = name[-1].lower()
    if last in "ая":
        return name[:-1] + "и"
    if last == "й":
        return name[:-1] + "я"
    if last == "ь":
        return name[:-1] + "я"
    return name + "а"


def _prep(name: str) -> str:
    known = _PREPOSITIONAL.get(name)
    return f"на {known}" if known else f"на счёте {name}"


def _rate_line(result: dict) -> str:
    rate = result.get("rate") or {}
    if not rate.get("rate_e6"):
        return ""
    pair = rate.get("pair") or "AED/RUB"
    src = RATE_SOURCE_RU.get(rate.get("source"), rate.get("source") or "")
    when = short_dt(rate.get("at"))
    tail = ", ".join(x for x in (src, when) if x)
    return f"Курс {format_rate(rate['rate_e6'], pair)}" + (f" ({tail})" if tail else "")


def _tranche_line(result: dict) -> str:
    tranche = _effects(result).get("tranche") or result.get("tranche")
    if not tranche:
        return ""
    label = (tranche.get("label") or "").strip()
    if label:
        label = label[0].upper() + label[1:]
    else:
        label = (f"Заблокировано в счёт взятых {full_date(tranche.get('op_date'))} "
                 f"{format_amount(tranche.get('aed_taken'))} по курсу {format_rate(tranche.get('rate_e6'))}")
    where = tranche.get("account_name")
    money = format_amount(tranche.get("rub_frozen") or tranche.get("rub_left"))
    return f"{label} — {money} {_prep(where)}" if where else f"{label} — {money}"


def _released_line(result: dict) -> str:
    released = _effects(result).get("released") or []
    if not released:
        return ""
    total = sum(int(r["rub"]["amount"]) for r in released if r.get("rub"))
    money = format_amount({"amount": total, "currency": "RUB"})
    if len(released) == 1:
        one = released[0]
        tail = ""
        if one.get("op_date"):
            tail = f" по траншу от {short_date(one['op_date'])}"
            if one.get("rate_e6"):
                tail += f" (курс {format_rate(one['rate_e6'])})"
        else:
            tail = " по траншу"
        return f"Разморожено {money}{tail}"
    return f"Разморожено {money} по {len(released)} траншам"


def _family_line(result: dict, *, with_frozen: bool = True) -> str:
    eff = _effects(result)
    debt = eff.get("family_debt")
    if debt is None:
        return ""
    direction = eff.get("family_direction") or ("i_owe" if int(debt.get("amount", 0)) >= 0 else "family_owes")
    if direction == "family_owes":
        shown = {"amount": abs(int(debt.get("amount", 0))), "currency": debt.get("currency", "AED")}
        return f"Семья должна вам {format_amount(shown)}"
    line = f"Долг семье: {format_amount(debt)}"
    frozen = eff.get("frozen_rub")
    if with_frozen and frozen and int(frozen.get("amount", 0)) > 0:
        line += f", заморожено {format_amount(frozen)}"
    return line


def _warning_lines(result: dict) -> list[str]:
    out: list[str] = []
    for warn in result.get("warnings") or []:
        code = warn.get("code")
        if code == "freeze_not_covered":
            shortfall = (warn.get("details") or {}).get("shortfall")
            out.append(f"Не хватает покрытия {format_amount(shortfall)} — заморожено больше, чем есть рублей")
        elif code == "rate_from_cache":
            at = short_dt(((warn.get("details") or {}).get("at")))
            out.append(f"Курс взят из кэша{(' от ' + at) if at else ''} — сейчас биржа не отвечает.")
        elif warn.get("message"):
            out.append(warn["message"])
    return out


def _from_to_line(result: dict) -> str:
    src = _money_account(result, "credit")
    dst = _money_account(result, "debit")
    if src and dst:
        return f"Со счёта: {src['name']}, на счёт: {dst['name']}"
    acc = src or dst
    return f"Счёт: {acc['name']}" if acc else ""


def _title_amount(result: dict) -> str:
    return format_amount(result.get("amount"))


def _tax_posting(result: dict) -> dict | None:
    for posting in result.get("postings") or []:
        if posting.get("account_slug") == "tax_npd" and posting.get("side") == "credit":
            return posting
    return None


# ---------------------------------------------------------------- карточки по видам

def card_for_entry(result: dict) -> str:
    """EntryFull + effects (§5.5) → текст карточки §7.2."""
    kind = result.get("kind")
    lines = _KIND_CARDS.get(kind, _card_generic)(result)
    warnings = _warning_lines(result)
    if warnings:
        lines = lines[:-1] + warnings + lines[-1:] if len(lines) > 1 else lines + warnings
    if result.get("status") == "void":
        lines.append("Операция отменена")
    return plain_tg("\n".join(x for x in lines if x))


def _card_expense(result: dict) -> list[str]:
    acc = _money_account(result, "credit")
    title = result.get("title") or "Расход"
    return [
        f"Расход {_title_amount(result)} — {title}",
        f"Счёт: {acc['name']}" if acc else "",
        _balance_line(acc),
    ]


def _card_income(result: dict) -> list[str]:
    acc = _money_account(result, "debit")
    title = result.get("title") or "Доход"
    project = result.get("project")
    head = f"Доход {_title_amount(result)} — {title}" + (f" ({project})" if project else "")
    lines = [head, f"Счёт: {acc['name']}" if acc else ""]
    tax = _tax_posting(result)
    if tax:
        base = int((result.get("amount") or {}).get("amount") or 0)
        got = int(tax["amount"]["amount"])
        pct = f"{round(got * 100 / base, 2):g}".replace(".", ",") if base else ""
        lines.append(f"Налог НПД{(' ' + pct + ' %') if pct else ''}: {format_amount(tax['amount'])} начислено")
    lines.append(_balance_line(acc))
    return lines


def _card_transfer(result: dict) -> list[str]:
    src = _money_account(result, "credit")
    dst = _money_account(result, "debit")
    return [
        f"Перевод {_title_amount(result)}",
        _from_to_line(result),
        _balances_line(result, [src, dst]),
    ]


def _card_exchange(result: dict) -> list[str]:
    src = _money_account(result, "credit")
    dst = _money_account(result, "debit")
    given = result.get("amount") or {}
    got = _exchange_got(result, given.get("currency"))
    head = f"Обмен {format_amount(given)}"
    if got:
        head += f" на {format_amount(got)}"
    lines = [head]
    rate_line = _rate_line(result)
    if not rate_line and got:
        rate_line = _computed_rate_line(given, got)
    lines.append(rate_line)
    lines.append(_from_to_line(result))
    lines.append(_balances_line(result, [src, dst]))
    return lines


def _exchange_got(result: dict, given_currency: str | None) -> dict | None:
    for posting in _postings(result, "debit"):
        money = posting.get("amount") or {}
        if money.get("currency") and money["currency"] != given_currency:
            return money
    return None


def _computed_rate_line(given: dict, got: dict) -> str:
    a, b = int(given.get("amount") or 0), int(got.get("amount") or 0)
    if not a or not b:
        return ""
    if given.get("currency") == "RUB":
        rate_e6 = a * 1_000_000 // b
        pair = f"{got['currency']}/RUB"
    elif got.get("currency") == "RUB":
        rate_e6 = b * 1_000_000 // a
        pair = f"{given['currency']}/RUB"
    else:
        rate_e6 = b * 1_000_000 // a
        pair = f"{given['currency']}/{got['currency']}"
    return f"Курс {format_rate(rate_e6, pair)} (по суммам операции)"


def _card_family_withdrawal(result: dict) -> list[str]:
    dst = _money_account(result, "debit")
    last = "Остатки: "
    parts = []
    if dst:
        parts.append(f"{dst['name']} {format_amount(dst.get('balance'))}")
    free = _free_rub_part(result)
    if free:
        parts.append(free)
    return [
        f"Взял из семейного {_title_amount(result)}",
        _from_to_line(result),
        _rate_line(result),
        _tranche_line(result),
        _family_line(result, with_frozen=False),
        last + ", ".join(parts) if parts else "",
    ]


def _card_family_repayment(result: dict) -> list[str]:
    src = _money_account(result, "credit")
    parts = []
    if src:
        parts.append(f"{src['name']} {format_amount(src.get('balance'))}")
    free = _free_rub_part(result)
    if free:
        parts.append(free)
    return [
        f"Вернул в семейный {_title_amount(result)}",
        _from_to_line(result),
        _released_line(result),
        _family_line(result),
        ("Остатки: " + ", ".join(parts)) if parts else "",
    ]


def _card_family_topup(result: dict) -> list[str]:
    acc = _money_account(result, "debit")
    tail = _family_line(result, with_frozen=False).replace("Долг семье: ", "долг семье ")
    return [
        f"Пополнение семейного {_title_amount(result)} — от родителей",
        f"Счёт: {acc['name']}" if acc else "",
        (f"Семейные: {format_amount(acc.get('balance'))}" + (f", {tail}" if tail else "")) if acc else tail,
    ]


def _card_family_spent_own(result: dict) -> list[str]:
    acc = _money_account(result, "credit")
    tail = _family_line(result, with_frozen=False).replace("Долг семье: ", "долг семье ")
    return [
        f"Семья потратила {_title_amount(result)} из семейного",
        f"Счёт: {acc['name']}" if acc else "",
        (f"Семейные: {format_amount(acc.get('balance'))}" + (f", {tail}" if tail else "")) if acc else tail,
    ]


def _card_own_contribution(result: dict) -> list[str]:
    src = _money_account(result, "credit")
    debt = _effects(result).get("family_debt")
    note = f"Это взнос, не возврат долга: долг семье не изменился — {format_amount(debt)}" if debt else \
        "Это взнос, не возврат долга: долг семье не изменился"
    return [
        f"Внёс своих в семейный {_title_amount(result)}",
        _from_to_line(result),
        note,
        _balance_line(src) if src else "",
    ]


def _card_paid_for_family(result: dict) -> list[str]:
    src = _money_account(result, "credit")
    lines = [
        f"Заплатил за семью {_title_amount(result)} со своих",
        f"Счёт: {src['name']}" if src else "",
    ]
    released = _released_line(result)
    if released:
        lines.append(released)
    lines.append(_family_line(result))
    lines.append(_balance_line(src) if src else "")
    return lines


def _debt_of_person(debt_acc: dict, who: str, currency: str | None) -> dict | None:
    """Итог по этому человеку в валюте операции — из `by_counterparty` ядра (журнал 21)."""
    if not who or not currency:
        return None
    for person in debt_acc.get("by_counterparty") or []:
        if (person.get("name") or "").strip().lower() != who.strip().lower():
            continue
        for amount in person.get("amounts") or []:
            if amount.get("currency") == currency:
                return amount
        return None
    return None


def _card_loan(result: dict) -> list[str]:
    kind = result.get("kind")
    who = result.get("counterparty") or ""
    acc = _money_account(result, "credit") if kind in ("loan_given", "loan_repaid_by_me") \
        else _money_account(result, "debit")
    heads = {
        "loan_given": f"Дал в долг {dative(who)} {_title_amount(result)}".replace("  ", " "),
        "loan_repaid_to_me": f"Мне вернули долг {_title_amount(result)}",
        "loan_taken": f"Занял у {genitive(who)} {_title_amount(result)}".replace("  ", " "),
        "loan_repaid_by_me": f"Отдал долг {dative(who)} {_title_amount(result)}".replace("  ", " "),
    }
    debt_slug = "receivable" if kind in ("loan_given", "loan_repaid_to_me") else "payable"
    debt_acc = _account_named(result, debt_slug)
    label = "Мне должны" if debt_slug == "receivable" else "Я должен"
    debt_line = ""
    if debt_acc:
        money = _debt_of_person(debt_acc, who, (result.get("amount") or {}).get("currency"))
        if money is None:
            money = debt_acc.get("natural") or debt_acc.get("balance")
            # мультивалютный счёт без разбивки: чужую валюту не печатаем, берём сумму операции
            if (money or {}).get("currency") != (result.get("amount") or {}).get("currency"):
                money = result.get("amount")
        debt_line = f"{label}: {who} {format_amount(money)}".replace(":  ", ": ")
    lines = [heads.get(kind, ""), f"Счёт: {acc['name']}" if acc else "", debt_line]
    if result.get("due_date"):
        word = "Обещали вернуть до" if debt_slug == "receivable" else "Обещал вернуть до"
        lines.append(f"{word} {short_date(result['due_date'])}")
    lines.append(_balance_line(acc) if acc else "")
    return lines


def _card_tax_payment(result: dict) -> list[str]:
    acc = _money_account(result, "credit")
    tax_acc = _account_named(result, "tax_npd")
    return [
        f"Уплата налога НПД {_title_amount(result)}",
        f"Счёт: {acc['name']}" if acc else "",
        f"Долг по налогу: {format_amount(tax_acc.get('natural'))}" if tax_acc else "",
        _balance_line(acc) if acc else "",
    ]


def _card_opening_balance(result: dict) -> list[str]:
    acc = _money_account(result, "debit") or _money_account(result, "credit")
    net = _effects(result).get("net_worth")
    return [
        f"Начальный остаток: {acc['name']} {format_amount(acc.get('balance'))}" if acc
        else f"Начальный остаток {_title_amount(result)}",
        f"Личный итог: {format_amount(net)}" if net else "",
    ]


def _card_balance_correction(result: dict) -> list[str]:
    acc = _money_account(result, "debit") or _money_account(result, "credit")
    delta = result.get("amount") or {}
    lines = [f"Выровнял остаток: {acc['name'] if acc else ''} {format_amount(delta, with_sign=True)}".strip()]
    if acc and acc.get("balance"):
        now = int(acc["balance"]["amount"])
        was = now - int(delta.get("amount") or 0)
        cur = acc["balance"]["currency"]
        lines.append(f"Было в учёте {format_amount({'amount': was, 'currency': cur})}, "
                     f"стало {format_amount({'amount': now, 'currency': cur})}")
    return lines


def _card_generic(result: dict) -> list[str]:
    acc = _money_account(result, "credit") or _money_account(result, "debit")
    return [
        f"{result.get('title') or 'Записано'} {_title_amount(result)}".strip(),
        f"Счёт: {acc['name']}" if acc else "",
        _balance_line(acc) if acc else "",
    ]


_KIND_CARDS = {
    "expense": _card_expense,
    "income": _card_income,
    "transfer": _card_transfer,
    "exchange": _card_exchange,
    "family_withdrawal": _card_family_withdrawal,
    "family_repayment": _card_family_repayment,
    "family_topup_by_parents": _card_family_topup,
    "family_spent_own": _card_family_spent_own,
    "own_contribution_to_family": _card_own_contribution,
    "paid_for_family_from_own": _card_paid_for_family,
    "loan_given": _card_loan,
    "loan_repaid_to_me": _card_loan,
    "loan_taken": _card_loan,
    "loan_repaid_by_me": _card_loan,
    "tax_payment": _card_tax_payment,
    "opening_balance": _card_opening_balance,
    "balance_correction": _card_balance_correction,
}


# ---------------------------------------------------------------- пачки и служебные тексты

def card_for_batch(results: list[dict]) -> str:
    """Несколько операций из одной фразы — одна карточка с перечислением (§7.2)."""
    if len(results) == 1:
        return card_for_entry(results[0])
    lines = [f"Записано {len(results)} {_plural_ops(len(results))}"]
    for i, result in enumerate(results, 1):
        acc = _money_account(result, "credit") or _money_account(result, "debit")
        title = result.get("title") or ""
        head = _short_kind(result)
        lines.append(f"{i}. {head} {_title_amount(result)}"
                     + (f" — {title}" if title else "")
                     + (f", {acc['name']}" if acc else ""))
    last = results[-1]
    acc = _money_account(last, "credit") or _money_account(last, "debit")
    if acc:
        lines.append(f"Остаток: {acc['name']} {format_amount(acc.get('balance'))}")
    return plain_tg("\n".join(lines))


_SHORT_KIND = {
    "expense": "Расход", "income": "Доход", "transfer": "Перевод", "exchange": "Обмен",
    "family_withdrawal": "Взял из семейного", "family_repayment": "Вернул в семейный",
    "family_topup_by_parents": "Пополнение семейного", "own_contribution_to_family": "Взнос в семейный",
    "family_spent_own": "Трата семьи", "paid_for_family_from_own": "Заплатил за семью",
    "loan_given": "Дал в долг", "loan_repaid_to_me": "Вернули долг",
    "loan_taken": "Занял", "loan_repaid_by_me": "Отдал долг",
    "tax_payment": "Уплата налога", "opening_balance": "Начальный остаток",
    "balance_correction": "Выравнивание",
}


def _short_kind(result: dict) -> str:
    return _SHORT_KIND.get(result.get("kind"), "Операция")


def _plural_ops(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "операция"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "операции"
    return "операций"


AMEND_PROMPT = "Что поправить? Напишите или скажите, например: не 43, а 34; это с налички; это подарки, не еда."
ERROR_TEXT = "Не получилось записать. Попробуйте ещё раз одной фразой."
NO_VOICE_TEXT = "Не расслышал голосовое. Повторите или напишите текстом."
QUOTA_TEXT = "Сегодня лимит запросов к ИИ исчерпан."
START_TEXT = "Готов. Открывайте приложение кнопкой ниже."
ALREADY_ALIGNED_TEXT = "Уже сходится, корректировка не нужна."


def card_amended(result: dict, changes: list[str]) -> str:
    """Карточка после правки: первая строка — что изменилось (§7.3)."""
    head = "Поправлено"
    if changes:
        head += ": " + "; ".join(changes)
    return plain_tg(head + "\n" + card_for_entry(result))


def card_voided(result: dict) -> str:
    text = card_for_entry(result)
    if "Операция отменена" not in text:
        text += "\nОперация отменена"
    return plain_tg(text)
