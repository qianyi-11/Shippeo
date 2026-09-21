import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, FIELD_LABEL, FieldKey, ReviewCase } from "../lib/api";
import { Button, CATEGORY, Card, Chip, Confidence, ErrorBox, Mono, RISK, Spinner, fmtDate, usePoll } from "../components/ui";

const FIELD_DECISIONS = ["confirm_mismatch", "correct_si_value", "correct_bl_value", "formatting_only_difference", "mark_unreadable"];
const COMMON = ["confirm_system_result", "request_updated_document", "retry_extraction", "dismiss"];

function kind(c: ReviewCase) {
  return c.field === "classification" ? "classification" : c.field && c.field in FIELD_LABEL ? "field" : "document";
}
function decisionsFor(c: ReviewCase) {
  const k = kind(c);
  if (k === "classification") return ["confirm_system_result", "change_category", "dismiss"];
  if (k === "field") return ["confirm_system_result", ...FIELD_DECISIONS, "request_updated_document", "retry_extraction", "dismiss"];
  return COMMON;
}
const getName = () => { try { return localStorage.getItem("reviewerName") ?? ""; } catch { return ""; } };
const saveName = (n: string) => { try { localStorage.setItem("reviewerName", n); } catch { /* private mode */ } };

export default function ReviewDesk() {
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState<"open" | "all">("open");
  const [type, setType] = useState<"all" | "document" | "field" | "classification">("all");
  const cases = usePoll(() => api.cases(status), [status], () => null);
  const decisions = usePoll(api.decisions, [], () => null);
  const emailFilter = params.get("email");
  const selectedId = params.get("case");

  const list = useMemo(() => (cases.data ?? [])
    .filter(c => !emailFilter || c.emailId === emailFilter)
    .filter(c => type === "all" || kind(c) === type), [cases.data, emailFilter, type]);
  const selected = list.find(c => c.reviewCaseId === selectedId) ?? list[0];
  const counts = useMemo(() => {
    const all = (cases.data ?? []).filter(c => !emailFilter || c.emailId === emailFilter);
    return { all: all.length, document: all.filter(c => kind(c) === "document").length, field: all.filter(c => kind(c) === "field").length, classification: all.filter(c => kind(c) === "classification").length };
  }, [cases.data, emailFilter]);

  const select = (id: string) => { const p = new URLSearchParams(params); p.set("case", id); setParams(p); };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-mute">Review Desk</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Review missions</h1>
          <p className="text-sm text-mute">Everything the system could not prove on its own. Your decision is stored next to the original AI output — never over it.</p>
        </div>
        <div className="flex flex-wrap gap-1.5 text-xs">
          {(["open", "all"] as const).map(s => <button key={s} onClick={() => setStatus(s)} className={`rounded-full px-3 py-1 ${status === s ? "bg-ink text-white font-semibold" : "text-mute shadow-[inset_0_0_0_1px_var(--color-line)]"}`}>{s === "open" ? "Open" : "All incl. resolved"}</button>)}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        {(["all", "document", "field", "classification"] as const).map(t => (
          <button key={t} onClick={() => setType(t)} className={`rounded-full px-3 py-1 ${type === t ? "bg-deck text-fog shadow-[inset_0_0_0_1px_var(--color-mute)]" : "text-mute shadow-[inset_0_0_0_1px_var(--color-line)]"}`}>
            {{ all: "All", document: "Documents", field: "Field values", classification: "Email category" }[t]} <span className="opacity-60">{counts[t]}</span>
          </button>
        ))}
        {emailFilter && <span className="ml-2 text-mute">for <Mono>{emailFilter}</Mono> <button className="underline" onClick={() => { const p = new URLSearchParams(params); p.delete("email"); setParams(p); }}>clear</button></span>}
      </div>

      {cases.error && <ErrorBox error={cases.error} onRetry={cases.reload} />}
      {!cases.data && !cases.error && <Spinner label="Loading missions" />}
      {cases.data && !list.length && <Card className="p-10 text-center text-mute">No review missions here. Every reality is resolved. ✓</Card>}
      {cases.data && !!list.length && (
        <div className="grid gap-5 lg:grid-cols-[minmax(300px,420px)_1fr]">
          <Card className="max-h-[75vh] overflow-auto p-2" as="nav">
            <ul aria-label="Missions">
              {list.map(c => (
                <li key={c.reviewCaseId}>
                  <button onClick={() => select(c.reviewCaseId)} aria-current={selected?.reviewCaseId === c.reviewCaseId}
                    className={`w-full rounded-xl px-3 py-2.5 text-left transition ${selected?.reviewCaseId === c.reviewCaseId ? "bg-deck shadow-[inset_0_0_0_1px_var(--color-line)]" : "hover:bg-deck/60"}`}>
                    <span className="flex items-center gap-2">
                      <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: RISK[c.priority] ?? "var(--color-void)" }} />
                      <span className="truncate text-sm font-medium">{c.title}</span>
                      {c.status !== "open" && <span className="ml-auto text-[11px] text-match">{c.status.replace(/_/g, " ")}</span>}
                    </span>
                    <span className="mt-0.5 block truncate pl-4 text-xs text-mute"><Mono>{c.emailId}</Mono> · {c.priority} · {c.subject}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {selected && <Mission key={selected.reviewCaseId} c={selected} labels={decisions.data ?? {}} onDone={() => cases.reload()} />}
        </div>
      )}
    </div>
  );
}

