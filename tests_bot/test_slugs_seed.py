# -*- coding: utf-8 -*-
"""Слаги категорий, источников и счетов везде одни и те же — как в seed.

Повод: фиксер фронта послал `POST /api/entries` с `category="exp_connect"` и получил
«Счёт не найден». Такого слага в коде не было ни разу — но проверять это глазами каждый раз
дорого, а цена ошибки — операция, которая не записалась.
"""
from __future__ import annotations

import re
from pathlib import Path

from backend.seed.accounts import ACCOUNTS, CATEGORIES, EQUITY, INCOME_SOURCES

ROOT = Path(__file__).resolve().parents[1]

SEED_SLUGS = {
    *(row[0] for row in ACCOUNTS),
    *(row[0] for row in CATEGORIES),
    *(row[0] for row in INCOME_SOURCES),
    *(row[0] for row in EQUITY),
}

# Слаги с узнаваемым префиксом: чужой ловится регуляркой, счета проверяются отдельно по refs.json
PREFIXED = re.compile(r"\b(?:exp|inc|eq)_[a-z][a-z_]*\b")

SOURCES = [
    ROOT / "backend" / "prompts" / "system_parse.md",
    ROOT / "backend" / "prompts" / "system_vision.md",
    ROOT / "backend" / "llm.py",
    ROOT / "tools" / "phrases.txt",
]


def _files() -> list[Path]:
    files = [p for p in SOURCES if p.exists()]
    front = ROOT / "frontend" / "src"
    if front.exists():
        files += [p for p in front.rglob("*") if p.suffix in (".json", ".ts", ".tsx")]
    return files


def test_categories_and_sources_match_seed():
    strangers: dict[str, list[str]] = {}
    for path in _files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for slug in set(PREFIXED.findall(text)):
            if slug not in SEED_SLUGS:
                strangers.setdefault(slug, []).append(str(path.relative_to(ROOT)))
    assert not strangers, f"слаги мимо seed: {strangers}"


def test_mock_refs_accounts_match_seed():
    """Моки фронта — те же счета, что заводит seed: иначе ручной ввод бьётся о живой сервер."""
    import json

    refs_path = ROOT / "frontend" / "src" / "mocks" / "refs.json"
    if not refs_path.exists():
        return
    refs = json.loads(refs_path.read_text(encoding="utf-8"))
    for key in ("accounts", "categories", "income_sources"):
        for item in refs.get(key) or []:
            assert item["slug"] in SEED_SLUGS, f"{key}: {item['slug']} нет в seed"
