import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import type { Draft } from "../lib/types";
import { useToast } from "./Toast";
import { Spinner } from "./ui";

/* ---------- global drafting runner (so progress survives navigation) ---------- */
interface Runner {
  running: string | null;
  run: (label: string, fn: () => Promise<Draft>) => Promise<Draft | null>;
}
const RunnerCtx = createContext<Runner>({ running: null, run: async () => null });
export const useDraftRunner = () => useContext(RunnerCtx);

function RunnerProvider({ children }: { children: ReactNode }) {
  const [running, setRunning] = useState<string | null>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();

  const run = useCallback(
    async (label: string, fn: () => Promise<Draft>) => {
      if (running) {
        toast("A draft is already in progress.", "info");
        return null;
      }
      setRunning(label);
      try {
        const d = await fn();
        const verdict: Record<string, string> = {
          auto_approved: "auto-approved",
          auto_discarded: "auto-discarded (restore it if you disagree)",
          needs_facts: "needs facts",
          review: "your call",
        };
        const score = d.quality_score != null ? ` · ${d.quality_score}/10` : "";
        toast(`Draft ready${score}${d.decision ? ` · ${verdict[d.decision] ?? d.decision}` : ""}`, d.decision === "auto_discarded" ? "info" : "success");
        qc.invalidateQueries();
        navigate(`/studio/${d.note_id}`);
        return d;
      } catch (e) {
        toast(e instanceof ApiError ? e.message : "Drafting failed. Check the server log.", "error");
        qc.invalidateQueries();
        return null;
      } finally {
        setRunning(null);
      }
    },
    [running, qc, toast, navigate],
  );
  return <RunnerCtx.Provider value={{ running, run }}>{children}</RunnerCtx.Provider>;
}

/* ---------- theme ---------- */
function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("theme", dark ? "dark" : "light");
    } catch {
      /* storage unavailable */
    }
  }, [dark]);
  return [dark, () => setDark((d) => !d)] as const;
}

const NAV = [
  { to: "/", label: "Inbox", n: "01", icon: "M4 6h16M4 12h16M4 18h10" },
  { to: "/studio", label: "Draft Studio", n: "02", icon: "M5 19l3.5-1 9-9a1.8 1.8 0 0 0-2.5-2.5l-9 9L5 19z" },
  { to: "/week", label: "This Week", n: "03", icon: "M4 7h16v13H4zM4 11h16M9 4v5M15 4v5" },
  { to: "/backlog", label: "Backlog", n: "04", icon: "M9 4h6M10 4v6l-5 9a1.5 1.5 0 0 0 1.3 2h11.4a1.5 1.5 0 0 0 1.3-2l-5-9V4" },
];

function Icon({ d, className = "" }: { d: string; className?: string }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className={className} aria-hidden>
      <path d={d} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Wordmark() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-md bg-sage text-paper">
        <Icon d="M9 4h6M10 4v6l-5 9a1.5 1.5 0 0 0 1.3 2h11.4a1.5 1.5 0 0 0 1.3-2l-5-9V4" />
      </span>
      <div className="leading-tight">
        <div className="font-serif text-[19px] tracking-tight text-ink">Draft Lab</div>
        <div className="label !text-[9.5px]">Skinstinct · M. Pillai</div>
      </div>
    </div>
  );
}

