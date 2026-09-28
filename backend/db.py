# -*- coding: utf-8 -*-
"""Соединение с SQLite, DDL (ARCHITECTURE §3 дословно), каталоги, первичный seed.

Соединение открывается с isolation_level=None: каждая пишущая функция ядра сама делает
BEGIN IMMEDIATE ... COMMIT (§4, грабля 9 журнала)."""
from __future__ import annotations

import os
import sqlite3
import threading

_local = threading.local()

DDL = """
CREATE TABLE IF NOT EXISTS accounts (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  slug               TEXT    NOT NULL UNIQUE,
  name               TEXT    NOT NULL,
  type               TEXT    NOT NULL CHECK (type IN
                       ('asset_personal','asset_family','liability','income','expense','equity')),
  currency           TEXT    CHECK (currency IN ('RUB','AED','USDT','USD')),
  is_money           INTEGER NOT NULL DEFAULT 0,
  needs_counterparty INTEGER NOT NULL DEFAULT 0,
  group_key          TEXT,
  icon               TEXT,
  sort               INTEGER NOT NULL DEFAULT 100,
  archived           INTEGER NOT NULL DEFAULT 0,
  created_at         INTEGER NOT NULL,
  CHECK (is_money = 0 OR currency IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_accounts_type ON accounts(type, archived);

CREATE TABLE IF NOT EXISTS categories (
  account_id INTEGER PRIMARY KEY REFERENCES accounts(id),
  parent_id  INTEGER REFERENCES accounts(id),
  color      TEXT,
  sort       INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS income_sources (
  account_id  INTEGER PRIMARY KEY REFERENCES accounts(id),
  tax_rate_bp INTEGER NOT NULL DEFAULT 0,
  tax_account_id INTEGER REFERENCES accounts(id),
  color       TEXT,
  icon        TEXT,
  sort        INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS counterparties (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  kind       TEXT NOT NULL DEFAULT 'person' CHECK (kind IN ('person','client','other')),
  note       TEXT,
  archived   INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS entries (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  kind                 TEXT    NOT NULL CHECK (kind IN (
                          'expense','income','transfer','exchange',
                          'family_withdrawal','family_repayment','family_topup_by_parents',
                          'own_contribution_to_family','family_spent_own','paid_for_family_from_own',
                          'loan_given','loan_repaid_to_me','loan_taken','loan_repaid_by_me',
                          'tax_payment','opening_balance','balance_correction')),
  op_date              TEXT    NOT NULL,
  created_at           INTEGER NOT NULL,
  description          TEXT    NOT NULL DEFAULT '',
  source               TEXT    NOT NULL CHECK (source IN
                          ('voice','text','manual','screenshot','statement','system')),
  status               TEXT    NOT NULL DEFAULT 'posted' CHECK (status IN ('posted','void')),
  version              INTEGER NOT NULL DEFAULT 1,
  replaces_entry_id    INTEGER REFERENCES entries(id),
  replaced_by_entry_id INTEGER REFERENCES entries(id),
  void_reason          TEXT,
  voided_at            INTEGER,
  rates_snapshot       TEXT,
  raw_input            TEXT,
  confidence           REAL,
  counterparty_id      INTEGER REFERENCES counterparties(id),
  project              TEXT,
  external_ref         TEXT,
  due_date             TEXT,
  sealed               INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_entries_due    ON entries(due_date) WHERE due_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_entries_date   ON entries(op_date DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_entries_status ON entries(status, op_date DESC);
CREATE INDEX IF NOT EXISTS ix_entries_kind   ON entries(kind, op_date DESC);
CREATE INDEX IF NOT EXISTS ix_entries_ext    ON entries(external_ref);

CREATE TABLE IF NOT EXISTS postings (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id        INTEGER NOT NULL REFERENCES entries(id),
  seq             INTEGER NOT NULL,
  account_id      INTEGER NOT NULL REFERENCES accounts(id),
  amount          INTEGER NOT NULL,
  currency        TEXT    NOT NULL CHECK (currency IN ('RUB','AED','USDT','USD')),
  counterparty_id INTEGER REFERENCES counterparties(id),
  project         TEXT,
  memo            TEXT,
  CHECK (amount <> 0)
);
CREATE INDEX IF NOT EXISTS ix_postings_entry   ON postings(entry_id, seq);
CREATE INDEX IF NOT EXISTS ix_postings_account ON postings(account_id, currency);

CREATE TRIGGER IF NOT EXISTS trg_entry_balanced
BEFORE UPDATE OF sealed ON entries WHEN NEW.sealed = 1 AND OLD.sealed = 0
BEGIN
  SELECT RAISE(ABORT, 'entry has no postings')
   WHERE NOT EXISTS (SELECT 1 FROM postings WHERE entry_id = NEW.id);
  SELECT RAISE(ABORT, 'entry not balanced by currency')
   WHERE EXISTS (SELECT 1 FROM postings WHERE entry_id = NEW.id
                 GROUP BY currency HAVING SUM(amount) <> 0);
END;

CREATE TRIGGER IF NOT EXISTS trg_entry_no_unseal
BEFORE UPDATE OF sealed ON entries WHEN OLD.sealed = 1 AND NEW.sealed = 0
BEGIN SELECT RAISE(ABORT, 'sealed entry cannot be reopened'); END;

CREATE TRIGGER IF NOT EXISTS trg_postings_sealed_insert
BEFORE INSERT ON postings
WHEN (SELECT sealed FROM entries WHERE id = NEW.entry_id) = 1
BEGIN SELECT RAISE(ABORT, 'cannot add postings to sealed entry'); END;

CREATE TRIGGER IF NOT EXISTS trg_postings_no_update
BEFORE UPDATE ON postings
BEGIN SELECT RAISE(ABORT, 'postings are immutable: void and repost'); END;

CREATE TRIGGER IF NOT EXISTS trg_postings_no_delete
BEFORE DELETE ON postings
BEGIN SELECT RAISE(ABORT, 'postings are immutable: void and repost'); END;

CREATE TRIGGER IF NOT EXISTS trg_posting_currency
BEFORE INSERT ON postings
WHEN (SELECT currency FROM accounts WHERE id = NEW.account_id) IS NOT NULL
 AND (SELECT currency FROM accounts WHERE id = NEW.account_id) <> NEW.currency
BEGIN SELECT RAISE(ABORT, 'posting currency <> account currency'); END;

CREATE VIEW IF NOT EXISTS v_balances AS
SELECT p.account_id, p.currency, SUM(p.amount) AS balance
  FROM postings p JOIN entries e ON e.id = p.entry_id
 WHERE e.status = 'posted' AND e.sealed = 1
 GROUP BY p.account_id, p.currency;

CREATE TABLE IF NOT EXISTS family_tranches (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id         INTEGER NOT NULL REFERENCES entries(id),
  op_date          TEXT    NOT NULL,
  aed_taken        INTEGER NOT NULL,
  aed_left         INTEGER NOT NULL,
  rate_e6          INTEGER NOT NULL,
  rate_source      TEXT    NOT NULL,
  rate_at          INTEGER NOT NULL,
  rub_frozen       INTEGER NOT NULL,
  rub_left         INTEGER NOT NULL,
  account_id       INTEGER REFERENCES accounts(id),
  status           TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed','void')),
  created_at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tranches_open ON family_tranches(status, op_date, id);

CREATE TABLE IF NOT EXISTS tranche_releases (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tranche_id  INTEGER NOT NULL REFERENCES family_tranches(id),
  entry_id    INTEGER NOT NULL REFERENCES entries(id),
  aed_released INTEGER NOT NULL,
  rub_released INTEGER NOT NULL,
  created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_releases_tranche ON tranche_releases(tranche_id);
CREATE INDEX IF NOT EXISTS ix_releases_entry   ON tranche_releases(entry_id);

-- Перенос заморозки в другую валюту (28.09, Артём): часть рублёвых траншей закрывается, взамен
-- блокируются дирхамы на счёте. Забалансовая запись, как и сами транши: проводок нет, остатки не
-- меняются. Поля rub_moved/aed_taken/aed_left/locked/locked_left — функция журнала (rebuild_releases).
CREATE TABLE IF NOT EXISTS freeze_moves (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  op_date       TEXT    NOT NULL,
  rub_requested INTEGER NOT NULL CHECK (rub_requested > 0),
  rate_e6       INTEGER,
  account_id    INTEGER NOT NULL REFERENCES accounts(id),
  currency      TEXT    NOT NULL DEFAULT 'AED' CHECK (currency IN ('AED')),
  rub_moved     INTEGER NOT NULL DEFAULT 0,
  aed_taken     INTEGER NOT NULL DEFAULT 0,
  aed_left      INTEGER NOT NULL DEFAULT 0,
  locked        INTEGER NOT NULL DEFAULT 0,
  locked_left   INTEGER NOT NULL DEFAULT 0,
  status        TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed','void')),
  note          TEXT,
  created_at    INTEGER NOT NULL,
  voided_at     INTEGER,
  void_reason   TEXT
);
CREATE TABLE IF NOT EXISTS freeze_move_parts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  move_id     INTEGER NOT NULL REFERENCES freeze_moves(id),
  tranche_id  INTEGER NOT NULL REFERENCES family_tranches(id),
  aed_moved   INTEGER NOT NULL,
  rub_moved   INTEGER NOT NULL,
  created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_move_parts_tranche ON freeze_move_parts(tranche_id);
CREATE TABLE IF NOT EXISTS freeze_move_releases (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  move_id         INTEGER NOT NULL REFERENCES freeze_moves(id),
  entry_id        INTEGER NOT NULL REFERENCES entries(id),
  aed_released    INTEGER NOT NULL,
  locked_released INTEGER NOT NULL,
  created_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_move_releases_entry ON freeze_move_releases(entry_id);

CREATE TABLE IF NOT EXISTS planned_payments (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  title              TEXT    NOT NULL,
  amount             INTEGER NOT NULL,
  currency           TEXT    NOT NULL,
  account_id         INTEGER REFERENCES accounts(id),
  category_id        INTEGER REFERENCES accounts(id),
  counterparty_id    INTEGER REFERENCES counterparties(id),
  repeat             TEXT    NOT NULL DEFAULT 'once'
                       CHECK (repeat IN ('once','weekly','monthly','quarterly','yearly')),
  next_date          TEXT    NOT NULL,
  day_of_month       INTEGER,
  remind_days_before INTEGER NOT NULL DEFAULT 0,
  active             INTEGER NOT NULL DEFAULT 1,
  last_paid_entry_id INTEGER REFERENCES entries(id),
  last_paid_date     TEXT,
  created_at         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_planned_next ON planned_payments(active, next_date);

CREATE TABLE IF NOT EXISTS goals (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT    NOT NULL,
  target      INTEGER NOT NULL,
  currency    TEXT    NOT NULL,
  account_id  INTEGER REFERENCES accounts(id),
  due_date    TEXT,
  archived    INTEGER NOT NULL DEFAULT 0,
  created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_allocations (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  goal_id    INTEGER NOT NULL REFERENCES goals(id),
  amount     INTEGER NOT NULL,
  currency   TEXT    NOT NULL,
  op_date    TEXT    NOT NULL,
  note       TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_goal_alloc ON goal_allocations(goal_id, op_date);

CREATE TABLE IF NOT EXISTS limits (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES accounts(id),
  period      TEXT    NOT NULL DEFAULT 'month' CHECK (period IN ('month')),
  amount      INTEGER NOT NULL,
  currency    TEXT    NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  INTEGER NOT NULL,
  UNIQUE (category_id, period)
);

CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rate_history (
  pair       TEXT    NOT NULL,
  at         INTEGER NOT NULL,
  rate_e6    INTEGER NOT NULL,
  source     TEXT    NOT NULL,
  raw        TEXT,
  PRIMARY KEY (pair, at)
);
CREATE INDEX IF NOT EXISTS ix_rate_hist ON rate_history(pair, at DESC);

CREATE VIEW IF NOT EXISTS rate_cache AS
SELECT h.pair, h.rate_e6, h.source, h.at, h.raw
  FROM rate_history h
  JOIN (SELECT pair, MAX(at) AS at FROM rate_history GROUP BY pair) last
    ON last.pair = h.pair AND last.at = h.at;

CREATE TABLE IF NOT EXISTS voice_transcripts (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id        INTEGER NOT NULL,
  file_unique_id TEXT,
  duration       INTEGER,
  sent_at        INTEGER NOT NULL,
  text           TEXT,
  provider       TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('pending','ready','failed')),
  created_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vt_fuid ON voice_transcripts(file_unique_id);
CREATE INDEX IF NOT EXISTS ix_vt_time ON voice_transcripts(chat_id, sent_at);

CREATE TABLE IF NOT EXISTS bot_pending (
  chat_id    INTEGER PRIMARY KEY,
  state      TEXT NOT NULL CHECK (state IN ('amend','clarify','reconcile')),
  entry_id   INTEGER REFERENCES entries(id),
  payload    TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS inbox (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id      TEXT    NOT NULL,
  source        TEXT    NOT NULL CHECK (source IN ('screenshot','statement')),
  account_id    INTEGER REFERENCES accounts(id),
  op_date       TEXT,
  amount        INTEGER NOT NULL,
  currency      TEXT    NOT NULL,
  raw_text      TEXT,
  suggested_kind TEXT,
  suggested_category_id INTEGER REFERENCES accounts(id),
  match_status  TEXT NOT NULL CHECK (match_status IN ('new','matched','ambiguous')),
  match_entry_id INTEGER REFERENCES entries(id),
  candidates    TEXT,
  status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','accepted','skipped','merged')),
  entry_id      INTEGER REFERENCES entries(id),
  created_at    INTEGER NOT NULL,
  resolved_at   INTEGER
);
CREATE INDEX IF NOT EXISTS ix_inbox_batch ON inbox(batch_id, status);

CREATE TABLE IF NOT EXISTS audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  at          INTEGER NOT NULL,
  actor       TEXT    NOT NULL,
  action      TEXT    NOT NULL,
  object_type TEXT,
  object_id   INTEGER,
  payload     TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_time ON audit_log(at DESC);

CREATE TABLE IF NOT EXISTS backups (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  at      INTEGER NOT NULL,
  path    TEXT NOT NULL,
  bytes   INTEGER,
  ok      INTEGER NOT NULL DEFAULT 1,
  note    TEXT
);
"""


