export type NoteStatus = "new" | "triaged" | "drafted" | "approved" | "discarded";
export type DraftStatus = "pending" | "approved" | "discarded" | "superseded";

export const CATEGORIES = [
  "Ingredient Deep-Dive",
  "Founder Story",
  "India-Specific Context",
  "Industry Transparency",
] as const;
export type Category = (typeof CATEGORIES)[number];

export interface Check {
  id: string;
  label: string;
  passed: boolean;
  detail: string;
  severity: "error" | "warning" | "info";
}

export interface SelfCheck {
  n: number;
  question: string;
  passed: boolean | null;
  note: string;
}

export interface Checklist {
  word_count?: number;
  word_range?: [number, number];
  verify_count?: number;
  verify_items?: string[];
  checks?: Check[];
  self_check?: SelfCheck[];
  hard_failures?: string[];
  passed?: boolean;
  revised?: boolean;
  edited?: boolean;
}

export interface Draft {
  id: number;
  note_id: number;
  version: number;
  body: string;
  status: DraftStatus;
  redraft_instruction: string | null;
  news_found: boolean;
  news_title: string | null;
  news_source: string | null;
  news_url: string | null;
  news_summary: string | null;
  news_note: string | null;
  checklist: Checklist;
  reviewer_notes: string | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
}

export interface Note {
  id: number;
  text: string;
  source: string;
  filename: string | null;
  telegram_message_id: number | null;
  received_at: string;
  status: NoteStatus;
  score: number | null;
  publishable: boolean | null;
  category: Category | null;
  core_insight: string | null;
  suggested_hook_type: string | null;
  missing_facts: string[];
  reason: string | null;
  triaged_at: string | null;
  current_draft_id: number | null;
  current_draft_status: DraftStatus | null;
}

export interface NoteDetail extends Note {
  drafts: Draft[];
}

export interface Week {
  target: number;
  approved_count: number;
  week_start: string;
  week_end: string;
  next_run: string | null;
  approved: Draft[];
  queue: Draft[];
  queue_notes: Record<string, Note>;
}

export interface Status {
  counts: Record<NoteStatus | "not_now", number>;
  model: string;
  threshold: number;
  gemini_configured: boolean;
  telegram_configured: boolean;
  bot_running: boolean;
  scheduler_running: boolean;
}

export interface ImportResult {
  imported: number;
  skipped: number;
  notes: Note[];
}
