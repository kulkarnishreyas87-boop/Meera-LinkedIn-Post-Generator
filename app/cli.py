"""Command line: bulk import, triage, drafting and serving.

    python -m app.cli import notes/          # import a folder of .txt/.md notes
    python -m app.cli triage                 # score every untriaged note
    python -m app.cli draft-next             # draft the next best note
    python -m app.cli draft <note_id>        # draft a specific note
    python -m app.cli weekly                 # run the Monday top-3 job now
    python -m app.cli show <draft_id>        # print a draft and its checklist
    python -m app.cli serve                  # API + dashboard + bot + scheduler
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app.db import repo
from app.db.models import Draft, Note
from app.db.session import init_db, session_scope


def _print_draft(draft: Draft) -> None:
    with session_scope() as s:
        note = s.get(Note, draft.note_id)
    c = draft.checklist or {}
    print(f"\n=== Draft #{draft.id} v{draft.version} - note #{note.id} ({note.category}, score {note.score}) ===\n")
    print(draft.body)
    print("\n--- news angle ---")
    if draft.news_found:
        print(f"{draft.news_title} | {draft.news_source}\n{draft.news_url}\n{draft.news_note or ''}")
    else:
        print(draft.news_note)
    print("\n--- checklist ---")
    print(f"words={c.get('word_count')} verify={c.get('verify_count')} revised={c.get('revised')}")
    for ch in c.get("checks", []):
        print(f"  [{'x' if ch['passed'] else ' '}] {ch['label']} {('- ' + ch['detail']) if ch['detail'] else ''}")
    for r in c.get("self_check", []):
        mark = {True: "x", False: " ", None: "?"}[r["passed"]]
        print(f"  [{mark}] Q{r['n']}: {r['question'][:70]}... {r['note']}")
    if draft.reviewer_notes:
        print(f"\nreviewer notes: {draft.reviewer_notes}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="skinstinct", description="Drafts-only LinkedIn assistant. Never posts.")
    sub = p.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="Import a folder of .txt/.md notes")
    imp.add_argument("folder", type=Path)
    sub.add_parser("triage", help="Triage all untriaged notes")
    sub.add_parser("draft-next", help="Draft the next best note")
    d = sub.add_parser("draft", help="Draft a specific note")
    d.add_argument("note_id", type=int)
    d.add_argument("--instruction", default=None)
    sub.add_parser("weekly", help="Run the weekly top-3 job now")
    sh = sub.add_parser("show", help="Print a draft")
    sh.add_argument("draft_id", type=int)
    sub.add_parser("status", help="Counts per status")
    sv = sub.add_parser("serve", help="Run API + dashboard + bot + scheduler")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    args = p.parse_args(argv)

    init_db()
    from app.pipeline import orchestrator

    if args.cmd == "import":
        if not args.folder.is_dir():
            print(f"Not a folder: {args.folder}", file=sys.stderr)
            return 1
        files = repo.read_notes_folder(args.folder)
        with session_scope() as s:
            created = repo.import_files(s, files, source="import")
        print(f"Imported {len(created)} note(s); skipped {len(files) - len(created)} duplicate/empty.")
    elif args.cmd == "triage":
        for n in orchestrator.triage_pending():
            flag = "draft" if n.publishable else "not now"
            print(f"#{n.id:<4} {n.score:>2}/10  {flag:<8} {n.category:<24} {n.reason}")
    elif args.cmd == "draft-next":
        try:
            _print_draft(orchestrator.draft_next_best())
        except orchestrator.NothingToDraft as exc:
            print(exc)
            return 1
    elif args.cmd == "draft":
        _print_draft(orchestrator.draft_note(args.note_id, instruction=args.instruction))
    elif args.cmd == "weekly":
        for dr in orchestrator.weekly_run(3):
            _print_draft(dr)
    elif args.cmd == "show":
        with session_scope() as s:
            dr = s.get(Draft, args.draft_id)
        if not dr:
            print("Draft not found", file=sys.stderr)
            return 1
        _print_draft(dr)
    elif args.cmd == "status":
        with session_scope() as s:
            print(json.dumps(repo.status_counts(s), indent=2))
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
