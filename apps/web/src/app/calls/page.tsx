"use client";

import { useState } from "react";
import Grid from "@/components/Grid";
import { Badge, Card, ErrorNote, statusTone } from "@/components/ui";
import { ago, money, useEvents, usePoll } from "@/lib/api";

type Line = { role: string; text: string; agent?: string; llm?: string | null; ts?: string };
type Call = {
  id: string; channel: string; caller: string | null; status: string; stage: string | null; order_id: string | null;
  total: string | null; transcript: Line[]; started_at: string; ended_at: string | null;
};

export default function Calls() {
  const { data, error, reload } = usePoll<Call[]>("/calls", 4000);
  const [sel, setSel] = useState<string | null>(null);
  useEvents((e) => e.topic.startsWith("call.") && reload());
  const call = data?.find((c) => c.id === sel) ?? data?.[0];

  return (
    <div className="grid lg:grid-cols-5 gap-4">
      <Card title="Calls" className="lg:col-span-3">
        <ErrorNote error={error} />
        <Grid<Call>
          rows={data}
          height={560}
          getRowId={(c) => c.id}
          onRowClicked={(c) => setSel(c.id)}
          cols={[
            { headerName: "Started", field: "started_at", valueFormatter: (p) => ago(p.value), sort: "desc", maxWidth: 110 },
            { headerName: "Channel", field: "channel", maxWidth: 100 },
            { headerName: "Caller", field: "caller", valueFormatter: (p) => p.value ?? "browser" },
            { headerName: "Status", field: "status", cellRenderer: (p: { value: string }) => <Badge tone={statusTone(p.value)}>{p.value}</Badge> },
            { headerName: "Stage", field: "stage", cellRenderer: (p: { value: string }) => <Badge tone={statusTone(p.value)}>{p.value}</Badge> },
            { headerName: "Total", field: "total", valueFormatter: (p) => money(p.value), maxWidth: 100 },
            { headerName: "Turns", valueGetter: (p) => p.data?.transcript.length ?? 0, maxWidth: 90 },
          ]}
        />
      </Card>
      <Card title={call ? `Transcript · ${call.id.slice(0, 8)}` : "Transcript"} className="lg:col-span-2"
        right={call && <Badge tone={statusTone(call.status)}>{call.status}</Badge>}>
        {!call && <div className="text-sm text-muted">No calls yet. Use “Try a call”.</div>}
        <div className="space-y-2 max-h-[560px] overflow-auto">
          {call?.transcript.map((l, i) => (
            <div key={i} className={`flex ${l.role === "agent" ? "" : "justify-end"}`}>
              <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${l.role === "agent" ? "bg-fg/5" : "bg-brand text-white"}`}>
                {l.text}
                {l.role === "agent" && l.agent && (
                  <div className="text-[10px] mt-1 opacity-60">{l.agent}{l.llm ? ` · ${l.llm}` : l.agent !== "planner" ? " · rules" : ""}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
