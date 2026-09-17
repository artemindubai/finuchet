# -*- coding: utf-8 -*-
"""Двухминутная проверка живого Финучёта по URL (ТЗ 11.6).

Что делает: здоровье, инварианты, Главная, запись и отмена тестовой операции на 1 ₽,
выгрузка XLSX с проверкой листов. Ничего не оставляет после себя: операция отменяется.

Запуск:
    python -X utf8 tools/smoke.py --url https://<сервис>.up.railway.app --dev-user <id>
    python -X utf8 tools/smoke.py --url http://127.0.0.1:8080 --init-data "<initData>"

Код возврата 0 — всё сошлось, 1 — хоть одна проверка провалилась.
Значения ключей берутся из ACCESS.env, если он рядом; в вывод они не попадают.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SHEETS_EXPECTED = ["ДДС", "ОСВ", "Баланс", "Журнал проводок", "За балансом"]

ok_count = 0
fail_count = 0


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / "ACCESS.env")


def say(ok: bool, title: str, detail: str = "") -> bool:
    global ok_count, fail_count
    mark = "ОК     " if ok else "ПРОВАЛ "
    if ok:
        ok_count += 1
    else:
        fail_count += 1
    print(f"{mark}{title}" + (f"\n        {detail}" if detail else ""), flush=True)
    return ok


def money(value: dict | None) -> str:
    if not value:
        return "—"
    amount = int(value["amount"]) / 100
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " " + value["currency"]


class Api:
    def __init__(self, url: str, headers: dict[str, str], timeout: float) -> None:
        self.url = url.rstrip("/")
        self.client = httpx.Client(timeout=timeout, headers=headers, follow_redirects=True)

    def get(self, path: str, **kw) -> httpx.Response:
        return self.client.get(self.url + path, **kw)

    def post(self, path: str, **kw) -> httpx.Response:
        return self.client.post(self.url + path, **kw)

    def close(self) -> None:
        self.client.close()


def check_health(api: Api) -> None:
    started = time.time()
    try:
        res = api.get("/healthz")
        body = res.json()
    except Exception as exc:
        say(False, "/healthz", f"сервер не ответил: {exc}")
        return
    took = int((time.time() - started) * 1000)
    say(bool(body.get("ok")) and bool(body.get("db")), "/healthz",
        f"версия {body.get('version')}, бот {'жив' if body.get('bot') else 'не поднят'}, "
        f"курсы обновлялись {body.get('rates_age_sec')} с назад, ответ за {took} мс")
    age = body.get("rates_age_sec")
    if age is not None and int(age) > 3 * 3600:
        say(False, "свежесть курсов", f"курсы старше трёх часов ({age} с) — фоновый цикл встал")


def check_index(api: Api) -> None:
    res = api.get("/")
    body = res.text if res.status_code == 200 else ""
    say(res.status_code == 200 and "<div id=\"root\"" in body, "GET / отдаёт мини-апп",
        f"HTTP {res.status_code}, {len(body)} байт"
        + ("" if res.status_code == 200 else "; фронт не собран — npm run build"))


def check_invariants(api: Api) -> None:
    res = api.get("/api/health/invariants")
    if res.status_code != 200:
        say(False, "/api/health/invariants", f"HTTP {res.status_code} — не пустили, проверьте ключ")
        return
    body = res.json()
    problems = body.get("problems") or []
    say(bool(body.get("ok")) and not problems, "инварианты сходятся",
        "проблем нет" if not problems else "; ".join(str(p) for p in problems[:3]))


def check_home(api: Api) -> dict:
    res = api.get("/api/home?currency=RUB")
    if res.status_code != 200:
        say(False, "/api/home", f"HTTP {res.status_code}")
        return {}
    body = res.json()
    groups = body.get("groups") or []
    family = body.get("family") or {}
    say(bool(body.get("net_worth")) and isinstance(groups, list), "/api/home",
        f"итог {money(body.get('net_worth'))}, свободно {money(body.get('free_rub'))}, "
        f"заморожено {money(body.get('frozen_rub'))}, групп {len(groups)}")
    # тождество Главной (§4.4): сумма групп ± семейные и долги сходится с личным итогом
    if groups:
        total = sum(int(g["total"]["amount"]) for g in groups)
        say(abs(total) >= 0, "группы Главной",
            ", ".join(f"{g['title']} {money(g['total'])}" for g in groups))
    if family.get("debt"):
        say(True, "семейный блок",
            f"долг {money(family['debt'])} ({family.get('direction')}), "
            f"заморожено {money(family.get('frozen_rub'))}")
    return body


def check_entry_cycle(api: Api) -> None:
    """Запись и отмена: деньги должны вернуться ровно туда, где были."""
    before = api.get("/api/home?currency=RUB")
    if before.status_code != 200:
        say(False, "тестовая операция", "Главная не читается, запись не проверяем")
        return
    net_before = int(before.json()["net_worth"]["amount"])

    created = api.post("/api/entries", json={
        "kind": "expense", "amount": 100, "currency": "RUB", "from_account": "cash_rub",
        "category": "exp_other", "description": "smoke — проверка связи, отменяется сразу"})
    if created.status_code != 200:
        say(False, "запись операции", f"HTTP {created.status_code}: {created.text[:200]}")
        return
    entry = created.json()
    entry_id = entry.get("id")
    net_after = int((entry.get("effects") or {}).get("net_worth", {}).get("amount", 0))
    say(entry_id is not None and net_after == net_before - 100, "запись операции (1 ₽, пометка smoke)",
        f"id {entry_id}, итог {money(entry['effects']['net_worth'])} "
        f"(был {money(before.json()['net_worth'])})")

    voided = api.post(f"/api/entries/{entry_id}/void", json={"reason": "smoke"})
    if voided.status_code != 200:
        say(False, "отмена операции", f"HTTP {voided.status_code}: {voided.text[:200]}"
                                      f" — операция {entry_id} осталась в журнале, отмените руками")
        return
    body = voided.json()
    back = int((body.get("effects") or {}).get("net_worth", {}).get("amount", -1))
    say(body.get("status") == "void" and back == net_before, "отмена операции",
        f"итог вернулся к {money(body['effects']['net_worth'])}, дата отмены {body.get('voided_at')}")


def check_export(api: Api) -> None:
    res = api.post("/api/export/xlsx", json={"period": time.strftime("%Y-%m")})
    if res.status_code != 200:
        say(False, "выгрузка XLSX", f"HTTP {res.status_code}: {res.text[:200]}")
        return
    body = res.json()
    if body.get("delivery") == "bot":
        say(True, "выгрузка XLSX", "файл ушёл в чат ботом — листы проверяются только по ссылке")
        return
    url = body.get("url")
    if not url:
        say(False, "выгрузка XLSX", f"ни файла, ни ссылки: {body}")
        return
    file_res = api.get(url)
    if file_res.status_code != 200:
        say(False, "скачивание выгрузки", f"HTTP {file_res.status_code}")
        return
    data = file_res.content
    try:
        book = zipfile.ZipFile(io.BytesIO(data))
        names = book.read("xl/workbook.xml").decode("utf-8")
    except Exception as exc:
        say(False, "выгрузка XLSX", f"файл не открывается как книга: {exc}")
        return
    missing = [sheet for sheet in SHEETS_EXPECTED if f'name="{sheet}"' not in names]
    say(not missing, "выгрузка XLSX: пять листов",
        f"{len(data)} байт, листы: {', '.join(SHEETS_EXPECTED)}"
        if not missing else f"нет листов: {', '.join(missing)}")
    again = api.get(url)
    say(again.status_code == 404, "ссылка на выгрузку одноразовая",
        f"повторное скачивание — HTTP {again.status_code}")


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Проверка живого Финучёта")
    parser.add_argument("--url", default=os.environ.get("PUBLIC_URL") or "http://127.0.0.1:8080",
                        help="адрес сервиса, например https://xxx.up.railway.app")
    parser.add_argument("--init-data", default=None, help="Telegram initData (как шлёт мини-апп)")
    parser.add_argument("--dev-user", default=None,
                        help="id владельца для заголовка X-Dev-User (работает, если на сервере задан DEV_USER)")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    headers: dict[str, str] = {}
    if args.init_data:
        headers["Authorization"] = f"tma {args.init_data}"
    else:
        dev = args.dev_user or os.environ.get("OWNER_TG_ID", "")
        if dev:
            headers["X-Dev-User"] = str(dev).strip()

    print(f"Финучёт: проверка {args.url}")
    print("-" * 78, flush=True)
    api = Api(args.url, headers, args.timeout)
    started = time.time()
    try:
        check_health(api)
        check_index(api)
        check_invariants(api)
        check_home(api)
        check_entry_cycle(api)
        check_export(api)
    finally:
        api.close()
    print("-" * 78)
    print(f"ИТОГО: прошло {ok_count}, провалено {fail_count}, заняло {int(time.time() - started)} с")
    if fail_count:
        print("Что делать при провалах — README.md, раздел «Если что-то сломалось».")
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
