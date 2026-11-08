import { motion, useReducedMotion } from "motion/react";
import { lazy, Suspense } from "react";
import type { Idea } from "../api";
import { FAMILY_LABEL, Heart, Icon, MonthBar } from "../components/ui";
import { timeAgo } from "./Capture";

const RegionMap = lazy(() => import("../map/RegionMap").then((m) => ({ default: m.RegionMap })));

function placeLine(idea: Idea): string {
  const p = idea.places[0];
  if (!p) return "No place yet";
  return [p.name, p.city !== p.name ? p.city : null, p.country].filter(Boolean).join(" · ");
}

export function IdeaCard({ idea, onClose, onHeart }: { idea: Idea; onClose: () => void; onHeart: () => void }) {
  const reduce = useReducedMotion();
  const p = idea.places[0];
  const both = idea.hearted_by.length >= 2;
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
      <div className="relative h-[300px] shrink-0 border-b border-line">
        {p ? (
          <Suspense fallback={<div className="size-full" />}>
            <RegionMap places={idea.places} family={idea.family} />
          </Suspense>
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
            saved by {idea.created_by} · {timeAgo(idea.created_at)}
          </span>
        </div>
        <h1 className="m-0 text-[30px] leading-[1.08] font-[640] tracking-[-0.035em]">{idea.title}</h1>
        <span className="font-mono text-xs text-muted">{placeLine(idea)}</span>
        {idea.summary && <p className="m-0 text-[15.5px] leading-normal text-soft">{idea.summary}</p>}

        <div className="mt-1 grid grid-cols-3 gap-2">
          <Stat k="Length" v={idea.trip_length_hint ?? "—"} />
          <Stat k="Budget" v={idea.budget_level ? "€".repeat(idea.budget_level) : "—"} />
          <Stat k="Who" v={both ? "You both" : idea.hearted_by.length ? idea.hearted_by[0] : "No ♥ yet"} />
        </div>

        <div className="mt-1 flex flex-col gap-1.5">
          <span className="t-label text-muted">When to go</span>
          <MonthBar best={idea.best_months} good={idea.good_months} />
        </div>
      </div>

      <div className="flex shrink-0 gap-2 px-4 pt-2" style={{ paddingBottom: "max(20px, env(safe-area-inset-bottom))" }}>
        <button
          type="button"
          disabled
          title="Chat arrives in Phase 3"
          className="flex h-[50px] flex-1 items-center justify-center gap-2 rounded-2xl border border-line bg-surface text-[15px] font-semibold text-muted"
        >
          <Icon name="chat" size={18} />
          Chat soon
        </button>
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
