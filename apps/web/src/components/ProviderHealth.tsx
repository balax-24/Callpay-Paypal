"use client";

import { useState } from "react";
import { post, usePoll } from "@/lib/api";
import { Badge, Button, Card, ErrorNote } from "./ui";

type P = { provider: string; configured: boolean; state: string; last_error: string | null; primary: boolean; last_used: boolean };
type Providers = Record<string, P[] | string>;

const LAYERS: [string, string][] = [
  ["llm", "AI brain"], ["payments", "PayPal collection"], ["stt", "Speech to text"], ["tts", "Text to speech"], ["sms", "SMS link"],
];
const LAST_RESORT: Record<string, string> = {
  llm: "rules engine", payments: "queue + retry", stt: "browser speech", tts: "browser voice", sms: "link on screen",
};

export default function ProviderHealth() {
  const { data, error, reload } = usePoll<Providers>("/providers", 3000);
  const [busy, setBusy] = useState<string | null>(null);

  async function toggle(layer: string, p: P) {
    setBusy(`${layer}/${p.provider}`);
    try {
      await post(`/providers/${layer}/${p.provider}/${p.state === "closed" ? "kill" : "revive"}`);
    } finally {
      setBusy(null);
      reload();
    }
  }

  const infra = data
    ? (["database", "event_bus", "workflows", "analytics", "object_storage"] as const).map((k) => [k, String(data[k] ?? "–")])
    : [];

  return (
    <Card title="Provider health" right={<span className="text-xs text-muted">Kill a provider: the next one takes over</span>}>
      <ErrorNote error={error} />
      <div className="space-y-3">
        {LAYERS.map(([layer, label]) => {
          const list = (data?.[layer] as P[] | undefined) ?? [];
          const live = list.find((p) => p.configured && p.state === "closed");
          return (
            <div key={layer}>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="font-medium">{label}</span>
                <span className="text-muted">
                  live: <span className="text-fg font-medium">{live?.provider ?? LAST_RESORT[layer]}</span>
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {list.map((p) => {
                  const tone = !p.configured ? "gray" : p.state === "closed" ? "green" : p.state === "half_open" ? "amber" : "red";
                  return (
                    <div key={p.provider} title={p.last_error ?? (p.configured ? "" : "no API key: skipped")}
                      className="flex items-center gap-1.5 rounded-lg border border-line px-2 py-1">
                      <Badge tone={tone}>{p.provider}</Badge>
                      {p.configured ? (
                        <Button small tone={p.state === "closed" ? "danger" : "default"} disabled={busy === `${layer}/${p.provider}`}
                          onClick={() => toggle(layer, p)}>
                          {p.state === "closed" ? "kill" : "revive"}
                        </Button>
                      ) : (
                        <span className="text-[10px] text-muted">no key</span>
                      )}
                    </div>
                  );
                })}
                <div className="flex items-center rounded-lg border border-dashed border-line px-2 py-1 text-xs text-muted">
                  ↳ {LAST_RESORT[layer]}
                </div>
              </div>
            </div>
          );
        })}
        <div className="flex flex-wrap gap-2 pt-2 border-t border-line text-xs">
          {infra.map(([k, v]) => (
            <span key={k} className="text-muted">
              {k.replace("_", " ")}: <Badge tone={["memory", "local", "sqlite", "database"].includes(v) ? "amber" : "green"}>{v}</Badge>
            </span>
          ))}
        </div>
      </div>
    </Card>
  );
}
