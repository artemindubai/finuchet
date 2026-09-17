# -*- coding: utf-8 -*-
"""Адверсариальные проверки HTTP-слоя: авторизация, мусор во входе, коды ошибок (§5.1, §5.2)."""
import json

import pytest
from fastapi.testclient import TestClient

from backend import db, ledger
from tests.conftest import OWNER, base_state, post


@pytest.fixture
def raw_client(monkeypatch):
    """Клиент БЕЗ заголовка X-Dev-User — чтобы проверять настоящий путь initData."""
    import asyncio
    from backend import app as app_module

    async def no_rates():
        await asyncio.sleep(3600)

    monkeypatch.setattr(app_module, "rates_loop", no_rates)
    with TestClient(app_module.app) as test_client:
        yield test_client


def test_foreign_id_is_403(client):
    response = client.get("/api/home", headers={"X-Dev-User": "999999"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_no_auth_headers_is_401(raw_client):
    response = raw_client.get("/api/home")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_init_data_without_hash_is_401(raw_client):
    init = f"auth_date=1700000000&user={json.dumps({'id': int(OWNER)})}"
    response = raw_client.get("/api/home", headers={"Authorization": f"tma {init}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_init_data_with_forged_hash_is_401(raw_client):
    init = (f"auth_date=1700000000&user={json.dumps({'id': int(OWNER)})}"
            "&hash=" + "0" * 64)
    response = raw_client.get("/api/home", headers={"Authorization": f"tma {init}"})
    assert response.status_code == 401


def test_broken_cursor_is_400_not_500(client):
    base_state()
    response = client.get("/api/entries", params={"cursor": "не-курсор-а-мусор"})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "bad_request"


def test_limit_out_of_range_is_client_error(client):
    base_state()
    for limit in (0, 1000, -5):
        response = client.get("/api/entries", params={"limit": limit})
        assert 400 <= response.status_code < 500, f"limit={limit} → {response.status_code}"
        assert response.status_code != 500


def test_bad_month_is_400_not_500(client):
    base_state()
    response = client.get("/api/analytics/month", params={"month": "2026-13"})
    assert response.status_code == 400, response.text
    response = client.get("/api/analytics/month", params={"month": "хрень"})
    assert response.status_code == 400, response.text


def test_zero_and_negative_amounts_rejected(client):
    base_state()
    for amount in (0, -4300):
        response = client.post("/api/entries", json={
            "kind": "expense", "amount": amount, "currency": "AED",
            "from_account": "mashreq_personal", "category": "exp_cafe"})
        assert response.status_code == 400, (amount, response.text)


def test_amount_as_string_is_accepted_or_rejected_cleanly(client):
    base_state()
    response = client.post("/api/entries", json={
        "kind": "expense", "amount": "4300", "currency": "AED",
        "from_account": "mashreq_personal", "category": "exp_cafe"})
    assert response.status_code in (200, 400), response.text
    if response.status_code == 200:
        assert response.json()["amount"] == {"amount": 4300, "currency": "AED"}


def test_fractional_amount_is_rejected(client):
    """Минорные единицы целые: 43,99 копейки — это ошибка ввода, а не 43."""
    base_state()
    response = client.post("/api/entries", json={
        "kind": "expense", "amount": 4300.99, "currency": "AED",
        "from_account": "mashreq_personal", "category": "exp_cafe"})
    assert response.status_code == 400, response.text


def test_unknown_account_is_400(client):
    base_state()
    response = client.post("/api/entries", json={
        "kind": "expense", "amount": 4300, "currency": "AED",
        "from_account": "нет-такого-счёта", "category": "exp_cafe"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_account"


def test_double_void_is_409(client):
    base_state()
    entry = post(kind="expense", amount=4_300, currency="AED",
                 from_account="mashreq_personal", category="exp_cafe")
    assert client.post(f"/api/entries/{entry['id']}/void").status_code == 200
    second = client.post(f"/api/entries/{entry['id']}/void")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "already_void"


def test_missing_entry_is_404(client):
    base_state()
    assert client.get("/api/entries/999999").status_code == 404