def db_path() -> str:
    return os.environ.get("DB_PATH") or os.path.join("data", "finuchet.db")


def backup_dir() -> str:
    return os.environ.get("BACKUP_DIR") or os.path.join(os.path.dirname(db_path()) or ".", "backups")


def tmp_dir() -> str:
    return os.environ.get("TMP_DIR") or os.path.join(os.path.dirname(db_path()) or ".", "tmp")


def ensure_dirs() -> None:
    """Каталоги создаются до всего остального (§1 правило 7): на проде /data пуст."""
    for path in (os.path.dirname(db_path()), backup_dir(), tmp_dir()):
        if path:
            os.makedirs(path, exist_ok=True)


def connect() -> sqlite3.Connection:
    """Новое соединение. Пишущие функции сами управляют транзакциями."""
    ensure_dirs()
    conn = sqlite3.connect(db_path(), isolation_level=None, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get_conn() -> sqlite3.Connection:
    """Соединение на поток: ядро синхронное и живёт в asyncio.to_thread."""
    path = db_path()
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == path:
        return conn
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    conn = connect()
    _local.conn = conn
    _local.path = path
    return conn


def close_conn() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            _local.conn = None
            _local.path = None


def init() -> None:
    """CREATE TABLE IF NOT EXISTS + seed плана счетов и умолчаний настроек."""
    ensure_dirs()
    conn = get_conn()
    conn.executescript(DDL)
    from backend.seed import accounts as seed_accounts
    seed_accounts.ensure(conn)
    from backend import settings_store
    settings_store.ensure_defaults(conn)


class transaction:
    """with transaction(conn): ... — явный BEGIN IMMEDIATE / COMMIT / ROLLBACK."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.own = False

    def __enter__(self) -> sqlite3.Connection:
        if not self.conn.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE")
            self.own = True
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self.own:
            return False
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
        return False
