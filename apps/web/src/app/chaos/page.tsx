"use client";

import { useEffect, useState } from "react";
import { Badge, Card } from "@/components/ui";

type Result = { calls_started: number; turns_succeeded: number; errors: number; failovers_triggered: number; success_rate_pct: number; elapsed_seconds: number };

export default function ChaosPage() {
  const [raw, setRaw] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const saved = window.localStorage.getItem("callpay-chaos-result");
    if (!saved) return;
    setRaw(saved);
    try { setResult(JSON.parse(saved) as Result); } catch { setError("Saved run data is invalid JSON."); }
  }, []);

  function load() {
    setError(null);
    try {
      const parsed = JSON.parse(raw) as Result;
      const fields: Array<keyof Result> = ["calls_started", "turns_succeeded", "errors", "failovers_triggered", "success_rate_pct", "elapsed_seconds"];
      if (!fields.every((key) => typeof parsed[key] === "number" && Number.isFinite(parsed[key]) && parsed[key] >= 0)) {
        throw new Error("Run data must contain non-negative numeric values for every required field.");
      }
      if (parsed.success_rate_pct > 100) {
        throw new Error("Success rate cannot be greater than 100%.");
      }
      setResult(parsed);
      window.localStorage.setItem("callpay-chaos-result", JSON.stringify(parsed));
    } catch (e) { setError((e as Error).message); }
  }

  const bars = result ? [
    { label: "Turns succeeded", value: result.turns_succeeded, color: "bg-ok" },
    { label: "Errors", value: result.errors, color: "bg-bad" },
    { label: "Provider toggles", value: result.failovers_triggered, color: "bg-warn" },
  ] : [];
  const max = Math.max(1, ...bars.map((bar) => bar.value));

  return (
    <div className="max-w-4xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Chaos run results</h1>
        <p className="text-sm text-muted">Paste measured intake and failover results here to chart a reliability run. Include calls_started, turns_succeeded, errors, failovers_triggered, success_rate_pct, and elapsed_seconds. This page does not simulate PayPal payments or mark orders as paid.</p>
      </div>
      <Card title="Load a measured run">
        <textarea className="min-h-28 w-full rounded-md border border-line bg-transparent p-3 font-mono text-xs" value={raw} onChange={(e) => setRaw(e.target.value)} placeholder="Paste measured run JSON here" />
        <div className="mt-2 flex items-center gap-3">
          <button className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white" onClick={load}>Show run</button>
          {error && <span className="text-xs text-bad">{error}</span>}
        </div>
      </Card>
      {result && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card><div className="text-xs text-muted">Calls started</div><div className="mt-1 text-2xl font-semibold">{result.calls_started}</div></Card>
            <Card><div className="text-xs text-muted">Successful turns</div><div className="mt-1 text-2xl font-semibold">{result.turns_succeeded}</div></Card>
            <Card><div className="text-xs text-muted">Errors</div><div className="mt-1 text-2xl font-semibold">{result.errors}</div></Card>
            <Card><div className="text-xs text-muted">Success rate</div><div className="mt-1 text-2xl font-semibold">{result.success_rate_pct}%</div></Card>
          </div>
          <Card title="Observed run" right={<Badge tone={result.errors ? "amber" : "green"}>{result.errors ? "errors observed" : "no errors observed"}</Badge>}>
            <div className="space-y-3">
              {bars.map((bar) => (
                <div key={bar.label}>
                  <div className="mb-1 flex justify-between text-xs"><span>{bar.label}</span><span>{bar.value}</span></div>
                  <div className="h-3 rounded-full bg-fg/5"><div className={`h-3 rounded-full ${bar.color}`} style={{ width: `${(bar.value / max) * 100}%` }} /></div>
                </div>
              ))}
              <div className="text-xs text-muted">Duration: {result.elapsed_seconds}s · This run covers order-intake turns only; it does not measure payment or fulfillment delivery.</div>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
