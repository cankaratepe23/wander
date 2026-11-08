// Thin client for the Wander API. Auth is Cloudflare Access's cookie, sent automatically
// because the SPA and the API share one origin.

export interface Me {
  email: string;
  display_name: string;
}

export interface Capture {
  id: number;
  kind: "text" | "url" | "image" | "voice" | "import";
  raw_text: string | null;
  url: string | null;
  has_file: boolean;
  status: "queued" | "processing" | "done" | "needs_review" | "failed";
  error: string | null;
  created_by: string;
  created_at: string;
}

export type Family = "food" | "nature" | "stays" | "culture";

export interface Place {
  id: number;
  name: string;
  type: string;
  lat: number;
  lng: number;
  country_code: string | null;
  country: string | null;
  region: string | null;
  city: string | null;
}

export interface Idea {
  id: number;
  capture_id: number | null;
  title: string;
  summary: string | null;
  category: string;
  family: Family;
  tags: string[];
  best_months: number[];
  good_months: number[];
  budget_level: number | null;
  trip_length_hint: string | null;
  status: string;
  created_by: string;
  created_at: string;
  places: Place[];
  hearted_by: string[];
  hearted_by_me: boolean;
}

export interface MapPointProps {
  idea_id: number;
  place_id: number;
  name: string;
  city: string;
  region: string;
  country: string;
  family: Family;
  both: number;
}

export interface MapPoints {
  type: "FeatureCollection";
  features: { type: "Feature"; geometry: { type: "Point"; coordinates: [number, number] }; properties: MapPointProps }[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin", ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => request<Me>("/api/me"),
  captures: () => request<Capture[]>("/api/captures"),
  capture: (text: string) =>
    request<Capture>("/api/capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, source_app: "web" }),
    }),
  captureImage: (file: File, text: string) => {
    const form = new FormData();
    form.set("file", file);
    if (text) form.set("text", text);
    form.set("source_app", "web");
    return request<Capture>("/api/capture", { method: "POST", body: form });
  },
  ideas: () => request<Idea[]>("/api/ideas"),
  heart: (id: number) => request<Idea>(`/api/ideas/${id}/heart`, { method: "POST" }),
  map: () => request<MapPoints>("/api/map"),
};
