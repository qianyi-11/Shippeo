import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { Button } from "./ui";

export default function UploadDialog({ onClose, onDone }: { onClose: () => void; onDone: (id: string) => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [subject, setSubject] = useState("Please check draft BL against SI");
  const [body, setBody] = useState("Hi team,\n\nAttached are the SI and draft BL. Please check the details and confirm.\n\nThanks");
  const [sender, setSender] = useState("ops@example.com");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { ref.current?.showModal(); }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    const fd = new FormData();
    fd.append("subject", subject); fd.append("body", body); fd.append("sender", sender);
    files.forEach(f => fd.append("files", f));
    try { const r = await api.upload(fd); onDone(r.emailId); }
    catch (err) { setError((err as Error).message); setBusy(false); }
  }

  const input = "w-full rounded-lg border border-line bg-deck px-3 py-2 text-sm outline-none focus:border-norm";
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="up-title"
      className="m-auto w-[min(640px,94vw)] rounded-2xl border border-line bg-panel p-0 text-fog backdrop:bg-ink/70 backdrop:backdrop-blur-sm">
      <form onSubmit={submit} className="space-y-4 p-6">
        <div>
          <h2 id="up-title" className="text-lg font-semibold">New email</h2>
          <p className="text-sm text-mute">Runs the full cloud pipeline: classify → locate SI/BL → read (text, PDF, Word, Excel, scans) → compare → review.</p>
        </div>
        <label className="block space-y-1 text-sm"><span className="text-mute">From</span><input className={input} value={sender} onChange={e => setSender(e.target.value)} /></label>
        <label className="block space-y-1 text-sm"><span className="text-mute">Subject</span><input className={input} required value={subject} onChange={e => setSubject(e.target.value)} /></label>
        <label className="block space-y-1 text-sm"><span className="text-mute">Body</span><textarea className={`${input} h-28`} value={body} onChange={e => setBody(e.target.value)} /></label>
        <label className="block space-y-1 text-sm">
          <span className="text-mute">Attachments (name them …_SI / …_BL, or let Shippeo detect them) · txt, pdf, docx, xlsx, png, jpg · max 4 MB</span>
          <input type="file" multiple accept=".txt,.pdf,.docx,.xlsx,.png,.jpg,.jpeg" onChange={e => setFiles(Array.from(e.target.files ?? []))}
            className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-deck file:px-3 file:py-1.5 file:text-fog" />
        </label>
        {error && <p role="alert" className="text-sm text-miss">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button onClick={() => ref.current?.close()}>Cancel</Button>
          <Button kind="primary" type="submit" disabled={busy}>{busy ? "Processing in the cloud…" : "Send & process"}</Button>
        </div>
      </form>
    </dialog>
  );
}
