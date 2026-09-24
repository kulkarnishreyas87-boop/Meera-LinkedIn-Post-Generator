import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { useDraftRunner } from "../components/Layout";
import { useToast } from "../components/Toast";
import { CategoryTile, EmptyState, noteDisplayStatus, PageHeader, ScoreChip, Skeleton, Spinner, StatusPill } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { pad } from "../lib/format";

const OK = /\.(txt|md)$/i;

/** Walk dropped folders (Chromium/Safari/Firefox support webkitGetAsEntry). */
async function filesFromDrop(e: DragEvent): Promise<File[]> {
  const items = Array.from(e.dataTransfer.items ?? []);
  const entries = items.map((i) => i.webkitGetAsEntry?.()).filter(Boolean) as FileSystemEntry[];
  if (!entries.length) return Array.from(e.dataTransfer.files);
  const out: File[] = [];
  const walk = async (entry: FileSystemEntry): Promise<void> => {
    if (entry.isFile) {
      out.push(await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej)));
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      let batch: FileSystemEntry[];
      do {
        batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
        for (const child of batch) await walk(child);
      } while (batch.length);
    }
  };
  for (const en of entries) await walk(en);
  return out;
}

function DropZone() {
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const upload = useMutation({
    mutationFn: (files: File[]) => api.importFiles(files),
    onSuccess: (r) => {
      toast(`Imported ${r.imported} note${r.imported === 1 ? "" : "s"}${r.skipped ? ` · ${r.skipped} duplicate or empty skipped` : ""}`, "success");
      qc.invalidateQueries();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Import failed", "error"),
  });
  const send = (files: File[]) => {
    const ok = files.filter((f) => OK.test(f.name));
    if (!ok.length) return toast("No .txt or .md files found", "error");
    upload.mutate(ok);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={async (e) => {
        e.preventDefault();
        setOver(false);
        send(await filesFromDrop(e));
      }}
      className={`relative flex flex-col items-center justify-center rounded-[10px] border-[1.5px] border-dashed px-6 py-10 text-center transition-colors ${
        over ? "border-sage bg-sage-soft" : "border-hairline bg-card/60"
      }`}
    >
      <svg width="40" height="40" viewBox="0 0 40 40" fill="none" className={`mb-3 ${over ? "text-sage" : "text-muted"}`} aria-hidden>
        <path d="M8 12a3 3 0 0 1 3-3h6l3 3h9a3 3 0 0 1 3 3v13a3 3 0 0 1-3 3H11a3 3 0 0 1-3-3V12z" stroke="currentColor" strokeWidth="1.4" />
        <path d="M20 17v9M16 22l4 4 4-4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <h3 className="text-[20px]">{upload.isPending ? "Importing…" : "Drop the notes folder here"}</h3>
      <p className="mt-1 text-[13.5px] text-muted">.txt and .md files · folders are read recursively · duplicates skipped</p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        <button className="btn" onClick={() => dirRef.current?.click()} disabled={upload.isPending}>
          {upload.isPending && <Spinner />} Choose folder
        </button>
        <button className="btn btn-ghost" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
          Choose files
        </button>
      </div>
      <input ref={fileRef} type="file" multiple accept=".txt,.md" className="hidden" onChange={(e) => e.target.files && send(Array.from(e.target.files))} />
      <input
        ref={dirRef}
        type="file"
        multiple
        className="hidden"
        // @ts-expect-error non-standard but widely supported folder picker
        webkitdirectory=""
        onChange={(e) => e.target.files && send(Array.from(e.target.files))}
      />
    </div>
  );
}

function QuickAdd() {
  const [text, setText] = useState("");
  const qc = useQueryClient();
  const toast = useToast();
  const add = useMutation({
    mutationFn: () => api.addNote(text),
    onSuccess: () => {
      setText("");
      toast("Note added", "success");
      qc.invalidateQueries();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Couldn't add note", "error"),
  });
  return (
    <div className="card p-4">
      <label htmlFor="quick" className="label mb-2 block">
        Or jot one down
      </label>
      <textarea
        id="quick"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="An observation, a number, a scene…"
        className="w-full resize-none rounded-md border border-hairline bg-paper p-3 text-[14px] outline-none placeholder:text-muted focus:border-sage"
      />
      <div className="mt-2 flex justify-end">
        <button className="btn" onClick={() => add.mutate()} disabled={!text.trim() || add.isPending}>
          Add note
        </button>
      </div>
    </div>
  );
}

export function Backlog() {
  const { data: notes, isLoading } = useQuery({ queryKey: ["backlog"], queryFn: api.backlog });
  const { data: st } = useQuery({ queryKey: ["status"], queryFn: api.status });
  const { run, running } = useDraftRunner();
  const qc = useQueryClient();
  const toast = useToast();
  const threshold = st?.threshold ?? 7;
  const scoreAll = useMutation({
    mutationFn: api.triagePending,
    onSuccess: (r) => {
      toast(`Scored ${r.length} note${r.length === 1 ? "" : "s"}`, "success");
      qc.invalidateQueries();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Scoring failed", "error"),
  });

  const ranked = notes?.filter((n) => n.score != null) ?? [];
  const unscored = notes?.filter((n) => n.score == null) ?? [];

  return (
    <>
      <PageHeader eyebrow={`Backlog · ${ranked.length} ranked · ${unscored.length} unscored`} title="The shelf, ranked.">
        {unscored.length > 0 && (
          <button className="btn" onClick={() => scoreAll.mutate()} disabled={scoreAll.isPending}>
            {scoreAll.isPending && <Spinner />} Score {unscored.length} new
          </button>
        )}
      </PageHeader>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,7fr)_minmax(0,4fr)]">
        <section className="order-2 lg:order-1">
          {isLoading ? (
            <div className="space-y-2">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-20" />)}</div>
          ) : !notes?.length ? (
            <EmptyState title="The backlog is empty">Import the notes folder or drop notes into Telegram. Drafted and approved notes leave the backlog.</EmptyState>
          ) : (
            <ol className="card divide-y divide-hairline-2 overflow-hidden">
              {[...ranked, ...unscored].map((n, i) => {
                const ready = n.score != null && n.score >= threshold && n.publishable;
                return (
                  <motion.li
                    key={n.id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: Math.min(i, 15) * 0.02 }}
                    className="flex items-center gap-3 px-4 py-3.5 sm:gap-4 sm:px-5"
                  >
                    <span className="w-6 shrink-0 text-right font-mono text-[12px] tabular-nums text-muted">{n.score != null ? i + 1 : "·"}</span>
                    <ScoreChip score={n.score} threshold={threshold} size="sm" />
                    <Link to={`/studio/${n.id}`} className="min-w-0 flex-1">
                      <p className="line-clamp-1 text-[14.5px] text-ink hover:underline hover:decoration-hairline hover:underline-offset-4">{n.text}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-[10.5px] text-muted">
                        <span>#{pad(n.id)}</span>
                        {n.category && <CategoryTile category={n.category} compact />}
                        {!ready && n.score != null && <StatusPill status={noteDisplayStatus(n)} />}
                      </div>
                    </Link>
                    <button
                      className={`btn h-8 shrink-0 !px-3 ${ready ? "" : "btn-ghost"}`}
                      onClick={() => run(`Drafting note #${pad(n.id)}`, () => api.draftNote(n.id))}
                      disabled={!!running}
                    >
                      Draft
                    </button>
                  </motion.li>
                );
              })}
            </ol>
          )}
        </section>
        <aside className="order-1 space-y-4 lg:order-2">
          <DropZone />
          <QuickAdd />
        </aside>
      </div>
    </>
  );
}
