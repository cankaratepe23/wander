import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { api, ApiError, type ImportProgress, type Me, type Usage } from "../api";
import { Icon } from "../components/ui";

const SOURCE: Record<ImportProgress["source"], string> = { whatsapp: "WhatsApp", tiktok: "TikTok", instagram: "Instagram" };

function ImportSection({ onImported }: { onImported: () => void }) {
  const [imports, setImports] = useState<ImportProgress[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.imports().then(setImports).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  async function upload(file: File) {
    setBusy(true);
    setNote(null);
    try {
      const imp = await api.uploadImport(file);
      setImports((all) => [imp, ...all]);
      setNote(`${imp.total} items from ${SOURCE[imp.source]}. They're read slowly, then filed in batches; new ideas wait under “From imports” in the Inbox.`);
      onImported();
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : "Upload failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-3 flex flex-col gap-2 rounded-[22px] border border-line bg-surface p-4 text-[14px] leading-normal text-soft">
      <span className="t-label text-muted">Import old saves</span>
      <p className="m-0">
        Upload a WhatsApp chat export (.txt or .zip, without media), TikTok's “Download your data” JSON, or Instagram's
        “Download your information” JSON. Links and travel talk become ideas at half the usual AI cost.
      </p>
      <label
        className={`mt-1 flex h-[42px] cursor-pointer items-center justify-center gap-2 rounded-xl border border-line text-sm font-semibold text-text ${busy ? "opacity-50" : ""}`}
      >
        {busy ? "Reading…" : "Choose an export"}
        <input
          type="file"
          accept=".txt,.json,.zip"
          hidden
          disabled={busy}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload(f);
            e.target.value = "";
          }}
        />
      </label>
      {note && <span className="text-[13px] text-muted">{note}</span>}
      {imports.map((imp) => {
        const done = (imp.counts.done ?? 0) + (imp.counts.needs_review ?? 0) + (imp.counts.dismissed ?? 0);
        return (
          <div key={imp.id} className="flex flex-col gap-1 rounded-xl border border-line px-3 py-2">
            <span className="text-[13px] font-semibold text-text">
              {SOURCE[imp.source]} · {imp.filename ?? "export"}
            </span>
            <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "var(--line)" }}>
              <div className="h-full bg-accent" style={{ width: `${Math.round((100 * done) / Math.max(1, imp.total))}%` }} />
            </div>
            <span className="font-mono text-[11px] text-muted">
              {done}/{imp.total} filed
              {imp.counts.waiting ? ` · ${imp.counts.waiting} to read` : ""}
              {imp.counts.batched ? ` · ${imp.counts.batched} in a batch` : ""}
              {imp.counts.dismissed ? ` · ${imp.counts.dismissed} not travel` : ""}
            </span>
          </div>
        );
      })}
    </section>
  );
}

function NudgeSection() {
  const [result, setResult] = useState<string | null>(null);
  async function check(send: boolean) {
    try {
      const r = await api.nudgePreview(send);
      if (!r.body) setResult("Nothing is in season this month or next.");
      else setResult(`${r.body}${r.sent ? " (sent)" : r.configured ? "" : " (not sent: no ntfy topic configured)"}`);
    } catch {
      setResult("Couldn't reach Wander.");
    }
  }
  return (
    <section className="mt-3 flex flex-col gap-2 rounded-[22px] border border-line bg-surface p-4 text-[14px] leading-normal text-soft">
      <span className="t-label text-muted">Seasonal nudge</span>
      <p className="m-0">On the 1st of each month, a push about ideas that are best this month or next.</p>
      <div className="flex gap-2">
        <button type="button" onClick={() => check(false)} className="h-10 flex-1 rounded-xl border border-line text-sm font-semibold text-text">
          Preview
        </button>
        <button type="button" onClick={() => check(true)} className="h-10 flex-1 rounded-xl border border-line text-sm font-semibold text-text">
          Send a test
        </button>
      </div>
      {result && <span className="text-[13px] text-muted">{result}</span>}
    </section>
  );
}

