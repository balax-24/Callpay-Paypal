"use client";

import { useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import Grid from "@/components/Grid";
import { Badge, Button, Card, ErrorNote, statusTone } from "@/components/ui";
import { ago, money, post, useEvents, usePoll } from "@/lib/api";

type Order = {
  id: string; status: string; total: string; tip?: string; items: { name: string; quantity: number; unit_amount: string; note?: string }[];
  payment_method: string | null; paypal_ref: string | null; pay_link: string | null; capture_id: string | null;
  created_at: string; paid_at: string | null; call_id: string | null; customer_phone: string | null; reminder_channel?: string;
  dispute: { id: string; reason: string; status: string; draft_evidence: string; evidence_submitted?: boolean } | null;
};

export default function Orders() {
  const { data, error, reload } = usePoll<Order[]>("/orders", 5000);
  const [sel, setSel] = useState<Order | null>(null);
  const [refundQty, setRefundQty] = useState<Record<string, number>>({});
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

  async function remind(order: Order) {
    setMsg("Sending payment link reminder…");
    try {
      const result = await post<Order & { reminder_channel: string }>(`/orders/${order.id}/remind`);
      setMsg(`Payment link reminder delivered via ${result.reminder_channel}.`);
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
            {o.items.filter((i) => i.name !== "Crew tip").map((i) => <li key={i.name} className="flex justify-between gap-2"><span>{i.quantity}× {i.name}{i.note && <strong className="ml-1">({i.note})</strong>}</span><span>{money(Number(i.unit_amount) * i.quantity)}</span></li>)}
            {Number(o.tip ?? 0) > 0 && <li className="flex justify-between border-t border-line pt-1"><span>Crew tip</span><span>{money(o.tip)}</span></li>}
            </ul>
            {o.capture_id && (
              <div className="space-y-2 rounded-lg border border-line p-3">
                <div className="text-xs font-medium">Refund selected items</div>
                {o.items.filter((i) => i.name !== "Crew tip").map((i) => (
                  <label key={i.name} className="flex items-center justify-between gap-2 text-xs">
                    <span>{i.name} · max {i.quantity}</span>
                    <input className="w-16 rounded border border-line bg-transparent px-2 py-1" type="number" min={0} max={i.quantity} value={refundQty[i.name] ?? 0}
                      onChange={(e) => setRefundQty({ ...refundQty, [i.name]: Math.max(0, Math.min(i.quantity, Number(e.target.value))) })} />
                  </label>
                ))}
                <Button disabled={!Object.values(refundQty).some((q) => q > 0)} onClick={() => act(
                  () => post(`/orders/${o.id}/refund`, { items: Object.entries(refundQty).filter(([, quantity]) => quantity > 0).map(([name, quantity]) => ({ name, quantity })), reason: "Selected item refund" }),
                  "Item-based refund requested; policy may require owner approval",
                )}>Refund selected items</Button>
              </div>
            )}
            <dl className="grid grid-cols-3 gap-1 text-xs">
              <dt className="text-muted">PayPal ref</dt><dd className="col-span-2 font-mono break-all">{o.paypal_ref ?? "–"}</dd>
              <dt className="text-muted">Capture</dt><dd className="col-span-2 font-mono break-all">{o.capture_id ?? "–"}</dd>
              <dt className="text-muted">Caller</dt><dd className="col-span-2">{o.customer_phone ?? "browser"}</dd>
              <dt className="text-muted">Paid</dt><dd className="col-span-2">{o.paid_at ? new Date(o.paid_at).toLocaleString() : "–"}</dd>
            </dl>
            {o.pay_link && o.status === "link_sent" && (
              <>
                <div className="flex flex-col items-center gap-2 rounded-lg border border-line bg-white p-3">
                  <QRCodeSVG value={o.pay_link} size={160} level="M" title="Scan to open PayPal checkout" />
                  <span className="text-xs text-gray-600">Scan to pay on your phone</span>
                  <a className="text-brand underline text-xs" href={o.pay_link} target="_blank" rel="noreferrer">Open PayPal checkout</a>
                </div>
                <Button disabled={Boolean(msg?.startsWith("Sending"))} onClick={() => remind(o)}>Resend pay link</Button>
                {o.reminder_channel && <div className="text-xs text-muted">Last reminder: {o.reminder_channel}</div>}
              </>
            )}
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
