# -*- coding: utf-8 -*-
"""Контракт API: формы ответов совпадают с примерами ARCHITECTURE §5."""
from tests.conftest import base_state, post

MONEY_KEYS = {"amount", "currency"}
ACCOUNT_KEYS = {"id", "slug", "name", "type", "role", "currency", "icon", "balance", "natural",
                "in_view", "frozen", "archived"}
ENTRY_SHORT_KEYS = {"id", "kind", "direction", "amount", "amount_in_view", "title", "subtitle",
                    "category_id", "icon", "color", "version", "op_date", "created_at", "status",
                    "source", "description", "counterparty", "project"}
EFFECTS_KEYS = {"accounts", "net_worth", "free_rub", "frozen_rub", "family_debt",
                "family_direction", "tranche", "released"}


def is_money(value) -> bool:
    return isinstance(value, dict) and set(value) == MONEY_KEYS and isinstance(value["amount"], int)


def prepare():
    base_state()
    post(kind="expense", amount=4_300, currency="AED", from_account="mashreq_personal",
         category="exp_cafe", description="обед в кафе")
    post(kind="income", amount=9_000_000, currency="RUB", to_account="tbank",
         income_source="inc_projects", project="Альфа")
    post(kind="family_withdrawal", amount=50_000, currency="AED", from_account="mashreq_family",
         to_account="mashreq_personal", rate_e6=24_500_000, rate_source="voice")


def test_home_shape(client):
    prepare()
    body = client.get("/api/home?currency=RUB").json()
    assert set(body) == {"currency", "as_of", "net_worth", "free_rub", "frozen_rub", "groups",
                         "totals_by_view", "family", "upcoming", "recent", "month", "rates",
                         "warnings", "my_money", "shortfall_rub", "hidden"}
    assert is_money(body["my_money"])
    assert set(body["hidden"]) == {"accounts", "total"}
    assert body["currency"] == "RUB"
    assert all(is_money(body[key]) for key in ("net_worth", "free_rub", "frozen_rub"))

    for group in body["groups"]:
        assert set(group) == {"key", "title", "total", "accounts"}
        assert is_money(group["total"])
        assert group["total"]["amount"] == sum(a["in_view"]["amount"] for a in group["accounts"])
        for account in group["accounts"]:
            assert set(account) == ACCOUNT_KEYS
            assert account["role"] in ("asset", "liability")
            assert is_money(account["balance"]) and is_money(account["in_view"])
            assert account["frozen"] is None or is_money(account["frozen"])

    assert set(body["totals_by_view"]) == {"net_worth", "groups", "my_money"}
    assert set(body["totals_by_view"]["net_worth"]) == {"RUB", "USD", "AED"}
    assert set(body["family"]) == {"visible", "total", "accounts", "debt", "direction",
                                   "frozen_rub", "frozen_note", "today_repay_rub"}
    assert body["family"]["direction"] in ("i_owe", "family_owes")
    assert set(body["month"]) == {"month", "expense_total", "income_total", "top_categories"}
    assert set(body["rates"]) == {"at", "source", "rub_per_aed_e6", "rub_per_usd_e6",
                                  "rub_per_usdt_e6"}
    assert len(body["recent"]) <= 7
    for item in body["recent"]:
        assert set(item) == ENTRY_SHORT_KEYS
    assert body["warnings"] == []


def test_entry_full_shape(client):
    prepare()
    feed = client.get("/api/entries").json()
    withdrawal = next(item for item in feed["items"] if item["kind"] == "family_withdrawal")
    body = client.get(f"/api/entries/{withdrawal['id']}").json()
    assert ENTRY_SHORT_KEYS <= set(body)
    assert {"replaces_entry_id", "replaced_by_entry_id", "due_date", "raw_input", "confidence",
            "postings", "rate", "rates_snapshot", "tranche", "versions", "warnings"} <= set(body)
    for posting in body["postings"]:
        assert set(posting) == {"seq", "account_id", "account_slug", "account_name", "side",
                                "amount", "counterparty", "project"}
        assert posting["side"] in ("debit", "credit")
    assert set(body["tranche"]) == {"id", "entry_id", "op_date", "aed_taken", "aed_left",
                                    "rub_frozen", "rub_left", "rate_e6", "rate_source",
                                    "account_id", "account_name", "status", "label"}
    assert body["rate"]["pair"] == "AED/RUB"
    assert body["versions"][0]["version"] == 1