export function Settings({ me, onClose, onReenriched }: { me: Me; onClose: () => void; onReenriched: () => void }) {
  const reduce = useReducedMotion();
  const [usage, setUsage] = useState<Usage | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    api.usage().then(setUsage).catch(() => {});
  }, []);

  async function reenrichAll() {
    if (!confirm("Re-read every capture with the current model? This uses AI credit.")) return;
    setBusy(true);
    try {
      const { queued } = await api.reenrichAll();
      setNote(`${queued} captures queued. They'll update over the next few minutes.`);
      onReenriched();
    } catch {
      setNote("Couldn't queue them. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <motion.div
      role="dialog"
      aria-label="Settings"
      initial={reduce ? { opacity: 0 } : { y: "100%" }}
      animate={reduce ? { opacity: 1 } : { y: 0 }}
      exit={reduce ? { opacity: 0 } : { y: "100%" }}
      transition={reduce ? { duration: 0.12 } : { type: "spring", stiffness: 380, damping: 36 }}
      className="absolute inset-0 z-20 flex flex-col overflow-y-auto bg-bg px-[22px] pb-8"
      style={{ paddingTop: "max(28px, env(safe-area-inset-top))" }}
    >
      <header className="flex items-center justify-between pt-4">
        <h1 className="t-display m-0">Settings</h1>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="grid size-10 place-items-center rounded-xl border border-line bg-surface text-text"
        >
          <Icon name="close" size={18} />
        </button>
      </header>

      <section className="mt-6 flex flex-col gap-1 rounded-[22px] border border-line bg-surface p-4">
        <span className="t-label text-muted">Signed in</span>
        <span className="text-[15px] font-semibold">{me.display_name}</span>
        <span className="font-mono text-xs text-muted">{me.email}</span>
      </section>

      <section className="mt-3 flex flex-col gap-2 rounded-[22px] border border-line bg-surface p-4">
        <span className="t-label text-muted">AI this month</span>
        {usage ? (
          <>
            <span className="text-[28px] font-[640] tracking-[-0.03em]">${usage.usd.toFixed(2)}</span>
            <span className="font-mono text-xs text-muted">
              {Object.entries(usage.by_task)
                .map(([task, t]) => `${task} ${t.calls}× $${t.usd.toFixed(2)}`)
                .join(" · ") || "No calls yet"}
            </span>
            {!usage.ai_configured && (
              <span className="text-[13px]" style={{ color: "var(--culture-ink)" }}>
                Claude isn't connected yet, so new captures wait in the queue.
              </span>
            )}
          </>
        ) : (
          <span className="text-sm text-muted">Loading…</span>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={reenrichAll}
          className="mt-2 flex h-[42px] items-center justify-center gap-2 rounded-xl border border-line text-sm font-semibold disabled:opacity-50"
        >
          <Icon name="refresh" size={16} />
          Re-enrich everything
        </button>
        {note && <span className="text-[13px] text-muted">{note}</span>}
      </section>

      <ImportSection onImported={onReenriched} />
      <NudgeSection />

      <section className="mt-3 flex flex-col gap-2 rounded-[22px] border border-line bg-surface p-4 text-[14px] leading-normal text-soft">
        <span className="t-label text-muted">Saving from other apps</span>
        <p className="m-0">
          <strong className="text-text">Android:</strong> install Wander (browser menu → Add to Home screen), then use Share →
          Wander in TikTok, Instagram, WhatsApp or Gallery.
        </p>
        <p className="m-0">
          <strong className="text-text">iPhone:</strong> add the “Save to Wander” Shortcut (see the setup guide in the
          repo, docs/ios-shortcut.md), then use Share → Save to Wander.
        </p>
      </section>
    </motion.div>
  );
}
