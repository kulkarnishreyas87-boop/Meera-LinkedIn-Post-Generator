"""Weekly rhythm: every Monday 09:00 IST, draft the top 3 notes for the week."""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.repo import IST
from app.pipeline import orchestrator

log = logging.getLogger(__name__)
JOB_ID = "weekly-top-3"

_scheduler: AsyncIOScheduler | None = None


async def weekly_job() -> None:
    log.info("Weekly run: drafting the top 3 notes")
    try:
        drafts = await orchestrator.weekly_run_async(3)
        log.info("Weekly run produced %d draft(s)", len(drafts))
    except Exception:
        log.exception("Weekly run failed")


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone=IST)
    _scheduler.add_job(
        weekly_job,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=IST),
        id=JOB_ID,
        replace_existing=True,
        misfire_grace_time=6 * 3600,  # if the laptop was asleep at 9:00, still run that morning
        coalesce=True,
    )
    _scheduler.start()
    log.info("Scheduler started; next weekly run at %s", next_run())
    return _scheduler


def stop_scheduler() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)


def next_run() -> datetime | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    return job.next_run_time if job else None
