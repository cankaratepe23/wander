// MapLibre v6 is ESM-only and loads its worker from a separate module next to its own file.
// Once bundled, the library no longer sits next to that file, so point it at the copied asset.
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "maplibre-gl/dist/maplibre-gl.css";

maplibregl.setWorkerUrl(workerUrl);

export { maplibregl };
