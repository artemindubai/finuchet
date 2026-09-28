# -*- coding: utf-8 -*-
"""Перенос заморозки в дирхамы (28.09): рубли, замороженные под семью и уже потраченные, закрываются
блоком дирхамов на личном счёте. Проводок нет — только транши и блок, всё пересчитывается по журналу."""
import pytest

from backend import ledger
from backend.contracts import LedgerError
from tests.conftest import base_state, post

RATE = 23_500_000


def take(amount, rate=RATE):
    return post(kind="family_withdrawal", amount=amount, currency="AED",
                from_account="mashreq_family", to_account="mashreq_personal",
                rate_e6=rate, rate_source="voice")


def repay(amount):
    return post(kind="family_repayment", amount=amount, currency="AED",
                from_account="mashreq_personal", to_account="mashreq_family")


def shortfall_state():
    """Рублей 155 400 ₽, заморожено 235 000 ₽ под 10 000 AED — не хватает 79 600 ₽."""
    base_state()
    take(1_000_000)
    home = ledger.balances()
    assert home["shortfall_rub"] == {"amount": 7_960_000, "currency": "RUB"}
    return home


def test_move_whole_shortfall_blocks_aed():
    before = shortfall_state()
    out = ledger.freeze_move()
    move = out["move"]
    assert move["rub_moved"]["amount"] == 7_960_000
    assert move["rub_left"] == {"amount": 338_723, "currency": "AED"}     # 79 600 / 23,5
    assert move["aed_taken"]["amount"] == 338_723
    home = ledger.balances()
    assert home["shortfall_rub"] is None
    assert home["free_rub"]["amount"] == 0
    assert home["frozen_rub"]["amount"] == 15_540_000
    assert home["frozen_aed"] == {"amount": 338_723, "currency": "AED"}
    assert home["free_aed"]["amount"] == 184_250 + 32_000 + 1_000_000 - 338_723
    assert home["family"]["frozen_aed"]["amount"] == 338_723
    assert home["net_worth"] == before["net_worth"]                         # проводок нет
    assert ledger.family_debt()["debt"]["amount"] == 1_000_000
    assert ledger.check_invariants() == []


def test_move_with_explicit_rate_and_amount():
    shortfall_state()
    move = ledger.freeze_move(rub_amount=2_350_000, rate_e6=23_500_000)["move"]
    assert move["rub_left"]["amount"] == 100_000                            # 23 500 ₽ = 1 000 AED
    assert ledger.balances()["shortfall_rub"]["amount"] == 7_960_000 - 2_350_000
    assert ledger.check_invariants() == []


def test_account_shows_aed_block_in_account_currency():
    shortfall_state()
    ledger.freeze_move()
    view = ledger.account_view("mashreq_personal")
    assert view["frozen"] == {"amount": 338_723, "currency": "AED"}
    tbank = ledger.account_view("tbank")
    assert tbank["frozen"]["currency"] == "RUB"


def test_repayment_unlocks_aed_first():
    shortfall_state()
    ledger.freeze_move()
    result = repay(50_000)
    assert result["effects"]["unlocked"][0]["unlocked"] == {"amount": 50_000, "currency": "AED"}
    home = ledger.balances()
    assert home["frozen_aed"]["amount"] == 338_723 - 50_000
    assert home["frozen_rub"]["amount"] == 15_540_000                       # рубли не тронуты
    assert ledger.check_invariants() == []
    repay(1_000_000 - 50_000)                                               # весь долг
    home = ledger.balances()
    assert home["frozen_aed"]["amount"] == 0 and home["frozen_rub"]["amount"] == 0
    assert ledger.check_invariants() == []


def test_void_move_restores_rub_freeze():
    shortfall_state()
    move_id = ledger.freeze_move()["move"]["id"]
    ledger.void_freeze_move(move_id, reason="тест")
    home = ledger.balances()
    assert home["frozen_aed"]["amount"] == 0
    assert home["shortfall_rub"]["amount"] == 7_960_000
    assert ledger.check_invariants() == []
    with pytest.raises(LedgerError):
        ledger.void_freeze_move(move_id)


def test_void_repayment_after_move_relocks():
    shortfall_state()
    ledger.freeze_move()
    entry_id = repay(50_000)["id"]
    ledger.void_entry(entry_id, actor="test")
    assert ledger.balances()["frozen_aed"]["amount"] == 338_723
    assert ledger.check_invariants() == []


def test_void_withdrawal_after_move_empties_block():
    base_state()
    first = take(1_000_000)
    ledger.freeze_move()
    ledger.void_entry(first["id"], actor="test")
    home = ledger.balances()
    assert home["frozen_aed"]["amount"] == 0 and home["frozen_rub"]["amount"] == 0
    assert ledger.check_invariants() == []


def test_nothing_to_move_and_bad_account():
    base_state()
    with pytest.raises(LedgerError) as err:
        ledger.freeze_move()
    assert err.value.code == "nothing_to_move"
    take(1_000_000)
    with pytest.raises(LedgerError):
        ledger.freeze_move(account="tbank")
    with pytest.raises(LedgerError):
        ledger.freeze_move(rub_amount=99_000_000)                           # больше, чем заморожено


def test_api_move_and_home(client):
    shortfall_state()
    res = client.post("/api/family/freeze_move", json={})
    assert res.status_code == 200, res.text
    move_id = res.json()["move"]["id"]
    home = client.get("/api/home").json()
    assert home["frozen_aed"]["amount"] == 338_723
    assert home["shortfall_rub"] is None
    acc = client.get("/api/accounts/mashreq_personal").json()
    assert any(t.get("kind") == "freeze_move" for t in acc["tranches"])
    assert client.get("/api/family/freeze_moves").json()["items"][0]["id"] == move_id
    res = client.post(f"/api/family/freeze_move/{move_id}/void", json={"reason": "тест"})
    assert res.status_code == 200, res.text
    assert client.get("/api/home").json()["frozen_aed"]["amount"] == 0
