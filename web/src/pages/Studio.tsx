import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { ChecklistPanel } from "../components/ChecklistPanel";
import { DraftingProgress } from "../components/DraftingProgress";
import { useDraftRunner } from "../components/Layout";
import { LinkedInPreview } from "../components/LinkedInPreview";
import { useToast } from "../components/Toast";
import { CategoryTile, EmptyState, noteDisplayStatus, PageHeader, ScoreChip, Skeleton, Spinner, StatusPill } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { countVerify, countWords, pad, relative, stamp } from "../lib/format";
import type { Draft, NoteDetail } from "../lib/types";

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

/* ---------- left column ---------- */

function NotePanel({ note }: { note: NoteDetail }) {
  return (
    <section className="card p-5 sm:p-6">
      <div className="mb-3 flex items-center justify-between">
        <span className="label">Specimen · note #{pad(note.id)}</span>
        <StatusPill status={noteDisplayStatus(note)} />
      </div>
      <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink">{note.text}</p>
      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-hairline-2 pt-3 font-mono text-[10.5px] uppercase tracking-wider text-muted">
        <span>{stamp(note.received_at)}</span>
        <span>{note.source === "telegram" ? `telegram · msg ${note.telegram_message_id ?? "?"}` : note.filename ?? note.source}</span>
      </div>
    </section>
  );
}

