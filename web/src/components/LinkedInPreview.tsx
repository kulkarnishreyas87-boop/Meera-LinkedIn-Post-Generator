import { useEffect, useRef } from "react";
import { Paragraphs } from "./ui";

export function LinkedInPreview({
  body,
  editing,
  onChange,
  meta,
}: {
  body: string;
  editing: boolean;
  onChange: (v: string) => void;
  meta: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 4}px`;
  }, [body, editing]);

  return (
    <article className="card overflow-hidden" aria-label="LinkedIn-style preview">
      <div className="flex items-center gap-3 px-5 pb-3 pt-5 sm:px-6">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-sage-soft font-serif text-[18px] text-sage-ink ring-1 ring-hairline">
          MP
        </div>
        <div className="min-w-0 leading-tight">
          <div className="text-[15px] font-semibold text-ink">Meera Pillai</div>
          <div className="truncate text-[12.5px] text-muted">Founder, Skinstinct · Formulation, ex-pharma</div>
          <div className="mt-0.5 font-mono text-[10.5px] text-muted">{meta}</div>
        </div>
      </div>
      <div className="px-5 pb-6 pt-1 sm:px-6">
        {editing ? (
          <textarea
            ref={ref}
            value={body}
            onChange={(e) => onChange(e.target.value)}
            className="block w-full resize-none rounded-md border border-dashed border-sage/60 bg-paper/60 p-3 text-[15px] leading-[1.62] text-ink outline-none focus:border-sage"
            aria-label="Edit draft"
            spellCheck
          />
        ) : (
          <Paragraphs text={body} className="text-[15px] leading-[1.62] text-ink" />
        )}
      </div>
      <div className="flex items-center justify-between border-t border-hairline-2 bg-paper-2/60 px-5 py-2.5 sm:px-6">
        <span className="label">Preview only · not posted</span>
        <span className="font-mono text-[10.5px] text-muted">Like · Comment · Repost</span>
      </div>
    </article>
  );
}
