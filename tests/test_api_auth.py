# -*- coding: utf-8 -*-
"""Авторизация мини-аппа: initData и белый список одного ID (ARCHITECTURE §5.1)."""
import hashlib
import hmac
import json
from urllib.parse import urlencode

from backend.tz import utc_now
from tests.conftest import OWNER


def init_data(user_id: int, token: str = "test-token") -> str:
    payload = {"auth_date": str(utc_now()),
               "query_id": "AAE",
               "user": json.dumps({"id": user_id, "first_name": "Артём"}, ensure_ascii=False)}
    check = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


def test_foreign_id_forbidden(client):
    response = client.get("/api/home", headers={"X-Dev-User": "111222333"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_missing_auth(client):
    response = client.get("/api/home", headers={"X-Dev-User": "", "Authorization": ""})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_init_data_hmac(client):
    good = client.get("/api/home", headers={"X-Dev-User": "",
                                            "Authorization": f"tma {init_data(int(OWNER))}"})
    assert good.status_code == 200

    stranger = client.get("/api/home", headers={"X-Dev-User": "",
                                                "Authorization": f"tma {init_data(111222333)}"})
    assert stranger.status_code == 403

    broken = init_data(int(OWNER))[:-4] + "0000"
    bad = client.get("/api/home", headers={"X-Dev-User": "", "Authorization": f"tma {broken}"})
    assert bad.status_code == 401


def test_healthz_is_open(client):
    response = client.get("/healthz", headers={"X-Dev-User": ""})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["db"] is True
    assert body["bot"] is False
