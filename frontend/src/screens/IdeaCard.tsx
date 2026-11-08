import { motion, useReducedMotion } from "motion/react";
import { lazy, Suspense, useState } from "react";
import { api, ApiError, type Idea, type IdeaStatus } from "../api";
import { FAMILY_LABEL, Heart, Icon, MonthBar } from "../components/ui";
import { timeAgo } from "./Capture";

const RegionMap = lazy(() => import("../map/RegionMap").then((m) => ({ default: m.RegionMap })));

const STATUSES: { id: IdeaStatus; label: string }[] = [
  { id: "someday", label: "Someday" },
  { id: "shortlist", label: "Shortlist" },
  { id: "planned", label: "Planned" },
  { id: "done", label: "Been" },
];

const PLATFORM: Record<string, string> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  youtube: "YouTube",
  google_maps: "Google Maps",
  booking: "Booking.com",
  airbnb: "Airbnb",
  web: "Web page",
};

function placeLine(idea: Idea): string {
  const p = idea.places[0];
  if (!p) return "No place yet";
  return [p.name, p.city !== p.name ? p.city : null, p.country].filter(Boolean).join(" · ");
}

export function IdeaCard({
  idea,
  onClose,
  onHeart,
  onChange,
}: {
  idea: Idea;
  onClose: () => void;
  onHeart: () => void;
  onChange: (next: Idea) => void;
}) {
  const reduce = useReducedMotion();
  const p = idea.places[0];
  const both = idea.hearted_by.length >= 2;
  const [notes, setNotes] = useState(idea.notes ?? "");
  const [editingTitle, setEditingTitle] = useState(false);
  const [title, setTitle] = useState(idea.title);
  const [placeQuery, setPlaceQuery] = useState("");
  const [placeError, setPlaceError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const patch = (body: Parameters<typeof api.patchIdea>[1]) => api.patchIdea(idea.id, body).then(onChange).catch(() => {});

  async function fixPlace() {
    if (!placeQuery.trim()) return;
    setBusy(true);
    setPlaceError(null);
    try {
      onChange(await api.addPlace(idea.id, placeQuery.trim()));
      setPlaceQuery("");
    } catch (e) {
      setPlaceError(e instanceof ApiError ? e.message : "Couldn't reach Wander");
    } finally {
      setBusy(false);
    }
  }

  return (
    <motion.div
      role="dialog"
      aria-label={idea.title}
      initial={reduce ? { opacity: 0 } : { y: "100%" }}
      animate={reduce ? { opacity: 1 } : { y: 0 }}
      exit={reduce ? { opacity: 0 } : { y: "100%" }}
      transition={reduce ? { duration: 0.12 } : { type: "spring", stiffness: 380, damping: 36 }}
      className="absolute inset-0 z-20 flex flex-col bg-bg"
    >
      <div className="relative h-[280px] shrink-0 border-b border-line">
        {p ? (
          <Suspense fallback={<div className="size-full" />}>
            <RegionMap places={idea.places} family={idea.family} />
          </Suspense>
        ) : idea.thumbnail ? (
          <img src={idea.thumbnail} alt="" className="size-full object-cover" />
        ) : (
          <div className="size-full bg-surface" />
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label="Back"
          className="absolute left-4 grid size-10 place-items-center rounded-xl border border-line bg-surface text-text"
          style={{ top: "max(16px, env(safe-area-inset-top))" }}
        >
          <Icon name="back" size={18} stroke={2} />
        </button>
        {p && (
          <span
            className="absolute right-4 rounded-[10px] border border-line bg-surface px-2.5 py-1 font-mono text-[11.5px] text-muted"
            style={{ top: "max(24px, calc(env(safe-area-inset-top) + 8px))" }}
          >
            {Math.abs(p.lat).toFixed(2)}° {p.lat >= 0 ? "N" : "S"} · {Math.abs(p.lng).toFixed(2)}° {p.lng >= 0 ? "E" : "W"}
          </span>
        )}
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto px-[22px] pt-[18px] pb-4">
        <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
          <span
            className="flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-semibold"
            style={{ background: `var(--${idea.family}-soft)`, color: `var(--${idea.family}-ink)` }}
          >
            <span className="size-[7px] rounded-full" style={{ background: `var(--${idea.family})` }} />
            {idea.category === "other" ? FAMILY_LABEL[idea.family] : idea.category[0].toUpperCase() + idea.category.slice(1)}
          </span>
          <span>
            {idea.source_platform ? `${PLATFORM[idea.source_platform] ?? idea.source_platform} · ` : ""}saved by{" "}
            {idea.created_by} · {timeAgo(idea.created_at)}
          </span>
        </div>

        {editingTitle ? (
          <input
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => {
              setEditingTitle(false);
              if (title.trim() && title !== idea.title) patch({ title: title.trim() });
              else setTitle(idea.title);
            }}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
            aria-label="Title"
            className="m-0 w-full rounded-lg border border-line bg-surface px-2 py-1 text-[26px] leading-[1.1] font-[640] tracking-[-0.035em] text-text outline-none"
          />
        ) : (
          <h1
            className="m-0 cursor-text text-[30px] leading-[1.08] font-[640] tracking-[-0.035em]"
            onClick={() => setEditingTitle(true)}
            title="Tap to edit"
          >
            {idea.title}
          </h1>
        )}
        <span className="font-mono text-xs text-muted">{placeLine(idea)}</span>
        {idea.summary && <p className="m-0 text-[15.5px] leading-normal text-soft">{idea.summary}</p>}

        <div role="group" aria-label="Status" className="mt-1 grid grid-cols-4 gap-1 rounded-[14px] border border-line bg-surface p-1">
          {STATUSES.map((s) => (
            <button
              key={s.id}
              type="button"
              aria-pressed={idea.status === s.id}
              onClick={() => patch({ status: s.id })}
              className={`h-9 rounded-[10px] text-[13px] font-semibold transition-colors duration-150 ${
                idea.status === s.id ? "bg-text text-bg" : "text-muted"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-3 gap-2">
          <Stat k="Length" v={idea.trip_length_hint ?? "—"} />
          <Stat k="Budget" v={idea.budget_level ? "€".repeat(idea.budget_level) : "—"} />
          <Stat k="Who" v={both ? "You both" : idea.hearted_by.length ? idea.hearted_by[0] : "No ♥ yet"} />
        </div>

        <div className="mt-1 flex flex-col gap-1.5">
          <span className="t-label text-muted">When to go</span>
          <MonthBar best={idea.best_months} good={idea.good_months} />
        </div>

        <div className="mt-2 flex flex-col gap-1.5">
          <span className="t-label text-muted">Places</span>
          {idea.places.map((pl) => (
            <div key={pl.id} className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-[14px]">
              <Icon name="pin" size={15} />
              <span className="min-w-0 flex-1 truncate">
                {pl.name}
                <span className="text-muted"> · {[pl.region, pl.country].filter(Boolean).join(", ")}</span>
              </span>
              <button
                type="button"
                aria-label={`Remove ${pl.name}`}
                onClick={() => api.removePlace(idea.id, pl.id).then(onChange).catch(() => {})}
                className="text-muted"
              >
                <Icon name="close" size={15} />
              </button>
            </div>
          ))}
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              fixPlace();
            }}
          >
            <input
              value={placeQuery}
              onChange={(e) => setPlaceQuery(e.target.value)}
              placeholder={idea.places.length ? "Wrong place? Add the right one" : "Add a place, e.g. Kaş, Türkiye"}
              aria-label="Add a place"
              className="h-10 min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 text-[14px] text-text outline-none placeholder:text-muted"
            />
            <button
              type="submit"
              disabled={busy || !placeQuery.trim()}
              className="h-10 rounded-xl border border-line px-3 text-[13px] font-semibold disabled:opacity-40"
            >
              {busy ? "…" : "Add"}
            </button>
          </form>
          {placeError && (
            <span className="text-[13px]" style={{ color: "var(--culture-ink)" }}>
              {placeError}
            </span>
          )}
        </div>

        <div className="mt-2 flex flex-col gap-1.5">
          <label htmlFor="idea-notes" className="t-label text-muted">
            Notes
          </label>
          <textarea
            id="idea-notes"
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => notes !== (idea.notes ?? "") && patch({ notes })}
            placeholder="Anything to remember about this one"
            className="resize-none rounded-xl border border-line bg-surface px-3 py-2 text-[14px] leading-normal text-text outline-none placeholder:text-muted"
          />
        </div>

        <div className="mt-2 flex items-center gap-3 text-[13px] font-semibold">
          {idea.source_url && (
            <a href={idea.source_url} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 text-accent">
              <Icon name="link" size={14} />
              Open the original
            </a>
          )}
          {idea.capture_id && (
            <button type="button" onClick={() => api.reenrich(idea.capture_id!)} className="flex items-center gap-1.5 text-muted">
              <Icon name="refresh" size={14} />
              Re-read
            </button>
          )}
          <button
            type="button"
            onClick={() => patch({ status: idea.status === "dismissed" ? "someday" : "dismissed" }).then(onClose)}
            className="ml-auto text-muted"
          >
            {idea.status === "dismissed" ? "Restore" : "Dismiss"}
          </button>
        </div>
      </div>

      <div
        className="flex shrink-0 gap-2 border-t border-line px-4 pt-3"
        style={{ paddingBottom: "max(16px, env(safe-area-inset-bottom))" }}
      >
        <a
          href={`#/chat?idea=${idea.id}`}
          onClick={onClose}
          className="flex h-[50px] flex-1 items-center justify-center gap-2 rounded-2xl border border-line bg-surface text-[15px] font-semibold text-text no-underline"
        >
          <Icon name="chat" size={18} />
          Chat about this
        </a>
        <button
          type="button"
          onClick={onHeart}
          aria-pressed={idea.hearted_by_me}
          className={`flex h-[50px] flex-1 items-center justify-center gap-2 rounded-2xl text-[15px] font-semibold ${
            idea.hearted_by_me ? "border border-line bg-surface text-text" : "bg-accent text-on-accent"
          }`}
        >
          <Heart filled={idea.hearted_by_me} size={16} />
          {idea.hearted_by_me ? "You want this" : "I want this"}
        </button>
      </div>
    </motion.div>
  );
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-[14px] border border-line bg-surface px-3 py-2.5">
      <span className="text-[11.5px] text-muted">{k}</span>
      <span className="truncate text-[15px] font-semibold">{v}</span>
    </div>
  );
}
