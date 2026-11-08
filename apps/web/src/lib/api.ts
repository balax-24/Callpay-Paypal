"use client";

import { useEffect, useRef, useState } from "react";

export const API = process.env.NEXT_PUBLIC_API_URL || "/api";

export async function api<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!r.ok) {
    let detail: unknown = r.statusText;
    try {
      detail = (await r.json()).detail;
    } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.json() as Promise<T>;
}

export const post = <T = unknown>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export type BusEvent = { topic: string; ts?: number; [k: string]: unknown };

/** Live event stream from the API (/events, Server-Sent Events). Reconnects automatically. */
export function useEvents(onEvent?: (e: BusEvent) => void, keep = 60) {
  const [events, setEvents] = useState<BusEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;
  useEffect(() => {
    const es = new EventSource(`${API}/events`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (m) => {
      try {
        const e = JSON.parse(m.data) as BusEvent;
        setEvents((prev) => [e, ...prev].slice(0, keep));
        cb.current?.(e);
      } catch {}
    };
    return () => es.close();
  }, [keep]);
  return { events, connected };
}

/** Fetch on mount, on an interval, and whenever `deps` change. */
export function usePoll<T>(path: string | null, ms = 5000, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    const load = () =>
      api<T>(path)
        .then((d) => alive && (setData(d), setError(null)))
        .catch((e) => alive && setError(String(e.message || e)));
    load();
    const t = setInterval(load, ms);
    return () => {
      alive = false;
      clearInterval(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ms, tick, ...deps]);
  return { data, error, reload: () => setTick((x) => x + 1) };
}

export const money = (v: string | number | null | undefined) =>
  v === null || v === undefined || v === "" ? "–" : `$${Number(v).toFixed(2)}`;

export const ago = (iso?: string | null) => {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
};
