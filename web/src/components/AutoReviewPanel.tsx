import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { countVerify } from "../lib/format";
import type { Draft } from "../lib/types";
import { useToast } from "./Toast";
import { Spinner } from "./ui";

const TONE: Record<string, { label: string; cls: string; dot: string }> = {
  auto_approved: { label: "Auto-approved", cls: "border-sage/50 bg-sage-soft", dot: "bg-sage" },
  approved: { label: "Approved by you", cls: "border-sage/50 bg-sage-soft", dot: "bg-sage" },
  needs_facts: { label: "Needs facts", cls: "border-verify-ink/30 bg-verify/60", dot: "bg-verify-ink" },
  review: { label: "Your call", cls: "border-hairline bg-card", dot: "bg-ochre" },
  auto_discarded: { label: "Auto-discarded", cls: "border-dashed border-hairline bg-paper-2/60", dot: "bg-clay" },
  discarded: { label: "Discarded by you", cls: "border-dashed border-hairline bg-paper-2/60", dot: "bg-muted" },
};

/** Score dial + decision + undo/restore. "Approved" never publishes anything. */
export function AutoReviewPanel({ draft, approveMin, discardBelow }: { draft: Draft; approveMin: number; discardBelow: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const reopen = useMutation({
    mutationFn: () => api.reopen(draft.id),
    onSuccess: () => {
      toast("Moved back to review", "success");
      qc.invalidateQueries();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Couldn't reopen", "error"),
  });

  if (draft.status === "superseded") return null;
  const key = draft.decision ?? (draft.status === "approved" ? "approved" : draft.status === "discarded" ? "discarded" : "review");
  const tone = TONE[key] ?? TONE.review;
  const q = draft.checklist.quality;
  const invented = draft.checklist.review?.invented_claims ?? [];
  const score = draft.quality_score;
  const pct = score == null ? 0 : score * 10;
  const band = score == null ? "text-muted" : score >= approveMin ? "text-sage-ink" : score < discardBelow ? "text-clay" : "text-ochre";

  return (
    <section className={`rounded-[10px] border p-4 sm:p-5 ${tone.cls}`} aria-label="Auto-review decision">
      <div className="flex items-start gap-4">
        {/* dial */}
        <div className="relative h-16 w-16 shrink-0" title={q?.formula ?? "Draft quality score"}>
          <svg viewBox="0 0 64 64" className="h-16 w-16 -rotate-90" aria-hidden>
            <circle cx="32" cy="32" r="27" fill="none" stroke="var(--hairline)" strokeWidth="4" />
            {/* threshold ticks */}
            {[discardBelow, approveMin].map((t) => (
              <circle key={t} cx="32" cy="32" r="27" fill="none" stroke="var(--ink-2)" strokeWidth="6"
                strokeDasharray={`0.8 ${2 * Math.PI * 27}`} strokeDashoffset={-((t / 10) * 2 * Math.PI * 27)} />
            ))}
            <circle cx="32" cy="32" r="27" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round"
              className={`${band} transition-[stroke-dasharray] duration-700`}
              strokeDasharray={`${(pct / 100) * 2 * Math.PI * 27} ${2 * Math.PI * 27}`} />
          </svg>
          <div className={`absolute inset-0 flex flex-col items-center justify-center font-mono tabular-nums ${band}`}>
            <span className="text-[19px] leading-none">{score ?? "–"}</span>
            <span className="text-[8px] tracking-widest opacity-70">/10</span>
          </div>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
            <span className="font-serif text-[18px] leading-tight text-ink">{tone.label}</span>
            {draft.decided_by === "auto" && <span className="font-mono text-[10px] uppercase tracking-wider text-muted">by the rule</span>}
          </div>
          {draft.decision_reason && <p className="mt-1 text-[13.5px] text-ink-2">{draft.decision_reason}</p>}
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10.5px] text-muted">
            {q?.voice != null && <span>voice {q.voice}/10</span>}
            {q?.self_check && <span>self-check {q.self_check}</span>}
            {q?.note_score != null && <span>note substance {q.note_score}/10</span>}
            {!!q?.format_failures && <span className="text-clay">{q.format_failures} format issue(s)</span>}
            {draft.checklist.auto_redraft_of_score != null && <span>auto-redrafted from {draft.checklist.auto_redraft_of_score}/10</span>}
            <span>
              rule: ≥{approveMin} approve · &lt;{discardBelow} discard
            </span>
          </div>
        </div>

        {(draft.status === "approved" || draft.status === "discarded") && (
          <button className="btn shrink-0" onClick={() => reopen.mutate()} disabled={reopen.isPending}>
            {reopen.isPending && <Spinner />}
            {draft.status === "approved" ? "Undo" : "Restore"}
          </button>
        )}
      </div>
      {invented.length > 0 && (
        <div className="mt-3 rounded-md border border-clay/40 bg-clay-soft p-3">
          <div className="label mb-1 !text-clay">Possibly invented · not in your note or fact sheet</div>
          <ul className="space-y-1 text-[13px] text-ink">
            {invented.map((c, i) => (
              <li key={i} className="flex gap-2">
                <span className="font-mono text-clay">!</span>
                {c}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[12px] text-ink-2">Drafts with invented details are never auto-approved. Edit it out, or approve if it's actually true.</p>
        </div>
      )}
      {draft.status === "approved" && (
        <p className="mt-3 border-t border-sage/30 pt-3 text-[12.5px] text-ink-2">Ready for you to copy and publish on LinkedIn. Nothing has been posted.</p>
      )}
    </section>
  );
}

/** Inputs for each [VERIFY] marker; submitting may auto-approve the draft. */
export function FillFactsPanel({ draft, items }: { draft: Draft; items: string[] }) {
  const [answers, setAnswers] = useState<string[]>(() => items.map(() => ""));
  const qc = useQueryClient();
  const toast = useToast();
  const fill = useMutation({
    mutationFn: () => api.fill(draft.id, answers),
    onSuccess: (d) => {
      const left = countVerify(d.body);
      toast(
        d.status === "approved" ? `Facts filled · scored ${d.quality_score}/10 · auto-approved` : left ? `${left} fact(s) still to fill` : "Facts filled",
        "success",
      );
      qc.invalidateQueries();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Couldn't fill facts", "error"),
  });
  if (!items.length) return null;

  return (
    <section className="card p-5 sm:p-6">
      <div className="mb-1 flex items-baseline justify-between">
        <h3 className="text-[20px]">Fill the facts</h3>
        <span className="font-mono text-[11px] text-verify-ink">{items.length} to fill</span>
      </div>
      <p className="mb-4 text-[13px] text-muted">Your words replace each marker exactly as written. Leave one blank to keep it.</p>
      <div className="space-y-3">
        {items.map((it, i) => (
          <label key={i} className="block">
            <span className="mb-1 flex gap-2 text-[12.5px] text-ink-2">
              <span className="font-mono text-muted">{i + 1}.</span>
              <span className="verify-mark !text-[11px]">{it}</span>
            </span>
            <input
              value={answers[i] ?? ""}
              onChange={(e) => setAnswers((a) => a.map((x, j) => (j === i ? e.target.value : x)))}
              className="h-10 w-full rounded-md border border-hairline bg-paper px-3 text-[14px] outline-none placeholder:text-muted focus:border-sage"
              placeholder="The real fact, in your words"
            />
          </label>
        ))}
      </div>
      <div className="mt-4 flex justify-end">
        <button className="btn btn-primary" onClick={() => fill.mutate()} disabled={fill.isPending || answers.every((a) => !a.trim())}>
          {fill.isPending && <Spinner />} Fill {answers.filter((a) => a.trim()).length || ""} fact(s)
        </button>
      </div>
    </section>
  );
}
