import { motion } from "framer-motion";
import { useEffect, useState } from "react";

const STEPS = [
  { label: "Scoring the note", at: 0 },
  { label: "Searching for a current news angle", at: 6 },
  { label: "Drafting in Meera's voice", at: 20 },
  { label: "Running the self-check", at: 45 },
];

/** Staged progress for the ~1 minute drafting call. Timing is approximate. */
export function DraftingProgress({ title = "Drafting" }: { title?: string }) {
  const [t, setT] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setT((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const active = STEPS.reduce((acc, s, i) => (t >= s.at ? i : acc), 0);

  return (
    <div className="card p-6" role="status" aria-live="polite">
      <div className="mb-5 flex items-baseline justify-between">
        <h3 className="text-xl">{title}…</h3>
        <span className="font-mono text-[12px] tabular-nums text-muted">{String(t).padStart(2, "0")}s</span>
      </div>
      <ol className="space-y-3">
        {STEPS.map((s, i) => (
          <li key={s.label} className="flex items-center gap-3 text-[14px]">
            <span className="relative flex h-4 w-4 items-center justify-center">
              {i < active ? (
                <svg width="14" height="14" viewBox="0 0 14 14" className="text-sage">
                  <path d="M3 7.5l2.5 2.5L11 4.5" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" />
                </svg>
              ) : i === active ? (
                <motion.span
                  className="h-2 w-2 rounded-full bg-sage"
                  animate={{ scale: [1, 1.5, 1], opacity: [1, 0.5, 1] }}
                  transition={{ duration: 1.4, repeat: Infinity }}
                />
              ) : (
                <span className="h-1.5 w-1.5 rounded-full bg-hairline" />
              )}
            </span>
            <span className={i <= active ? "text-ink" : "text-muted"}>{s.label}</span>
          </li>
        ))}
      </ol>
      <div className="mt-6 h-px overflow-hidden bg-hairline">
        <motion.div
          className="h-px bg-sage"
          initial={{ width: "2%" }}
          animate={{ width: `${Math.min(95, 2 + t * 1.5)}%` }}
          transition={{ ease: "linear", duration: 1 }}
        />
      </div>
      <p className="mt-3 text-[12.5px] text-muted">Usually under a minute. You can leave this page; the draft also arrives in Telegram.</p>
    </div>
  );
}
