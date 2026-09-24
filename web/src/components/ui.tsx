import { Fragment, type ReactNode } from "react";
import { CATEGORY_META, VERIFY_RE } from "../lib/format";
import type { Category, DraftStatus, NoteStatus } from "../lib/types";

/* ---------- score chip: reads like an assay value ---------- */
export function ScoreChip({ score, threshold = 7, size = "md" }: { score: number | null; threshold?: number; size?: "sm" | "md" | "lg" }) {
  const tone =
    score == null ? "text-muted border-hairline" : score >= threshold ? "text-sage-ink border-sage bg-sage-soft" : score >= 5 ? "text-ochre border-hairline" : "text-muted border-hairline";
  const dims = size === "lg" ? "h-14 w-14 text-xl" : size === "sm" ? "h-8 w-8 text-[12px]" : "h-10 w-10 text-sm";
  return (
    <div
      className={`relative inline-flex shrink-0 flex-col items-center justify-center rounded-full border font-mono tabular-nums ${tone} ${dims}`}
      title={score == null ? "Not scored yet" : `Triage score ${score}/10 (threshold ${threshold})`}
      aria-label={score == null ? "Not scored" : `Score ${score} out of 10`}
    >
      <span className="leading-none">{score ?? "·"}</span>
      {size !== "sm" && <span className="mt-0.5 text-[8px] leading-none tracking-widest opacity-70">/10</span>}
    </div>
  );
}

/* ---------- category: periodic-table tile ---------- */
export function CategoryTile({ category, active = false, compact = false }: { category: Category | null; active?: boolean; compact?: boolean }) {
  if (!category) return <span className="label">uncategorised</span>;
  const m = CATEGORY_META[category];
  if (compact)
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] text-ink-2">
        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-[3px] border border-hairline px-1 font-mono text-[10.5px] text-sage-ink">
          {m.code}
        </span>
        {m.short}
      </span>
    );
  return (
    <span
      className={`inline-flex items-stretch overflow-hidden rounded-md border text-[12px] transition-colors ${
        active ? "border-ink bg-ink text-paper" : "border-hairline text-ink-2"
      }`}
    >
      <span className={`flex w-7 flex-col items-center justify-center border-r font-mono ${active ? "border-paper/20" : "border-hairline"}`}>
        <span className="text-[8px] leading-none opacity-60">{m.n}</span>
        <span className="text-[12px] leading-tight">{m.code}</span>
      </span>
      <span className="flex items-center px-2 py-1">{m.short}</span>
    </span>
  );
}

/* ---------- status ---------- */
const STATUS_STYLE: Record<string, string> = {
  new: "text-ink-2 border-hairline",
  triaged: "text-ink-2 border-hairline",
  not_now: "text-muted border-hairline border-dashed",
  drafted: "text-ochre border-ochre/40",
  pending: "text-ochre border-ochre/40",
  approved: "text-sage-ink border-sage bg-sage-soft",
  discarded: "text-muted border-hairline line-through",
  superseded: "text-muted border-hairline",
};
const STATUS_LABEL: Record<string, string> = { not_now: "not now", pending: "in review" };

export function StatusPill({ status }: { status: NoteStatus | DraftStatus | "not_now" }) {
  return (
    <span className={`inline-flex h-5 items-center rounded-full border px-2 font-mono text-[10.5px] uppercase tracking-wider ${STATUS_STYLE[status]}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function noteDisplayStatus(n: { status: NoteStatus; publishable: boolean | null }): NoteStatus | "not_now" {
  return n.status === "triaged" && n.publishable === false ? "not_now" : n.status;
}

/* ---------- [VERIFY] highlighting ---------- */
export function VerifyText({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(VERIFY_RE)) {
    const i = m.index ?? 0;
    parts.push(<Fragment key={`t${i}`}>{text.slice(last, i)}</Fragment>);
    parts.push(
      <mark key={`v${i}`} className="verify-mark" title="Needs verifying before posting">
        {m[0]}
      </mark>,
    );
    last = i + m[0].length;
  }
  parts.push(<Fragment key="end">{text.slice(last)}</Fragment>);
  return <>{parts}</>;
}

export function Paragraphs({ text, className = "" }: { text: string; className?: string }) {
  return (
    <div className={className}>
      {text
        .split(/\n\s*\n/)
        .filter((p) => p.trim())
        .map((p, i) => (
          <p key={i} className="mb-[1.05em] whitespace-pre-line last:mb-0">
            <VerifyText text={p.trim()} />
          </p>
        ))}
    </div>
  );
}

/* ---------- skeletons & empty states ---------- */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function CardSkeleton() {
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 space-y-3">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-3 w-2/3" />
        </div>
        <Skeleton className="h-10 w-10 rounded-full" />
      </div>
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center px-6 py-14 text-center">
      <svg width="56" height="56" viewBox="0 0 56 56" fill="none" className="mb-5 text-hairline" aria-hidden>
        <path d="M22 8h12M24 8v14L12 42a4 4 0 0 0 3.5 6h25a4 4 0 0 0 3.5-6L32 22V8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M17 36h22" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2 3" />
      </svg>
      <h3 className="text-xl text-ink">{title}</h3>
      {children && <div className="mt-2 max-w-md text-[14px] text-muted">{children}</div>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function PageHeader({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-col gap-4 border-b border-hairline pb-6 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <div className="label mb-2">{eyebrow}</div>
        <h1 className="text-[34px] leading-[1.05] text-ink sm:text-[42px]">{title}</h1>
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </header>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}
