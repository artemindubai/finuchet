# -*- coding: utf-8 -*-
"""Суточная копия базы: 7 файлов в BACKUP_DIR (ARCHITECTURE §1.1, ТЗ 10)."""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import sqlite3

from backend import db
from backend.tz import now_dubai, today_dubai, utc_now

log = logging.getLogger("finuchet.backup")
KEEP = 7


def backup_once() -> str | None:
    db.ensure_dirs()
    target = os.path.join(db.backup_dir(), f"finuchet-{today_dubai()}.db")
    conn = db.get_conn()
    try:
        with sqlite3.connect(target) as dest:
            conn.backup(dest)
        size = os.path.getsize(target)
        with db.transaction(conn):
            conn.execute("INSERT INTO backups (at, path, bytes, ok, note) VALUES (?,?,?,1,NULL)",
                         (utc_now(), target, size))
        _rotate()
        log.info("копия базы готова: %s (%d байт)", target, size)
        return target
    except Exception as exc:
        log.error("копия базы не удалась: %s", exc)
        try:
            with db.transaction(conn):
                conn.execute("INSERT INTO backups (at, path, bytes, ok, note) VALUES (?,?,0,0,?)",
                             (utc_now(), target, str(exc)[:200]))
        except Exception:
            pass
        return None


def _rotate() -> None:
    files = sorted(glob.glob(os.path.join(db.backup_dir(), "finuchet-*.db")))
    for path in files[:-KEEP]:
        try:
            os.remove(path)
        except OSError:
            pass


def _seconds_until(hour: int) -> float:
    now = now_dubai()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        from datetime import timedelta
        target += timedelta(days=1)
    return max(60.0, (target - now).total_seconds())


async def backup_loop() -> None:
    """Копия при старте, дальше — раз в сутки в 03:00 по Дубаю."""
    try:
        await asyncio.to_thread(backup_once)
    except Exception as exc:
        log.error("первая копия не удалась: %s", exc)
    while True:
        try:
            await asyncio.sleep(_seconds_until(3))
            await asyncio.to_thread(backup_once)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("цикл копий: %s", exc)
            await asyncio.sleep(3600)
