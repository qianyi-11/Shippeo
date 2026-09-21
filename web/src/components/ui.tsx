import { ReactNode, useEffect, useState } from "react";
import type { FieldState } from "../lib/api";

/* ---------- status vocabulary: plain label first, theme label second ---------- */

export const REALITY: Record<string, { label: string; theme: string; color: string; icon: string }> = {
  converged: { label: "Match", theme: "Converged Reality", color: "var(--color-match)", icon: "✓" },
  diverging: { label: "Mismatch", theme: "Diverging Reality", color: "var(--color-miss)", icon: "✕" },
  unresolved: { label: "Needs review", theme: "Unresolved Reality", color: "var(--color-review)", icon: "?" },
  incomplete: { label: "Incomplete", theme: "Incomplete Reality", color: "var(--color-void)", icon: "∅" },
};

export const STATE: Record<FieldState, { label: string; color: string; icon: string; line: "solid" | "soft" | "broken" | "dashed" | "void" }> = {
  match_confirmed: { label: "Match", color: "var(--color-match)", icon: "✓", line: "solid" },
  normalized_match: { label: "Normalized match", color: "var(--color-norm)", icon: "≈", line: "soft" },
  mismatch_confirmed: { label: "Mismatch", color: "var(--color-miss)", icon: "✕", line: "broken" },
  missing_in_si: { label: "Missing in SI", color: "var(--color-void)", icon: "∅", line: "void" },
  missing_in_bl: { label: "Missing in BL", color: "var(--color-void)", icon: "∅", line: "void" },
  unreadable: { label: "Unreadable", color: "var(--color-review)", icon: "?", line: "dashed" },
  ambiguous_needs_review: { label: "Needs review", color: "var(--color-review)", icon: "?", line: "dashed" },
};

export const CATEGORY: Record<string, string> = {
  document_comparison: "Document comparison",
  new_si_request: "New SI request",
  invoice_query: "Invoice query",
  general_message: "General message",
  spam: "Spam",
  needs_review: "Needs review",
};

export const RISK: Record<string, string> = {
  low: "var(--color-match)", medium: "var(--color-review)", high: "var(--color-miss)", critical: "#ff4d6d",
};

export const PROCESS_LABEL: Record<string, string> = {
  queued: "Queued", classifying: "Classifying", classified: "Classified", locating_documents: "Locating documents",
  extracting: "Extracting", normalizing: "Normalizing", comparing: "Comparing", completed: "Completed",
  needs_review: "Needs review", failed_retry_available: "Failed · retry",
};

