import { useCallback, useEffect, useRef, useState } from "react";
import type { State } from "@contract/state";
import { looksLikeState, normalizeState } from "@/lib/state";

export type ConnectionMode = "connecting" | "live" | "polling" | "offline";

export interface LiveState {
  state: State | null;
  mode: ConnectionMode;
  /** The data on screen comes from the sample fixture, not the backend. */
  sample: boolean;
  /** `?sample` was requested explicitly: no backend calls at all. */
  forcedSample: boolean;
  fetchedAt: Date | null;
  error: string | null;
  refresh: () => void;
}

// Relative URLs so the app also works when served below a path prefix.
const API_STATE = "api/state";
const API_EVENTS = "api/events";
const POLL_MS = 3000;
const SSE_RETRY_MS = 30000;

/** `?sample` → ./sample-state.json; `?sample=other.json` → ./other.json (file names only). */
export function sampleRequest(search: string): string | null {
  const params = new URLSearchParams(search);
  if (!params.has("sample")) return null;
  const name = params.get("sample") ?? "";
  const file = /^[\w.-]+\.json$/.test(name) ? name : "sample-state.json";
  return `${import.meta.env.BASE_URL}${file}`;
}

export function useLiveState(): LiveState {
  const [state, setState] = useState<State | null>(null);
  const [mode, setMode] = useState<ConnectionMode>("connecting");
  const [sample, setSample] = useState(false);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refreshRef = useRef<() => void>(() => undefined);

  const forcedUrl = sampleRequest(window.location.search);
  const forcedSample = forcedUrl !== null;

  useEffect(() => {
    let disposed = false;
    let es: EventSource | null = null;
    let pollTimer: number | undefined;
    let sseTimer: number | undefined;
    let lastText = "";
    let lastMode: ConnectionMode = "connecting";

    const setModeTracked = (m: ConnectionMode) => {
      lastMode = m;
      setMode(m);
    };

    const apply = (text: string, fromSample: boolean) => {
      setFetchedAt(new Date());
      if (text === lastText) return;
      const raw: unknown = JSON.parse(text);
      if (!looksLikeState(raw)) throw new Error("response is not a qcc state document");
      lastText = text;
      setState(normalizeState(raw));
      setSample(fromSample);
    };

    const fetchState = async (): Promise<boolean> => {
      try {
        const r = await fetch(API_STATE, { cache: "no-store", headers: { Accept: "application/json" } });
        if (!r.ok) throw new Error(`GET /${API_STATE}: HTTP ${r.status}`);
        const text = await r.text();
        if (disposed) return true;
        apply(text, false);
        setError(null);
        return true;
      } catch (e) {
        if (!disposed) setError(e instanceof Error ? e.message : String(e));
        return false;
      }
    };

    const loadSample = async (url: string) => {
      try {
        const r = await fetch(url, { cache: "no-store" });
        if (!r.ok) throw new Error(`GET ${url}: HTTP ${r.status}`);
        const text = await r.text();
        if (!disposed) apply(text, true);
      } catch (e) {
        if (!disposed) setError(e instanceof Error ? e.message : String(e));
      }
    };

    const stopPolling = () => {
      window.clearInterval(pollTimer);
      pollTimer = undefined;
    };

    const scheduleSse = (delay: number) => {
      if (es || sseTimer !== undefined) return;
      sseTimer = window.setTimeout(() => {
        sseTimer = undefined;
        openSse();
      }, delay);
    };

    const startPolling = () => {
      if (pollTimer !== undefined) return;
      pollTimer = window.setInterval(async () => {
        const wasOffline = lastMode === "offline";
        const ok = await fetchState();
        if (disposed || pollTimer === undefined) return;
        setModeTracked(ok ? "polling" : "offline");
        // Back from offline: try the event stream right away, otherwise only now and then.
        if (ok) scheduleSse(wasOffline ? 0 : SSE_RETRY_MS);
      }, POLL_MS);
    };

    const openSse = () => {
      if (disposed || es) return;
      if (typeof EventSource === "undefined") {
        startPolling();
        return;
      }
      const source = new EventSource(API_EVENTS);
      es = source;
      source.addEventListener("open", () => {
        setModeTracked("live");
        stopPolling();
        void fetchState(); // catch changes that happened while (re)connecting
      });
      source.addEventListener("state", () => void fetchState());
      source.onerror = () => {
        source.close();
        if (es === source) es = null;
        if (disposed) return;
        if (lastMode === "live" || lastMode === "connecting") setModeTracked("polling");
        startPolling();
      };
    };

    refreshRef.current = () => void fetchState();

    void (async () => {
      if (forcedUrl) {
        await loadSample(forcedUrl);
        setModeTracked("offline");
        return;
      }
      const ok = await fetchState();
      if (disposed) return;
      if (ok) {
        setModeTracked("polling");
        openSse();
      } else {
        await loadSample(`${import.meta.env.BASE_URL}sample-state.json`);
        setModeTracked("offline");
        startPolling();
      }
    })();

    return () => {
      disposed = true;
      es?.close();
      stopPolling();
      window.clearTimeout(sseTimer);
      refreshRef.current = () => undefined;
    };
  }, [forcedUrl]);

  const refresh = useCallback(() => refreshRef.current(), []);

  return { state, mode, sample, forcedSample, fetchedAt, error, refresh };
}
