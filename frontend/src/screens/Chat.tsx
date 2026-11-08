import { motion, useReducedMotion } from "motion/react";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type ChatMessage, type Conversation, type Idea } from "../api";
import { Icon } from "../components/ui";

export interface ChatScope {
  scope: Conversation["scope"];
  scopeId?: string;
  label: string;
}

/** Read the chat's scope from the hash: #/chat?idea=12, #/chat?region=Portugal, or #/chat. */
export function scopeFromHash(ideas: Idea[]): ChatScope {
  const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
  const idea = params.get("idea");
  if (idea) {
    const found = ideas.find((i) => String(i.id) === idea);
    return { scope: "idea", scopeId: idea, label: found?.title ?? "This idea" };
  }
  const region = params.get("region");
  if (region) return { scope: "region", scopeId: region, label: region };
  return { scope: "global", label: "Your world" };
}

// Claude answers in light Markdown: paragraphs, "- " bullets and **bold**. Render just that, as text.
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>,
  );
}

function Prose({ text }: { text: string }) {
  const blocks = text.trim().split(/\n{2,}/);
  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        if (lines.every((l) => /^\s*[-*•] /.test(l))) {
          return (
            <ul key={i} className="m-0 flex list-disc flex-col gap-1 pl-5">
              {lines.map((l, j) => (
                <li key={j}>{inline(l.replace(/^\s*[-*•] /, ""))}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i} className="m-0">
            {lines.map((l, j) => (
              <Fragment key={j}>
                {j > 0 && <br />}
                {inline(l.replace(/^#+\s*/, ""))}
              </Fragment>
            ))}
          </p>
        );
      })}
    </>
  );
}

const SUGGESTIONS: Record<Conversation["scope"], string[]> = {
  idea: ["When's the best time for this?", "What else is nearby?", "Is this doable in a long weekend?"],
  region: ["What do we have here?", "Which of these could be one trip?", "When should we go?"],
  place: ["What do we have here?", "What else is nearby?"],
  global: ["Where are our ideas piling up?", "What could we do in May?", "What do we both want most?"],
};

export function ChatScreen({ scope, onBack, onChanged }: { scope: ChatScope; onBack: () => void; onChanged: () => void }) {
  const reduce = useReducedMotion();
  const [convo, setConvo] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState<{ text: string; steps: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  // Pick up the latest conversation for this scope, if there is one.
  useEffect(() => {
    let alive = true;
    setConvo(null);
    setMessages([]);
    api
      .conversations(scope.scope, scope.scopeId)
      .then(async (list) => {
        if (!alive || !list.length) return;
        const c = await api.conversation(list[0].id);
        if (!alive) return;
        setConvo(c);
        setMessages(c.messages);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [scope.scope, scope.scopeId]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "end" });
  }, [messages, live, reduce]);

  async function send(text: string) {
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    setDraft("");
    setMessages((m) => [...m, { id: Date.now(), role: "user", text: value }]);
    setLive({ text: "", steps: [] });
    try {
      const c = convo ?? (await api.newConversation(scope.scope, scope.scopeId));
      setConvo(c);
      let changed = false;
      await api.chat(c.id, value, (e) => {
        if (e.type === "text") setLive((l) => ({ text: (l?.text ?? "") + e.text, steps: l?.steps ?? [] }));
        else if (e.type === "tool") setLive((l) => ({ text: l?.text ?? "", steps: [...(l?.steps ?? []), e.label] }));
        else if (e.type === "changed") changed = true;
        else if (e.type === "error") setError(e.message);
      });
      const fresh = await api.conversation(c.id);
      setMessages(fresh.messages);
      if (changed) onChanged();
    } catch (e) {
      setError(e instanceof ApiError && e.status === 503 ? "Claude isn't connected yet." : "Couldn't reach Wander. Try again.");
    } finally {
      setLive(null);
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col" style={{ paddingTop: "max(20px, env(safe-area-inset-top))" }}>
      <header className="flex items-center gap-3 border-b border-line px-4 pt-3 pb-3">
        <button
          type="button"
          onClick={onBack}
          aria-label="Back"
          className="grid size-10 shrink-0 place-items-center rounded-xl border border-line bg-surface text-text"
        >
          <Icon name="back" size={18} stroke={2} />
        </button>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="t-label text-muted">Chat</span>
          <span className="truncate text-[17px] font-semibold tracking-[-0.02em]">{scope.label}</span>
        </div>
        {convo && (
          <button
            type="button"
            onClick={() => {
              setConvo(null);
              setMessages([]);
            }}
            className="h-9 shrink-0 rounded-xl border border-line px-3 text-[13px] font-semibold"
          >
            New chat
          </button>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4" aria-live="polite">
        {messages.length === 0 && !live && (
          <div className="flex flex-col gap-2 pt-2">
            <p className="m-0 px-1 text-sm text-muted">
              Ask about your ideas, or ask Claude to change them: fix a place, add a list of restaurants, shortlist something.
            </p>
            {SUGGESTIONS[scope.scope].map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => send(s)}
                className="self-start rounded-full border border-line bg-surface px-3.5 py-2 text-left text-[14px]"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        <div className="flex flex-col gap-3">
          {messages.map((m) => (
            <Bubble key={m.id} message={m} />
          ))}
          {live && <Bubble message={{ id: -1, role: "assistant", text: live.text, steps: live.steps }} thinking={!live.text} />}
          {error && (
            <p className="m-0 rounded-[14px] px-3 py-2 text-[13px]" style={{ background: "var(--culture-soft)", color: "var(--culture-ink)" }}>
              {error}
            </p>
          )}
        </div>
        <div ref={end} />
      </div>

      <form
        className="flex shrink-0 items-end gap-2 border-t border-line bg-bg px-3 pt-2.5"
        style={{ paddingBottom: "max(12px, env(safe-area-inset-bottom))" }}
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <textarea
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(draft);
            }
          }}
          placeholder="Ask or tell Claude…"
          aria-label="Message"
          className="max-h-32 min-h-[44px] flex-1 resize-none rounded-[14px] border border-line bg-surface px-3.5 py-2.5 text-[15px] leading-snug text-text outline-none placeholder:text-muted"
        />
        <motion.button
          type="submit"
          disabled={busy || !draft.trim()}
          whileTap={reduce ? undefined : { scale: 0.94 }}
          aria-label="Send"
          className="grid size-11 shrink-0 place-items-center rounded-[14px] bg-accent text-on-accent disabled:opacity-40"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
        </motion.button>
      </form>
    </div>
  );
}

function Bubble({ message, thinking }: { message: ChatMessage; thinking?: boolean }) {
  if (message.role === "user") {
    return (
      <div className="max-w-[85%] self-end rounded-[18px] rounded-br-md bg-text px-3.5 py-2.5 text-[15px] leading-snug whitespace-pre-wrap text-bg">
        {message.text}
      </div>
    );
  }
  return (
    <div className="flex max-w-[92%] flex-col gap-1.5 self-start">
      {!!message.steps?.length && (
        <div className="flex flex-wrap gap-1.5">
          {message.steps.map((s, i) => (
            <span key={i} className="rounded-full border border-line px-2 py-0.5 font-mono text-[11px] text-muted">
              {s}
            </span>
          ))}
        </div>
      )}
      {thinking ? (
        <span className="font-mono text-xs text-muted">Thinking…</span>
      ) : (
        message.text && <div className="flex flex-col gap-2 text-[15px] leading-normal text-text">{<Prose text={message.text} />}</div>
      )}
    </div>
  );
}
