"""Telegram bot: collects notes, sends drafts with review buttons, and answers commands.

Uses long polling (no public URL). Handles both `message` (group/DM) and `channel_post`
(channel) updates, and ignores everything not from TELEGRAM_CHAT_ID.
"""

from __future__ import annotations

import asyncio
import html
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.bot.filters import is_allowed_update, note_text
from app.bot.format import keyboard_for, redraft_keyboard, render_auto_discarded, render_draft_messages
from app.config import Settings
from app.db import repo
from app.db.models import REVIEWABLE, Draft, DraftStatus, Note
from app.pipeline.autoreview import verify_items
from app.db.session import session_scope
from app.pipeline import orchestrator
from app.pipeline.gemini import GeminiUnavailable

log = logging.getLogger(__name__)
T = TypeVar("T")
PENDING_REDRAFT = "pending_redraft"  # bot_data key: {prompt_message_id: draft_id}
PENDING_FILL = "pending_fill"  # bot_data key: {prompt_message_id: draft_id}
# Which drafts each button may act on
ALLOWED = {
    "a": REVIEWABLE,
    "d": REVIEWABLE,
    "f": {DraftStatus.needs_facts},
    "r": REVIEWABLE | {DraftStatus.approved},
    "rn": REVIEWABLE | {DraftStatus.approved},
    "u": {DraftStatus.approved, DraftStatus.discarded},
}


async def with_tg_retry(fn: Callable[[], Awaitable[T]], attempts: int = 4) -> T:
    """Retry Telegram calls on flood control and transient network errors."""
    delay = 2.0
    for i in range(1, attempts + 1):
        try:
            return await fn()
        except RetryAfter as exc:
            wait = float(getattr(exc.retry_after, "total_seconds", lambda: exc.retry_after)())
            log.warning("Telegram flood control, waiting %.0fs", wait)
            await asyncio.sleep(wait + 1)
        except (TimedOut, NetworkError) as exc:
            if isinstance(exc, BadRequest) or i == attempts:
                raise
            log.warning("Telegram network error (%s), retry %d in %.0fs", exc, i, delay)
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


