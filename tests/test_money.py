# -*- coding: utf-8 -*-
"""Деньги: целочисленное округление и пересчёт (ARCHITECTURE §4.4)."""
from backend.money import convert, fmt_amount, round_half_up


def test_round_half_up_symmetric():
    assert round_half_up(5, 10) == 1
    assert round_half_up(-5, 10) == -1
    assert round_half_up(4, 10) == 0
    assert round_half_up(-4, 10) == 0
    assert round_half_up(15, 10) == 2
    assert round_half_up(-15, 10) == -2
    assert round_half_up(0, 10) == 0
    for value in range(-50, 51):
        assert round_half_up(value, 7) == -round_half_up(-value, 7)


def test_round_half_up_generic_denominator():
    # налог считается не по 1e6, а по 10 000 базисных пунктов
    assert round_half_up(1_234_567 * 600, 10_000) == 74_074
    assert round_half_up(9_000_000 * 600, 10_000) == 540_000
    assert round_half_up(184_250 * 23_450_000, 1_000_000) == 4_320_663


def test_convert_e6():
    snapshot = {"rub_per_aed_e6": 23_450_000, "rub_per_usd_e6": 84_173_200,
                "rub_per_usdt_e6": 97_150_000}
    assert convert(184_250, "AED", "RUB", snapshot=snapshot) == 4_320_663
    assert convert(22_291_642, "RUB", "USD", snapshot=snapshot) == 264_831
    assert convert(41_025, "USDT", "RUB", snapshot=snapshot) == 3_985_579
    # цепочка туда-обратно не теряет больше копейки
    there = convert(1_000_000, "RUB", "AED", snapshot=snapshot)
    back = convert(there, "AED", "RUB", snapshot=snapshot)
    assert abs(back - 1_000_000) <= 24
    assert convert(500, "RUB", "RUB", snapshot=snapshot) == 500


def test_format_matches_cards():
    assert fmt_amount(184_250, "AED") == "1 842,50 AED"
    assert fmt_amount(13_200_000, "RUB") == "132 000 ₽"
    assert fmt_amount(41_025, "USDT") == "410,25 USDT"