function StatusLine() {
  const { data } = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 30_000 });
  if (!data) return <div className="h-4" />;
  const dot = (ok: boolean) => <span className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? "bg-sage" : "bg-clay"}`} />;
  return (
    <div className="space-y-1.5 font-mono text-[10.5px] text-muted">
      <div className="flex items-center gap-2">{dot(data.gemini_configured)} {data.model}</div>
      <div className="flex items-center gap-2">{dot(data.bot_running)} telegram {data.bot_running ? "live" : "off"}</div>
      <div className="flex items-center gap-2">{dot(data.scheduler_running)} triage ≥{data.threshold}/10</div>
      <div className="flex items-center gap-2" title="Draft auto-review rule">
        {dot(data.auto_review)} {data.auto_review ? `auto ≥${data.auto_approve_min} ✓ · <${data.auto_discard_below} ✗` : "auto-review off"}
      </div>
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  return (
    <RunnerProvider>
      <Shell>{children}</Shell>
    </RunnerProvider>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const [dark, toggle] = useTheme();
  const { running, run } = useDraftRunner();
  const loc = useLocation();

  const isActive = (to: string) => (to === "/" ? loc.pathname === "/" : loc.pathname.startsWith(to));

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
      {/* desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen flex-col justify-between border-r border-hairline bg-paper/80 px-5 py-6 backdrop-blur lg:flex">
        <div>
          <Wordmark />
          <nav className="mt-10 space-y-0.5" aria-label="Main">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={`group flex items-center gap-3 rounded-md px-3 py-2 text-[14px] transition-colors ${
                  isActive(n.to) ? "bg-card text-ink shadow-paper" : "text-ink-2 hover:bg-paper-2"
                }`}
              >
                <span className="font-mono text-[10.5px] text-muted">{n.n}</span>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <button className="btn btn-primary mt-8 w-full" onClick={() => run("Drafting the next best note", api.draftNext)} disabled={!!running}>
            {running ? <Spinner /> : <Icon d="M12 5v14M5 12h14" className="-ml-1" />}
            {running ? "Drafting…" : "Draft next best note"}
          </button>
        </div>
        <div className="space-y-5">
          <div className="rounded-md border border-dashed border-hairline p-3 text-[12px] leading-snug text-muted">
            Drafts only. Nothing here posts to LinkedIn - approve, copy, and publish it yourself.
          </div>
          <div className="flex items-end justify-between">
            <StatusLine />
            <button className="btn btn-ghost h-8 w-8 !px-0" onClick={toggle} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}>
              <Icon d={dark ? "M12 4v1m0 14v1m8-8h-1M5 12H4m13.66-5.66-.7.7M7.05 16.95l-.7.7m11.31 0-.7-.7M7.05 7.05l-.7-.7M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0z" : "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"} />
            </button>
          </div>
        </div>
      </aside>

      {/* mobile top bar */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-hairline bg-paper/90 px-4 py-3 backdrop-blur lg:hidden">
        <Wordmark />
        <div className="flex items-center gap-1">
          <button className="btn btn-ghost h-9 w-9 !px-0" onClick={toggle} aria-label="Toggle dark mode">
            <Icon d={dark ? "M12 4v1m0 14v1m8-8h-1M5 12H4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0z" : "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"} />
          </button>
          <button className="btn btn-primary h-9" onClick={() => run("Drafting the next best note", api.draftNext)} disabled={!!running} aria-label="Draft next best note">
            {running ? <Spinner /> : <Icon d="M12 5v14M5 12h14" />}
            <span className="hidden sm:inline">{running ? "Drafting…" : "Draft next"}</span>
          </button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1180px] px-4 pb-28 pt-6 sm:px-8 lg:pb-16 lg:pt-12">
        <AnimatePresence>
          {running && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mb-6 overflow-hidden"
            >
              <div className="flex items-center gap-3 rounded-full border border-sage/40 bg-sage-soft px-4 py-2 text-[13px] text-ink">
                <Spinner className="text-sage" /> {running}… this takes about a minute.
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <motion.div key={loc.pathname.split("/")[1]} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.28, ease: [0.2, 0.7, 0.2, 1] }}>
          {children}
        </motion.div>
      </main>

      {/* mobile tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-hairline bg-paper/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden" aria-label="Main">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} className={`flex flex-col items-center gap-1 py-2.5 text-[11px] ${isActive(n.to) ? "text-ink" : "text-muted"}`}>
            <Icon d={n.icon} />
            {n.label.replace("Draft ", "")}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