class DraftBot:
    def __init__(self, settings: Settings):
        settings.require_telegram()
        self.settings = settings
        self.chat_id = settings.telegram_chat_id
        self.app: Application = (
            ApplicationBuilder()
            .token(settings.telegram_bot_token)
            .connect_timeout(20)
            .read_timeout(20)
            .write_timeout(20)
            .get_updates_connect_timeout(20)
            .get_updates_read_timeout(30)
            .build()
        )
        self._register()

    # ---------- wiring ----------

    def _register(self) -> None:
        chat = filters.Chat(chat_id=self.chat_id)
        new_msgs = filters.UpdateType.MESSAGE | filters.UpdateType.CHANNEL_POST
        a = self.app
        a.add_handler(CommandHandler("start", self.cmd_start, filters=chat))
        a.add_handler(CommandHandler("help", self.cmd_start, filters=chat))
        a.add_handler(CommandHandler("status", self.cmd_status, filters=chat))
        a.add_handler(CommandHandler("draft", self.cmd_draft, filters=chat))
        a.add_handler(CommandHandler("backlog", self.cmd_backlog, filters=chat))
        a.add_handler(CallbackQueryHandler(self.on_button))
        a.add_handler(MessageHandler(chat & new_msgs & (filters.TEXT | filters.CAPTION) & ~filters.COMMAND, self.on_text))
        a.add_error_handler(self.on_error)
        orchestrator.register_notifier(self.send_draft)

    async def start(self, attempts: int = 4) -> None:
        """Start polling, retrying transient network failures (slow or flaky connections)."""
        delay = 3.0
        for i in range(1, attempts + 1):
            try:
                await self.app.initialize()
                break
            except (TimedOut, NetworkError) as exc:
                if isinstance(exc, BadRequest) or i == attempts:
                    raise
                log.warning("Telegram not reachable (%s); retry %d/%d in %.0fs", exc, i, attempts - 1, delay)
                await asyncio.sleep(delay)
                delay *= 2
        await self.app.start()
        await self.app.updater.start_polling(
            allowed_updates=["message", "channel_post", "callback_query"],
            drop_pending_updates=False,
        )
        me = await self.app.bot.get_me()
        log.info("Telegram bot @%s polling chat %s", me.username, self.chat_id)

    async def stop(self) -> None:
        if self.app.updater and self.app.updater.running:
            await self.app.updater.stop()
        if self.app.running:
            await self.app.stop()
        await self.app.shutdown()

    # ---------- sending ----------

    async def say(self, text: str, **kw) -> Message:
        return await with_tg_retry(lambda: self.app.bot.send_message(
            self.chat_id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, **kw))

    async def send_draft(self, draft_id: int) -> None:
        with session_scope() as s:
            draft = s.get(Draft, draft_id)
            note = s.get(Note, draft.note_id) if draft else None
        if not draft or not note:
            return
        if draft.decision == "auto_discarded" and draft.status == DraftStatus.discarded:
            msgs = [render_auto_discarded(draft, note)]
        else:
            msgs = render_draft_messages(draft, note)
        last: Message | None = None
        for i, text in enumerate(msgs):
            kb = keyboard_for(draft) if i == len(msgs) - 1 else None
            last = await self.say(text, reply_markup=kb)
        if last:
            with session_scope() as s:
                d = s.get(Draft, draft_id)
                d.telegram_message_id = last.message_id
                s.add(d)
                s.commit()

    # ---------- incoming notes ----------

    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not is_allowed_update(update, self.chat_id):
            return
        msg = update.effective_message
        pending: dict[int, int] = ctx.bot_data.setdefault(PENDING_REDRAFT, {})
        if msg.reply_to_message and msg.reply_to_message.message_id in pending:
            draft_id = pending.pop(msg.reply_to_message.message_id)
            await self._redraft(draft_id, msg.text or msg.caption or "")
            return
        fills: dict[int, int] = ctx.bot_data.setdefault(PENDING_FILL, {})
        if msg.reply_to_message and msg.reply_to_message.message_id in fills:
            draft_id = fills.pop(msg.reply_to_message.message_id)
            await self._fill(draft_id, msg.text or msg.caption or "", ctx)
            return
        text = note_text(update)
        if not text:
            return
        with session_scope() as s:
            note = repo.create_note(s, text, source="telegram", telegram_message_id=msg.message_id)
        if note:
            log.info("Stored note %s from Telegram message %s", note.id, msg.message_id)

    # ---------- commands ----------

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self.say(
            "<b>Skinstinct drafting assistant</b>\n"
            "Drop raw notes here - observations, two-liners, voice-note transcripts. I keep every one, "
            "score it, and draft the strongest into LinkedIn posts in your voice.\n\n"
            "I <b>never</b> post to LinkedIn. Approving a draft just marks it ready for you to copy and post.\n\n"
            + (
                f"Each draft gets a quality score. {self.settings.auto_approve_min}+ is auto-approved (once any "
                f"[VERIFY] facts are filled), below {self.settings.auto_discard_below} gets one automatic redraft "
                "and is then discarded, and anything in between comes to you. Every automatic call has an Undo "
                "or Restore button.\n\n"
                if self.settings.auto_review else ""
            )
            +
            "/status - counts per status\n/draft - draft the next best note\n/backlog - top 5 unused notes"
        )

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        with session_scope() as s:
            c = repo.status_counts(s)
            auto = repo.auto_decision_counts(s)
            week = len(repo.approved_this_week(s))
        st = self.settings
        mode = (
            f"Auto-review <b>on</b>: approve at {st.auto_approve_min}+, discard below {st.auto_discard_below} "
            f"({auto['auto_approved']} auto-approved, {auto['auto_discarded']} auto-discarded so far)"
            if st.auto_review else "Auto-review <b>off</b>: every draft waits for you"
        )
        await self.say(
            "<b>Status</b>\n"
            f"<code>new        {c['new']:>3}\ntriaged    {c['triaged']:>3}  ({c['not_now']} not now)\n"
            f"drafted    {c['drafted']:>3}  ({c['needs_facts']} need facts)\napproved   {c['approved']:>3}\n"
            f"discarded  {c['discarded']:>3}</code>\n\n"
            f"This week: <b>{week}/3</b> approved\n{mode}"
        )

    async def cmd_draft(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self.say("Picking the next best note and drafting it. This takes about a minute.")
        asyncio.create_task(self._draft_next())

    async def _draft_next(self) -> None:
        try:
            await orchestrator.draft_next_best_async()
        except orchestrator.NothingToDraft:
            await self.say("Nothing publishable in the backlog right now. Drop a few more notes and try again.")
        except GeminiUnavailable as exc:
            log.warning("Draft failed: %s", exc)
            await self.say("Gemini is unavailable or rate-limited right now. Try /draft again in a few minutes.")
        except Exception:
            log.exception("Draft failed")
            await self.say("Something went wrong while drafting. Details are in the server log.")

    async def cmd_backlog(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        with session_scope() as s:
            notes = repo.ranked_backlog(s, limit=5)
            waiting = len(repo.untriaged(s))
        if not notes:
            await self.say("Backlog is empty." + (f" {waiting} note(s) not scored yet." if waiting else ""))
            return
        lines = ["<b>Top unused notes</b>"]
        for n in notes:
            preview = html.escape(n.text.strip().replace("\n", " ")[:90])
            flag = "" if n.publishable else " · not now"
            lines.append(f"<code>{n.score:>2}/10</code> #{n.id} {html.escape(n.category or '')}{flag}\n<i>{preview}…</i>")
        if waiting:
            lines.append(f"\n{waiting} note(s) not scored yet - they're scored when you /draft.")
        await self.say("\n\n".join(lines))

    # ---------- buttons ----------

    async def on_button(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        if not is_allowed_update(update, self.chat_id):
            await q.answer("Not allowed here.")
            return
        action, _, raw_id = (q.data or "").partition(":")
        try:
            draft_id = int(raw_id)
        except ValueError:
            await q.answer()
            return

        with session_scope() as s:
            draft = s.get(Draft, draft_id)
        if draft is None or draft.status not in ALLOWED.get(action, set()):
            state = draft.status.value.replace("_", " ") if draft else "deleted"
            await q.answer(f"This draft is already {state}.")
            await self._close_buttons(q.message, f"This draft is already <b>{state}</b>.")
            return

        if action == "u":
            was = draft.status
            orchestrator.reopen_draft(draft_id)
            await q.answer("Back in review.")
            await self._close_buttons(q.message, "↩️ Approval undone." if was == DraftStatus.approved else "♻️ Restored.")
            await self.send_draft(draft_id)
        elif action == "f":
            await q.answer()
            items = verify_items(draft.body)
            listing = "\n".join(f"{i}. {html.escape(it)}" for i, it in enumerate(items, 1))
            prompt = await self.say(
                f"✍️ <b>Reply to this message</b> with the facts for draft #{draft_id}, one per line:\n\n{listing}\n\n"
                "<i>Your words replace each marker exactly as written. Write <code>skip</code> to leave one.</i>"
            )
            ctx.bot_data.setdefault(PENDING_FILL, {})[prompt.message_id] = draft_id
        elif action == "a":
            orchestrator.set_draft_status(draft_id, DraftStatus.approved)
            await q.answer("Approved. Copy it and post it yourself.")
            await self._close_buttons(q.message, "✅ <b>Approved</b> - ready for you to copy and post on LinkedIn.")
        elif action == "d":
            orchestrator.set_draft_status(draft_id, DraftStatus.discarded)
            await q.answer("Discarded. The note is kept.")
            await self._close_buttons(q.message, "🗑️ <b>Discarded</b> (the original note is kept).")
        elif action == "r":
            await q.answer()
            prompt = await self.say(
                f"✏️ Redrafting #{draft_id}. <b>Reply to this message</b> with a one-line instruction "
                "(e.g. <i>lead with the Mumbai scene, shorter mechanism</i>), or tap below.",
                reply_markup=redraft_keyboard(draft_id),
            )
            ctx.bot_data.setdefault(PENDING_REDRAFT, {})[prompt.message_id] = draft_id
        elif action == "rn":
            await q.answer("Redrafting…")
            pending: dict[int, int] = ctx.bot_data.setdefault(PENDING_REDRAFT, {})
            pending.pop(q.message.message_id, None)
            await self._close_buttons(q.message, "↻ Redrafting without an instruction…", replace=True)
            await self._redraft(draft_id, "")
        else:
            await q.answer()

    async def _fill(self, draft_id: int, reply: str, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        draft, filled, missing = orchestrator.fill_facts(draft_id, reply)
        if not filled:
            await self.say("I couldn't match that to the [VERIFY] items. Tap ✍️ Fill facts and reply with one answer per line.")
            return
        if draft.status == DraftStatus.approved:
            await self.say(f"✍️ Filled {filled} fact(s). Draft #{draft_id} now scores {draft.quality_score}/10 and is <b>auto-approved</b>:")
        elif missing:
            await self.say(f"✍️ Filled {filled} fact(s); {missing} still to go.")
        else:
            await self.say(f"✍️ Filled {filled} fact(s). Here's the updated draft:")
        await self.send_draft(draft_id)

    async def _redraft(self, draft_id: int, instruction: str) -> None:
        with session_scope() as s:
            draft = s.get(Draft, draft_id)
        if not draft:
            await self.say("That draft no longer exists.")
            return
        if instruction:
            await self.say(f"Redrafting with: <i>{html.escape(instruction[:200])}</i>")

        async def run():
            try:
                await orchestrator.draft_note_async(draft.note_id, instruction=instruction or "")
            except GeminiUnavailable:
                await self.say("Gemini is unavailable or rate-limited right now. Tap Redraft again in a few minutes.")
            except Exception:
                log.exception("Redraft failed")
                await self.say("Redraft failed. Details are in the server log.")

        asyncio.create_task(run())

    async def _close_buttons(self, message: Message | None, status_html: str, replace: bool = False) -> None:
        if message is None:
            return
        try:
            if replace:
                await with_tg_retry(lambda: message.edit_text(status_html, parse_mode=ParseMode.HTML))
            else:
                await with_tg_retry(lambda: message.edit_reply_markup(reply_markup=None))
                await with_tg_retry(lambda: message.reply_text(status_html, parse_mode=ParseMode.HTML))
        except BadRequest as exc:  # message too old / already edited
            log.info("Could not update message: %s", exc)

    async def on_error(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if isinstance(ctx.error, (NetworkError, TimedOut)):
            log.warning("Telegram network error: %s", ctx.error)
        else:
            log.exception("Unhandled bot error", exc_info=ctx.error)
