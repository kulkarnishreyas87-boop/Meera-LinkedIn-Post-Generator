import type { Draft, ImportResult, Note, NoteDetail, Status, Week } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const data = await res.json();
      msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  status: () => req<Status>("/status"),
  notes: (params: { status?: string; category?: string } = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return req<Note[]>(`/notes${q.toString() ? `?${q}` : ""}`);
  },
  note: (id: number) => req<NoteDetail>(`/notes/${id}`),
  addNote: (text: string) => post<Note>("/notes", { text }),
  importFiles: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    return req<ImportResult>("/notes/import", { method: "POST", body: fd });
  },
  triage: (id: number) => post<Note>(`/notes/${id}/triage`),
  triagePending: () => post<Note[]>("/triage-pending"),
  draftNote: (id: number) => post<Draft>(`/notes/${id}/draft`, {}),
  draftNext: () => post<Draft>("/draft-next"),
  backlog: () => req<Note[]>("/backlog"),
  editDraft: (id: number, body: string) => req<Draft>(`/drafts/${id}`, { method: "PATCH", body: JSON.stringify({ body }) }),
  approve: (id: number) => post<Draft>(`/drafts/${id}/approve`),
  discard: (id: number) => post<Draft>(`/drafts/${id}/discard`),
  redraft: (id: number, instruction: string) => post<Draft>(`/drafts/${id}/redraft`, { instruction }),
  reopen: (id: number) => post<Draft>(`/drafts/${id}/reopen`),
  fill: (id: number, answers: string[]) => post<Draft>(`/drafts/${id}/fill`, { answers }),
  week: () => req<Week>("/week"),
};
