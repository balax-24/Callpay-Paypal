"use client";

import { useState } from "react";
import Grid from "@/components/Grid";
import { Badge, Button, Card, ErrorNote, statusTone } from "@/components/ui";
import { ago, money, post, useEvents, usePoll } from "@/lib/api";

type Order = {
  id: string; status: string; total: string; items: { name: string; quantity: number; unit_amount: string }[];
  payment_method: string | null; paypal_ref: string | null; pay_link: string | null; capture_id: string | null;
  created_at: string; paid_at: string | null; call_id: string | null; customer_phone: string | null;
  dispute: { id: string; reason: string; status: string; draft_evidence: string; evidence_submitted?: boolean } | null;
};

export default function Orders() {
  const { data, error, reload } = usePoll<Order[]>("/orders", 5000);
  const [sel, setSel] = useState<Order | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEvents((e) => (e.topic.startsWith("order.") || e.topic.startsWith("payment.") || e.topic.startsWith("dispute.")) && reload());
  const o = sel ? data?.find((x) => x.id === sel.id) ?? sel : null;

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
    } catch (e) {
      setMsg(`Failed: ${(e as Error).message}`);
    }
    reload();
  }

  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <Card title="Orders" className="lg:col-span-2">
        <ErrorNote error={error} />
        <Grid<Order>
          rows={data}
          height={560}
          getRowId={(r) => r.id}
          onRowClicked={setSel}
          cols={[
            { headerName: "Created", field: "created_at", valueFormatter: (p) => ago(p.value), maxWidth: 110 },
            { headerName: "Order", field: "id", valueFormatter: (p) => `#${String(p.value).slice(0, 6)}`, maxWidth: 100 },
            { headerName: "Items", valueGetter: (p) => p.data?.items.map((i) => `${i.quantity}× ${i.name}`).join(", "), flex: 2 },
            { headerName: "Total", field: "total", valueFormatter: (p) => money(p.value), maxWidth: 100 },
            { headerName: "Status", field: "status", cellRenderer: (p: { value: string }) => <Badge tone={statusTone(p.value)}>{p.value}</Badge> },
            { headerName: "PayPal via", field: "payment_method", maxWidth: 110 },
            { headerName: "Dispute", valueGetter: (p) => p.data?.dispute?.status ?? "", maxWidth: 110 },
          ]}
        />
      </Card>
      <Card title={o ? `Order #${o.id.slice(0, 6)}` : "Order details"}>
        {!o && <div className="text-sm text-muted">Select an order.</div>}
        {o && (
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-2"><Badge tone={statusTone(o.status)}>{o.status}</Badge><span className="font-semibold">{money(o.total)}</span></div>
            <ul className="space-y-1">
              {o.items.map((i) => <li key={i.name} className="flex justify-between"><span>{i.quantity}× {i.name}</span><span>{money(Number(i.unit_amount) * i.quantity)}</span></li>)}
            </ul>
            <dl className="grid grid-cols-3 gap-1 text-xs">
              <dt className="text-muted">PayPal ref</dt><dd className="col-span-2 font-mono break-all">{o.paypal_ref ?? "–"}</dd>
              <dt className="text-muted">Capture</dt><dd className="col-span-2 font-mono break-all">{o.capture_id ?? "–"}</dd>
              <dt className="text-muted">Caller</dt><dd className="col-span-2">{o.customer_phone ?? "browser"}</dd>
              <dt className="text-muted">Paid</dt><dd className="col-span-2">{o.paid_at ? new Date(o.paid_at).toLocaleString() : "–"}</dd>
            </dl>
            {o.pay_link && o.status === "link_sent" && <a className="text-brand underline text-xs" href={o.pay_link} target="_blank" rel="noreferrer">Open PayPal checkout</a>}
            {o.capture_id && (
              <div className="flex gap-2">
                <Button onClick={() => act(() => post(`/orders/${o.id}/refund`, { amount: "1.00", reason: "Goodwill credit" }), "Refund of $1.00 requested")}>Refund $1</Button>
                <Button tone="danger" onClick={() => act(() => post(`/orders/${o.id}/refund`, { reason: "Full refund" }), "Full refund requested (owner approval if above limit)")}>Full refund</Button>
              </div>
            )}
            {o.dispute && (
              <div className="rounded-lg border border-warn/40 bg-warn/5 p-3 space-y-2">
                <div className="font-medium">PayPal dispute {o.dispute.id} · {o.dispute.reason}</div>
                <div className="text-xs whitespace-pre-wrap text-muted">{o.dispute.draft_evidence}</div>
                {o.dispute.evidence_submitted ? <Badge tone="green">evidence submitted</Badge> : (
                  <Button tone="primary" onClick={() => act(() => post(`/orders/${o.id}/dispute/submit`), "Evidence sent to PayPal")}>Approve &amp; submit evidence</Button>
                )}
              </div>
            )}
            {msg && <div className="text-xs text-muted">{msg}</div>}
          </div>
        )}
      </Card>
    </div>
  );
}
