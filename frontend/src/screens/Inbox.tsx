import { useState } from "react";
import { api, type Capture, type Family, type Idea } from "../api";
import { emptyMix, Pile } from "../components/Pile";
import { Chip, FAMILIES, FAMILY_LABEL, Heart, Icon } from "../components/ui";
import { captureText, STATUS_LABEL, statusStyle, timeAgo } from "./Capture";

type Filter = "all" | Family | "both" | "review" | "imported";

export function InboxScreen({
  ideas,
  captures,
  onOpen,
  only,
  onClearOnly,
  onChanged,
}: {
  ideas: Idea[];
  captures: Capture[];
  onOpen: (idea: Idea) => void;
  only?: { label: string; ids: number[] } | null;
  onClearOnly?: () => void;
  onChanged: () => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  // Imported items in progress are tracked in Settings → Import, not listed here one by one.
  const pending = captures.filter(
    (c) => c.status !== "done" && c.status !== "dismissed" && (c.kind !== "import" || c.status === "needs_review"),
  );
  const review = pending.filter((c) => c.status === "needs_review" || c.status === "failed");

  const unreviewed = ideas.filter((i) => !i.reviewed && i.status !== "dismissed");
  let shown = (only ? ideas.filter((i) => only.ids.includes(i.id)) : ideas).filter(
    (i) => i.status !== "dismissed" && (filter === "imported" ? !i.reviewed : i.reviewed),
  );
  if (filter === "both") shown = shown.filter((i) => i.hearted_by.length >= 2);
  else if (filter !== "all" && filter !== "review") shown = shown.filter((i) => i.family === filter);

  return (
    <div className="flex min-h-0 flex-1 flex-col" style={{ paddingTop: "max(28px, env(safe-area-inset-top))" }}>
      <header className="flex flex-col gap-1 px-[22px] pt-4">
        <h1 className="t-display m-0">{only ? only.label : "Inbox"}</h1>
        <span className="font-mono text-xs text-muted">
          {shown.length} ideas{review.length ? ` · ${review.length} need a look` : ""}
        </span>
      </header>

      <div role="group" aria-label="Filter" className="flex gap-1.5 overflow-x-auto px-4 pt-4 pb-1 [scrollbar-width:none]">
        {only && (
          <Chip active onClick={() => onClearOnly?.()}>
            {only.label} ✕
          </Chip>
        )}
        <Chip active={filter === "all"} onClick={() => setFilter("all")}>
          All
        </Chip>
        {FAMILIES.map((f) => (
          <Chip key={f} active={filter === f} onClick={() => setFilter(f)} dot={`var(--${f})`}>
            {FAMILY_LABEL[f]}
          </Chip>
        ))}
        <Chip active={filter === "both"} onClick={() => setFilter("both")}>
          ♥ Both
        </Chip>
        {review.length > 0 && (
          <Chip active={filter === "review"} onClick={() => setFilter("review")}>
            Needs a look · {review.length}
          </Chip>
        )}
        {unreviewed.length > 0 && (
          <Chip active={filter === "imported"} onClick={() => setFilter("imported")}>
            From imports · {unreviewed.length}
          </Chip>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-3 pb-6">
        {filter === "review" || (filter === "all" && !only && pending.length > 0) ? (
          <section className="mb-5">
            <h2 className="t-label m-0 mb-2 px-1.5 text-muted">{filter === "review" ? "Needs a look" : "Not filed yet"}</h2>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {(filter === "review" ? review : pending).map((c) => (
                <li key={c.id} className="rounded-[14px] border border-line bg-surface px-3.5 py-3">
                  <div className="line-clamp-2 text-[15px] leading-snug">{captureText(c)}</div>
                  {c.error && <div className="mt-1 text-[13px] text-muted">{c.error}</div>}
                  <div className="mt-2 flex items-center gap-2 text-xs text-muted">
                    <span className="rounded-full px-2 py-0.5 font-semibold" style={statusStyle(c.status)}>
                      {STATUS_LABEL[c.status]}
                    </span>
                    <span className="font-mono">
                      {c.created_by} · {timeAgo(c.created_at)}
                    </span>
                  </div>
                  {(c.status === "needs_review" || c.status === "failed") && (
                    <div className="mt-2.5 flex gap-2">
                      <button
                        type="button"
                        onClick={() => api.reenrich(c.id).then(onChanged)}
                        className="flex h-9 items-center gap-1.5 rounded-xl border border-line px-3 text-[13px] font-semibold"
                      >
                        <Icon name="refresh" size={14} />
                        Try again
                      </button>
                      <button
                        type="button"
                        onClick={() => api.dismiss(c.id).then(onChanged)}
                        className="h-9 rounded-xl px-3 text-[13px] font-semibold text-muted"
                      >
                        Dismiss
                      </button>
                      {c.url && (
                        <a
                          href={c.url}
                          target="_blank"
                          rel="noreferrer"
                          className="ml-auto flex h-9 items-center gap-1.5 px-1 text-[13px] font-semibold text-accent"
                        >
                          <Icon name="link" size={14} />
                          Open
                        </a>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {filter !== "review" && (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {shown.map((i) => {
              const mix = emptyMix();
              mix[i.family] = 1;
              const p = i.places[0];
              return (
                <li key={i.id}>
                  <button
                    type="button"
                    onClick={() => onOpen(i)}
                    className="flex w-full items-center gap-3 rounded-[14px] border border-line bg-surface px-3.5 py-3 text-left"
                  >
                    <span className="grid size-9 shrink-0 place-items-center">
                      <Pile mix={mix} count={1} />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="truncate text-[15px] font-semibold">{i.title}</span>
                      <span className="truncate font-mono text-xs text-muted">
                        {p ? [p.name, p.country].filter(Boolean).join(" · ") : "No place yet"}
                      </span>
                    </span>
                    {!i.reviewed && (
                      <span className="flex shrink-0 gap-1.5" onClick={(e) => e.stopPropagation()}>
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={() => api.patchIdea(i.id, { reviewed: true }).then(onChanged)}
                          className="rounded-lg bg-accent px-2.5 py-1 text-[12px] font-semibold text-on-accent"
                        >
                          Keep
                        </span>
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={() => api.patchIdea(i.id, { status: "dismissed", reviewed: true }).then(onChanged)}
                          className="rounded-lg border border-line px-2.5 py-1 text-[12px] font-semibold text-muted"
                        >
                          Drop
                        </span>
                      </span>
                    )}
                    {i.reviewed && i.hearted_by.length > 0 && (
                      <span className="flex items-center gap-1 font-mono text-xs text-muted">
                        <Heart filled={i.hearted_by_me} />
                        {i.hearted_by.length >= 2 ? "both" : i.hearted_by[0]}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
            {shown.length === 0 && <p className="px-1.5 text-sm text-muted">No ideas here yet.</p>}
          </ul>
        )}
      </div>
    </div>
  );
}