export function Chip({ color, icon, children, title, solid }: { color: string; icon?: string; children: ReactNode; title?: string; solid?: boolean }) {
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap"
      style={{
        color: solid ? "#0b1220" : color,
        background: solid ? color : `color-mix(in srgb, ${color} 14%, transparent)`,
        boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${color} 45%, transparent)`,
      }}
    >
      {icon && <span aria-hidden className="font-semibold">{icon}</span>}
      {children}
    </span>
  );
}

export function RealityChip({ status, theme = false }: { status: string | null; theme?: boolean }) {
  if (!status) return <span className="text-mute text-xs">—</span>;
  const r = REALITY[status];
  if (!r) return <span className="text-xs">{status}</span>;
  return <Chip color={r.color} icon={r.icon} title={r.theme}>{r.label}{theme && <span className="opacity-70 font-normal">· {r.theme}</span>}</Chip>;
}

export function StateChip({ state }: { state: FieldState }) {
  const s = STATE[state];
  return <Chip color={s.color} icon={s.icon}>{s.label}</Chip>;
}

export function RiskChip({ level }: { level: string | null }) {
  if (!level) return <span className="text-mute text-xs">—</span>;
  return <Chip color={RISK[level] ?? "var(--color-void)"} icon={level === "critical" ? "‼" : level === "high" ? "▲" : level === "medium" ? "◆" : "●"}>{level[0].toUpperCase() + level.slice(1)} risk</Chip>;
}

export function ProcessChip({ status }: { status: string }) {
  const busy = !["completed", "needs_review", "failed_retry_available"].includes(status);
  const color = status === "failed_retry_available" ? "var(--color-miss)" : status === "needs_review" ? "var(--color-review)" : busy ? "var(--color-norm)" : "var(--color-mute)";
  return <span className={`inline-flex items-center gap-1.5 text-xs ${busy ? "pulse-soft" : ""}`} style={{ color }}>
    <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />{PROCESS_LABEL[status] ?? status}
  </span>;
}

export function Card({ children, className = "", as: As = "section" }: { children: ReactNode; className?: string; as?: any }) {
  return <As className={`rounded-2xl border border-line bg-panel/80 backdrop-blur-sm ${className}`}>{children}</As>;
}

export function Button({ children, onClick, kind = "ghost", disabled, type = "button", className = "", title }:
  { children: ReactNode; onClick?: () => void; kind?: "primary" | "ghost" | "danger" | "quiet"; disabled?: boolean; type?: "button" | "submit"; className?: string; title?: string }) {
  const k = {
    primary: "bg-match text-ink hover:brightness-110 font-semibold",
    ghost: "border border-line text-fog hover:bg-deck",
    danger: "border border-miss/60 text-miss hover:bg-miss/10",
    quiet: "text-mute hover:text-fog",
  }[kind];
  return <button type={type} title={title} disabled={disabled} onClick={onClick}
    className={`inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition disabled:opacity-40 disabled:cursor-not-allowed ${k} ${className}`}>{children}</button>;
}

export function Confidence({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-mute text-xs">—</span>;
  const pct = Math.round(value * 100);
  const color = value >= 0.9 ? "var(--color-match)" : value >= 0.7 ? "var(--color-review)" : "var(--color-miss)";
  return <span className="inline-flex items-center gap-2 text-xs tabular-nums" title={value >= 0.9 ? "High confidence" : value >= 0.7 ? "Medium confidence" : "Low confidence"}>
    <span className="h-1.5 w-12 overflow-hidden rounded-full bg-line" aria-hidden><span className="block h-full" style={{ width: `${pct}%`, background: color }} /></span>
    {pct}%
  </span>;
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-[0.82em] ${className}`}>{children}</span>;
}

export function Logo({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden>
      <rect width="40" height="40" rx="11" fill="#16213a" stroke="#26355a" />
      <path d="M8 14h11l6 6h7" stroke="#6fa8dc" strokeWidth="3" fill="none" strokeLinecap="round" />
      <path d="M8 26h11l6-6" stroke="#2bb5a0" strokeWidth="3" fill="none" strokeLinecap="round" />
      <circle cx="32" cy="20" r="2.6" fill="#2bb5a0" />
    </svg>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <div role="status" className="flex items-center gap-3 text-mute text-sm p-6"><span className="h-4 w-4 rounded-full border-2 border-line border-t-norm animate-spin" />{label}…</div>;
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return <div role="alert" className="rounded-xl border border-miss/50 bg-miss/10 p-4 text-sm text-fog flex items-center justify-between gap-4">
    <span><b className="text-miss">Something went wrong.</b> {error}</span>{onRetry && <Button onClick={onRetry}>Try again</Button>}
  </div>;
}

export function usePoll<T>(fn: () => Promise<T>, deps: unknown[], interval: (d: T | null) => number | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true, timer: number | undefined;
    // A background tab left open during a long-running job shouldn't keep polling the
    // database on a timer — every poll of a list endpoint costs a real Firestore read
    // per document, and those add up fast against the free-tier daily quota.
    const schedule = (ms: number) => {
      timer = window.setTimeout(() => {
        if (document.hidden) { schedule(ms); return; }
        run();
      }, ms);
    };
    const run = async () => {
      try {
        const d = await fn();
        if (!alive) return;
        setData(d); setError(null);
        const ms = interval(d);
        if (ms) schedule(ms);
      } catch (e) { if (alive) setError((e as Error).message); }
    };
    run();
    return () => { alive = false; if (timer) clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, reload: () => setTick(t => t + 1), setData };
}

export function fmtDate(s: string | null | undefined) {
  if (!s) return "—";
  const d = new Date(s);
  return isNaN(+d) ? s : d.toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtVal(v: unknown) {
  if (v == null || v === "") return "—";
  if (typeof v === "number") return v.toLocaleString();
  return String(v);
}
