import { useMemo, useState } from "react";
import type { Family, Idea, MapPoints } from "../api";
import { Chip, FAMILIES, FAMILY_LABEL, Icon, monthRange } from "../components/ui";
import { GlobeMap, type PileData } from "../map/GlobeMap";

type Filter = "all" | Family | "both";

export function GlobeScreen({
  points,
  ideas,
  onOpenPile,
}: {
  points: MapPoints;
  ideas: Idea[];
  onOpenPile: (pile: PileData) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [hot, setHot] = useState<PileData | null>(null);

  const shown = useMemo<MapPoints>(
    () => ({
      type: "FeatureCollection",
      features: points.features.filter((f) =>
        filter === "all" ? true : filter === "both" ? f.properties.both : f.properties.family === filter,
      ),
    }),
    [points, filter],
  );
  const places = new Set(points.features.map((f) => f.properties.place_id)).size;

  const hotIdeas = hot ? ideas.filter((i) => hot.ideaIds.includes(i.id)) : [];
  const best = monthRange([...new Set(hotIdeas.flatMap((i) => i.best_months))]);
  const mixLine = hot
    ? FAMILIES.filter((f) => hot.mix[f])
        .map((f) => `${hot.mix[f]} ${FAMILY_LABEL[f].toLowerCase()}`)
        .join(", ")
    : "";

  return (
    <div className="relative flex min-h-0 flex-1 flex-col" style={{ paddingTop: "max(28px, env(safe-area-inset-top))" }}>
      <header className="flex items-end justify-between px-[22px] pt-4">
        <div className="flex flex-col gap-1">
          <h1 className="t-display m-0">Your world</h1>
          <span className="font-mono text-xs text-muted">
            {ideas.length} ideas · {places} places
          </span>
        </div>
      </header>
      <div role="group" aria-label="Filter ideas" className="flex gap-1.5 overflow-x-auto px-4 pt-4 [scrollbar-width:none]">
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
      </div>

      <div className="relative min-h-0 flex-1">
        <GlobeMap
          points={shown}
          onSelect={onOpenPile}
          onPiles={(piles) => setHot(piles.reduce<PileData | null>((a, p) => (!a || p.count > a.count ? p : a), null))}
        />
        {points.features.length === 0 && (
          <p className="pointer-events-none absolute inset-x-8 top-1/2 m-0 -translate-y-1/2 text-center text-sm text-muted">
            Ideas appear here once they're filed with a place.
          </p>
        )}
      </div>

      {hot && hot.count > 1 && (
        <section
          aria-label="Hotspot"
          className="mx-3 mb-3 flex flex-col gap-2.5 rounded-[22px] border border-line bg-surface px-[18px] pt-3.5 pb-4 shadow-[0_8px_28px_var(--shadow)]"
        >
          <div className="flex items-center justify-between">
            <span className="t-label flex items-center gap-1.5 text-hot">
              <Icon name="flame" size={14} stroke={2} />
              Hotspot in view
            </span>
            {best && <span className="font-mono text-xs text-muted">Best {best}</span>}
          </div>
          <div className="flex flex-col gap-0.5">
            <h2 className="t-title m-0">{hot.label} is filling up</h2>
            <p className="m-0 text-sm text-muted">
              {hot.count} ideas: {mixLine}
              {hot.both ? ` · you both ♥ ${hot.both}` : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={() => onOpenPile(hot)}
            className="h-[42px] rounded-xl border border-line text-sm font-semibold text-text"
          >
            See the {hot.count} ideas
          </button>
        </section>
      )}
    </div>
  );
}
