import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useRef, useState } from "react";
import { api, ApiError, type Capture as CaptureRow, type Idea, type Me } from "../api";
import { enqueue } from "../queue";
import { Icon, SourceIcon } from "../components/ui";

export const STATUS_LABEL: Record<CaptureRow["status"], string> = {
  queued: "Saved",
  processing: "Filing…",
  done: "Filed",
  needs_review: "Needs a look",
  failed: "Failed",
  dismissed: "Dismissed",
};

export function statusStyle(s: CaptureRow["status"]): { background: string; color: string } {
  if (s === "done") return { background: "var(--nature-soft)", color: "var(--nature-ink)" };
  if (s === "needs_review" || s === "failed") return { background: "var(--culture-soft)", color: "var(--culture-ink)" };
  return { background: "var(--accent-soft)", color: "var(--accent-ink)" };
}

export function timeAgo(iso: string): string {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export function captureText(c: CaptureRow): string {
  return c.raw_text ?? c.url ?? (c.has_file ? "Screenshot" : "");
}

function RecentBody({ c }: { c: CaptureRow }) {
  return (
    <>
      <span className="flex items-start gap-2.5">
        <span className="mt-0.5 shrink-0 text-muted">
          <SourceIcon source={c.source} />
        </span>
        <span className="block min-w-0 flex-1">
          <span className="line-clamp-2 text-[15px] leading-snug">{c.title ?? captureText(c)}</span>
          {c.title && <span className="mt-0.5 block truncate text-xs text-muted">{captureText(c)}</span>}
        </span>
      </span>
      <span className="mt-2 flex items-center gap-2 text-xs text-muted">
        <span className="rounded-full px-2 py-0.5 font-semibold" style={statusStyle(c.status)}>
          {STATUS_LABEL[c.status]}
        </span>
        <span className="font-mono">
          {c.created_by} · {timeAgo(c.created_at)}
        </span>
      </span>
    </>
  );
}

export function CaptureScreen({
  me,
  captures,
  ideas,
  onOpen,
  onSaved,
  onQueued,
  onSettings,
}: {
  me: Me;
  captures: CaptureRow[];
  ideas: Idea[];
  onOpen: (idea: Idea) => void;
  onSaved: (c: CaptureRow) => void;
  onQueued: () => void;
  onSettings: () => void;
}) {
  const [text, setText] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const reduce = useReducedMotion();
  const [listening, setListening] = useState(false);
  const recognizer = useRef<SpeechRecognitionLike | null>(null);
  const Speech = speechRecognition();

  // Voice note (PLAN.md §4.1): the browser's own speech-to-text fills the box; nothing leaves the phone
  // until Save.
  function toggleVoice() {
    if (listening) {
      recognizer.current?.stop();
      return;
    }
    if (!Speech) return;
    const r = new Speech();
    r.lang = navigator.language || "en-US";
    r.interimResults = false;
    r.continuous = false;
    r.onresult = (e) => {
      const said = Array.from(e.results)
        .map((res) => res[0].transcript)
        .join(" ")
        .trim();
      if (said) setText((t) => (t.trim() ? `${t.trim()} ${said}` : said));
    };
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    recognizer.current = r;
    setListening(true);
    r.start();
  }

  const places = new Set(ideas.flatMap((i) => i.places.map((p) => p.id))).size;
  const canSave = !saving && (text.trim().length > 0 || image !== null);

  async function save() {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const saved = image ? await api.captureImage(image, text.trim()) : await api.capture(text.trim());
      onSaved(saved);
      setText("");
      setImage(null);
      box.current?.focus();
    } catch (e) {
      const unreachable = !(e instanceof ApiError) || e.status === 401 || e.status >= 500;
      if (unreachable) {
        // Never lose an idea: keep it on the phone and send it later.
        await enqueue({ text: text.trim(), files: image ? [image] : [], source_app: "web" });
        setText("");
        setImage(null);
        onQueued();
      } else {
        setError(`Not saved: ${e.message}`);
      }
    } finally {
      setSaving(false);
    }
  }

  function onPaste(e: React.ClipboardEvent) {
    const img = [...e.clipboardData.files].find((f) => f.type.startsWith("image/"));
    if (img) {
      e.preventDefault();
      setImage(img);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 pb-6" style={{ paddingTop: "max(28px, env(safe-area-inset-top))" }}>
      <header className="flex items-end justify-between gap-3 px-1.5 pt-4">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="t-display m-0">
            {greeting()}, {me.display_name}
          </h1>
          <span className="font-mono text-xs text-muted">
            {ideas.length} ideas · {places} places
          </span>
        </div>
        <button
          type="button"
          onClick={onSettings}
          aria-label="Settings"
          className="grid size-10 shrink-0 place-items-center rounded-xl border border-line bg-surface text-text"
        >
          <Icon name="settings" size={18} />
        </button>
      </header>

      <section className="mt-5 rounded-[22px] border border-line bg-surface p-4 shadow-[0_8px_28px_var(--shadow)]">
        <label htmlFor="capture-box" className="t-label text-muted">
          New idea
        </label>
        <textarea
          id="capture-box"
          ref={box}
          autoFocus
          rows={4}
          placeholder="A place, a link, a half-remembered idea…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onPaste={onPaste}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) save();
          }}
          className="mt-2 block w-full resize-none border-0 bg-transparent p-0 text-[17px] leading-[1.45] text-text outline-none placeholder:text-muted"
        />
        {image && (
          <div className="mt-2 flex items-center gap-2 rounded-xl border border-line px-3 py-2 text-[13px]">
            <Icon name="image" size={16} />
            <span className="min-w-0 flex-1 truncate">{image.name || "Pasted image"}</span>
            <button type="button" aria-label="Remove image" onClick={() => setImage(null)} className="text-muted">
              <Icon name="close" size={16} />
            </button>
          </div>
        )}
        <div className="mt-3 flex items-center gap-2">
          {Speech && (
            <button
              type="button"
              aria-label={listening ? "Stop listening" : "Say an idea"}
              aria-pressed={listening}
              onClick={toggleVoice}
              className={`grid size-10 place-items-center rounded-xl border ${listening ? "border-accent bg-accent-soft text-accent-ink" : "border-line text-text"}`}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden="true">
                <rect x="9" y="3" width="6" height="11" rx="3" />
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
              </svg>
            </button>
          )}
          <button
            type="button"
            aria-label="Add a screenshot"
            onClick={() => file.current?.click()}
            className="grid size-10 place-items-center rounded-xl border border-line text-text"
          >
            <Icon name="image" size={18} />
          </button>
          <input
            ref={file}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => setImage(e.target.files?.[0] ?? null)}
          />
          <span className="flex-1 text-[13px]" aria-live="polite" style={{ color: "var(--culture-ink)" }}>
            {error}
          </span>
          <button
            type="button"
            onClick={save}
            disabled={!canSave}
            className="h-11 rounded-xl bg-accent px-5 text-sm font-semibold text-on-accent transition-opacity duration-150 disabled:opacity-40"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </section>

      <section className="mt-6">
        <h2 className="t-label m-0 px-1.5 text-muted">Recent</h2>
        {captures.length === 0 ? (
          <p className="px-1.5 text-sm text-muted">Nothing yet. Your first idea goes in the box above.</p>
        ) : (
          <ul className="m-0 mt-2.5 flex list-none flex-col gap-2 p-0">
            <AnimatePresence initial={false}>
              {captures.slice(0, 6).map((c) => {
                const idea = ideas.find((i) => i.capture_id === c.id);
                return (
                <motion.li
                  key={c.id}
                  layout={!reduce}
                  initial={reduce ? { opacity: 0 } : { opacity: 0, y: -36, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0 }}
                  transition={reduce ? { duration: 0.12 } : { type: "spring", stiffness: 380, damping: 30 }}
                  className="overflow-hidden rounded-[14px] border border-line bg-surface"
                >
                  {idea ? (
                    <button
                      type="button"
                      onClick={() => onOpen(idea)}
                      className="block w-full cursor-pointer px-3.5 py-3 text-left active:opacity-70"
                    >
                      <RecentBody c={c} />
                    </button>
                  ) : (
                    <div className="px-3.5 py-3">
                      <RecentBody c={c} />
                    </div>
                  )}
                </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
        )}
      </section>
    </div>
  );
}

// The Web Speech API isn't in TypeScript's DOM types yet; this is the slice Capture uses.
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}

function speechRecognition(): (new () => SpeechRecognitionLike) | null {
  const w = window as unknown as Record<string, unknown>;
  return (w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null) as (new () => SpeechRecognitionLike) | null;
}
