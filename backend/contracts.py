# -*- coding: utf-8 -*-
"""Общие типы Финучёта. Единственный файл, который импортируют и ядро, и бот.
Правка — только через ARCHITECTURE.md §8.0 и согласование мастера."""
from dataclasses import dataclass, field
from typing import Literal, Optional

Currency = Literal["RUB", "AED", "USDT", "USD"]
Kind = Literal[
    "expense", "income", "transfer", "exchange",
    "family_withdrawal", "family_repayment", "family_topup_by_parents",
    "own_contribution_to_family", "family_spent_own", "paid_for_family_from_own",
    "loan_given", "loan_repaid_to_me", "loan_taken", "loan_repaid_by_me",
    "tax_payment", "opening_balance", "balance_correction",
]
Source = Literal["voice", "text", "manual", "screenshot", "statement", "system"]
AccountRef = int | str  # id или slug


class LedgerError(Exception):
    def __init__(self, code: str, message: str = "", details: dict | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.details = details or {}


@dataclass
class ParsedOperation:
    kind: Kind
    amount: int                      # минорные единицы, всегда > 0 (кроме balance_correction — со знаком)
    currency: Currency
    from_account: Optional[AccountRef] = None
    to_account: Optional[AccountRef] = None
    category: Optional[AccountRef] = None        # slug/id расходного счёта
    income_source: Optional[AccountRef] = None   # slug/id доходного счёта
    counterparty: Optional[str] = None           # имя; создаётся при первом упоминании
    project: Optional[str] = None
    op_date: Optional[str] = None                # 'YYYY-MM-DD'; None = сегодня по Дубаю
    amount_to: Optional[int] = None              # exchange: сколько получено
    currency_to: Optional[Currency] = None
    rate_e6: Optional[int] = None                # курс × 1_000_000, если назван голосом или следует из сумм
    rate_source: Optional[str] = None            # 'voice' | 'bybit_p2p' | 'er_api+markup' | 'cbr+markup' | 'manual'
    no_tax: bool = False
    freeze: bool = True                          # для family_withdrawal
    freeze_account: Optional[AccountRef] = None  # None = настройка freeze_account (умолчание tbank)
    description: str = ""
    source: Source = "voice"
    raw_input: Optional[str] = None
    confidence: Optional[float] = None
    due_date: Optional[str] = None               # срок долга/платежа, если назван


@dataclass
class OperationPatch:
    """Дельта правки. Заполнены только меняемые поля; остальное копируется из старой версии."""
    amount: Optional[int] = None
    currency: Optional[Currency] = None
    kind: Optional[Kind] = None
    from_account: Optional[AccountRef] = None
    to_account: Optional[AccountRef] = None
    category: Optional[AccountRef] = None
    income_source: Optional[AccountRef] = None
    counterparty: Optional[str] = None
    project: Optional[str] = None
    op_date: Optional[str] = None
    amount_to: Optional[int] = None              # exchange: «не 500 USDT, а 512»
    currency_to: Optional[Currency] = None
    rate_e6: Optional[int] = None
    no_tax: Optional[bool] = None
    freeze: Optional[bool] = None                # family_withdrawal: «не надо было замораживать»
    freeze_account: Optional[AccountRef] = None  # «заморозь на Сбере, не на Т-Банке»
    due_date: Optional[str] = None
    description: Optional[str] = None
    raw_input: Optional[str] = None


@dataclass
class EntryFilters:
    q: Optional[str] = None
    account_id: Optional[int] = None
    category_id: Optional[int] = None
    kind: Optional[Kind] = None
    status: str = "posted"           # 'posted' | 'void' | 'all'
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    currency_view: Currency = "RUB"
    limit: int = 50
    cursor: Optional[str] = None


@dataclass
class OpeningBalanceItem:
    account: AccountRef
    amount: int
    currency: Currency
    op_date: Optional[str] = None


@dataclass
class ScreenRow:
    amount: int                      # СО ЗНАКОМ глазами банка: − списание, + зачисление
    currency: Currency
    op_date: Optional[str] = None
    raw_text: str = ""
    suggested_category: Optional[AccountRef] = None
    suggested_kind: Optional[Kind] = None


@dataclass
class ScreenBatch:
    account: AccountRef
    rows: list[ScreenRow] = field(default_factory=list)
    balance: Optional[int] = None    # остаток на скрине, минорные единицы
    currency: Optional[Currency] = None
    source: Source = "screenshot"
    period: Optional[str] = None     # '2026-09-01..2026-09-30' для выписки


@dataclass
class ReconcileDecision:
    inbox_id: int
    decision: Literal["new", "same", "skip", "align"]
    match_entry_id: Optional[int] = None
    category: Optional[AccountRef] = None


@dataclass
class RateQuote:
    pair: str                        # 'AED/RUB'
    rate_e6: int
    source: str                      # 'bybit_p2p' | 'er_api+markup' | 'cbr+markup' | 'cache' | 'voice'
    at: int                          # unix UTC
    markup_e6: int = 0
    legs: dict = field(default_factory=dict)   # {'usdt_rub_e6':…, 'usdt_aed_e6':…}
    stale: bool = False
