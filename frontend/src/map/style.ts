import type { StyleSpecification } from "maplibre-gl";

// The Meridian map style (docs/design/meridian.md §6): OpenFreeMap vector tiles, flat land and ocean,
// a graticule at low zoom, hairline borders, sparse labels, globe projection and no atmosphere.
// Colours come from the CSS tokens, so the map follows the phone's light/dark setting.

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function graticule(step = 15): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (let lng = -180; lng < 180; lng += step) {
    const line: [number, number][] = [];
    for (let lat = -80; lat <= 80; lat += 2) line.push([lng, lat]);
    features.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: line } });
  }
  for (let lat = -75; lat <= 75; lat += step) {
    const line: [number, number][] = [];
    for (let lng = -180; lng <= 180; lng += 2) line.push([lng, lat]);
    features.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: line } });
  }
  return { type: "FeatureCollection", features };
}

export function meridianStyle(opts: { region?: boolean } = {}): StyleSpecification {
  const region = opts.region ?? false;
  const ocean = css(region ? "--map-region-ocean" : "--map-ocean");
  const land = css(region ? "--map-region-land" : "--map-land");
  const label = css("--muted");
  const halo = css("--bg");
  return {
    version: 8,
    projection: { type: region ? "mercator" : "globe" },
    sky: { "atmosphere-blend": 0 },
    glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
    sources: {
      omt: { type: "vector", url: "https://tiles.openfreemap.org/planet", attribution: "© OpenFreeMap © OpenStreetMap" },
      graticule: { type: "geojson", data: graticule() },
    },
    layers: [
      { id: "land", type: "background", paint: { "background-color": land } },
      { id: "water", type: "fill", source: "omt", "source-layer": "water", paint: { "fill-color": ocean } },
      ...(region
        ? [
            {
              id: "coast",
              type: "line" as const,
              source: "omt",
              "source-layer": "water",
              paint: { "line-color": css("--map-rim"), "line-width": 0.8 },
            },
          ]
        : []),
      {
        id: "graticule",
        type: "line",
        source: "graticule",
        maxzoom: 4,
        paint: { "line-color": css("--map-grat"), "line-width": 0.7 },
      },
      {
        id: "borders",
        type: "line",
        source: "omt",
        "source-layer": "boundary",
        minzoom: 2.5,
        filter: ["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 1]],
        paint: { "line-color": css("--map-border"), "line-width": 0.6 },
      },
      {
        id: "country-labels",
        type: "symbol",
        source: "omt",
        "source-layer": "place",
        minzoom: 2.5,
        maxzoom: 7,
        filter: ["==", ["get", "class"], "country"],
        layout: {
          "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]],
          "text-font": ["Noto Sans Regular"],
          "text-size": 11,
          "text-letter-spacing": 0.08,
          "text-transform": "uppercase",
        },
        paint: { "text-color": label, "text-halo-color": halo, "text-halo-width": 1.2 },
      },
      {
        id: "city-labels",
        type: "symbol",
        source: "omt",
        "source-layer": "place",
        minzoom: 5,
        filter: ["in", ["get", "class"], ["literal", ["city", "town"]]],
        layout: {
          "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]],
          "text-font": ["Noto Sans Regular"],
          "text-size": 12,
        },
        paint: { "text-color": label, "text-halo-color": halo, "text-halo-width": 1.2 },
      },
    ],
  };
}
