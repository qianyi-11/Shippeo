import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, EmailRow, FIELD_LABEL, FIELDS } from "../lib/api";
import { CATEGORY, Card, ErrorBox, REALITY, Spinner, usePoll } from "../components/ui";

/** Single-series horizontal bars: one hue, direct value labels, hover title, table alternative. */
function Bars({ title, rows, color = "var(--color-norm)", unit = "" }: { title: string; rows: [string, number][]; color?: string; unit?: string }) {
  const [table, setTable] = useState(false);
  const max = Math.max(1, ...rows.map(r => r[1]));
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        <button className="text-xs text-mute underline" onClick={() => setTable(t => !t)}>{table ? "Chart" : "Table"}</button>
      </div>
      {table ? (
        <table className="mt-3 w-full text-sm"><tbody>{rows.map(([k, v]) => <tr key={k} className="border-b border-line/50"><td className="py-1 text-mute">{k}</td><td className="py-1 text-right tabular-nums">{v}{unit}</td></tr>)}</tbody></table>
      ) : (
        <ul className="mt-3 space-y-2.5">
          {rows.map(([k, v]) => (
            <li key={k} className="grid grid-cols-[130px_1fr_44px] items-center gap-3 text-sm" title={`${k}: ${v}${unit}`}>
              <span className="truncate text-mute">{k}</span>
              <span className="h-2.5 rounded-r-[4px] bg-line/40"><span className="block h-full rounded-r-[4px]" style={{ width: `${(v / max) * 100}%`, background: color, minWidth: v ? 3 : 0 }} /></span>
              <span className="text-right tabular-nums text-fog">{v}{unit}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Constellation({ emails }: { emails: EmailRow[] }) {
  const nav = useNavigate();
  const stars = emails.filter(e => e.category === "document_comparison");
  const size = (e: EmailRow) => (e.riskLevel === "critical" ? 9 : e.riskLevel === "high" ? 7 : e.riskLevel === "medium" ? 5.5 : 4);
  const W = 1000, H = 300;
  // deterministic scatter: status bands left->right, stable jitter from the id
  const order = ["converged", "diverging", "unresolved", "incomplete"];
  const hash = (s: string, seed: number) => { let h = seed >>> 0; for (const c of s) { h = Math.imul(h ^ c.charCodeAt(0), 2654435761); h ^= h >>> 13; } return (h >>> 0) / 4294967296; };
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Cargo constellation <span className="font-normal text-mute">· one star per shipment · larger = higher priority</span></h2>
        <ul className="flex flex-wrap gap-3 text-xs">{order.map(k => <li key={k} className="flex items-center gap-1.5"><span aria-hidden style={{ color: REALITY[k].color }}>{REALITY[k].icon}</span>{REALITY[k].label}</li>)}</ul>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-3 w-full" role="img" aria-label="Shipments by reality status">
        {order.map((k, i) => <text key={k} x={(i + 0.5) * (W / 4)} y={H - 8} textAnchor="middle" fontSize="13" fill="var(--color-mute)">{REALITY[k].theme}</text>)}
        {stars.map(e => {
          const band = Math.max(0, order.indexOf(e.realityStatus ?? "incomplete"));
          const x = band * (W / 4) + 30 + hash(e.emailId, 7) * (W / 4 - 60);
          const y = 20 + hash(e.emailId, 1337) * (H - 60);
          const c = REALITY[e.realityStatus ?? "incomplete"]?.color ?? "var(--color-void)";
          return <g key={e.emailId} className="cursor-pointer" onClick={() => nav(`/email/${e.emailId}`)}>
            <title>{`${e.emailId} · ${REALITY[e.realityStatus ?? "incomplete"]?.label} · ${e.riskLevel ?? ""} risk`}</title>
            <circle cx={x} cy={y} r={size(e) * 2.2} fill={c} opacity=".12" />
            <circle cx={x} cy={y} r={size(e)} fill={c} stroke="var(--color-panel)" strokeWidth="2" />
          </g>;
        })}
      </svg>
    </Card>
  );
}

function EvalRuns() {
  const runs = usePoll(api.evalRuns, [], () => null);
  const pts = (runs.data ?? []).map(r => ({ at: r.at, v: Number(r.score?.final_score ?? r.score?.score ?? NaN), r })).filter(p => !isNaN(p.v));
  return (
    <Card className="p-5">
      <h2 className="text-sm font-semibold">Self-evaluation score over time</h2>
      <p className="text-xs text-mute">Recorded by <code className="font-mono">scripts/submit.py</code> against the organisers' scoring server.</p>
      {!pts.length ? <p className="mt-4 text-sm text-mute">No runs recorded yet.</p> : (
        <>
          <svg viewBox="0 0 600 180" className="mt-3 w-full" role="img" aria-label="Final score per run">
            {[0, 0.5, 1].map(g => <g key={g}><line x1="40" x2="590" y1={160 - g * 140} y2={160 - g * 140} stroke="var(--color-line)" strokeWidth="1" /><text x="34" y={164 - g * 140} fontSize="11" textAnchor="end" fill="var(--color-mute)">{g}</text></g>)}
            <polyline fill="none" stroke="var(--color-match)" strokeWidth="2" points={pts.map((p, i) => `${40 + (i / Math.max(1, pts.length - 1)) * 550},${160 - Math.min(1, p.v) * 140}`).join(" ")} />
            {pts.map((p, i) => { const x = 40 + (i / Math.max(1, pts.length - 1)) * 550, y = 160 - Math.min(1, p.v) * 140;
              return <g key={i}><circle cx={x} cy={y} r="5" fill="var(--color-match)" stroke="var(--color-panel)" strokeWidth="2"><title>{`${p.at}: ${p.v.toFixed(3)}${p.r.note ? " — " + p.r.note : ""}`}</title></circle>
                {i === pts.length - 1 && <text x={x - 6} y={y - 10} textAnchor="end" fontSize="12" fill="var(--color-fog)">{p.v.toFixed(3)}</text>}</g>; })}
          </svg>
          <details className="mt-2 text-xs text-mute"><summary className="cursor-pointer">Latest scoreboard</summary>
            <pre className="mt-2 max-h-64 overflow-auto rounded bg-ink p-3 font-mono text-slate-100">{JSON.stringify(pts[pts.length - 1].r.score, null, 2)}</pre></details>
        </>
      )}
    </Card>
  );
}

export default function Insights() {
  const stats = usePoll(api.stats, [], () => null);
  const emails = usePoll(api.emails, [], () => null);
  const cases = usePoll(() => api.cases("open"), [], () => null);
  const ages = useMemo(() => {
    const now = Date.now(), b: Record<string, number> = { "< 1 hour": 0, "1–24 hours": 0, "1–3 days": 0, "> 3 days": 0 };
    for (const c of cases.data ?? []) {
      const h = (now - new Date(c.createdAt).getTime()) / 3.6e6;
      b[h < 1 ? "< 1 hour" : h < 24 ? "1–24 hours" : h < 72 ? "1–3 days" : "> 3 days"]++;
    }
    return Object.entries(b) as [string, number][];
  }, [cases.data]);

  if (stats.error) return <ErrorBox error={stats.error} onRetry={stats.reload} />;
  if (!stats.data || !emails.data) return <Spinner label="Computing insights" />;
  const s = stats.data;
  const tiles = [
    { k: "converged", v: s.clear }, { k: "diverging", v: s.mismatches },
    { k: "unresolved", v: s.unresolved - s.incomplete }, { k: "incomplete", v: s.incomplete },
  ];
  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs uppercase tracking-[0.18em] text-mute">Insights</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Mismatch constellation</h1>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        {tiles.map(t => <Card key={t.k} className="p-4"><p className="text-xs text-mute"><span aria-hidden style={{ color: REALITY[t.k].color }}>{REALITY[t.k].icon}</span> {REALITY[t.k].label}</p><p className="text-3xl font-semibold tabular-nums">{t.v}</p><p className="text-[11px] text-mute">{REALITY[t.k].theme}</p></Card>)}
        <Card className="p-4"><p className="text-xs text-mute">Open review cases</p><p className="text-3xl font-semibold tabular-nums">{s.openCases}</p></Card>
        <Card className="p-4"><p className="text-xs text-mute">Avg. confidence (compared)</p><p className="text-3xl font-semibold tabular-nums">{s.avgConfidence != null ? `${Math.round(s.avgConfidence * 100)}%` : "—"}</p><p className="text-[11px] text-mute">{s.failures} processing failures</p></Card>
      </div>
      <Constellation emails={emails.data} />
      <div className="grid gap-5 lg:grid-cols-2">
        <Bars title="Confirmed mismatches by field" color="var(--color-miss)" rows={FIELDS.map(f => [FIELD_LABEL[f], s.mismatchByField[f] ?? 0])} />
        <Bars title="Classification distribution" rows={Object.entries(s.categories).sort((a, b) => b[1] - a[1]).map(([k, v]) => [CATEGORY[k] ?? k, v])} />
        <Bars title="Why shipments need review" color="var(--color-review)" rows={Object.entries(s.reviewReasons).map(([k, v]) => [k.replace(/_/g, " "), v])} />
        <Bars title="Open review cases by age" color="var(--color-review)" rows={ages} />
      </div>
      <EvalRuns />
    </div>
  );
}