function Mission({ c, labels, onDone }: { c: ReviewCase; labels: Record<string, string>; onDone: () => void }) {
  const opts = decisionsFor(c);
  const [name, setName] = useState(getName());
  const [decision, setDecision] = useState(opts[0]);
  const [comment, setComment] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { setValue(decision === "correct_si_value" ? c.siValue ?? "" : decision === "correct_bl_value" ? c.blCandidateValue ?? "" : ""); }, [decision, c]);
  const needsValue = ["correct_si_value", "correct_bl_value", "change_category"].includes(decision);
  const done = c.status !== "open";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null); saveName(name);
    try {
      await api.resolve(c.reviewCaseId, { reviewerName: name, decision, comment, correctedValue: needsValue ? value : undefined });
      setMsg({ ok: true, text: "Decision saved. The Shipment Twin, report and submission now use it; the original AI output is preserved." });
      onDone();
    } catch (err) { setMsg({ ok: false, text: (err as Error).message }); }
    finally { setBusy(false); }
  }

  const input = "w-full rounded-lg border border-line bg-deck px-3 py-2 text-sm outline-none focus:border-norm";
  return (
    <Card className="space-y-5 p-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-[0.18em]" style={{ color: RISK[c.priority] }}>{c.priority} priority mission</p>
          <h2 className="text-xl font-semibold">{c.title}</h2>
          <p className="text-sm text-mute"><Link className="underline" to={`/email/${c.emailId}`}>{c.emailId}</Link>{c.shipmentRef && <> · Ref <Mono>{c.shipmentRef}</Mono></>} · {c.category ? CATEGORY[c.category] : ""} · opened {fmtDate(c.createdAt)}</p>
        </div>
        {c.field && c.field in FIELD_LABEL && <Chip color="var(--color-review)" icon="?">{FIELD_LABEL[c.field as FieldKey]}</Chip>}
      </div>

      <div>
        <p className="text-xs uppercase tracking-wider text-mute">Why this was escalated</p>
        <p className="mt-1 text-sm leading-relaxed">{c.reason}</p>
        <p className="mt-2 text-sm"><span className="text-mute">Recommended action:</span> {c.recommendedAction}</p>
      </div>

      {(c.siValue !== undefined || c.blCandidateValue !== undefined) && c.field !== "classification" && (
        <div className="grid gap-3 sm:grid-cols-2">
          {([["SI value", c.siValue, 0], ["BL candidate value", c.blCandidateValue, 1]] as const).map(([l, v, i]) => (
            <div key={l} className="rounded-xl border border-paperline bg-paper p-3 text-graphite">
              <p className="text-[11px] uppercase tracking-wider text-graphite/60">{l}</p>
              <p className="font-medium whitespace-pre-wrap">{v ?? "— missing —"}</p>
              {c.evidence?.[i]?.snippet && <pre className="mt-2 whitespace-pre-wrap rounded bg-paperline/60 p-2 font-mono text-[11px]">{c.evidence[i].snippet}</pre>}
            </div>
          ))}
          {c.confidence != null && <p className="text-sm sm:col-span-2">Field confidence: <Confidence value={c.confidence} /></p>}
        </div>
      )}

      {!!c.attachments?.length && (
        <div className="flex flex-wrap gap-2 text-xs">
          {c.attachments.map(a => <a key={a.name} className="rounded-lg border border-line px-2 py-1 hover:bg-deck" target="_blank" rel="noreferrer" href={a.fileId ? api.fileUrl(a.fileId) : undefined}>📄 <Mono>{a.name}</Mono></a>)}
        </div>
      )}

      {done ? (
        <div className="rounded-xl border border-match/40 bg-match/10 p-4 text-sm">
          <b className="text-match">{c.status.replace(/_/g, " ")}</b> by {c.reviewerName} · {fmtDate(c.reviewedAt)} — {labels[c.reviewerDecision ?? ""] ?? c.reviewerDecision}
          {c.correctedValue && <> · corrected value <Mono>{c.correctedValue}</Mono></>}{c.reviewerComment && <> · “{c.reviewerComment}”</>}
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3 rounded-xl border border-line bg-deck/50 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm"><span className="text-mute">Reviewer name</span>
              <input required minLength={2} maxLength={60} className={input} value={name} onChange={e => setName(e.target.value)} placeholder="Your name" /></label>
            <label className="space-y-1 text-sm"><span className="text-mute">Decision</span>
              <select className={input} value={decision} onChange={e => setDecision(e.target.value)}>
                {opts.map(o => <option key={o} value={o}>{labels[o] ?? o}</option>)}
              </select></label>
          </div>
          {needsValue && (
            <label className="block space-y-1 text-sm"><span className="text-mute">{decision === "change_category" ? "Correct category" : "Corrected value (it will be normalized and compared again)"}</span>
              {decision === "change_category"
                ? <select className={input} value={value} onChange={e => setValue(e.target.value)} required>
                    <option value="">Choose…</option>
                    {Object.entries(CATEGORY).filter(([k]) => k !== "needs_review").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                : <input className={input} required value={value} onChange={e => setValue(e.target.value)} />}
            </label>
          )}
          <label className="block space-y-1 text-sm"><span className="text-mute">Reviewer comment</span>
            <textarea className={`${input} h-20`} value={comment} onChange={e => setComment(e.target.value)} placeholder="What did you check?" /></label>
          <div className="flex items-center gap-3">
            <Button kind="primary" type="submit" disabled={busy}>{busy ? "Saving…" : "Save review decision"}</Button>
            <span className="text-xs text-mute">No login (MVP) — your name is recorded in the audit log.</span>
          </div>
          {msg && <p role="status" className={`text-sm ${msg.ok ? "text-match" : "text-miss"}`}>{msg.text}</p>}
        </form>
      )}

      {!!c.history?.length && (
        <details className="text-sm"><summary className="cursor-pointer text-mute">Processing history</summary>
          <ul className="mt-2 space-y-1">{c.history.map((h, i) => <li key={i} className="text-xs text-mute">{fmtDate(h.at)} · {h.by} · {h.event}{h.comment ? ` — ${h.comment}` : ""}</li>)}</ul>
        </details>
      )}
    </Card>
  );
}
