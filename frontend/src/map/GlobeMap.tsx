import { maplibregl } from "./maplibre";
import type { GeoJSONSource, Map as MLMap, MapSourceDataEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { MapPointProps, MapPoints } from "../api";
import { emptyMix, Pile, pileHeight, type Mix } from "../components/Pile";
import { meridianStyle } from "./style";

export interface PileData {
  key: string;
  lngLat: [number, number];
  mix: Mix;
  count: number;
  both: number;
  places: number;
  label: string;
  ideaIds: number[];
  clusterId?: number;
}

const SOURCE = "ideas";
const CLUSTER_RADIUS = 44; // px, docs/design/meridian.md §7

/** Name a group of points by the lowest admin level they all share: city, then region, then country. */
function nameOf(points: MapPointProps[]): { label: string; places: number } {
  const places = new Set(points.map((p) => p.place_id)).size;
  if (places === 1) return { label: points[0].name, places };
  for (const level of ["city", "region", "country"] as const) {
    const v = points[0][level];
    if (v && points.every((p) => p[level] === v)) return { label: v, places };
  }
  const counts = new Map<string, number>();
  for (const p of points) counts.set(p.name, (counts.get(p.name) ?? 0) + 1);
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
  return { label: `${top} +${places - 1}`, places };
}

function pileFrom(key: string, lngLat: [number, number], points: MapPointProps[], clusterId?: number): PileData {
  const mix = emptyMix();
  for (const p of points) mix[p.family] += 1;
  return {
    key,
    lngLat,
    mix,
    count: points.length,
    both: points.reduce((n, p) => n + (p.both ? 1 : 0), 0),
    ideaIds: [...new Set(points.map((p) => p.idea_id))],
    clusterId,
    ...nameOf(points),
  };
}

function angularDistance(a: [number, number], b: [number, number]): number {
  const r = Math.PI / 180;
  const [l1, p1, l2, p2] = [a[0] * r, a[1] * r, b[0] * r, b[1] * r];
  return Math.acos(Math.min(1, Math.sin(p1) * Math.sin(p2) + Math.cos(p1) * Math.cos(p2) * Math.cos(l1 - l2))) / r;
}

async function computePiles(map: MLMap): Promise<PileData[]> {
  const src = map.getSource(SOURCE) as GeoJSONSource | undefined;
  if (!src) return [];
  const centre = map.getCenter();
  const c: [number, number] = [centre.lng, centre.lat];
  const seen = new Set<string>();
  const out: Promise<PileData>[] = [];
  for (const f of map.querySourceFeatures(SOURCE)) {
    const props = f.properties as Record<string, unknown>;
    const coords = (f.geometry as GeoJSON.Point).coordinates as [number, number];
    if (map.getZoom() < 4 && angularDistance(c, coords) > 82) continue; // far side of the globe
    if (props.cluster) {
      const id = props.cluster_id as number;
      const key = `c${id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(
        src
          .getClusterLeaves(id, props.point_count as number, 0)
          .then((leaves) => pileFrom(key, coords, leaves.map((l) => l.properties as MapPointProps), id)),
      );
    } else {
      const p = props as unknown as MapPointProps;
      const key = `p${p.idea_id}-${p.place_id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(Promise.resolve(pileFrom(key, coords, [p])));
    }
  }
  return Promise.all(out);
}

export function GlobeMap({
  points,
  onPiles,
  onSelect,
}: {
  points: MapPoints;
  onPiles?: (piles: PileData[]) => void;
  onSelect?: (pile: PileData) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const pointsRef = useRef(points);
  const markers = useRef(new Map<string, { marker: maplibregl.Marker; el: HTMLDivElement }>());
  const [piles, setPiles] = useState<PileData[]>([]);
  const onPilesRef = useRef(onPiles);
  onPilesRef.current = onPiles;

  useEffect(() => {
    const map = new maplibregl.Map({
      container: box.current!,
      style: meridianStyle(),
      center: [14, 36],
      zoom: 1.25,
      attributionControl: { compact: true },
      maxPitch: 0,
      renderWorldCopies: false,
    });
    mapRef.current = map;
    if (import.meta.env.DEV) (window as unknown as { __wanderMap: MLMap }).__wanderMap = map; // for debugging
    map.dragRotate.disable();
    map.touchZoomRotate.disableRotation();

    let pending = 0;
    const update = () => {
      const ticket = ++pending;
      computePiles(map).then((next) => {
        if (ticket !== pending) return; // a newer update is on its way
        setPiles(next);
        onPilesRef.current?.(next);
      });
    };
    const addSource = () => {
      if (map.getSource(SOURCE)) return;
      map.addSource(SOURCE, {
        type: "geojson",
        data: pointsRef.current,
        cluster: true,
        clusterRadius: CLUSTER_RADIUS,
        clusterMaxZoom: 16,
      });
      // querySourceFeatures needs the source's tiles loaded, which needs a layer that uses it.
      map.addLayer({ id: "ideas-hit", type: "circle", source: SOURCE, paint: { "circle-radius": 0, "circle-opacity": 0 } });
    };
    map.on("style.load", addSource);
    map.on("moveend", update);
    map.on("sourcedata", (e: MapSourceDataEvent) => {
      if (e.sourceId === SOURCE && e.isSourceLoaded) update();
    });

    const scheme = matchMedia("(prefers-color-scheme: dark)");
    const restyle = () => map.setStyle(meridianStyle(), { diff: false });
    scheme.addEventListener("change", restyle);

    return () => {
      scheme.removeEventListener("change", restyle);
      for (const { marker } of markers.current.values()) marker.remove();
      markers.current.clear();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    pointsRef.current = points;
    (mapRef.current?.getSource(SOURCE) as GeoJSONSource | undefined)?.setData(points);
  }, [points]);

  // Keep one MapLibre marker per pile; React renders into each marker's element through a portal.
  const map = mapRef.current;
  if (map) {
    const live = new Set(piles.map((p) => p.key));
    for (const [key, m] of markers.current) {
      if (!live.has(key)) {
        m.marker.remove();
        markers.current.delete(key);
      }
    }
    for (const p of piles) {
      const existing = markers.current.get(p.key);
      if (existing) existing.marker.setLngLat(p.lngLat);
      else {
        const el = document.createElement("div");
        const marker = new maplibregl.Marker({ element: el, anchor: "bottom", offset: [0, 9] }).setLngLat(p.lngLat).addTo(map);
        markers.current.set(p.key, { marker, el });
      }
    }
  }

  const callouts = new Set(
    [...piles]
      .sort((a, b) => b.count - a.count)
      .slice(0, 2)
      .filter((p) => p.count > 1)
      .map((p) => p.key),
  );

  const select = async (p: PileData) => {
    const m = mapRef.current;
    if (m && p.clusterId !== undefined && p.places > 1) {
      const src = m.getSource(SOURCE) as GeoJSONSource;
      const zoom = await src.getClusterExpansionZoom(p.clusterId);
      m.easeTo({ center: p.lngLat, zoom: Math.min(zoom + 0.3, 16), duration: 700 });
      return;
    }
    onSelect?.(p);
  };

  return (
    <div className="relative size-full">
      <div ref={box} className="size-full" />
      {piles.map((p) => {
        const slot = markers.current.get(p.key);
        if (!slot) return null;
        return createPortal(
          <button
            type="button"
            onClick={() => select(p)}
            aria-label={`${p.label}: ${p.count} idea${p.count === 1 ? "" : "s"}`}
            className="relative block cursor-pointer"
          >
            <Pile mix={p.mix} count={callouts.has(p.key) ? 1 : p.count} />
            {callouts.has(p.key) && <Callout pile={p} left={!!map && flipLeft(map, p)} />}
          </button>,
          slot.el,
          p.key,
        );
      })}
    </div>
  );
}

/** Flip a callout to the left only when, drawn on the right, it would be cut off. */
function flipLeft(map: MLMap, p: PileData): boolean {
  const labelWidth = Math.max(p.label.length * 7.2, 62);
  return map.project(p.lngLat).x + 52 + labelWidth > map.getContainer().clientWidth - 6;
}

/** A hairline leader from the top of the pile to a two-line label; flips left near the right edge. */
function Callout({ pile, left }: { pile: PileData; left: boolean }) {
  const lift = pileHeight(pile.mix) + 4;
  return (
    <span
      className="pointer-events-none absolute flex items-end"
      style={{ bottom: lift + 9, ...(left ? { right: 20, flexDirection: "row-reverse" } : { left: 20 }) }}
    >
      <svg width="30" height="22" className="shrink-0" style={{ marginBottom: -16, transform: left ? "scaleX(-1)" : undefined }} aria-hidden="true">
        <path d="M2 20L20 6H30" fill="none" stroke="var(--text)" strokeWidth="1" />
        <circle cx="2" cy="20" r="1.6" fill="var(--text)" />
      </svg>
      <span
        className={`flex flex-col whitespace-nowrap ${left ? "pr-1 text-right" : "pl-1 text-left"}`}
        style={{ marginBottom: -4, textShadow: "0 0 3px var(--map-ocean), 0 0 3px var(--map-ocean)" }}
      >
        <span className="text-[12.5px] font-[640] text-text">{pile.label}</span>
        <span className="font-mono text-[10.5px] text-muted">
          {pile.count} ideas
        </span>
      </span>
    </span>
  );
}
