import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { pad, relative, stamp } from "../lib/format";
import { CATEGORIES, type Category, type Note } from "../lib/types";
import { CardSkeleton, CategoryTile, EmptyState, noteDisplayStatus, PageHeader, ScoreChip, StatusPill } from "../components/ui";

const STATUS_FILTERS = [
  { v: "", label: "All" },
  { v: "new", label: "New" },
  { v: "triaged", label: "Triaged" },
  { v: "not_now", label: "Not now" },
  { v: "drafted", label: "Drafted" },
  { v: "approved", label: "Approved" },
  { v: "discarded", label: "Discarded" },
];

export function NoteCard({ note, threshold, index = 0 }: { note: Note; threshold: number; index?: number }) {
  const status = noteDisplayStatus(note);
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(index, 12) * 0.025, duration: 0.3 }}>
      <Link
        to={`/studio/${note.id}`}
        className={`card group block p-5 transition-all hover:-translate-y-px hover:border-ink-2/40 ${status === "not_now" || status === "discarded" ? "opacity-75" : ""}`}
      >
        <div className="flex items-start gap-4">
          <div className="min-w-0 flex-1">
            <div className="mb-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 font-mono text-[10.5px] uppercase tracking-wider text-muted">
              <span className="text-ink-2">#{pad(note.id)}</span>
              <span title={note.received_at}>{stamp(note.received_at)}</span>
              <span>{note.source === "telegram" ? "telegram" : note.filename ?? note.source}</span>
            </div>
            <p className="line-clamp-3 text-[15px] leading-relaxed text-ink">{note.text}</p>
            {note.reason && (
              <p className="mt-2.5 line-clamp-1 font-serif text-[14px] italic text-muted" title={note.reason}>
                {note.reason}
              </p>
            )}
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <StatusPill status={status} />
              {note.category && <CategoryTile category={note.category} compact />}
              {note.missing_facts.length > 0 && (
                <span className="font-mono text-[10.5px] text-ochre">{note.missing_facts.length} missing fact{note.missing_facts.length > 1 ? "s" : ""}</span>
              )}
            </div>
          </div>
          <ScoreChip score={note.score} threshold={threshold} />
        </div>
      </Link>
    </motion.div>
  );
}

export function Inbox() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const category = params.get("category") ?? "";
  const { data: st } = useQuery({ queryKey: ["status"], queryFn: api.status });
  const { data: notes, isLoading, error } = useQuery({
    queryKey: ["notes", status, category],
    queryFn: () => api.notes({ status, category }),
    refetchInterval: 20_000,
  });

  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p, { replace: true });
  };
  const counts = st?.counts;
  const total = counts ? counts.new + counts.triaged + counts.drafted + counts.approved + counts.discarded : undefined;

  return (
    <>
      <PageHeader eyebrow={`Inbox · ${total ?? "…"} notes`} title="Every note, kept." />

      <div className="mb-6 space-y-4">
        <div className="scrollbar-thin -mx-4 flex gap-1 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0" role="tablist" aria-label="Filter by status">
          {STATUS_FILTERS.map((f) => {
            const n = f.v === "" ? total : counts?.[f.v as keyof typeof counts];
            const on = status === f.v;
            return (
              <button
                key={f.v}
                role="tab"
                aria-selected={on}
                onClick={() => set("status", f.v)}
                className={`flex h-8 shrink-0 items-center gap-2 rounded-full border px-3 text-[13px] transition-colors ${
                  on ? "border-ink bg-ink text-paper" : "border-hairline text-ink-2 hover:border-ink-2"
                }`}
              >
                {f.label}
                {n != null && <span className={`font-mono text-[10.5px] ${on ? "text-paper/70" : "text-muted"}`}>{n}</span>}
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap gap-2" aria-label="Filter by category">
          {CATEGORIES.map((c: Category) => (
            <button key={c} onClick={() => set("category", category === c ? "" : c)} aria-pressed={category === c}>
              <CategoryTile category={c} active={category === c} />
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <EmptyState title="Couldn't reach the server">Is the backend running on port 8000?</EmptyState>
      ) : isLoading ? (
        <div className="grid gap-4 md:grid-cols-2">{Array.from({ length: 6 }, (_, i) => <CardSkeleton key={i} />)}</div>
      ) : !notes?.length ? (
        <EmptyState
          title={status || category ? "Nothing matches these filters" : "No notes yet"}
          action={!(status || category) && <Link to="/backlog" className="btn">Import notes</Link>}
        >
          {status || category
            ? "Try clearing a filter."
            : "Drop a note into the Telegram channel, or import the backlog folder. Every note is kept, even the ones that aren't ready yet."}
        </EmptyState>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {notes.map((n, i) => (
            <NoteCard key={n.id} note={n} threshold={st?.threshold ?? 7} index={i} />
          ))}
        </div>
      )}
      {notes && notes.length > 0 && (
        <p className="mt-8 text-center font-mono text-[10.5px] text-muted">last note {relative(notes[0]?.received_at)}</p>
      )}
    </>
  );
}