def test_entries_pagination_cursor(client):
    base_state()
    for index in range(12):
        post(kind="expense", amount=1_000 + index, currency="RUB", from_account="tbank",
             category="exp_cafe", op_date="2026-09-1%d" % (index % 10))
    first = client.get("/api/entries?limit=5").json()
    assert len(first["items"]) == 5 and first["has_more"] is True
    assert first["next_cursor"]

    second = client.get(f"/api/entries?limit=5&cursor={first['next_cursor']}").json()
    assert len(second["items"]) == 5
    ids_first = [item["id"] for item in first["items"]]
    ids_second = [item["id"] for item in second["items"]]
    assert not set(ids_first) & set(ids_second)

    third = client.get(f"/api/entries?limit=20&cursor={second['next_cursor']}").json()
    all_ids = ids_first + ids_second + [item["id"] for item in third["items"]]
    assert len(all_ids) == len(set(all_ids))
    assert len(all_ids) == first["total"]
    assert third["has_more"] is False and third["next_cursor"] is None


def test_entries_summary_first_page_only(client):
    prepare()
    first = client.get("/api/entries?limit=2").json()
    assert "summary" in first
    summary = first["summary"]
    assert set(summary) == {"currency", "out", "in", "out_breakdown", "in_breakdown"}
    assert sum(item["share_bp"] for item in summary["out_breakdown"]) == 10_000
    assert sum(item["share_bp"] for item in summary["in_breakdown"]) == 10_000

    if first["next_cursor"]:
        nxt = client.get(f"/api/entries?limit=2&cursor={first['next_cursor']}").json()
        assert "summary" not in nxt

    assert set(first["days"][0]) == {"date", "title", "total_out", "total_in", "ids"}


def test_effects_shape_is_single(client):
    prepare()
    created = client.post("/api/entries", json={
        "kind": "expense", "amount": 4_300, "currency": "AED",
        "from_account": "mashreq_personal", "category": "exp_cafe"}).json()
    assert set(created["effects"]) == EFFECTS_KEYS
    assert created["source"] == "manual"
    entry_id = created["id"]

    amended = client.post(f"/api/entries/{entry_id}/amend", json={"amount": 3_400}).json()
    assert set(amended["effects"]) == EFFECTS_KEYS
    voided = client.post(f"/api/entries/{amended['id']}/void", json={"reason": "ошибся"}).json()
    assert set(voided["effects"]) == EFFECTS_KEYS
    restored = client.post(f"/api/entries/{amended['id']}/unvoid").json()
    assert set(restored["effects"]) == EFFECTS_KEYS

    plan = client.post("/api/calendar", json={"title": "Универ", "amount": 1_200_000,
                                              "currency": "RUB", "repeat": "quarterly",
                                              "next_date": "2026-10-10", "account": "tbank",
                                              "category": "exp_edu"}).json()
    paid = client.post(f"/api/calendar/{plan['id']}/paid", json={"op_date": "2026-10-10"}).json()
    assert set(paid["effects"]) == EFFECTS_KEYS
    assert "planned" in paid

    for account in created["effects"]["accounts"]:
        assert set(account) == {"id", "slug", "name", "role", "balance", "natural", "in_view",
                                "frozen", "balances_by_currency", "by_counterparty"}
        # вектор по валютам — только у мультивалютных счетов (currency в БД пуст)
        if account["slug"] == "mashreq_personal":
            assert account["balances_by_currency"] is None


def test_effects_debt_account_has_currencies_and_person(client):
    """Журнал 21: карточка долга печатает итог по человеку в валюте операции, а не в рублях."""
    prepare()
    post(kind="loan_given", amount=30_000, currency="AED", from_account="mashreq_personal",
         counterparty="Маша")
    created = client.post("/api/entries", json={
        "kind": "loan_given", "amount": 20_000, "currency": "AED",
        "from_account": "mashreq_personal", "counterparty": "Маша"}).json()
    debt = next(a for a in created["effects"]["accounts"] if a["slug"] == "receivable")
    assert debt["balances_by_currency"] == [{"amount": 50_000, "currency": "AED"}]
    masha = next(p for p in debt["by_counterparty"] if p["name"] == "Маша")
    assert masha["amounts"] == [{"amount": 50_000, "currency": "AED"}]

    from backend.bot.cards import card_for_entry
    assert "Мне должны: Маша 500 AED" in card_for_entry(created)


def test_entry_full_has_voided_at(client):
    """Журнал 26: карточке отменённой операции нужна дата отмены, а не дата операции."""
    prepare()
    created = client.post("/api/entries", json={
        "kind": "expense", "amount": 4_300, "currency": "AED",
        "from_account": "mashreq_personal", "category": "exp_cafe"}).json()
    assert created["voided_at"] is None and created["void_reason"] is None
    voided = client.post(f"/api/entries/{created['id']}/void", json={"reason": "ошибся"}).json()
    assert voided["voided_at"] and voided["voided_at"].endswith("Z")
    assert voided["void_reason"] == "ошибся"
    assert client.get(f"/api/entries/{created['id']}").json()["voided_at"] == voided["voided_at"]


