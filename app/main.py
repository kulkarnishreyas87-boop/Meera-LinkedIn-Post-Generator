"""FastAPI app: API + built dashboard, with the Telegram bot and scheduler in the same process.

Run:  uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import scheduler
from app.api.routes import router, runtime
from app.config import get_settings
from app.db.session import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log request URLs (they contain the bot token)
log = logging.getLogger("skinstinct")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    init_db()
    bot = None
    if settings.enable_bot:
        try:
            from app.bot.handlers import DraftBot

            bot = DraftBot(settings)
            await bot.start()
            runtime["bot_running"] = True
        except Exception as exc:  # the dashboard should still work without Telegram
            log.error("Telegram bot not started: %s", exc)
            bot = None
    if settings.enable_scheduler:
        scheduler.start_scheduler()
    try:
        yield
    finally:
        scheduler.stop_scheduler()
        if bot:
            await bot.stop()
            runtime["bot_running"] = False


app = FastAPI(title="Skinstinct Drafts", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

_dist = get_settings().web_dist
if (_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (_dist / path).resolve()
        if path and candidate.is_file() and _dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
else:

    @app.get("/", include_in_schema=False)
    async def no_build():
        return JSONResponse({"detail": "Dashboard not built. Run `npm run build` in web/, or use the Vite dev server on :5173."})
