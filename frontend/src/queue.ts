// The offline capture queue (PLAN.md §4.1). Anything that can't reach the server right away, and
// everything the Android share target receives, waits here in IndexedDB until it can be sent.
// public/sw.js writes to the same database, so keep DB/STORE in sync with it.
import { api, ApiError, type Capture } from "./api";

const DB = "wander";
const STORE = "outbox";

export interface Pending {
  id?: number;
  text: string;
  files: Blob[];
  source_app: string;
  at: number;
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const req = fn(db.transaction(STORE, mode).objectStore(STORE));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export const enqueue = (item: Omit<Pending, "id" | "at">) => tx("readwrite", (s) => s.add({ ...item, at: Date.now() }));
export const pending = () => tx<Pending[]>("readonly", (s) => s.getAll() as IDBRequest<Pending[]>);
const remove = (id: number) => tx("readwrite", (s) => s.delete(id));

async function send(item: Pending): Promise<Capture[]> {
  if (!item.files.length) return [await api.capture(item.text, item.source_app)];
  const out = [];
  for (const [i, f] of item.files.entries()) {
    out.push(await api.captureImage(f, i === 0 ? item.text : "", item.source_app, `shared-${item.at}-${i}`));
  }
  return out;
}

export type FlushResult = { sent: Capture[]; left: number; signedOut: boolean };

let flushing: Promise<FlushResult> | null = null;

/** Send everything queued, oldest first. Stops at the first failure and leaves the rest queued. */
export function flush(): Promise<FlushResult> {
  flushing ??= (async () => {
    const sent: Capture[] = [];
    let signedOut = false;
    const items = (await pending()).sort((a, b) => a.at - b.at);
    let left = items.length;
    for (const item of items) {
      try {
        sent.push(...(await send(item)));
        await remove(item.id!);
        left--;
      } catch (e) {
        signedOut = e instanceof ApiError && (e.status === 401 || e.status === 403);
        break;
      }
    }
    return { sent, left, signedOut };
  })().finally(() => {
    flushing = null;
  });
  return flushing;
}
