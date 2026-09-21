import { Link, useParams } from "react-router-dom";
import { api, FIELD_LABEL, FIELDS, FieldKey } from "../lib/api";
import { ErrorBox, Spinner, STATE, fmtDate, fmtVal, usePoll } from "../components/ui";

const COLOR: Record<string, string> = { match: "#1f8f7e", mismatch: "#c9442c", needs_review: "#b07a12", incomplete: "#6b7385" };

export default function Report() {
  const { id = "" } = useParams();
  const r = usePoll(() => api.report(id), [id], () => null);
  if (r.error) return <div className="p-6"><ErrorBox error={r.error} /></div>;
  if (!r.data) return <Spinner label="Building report" />;
  const d = r.data;
  const status = d.status as string;
  const banner = status === "match" ? "No mismatch detected." : status === "mismatch"
    ? `Mismatch detected at ${(d.fields ? FIELDS.filter(f => d.fields[f]?.state === "mismatch_confirmed") : []).map((f: FieldKey) => FIELD_LABEL[f]).join(", ")}.`
    : d.headline;

  return (
    <div className="min-h-screen bg-[#e9e6df] py-6 print:bg-white print:py-0">
      <div className="no-print mx-auto mb-4 flex max-w-[900px] items-center justify-between px-4 text-sm text-graphite">
        <Link to={`/email/${id}`} className="underline">← Back to the Shipment Twin</Link>
        <span className="flex gap-2">
          <button onClick={() => window.print()} className="rounded-lg bg-graphite px-3 py-1.5 text-paper">Print / Save as PDF</button>
          <button onClick={() => { const b = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" }); const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = `${id}-report.json`; a.click(); }}
            className="rounded-lg border border-graphite px-3 py-1.5">Download JSON</button>
        </span>
      </div>
      <article className="print-sheet mx-auto max-w-[900px] bg-white px-10 py-10 text-[#1d2635] shadow-xl">
        <header className="flex items-start justify-between border-b-2 border-[#1d2635] pb-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b7385]">Shippeo · Discrepancy report</p>
            <h1 className="mt-1 text-2xl font-bold">{d.shipmentRef ?? d.emailId}</h1>
            <p className="text-sm text-[#4a5468]">{d.subject}</p>
          </div>
          <div className="text-right text-xs text-[#4a5468]">Generated {fmtDate(d.generatedAt)}<br />Email <span className="font-mono">{d.emailId}</span></div>
        </header>

        <section className="mt-5 rounded-lg p-4 text-white" style={{ background: COLOR[status] ?? "#6b7385" }}>
          <p className="text-xs uppercase tracking-wider opacity-90">{d.statusLabel} · {d.realityStatus} reality · {d.riskLevel} risk</p>
          <p className="text-xl font-bold">{banner}</p>
          <p className="text-sm opacity-90">{d.riskReason}</p>
        </section>

        <dl className="mt-5 grid grid-cols-2 gap-x-8 gap-y-1 text-sm">
          {[["Sender", d.sender], ["Received", fmtDate(d.receivedAt)], ["Category", d.category], ["SI attachment", d.siFile],
            ["BL attachment", d.blFile], ["Overall confidence", d.overallConfidence != null ? `${Math.round(d.overallConfidence * 100)}%` : "—"],
            ["Mismatch count", d.mismatchCount], ["Human review", d.needsHumanReview ? "Open items remain" : "None open"]].map(([k, v]) => (
            <div key={k as string} className="flex justify-between border-b border-[#eceae4] py-1"><dt className="text-[#6b7385]">{k}</dt><dd className="font-medium">{fmtVal(v)}</dd></div>
          ))}
        </dl>

        {Object.keys(d.fields ?? {}).length > 0 && (
          <table className="mt-6 w-full border-collapse text-[12.5px]">
            <thead><tr className="bg-[#1d2635] text-left text-white">
              <th className="p-2">Field</th><th className="p-2">SI (reference)</th><th className="p-2">Draft BL</th><th className="p-2">Result</th></tr></thead>
            <tbody>
              {FIELDS.map(f => {
                const x = d.fields[f];
                if (!x) return null;
                const bad = x.state === "mismatch_confirmed";
                return (
                  <tr key={f} className={`align-top ${bad ? "bg-[#fdecea]" : ""}`} style={{ borderBottom: "1px solid #eceae4" }}>
                    <td className="p-2 font-semibold">{FIELD_LABEL[f as FieldKey]}</td>
                    <td className="p-2 whitespace-pre-wrap">{fmtVal(x.siOriginal)}<div className="text-[11px] text-[#6b7385]">{x.siLabel} · norm: {fmtVal(x.siNormalized)}</div></td>
                    <td className="p-2 whitespace-pre-wrap">{fmtVal(x.blOriginal)}<div className="text-[11px] text-[#6b7385]">{x.blLabel} · norm: {fmtVal(x.blNormalized)}</div></td>
                    <td className="p-2"><b>{STATE[x.state as keyof typeof STATE]?.icon} {STATE[x.state as keyof typeof STATE]?.label}</b><div className="text-[11px] text-[#4a5468]">{x.explanation}</div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        <section className="mt-6">
          <h2 className="text-sm font-bold uppercase tracking-wider">Recommended next action</h2>
          <p className="mt-1 text-sm">{d.recommendedAction}</p>
        </section>

        {(d.reviews?.length > 0) && (
          <section className="mt-5">
            <h2 className="text-sm font-bold uppercase tracking-wider">Review decisions</h2>
            <ul className="mt-1 list-disc pl-5 text-sm">
              {d.reviews.map((c: any) => <li key={c.reviewCaseId}>{fmtDate(c.reviewedAt)} — {c.reviewerName}: {d.decisions?.[c.reviewerDecision] ?? c.reviewerDecision}{c.field ? ` (${FIELD_LABEL[c.field as FieldKey] ?? c.field})` : ""}{c.correctedValue ? ` → “${c.correctedValue}”` : ""}{c.reviewerComment ? ` — ${c.reviewerComment}` : ""}</li>)}
            </ul>
          </section>
        )}
        <footer className="mt-8 border-t border-[#eceae4] pt-3 text-[11px] text-[#6b7385]">
          Values were extracted from the attached documents (rule parser + Gemini) and compared by deterministic code. The SI is the reference.
          Operational risk priority only — not a legal, customs or insurance conclusion.
        </footer>
      </article>
    </div>
  );
}
