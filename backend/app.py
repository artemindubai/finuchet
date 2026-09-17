# -*- coding: utf-8 -*-
"""FastAPI: API мини-аппа, статика фронтенда, фоновые задачи (ARCHITECTURE §1).

Запуск ровно один и тот же локально и в образе: python -m uvicorn backend.app:app из корня."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import backup, db, rates
from backend.api import errors
from backend.api.routes_entries import router as entries_router
from backend.api.routes_home import router as home_router
from backend.api.routes_refs import router as refs_router
from backend.api.routes_reports import router as reports_router
from backend.rates.loop import rates_loop
from backend.tz import utc_now

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("finuchet.app")

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
VERSION = os.environ.get("APP_VERSION", "1.0.0")
_tasks: list[asyncio.Task] = []
_bot_started = False


def _spawn(coro, name: str) -> None:
    async def guarded():
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("фоновая задача %s остановилась: %s", name, exc)

    _tasks.append(asyncio.create_task(guarded(), name=name))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot_started
    db.ensure_dirs()                       # каталоги — до всего остального (§1 правило 7)
    await asyncio.to_thread(db.init)
    log.info("база готова: %s", db.db_path())

    _spawn(rates_loop(), "rates")
    _spawn(backup.backup_loop(), "backup")

    if os.environ.get("BOT_TOKEN") and os.environ.get("NO_BOT") != "1":
        try:
            from backend.bot.runner import (run_bot_forever, run_reminders_forever,
                                            run_telethon_stt_forever)
            _spawn(run_bot_forever(), "bot")
            _spawn(run_telethon_stt_forever(), "telethon_stt")
            _spawn(run_reminders_forever(), "reminders")
            _bot_started = True
        except ImportError:
            log.warning("бот не подключён: модуль backend.bot ещё не готов — поднимаем только веб")
    else:
        log.info("бот не запускается: NO_BOT=1 или пустой BOT_TOKEN")

    try:
        yield
    finally:
        for task in _tasks:
            task.cancel()
        await asyncio.gather(*_tasks, return_exceptions=True)
        _tasks.clear()


app = FastAPI(title="Финучёт", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)
errors.install(app)
app.include_router(home_router)
app.include_router(entries_router)
app.include_router(reports_router)
app.include_router(refs_router)          # последним: у него общий путь /api/{ref}


def _bot_alive() -> bool:
    """`bot` в /healthz — не «задачу создали», а «поллинг действительно крутится»."""
    if not _bot_started:
        return False
    try:
        from backend.bot import runner
    except ImportError:
        return True
    return bool(runner.polling_alive())


@app.get("/healthz")
async def healthz():
    def _state() -> dict:
        ok_db = True
        rates_age = None
        try:
            conn = db.get_conn()
            conn.execute("SELECT 1").fetchone()
            row = conn.execute("SELECT MAX(at) AS at FROM rate_history").fetchone()
            if row and row["at"]:
                rates_age = utc_now() - int(row["at"])
        except Exception:
            ok_db = False
        return {"ok": ok_db, "db": ok_db, "bot": _bot_alive(), "rates_age_sec": rates_age,
                "version": VERSION}
    return await asyncio.to_thread(_state)


if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")


@app.get("/")
async def index():
    index_file = DIST / "index.html"
    if index_file.is_file():
        return FileResponse(str(index_file))
    return JSONResponse(status_code=503, content=errors.error_body(
        "frontend_not_built", "Фронтенд ещё не собран: выполните npm run build в frontend"))


@app.get("/{path:path}")
async def spa(path: str):
    """Мини-апп — одностраничник с хеш-маршрутами; всё остальное отдаём index.html."""
    if path.startswith("api/"):
        return JSONResponse(status_code=404,
                            content=errors.error_body("not_found", "Нет такого метода"))
    candidate = DIST / path
    if path and candidate.is_file():
        return FileResponse(str(candidate))
    return await index()