function TriagePanel({ note, threshold }: { note: NoteDetail; threshold: number }) {
  const [raw, setRaw] = useState(false);
  const json = {
    score: note.score,
    publishable: note.publishable,
    category: note.category,
    core_insight: note.core_insight,
    suggested_hook_type: note.suggested_hook_type,
    missing_facts: note.missing_facts,
    reason: note.reason,
  };
  return (
    <section className="card p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between">
        <span className="label">Triage · assay</span>
        <button className="font-mono text-[10.5px] text-muted underline-offset-4 hover:text-ink hover:underline" onClick={() => setRaw((r) => !r)}>
          {raw ? "formatted" : "raw json"}
        </button>
      </div>
      {raw ? (
        <pre className="scrollbar-thin overflow-x-auto rounded-md bg-paper-2 p-3 font-mono text-[11.5px] leading-relaxed text-ink-2">{JSON.stringify(json, null, 2)}</pre>
      ) : (
        <>
          <div className="flex items-center gap-4">
            <ScoreChip score={note.score} threshold={threshold} size="lg" />
            <div className="space-y-1.5">
              <CategoryTile category={note.category} />
              {note.suggested_hook_type && (
                <div className="font-mono text-[11px] text-muted">
                  hook → <span className="text-ink-2">{note.suggested_hook_type}</span>
                </div>
              )}
            </div>
          </div>
          {note.core_insight && <p className="mt-4 font-serif text-[16px] leading-snug text-ink">“{note.core_insight}”</p>}
          {note.reason && <p className="mt-2 text-[13.5px] text-muted">{note.reason}</p>}
          {note.missing_facts.length > 0 && (
            <div className="mt-4 rounded-md border border-dashed border-ochre/50 p-3">
              <div className="label mb-1.5 !text-ochre">Missing facts</div>
              <ul className="space-y-1 text-[13px] text-ink-2">
                {note.missing_facts.map((f, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="font-mono text-muted">{i + 1}.</span>
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function NewsPanel({ draft }: { draft: Draft }) {
  if (!draft.news_found)
    return (
      <section className="rounded-[10px] border border-dashed border-hairline p-5 sm:p-6">
        <span className="label">News angle · none</span>
        <p className="mt-2 text-[13.5px] text-muted">{draft.news_note ?? "Nothing credible was found, so the post stands on the note alone."}</p>
      </section>
    );
  return (
    <section className="card relative overflow-hidden p-5 sm:p-6">
      <div className="absolute inset-y-0 left-0 w-[3px] bg-sage" aria-hidden />
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="label">News angle · {draft.news_source}</span>
        <span className="font-mono text-[10px] text-sage-ink">grounded</span>
      </div>
      <h3 className="text-[19px] leading-snug text-ink">{draft.news_title}</h3>
      {draft.news_summary && <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">{draft.news_summary}</p>}
      {draft.news_note && <p className="mt-2 font-serif text-[13.5px] italic text-muted">{draft.news_note}</p>}
      {draft.news_url && (
        <a href={draft.news_url} target="_blank" rel="noopener noreferrer" className="mt-4 inline-flex items-center gap-1.5 font-mono text-[11.5px] text-sage-ink underline decoration-sage/40 underline-offset-4 hover:decoration-sage">
          open source ↗
        </a>
      )}
    </section>
  );
}

function Versions({ drafts, current, onPick }: { drafts: Draft[]; current: number; onPick: (id: number) => void }) {
  if (drafts.length < 2) return null;
  return (
    <section className="px-1">
      <div className="label mb-2">Versions</div>
      <div className="flex flex-wrap gap-1.5">
        {drafts.map((d) => (
          <button
            key={d.id}
            onClick={() => onPick(d.id)}
            className={`h-7 rounded-full border px-2.5 font-mono text-[11px] ${d.id === current ? "border-ink bg-ink text-paper" : "border-hairline text-muted hover:border-ink-2"}`}
            title={d.redraft_instruction ? `Instruction: ${d.redraft_instruction}` : `Created ${relative(d.created_at)}`}
          >
            v{d.version} · {d.status === "pending" ? "review" : d.status}
          </button>
        ))}
      </div>
    </section>
  );
}

/* ---------- right column ---------- */

function DraftWorkbench({ draft, note }: { draft: Draft; note: NoteDetail }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { run, running } = useDraftRunner();
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(draft.body);
  const [instruction, setInstruction] = useState("");
  const [showRedraft, setShowRedraft] = useState(false);

  useEffect(() => {
    setBody(draft.body);
    setEditing(false);
  }, [draft.id, draft.body]);

  const words = useMemo(() => countWords(body), [body]);
  const verify = useMemo(() => countVerify(body), [body]);
  const [lo, hi] = draft.checklist.word_range ?? [400, 550];
  const dirty = body !== draft.body;
  const reviewable = draft.status === "pending";

  const refresh = () => qc.invalidateQueries();
  const save = useMutation({
    mutationFn: () => api.editDraft(draft.id, body),
    onSuccess: () => {
      toast("Edits saved", "success");
      setEditing(false);
      refresh();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Save failed", "error"),
  });
  const approve = useMutation({
    mutationFn: async () => {
      if (dirty) await api.editDraft(draft.id, body);
      return api.approve(draft.id);
    },
    onSuccess: () => {
      toast("Approved. Copy it and post it on LinkedIn yourself.", "success");
      refresh();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Approve failed", "error"),
  });
  const discard = useMutation({
    mutationFn: () => api.discard(draft.id),
    onSuccess: () => {
      toast("Discarded. The original note is kept.");
      refresh();
    },
  });

  const onCopy = async () => {
    await copyText(body);
    toast(verify ? `Copied · ${verify} [VERIFY] marker${verify > 1 ? "s" : ""} still in the text` : "Copied to clipboard", verify ? "info" : "success");
  };
  const onRedraft = () => {
    setShowRedraft(false);
    run(instruction ? `Redrafting: “${instruction}”` : "Redrafting", () => api.redraft(draft.id, instruction));
    setInstruction("");
  };

  const busy = save.isPending || approve.isPending || discard.isPending || !!running;

  return (
    <div className="space-y-5">
      {/* status banner */}
      {draft.status === "approved" && (
        <div className="flex items-center gap-3 rounded-[10px] border border-sage/50 bg-sage-soft px-4 py-3 text-[13.5px] text-ink">
          <span className="h-2 w-2 rounded-full bg-sage" />
          Approved {relative(draft.approved_at)}. Ready for you to copy and publish on LinkedIn. Nothing has been posted.
        </div>
      )}
      {(draft.status === "discarded" || draft.status === "superseded") && (
        <div className="rounded-[10px] border border-dashed border-hairline px-4 py-3 text-[13.5px] text-muted">
          This version was {draft.status === "superseded" ? "replaced by a redraft" : "discarded"}. The note is kept.
        </div>
      )}

      {/* instrument bar */}
      <div className="card sticky top-[64px] z-20 flex flex-wrap items-center justify-between gap-3 px-4 py-3 lg:top-4">
        <div className="flex items-center gap-4 font-mono text-[12px] tabular-nums">
          <span className={words < lo || words > hi ? "text-clay" : "text-sage-ink"} title={`Target ${lo}-${hi} words`}>
            {words}
            <span className="text-muted">
              {" "}
              / {lo}–{hi}w
            </span>
          </span>
          <span className={verify ? "rounded bg-verify px-1.5 py-0.5 text-verify-ink" : "text-muted"}>{verify} verify</span>
          {dirty && <span className="text-ochre">unsaved</span>}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {editing ? (
            <>
              <button className="btn btn-ghost" onClick={() => { setBody(draft.body); setEditing(false); }} disabled={busy}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={() => save.mutate()} disabled={!dirty || busy}>
                {save.isPending && <Spinner />} Save
              </button>
            </>
          ) : (
            <button className="btn" onClick={() => setEditing(true)} disabled={busy}>
              Edit
            </button>
          )}
          <button className="btn" onClick={onCopy}>
            Copy
          </button>
        </div>
      </div>

      <LinkedInPreview body={body} editing={editing} onChange={setBody} meta={`Draft v${draft.version} · ${stamp(draft.created_at)}`} />

      {draft.reviewer_notes && (
        <div className="rounded-[10px] border border-hairline bg-paper-2/60 px-5 py-4">
          <div className="label mb-1">Before you post</div>
          <p className="text-[13.5px] text-ink-2">{draft.reviewer_notes}</p>
        </div>
      )}

      {/* actions */}
      {reviewable && (
        <div className="card p-4 sm:p-5">
          <AnimatePresence initial={false}>
            {showRedraft && (
              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                <label className="label mb-2 block" htmlFor="instr">
                  Redraft instruction · optional
                </label>
                <div className="mb-4 flex flex-col gap-2 sm:flex-row">
                  <input
                    id="instr"
                    value={instruction}
                    onChange={(e) => setInstruction(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && onRedraft()}
                    placeholder="e.g. lead with the Bandra scene, cut the second mechanism"
                    className="h-10 flex-1 rounded-full border border-hairline bg-paper px-4 text-[14px] outline-none placeholder:text-muted focus:border-sage"
                    autoFocus
                  />
                  <button className="btn btn-primary h-10" onClick={onRedraft} disabled={busy}>
                    Redraft
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button className="btn btn-danger" onClick={() => discard.mutate()} disabled={busy}>
              Discard
            </button>
            <div className="flex flex-wrap gap-2">
              <button className="btn" onClick={() => setShowRedraft((s) => !s)} disabled={busy}>
                Redraft…
              </button>
              <button className="btn btn-sage" onClick={() => approve.mutate()} disabled={busy} title="Approve for you to post manually. Nothing is published.">
                {approve.isPending && <Spinner />} Approve
              </button>
            </div>
          </div>
        </div>
      )}

      <ChecklistPanel checklist={draft.checklist} />
      <p className="px-1 font-mono text-[10.5px] text-muted">note #{pad(note.id)} · draft #{pad(draft.id)} · this app never posts to LinkedIn</p>
    </div>
  );
}

function NoDraftYet({ note, threshold }: { note: NoteDetail; threshold: number }) {
  const { run, running } = useDraftRunner();
  const qc = useQueryClient();
  const toast = useToast();
  const triage = useMutation({
    mutationFn: () => api.triage(note.id),
    onSuccess: () => qc.invalidateQueries(),
    onError: (e) => toast(e instanceof ApiError ? e.message : "Triage failed", "error"),
  });
  const below = note.score != null && note.score < threshold;
  if (running) return <DraftingProgress title={running} />;
  return (
    <EmptyState
      title={note.status === "new" ? "Not scored yet" : below ? "Scored below the threshold" : "Ready to draft"}
      action={
        <div className="flex flex-wrap justify-center gap-2">
          {note.status === "new" && (
            <button className="btn" onClick={() => triage.mutate()} disabled={triage.isPending}>
              {triage.isPending && <Spinner />} Score only
            </button>
          )}
          <button className="btn btn-primary" onClick={() => run("Drafting this note", () => api.draftNote(note.id))}>
            {below ? "Draft anyway" : "Draft this note"}
          </button>
        </div>
      }
    >
      {below
        ? `This note scored ${note.score}/10, under the ${threshold} threshold, so it's parked as "not now". It's kept and you can still draft it.`
        : "Drafting searches for a current news angle, writes the post with Meera's voice skill, and runs the self-check. It usually takes under a minute."}
    </EmptyState>
  );
}

/* ---------- page ---------- */

export function Studio() {
  const { noteId } = useParams();
  const id = Number(noteId);
  const { running } = useDraftRunner();
  const { data: st } = useQuery({ queryKey: ["status"], queryFn: api.status });
  const { data: note, isLoading, error } = useQuery({ queryKey: ["note", id], queryFn: () => api.note(id), enabled: !!id });
  const [picked, setPicked] = useState<number | null>(null);
  useEffect(() => setPicked(null), [id, note?.drafts.length]);

  if (!noteId) return <StudioIndex />;
  const threshold = st?.threshold ?? 7;

  if (error) return <EmptyState title="Note not found" action={<Link to="/" className="btn">Back to inbox</Link>} />;
  if (isLoading || !note)
    return (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="space-y-4">
          <Skeleton className="h-40" />
          <Skeleton className="h-56" />
        </div>
        <Skeleton className="h-[560px]" />
      </div>
    );

  const visible = note.drafts.filter((d) => d.status !== "superseded" || d.id === picked);
  const current = note.drafts.find((d) => d.id === picked) ?? visible[0] ?? note.drafts[0];

  return (
    <>
      <PageHeader eyebrow={`Draft Studio · note #${pad(note.id)}`} title={note.core_insight ? "In the studio" : "Raw note"}>
        <Link to="/" className="btn btn-ghost">
          ← Inbox
        </Link>
      </PageHeader>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-8">
        <div className="order-2 space-y-5 lg:order-1">
          <NotePanel note={note} />
          {note.score != null && <TriagePanel note={note} threshold={threshold} />}
          {current && <NewsPanel draft={current} />}
          <Versions drafts={note.drafts} current={current?.id ?? 0} onPick={setPicked} />
        </div>
        <div className="order-1 lg:order-2">
          {running && current ? (
            <div className="space-y-5">
              <DraftingProgress title={running} />
            </div>
          ) : current ? (
            <DraftWorkbench draft={current} note={note} />
          ) : (
            <NoDraftYet note={note} threshold={threshold} />
          )}
        </div>
      </div>
    </>
  );
}

function StudioIndex() {
  const { data: week, isLoading } = useQuery({ queryKey: ["week"], queryFn: api.week });
  if (isLoading) return <Skeleton className="h-64" />;
  const first = week?.queue[0];
  if (first) return <Navigate to={`/studio/${first.note_id}`} replace />;
  return (
    <>
      <PageHeader eyebrow="Draft Studio" title="Nothing on the bench." />
      <EmptyState title="No drafts waiting for review" action={<Link to="/backlog" className="btn">Open the backlog</Link>}>
        Use “Draft next best note” to pick the strongest unused note, or open any note from the inbox.
      </EmptyState>
    </>
  );
}
