import type { ClaimResult, Draft, Tier } from "../lib/types";
import { useToast } from "./Toast";

export const TIER_META: Record<Tier, { label: string; cls: string }> = {
  regulator: { label: "Regulator", cls: "border-sage bg-sage-soft text-sage-ink" },
  journal: { label: "Journal", cls: "border-sage/60 bg-sage-soft/60 text-sage-ink" },
  press: { label: "Press", cls: "border-hairline text-ink-2" },
  trade: { label: "Trade press", cls: "border-hairline text-ink-2" },
  other: { label: "Other", cls: "border-dashed border-hairline text-muted" },
};

export function TierBadge({ tier }: { tier: Tier | null | undefined }) {
  if (!tier) return null;
  const m = TIER_META[tier] ?? TIER_META.other;
  return <span className={`inline-flex h-5 items-center rounded-full border px-2 font-mono text-[10px] uppercase tracking-wider ${m.cls}`}>{m.label}</span>;
}

const VERDICT: Record<ClaimResult["verdict"], { icon: string; cls: string; label: string }> = {
  supported: { icon: "✓", cls: "text-sage-ink", label: "Supported" },
  unclear: { icon: "?", cls: "text-ochre", label: "Unclear" },
  contradicted: { icon: "✗", cls: "text-clay", label: "Contradicted" },
};

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Claim check + citable source list for the post. */
export function SourcesPanel({ draft }: { draft: Draft }) {
  const toast = useToast();
  const cc = draft.checklist.claim_check;
  const sources = draft.sources ?? [];
  if (!cc?.claims?.length && !sources.length) return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(draft.first_comment);
      toast("Sources copied - paste them as your first comment", "success");
    } catch {
      toast("Couldn't copy - select the text instead", "error");
    }
  };

  return (
    <section className="card p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[20px]">Sources &amp; claim check</h3>
        {cc && (
          <span className="font-mono text-[11px] text-muted">
            <span className="text-sage-ink">{cc.supported} supported</span> · <span className="text-ochre">{cc.unclear} unclear</span> ·{" "}
            <span className={cc.contradicted ? "text-clay" : ""}>{cc.contradicted} contradicted</span>
          </span>
        )}
      </div>

      {!!cc?.claims?.length && (
        <>
          <div className="label mb-2">Claims in the post · checked with Google Search</div>
          <ul className="mb-6 space-y-3">
            {cc.claims.map((c, i) => {
              const v = VERDICT[c.verdict] ?? VERDICT.unclear;
              return (
                <li key={i} className="flex gap-3 text-[13.5px]">
                  <span className={`mt-0.5 w-4 shrink-0 text-center font-mono ${v.cls}`} aria-label={v.label}>
                    {v.icon}
                  </span>
                  <div className="min-w-0">
                    <p className="text-ink">{c.claim}</p>
                    {c.explanation && <p className={`mt-0.5 font-serif text-[13px] italic ${c.verdict === "contradicted" ? "text-clay" : "text-muted"}`}>{c.explanation}</p>}
                    {c.source && (
                      <a href={c.source.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-2 font-mono text-[11px] text-sage-ink underline decoration-sage/30 underline-offset-4">
                        {c.source.publisher} ↗ <TierBadge tier={c.source.tier} />
                      </a>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {sources.length > 0 && (
        <>
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="label">Citable sources · most credible first</span>
            <button className="btn h-8 !px-3" onClick={copy} title="Copy a 'Sources:' list to paste as the first comment on LinkedIn">
              Copy for first comment
            </button>
          </div>
          <ol className="divide-y divide-hairline-2 rounded-md border border-hairline">
            {sources.map((s, i) => (
              <li key={i} className="flex gap-3 px-3 py-2.5">
                <span className="w-4 shrink-0 pt-0.5 text-right font-mono text-[11px] text-muted">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <a href={s.url} target="_blank" rel="noopener noreferrer" className="line-clamp-2 text-[13.5px] text-ink hover:underline hover:decoration-hairline hover:underline-offset-4">
                    {s.title}
                  </a>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10.5px] text-muted">
                    <span>{s.publisher}</span>
                    <TierBadge tier={s.tier} />
                    {s.published && <span>{s.published}</span>}
                    <span>{s.role}</span>
                    {s.link_is_publisher ? <span title="Links straight to the publisher's own page">· {host(s.url)}</span> : <span>· via redirect</span>}
                  </div>
                </div>
              </li>
            ))}
          </ol>
          <p className="mt-2 text-[12px] text-muted">
            LinkedIn favours posts without links, so these go in the first comment. Press-release wires, blogs and social media are never cited.
          </p>
        </>
      )}
    </section>
  );
}
