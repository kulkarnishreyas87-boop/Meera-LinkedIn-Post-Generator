export type NoteStatus = "new" | "triaged" | "drafted" | "approved" | "discarded";
export type DraftStatus = "pending" | "needs_facts" | "approved" | "discarded" | "superseded";
export type Decision = "auto_approved" | "auto_discarded" | "needs_facts" | "review" | "approved" | "discarded";

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

export type Tier = "regulator" | "journal" | "press" | "trade" | "other";

export interface Source {
  role: "news angle" | "supports a claim";
  title: string;
  publisher: string;
  url: string;
  published?: string | null;
  tier: Tier;
  tier_label: string;
  via?: string;
  link_is_publisher?: boolean;
  claim?: string;
}

export interface ClaimResult {
  claim: string;
  verdict: "supported" | "contradicted" | "unclear";
  explanation: string;
  source: { title: string; publisher: string; url: string; tier: Tier; tier_label: string } | null;
}

export interface Checklist {
  claim_check?: { claims: ClaimResult[]; supported: number; contradicted: number; unclear: number };
  word_count?: number;
  word_range?: [number, number];
  verify_count?: number;
  verify_items?: string[];
  checks?: Check[];
  self_check?: SelfCheck[];
  hard_failures?: string[];
  review?: { voice_score: number | null; top_issue: string | null; invented_claims?: string[] };
  quality?: { score: number | null; voice?: number | null; self_check?: string | null; note_score?: number; format_failures?: number; invented?: number; formula?: string };
  auto_redraft_of_score?: number | null;
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
  news_published: string | null;
  news_tier: Tier | null;
  news_via: "google_news" | "google_search" | null;
  sources: Source[] | null;
  first_comment: string;
  checklist: Checklist;
  reviewer_notes: string | null;
  quality_score: number | null;
  decision: Decision | null;
  decided_by: "auto" | "meera" | null;
  decision_reason: string | null;
  telegram_message_id: number | null;
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
  auto_review: boolean;
  auto_approve_min: number;
  auto_discard_below: number;
  auto_counts: { auto_approved: number; auto_discarded: number };
}

export interface ImportResult {
  imported: number;
  skipped: number;
  notes: Note[];
}
