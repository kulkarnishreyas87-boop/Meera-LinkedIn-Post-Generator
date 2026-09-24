import type { Category } from "./types";

const IST: Intl.DateTimeFormatOptions = { timeZone: "Asia/Kolkata" };
const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

export function stamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const [dd, mm] = d.toLocaleDateString("en-GB", { ...IST, day: "2-digit", month: "numeric" }).split("/");
  const day = `${dd} ${MONTHS[Number(mm) - 1]}`;
  const time = d.toLocaleTimeString("en-GB", { ...IST, hour: "2-digit", minute: "2-digit", hour12: false });
  return `${day} · ${time}`;
}

export function longDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-GB", { ...IST, weekday: "long", day: "numeric", month: "long" });
}

export function relative(iso: string | null | undefined): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const pad = (n: number | null | undefined, w = 3) => (n == null ? "—" : String(n).padStart(w, "0"));

/** Periodic-table style codes for the skill's four content pillars. */
export const CATEGORY_META: Record<Category, { code: string; n: number; short: string }> = {
  "Ingredient Deep-Dive": { code: "Id", n: 1, short: "Ingredient" },
  "Founder Story": { code: "Fs", n: 2, short: "Founder" },
  "India-Specific Context": { code: "In", n: 3, short: "India" },
  "Industry Transparency": { code: "Tr", n: 4, short: "Transparency" },
};

export const VERIFY_RE = /\[VERIFY:[^\]]*\]/gi;

export function countWords(text: string): number {
  const t = text.replace(VERIFY_RE, " X ");
  return (t.match(/[A-Za-z0-9À-ɏ]+(?:['’.,%-][A-Za-z0-9]+)*/g) || []).length;
}

export function countVerify(text: string): number {
  return (text.match(VERIFY_RE) || []).length;
}
