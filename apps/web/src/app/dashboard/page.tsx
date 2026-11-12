"use client";

import Link from "next/link";
import ProviderHealth from "@/components/ProviderHealth";
import LiveCalls from "@/components/LiveCalls";
import { Badge, Card, ErrorNote, Stat, statusTone } from "@/components/ui";
import { ago, money, useEvents, usePoll, type BusEvent } from "@/lib/api";

type Summary = {
  revenue: string; orders: number; avg_order: string; calls: number; abandoned: number; recovery_texts: number;
  conversion_pct: number; paid_out: string; batches: number; source: string;
};
type Point = { t: string; revenue: string; orders: number };
type Order = { id: string; status: string; total: string; tip?: string; items: { name: string; quantity: number; note?: string }[]; paid_at: string | null };

const LABEL: Record<string, string> = {
  "call.started": "Call started", "call.ended": "Call ended", "call.abandoned": "Caller hung up before paying",
  "call.transcript": "Transcript", "call.pay_link_sent": "PayPal link sent", "payment.link_sent": "PayPal checkout created",
  "payment.completed": "Payment received", "order.preparing": "Sent to kitchen", "order.ready": "Order ready",
  "payout.requested": "Crew payout proposed", "payout.sent": "PayPal Payout sent", "payout.failed": "Payout failed, queued",
  "provider.failover": "Failover", "provider.health": "Provider switched", "recovery.sent": "Recovery text sent",
  "support.requested": "Support case opened", "payment.refunded": "Refund sent", "order.created": "Order created",
};

function describe(e: BusEvent) {
  if (e.topic === "call.transcript") return `${e.role === "agent" ? "🤖" : "🗣️"} ${String(e.text).slice(0, 90)}`;
  if (e.topic === "provider.failover") return `${e.layer}: ${e.from_provider} → ${e.to_provider ?? "fallback"}`;
  if (e.topic === "provider.health") return `${e.layer}/${e.provider} is ${e.state}`;
  if (e.total) return money(String(e.total));
  return "";
}

function RevenueChart({ points }: { points: Point[] }) {
  const max = Math.max(1, ...points.map((p) => Number(p.revenue)));
  if (!points.length) return <div className="h-36 grid place-items-center text-sm text-muted">No payments in the last hour yet.</div>;
  return (
    <div className="h-36 flex items-end gap-1">
      {points.map((p) => (
        <div key={p.t} className="flex-1 min-w-[6px] group relative">
          <div className="bg-brand/80 rounded-t" style={{ height: `${(Number(p.revenue) / max) * 128 + 2}px` }} />
          <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 hidden group-hover:block text-[10px] bg-fg text-bg rounded px-1.5 py-0.5 whitespace-nowrap">
            {new Date(p.t.endsWith("Z") || p.t.includes("+") ? p.t : p.t + "Z").toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {money(p.revenue)} · {p.orders} orders
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Overview() {
  const sum = usePoll<Summary>("/analytics/summary?window=today", 5000);
  const series = usePoll<Point[]>("/analytics/timeseries?minutes=60", 10000);
  const kitchen = usePoll<Order[]>("/kitchen", 4000);
  const { events, connected } = useEvents((e) => {
    if (["payment.completed", "order.preparing", "order.ready", "payout.sent"].includes(e.topic)) {
      sum.reload();
      kitchen.reload();
      series.reload();
    }
  });
  const s = sum.data;

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-semibold">Rosa&apos;s Taco Truck</h1>
          <p className="text-sm text-muted">Every call answered, paid on the line, crew paid automatically.</p>
        </div>
        <Link href="/call" className="rounded-md bg-brand text-white text-sm font-medium px-4 py-2">Try a call →</Link>
      </div>
      <ErrorNote error={sum.error} />
      <LiveCalls />
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label="Revenue today" value={money(s?.revenue)} hint={`${s?.orders ?? 0} paid orders`} />
        <Stat label="Calls today" value={s?.calls ?? "–"} hint={`${s?.conversion_pct ?? 0}% converted`} />
        <Stat label="Average order" value={money(s?.avg_order)} />
        <Stat label="Abandoned → recovered" value={s ? `${s.abandoned} → ${s.recovery_texts}` : "–"} hint="recovery texts with pay link" />
        <Stat label="Paid to crew" value={money(s?.paid_out)} hint={`${s?.batches ?? 0} PayPal Payouts · ${s?.source ?? ""}`} />
      </div>
      <div className="grid lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 space-y-4">
          <Card title="Revenue per minute (last hour)" right={<span className="text-xs text-muted">Kafka → Flink → ClickHouse</span>}>
            <RevenueChart points={series.data ?? []} />
          </Card>
          <ProviderHealth />
        </div>
        <div className="space-y-4">
          <Card title="Kitchen" right={<span className="text-xs text-muted">paid orders</span>}>
            <div className="space-y-2 max-h-64 overflow-auto">
              {(kitchen.data ?? []).slice(0, 8).map((o) => (
                <div key={o.id} className="flex items-start justify-between gap-2 text-sm border-b border-line pb-2 last:border-0">
                  <div>
                    <div className="font-mono text-xs text-muted">#{o.id.slice(0, 6)} · {ago(o.paid_at)}</div>
                    <div>{o.items.filter((i) => i.name !== "Crew tip").map((i) => <span key={i.name}>{i.quantity}× {i.name}{i.note && <strong className="ml-1">({i.note})</strong>} </span>)}</div>
                    {Number(o.tip ?? 0) > 0 && <div className="text-xs text-muted">Crew tip: {money(o.tip)}</div>}
                  </div>
                  <Badge tone={statusTone(o.status)}>{o.status}</Badge>
                </div>
              ))}
              {kitchen.data?.length === 0 && <div className="text-sm text-muted">No paid orders yet.</div>}
            </div>
          </Card>
          <Card title="Live events" right={<Badge tone={connected ? "green" : "red"}>{connected ? "live" : "offline"}</Badge>}>
            <ul className="space-y-1.5 max-h-96 overflow-auto text-sm">
              {events.map((e, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-xs text-muted tabular-nums w-14 shrink-0">
                    {e.ts ? new Date(e.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}
                  </span>
                  <span>
                    <span className={e.topic === "provider.failover" ? "text-warn font-medium" : "font-medium"}>{LABEL[e.topic] ?? e.topic}</span>{" "}
                    <span className="text-muted">{describe(e)}</span>
                  </span>
                </li>
              ))}
              {!events.length && <li className="text-muted">Waiting for activity. Start a call to see it stream in.</li>}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