def test_debts_by_currency(client):
    """Остаток мультивалютных receivable/payable вектором по валютам (§5.8, журнал 21)."""
    prepare()
    post(kind="loan_given", amount=30_000, currency="AED", from_account="mashreq_personal",
         counterparty="Маша")
    post(kind="loan_taken", amount=500_000, currency="RUB", to_account="tbank",
         counterparty="Костя")
    body = client.get("/api/debts").json()
    assert body["owed_to_me_by_currency"] == [{"amount": 30_000, "currency": "AED"}]
    assert body["i_owe_by_currency"] == [{"amount": 500_000, "currency": "RUB"}]


def test_inbox_batch_bridge():
    """Мост бота: кнопка «Занести новые» берёт id строк пачки через inbox_batch (просьба B №3)."""
    from backend.contracts import ScreenBatch, ScreenRow
    from backend.ledger import bot_bridge
    import importlib
    # в backend.ledger.__init__ имя reconcile занято функцией — модуль берём явно
    reconcile_mod = importlib.import_module("backend.ledger.reconcile")
    base_state()
    batch = ScreenBatch(account="tbank", currency="RUB",
                        rows=[ScreenRow(amount=-235_000, currency="RUB", op_date="2026-09-16",
                                        raw_text="ЯНДЕКС ЕДА")])
    batch_id = reconcile_mod.reconcile(batch)["batch_id"]
    one = bot_bridge.inbox_batch(batch_id)
    assert one is not None and one["batch_id"] == batch_id
    assert [i["id"] for i in one["items"]] == [i["id"] for i in
                                               reconcile_mod.inbox(batch_id)["batches"][0]["items"]]
    assert bot_bridge.inbox_batch("нет такой пачки") is None


def test_refs_and_settings_shape(client):
    prepare()
    refs = client.get("/api/refs").json()
    assert set(refs) == {"accounts", "categories", "income_sources", "counterparties",
                         "currencies", "kinds"}
    assert len(refs["kinds"]) == 17
    assert refs["currencies"] == ["RUB", "AED", "USDT", "USD"]
    assert set(refs["categories"][0]) == {"id", "slug", "name", "icon", "color", "sort", "archived"}

    settings = client.get("/api/settings").json()
    assert {"default_currency_view", "family_block_visible", "freeze_account",
            "rate_markup_rub_per_aed_e6", "mashreq_pdf_password_set", "stt_provider",
            "version", "db_size_bytes", "last_backup_at"} <= set(settings)
    assert "mashreq_pdf_password" not in settings

    updated = client.put("/api/settings", json={"family_block_visible": False}).json()
    assert updated["family_block_visible"] is False
    assert client.get("/api/home").json()["family"]["visible"] is False


def test_debts_and_account_shape(client):
    prepare()
    post(kind="loan_given", amount=30_000, currency="AED", from_account="mashreq_personal",
         counterparty="Маша")
    debts = client.get("/api/debts").json()
    assert set(debts) == {"owed_to_me", "i_owe", "tax", "credit_card", "family", "total_in_view",
                          "owed_to_me_by_currency", "i_owe_by_currency"}
    assert set(debts["owed_to_me"][0]) == {"counterparty_id", "name", "amounts", "in_view",
                                           "due_date", "since", "entry_ids"}
    assert set(debts["family"]) == {"debt", "direction", "frozen_rub", "today_repay_rub",
                                    "tranches"}

    account = client.get("/api/accounts/tbank").json()
    assert set(account) == {"account", "tranches", "entries", "month"}
    assert ACCOUNT_KEYS | {"free"} == set(account["account"])
    assert set(account["entries"]) == {"items", "days", "next_cursor", "has_more"}
    assert set(account["month"]) == {"in", "out"}
    assert account["tranches"][0]["label"].startswith("заблокировано в счёт взятых")


def test_analytics_shape(client):
    prepare()
    from backend.tz import today_dubai
    body = client.get(f"/api/analytics/month?month={today_dubai()[:7]}").json()
    assert {"month", "currency", "prev_month", "next_month", "income_total", "expense_total",
            "net", "categories", "by_month", "income_sources", "limits"} == set(body)
    assert len(body["by_month"]) == 12
    category = body["categories"][0]
    assert {"category_id", "name", "icon", "color", "amount", "share_bp", "count", "prev_amount",
            "limit", "limit_used_bp"} == set(category)
    source = body["income_sources"][0]
    assert {"source_id", "name", "icon", "color", "amount", "share_bp", "tax_accrued",
            "projects"} == set(source)


def test_my_money_excludes_frozen_and_hidden(client):
    """25.09 Артём: «Мои деньги» = видимые личные счета минус замороженные рубли; копилка — отдельно."""
    prepare()
    body = client.get("/api/home?currency=RUB").json()
    visible = sum(a["in_view"]["amount"] for g in body["groups"] for a in g["accounts"])
    assert body["my_money"]["amount"] == visible - body["frozen_rub"]["amount"]
    slugs = {a["slug"] for g in body["groups"] for a in g["accounts"]}
    assert not slugs & {a["slug"] for a in body["hidden"]["accounts"]}
