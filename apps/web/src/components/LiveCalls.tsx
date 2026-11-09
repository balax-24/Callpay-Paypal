"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge, Card, statusTone } from "@/components/ui";
import { ago, useEvents, type BusEvent } from "@/lib/api";

type TranscriptLine = {
  role: "agent" | "caller";
  text: string;
  agent?: string;
  llm?: string | null;
  ts?: number;
};

type LiveCall = {
  id: string;
  caller: string | null;
  channel: string;
  status: string;
  stage: string;
  lines: TranscriptLine[];
  paid: boolean;
  updatedAt: number;
  endedAt: number | null;
};

const ACTIVE_TTL_MS = 30_000;
const CLOSED_TTL_MS = 30_000;

function applyEvent(calls: Map<string, LiveCall>, event: BusEvent): Map<string, LiveCall> {
  const callId = typeof event.call_id === "string" ? event.call_id : null;
  if (!callId) return calls;

  const next = new Map(calls);
  const current = next.get(callId);
  const now = typeof event.ts === "number" ? event.ts : Date.now();

  if (event.topic === "call.started") {
    next.set(callId, {
      id: callId,
      caller: typeof event.caller === "string" ? event.caller : null,
      channel: typeof event.channel === "string" ? event.channel : "browser",
      status: "active",
      stage: "ordering",
      lines: current?.lines ?? [],
      paid: current?.paid ?? false,
      updatedAt: now,
      endedAt: null,
    });
  } else if (event.topic === "call.transcript") {
    if (event.role !== "agent" && event.role !== "caller") return calls;
    const line: TranscriptLine = {
      role: event.role,
      text: typeof event.text === "string" ? event.text : "",
      agent: typeof event.agent === "string" ? event.agent : undefined,
      llm: typeof event.llm === "string" ? event.llm : null,
      ts: now,
    };
    const base = current ?? {
      id: callId,
      caller: typeof event.caller === "string" ? event.caller : null,
      channel: "browser",
      status: "active",
      stage: "ordering",
      lines: [],
      paid: false,
      updatedAt: now,
      endedAt: null,
    };
    next.set(callId, { ...base, lines: [...base.lines, line].slice(-40), updatedAt: now });
  } else if (event.topic === "call.pay_link_sent") {
    if (current) next.set(callId, { ...current, stage: "awaiting_payment", updatedAt: now });
  } else if (event.topic === "payment.completed") {
    if (current) next.set(callId, { ...current, paid: true, stage: "paid", updatedAt: now });
  } else if (event.topic === "call.ended") {
    const base = current ?? {
      id: callId,
      caller: null,
      channel: "browser",
      status: "ended",
      stage: "ended",
      lines: [],
      paid: false,
      updatedAt: now,
      endedAt: now,
    };
    next.set(callId, {
      ...base,
      status: typeof event.status === "string" ? event.status : "ended",
      stage: base.paid ? "paid" : "ended",
      endedAt: now,
      updatedAt: now,
    });
  }
  return next;
}

export default function LiveCalls() {
  const { events, connected } = useEvents(undefined, 200);
  const [calls, setCalls] = useState<Map<string, LiveCall>>(new Map());

  useEffect(() => {
    setCalls((current) => {
      let next = current;
      for (const event of [...events].reverse()) next = applyEvent(next, event);
      return next;
    });
  }, [events]);

  useEffect(() => {
    let alive = true;
    fetch(`${process.env.NEXT_PUBLIC_API_URL || "/api"}/calls`, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : []))
      .then((rows: Array<{ id: string; caller: string | null; channel: string; status: string; stage: string | null; transcript: Array<{ role: string; text: string; agent?: string; llm?: string | null; ts?: string }>; started_at: string; ended_at: string | null }>) => {
        if (!alive) return;
        setCalls((current) => {
          const next = new Map(current);
          for (const row of rows) {
            const startedAt = new Date(row.started_at).getTime();
            const endedAt = row.ended_at ? new Date(row.ended_at).getTime() : null;
            const existing = next.get(row.id);
            const isRecent = endedAt ? Date.now() - endedAt < CLOSED_TTL_MS : Date.now() - startedAt < ACTIVE_TTL_MS;
            if (!isRecent && !existing) continue;
            const restoredBase: LiveCall = {
              id: row.id,
              caller: row.caller,
              channel: row.channel,
              status: row.status,
              stage: row.stage ?? row.status,
              lines: (row.transcript ?? []).map((line) => ({
                role: line.role === "caller" ? "caller" : "agent",
                text: line.text,
                agent: line.agent,
                llm: line.llm ?? null,
                ts: line.ts ? new Date(line.ts).getTime() : startedAt,
              })),
              paid: row.stage === "done",
              updatedAt: endedAt ?? startedAt,
              endedAt,
            };
            const restored = existing && existing.updatedAt > restoredBase.updatedAt ? existing : restoredBase;
            next.set(row.id, {
              ...restored,
              caller: row.caller,
              channel: row.channel,
              status: row.status,
              stage: restored.paid ? "paid" : row.stage ?? restored.stage,
              endedAt,
              updatedAt: Math.max(restored.updatedAt, endedAt ?? startedAt),
            });
          }
          return next;
        });
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const now = Date.now();
      setCalls((current) => {
        const next = new Map([...current].filter(([, call]) =>
          call.endedAt ? now - call.endedAt < CLOSED_TTL_MS : now - call.updatedAt < ACTIVE_TTL_MS,
        ));
        return next.size === current.size ? current : next;
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const visibleCalls = useMemo(() => [...calls.values()].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 6), [calls]);

  return (
    <Card title="Live calls" right={<Badge tone={connected ? "green" : "amber"}>{connected ? "streaming" : "reconnecting"}</Badge>}>
      {!visibleCalls.length ? (
        <div className="text-sm text-muted">Waiting for a call. Start one from <a className="text-brand underline" href="/call">Try a call</a> to see the conversation here.</div>
      ) : (
        <div className="grid md:grid-cols-2 gap-3">
          {visibleCalls.map((call) => {
            const lastAgent = [...call.lines].reverse().find((line) => line.role === "agent");
            return (
              <section key={call.id} className="rounded-lg border border-line p-3 min-w-0">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">{call.caller ?? "Browser caller"}</div>
                    <div className="text-[11px] text-muted">{call.channel} · {ago(new Date(call.updatedAt).toISOString())}</div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {call.paid && <Badge tone="green">PAID</Badge>}
                    <Badge tone={statusTone(call.stage)}>{call.stage.replaceAll("_", " ")}</Badge>
                  </div>
                </div>
                <div className="space-y-1.5 max-h-48 overflow-auto">
                  {call.lines.slice(-8).map((line, index) => (
                    <div key={`${line.ts}-${index}`} className={`flex ${line.role === "caller" ? "justify-end" : ""}`}>
                      <div className={`max-w-[90%] rounded-xl px-2.5 py-1.5 text-xs ${line.role === "caller" ? "bg-brand text-white" : "bg-fg/5"}`}>
                        <div className="whitespace-pre-wrap break-words">{line.text}</div>
                        {line.role === "agent" && <div className="text-[10px] mt-1 opacity-60">{line.agent ?? "agent"} · {line.llm ?? "rules"}</div>}
                      </div>
                    </div>
                  ))}
                  {!call.lines.length && <div className="text-xs text-muted">Call connected; waiting for the first turn.</div>}
                </div>
                {lastAgent?.llm && <div className="text-[10px] text-muted mt-2">Latest brain: {lastAgent.llm}</div>}
              </section>
            );
          })}
        </div>
      )}
    </Card>
  );
}
