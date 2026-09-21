import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, EmailRow, IN_PROGRESS, Stats } from "../lib/api";
import { Button, CATEGORY, Card, Confidence, ErrorBox, ProcessChip, RealityChip, RiskChip, Spinner, fmtDate, usePoll } from "../components/ui";
import UploadDialog from "../components/UploadDialog";

const FILTERS: { key: string; label: string; test: (e: EmailRow) => boolean }[] = [
  { key: "all", label: "All", test: () => true },
  { key: "cmp", label: "Document comparison", test: e => e.category === "document_comparison" },
  { key: "review", label: "Needs review", test: e => (e.openCases ?? 0) > 0 || e.realityStatus === "unresolved" || e.realityStatus === "incomplete" },
  { key: "mismatch", label: "Mismatch detected", test: e => e.realityStatus === "diverging" },
  { key: "clear", label: "No mismatch detected", test: e => e.realityStatus === "converged" },
  { key: "si", label: "New SI request", test: e => e.category === "new_si_request" },
  { key: "inv", label: "Invoice query", test: e => e.category === "invoice_query" },
  { key: "gen", label: "General message", test: e => e.category === "general_message" },
  { key: "spam", label: "Spam", test: e => e.category === "spam" },
  { key: "failed", label: "Processing failed", test: e => e.processingStatus === "failed_retry_available" },
];

const ACTION: Record<string, string> = {
  locate_si_and_bl: "Verify SI vs BL", create_si_task: "Prepare SI", route_invoice_query: "Route to finance",
  classify_only: "No action", ignore_spam: "Ignore", human_review: "Human review",
};

export default function CommandCenter() {
  const nav = useNavigate();
  const [filter, setFilter] = useState("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [upload, setUpload] = useState(false);
  const [busy, setBusy] = useState(false);
  const emails = usePoll(api.emails, [], d => (d?.some(e => IN_PROGRESS.has(e.processingStatus)) ? 15000 : null));
  // Tied to the *presence* of in-progress emails, not emails.data?.length — the old code
  // re-ran this (and its own full collection scan) on every single length change during a
  // bulk ingest, doubling read cost on top of the emails poll above.
  const anyInProgress = emails.data?.some(e => IN_PROGRESS.has(e.processingStatus)) ?? false;
  const stats = usePoll(api.stats, [anyInProgress], () => (anyInProgress ? 15000 : null));

  const counts = useMemo(() => Object.fromEntries(FILTERS.map(f => [f.key, (emails.data ?? []).filter(f.test).length])), [emails.data]);
  const rows = useMemo(() => {
    const f = FILTERS.find(x => x.key === filter)!;
    const needle = q.trim().toLowerCase();
    return (emails.data ?? []).filter(f.test).filter(e => !needle ||
      [e.emailId, e.subject, e.sender, e.shipmentRef, e.searchText].some(v => (v ?? "").toLowerCase().includes(needle)));
  }, [emails.data, filter, q]);
  const PAGE = 25;
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE);

  async function processQueued() {
    setBusy(true);
    try {
      for (const e of (emails.data ?? []).filter(e => e.processingStatus === "queued").slice(0, 20)) await api.process(e.emailId);
    } finally { setBusy(false); emails.reload(); stats.reload(); }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-mute">Command Center</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Inbox verification control tower</h1>
        </div>
        <div className="flex gap-2">
          {(stats.data?.queued ?? 0) > 0 && <Button onClick={processQueued} disabled={busy}>{busy ? "Processing…" : `Process ${Math.min(20, stats.data!.queued)} queued`}</Button>}
          <Button kind="primary" onClick={() => setUpload(true)}>＋ New email</Button>
        </div>
      </div>

      <Briefing stats={stats.data} />
      <Kpis stats={stats.data} onPick={k => { setFilter(k); setPage(0); }} />

      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-line p-4 lg:flex-row lg:items-center">
          <div role="tablist" aria-label="Filter inbox" className="flex flex-wrap gap-1.5">
            {FILTERS.map(f => (
              <button key={f.key} role="tab" aria-selected={filter === f.key} onClick={() => { setFilter(f.key); setPage(0); }}
                className={`rounded-full px-3 py-1 text-xs transition ${filter === f.key ? "bg-ink text-white font-semibold" : "text-mute hover:text-fog shadow-[inset_0_0_0_1px_var(--color-line)]"}`}>
                {f.label} <span className="opacity-60 tabular-nums">{counts[f.key] ?? 0}</span>
              </button>
            ))}
          </div>
          <label className="lg:ml-auto flex items-center gap-2 rounded-lg border border-line bg-deck px-3 py-1.5 text-sm lg:w-80">
            <span aria-hidden className="text-mute">⌕</span>
            <span className="sr-only">Search</span>
            <input value={q} onChange={e => { setQ(e.target.value); setPage(0); }} placeholder="ID, subject, sender, ref, shipper, port…"
              className="w-full bg-transparent outline-none placeholder:text-mute/70" />
          </label>
        </div>

        {emails.error && <div className="p-4"><ErrorBox error={emails.error} onRetry={emails.reload} /></div>}
        {!emails.data && !emails.error && <Spinner label="Loading inbox" />}
        {emails.data && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] text-sm">
              <caption className="sr-only">Emails</caption>
              <thead className="text-left text-[11px] uppercase tracking-wider text-mute">
                <tr className="border-b border-line">
                  {["Email", "Subject / sender", "Received", "Classification", "Att.", "Processing", "Result", "Risk", "Next action"].map(h =>
                    <th key={h} scope="col" className="px-4 py-2.5 font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {shown.map(e => (
                  <tr key={e.emailId} tabIndex={0} onClick={() => nav(`/email/${e.emailId}`)} onKeyDown={ev => ev.key === "Enter" && nav(`/email/${e.emailId}`)}
                    className="cursor-pointer border-b border-line/60 hover:bg-deck/70 focus:bg-deck/70 focus:outline-none">
                    <td className="px-4 py-3 font-mono text-xs text-mute">{e.emailId}{e.source === "upload" && <span className="ml-1 text-norm">↑</span>}</td>
                    <td className="max-w-[380px] px-4 py-3">
                      <Link to={`/email/${e.emailId}`} className="block truncate font-medium text-fog hover:underline" onClick={ev => ev.stopPropagation()}>{e.subject || "(no subject)"}</Link>
                      <span className="block truncate text-xs text-mute">{e.sender}{e.shipmentRef && <> · <span className="font-mono">{e.shipmentRef}</span></>}</span>
                    </td>
                    <td className="px-4 py-3 text-xs text-mute whitespace-nowrap">{fmtDate(e.receivedAt)}</td>
                    <td className="px-4 py-3">
                      <div className="text-xs">{e.category ? CATEGORY[e.category] : "—"}</div>
                      <Confidence value={e.classificationConfidence} />
                    </td>
                    <td className="px-4 py-3 text-center tabular-nums text-mute">{e.attachmentCount || "–"}</td>
                    <td className="px-4 py-3"><ProcessChip status={e.processingStatus} /></td>
                    <td className="px-4 py-3">{e.category === "document_comparison" ? <RealityChip status={e.realityStatus} /> : <span className="text-xs text-mute">n/a</span>}</td>
                    <td className="px-4 py-3">{e.riskLevel ? <RiskChip level={e.riskLevel} /> : <span className="text-xs text-mute">—</span>}</td>
                    <td className="px-4 py-3 text-xs">
                      {(e.openCases ?? 0) > 0 ? <span className="text-review">Review ({e.openCases})</span> : <span className="text-mute">{ACTION[e.suggestedAction ?? ""] ?? "—"}</span>}
                    </td>
                  </tr>
                ))}
                {!shown.length && <tr><td colSpan={9} className="px-4 py-10 text-center text-mute">No emails match this view.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        {rows.length > PAGE && (
          <div className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-mute">
            <span>{page * PAGE + 1}–{Math.min(rows.length, (page + 1) * PAGE)} of {rows.length}</span>
            <span className="flex gap-2">
              <Button kind="quiet" disabled={!page} onClick={() => setPage(p => p - 1)}>← Prev</Button>
              <Button kind="quiet" disabled={(page + 1) * PAGE >= rows.length} onClick={() => setPage(p => p + 1)}>Next →</Button>
            </span>
          </div>
        )}
      </Card>
      {upload && <UploadDialog onClose={() => setUpload(false)} onDone={id => { setUpload(false); nav(`/email/${id}`); }} />}
    </div>
  );
}

