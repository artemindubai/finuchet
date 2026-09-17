# -*- coding: utf-8 -*-
"""Остальные эндпоинты: справочники, курсы, выгрузка, сверка (ARCHITECTURE §5.11–5.13)."""
from tests.conftest import base_state, post


def test_refs_crud(client):
    base_state()
    created = client.post("/api/categories", json={"name": "Спорт", "icon": "sport",
                                                   "color": "#3BA55D"}).json()
    sport = next(item for item in created["categories"] if item["name"] == "Спорт")
    assert sport["slug"].startswith("exp_") and sport["color"] == "#3BA55D"

    patched = client.patch(f"/api/categories/{sport['id']}", json={"color": "#112233"}).json()
    assert next(i for i in patched["categories"] if i["id"] == sport["id"])["color"] == "#112233"

    source = client.post("/api/income-sources", json={"name": "Консультации", "tax_rate_bp": 600,
                                                      "color": "#5B6CD9",
                                                      "icon": "briefcase"}).json()
    consult = next(i for i in source["income_sources"] if i["name"] == "Консультации")
    assert consult["tax_rate_bp"] == 600 and consult["tax_account_id"]

    account = client.post("/api/accounts", json={"name": "Wio Bank", "type": "asset_personal",
                                                 "currency": "AED", "is_money": True,
                                                 "group_key": "AED", "icon": "bank"}).json()
    wio = next(i for i in account["accounts"] if i["name"] == "Wio Bank")
    assert wio["slug"] == "wio_bank" and wio["currency"] == "AED"

    archived = client.post(f"/api/accounts/{wio['id']}/archive").json()
    assert next(i for i in archived["accounts"] if i["id"] == wio["id"])["archived"] is True
    assert archived["warnings"] == []

    # тип и валюту счёта с проводками менять нельзя
    tbank = next(i for i in archived["accounts"] if i["slug"] == "tbank")
    denied = client.patch(f"/api/accounts/{tbank['id']}", json={"currency": "AED"})
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "bad_request"


def test_archive_with_balance_warns(client):
    base_state()
    refs = client.get("/api/refs").json()
    sber = next(i for i in refs["accounts"] if i["slug"] == "sber")
    body = client.post(f"/api/accounts/{sber['id']}/archive").json()
    assert [w["code"] for w in body["warnings"]] == ["archived_with_balance"]


def test_rates_endpoints(client):
    body = client.get("/api/rates").json()
    assert set(body) == {"at", "rates", "markup_rub_per_aed_e6"}
    pairs = {item["pair"]: item for item in body["rates"]}
    assert pairs["AED/RUB"]["rate_e6"] == 23_450_000
    assert pairs["AED/RUB"]["stale"] is False
    assert body["markup_rub_per_aed_e6"] == 2_000_000

    at_date = client.get("/api/rates/at?pair=AED/RUB&date=2026-09-17").json()
    assert at_date["pair"] == "AED/RUB" and at_date["rate_e6"] == 23_450_000


def test_export_link_and_download(client):
    base_state()
    post(kind="expense", amount=235_000, currency="RUB", from_account="tbank",
         category="exp_groceries")
    from backend.tz import today_dubai
    response = client.post("/api/export/xlsx", json={"period": today_dubai()[:7]}).json()
    assert response["ok"] is True
    assert response["delivery"] == "link"          # бот в тестах не поднят
    url = response["url"]

    downloaded = client.get(url)
    assert downloaded.status_code == 200
    assert downloaded.content[:2] == b"PK"         # это .xlsx
    assert client.get(url).status_code == 404      # токен одноразовый


def test_inbox_endpoints(client):
    base_state()
    post(kind="expense", amount=235_000, currency="RUB", from_account="tbank",
         category="exp_groceries", op_date="2026-09-16")
    from backend.contracts import ScreenBatch, ScreenRow
    from backend.ledger.reconcile import reconcile
    batch = reconcile(ScreenBatch(account="tbank", currency="RUB", balance=12_900_000, rows=[
        ScreenRow(amount=-235_000, currency="RUB", op_date="2026-09-16", raw_text="ЯНДЕКС ЕДА"),
        ScreenRow(amount=-65_000, currency="RUB", op_date="2026-09-16", raw_text="ПЯТЁРОЧКА"),
    ]))
    listing = client.get("/api/inbox").json()
    assert listing["batches"][0]["pending"] == 1
    assert listing["batches"][0]["balance_check"]["diff"]["amount"] == -65_000

    new_id = batch["new"][0]["id"]
    resolved = client.post(f"/api/inbox/{new_id}/resolve",
                           json={"decision": "new", "category": "exp_groceries"}).json()
    assert resolved["applied"][0]["status"] == "accepted"

    aligned = client.post(f"/api/inbox/{batch['batch_id']}/align", json={}).json()
    assert [w["code"] for w in aligned["warnings"]] == ["already_aligned"]


def test_opening_balances_endpoint(client):
    response = client.post("/api/opening-balances", json={
        "op_date": "2026-09-17",
        "items": [{"account": "tbank", "amount": 13_200_000, "currency": "RUB"},
                  {"account": "mashreq_family", "amount": 850_000, "currency": "AED"}]}).json()
    assert [item["account"] for item in response["created"]] == ["tbank", "mashreq_family"]
    home = client.get("/api/home").json()
    assert home["net_worth"]["amount"] == 13_200_000

    denied = client.post("/api/opening-balances", json={
        "items": [{"account": "family_fund", "amount": 100, "currency": "AED"}]})
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "opening_balance_not_allowed"


def test_goals_and_limits_endpoints(client):
    base_state()
    goal = client.post("/api/goals", json={"name": "Виза", "target": 900_000,
                                           "currency": "AED", "due_date": "2026-12-01"}).json()
    allocated = client.post(f"/api/goals/{goal['id']}/allocate",
                            json={"amount": 320_000, "currency": "AED",
                                  "op_date": "2026-09-10", "note": "отложил"}).json()
    assert allocated["saved"] == {"amount": 320_000, "currency": "AED"}
    assert client.get("/api/goals").json()["items"][0]["progress_bp"] == 3556

    refs = client.get("/api/refs").json()
    cafe = next(i for i in refs["categories"] if i["slug"] == "exp_cafe")
    limits = client.put(f"/api/limits/{cafe['id']}", json={"amount": 1_500_000,
                                                           "currency": "RUB"}).json()
    assert limits["items"][0]["limit"] == {"amount": 1_500_000, "currency": "RUB"}
    assert client.delete(f"/api/limits/{cafe['id']}").json()["items"] == []


def test_unknown_api_path_is_404(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_root_without_frontend(client):
    response = client.get("/")
    assert response.status_code in (200, 503)
    if response.status_code == 503:
        assert response.json()["error"]["code"] == "frontend_not_built"
