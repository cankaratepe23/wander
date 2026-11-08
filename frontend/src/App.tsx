import { AnimatePresence } from "motion/react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api, ApiError, type Capture, type Idea, type MapPoints, type Me } from "./api";
import { BottomNav, type Tab } from "./components/ui";
import { flush, pending } from "./queue";
import { Settings } from "./screens/Settings";
import type { PileData } from "./map/GlobeMap";
import { CaptureScreen } from "./screens/Capture";
import { ChatScreen, scopeFromHash } from "./screens/Chat";
import { IdeaCard } from "./screens/IdeaCard";
import { InboxScreen } from "./screens/Inbox";

// The map (MapLibre) is most of the bundle; load it only when the Globe tab is opened,
// so capturing an idea never waits for it.
const GlobeScreen = lazy(() => import("./screens/Globe").then((m) => ({ default: m.GlobeScreen })));

const TABS: Tab[] = ["inbox", "capture", "globe", "chat"];
const EMPTY_MAP: MapPoints = { type: "FeatureCollection", features: [] };

function tabFromHash(): Tab {
  const t = location.hash.replace("#/", "").split("?")[0] as Tab;
  return TABS.includes(t) ? t : "capture";
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [points, setPoints] = useState<MapPoints>(EMPTY_MAP);
  const [open, setOpen] = useState<Idea | null>(null);
  const [only, setOnly] = useState<{ label: string; ids: number[] } | null>(null);
  const [outbox, setOutbox] = useState<{ left: number; signedOut: boolean }>({ left: 0, signedOut: false });
  const [toast, setToast] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const say = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2600);
  }, []);

  // Send anything waiting in the outbox (offline saves and Android shares).
  const sendOutbox = useCallback(async () => {
    const { sent, left, signedOut } = await flush();
    setOutbox({ left, signedOut });
    if (sent.length) {
      setCaptures((prev) => [...sent.reverse(), ...prev.filter((c) => !sent.some((s) => s.id === c.id))]);
      say(sent.length === 1 ? "Saved ✓" : `${sent.length} saved ✓`);
    }
  }, [say]);

  const refresh = useCallback(() => {
    api.captures().then(setCaptures).catch(() => {});
    api.ideas().then(setIdeas).catch(() => {});
    api.map().then(setPoints).catch(() => {});
  }, []);

  useEffect(() => {
    api
      .me()
      .then((m) => {
        setMe(m);
        refresh();
        sendOutbox();
        // The server-side share fallback redirects here with how many it saved.
        const shared = Number(new URLSearchParams(location.hash.split("?")[1] ?? "").get("shared") ?? 0);
        if (shared > 0) say(shared === 1 ? "Saved ✓" : `${shared} saved ✓`);
      })
      .catch(async (e: unknown) => {
        // Offline with a cached shell: still let people capture, into the outbox.
        if (!(e instanceof ApiError)) {
          setMe({ email: "", display_name: "there" });
          setOutbox({ left: (await pending().catch(() => [])).length, signedOut: false });
          return;
        }
        setAuthError(e instanceof ApiError ? `${e.status}: ${e.message}` : "Can't reach Wander");
      });
  }, [refresh, sendOutbox, say]);

  useEffect(() => {
    addEventListener("online", sendOutbox);
    return () => removeEventListener("online", sendOutbox);
  }, [sendOutbox]);

  // While anything is still being filed, check the captures every few seconds, and reload the
  // ideas and the map only when one of them has finished.
  const filing = captures.filter((c) => c.status === "queued" || c.status === "processing").length;
  useEffect(() => {
    if (!filing) return;
    const t = setInterval(() => {
      api
        .captures()
        .then((next) => {
          setCaptures(next);
          if (next.filter((c) => c.status === "queued" || c.status === "processing").length < filing) refresh();
        })
        .catch(() => {});
    }, 4000);
    return () => clearInterval(t);
  }, [filing, refresh]);

  // The hash's query (e.g. which idea a chat is about) matters too, not just the tab.
  const [, setHashKey] = useState(location.hash);
  useEffect(() => {
    const onHash = () => {
      setTab(tabFromHash());
      setHashKey(location.hash);
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  const go = (t: Tab, query = "") => {
    location.hash = `#/${t}${query}`;
    setTab(t);
  };

  const heart = async (idea: Idea) => {
    const next = await api.heart(idea.id);
    setIdeas((all) => all.map((i) => (i.id === next.id ? next : i)));
    setOpen((o) => (o?.id === next.id ? next : o));
    api.map().then(setPoints).catch(() => {});
  };

  const openPile = (pile: PileData) => {
    if (pile.ideaIds.length === 1) {
      const idea = ideas.find((i) => i.id === pile.ideaIds[0]);
      if (idea) setOpen(idea);
      return;
    }
    setOnly({ label: pile.label, ids: pile.ideaIds });
    go("inbox");
  };

  if (authError) {
    return (
      <main className="grid h-full place-items-center p-8 text-center">
        <div>
          <h1 className="t-display m-0">Wander</h1>
          <p className="text-muted">Couldn't sign you in ({authError}).</p>
        </div>
      </main>
    );
  }
  if (!me) return <main className="h-full" aria-busy="true" />;

  return (
    <main className="relative mx-auto flex h-full max-w-[480px] flex-col overflow-hidden bg-bg">
      {tab === "capture" && (
        <CaptureScreen
          me={me}
          captures={captures.filter((c) => c.status !== "dismissed")}
          ideas={ideas}
          onSaved={(c) => setCaptures((prev) => [c, ...prev])}
          onQueued={async () => {
            setOutbox({ left: (await pending()).length, signedOut: false });
            say("Saved on this phone. It'll be sent when you're back online.");
          }}
          onSettings={() => setSettingsOpen(true)}
        />
      )}
      {tab === "inbox" && (
        <InboxScreen
          ideas={ideas}
          captures={captures}
          onOpen={setOpen}
          only={only}
          onClearOnly={() => setOnly(null)}
          onChanged={refresh}
        />
      )}
      {tab === "globe" && (
        <Suspense fallback={<div className="flex-1" aria-busy="true" />}>
          <GlobeScreen
            points={points}
            ideas={ideas}
            onOpenPile={openPile}
            onChat={(region) => go("chat", region ? `?region=${encodeURIComponent(region)}` : "")}
          />
        </Suspense>
      )}
      {(outbox.left > 0 || toast) && (
        <div
          role="status"
          className="pointer-events-none absolute inset-x-4 z-30 rounded-[14px] border border-line bg-surface px-4 py-3 text-sm shadow-[0_8px_28px_var(--shadow)]"
          style={{ bottom: "calc(96px + env(safe-area-inset-bottom))" }}
        >
          {toast ??
            (outbox.signedOut
              ? `${outbox.left} waiting. Open Wander while signed in to send ${outbox.left === 1 ? "it" : "them"}.`
              : `${outbox.left} waiting to be sent.`)}
        </div>
      )}
      {tab === "chat" && (
        <ChatScreen
          scope={scopeFromHash(ideas)}
          onBack={() => (history.length > 1 ? history.back() : go("globe"))}
          onChanged={refresh}
        />
      )}
      {tab !== "chat" && <BottomNav
        tab={tab}
        onTab={(t) => {
          if (t !== "inbox") setOnly(null);
          go(t);
        }}
      />}
      <AnimatePresence>
        {open && (
          <IdeaCard
            key={open.id}
            idea={open}
            onClose={() => setOpen(null)}
            onHeart={() => heart(open)}
            onChange={(next) => {
              setIdeas((all) => all.map((i) => (i.id === next.id ? next : i)));
              setOpen(next);
              api.map().then(setPoints).catch(() => {});
            }}
          />
        )}
        {settingsOpen && <Settings me={me} onClose={() => setSettingsOpen(false)} onReenriched={refresh} />}
      </AnimatePresence>
    </main>
  );
}
