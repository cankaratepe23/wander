import { AnimatePresence } from "motion/react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api, ApiError, type Capture, type Idea, type MapPoints, type Me } from "./api";
import { BottomNav, type Tab } from "./components/ui";
import type { PileData } from "./map/GlobeMap";
import { CaptureScreen } from "./screens/Capture";
import { IdeaCard } from "./screens/IdeaCard";
import { InboxScreen } from "./screens/Inbox";

// The map (MapLibre) is most of the bundle; load it only when the Globe tab is opened,
// so capturing an idea never waits for it.
const GlobeScreen = lazy(() => import("./screens/Globe").then((m) => ({ default: m.GlobeScreen })));

const TABS: Tab[] = ["inbox", "capture", "globe"];
const EMPTY_MAP: MapPoints = { type: "FeatureCollection", features: [] };

function tabFromHash(): Tab {
  const t = location.hash.replace("#/", "") as Tab;
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
      })
      .catch((e: unknown) => setAuthError(e instanceof ApiError ? `${e.status}: ${e.message}` : "Can't reach Wander"));
  }, [refresh]);

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

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  const go = (t: Tab) => {
    location.hash = `#/${t}`;
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
        <CaptureScreen me={me} captures={captures} ideas={ideas} onSaved={(c) => setCaptures((prev) => [c, ...prev])} />
      )}
      {tab === "inbox" && (
        <InboxScreen ideas={ideas} captures={captures} onOpen={setOpen} only={only} onClearOnly={() => setOnly(null)} />
      )}
      {tab === "globe" && (
        <Suspense fallback={<div className="flex-1" aria-busy="true" />}>
          <GlobeScreen points={points} ideas={ideas} onOpenPile={openPile} />
        </Suspense>
      )}
      <BottomNav
        tab={tab}
        onTab={(t) => {
          if (t !== "inbox") setOnly(null);
          go(t);
        }}
      />
      <AnimatePresence>
        {open && <IdeaCard key={open.id} idea={open} onClose={() => setOpen(null)} onHeart={() => heart(open)} />}
      </AnimatePresence>
    </main>
  );
}
