# -*- coding: utf-8 -*-
"""Кнопки под карточками (ARCHITECTURE §7.1).

Формат callback_data — `f:<буква>:<id>`, не длиннее 64 байт. «Открыть» — не callback, а web_app
на адрес мини-аппа с хеш-маршрутом `#/entry/<id>` (§5.14).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

CALLBACK_LIMIT = 64


@dataclass(frozen=True)
class Button:
    label: str
    data: str | None = None
    web_app: str | None = None


def public_url() -> str:
    return (os.getenv("PUBLIC_URL") or "http://localhost:8080").rstrip("/")


def cb(letter: str, ident: object) -> str:
    data = f"f:{letter}:{ident}"
    if len(data.encode("utf-8")) > CALLBACK_LIMIT:
        raise ValueError(f"callback_data длиннее {CALLBACK_LIMIT} байт: {data[:20]}…")
    return data


def fits(letter: str, ident: object) -> bool:
    return len(f"f:{letter}:{ident}".encode("utf-8")) <= CALLBACK_LIMIT


def parse_cb(data: str) -> tuple[str, str] | None:
    """'f:u:431' → ('u', '431'). Чужой формат → None."""
    parts = (data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "f":
        return None
    return parts[1], parts[2]


def open_button(entry_id: object) -> Button:
    return Button("Открыть", web_app=f"{public_url()}/#/entry/{entry_id}")


def entry_buttons(entry_id: object) -> list[Button]:
    return [Button("Отменить", cb("u", entry_id)), Button("Поправить", cb("e", entry_id)), open_button(entry_id)]


def voided_buttons(entry_id: object) -> list[Button]:
    return [Button("Вернуть", cb("r", entry_id)), open_button(entry_id)]


def batch_buttons(entry_ids: list[int]) -> list[Button]:
    """Пачка операций из одной фразы: общая отмена, если влезает в 64 байта (§7.2)."""
    ids = ",".join(str(i) for i in entry_ids)
    buttons: list[Button] = []
    if entry_ids and fits("U", ids):
        buttons.append(Button("Отменить всё", cb("U", ids)))
    if entry_ids:
        buttons.append(open_button(entry_ids[-1]))
    return buttons


def reconcile_batch_buttons(batch_id: str) -> list[Button]:
    return [Button("Занести новые", cb("N", batch_id)), Button("Разобрать по одной", cb("D", batch_id))]


def ambiguous_buttons(inbox_id: object) -> list[Button]:
    return [Button("Это она", cb("s", inbox_id)), Button("Новая", cb("n", inbox_id)),
            Button("Пропустить", cb("k", inbox_id))]


def align_buttons(batch_id: str) -> list[Button]:
    return [Button("Выровнять", cb("a", batch_id))]


def clarify_buttons(pending_id: object = 0) -> list[Button]:
    return [Button("Отмена", cb("c", pending_id))]


def to_markup(buttons: list[Button]):
    """Список кнопок → aiogram-клавиатура. Пусто → None (клавиатуры нет)."""
    if not buttons:
        return None
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    row = []
    for b in buttons:
        if b.web_app:
            row.append(InlineKeyboardButton(text=b.label, web_app=WebAppInfo(url=b.web_app)))
        else:
            row.append(InlineKeyboardButton(text=b.label, callback_data=b.data))
    return InlineKeyboardMarkup(inline_keyboard=[row])
