import { useState } from "react";
import type { Check, Checklist } from "../lib/types";

function Mark({ state }: { state: boolean | null | "info" | "warn" }) {
  if (state === true)
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" className="shrink-0 text-sage" aria-label="passed">
        <circle cx="8" cy="8" r="7.25" fill="none" stroke="currentColor" strokeOpacity="0.35" />
        <path d="M4.8 8.3l2.1 2.1 4.3-4.6" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
      </svg>
    );
  if (state === false)
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" className="shrink-0 text-clay" aria-label="failed">
        <circle cx="8" cy="8" r="7.25" fill="none" stroke="currentColor" strokeOpacity="0.5" />
        <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  if (state === "warn" || state === "info")
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" className={`shrink-0 ${state === "warn" ? "text-ochre" : "text-muted"}`} aria-label={state}>
        <circle cx="8" cy="8" r="7.25" fill="none" stroke="currentColor" strokeOpacity="0.5" />
        <path d="M8 4.5v4.2M8 11.2v.3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  return <span className="h-4 w-4 shrink-0 rounded-full border border-dashed border-hairline" aria-label="unknown" />;
}

function checkState(c: Check): boolean | "info" | "warn" {
  if (c.passed) return true;
  if (c.severity === "info") return "info";
  if (c.severity === "warning") return "warn";
  return false;
}

export function ChecklistPanel({ checklist }: { checklist: Checklist }) {
  const [open, setOpen] = useState(false);
  const checks = checklist.checks ?? [];
  const self = checklist.self_check ?? [];
  const failures = checks.filter((c) => !c.passed && c.severity === "error").length + self.filter((s) => s.passed === false).length;

  return (
    <section className="card p-5 sm:p-6">
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h3 className="text-[20px]">Self-check</h3>
        <span className={`font-mono text-[11px] ${failures ? "text-clay" : "text-sage-ink"}`}>
          {failures ? `${failures} to fix` : "all clear"}
          {checklist.revised ? " · auto-revised once" : ""}
          {checklist.edited ? " · edited" : ""}
        </span>
      </div>

      <div className="label mb-2">Format · checked in code</div>
      <ul className="mb-6 grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {checks.map((c) => (
          <li key={c.id} className="flex items-start gap-2.5 text-[13.5px]" title={c.detail}>
            <Mark state={checkState(c)} />
            <span className={c.passed ? "text-ink-2" : "text-ink"}>
              {c.label}
              {!c.passed && c.detail && <span className="block font-mono text-[11px] text-muted">{c.detail}</span>}
            </span>
          </li>
        ))}
      </ul>

      {self.length > 0 && (
        <>
          <button className="label mb-2 flex w-full items-center justify-between" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            <span>Voice · skill self-check questions</span>
            <span className="font-mono normal-case tracking-normal">
              {self.filter((s) => s.passed).length}/{self.length} {open ? "−" : "+"}
            </span>
          </button>
          <ol className="space-y-2.5">
            {self.map((s) => (
              <li key={s.n} className="flex items-start gap-2.5 text-[13.5px]">
                <Mark state={s.passed} />
                <div className="min-w-0">
                  <span className={open ? "text-ink" : "line-clamp-1 text-ink-2"}>
                    <span className="font-mono text-[11px] text-muted">{s.n}. </span>
                    {s.question}
                  </span>
                  {(open || s.passed === false) && s.note && <span className="block font-serif text-[13px] italic text-muted">{s.note}</span>}
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
