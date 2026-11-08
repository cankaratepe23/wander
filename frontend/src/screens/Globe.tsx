import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { api, type Family, type Hotspot, type Idea, type MapPoints } from "../api";
import { emptyMix, Pile } from "../components/Pile";
import { Chip, FAMILIES, FAMILY_LABEL, Icon, monthRange } from "../components/ui";
import { GlobeMap, type Focus, type PileData } from "../map/GlobeMap";

type Filter = "all" | Family | "both";
const ZOOM: Record<Hotspot["level"], number> = { country: 4.2, region: 6.2, city: 9 };

export function GlobeScreen({
  points,
  ideas,
  onOpenPile,
  onChat,
}: {
  points: MapPoints;
  ideas: Idea[];
  onOpenPile: (pile: PileData) => void;
  onChat: (region?: string) => void;
}) {
  const reduce = useReducedMotion();
  const [filter, setFilter] = useState<Filter>("all");
  const [hot, setHot] = useState<PileData | null>(null);
  const [heat, setHeat] = useState(false);
  const [panel, setPanel] = useState(false);
  const [focus, setFocus] = useState<Focus | null>(null);

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
      <header className="flex items-end justify-between gap-3 px-[22px] pt-4">
        <div className="flex flex-col gap-1">
          <h1 className="t-display m-0">Your world</h1>
          <span className="font-mono text-xs text-muted">
            {ideas.length} ideas · {places} places
          </span>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onChat()}
            aria-label="Ask about your ideas"
            className="grid size-10 place-items-center rounded-xl border border-line bg-surface text-text"
          >
            <Icon name="chat" size={18} />
          </button>
          <button
            type="button"
            onClick={() => setPanel(true)}
            className="flex h-10 items-center gap-1.5 rounded-xl border border-line bg-surface px-3 text-[13px] font-semibold text-text"
          >
            <Icon name="flame" size={15} stroke={2} />
            Hotspots
          </button>
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
          heat={heat}
          focus={focus}
          onSelect={onOpenPile}
          onPiles={(piles) => setHot(piles.reduce<PileData | null>((a, p) => (!a || p.count > a.count ? p : a), null))}
        />
        <div
          role="group"
          aria-label="Map style"
          className="absolute top-3 right-3 flex rounded-xl border border-line bg-surface p-0.5 text-[12px] font-semibold"
        >
          {(["Piles", "Heat"] as const).map((label) => {
            const on = (label === "Heat") === heat;
            return (
              <button
                key={label}
                type="button"
                aria-pressed={on}
                onClick={() => setHeat(label === "Heat")}
                className={`h-8 rounded-[10px] px-3 ${on ? "bg-text text-bg" : "text-muted"}`}
              >
                {label}
              </button>
            );
          })}
        </div>
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
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => onOpenPile(hot)}
              className="h-[42px] flex-1 rounded-xl border border-line text-sm font-semibold text-text"
            >
              See the {hot.count} ideas
            </button>
            <button
              type="button"
              onClick={() => onChat(hot.label)}
              className="h-[42px] flex-1 rounded-xl bg-accent text-sm font-semibold text-on-accent"
            >
              Plan with Claude
            </button>
          </div>
        </section>
      )}

      <AnimatePresence>
        {panel && (
          <HotspotsPanel
            reduce={!!reduce}
            onClose={() => setPanel(false)}
            onFocus={(h) => {
              setPanel(false);
              setHeat(false);
              setFocus({ lng: h.lng, lat: h.lat, zoom: ZOOM[h.level] });
            }}
            onChat={(h) => onChat(h.name)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

function HotspotsPanel({
  reduce,
  onClose,
  onFocus,
  onChat,
}: {
  reduce: boolean;
  onClose: () => void;
  onFocus: (h: Hotspot) => void;
  onChat: (h: Hotspot) => void;
}) {
  const [level, setLevel] = useState<Hotspot["level"]>("country");
  const [rows, setRows] = useState<Hotspot[] | null>(null);

  useEffect(() => {
    setRows(null);
    api.hotspots(level).then(setRows).catch(() => setRows([]));
  }, [level]);

  return (
    <motion.div
      role="dialog"
      aria-label="Hotspots"
      initial={reduce ? { opacity: 0 } : { y: "100%" }}
      animate={reduce ? { opacity: 1 } : { y: 0 }}
      exit={reduce ? { opacity: 0 } : { y: "100%" }}
      transition={reduce ? { duration: 0.12 } : { type: "spring", stiffness: 380, damping: 36 }}
      className="absolute inset-0 z-20 flex flex-col bg-bg"
      style={{ paddingTop: "max(28px, env(safe-area-inset-top))" }}
    >
      <header className="flex items-end justify-between px-[22px] pt-4">
        <div className="flex flex-col gap-1">
          <h1 className="t-display m-0">Hotspots</h1>
          <span className="font-mono text-xs text-muted">ranked by ideas, recency, hearts and variety</span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="grid size-10 place-items-center rounded-xl border border-line bg-surface text-text"
        >
          <Icon name="close" size={18} />
        </button>
      </header>
      <div role="group" aria-label="Level" className="mx-4 mt-4 grid grid-cols-3 gap-1 rounded-[14px] border border-line bg-surface p-1">
        {(["country", "region", "city"] as const).map((l) => (
          <button
            key={l}
            type="button"
            aria-pressed={level === l}
            onClick={() => setLevel(l)}
            className={`h-9 rounded-[10px] text-[13px] font-semibold capitalize ${level === l ? "bg-text text-bg" : "text-muted"}`}
          >
            {l === "city" ? "Cities" : l === "region" ? "Regions" : "Countries"}
          </button>
        ))}
      </div>
      <ol className="m-0 flex min-h-0 flex-1 list-none flex-col gap-2 overflow-y-auto px-4 pt-3 pb-6">
        {rows === null && <li className="px-1 text-sm text-muted">Loading…</li>}
        {rows?.length === 0 && <li className="px-1 text-sm text-muted">No hotspots yet. They appear as ideas get filed.</li>}
        {rows?.map((h, i) => {
          const mix = emptyMix();
          for (const f of FAMILIES) mix[f] = h.mix[f];
          return (
            <li key={`${h.name}-${h.within}`} className="flex items-center gap-3 rounded-[14px] border border-line bg-surface px-3 py-3">
              <span className="w-5 shrink-0 text-right font-mono text-xs text-muted">{i + 1}</span>
              <span className="grid w-9 shrink-0 place-items-center">
                <Pile mix={mix} count={1} />
              </span>
              <button type="button" onClick={() => onFocus(h)} className="flex min-w-0 flex-1 flex-col gap-0.5 text-left">
                <span className="truncate text-[15px] font-semibold">
                  {h.name}
                  {h.within && <span className="font-normal text-muted"> · {h.within}</span>}
                </span>
                <span className="truncate font-mono text-xs text-muted">
                  {h.ideas} ideas{h.both ? ` · ♥ both ${h.both}` : ""}
                  {h.best_months.length ? ` · best ${monthRange(h.best_months)}` : ""}
                </span>
              </button>
              <button
                type="button"
                onClick={() => onChat(h)}
                aria-label={`Plan ${h.name} with Claude`}
                className="grid size-9 shrink-0 place-items-center rounded-xl border border-line text-text"
              >
                <Icon name="chat" size={16} />
              </button>
            </li>
          );
        })}
      </ol>
    </motion.div>
  );
}
