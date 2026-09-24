import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useDraftRunner } from "../components/Layout";
import { CategoryTile, EmptyState, PageHeader, Skeleton, StatusPill } from "../components/ui";
import { api } from "../lib/api";
import { longDate, pad, relative } from "../lib/format";
import type { Draft, Note } from "../lib/types";

/** Three vials that fill as posts are approved. */
function Vials({ done, target }: { done: number; target: number }) {
  return (
    <div className="flex items-end gap-5" role="img" aria-label={`${done} of ${target} posts approved this week`}>
      {Array.from({ length: target }, (_, i) => {
        const filled = i < done;
        return (
          <div key={i} className="flex flex-col items-center gap-2">
            <svg width="44" height="112" viewBox="0 0 44 112" fill="none" aria-hidden>
              <defs>
                <clipPath id={`vial-${i}`}>
                  <path d="M8 10h28v84a14 14 0 0 1-28 0V10z" />
                </clipPath>
              </defs>
              <g clipPath={`url(#vial-${i})`}>
                <rect
                  x="0"
                  y="26"
                  width="44"
                  height="112"
                  fill="var(--sage)"
                  className="vial-fill"
                  style={{ opacity: filled ? 1 : 0, animationDelay: `${0.15 + i * 0.12}s` }}
                />
                {[34, 50, 66, 82].map((y) => (
                  <line key={y} x1="8" x2="16" y1={y} y2={y} stroke="var(--hairline)" strokeWidth="1" />
                ))}
              </g>
              <path d="M8 10h28v84a14 14 0 0 1-28 0V10z" stroke="var(--ink-2)" strokeWidth="1.2" />
              <path d="M4 10h36" stroke="var(--ink-2)" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
            <span className={`font-mono text-[10.5px] ${filled ? "text-sage-ink" : "text-muted"}`}>0{i + 1}</span>
          </div>
        );
      })}
    </div>
  );
}

function DraftRow({ draft, note }: { draft: Draft; note?: Note }) {
  const c = draft.checklist;
  return (
    <Link to={`/studio/${draft.note_id}`} className="card group flex items-start gap-4 p-4 transition-all hover:-translate-y-px hover:border-ink-2/40 sm:p-5">
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex flex-wrap items-center gap-2">
          <StatusPill status={draft.status} />
          {note?.category && <CategoryTile category={note.category} compact />}
        </div>
        <p className="line-clamp-2 text-[14.5px] leading-relaxed text-ink">{draft.body}</p>
        <div className="mt-2 flex flex-wrap gap-x-4 font-mono text-[10.5px] text-muted">
          <span>#{pad(draft.note_id)} · v{draft.version}</span>
          <span>{c.word_count ?? "?"}w</span>
          {!!c.verify_count && <span className="text-verify-ink">{c.verify_count} verify</span>}
          <span>{relative(draft.approved_at ?? draft.created_at)}</span>
        </div>
      </div>
      <span className="self-center text-muted transition-transform group-hover:translate-x-0.5">→</span>
    </Link>
  );
}

export function Week() {
  const { data, isLoading } = useQuery({ queryKey: ["week"], queryFn: api.week, refetchInterval: 30_000 });
  const { run, running } = useDraftRunner();

  if (isLoading || !data)
    return (
      <>
        <Skeleton className="mb-8 h-24" />
        <Skeleton className="h-64" />
      </>
    );

  const remaining = Math.max(0, data.target - data.approved_count);

  return (
    <>
      <PageHeader eyebrow={`This week · ${longDate(data.week_start)}`} title={remaining ? `${remaining} to go this week.` : "Week's quota met."} />

      <section className="card mb-10 grid gap-8 p-6 sm:grid-cols-[auto_1fr] sm:items-center sm:p-8">
        <Vials done={Math.min(data.approved_count, data.target)} target={data.target} />
        <div>
          <div className="font-mono text-[56px] leading-none tabular-nums text-ink">
            {data.approved_count}
            <span className="text-muted">/{data.target}</span>
          </div>
          <div className="label mt-2">approved for posting</div>
          <p className="mt-4 max-w-md text-[14px] text-ink-2">
            {data.queue.length
              ? `${data.queue.length} draft${data.queue.length > 1 ? "s" : ""} waiting for your review.`
              : "No drafts waiting for review."}{" "}
            {data.next_run && <>Next automatic batch: {longDate(data.next_run)}, 9:00 IST.</>}
          </p>
          <button className="btn btn-primary mt-5" onClick={() => run("Drafting the next best note", api.draftNext)} disabled={!!running}>
            Draft next best note
          </button>
        </div>
      </section>

      <div className="grid gap-10 lg:grid-cols-2">
        <section>
          <h2 className="mb-4 text-[24px]">Review queue</h2>
          {data.queue.length ? (
            <div className="space-y-3">
              {data.queue.map((d) => (
                <DraftRow key={d.id} draft={d} note={data.queue_notes[d.note_id]} />
              ))}
            </div>
          ) : (
            <EmptyState title="Queue is clear">Monday's batch drafts the top 3 notes automatically.</EmptyState>
          )}
        </section>
        <section>
          <h2 className="mb-4 text-[24px]">Approved this week</h2>
          {data.approved.length ? (
            <div className="space-y-3">
              {data.approved.map((d) => (
                <DraftRow key={d.id} draft={d} note={data.queue_notes[d.note_id]} />
              ))}
            </div>
          ) : (
            <EmptyState title="None yet">Approved drafts land here, ready for you to copy and post.</EmptyState>
          )}
        </section>
      </div>
    </>
  );
}
