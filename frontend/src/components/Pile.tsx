import { motion, useReducedMotion } from "motion/react";
import type { Family } from "../api";
import { FAMILIES } from "./ui";

// A pile: one isometric tile per idea, coloured by its category family (docs/design/meridian.md §7).
const A = 11; // half width of the top face (22 px tile)
const B = 5.4; // half height of the top face
const TH = 3.4; // side thickness
const GAP = 3.8; // vertical distance between tiles
const MAX = 8;
const JITTER = [0, 1.1, -0.9, 0.7, -1.2, 0.9, -0.6, 1.2];

export type Mix = Record<Family, number>;

export function tilesOf(mix: Mix): Family[] {
  const tiles: Family[] = [];
  for (const f of FAMILIES) for (let i = 0; i < mix[f]; i++) tiles.push(f);
  return tiles.slice(0, MAX);
}

/** Height of the drawn pile above its base point, for placing labels. */
export function pileHeight(mix: Mix): number {
  return (tilesOf(mix).length - 1) * GAP + B;
}

export function Pile({ mix, count, size = 1 }: { mix: Mix; count: number; size?: number }) {
  const reduce = useReducedMotion();
  const tiles = tilesOf(mix);
  const top = (tiles.length - 1) * GAP;
  const w = 2 * A + 6;
  const h = top + 2 * B + TH + 4;
  return (
    <span className="relative inline-flex items-end" style={{ width: w * size, height: h * size }}>
      <svg
        width={w * size}
        height={h * size}
        viewBox={`${-A - 3} ${-top - B - 2} ${w} ${h}`}
        overflow="visible"
        aria-hidden="true"
      >
        {tiles.map((f, i) => {
          const oy = -i * GAP;
          const ox = JITTER[i % JITTER.length];
          const col = `var(--${f})`;
          return (
            <motion.g
              key={`${i}-${f}`}
              initial={reduce ? { opacity: 0 } : { opacity: 0, y: -16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={reduce ? { duration: 0.12 } : { type: "spring", stiffness: 380, damping: 30, delay: i * 0.035 }}
            >
              <path
                d={`M${ox - A} ${oy}L${ox} ${oy + B}L${ox + A} ${oy}L${ox + A} ${oy + TH}L${ox} ${oy + B + TH}L${ox - A} ${oy + TH}Z`}
                style={{ fill: `color-mix(in oklab, ${col} 62%, black)`, stroke: "var(--map-ocean)", strokeWidth: 1 }}
              />
              <path
                d={`M${ox} ${oy - B}L${ox + A} ${oy}L${ox} ${oy + B}L${ox - A} ${oy}Z`}
                style={{ fill: col, stroke: "var(--map-ocean)", strokeWidth: 1 }}
              />
            </motion.g>
          );
        })}
      </svg>
      {count > 1 && (
        <span
          className="absolute font-mono text-[11px] font-semibold text-text"
          style={{
            left: (w - 2) * size,
            top: 0,
            textShadow: "0 0 3px var(--map-ocean), 0 0 3px var(--map-ocean), 0 0 2px var(--map-ocean)",
          }}
        >
          {count}
        </span>
      )}
    </span>
  );
}

export function emptyMix(): Mix {
  return { food: 0, nature: 0, stays: 0, culture: 0 };
}