function Briefing({ stats }: { stats: Stats | null }) {
  return (
    <Card className="border-l-4 border-l-match p-5 sm:p-6">
      <p className="text-xs uppercase tracking-[0.18em] text-match">Morning briefing</p>
      <p className="mt-2 max-w-4xl text-lg leading-relaxed text-fog sm:text-xl">{stats ? stats.briefing : "Reading the inbox…"}</p>
    </Card>
  );
}

function Kpis({ stats, onPick }: { stats: Stats | null; onPick: (k: string) => void }) {
  const items = [
    { k: "all", label: "Total emails", v: stats?.total, color: "var(--color-fog)" },
    { k: "cmp", label: "Document comparisons", v: stats?.comparisons, color: "var(--color-norm)" },
    { k: "clear", label: "Clear shipments", v: stats?.clear, color: "var(--color-match)", sub: "Converged" },
    { k: "mismatch", label: "Confirmed mismatches", v: stats?.mismatches, color: "var(--color-miss)", sub: "Diverging" },
    { k: "review", label: "Needs human review", v: stats?.unresolved, color: "var(--color-review)", sub: "Unresolved Reality" },
    { k: "failed", label: "Processing failures", v: stats?.failures, color: "var(--color-void)" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {items.map(i => (
        <button key={i.label} onClick={() => onPick(i.k)} className="group rounded-2xl border border-line bg-panel/70 p-4 text-left transition hover:border-mute/50">
          <span className="block text-xs text-mute">{i.label}</span>
          <span className="mt-1 block text-3xl font-semibold tabular-nums" style={{ color: i.color }}>{i.v ?? "–"}</span>
          {i.sub && <span className="text-[11px] text-mute">{i.sub}</span>}
        </button>
      ))}
    </div>
  );
}
