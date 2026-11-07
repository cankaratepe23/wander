import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Capture, type Me } from "./api";

const STATUS_LABEL: Record<Capture["status"], string> = {
  queued: "Saved",
  processing: "Filing…",
  done: "Filed",
  needs_review: "Needs a look",
  failed: "Failed",
};

function timeAgo(iso: string): string {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  const refresh = useCallback(() => {
    api.captures().then(setCaptures).catch(() => {});
  }, []);

  useEffect(() => {
    api
      .me()
      .then((m) => {
        setMe(m);
        refresh();
      })
      .catch((e: unknown) =>
        setAuthError(e instanceof ApiError ? `${e.status}: ${e.message}` : "Can't reach Wander"),
      );
  }, [refresh]);

  async function save() {
    const value = text.trim();
    if (!value || saving) return;
    setSaving(true);
    try {
      const saved = await api.capture(value);
      setCaptures((prev) => [saved, ...prev]);
      setText("");
      setFlash("Saved ✓");
      setTimeout(() => setFlash(null), 1800);
      box.current?.focus();
    } catch (e) {
      setFlash(e instanceof ApiError ? `Not saved: ${e.message}` : "Not saved: offline?");
    } finally {
      setSaving(false);
    }
  }

  if (authError) {
    return (
      <main className="shell">
        <h1 className="brand">Wander</h1>
        <p className="muted">Couldn't sign you in ({authError}).</p>
      </main>
    );
  }

  return (
    <main className="shell">
      <header className="top">
        <h1 className="brand">Wander</h1>
        {me && <span className="muted">hello, {me.display_name}</span>}
      </header>

      <section className="capture">
        <textarea
          ref={box}
          autoFocus
          rows={3}
          placeholder="A place, a link, a half-remembered idea…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) save();
          }}
        />
        <div className="row">
          <span className="flash" aria-live="polite">
            {flash}
          </span>
          <button onClick={save} disabled={!text.trim() || saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </section>

      <section>
        <h2 className="section-title">Recent</h2>
        {captures.length === 0 ? (
          <p className="muted">Nothing yet. Your first idea goes in the box above.</p>
        ) : (
          <ul className="list">
            {captures.map((c) => (
              <li key={c.id} className="item">
                <div className="item-text">
                  {c.raw_text ?? c.url ?? (c.has_file ? "📷 Screenshot" : "")}
                </div>
                <div className="item-meta">
                  <span className={`badge badge-${c.status}`}>{STATUS_LABEL[c.status]}</span>
                  <span>
                    {c.created_by} · {timeAgo(c.created_at)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
