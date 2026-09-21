import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Comparison, DocRecord, EmailDetail, FIELD_LABEL, FIELDS, FieldKey, FieldResult, IN_PROGRESS } from "../lib/api";
import {
  Button, CATEGORY, Card, Chip, Confidence, ErrorBox, Mono, ProcessChip, REALITY, RealityChip, RiskChip, STATE, Spinner,
  StateChip, fmtDate, fmtVal, usePoll,
} from "../components/ui";
import RouteMap from "../components/RouteMap";
import { findPortCoords } from "../lib/portCoords";

const REALITY_OF: Record<string, string> = { match: "converged", mismatch: "diverging", needs_review: "unresolved", incomplete: "incomplete" };

export default function ShipmentTwin() {
  const { id = "" } = useParams();
  const d = usePoll(() => api.email(id), [id], x => (x && IN_PROGRESS.has(x.email.processingStatus) ? 6000 : null));
  const [tab, setTab] = useState<"twin" | "forensics" | "audit">("twin");
  const [field, setField] = useState<FieldKey>("shipper");
  const [explain, setExplain] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  if (d.error) return <ErrorBox error={d.error} onRetry={d.reload} />;
  if (!d.data) return <Spinner label="Opening shipment" />;
  const { email, comparison } = d.data;
  const eff = comparison?.effectiveResult ?? null;
  const reality = eff ? REALITY_OF[eff.status] : null;
  const openCases = d.data.reviewCases.filter(c => c.status === "open");

  async function retry() {
    setBusy(true); setMsg(null);
    try { await api.retry(id); setMsg("Re-processed with the latest pipeline."); d.reload(); }
    catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }
  function exportJson() {
    const blob = new Blob([JSON.stringify(d.data, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${id}.json`; a.click();
  }
  const pick = (f: FieldKey) => { setField(f); setTab("forensics"); };

  return (
    <div className="space-y-5">
      <Link to="/" className="no-print text-sm text-mute hover:text-fog">← Command Center</Link>

      {/* ---------------- header ---------------- */}
      <Card className="p-5">
        <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-xs text-mute">
              <Mono>{email.emailId}</Mono>
              {email.shipmentRef && <>· Ref <Mono className="text-fog">{email.shipmentRef}</Mono></>}
              · {email.category ? CATEGORY[email.category] : "Unclassified"}
              {email.classificationConfidence != null && <Confidence value={email.classificationConfidence} />}
            </div>
            <h1 className="mt-1 text-xl font-semibold leading-snug sm:text-2xl">{email.subject || "(no subject)"}</h1>
            <p className="mt-1 text-sm text-mute">From {email.sender} · received {fmtDate(email.receivedAt)} · processed {fmtDate(email.processedAt)}</p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <ProcessChip status={email.processingStatus} />
            {eff && <RealityChip status={reality} theme />}
            {eff?.riskLevel && <RiskChip level={eff.riskLevel} />}
            {eff && !eff.provisional && eff.status !== "incomplete" && <Chip color="var(--color-norm)" icon="⌖" title="Every value is tied to a verbatim snippet in its source document">Evidence-backed</Chip>}
          </div>
        </div>
        {email.attachments?.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {email.attachments.map(a => (
              <a key={a.name} href={a.fileId ? api.fileUrl(a.fileId) : undefined} target="_blank" rel="noreferrer"
                className={`inline-flex items-center gap-2 rounded-lg border border-line px-2.5 py-1 text-xs ${a.fileId ? "hover:bg-deck" : "opacity-60"}`}>
                <span aria-hidden>📄</span><Mono>{a.name}</Mono>{a.size != null && <span className="text-mute">{Math.round(a.size / 1024)} KB</span>}
              </a>
            ))}
          </div>
        )}
      </Card>

      {email.category !== "document_comparison" ? (
        <ClassificationView detail={d.data} />
      ) : !eff ? (
        <Card className="p-6 text-mute">{IN_PROGRESS.has(email.processingStatus) ? "Processing… the twin appears when the comparison is ready." : email.statusReason ?? "No comparison available."}</Card>
      ) : (
        <>
          <Banner eff={eff} />
          <div className="no-print flex flex-wrap gap-2">
            <Button onClick={() => pick(eff.mismatchedFields[0] ?? eff.unresolvedFields?.[0] ?? "shipper")}>⌖ View evidence</Button>
            <Button onClick={() => setExplain(x => !x)} kind={explain ? "primary" : "ghost"}>ⓘ Explain comparison</Button>
            <Button onClick={() => setTab("forensics")}>🔬 Open Document Forensics</Button>
            <Link to={`/review?email=${id}`}><Button>⚑ Review Desk {openCases.length ? `(${openCases.length})` : ""}</Button></Link>
            <Button onClick={retry} disabled={busy}>{busy ? "Re-processing…" : "↻ Retry extraction"}</Button>
            <Link to={`/report/${id}`}><Button>▤ Generate report</Button></Link>
            <Button onClick={exportJson}>⤓ Export JSON</Button>
            {msg && <span role="status" className="self-center text-xs text-mute">{msg}</span>}
          </div>

          <div role="tablist" aria-label="Views" className="no-print flex gap-1 border-b border-line">
            {([["twin", "Compare (Shipment Twin)"], ["forensics", "See the evidence (Document Forensics)"], ["audit", `History (${d.data.auditLogs.length})`]] as const).map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                className={`-mb-px border-b-2 px-4 py-2 text-sm ${tab === k ? "border-match text-fog" : "border-transparent text-mute hover:text-fog"}`}>{l}</button>
            ))}
          </div>

          {tab === "twin" && (eff.status === "incomplete" ? <Incomplete detail={d.data} eff={eff} /> : <>
            <RouteStrip eff={eff} />
            <Twin eff={eff} explain={explain} onPick={pick} />
          </>)}
          {tab === "forensics" && <Forensics detail={d.data} eff={eff} field={field} setField={setField} />}
          {tab === "audit" && <Audit detail={d.data} />}
        </>
      )}

      {openCases.length > 0 && (
        <Card className="border-review/40 p-5">
          <h2 className="font-semibold text-review">⚑ {openCases.length} open review mission{openCases.length > 1 ? "s" : ""}</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {openCases.map(c => <li key={c.reviewCaseId}><Link className="hover:underline" to={`/review?case=${encodeURIComponent(c.reviewCaseId)}`}>{c.title}</Link> <span className="text-mute">— {c.reason}</span></li>)}
          </ul>
        </Card>
      )}
    </div>
  );
}

/* ---------------- banner ---------------- */

export function bannerText(eff: Comparison) {
  if (eff.status === "match") return "No mismatch detected.";
  if (eff.status === "mismatch") return `Reality split detected at ${eff.mismatchedFields.map(f => FIELD_LABEL[f]).join(", ")}.`;
  if (eff.status === "incomplete") return eff.headline;
  return eff.headline || "Human confirmation required before verification can be completed.";
}

function Banner({ eff }: { eff: Comparison }) {
  const r = REALITY[REALITY_OF[eff.status]];
  return (
    <div role="status" className="relative overflow-hidden rounded-2xl border p-5 sm:p-6"
      style={{ borderColor: `color-mix(in srgb, ${r.color} 55%, transparent)`, background: `linear-gradient(100deg, color-mix(in srgb, ${r.color} 16%, var(--color-panel)), var(--color-panel) 70%)` }}>
      <div className="flex flex-wrap items-center gap-4">
        <span aria-hidden className="grid h-12 w-12 place-items-center rounded-full text-2xl font-bold text-ink" style={{ background: r.color }}>{r.icon}</span>
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-[0.18em]" style={{ color: r.color }}>{r.label} · {r.theme}</p>
          <p className="text-xl font-semibold sm:text-2xl">{bannerText(eff)}</p>
          <p className="mt-1 text-sm text-mute">{eff.riskReason} Overall confidence {Math.round((eff.overallConfidence ?? 0) * 100)}%.
            {eff.provisional && eff.provisionalMismatches?.length ? ` OCR suggests differences at ${eff.provisionalMismatches.map(f => FIELD_LABEL[f]).join(", ")} — not counted until a person confirms.` : ""}
            {eff.confirmedOcrBy && ` OCR values confirmed by ${eff.confirmedOcrBy}.`}</p>
        </div>
      </div>
    </div>
  );
}

/* ---------------- route strip ---------------- */

function short(v: string | null) { return v ? v.split(",")[0].replace(/\s*\(.*?\)\s*/g, " ").trim() : "?"; }

function RouteStrip({ eff }: { eff: Comparison }) {
  const pol = eff.fields.port_of_loading, pod = eff.fields.port_of_discharge;
  if (!pol || !pod) return null;
  const split = (s?: FieldResult) => s?.state === "mismatch_confirmed";
  const unsure = (s?: FieldResult) => s && !["match_confirmed", "normalized_match", "mismatch_confirmed"].includes(s.state);
  const splitAny = split(pol) || split(pod);
  const col = splitAny ? "var(--color-miss)" : unsure(pol) || unsure(pod) ? "var(--color-review)" : "var(--color-match)";

  const lookupName = (norm: unknown, raw: string | null) => String(norm ?? short(raw)).toLowerCase();
  const siPolC = findPortCoords(lookupName(pol.siNormalized, pol.siOriginal));
  const siPodC = findPortCoords(lookupName(pod.siNormalized, pod.siOriginal));
  const blPolC = findPortCoords(lookupName(pol.blNormalized, pol.blOriginal));
  const blPodC = findPortCoords(lookupName(pod.blNormalized, pod.blOriginal));

  if (siPolC && siPodC && blPolC && blPodC) {
    return (
      <Card className="overflow-hidden p-4">
        <p className="mb-2 text-xs uppercase tracking-[0.18em] text-mute">Route</p>
        <RouteMap
          si={{ pol: { name: short(pol.siOriginal), coord: siPolC }, pod: { name: short(pod.siOriginal), coord: siPodC } }}
          bl={{ pol: { name: short(pol.blOriginal), coord: blPolC }, pod: { name: short(pod.blOriginal), coord: blPodC } }}
          color={col} dashed={!!(unsure(pol) || unsure(pod))} sameRoute={!splitAny}
        />
        <p className="mt-2 text-xs text-mute">
          {splitAny ? "SI and BL name different ports — routes diverge." : "SI and BL describe the same route."} Map data &copy;{" "}
          <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" className="underline">OpenStreetMap</a> contributors.
        </p>
      </Card>
    );
  }
  return (
    <Card className="p-4">
      <p className="mb-2 text-xs uppercase tracking-[0.18em] text-mute">Route</p>
      <svg viewBox="0 0 1000 110" className="h-24 w-full" role="img"
        aria-label={`SI route ${short(pol.siOriginal)} to ${short(pod.siOriginal)}; BL route ${short(pol.blOriginal)} to ${short(pod.blOriginal)}${splitAny ? " — routes differ" : ""}`}>
        {!splitAny ? (
          <>
            <path d="M120 55 C 400 20, 600 20, 880 55" stroke={col} strokeWidth="3" fill="none" strokeDasharray={unsure(pol) || unsure(pod) ? "8 8" : undefined} className="flow" />
            <circle cx="120" cy="55" r="9" fill={col} /><circle cx="880" cy="55" r="9" fill={col} />
            <text x="120" y="92" textAnchor="middle" fill="var(--color-fog)" fontSize="18">{short(pol.siOriginal)}</text>
            <text x="880" y="92" textAnchor="middle" fill="var(--color-fog)" fontSize="18">{short(pod.siOriginal)}</text>
            <text x="500" y="20" textAnchor="middle" fill="var(--color-mute)" fontSize="13">SI and BL describe the same route</text>
          </>
        ) : (
          <>
            <path d="M120 30 C 400 5, 600 5, 880 30" stroke="var(--color-norm)" strokeWidth="3" fill="none" />
            <path d="M120 80 C 400 105, 600 105, 880 80" stroke="var(--color-miss)" strokeWidth="3" fill="none" strokeDasharray="10 6" />
            <circle cx="120" cy="30" r="7" fill="var(--color-norm)" /><circle cx="880" cy="30" r="7" fill="var(--color-norm)" />
            <circle cx="120" cy="80" r="7" fill="var(--color-miss)" /><circle cx="880" cy="80" r="7" fill="var(--color-miss)" />
            <text x="20" y="35" fill="var(--color-mute)" fontSize="13">SI</text><text x="20" y="85" fill="var(--color-mute)" fontSize="13">BL</text>
            <text x="140" y="22" fill="var(--color-fog)" fontSize="15">{short(pol.siOriginal)}</text>
            <text x="860" y="22" textAnchor="end" fill="var(--color-fog)" fontSize="15">{short(pod.siOriginal)}</text>
            <text x="140" y="102" fill="var(--color-fog)" fontSize="15">{short(pol.blOriginal)}</text>
            <text x="860" y="102" textAnchor="end" fill="var(--color-fog)" fontSize="15">{short(pod.blOriginal)}</text>
            <text x="500" y="60" textAnchor="middle" fill="var(--color-miss)" fontSize="14">✕ routes diverge</text>
          </>
        )}
      </svg>
    </Card>
  );
}

/* ---------------- the twin ---------------- */

function Connector({ state }: { state: FieldResult["state"] }) {
  const s = STATE[state];
  const c = s.color;
  return (
    <svg viewBox="0 0 200 40" preserveAspectRatio="none" className="h-8 w-full" aria-hidden>
      {s.line === "solid" && <line x1="0" y1="20" x2="200" y2="20" stroke={c} strokeWidth="3" />}
      {s.line === "soft" && <><line x1="0" y1="16" x2="200" y2="16" stroke={c} strokeWidth="2" /><line x1="0" y1="24" x2="200" y2="24" stroke={c} strokeWidth="2" opacity=".6" /></>}
      {s.line === "broken" && <>
        <line x1="0" y1="20" x2="78" y2="20" stroke={c} strokeWidth="3" />
        <line x1="122" y1="20" x2="200" y2="20" stroke={c} strokeWidth="3" />
        <path d="M78 20 L96 6 M78 20 L96 34 M122 20 L104 6 M122 20 L104 34" stroke={c} strokeWidth="2.5" />
      </>}
      {s.line === "dashed" && <line x1="0" y1="20" x2="200" y2="20" stroke={c} strokeWidth="3" strokeDasharray="8 7" className="flow" />}
      {s.line === "void" && <line x1="0" y1="20" x2="200" y2="20" stroke={c} strokeWidth="2" strokeDasharray="2 6" />}
    </svg>
  );
}

function Twin({ eff, explain, onPick }: { eff: Comparison; explain: boolean; onPick: (f: FieldKey) => void }) {
  return (
    <div className="grid grid-cols-1 gap-0 overflow-hidden rounded-2xl border border-line bg-panel/60 lg:grid-cols-[minmax(0,1fr)_minmax(220px,260px)_minmax(0,1fr)]">
      <UniverseHead side="SI" title="Shipping Instruction" theme="Intended Universe" sub={eff.siFile} note="The source of truth" color="var(--color-norm)" />
      <div className="hidden min-w-0 border-x border-line bg-deck/60 px-4 py-4 text-center lg:block">
        <p className="text-xs uppercase tracking-[0.18em] text-mute">Field-by-field comparison</p>
        <p className="text-[11px] text-mute">Reality Alignment Core</p>
      </div>
      <UniverseHead side="BL" title="Draft Bill of Lading" theme="Draft Universe" sub={eff.blFile} note="Being checked against the SI" color="var(--color-review)" right />
      {FIELDS.map(f => {
        const r = eff.fields[f];
        if (!r) return null;
        return (
          <div key={f} className="contents">
            <ValueCell r={r} side="si" onClick={() => onPick(f)} />
            <button onClick={() => onPick(f)} className="group flex min-w-0 flex-col items-center justify-center gap-1 border-t border-line bg-deck/40 px-3 py-3 lg:border-x"
              aria-label={`${FIELD_LABEL[f]}: ${STATE[r.state].label}. Open evidence`}>
              <span className="text-[11px] font-medium uppercase tracking-wider text-mute group-hover:text-fog">{FIELD_LABEL[f]}</span>
              <Connector state={r.state} />
              <span className="flex items-center gap-2"><StateChip state={r.state} /><Confidence value={r.confidence} /></span>
              {r.correctedBy && <span className="text-[11px] text-norm">corrected by {r.correctedBy}</span>}
            </button>
            <ValueCell r={r} side="bl" onClick={() => onPick(f)} right />
            {explain && <p className="border-t border-line bg-deck px-4 py-2 text-sm text-mute lg:col-span-3">{r.explanation}</p>}
          </div>
        );
      })}
    </div>
  );
}

function UniverseHead({ side, title, theme, sub, note, color, right }: { side: string; title: string; theme: string; sub?: string; note: string; color: string; right?: boolean }) {
  return (
    <div className={`min-w-0 px-5 py-4 ${right ? "lg:text-right" : ""}`}>
      <p className="text-sm font-semibold" style={{ color }}>{side} · {title}</p>
      <p className="text-xs text-mute">{note} <span className="opacity-70">· {theme}</span></p>
      {sub && <p className="truncate text-xs text-mute font-mono">{sub}</p>}
    </div>
  );
}

function ValueCell({ r, side, right, onClick }: { r: FieldResult; side: "si" | "bl"; right?: boolean; onClick: () => void }) {
  const raw = side === "si" ? r.siOriginal : r.blOriginal;
  const label = side === "si" ? r.siLabel : r.blLabel;
  const norm = side === "si" ? r.siNormalized : r.blNormalized;
  const lines = (raw ?? "").split("\n");
  const off = r.state === "mismatch_confirmed";
  return (
    <button onClick={onClick} className={`min-w-0 overflow-hidden border-t border-line px-5 py-3 text-left hover:bg-deck/50 ${right ? "lg:text-right" : ""}`}>
      <span className="block truncate text-[11px] text-mute">{label ?? "no label found"}</span>
      {raw ? (
        <span className={`block font-medium ${off ? "text-miss" : "text-fog"}`}>{lines[0]}
          {lines.length > 1 && <span className="block truncate text-xs font-normal text-mute" title={lines.slice(1).join(" · ")}>{lines.slice(1).join(" · ")}</span>}
        </span>
      ) : <span className="block text-void italic">— not found / unreadable —</span>}
      {norm != null && String(norm).toLowerCase() !== lines[0].toLowerCase() && <span className="block text-[11px] text-mute">cleaned up as: <Mono>{fmtVal(norm)}</Mono></span>}
    </button>
  );
}

/* ---------------- incomplete ---------------- */

function Incomplete({ detail, eff }: { detail: EmailDetail; eff: Comparison }) {
  return (
    <Card className="p-5">
      <h2 className="font-semibold">Why the comparison could not begin</h2>
      <p className="mt-1 text-sm text-mute">{eff.reviewReasons?.[0]}</p>
      <ul className="mt-4 grid gap-3 md:grid-cols-2">
        {detail.documents.map(d => (
          <li key={d.fileName} className="rounded-xl border border-line p-4 text-sm">
            <p className="font-mono text-xs">{d.fileName}</p>
            <p className="mt-1">Role: <b>{d.role}</b> <span className="text-mute">({d.roleReason})</span></p>
            <p>Content: <b>{d.contentType === "OTHER" ? `not an SI/BL — ${d.heading}` : d.contentType}</b></p>
            <p>Read as: <b>{d.kind}</b> {d.readNote && <span className="text-mute">— {d.readNote}</span>}</p>
            {d.error && <p className="text-miss">{d.error}</p>}
          </li>
        ))}
        {!detail.documents.length && <li className="text-mute">No attachments were received with this email.</li>}
      </ul>
    </Card>
  );
}

/* ---------------- classification view ---------------- */

function ClassificationView({ detail }: { detail: EmailDetail }) {
  const e = detail.email;
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr]">
      <Card className="p-5">
        <p className="text-xs uppercase tracking-[0.18em] text-mute">Classification</p>
        <p className="mt-2 text-2xl font-semibold">{e.category ? CATEGORY[e.category] : "—"}</p>
        <div className="mt-2"><Confidence value={e.classificationConfidence} /></div>
        <p className="mt-3 text-sm text-fog">{e.classificationReason}</p>
        <p className="mt-2 text-xs text-mute">Decided by: {e.classificationSource === "gemini" ? "Gemini AI (reading the body, subject, sender and attachments)" : e.classificationSource === "reviewer" ? "a reviewer" : "automatic keyword rules (Gemini not needed or unavailable)"}</p>
        <p className="mt-4 text-sm text-mute">Only document-comparison requests continue to SI/BL extraction. This email is closed after classification.</p>
      </Card>
      <Card className="bg-paper p-5 text-graphite">
        <p className="text-xs uppercase tracking-[0.18em] text-graphite/60">Email body</p>
        <pre className="mt-2 max-h-[420px] overflow-auto whitespace-pre-wrap font-sans text-sm leading-relaxed">{e.body}</pre>
      </Card>
    </div>
  );
}

/* ---------------- forensics ---------------- */

type Needle = { value: string; evidence?: string | null; active: boolean };

/** Highlight each value inside ITS OWN evidence snippet, so equal values under different labels
 *  (e.g. consignee and notify party) point to the right line. */
function highlight(text: string, needles: Needle[]) {
  const ranges: { s: number; e: number; active: boolean }[] = [];
  const low = text.toLowerCase();
  const taken = (s: number, e: number) => ranges.some(r => s < r.e && e > r.s);
  for (const n of needles) {
    const evLine = (n.evidence ?? "").split("\n")[0].trim().toLowerCase();
    let from = evLine ? low.indexOf(evLine) : -1;
    if (from < 0) from = 0;
    for (const line of n.value.split("\n").map(x => x.trim()).filter(x => x.length > 1)) {
      let i = low.indexOf(line.toLowerCase(), from);
      while (i >= 0 && taken(i, i + line.length)) i = low.indexOf(line.toLowerCase(), i + 1);
      if (i < 0) i = low.indexOf(line.toLowerCase());
      if (i >= 0 && !taken(i, i + line.length)) { ranges.push({ s: i, e: i + line.length, active: n.active }); from = i + line.length; }
    }
  }
  ranges.sort((a, b) => a.s - b.s);
  const out: (string | JSX.Element)[] = [];
  let pos = 0;
  ranges.forEach((r, k) => {
    out.push(text.slice(pos, r.s));
    out.push(<mark key={k} data-active={r.active || undefined} className={`mark-evidence ${r.active ? "active" : ""}`}>{text.slice(r.s, r.e)}</mark>);
    pos = r.e;
  });
  out.push(text.slice(pos));
  return out;
}

function DocPane({ doc, label, needles }: { doc?: DocRecord; label: string; needles: Needle[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const key = needles.find(n => n.active)?.value;
  useEffect(() => { ref.current?.querySelector("[data-active]")?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [key, doc]);
  return (
    <div className="flex min-h-[360px] flex-col overflow-hidden rounded-2xl border border-paperline bg-paper text-graphite">
      <div className="flex items-center justify-between border-b border-paperline px-4 py-2 text-xs">
        <b className="uppercase tracking-wider">{label}</b><span className="font-mono">{doc?.fileName ?? "—"}</span>
      </div>
      <div ref={ref} className="max-h-[440px] flex-1 overflow-auto p-4">
        {doc?.text ? (
          <pre className="whitespace-pre-wrap font-mono text-[12.5px] leading-6">
            {highlight(doc.text, [...needles.filter(n => n.active), ...needles.filter(n => !n.active)])}
          </pre>
        ) : (
          <p className="text-sm text-graphite/70">{doc?.kind === "scanned" ? "Image-only document: values were read by Gemini OCR. Open the original file to compare against the scan." : "No readable text for this document."}</p>
        )}
      </div>
    </div>
  );
}

function Forensics({ detail, eff, field, setField }: { detail: EmailDetail; eff: Comparison; field: FieldKey; setField: (f: FieldKey) => void }) {
  const si = detail.documents.find(d => d.fileName === eff.siFile);
  const bl = detail.documents.find(d => d.fileName === eff.blFile);
  const r = eff.fields[field];
  const mismatchFields = useMemo(() => FIELDS.filter(f => eff.fields[f]?.state === "mismatch_confirmed"), [eff]);
  const needles = (side: "si" | "bl"): Needle[] => mismatchFields.map(f => {
    const x = eff.fields[f];
    return { value: (side === "si" ? x?.siOriginal : x?.blOriginal) ?? "", evidence: side === "si" ? x?.siEvidence : x?.blEvidence, active: f === field };
  }).filter(n => n.value);
  const fv = (doc?: DocRecord) => (doc?.fields?.[field] ?? {}) as Record<string, any>;
  const rows: [string, (d: Record<string, any>, side: "si" | "bl") => unknown][] = [
    ["Original label", d => d.source_label],
    ["Raw value", d => d.raw_value],
    ["Cleaned-up value", d => d.normalized],
    ["How it was cleaned up", d => d.normalization_note],
    ["Confidence", d => d.level ? `${d.level} (${Math.round((d.confidence ?? 0) * 100)}%)` : null],
    ["Found word-for-word in the document?", d => d.evidence_verified == null ? null : d.evidence_verified ? "yes" : "no"],
    ["Checked two ways — do they agree?", d => d.extractors_agree == null ? (d.gemini_value ? "Only read by Gemini" : "Only read by the text parser") : d.extractors_agree ? "yes, they agree" : "no, they disagree"],
    ["Page", d => d.page],
    ["Uncertainty", d => d.uncertainty],
  ];
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Field" className="flex flex-wrap gap-1.5">
        {FIELDS.map(f => {
          const st = eff.fields[f]?.state;
          const color = st ? STATE[st].color : "var(--color-mute)";
          const active = field === f;
          return <button key={f} role="tab" aria-selected={active} onClick={() => setField(f)}
            className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium transition hover:brightness-110"
            style={active
              ? { background: color, color: "#0b1220" }
              : { color, background: `color-mix(in srgb, ${color} 16%, transparent)`, boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${color} 45%, transparent)` }}>
            {st && <span aria-hidden>{STATE[st].icon}</span>}{FIELD_LABEL[f]}</button>;
        })}
      </div>
      {mismatchFields.length > 0 && (
        <p className="text-xs text-mute">
          Highlighting only the mismatched field{mismatchFields.length === 1 ? "" : "s"} ({mismatchFields.map(f => FIELD_LABEL[f]).join(", ")}) in the documents below.
        </p>
      )}
      {r && (
        <Card className="p-4">
          <div className="flex flex-wrap items-center gap-3"><StateChip state={r.state} /><Confidence value={r.confidence} /></div>
          <p className="mt-2 text-sm leading-relaxed">{r.explanation}</p>
        </Card>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <DocPane doc={si} label="SI — Shipping Instruction (source of truth)" needles={needles("si")} />
        <DocPane doc={bl} label="BL — Draft Bill of Lading (being checked)" needles={needles("bl")} />
      </div>
      <Card className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <caption className="sr-only">Extraction details for {FIELD_LABEL[field]}</caption>
          <thead className="text-left text-[11px] uppercase tracking-wider text-mute">
            <tr className="border-b border-line"><th className="px-4 py-2">{FIELD_LABEL[field]}</th><th className="px-4 py-2">SI</th><th className="px-4 py-2">BL</th></tr>
          </thead>
          <tbody>
            {rows.map(([name, get]) => (
              <tr key={name} className="border-b border-line/50">
                <th scope="row" className="px-4 py-2 text-left font-normal text-mute">{name}</th>
                <td className="px-4 py-2 whitespace-pre-wrap">{fmtVal(get(fv(si), "si"))}</td>
                <td className="px-4 py-2 whitespace-pre-wrap">{fmtVal(get(fv(bl), "bl"))}</td>
              </tr>
            ))}
            <tr><th scope="row" className="px-4 py-2 text-left font-normal text-mute">Evidence snippet</th>
              <td className="px-4 py-2"><Mono className="whitespace-pre-wrap">{r?.siEvidence ?? "—"}</Mono></td>
              <td className="px-4 py-2"><Mono className="whitespace-pre-wrap">{r?.blEvidence ?? "—"}</Mono></td></tr>
          </tbody>
        </table>
      </Card>
      {(si?.geminiRaw || bl?.geminiRaw) && (
        <details className="rounded-xl border border-line p-4 text-sm">
          <summary className="cursor-pointer text-mute">Raw Gemini output (preserved for audit)</summary>
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            {[si, bl].map((d, i) => <pre key={i} className="max-h-72 overflow-auto rounded-lg bg-ink p-3 font-mono text-[11px] text-slate-100">{d?.geminiRaw ?? "(Gemini not called: the rule parser read every field cleanly)"}</pre>)}
          </div>
        </details>
      )}
    </div>
  );
}

/* ---------------- audit ---------------- */

function Audit({ detail }: { detail: EmailDetail }) {
  return (
    <Card className="p-5">
      <ol className="relative space-y-3 border-l border-line pl-5">
        {detail.auditLogs.map((l, i) => (
          <li key={i} className="text-sm">
            <span aria-hidden className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full" style={{ background: l.actor === "system" ? "var(--color-norm)" : "var(--color-review)" }} />
            <span className="text-xs text-mute">{fmtDate(l.createdAt)} · {l.actor}</span>
            <p><b className="font-medium">{l.eventType.replace(/_/g, " ")}</b> — {l.details}</p>
          </li>
        ))}
      </ol>
    </Card>
  );
}
