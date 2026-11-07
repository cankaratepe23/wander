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
};
