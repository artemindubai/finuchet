# -*- coding: utf-8 -*-
"""Приёмка конвейера без Телеграма (ARCHITECTURE §10, ТЗ 11.1).

Гоняет фразы Артёма через настоящий разбор ИИ и, если ядро учёта уже собрано, через настоящую
запись во временную базу: печатает карточки, остатки и итог. Код возврата 0 только когда
все фразы разобраны как ожидалось и инварианты ядра сходятся.

    python -X utf8 tools\\offline_check.py                    — реальный ИИ, временная БД
    python -X utf8 tools\\offline_check.py --mock-llm         — без вызова ИИ (проверка ядра)
    python -X utf8 tools\\offline_check.py --audio voice.ogg  — плюс одно настоящее голосовое
    python -X utf8 tools\\offline_check.py --json out.json    — машинный отчёт

Ключи берутся из ACCESS.env; в вывод попадают только имена переменных.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "ACCESS.env")
except ImportError:  # pragma: no cover
    print("нет python-dotenv — переменные берём из окружения")

BOOL_FIELDS = {"freeze", "no_tax", "rate_named_by_voice"}
INT_FIELDS = {"amount", "amount_to", "rate", "operations"}


def read_phrases(path: Path) -> list[tuple[str, dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        phrase, _, tail = line.partition("|")
        expect: dict[str, Any] = {}
        for pair in tail.split():
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            if key in BOOL_FIELDS:
                expect[key] = value.lower() in ("1", "true", "да")
            elif key in INT_FIELDS:
                expect[key] = int(value)
            else:
                expect[key] = value
        items.append((phrase.strip(), expect))
    return items


def mock_answer(expect: dict[str, Any]) -> dict[str, Any]:
    """Ответ модели, собранный из ожиданий: --mock-llm не зависит от баланса ключей."""
    operation = op_template()
    for key, value in expect.items():
        if key == "operations":
            continue
        operation[key] = value
    return {"mode": "create", "needs_clarification": False, "clarification_question": None,
            "note": None, "operations": [operation]}


def op_template() -> dict[str, Any]:
    from backend.prompts.schemas import _OP_DEFAULTS

    return dict(_OP_DEFAULTS)


def check_operation(parsed: Any, expect: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for key, want in expect.items():
        if key == "operations":
            continue
        got = getattr(parsed, key, None)
        if key == "counterparty" and isinstance(got, str) and isinstance(want, str):
            if got.lower().startswith(want.lower()[:4]):
                continue
        if got != want:
            problems.append(f"{key}: ожидали {want!r}, получили {got!r}")
    return problems


async def run_check(args: argparse.Namespace) -> int:
    from backend import llm
    from backend.bot import cards
    from backend.pipeline import ledger_ref, text as pipeline

    phrases = read_phrases(Path(args.phrases))
    core = prepare_core(args)
    report: dict[str, Any] = {"phrases": [], "core": core, "ok": True,
                              "provider": llm.provider() if not args.mock_llm else "mock"}

    reference = llm.reference_text()
    hints = await pipeline.hints()
    total_ops = 0

    print(f"Разбор: {'заглушка' if args.mock_llm else llm.provider()}, "
          f"ядро: {'подключено' if core else 'нет (останавливаемся на ParsedOperation)'}")
    print("-" * 78)

    for phrase, expect in phrases:
        started = time.monotonic()
        row: dict[str, Any] = {"phrase": phrase, "problems": []}
        try:
            data = mock_answer(expect) if args.mock_llm else await llm.parse_phrase(
                phrase, today=hints["today"], reference=reference, hints=hints)
        except Exception as exc:
            row["problems"].append(f"разбор упал: {exc}")
            report["phrases"].append(row)
            report["ok"] = False
            print(f"ОШИБКА  {phrase}\n        {exc}")
            continue

        operations = data.get("operations") or []
        row["operations"] = len(operations)
        if expect.get("operations") and len(operations) != expect["operations"]:
            row["problems"].append(f"операций: ожидали {expect['operations']}, вышло {len(operations)}")
        if not operations:
            row["problems"].append(f"модель просит уточнение: {data.get('clarification_question')}")
        else:
            try:
                parsed = pipeline.to_parsed(operations[0], source="text", raw_input=phrase)
                row["problems"].extend(check_operation(parsed, expect))
                row["parsed"] = {"kind": parsed.kind, "amount": parsed.amount,
                                 "currency": parsed.currency, "from_account": parsed.from_account,
                                 "to_account": parsed.to_account, "category": parsed.category,
                                 "income_source": parsed.income_source,
                                 "counterparty": parsed.counterparty}
                total_ops += len(operations)
                if core:
                    for operation in operations:
                        result = await ledger_ref.call(
                            "post_operation", pipeline.to_parsed(operation, source="text", raw_input=phrase),
                            actor="offline_check")
                        row.setdefault("cards", []).append(cards.card_for_entry(result))
            except Exception as exc:
                row["problems"].append(f"запись не прошла: {exc}")

        row["took_sec"] = round(time.monotonic() - started, 2)
        report["phrases"].append(row)
        mark = "ОК     " if not row["problems"] else "НЕ ТО  "
        if row["problems"]:
            report["ok"] = False
        print(f"{mark} {phrase}")
        if row.get("parsed"):
            p = row["parsed"]
            print(f"        {p['kind']} {p['amount']} {p['currency']} "
                  f"из={p['from_account']} в={p['to_account']} "
                  f"кат={p['category'] or p['income_source'] or '-'}")
        for problem in row["problems"]:
            print(f"        {problem}")
        for card in row.get("cards", []):
            print("        " + card.replace("\n", "\n        "))

    if args.audio:
        report["audio"] = await check_audio(args.audio)
        print("-" * 78)
        print(f"Аудио: {report['audio']}")
        if not report["audio"].get("text"):
            report["ok"] = False

    broken: list[str] = []
    if core and ledger_ref.has("check_invariants"):
        broken = await ledger_ref.call("check_invariants") or []
    report["invariants_broken"] = broken
    if broken:
        report["ok"] = False

    print("-" * 78)
    print(f"ИТОГО: операций {total_ops}, инвариантов нарушено {len(broken)}")
    for line in broken:
        print(f"  нарушен инвариант: {line}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"машинный отчёт: {args.json}")

    return 0 if report["ok"] else 1


def prepare_core(args: argparse.Namespace) -> bool:
    """Поднимает локальную базу, если ядро уже собрано. Нет ядра — работаем до ParsedOperation."""
    from backend.pipeline import ledger_ref

    fresh = args.db is None
    db_path = args.db or str(Path(tempfile.gettempdir()) / "finuchet_offline.db")
    if fresh:  # без --db прогон начинается с чистой базы, иначе остатки едут из прошлого запуска
        for suffix in ("", "-wal", "-shm"):
            Path(db_path + suffix).unlink(missing_ok=True)
    os.environ.setdefault("TZ", "Asia/Dubai")
    os.environ["DB_PATH"] = db_path
    try:
        from backend import db as core_db

        if hasattr(core_db, "ensure_dirs"):
            core_db.ensure_dirs()
        core_db.init()
    except Exception as exc:
        print(f"база ядра не поднялась ({exc})")
    return ledger_ref.has("post_operation")


async def check_audio(path: str) -> dict[str, Any]:
    from backend.stt import router as stt_router

    blob = Path(path).read_bytes()
    text, provider = await stt_router.transcribe(file_bytes=blob, chat_id=None, duration=None)
    return {"provider": provider, "text": text}


def main() -> int:
    parser = argparse.ArgumentParser(description="Приёмка разбора фраз без Телеграма")
    parser.add_argument("--phrases", default=str(ROOT / "tools" / "phrases.txt"))
    parser.add_argument("--db", default=None, help="путь к базе; по умолчанию временный файл")
    parser.add_argument("--mock-llm", action="store_true", help="без вызова модели")
    parser.add_argument("--audio", default=None, help="файл .ogg для проверки расшифровки")
    parser.add_argument("--json", default=None, help="куда положить машинный отчёт")
    args = parser.parse_args()
    return asyncio.run(run_check(args))


if __name__ == "__main__":
    raise SystemExit(main())
