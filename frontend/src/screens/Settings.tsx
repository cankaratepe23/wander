import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { api, type Me, type Usage } from "../api";
import { Icon } from "../components/ui";

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
