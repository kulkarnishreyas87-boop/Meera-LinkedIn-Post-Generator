"""Render drafts as Telegram HTML messages with review buttons."""

from __future__ import annotations

import html
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import Draft, Note

TG_LIMIT = 4096
TIER_SHORT = {"regulator": "🏛 regulator", "journal": "🔬 journal", "press": "📰 press", "trade": "🏷 trade", "other": "other"}
VERIFY_RE = re.compile(r"\[VERIFY:[^\]]*\]", re.IGNORECASE)


def review_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Approve", callback_data=f"a:{draft_id}"),
            InlineKeyboardButton("✏️ Redraft", callback_data=f"r:{draft_id}"),
            InlineKeyboardButton("🗑️ Discard", callback_data=f"d:{draft_id}"),
        ]]
    )


def redraft_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("↻ Just redraft", callback_data=f"rn:{draft_id}")]])


def needs_facts_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✍️ Fill facts", callback_data=f"f:{draft_id}"),
                InlineKeyboardButton("✅ Approve anyway", callback_data=f"a:{draft_id}"),
            ],
            [
                InlineKeyboardButton("✏️ Redraft", callback_data=f"r:{draft_id}"),
                InlineKeyboardButton("🗑️ Discard", callback_data=f"d:{draft_id}"),
            ],
        ]
    )


def auto_approved_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("↩️ Undo approval", callback_data=f"u:{draft_id}"),
            InlineKeyboardButton("✏️ Redraft", callback_data=f"r:{draft_id}"),
        ]]
    )


def auto_discarded_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("♻️ Restore to review", callback_data=f"u:{draft_id}")]])


def keyboard_for(draft: Draft) -> InlineKeyboardMarkup | None:
    status = getattr(draft.status, "value", draft.status)
    if status == "approved":
        return auto_approved_keyboard(draft.id)
    if status == "discarded":
        return auto_discarded_keyboard(draft.id)
    if status == "needs_facts":
        return needs_facts_keyboard(draft.id)
    if status == "pending":
        return review_keyboard(draft.id)
    return None


DECISION_BANNER = {
    "auto_approved": "✅ <b>Auto-approved</b> - ready for you to copy and post on LinkedIn. Nothing has been published.",
    "needs_facts": "✍️ <b>Needs facts</b> - fill the [VERIFY] items and it approves itself.",
    "review": "👀 <b>Your call</b>",
    "auto_discarded": "🗑️ <b>Auto-discarded</b> - the note is kept. Restore it if you disagree.",
}


def decision_line(draft: Draft) -> str:
    banner = DECISION_BANNER.get(draft.decision or "", "")
    reason = html.escape(draft.decision_reason or "")
    return f"{banner}\n<i>{reason}</i>" if banner else ""


def render_auto_discarded(draft: Draft, note: Note) -> str:
    """Compact message for auto-discards: no need to read the full post."""
    preview = html.escape(note.text.strip().replace("\n", " ")[:140])
    score = f"{draft.quality_score}/10" if draft.quality_score is not None else "?"
    return (
        f"🗑️ <b>Auto-discarded draft #{draft.id}</b> · note #{note.id} · score {score}\n"
        f"<i>{html.escape(draft.decision_reason or '')}</i>\n\n"
        f"Note: “{preview}…”\n\nThe note is kept. Tap Restore to review the draft yourself."
    )


def highlight_verify(text: str) -> str:
    """HTML-escape the body and underline+bold every [VERIFY: ...] marker."""
    out, last = [], 0
    for m in VERIFY_RE.finditer(text):
        out.append(html.escape(text[last : m.start()]))
        out.append(f"<b><u>{html.escape(m.group(0))}</u></b>")
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def header(draft: Draft, note: Note) -> str:
    c = draft.checklist or {}
    bits = [f"Draft #{draft.id}", f"v{draft.version}"]
    if note.category:
        bits.append(html.escape(note.category))
    bits.append(f"{c.get('word_count', '?')} words")
    if c.get("verify_count"):
        bits.append(f"{c['verify_count']} [VERIFY]")
    if draft.quality_score is not None:
        bits.append(f"score {draft.quality_score}/10")
    head = "📝 <b>" + " · ".join(bits) + "</b>"
    line = decision_line(draft)
    return f"{head}\n{line}" if line else head


def footer(draft: Draft) -> str:
    c = draft.checklist or {}
    lines = []
    if draft.news_found and draft.news_url:
        meta = " · ".join(x for x in [draft.news_source, TIER_SHORT.get(draft.news_tier or "", ""), draft.news_published] if x)
        via = " · via Google News" if draft.news_via == "google_news" else ""
        lines.append(f'📰 Angle: <a href="{html.escape(draft.news_url, quote=True)}">{html.escape(draft.news_title or "source")}</a>'
                     + (f" ({html.escape(meta)}{via})" if meta else ""))
    else:
        lines.append("📰 No news angle: " + html.escape(draft.news_note or "nothing credible found"))

    cc = c.get("claim_check") or {}
    if cc.get("claims"):
        summary = f"{cc.get('supported', 0)} supported · {cc.get('unclear', 0)} unclear · {cc.get('contradicted', 0)} contradicted"
        lines.append(f"🔍 Claim check: {summary}")
        for x in cc["claims"]:
            if x.get("verdict") == "contradicted":
                lines.append(f"   ❌ {html.escape(x['claim'])} - <i>{html.escape(x.get('explanation') or '')}</i>")
    srcs = draft.sources or []
    if srcs:
        lines.append("📚 Sources (for your first comment):")
        for i, s in enumerate(srcs[:4], 1):
            tier = TIER_SHORT.get(s.get("tier") or "", "")
            lines.append(f'   {i}. <a href="{html.escape(s.get("url") or "", quote=True)}">{html.escape(s.get("publisher") or "source")}</a>'
                         + (f" · {tier}" if tier else "") + (f" · {s['published']}" if s.get("published") else ""))
    failed = [ch["label"] for ch in c.get("checks", []) if not ch["passed"] and ch["severity"] != "info"]
    failed += [f"Self-check #{r['n']}" for r in c.get("self_check", []) if r.get("passed") is False]
    lines.append("☑️ Checklist: all passed" if not failed else "⚠️ Check: " + html.escape(", ".join(failed)))
    invented = (c.get("review") or {}).get("invented_claims") or []
    if invented:
        lines.append("🚩 <b>Possibly invented</b> (not in your note or fact sheet): " + html.escape("; ".join(invented)))
    if draft.reviewer_notes:
        lines.append("🔎 " + html.escape(draft.reviewer_notes))
    lines.append("<i>Drafts only - nothing is posted to LinkedIn. Approve = ready for you to copy and post.</i>")
    return "\n".join(lines)


def render_draft_messages(draft: Draft, note: Note) -> list[str]:
    """One message if it fits, else header+body and footer as separate messages."""
    head, body, foot = header(draft, note), highlight_verify(draft.body), footer(draft)
    single = f"{head}\n\n{body}\n\n{foot}"
    if len(single) <= TG_LIMIT:
        return [single]
    parts = [f"{head}\n\n{body}"] if len(head) + len(body) + 2 <= TG_LIMIT else [head, *_chunks(body)]
    return [*parts, foot]


def _chunks(text: str, size: int = TG_LIMIT - 50) -> list[str]:
    chunks, buf = [], ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) + 2 > size and buf:
            chunks.append(buf)
            buf = ""
        buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks
