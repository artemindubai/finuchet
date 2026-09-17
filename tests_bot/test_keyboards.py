# -*- coding: utf-8 -*-
"""Кнопки: формат callback_data и предел 64 байта (ARCHITECTURE §7.1)."""
from __future__ import annotations

import pytest

from backend.bot import keyboards


def test_entry_buttons_shape():
    buttons = keyboards.entry_buttons(431)
    assert [b.label for b in buttons] == ["Отменить", "Поправить", "Открыть"]
    assert buttons[0].data == "f:u:431"
    assert buttons[1].data == "f:e:431"
    assert buttons[2].data is None
    assert buttons[2].web_app == "https://finuchet.example/#/entry/431"


def test_all_callbacks_fit_64_bytes():
    made = (
        keyboards.entry_buttons(999999)
        + keyboards.voided_buttons(999999)
        + keyboards.ambiguous_buttons(12345)
        + keyboards.align_buttons("scr_20260917_1")
        + keyboards.reconcile_batch_buttons("scr_20260917_1")
        + keyboards.clarify_buttons(7)
    )
    for button in made:
        if button.data:
            assert len(button.data.encode("utf-8")) <= 64, button.data


def test_batch_button_drops_when_too_long():
    short = keyboards.batch_buttons([501, 502])
    assert short[0].data == "f:U:501,502"
    long_ids = list(range(100000, 100020))
    buttons = keyboards.batch_buttons(long_ids)
    assert [b.label for b in buttons] == ["Открыть"]   # общая отмена не влезла — карточки по одной


def test_parse_cb_roundtrip():
    assert keyboards.parse_cb("f:s:11") == ("s", "11")
    assert keyboards.parse_cb("f:a:scr_20260917_1") == ("a", "scr_20260917_1")
    assert keyboards.parse_cb("garbage") is None
    assert keyboards.parse_cb("") is None


def test_cb_refuses_too_long_id():
    with pytest.raises(ValueError):
        keyboards.cb("a", "x" * 70)


def test_markup_has_no_parse_mode_and_builds():
    markup = keyboards.to_markup(keyboards.entry_buttons(431))
    assert markup is not None
    assert len(markup.inline_keyboard[0]) == 3
    assert keyboards.to_markup([]) is None
