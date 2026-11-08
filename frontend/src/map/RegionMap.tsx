import { maplibregl } from "./maplibre";
import { useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import type { Family, Place } from "../api";
import { emptyMix, Pile } from "../components/Pile";
import { meridianStyle } from "./style";

/** A small, still map of an idea's places (the top of the idea card). */
export function RegionMap({ places, family }: { places: Place[]; family: Family }) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!places.length) return;
    const map = new maplibregl.Map({
      container: box.current!,
      style: meridianStyle({ region: true }),
      center: [places[0].lng, places[0].lat],
      zoom: 8,
      interactive: false,
      attributionControl: { compact: true },
    });
    if (places.length > 1) {
      const b = new maplibregl.LngLatBounds();
      for (const p of places) b.extend([p.lng, p.lat]);
      map.fitBounds(b, { padding: 56, maxZoom: 11, duration: 0 });
    }
    const roots = places.map((p) => {
      const el = document.createElement("div");
      const root = createRoot(el);
      const mix = emptyMix();
      mix[family] = 1;
      root.render(
        <span className="flex items-center gap-1.5">
          <Pile mix={mix} count={1} />
          <span
            className="text-[12.5px] font-semibold text-text"
            style={{ textShadow: "0 0 3px var(--map-region-land), 0 0 3px var(--map-region-land)" }}
          >
            {p.name}
          </span>
        </span>,
      );
      new maplibregl.Marker({ element: el, anchor: "bottom-left", offset: [-14, 9] }).setLngLat([p.lng, p.lat]).addTo(map);
      return root;
    });
    return () => {
      roots.forEach((r) => setTimeout(() => r.unmount()));
      map.remove();
    };
  }, [places, family]);

  return <div ref={box} className="size-full" />;
}
