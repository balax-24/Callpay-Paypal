"use client";

import { useState } from "react";
import { Badge, Button, Card, ErrorNote } from "@/components/ui";
import { ago, money, post, useEvents, usePoll } from "@/lib/api";

type Flag = { id: string; caller: string; reason: string; source: string; in_effect: boolean; created_at: string; expires_at: string };
type Flags = {
  flags: Flag[];
  rules: {
    flag_after_calls: number; window_minutes: number; flag_minutes: number; checkout_cap: string;
    max_calls_per_window: number; max_checkouts_per_hour: number; max_turns_per_call: number;
  };
};
type Alert = { id: string; kind: string; message: string; channel: string; created_at: string };
type Alerts = { alerts: Alert[]; delivery: string; owner_phone_set: boolean; sms_provider_ready: boolean; large_order_total: string; cooldown_seconds: number };

const KIND: Record<string, string> = {
  payout_approval: "Payout approval", payout_failed: "Payout failed", refund_approval: "Refund approval",
  dispute: "Dispute", fraud: "Fraud flag", large_order: "Large order",
};

export default function SafetyPage() {
  const flags = usePoll<Flags>("/fraud/flags", 5000);
  const alerts = usePoll<Alerts>("/alerts", 5000);
  const [caller, setCaller] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  useEvents((e) => (e.topic.startsWith("fraud.") || e.topic === "owner.alert") && (flags.reload(), alerts.reload()));

  async function run(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      setMsg(ok);
    } catch (e) {
      setMsg(`Failed: ${(e as Error).message}`);
    }
    flags.reload();
    alerts.reload();
  }

  const r = flags.data?.rules;
  const a = alerts.data;
  const active = (flags.data?.flags ?? []).filter((f) => f.in_effect);
  const past = (flags.data?.flags ?? []).filter((f) => !f.in_effect).slice(0, 8);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Safety &amp; alerts</h1>
        <p className="text-sm text-muted">Callers who behave unusually get stricter rules, never looser ones. You hear about anything that needs you.</p>
      </div>
      <ErrorNote error={flags.error ?? alerts.error} />
      {msg && <div className="rounded-md border border-line bg-panel px-3 py-2 text-sm">{msg}</div>}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Card title={`Flagged callers (${active.length})`}>
            {!active.length && <div className="text-sm text-muted">No caller is flagged right now.</div>}
            <div className="space-y-2">
              {active.map((f) => (
                <div key={f.id} className="flex items-start justify-between gap-3 rounded-lg border border-bad/30 p-3">
                  <div className="text-sm">
                    <div className="font-medium">{f.caller} <Badge tone="red">{f.source === "owner" ? "flagged by you" : "automatic"}</Badge></div>
                    <div className="text-xs text-muted">{f.reason} · {ago(f.created_at)} · lifts {new Date(f.expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div>
                  </div>
                  <Button small onClick={() => run(() => post(`/fraud/flags/${f.id}/clear`), `Cleared ${f.caller}.`)}>Clear</Button>
                </div>
              ))}
            </div>
            <form className="mt-3 flex gap-2 border-t border-line pt-3" onSubmit={(e) => { e.preventDefault(); run(() => post("/fraud/flags", { caller }), `Flagged ${caller}.`); setCaller(""); }}>
              <input className="flex-1 rounded-md border border-line bg-transparent px-3 py-2 text-sm" placeholder="Phone number to flag, e.g. +15550001111" value={caller} onChange={(e) => setCaller(e.target.value)} />
              <Button tone="danger" disabled={caller.trim().length < 3}>Flag caller</Button>
            </form>
            {past.length > 0 && (
              <div className="mt-3 text-xs text-muted">Earlier: {past.map((f) => f.caller).join(", ")}</div>
            )}
          </Card>
          <Card title="Rules in force">
            {r && (
              <ul className="space-y-1.5 text-sm">
                <li><b>{r.flag_after_calls} calls</b> from one number in {r.window_minutes} minutes flags it for {r.flag_minutes} minutes.</li>
                <li>A flagged caller can check out up to <b>{money(r.checkout_cap)}</b>; the agent says so on the call.</li>
                <li>Every refund for a flagged caller <b>waits for your approval</b>, however small.</li>
                <li>Hard limits per number: <b>{r.max_calls_per_window} calls</b> per {r.window_minutes} minutes, <b>{r.max_checkouts_per_hour} checkouts</b> per hour, <b>{r.max_turns_per_call} turns</b> per call.</li>
              </ul>
            )}
            <p className="mt-2 text-xs text-muted">Limits apply to callers with a known phone number. The Flink job watches the same pattern on the event stream.</p>
          </Card>
        </div>
        <Card title="Alerts sent to you" right={a && <Badge tone={a.delivery === "sms" ? "green" : "amber"}>{a.delivery === "sms" ? "by text message" : "on this screen"}</Badge>}>
          {a && a.delivery !== "sms" && (
            <div className="mb-3 rounded-md bg-fg/5 px-3 py-2 text-xs text-muted">
              {a.owner_phone_set ? "No SMS provider is set up yet, so alerts show here." : "Set OWNER_PHONE (and Twilio or Telnyx keys) to get these as text messages."}
            </div>
          )}
          {!a?.alerts.length && <div className="text-sm text-muted">Nothing has needed you yet.</div>}
          <ul className="space-y-2">
            {a?.alerts.map((x) => (
              <li key={x.id} className="rounded-lg border border-line p-3 text-sm">
                <div className="flex items-center gap-2">
                  <Badge tone={x.kind === "fraud" || x.kind === "dispute" || x.kind === "payout_failed" ? "red" : "amber"}>{KIND[x.kind] ?? x.kind}</Badge>
                  <span className="ml-auto text-xs text-muted">{ago(x.created_at)} · {x.channel === "sms" ? "texted" : "shown here"}</span>
                </div>
                <div className="mt-1">{x.message}</div>
              </li>
            ))}
          </ul>
          {a && (
            <p className="mt-3 text-xs text-muted">
              You&apos;re alerted for approvals, failed payouts, disputes, fraud flags and orders of {money(a.large_order_total)} or more; at most one per type every {Math.round(a.cooldown_seconds / 60)} minutes.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}
