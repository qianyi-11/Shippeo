export type FieldKey =
  | "shipper" | "consignee" | "notify_party" | "port_of_loading"
  | "port_of_discharge" | "container_count" | "gross_weight_kg";

export const FIELDS: FieldKey[] = [
  "shipper", "consignee", "notify_party", "port_of_loading", "port_of_discharge", "container_count", "gross_weight_kg",
];

export const FIELD_LABEL: Record<FieldKey, string> = {
  shipper: "Shipper",
  consignee: "Consignee",
  notify_party: "Notify Party",
  port_of_loading: "Port of Loading",
  port_of_discharge: "Port of Discharge",
  container_count: "Container Count",
  gross_weight_kg: "Gross Weight (kg)",
};

export type FieldState =
  | "match_confirmed" | "normalized_match" | "mismatch_confirmed"
  | "missing_in_si" | "missing_in_bl" | "unreadable" | "ambiguous_needs_review";

export interface FieldResult {
  field: FieldKey;
  state: FieldState;
  explanation: string;
  confidence: number;
  needsReview: boolean;
  issue?: string | null;
  siOriginal: string | null; blOriginal: string | null;
  siNormalized: unknown; blNormalized: unknown;
  siLabel: string | null; blLabel: string | null;
  siEvidence: string | null; blEvidence: string | null;
  siNote: string; blNote: string;
  siLevel: string; blLevel: string;
  correctedBy?: string; correctedSide?: string; originalValue?: string | null;
}

export interface Comparison {
  status: "match" | "mismatch" | "needs_review" | "incomplete";
  statusLabel: string; themeLabel: string; headline: string;
  mismatchedFields: FieldKey[]; mismatchCount: number; unresolvedFields: FieldKey[];
  needsHumanReview: boolean; reviewReasons: string[]; overallConfidence: number;
  riskLevel: string; riskReason: string; fields: Partial<Record<FieldKey, FieldResult>>;
  siFile?: string; blFile?: string; reviewReason?: string | null;
  provisional?: boolean; provisionalMismatches?: FieldKey[]; confirmedOcrBy?: string;
}

export interface Attachment {
  name: string; path: string; mime: string; size: number | null; stored: boolean; fileId: string | null; missing?: boolean;
}

export interface EmailRow {
  emailId: string; sender: string; subject: string; receivedAt: string | null; attachmentCount: number;
  category: string | null; classificationConfidence: number | null; processingStatus: string;
  realityStatus: string | null; riskLevel: string | null; suggestedAction: string | null; headline: string | null;
  mismatchedFields: FieldKey[]; shipmentRef: string | null; searchText: string | null; openCases: number;
  source: string; updatedAt: string; reviewReason: string | null; statusReason: string | null;
}

export interface EmailDoc extends EmailRow {
  body: string; attachments: Attachment[]; classificationReason: string | null; classificationSource: string | null;
  riskReason: string | null; overallConfidence: number | null; processedAt: string | null; geminiUsed?: boolean;
}

export interface DocRecord {
  fileName: string; role: string; roleReason: string; contentType: string; heading?: string; kind: string;
  readNote?: string; text: string | null; error: string | null; gemini: unknown; geminiRaw: string | null;
  fields?: Record<FieldKey, Record<string, unknown>>;
}

export interface ReviewCase {
  reviewCaseId: string; emailId: string; field: string | null; reason: string; priority: string;
  recommendedAction: string; status: string; title: string; createdAt: string;
  siValue?: string | null; blCandidateValue?: string | null; confidence?: number;
  evidence?: { document: string; snippet: string | null }[];
  reviewerName: string | null; reviewerDecision: string | null; reviewerComment: string | null; reviewedAt: string | null;
  correctedValue?: string | null; history?: { at: string; event: string; by: string; comment?: string }[];
  subject?: string; shipmentRef?: string | null; category?: string | null; attachments?: Attachment[];
}

export interface AuditLog { eventType: string; details: string; actor: string; createdAt: string }

export interface EmailDetail {
  email: EmailDoc;
  documents: DocRecord[];
  comparison: { systemResult: Comparison; effectiveResult: Comparison; corrections: unknown[] } | null;
  reviewCases: ReviewCase[];
  auditLogs: AuditLog[];
}

export interface Stats {
  total: number; categories: Record<string, number>; comparisons: number; clear: number; mismatches: number;
  unresolved: number; incomplete: number; failures: number; queued: number;
  mismatchByField: Record<FieldKey, number>; risk: Record<string, number>; reviewReasons: Record<string, number>;
  openCases: number; avgConfidence: number | null; briefing: string;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail ?? msg; } catch { /* keep status text */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

const post = <T,>(path: string, body: unknown) =>
  req<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  health: () => req<{ ok: boolean; store: string; gemini: boolean; geminiModel: string; geminiMode: string }>("/api/health"),
  emails: () => req<EmailRow[]>("/api/emails"),
  email: (id: string) => req<EmailDetail>(`/api/emails/${encodeURIComponent(id)}`),
  stats: () => req<Stats>("/api/stats"),
  cases: (status = "open") => req<ReviewCase[]>(`/api/cases?status=${status}`),
  decisions: () => req<Record<string, string>>("/api/decisions"),
  report: (id: string) => req<Record<string, any>>(`/api/report/${encodeURIComponent(id)}`),
  evalRuns: () => req<{ at: string; score: Record<string, any>; note?: string; commit?: string }[]>("/api/eval-runs"),
  submission: () => req<Record<string, unknown>>("/api/submission"),
  process: (emailId: string) => post<{ processingStatus: string }>("/api/process", { emailId }),
  retry: (emailId: string) => post<{ processingStatus: string }>("/api/retry", { emailId }),
  resolve: (caseId: string, body: { reviewerName: string; decision: string; comment: string; correctedValue?: string }) =>
    post<{ case: ReviewCase }>(`/api/cases/${encodeURIComponent(caseId)}/resolve`, body),
  upload: (form: FormData) => req<{ emailId: string; processingStatus: string }>("/api/upload", { method: "POST", body: form }),
  fileUrl: (fileId: string) => `/api/files/${encodeURIComponent(fileId)}`,
};

export const IN_PROGRESS = new Set(["queued", "classifying", "classified", "locating_documents", "extracting", "normalizing", "comparing"]);
