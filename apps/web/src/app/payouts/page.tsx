"use client";

import { useState } from "react";
import Grid from "@/components/Grid";
import { Badge, Button, Card, ErrorNote, statusTone } from "@/components/ui";
import { ago, api, money, post, useEvents, usePoll } from "@/lib/api";

type Item = { name: string; email: string; amount: string; paypal_status?: string };
type Payout = {
  id: string; status: string; total: string; items: Item[]; memo: string; policy: { decision: string; reasons: string[] };
  paypal_batch_id: string | null; error: string | null; decided_by: string | null; created_at: string;
};
type Refund = { id: string; order_id: string; amount: string; reason: string; status: string; policy: { reasons: string[] }; error: string | null; created_at: string };
type Staff = { id: string; name: string; paypal_email: string; role: string };
type Biz = { id: string; name: string };

export default function Payouts() {
  const payouts = usePoll<Payout[]>("/payouts", 5000);
  const refunds = usePoll<Refund[]>("/refunds", 5000);
  const staff = usePoll<Staff[]>("/staff", 15000);
  const [msg, setMsg] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", email: "" });
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  useEvents((e) => (e.topic.startsWith("payout.") || e.topic.startsWith("payment.refunded")) && (payouts.reload(), refunds.reload()));

  const pendingP = (payouts.data ?? []).filter((p) => p.status === "pending_approval");
  const pendingR = (refunds.data ?? []).filter((r) => r.status === "pending_approval");

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
    } catch (e) {
      setMsg(`Failed: ${(e as Error).message}`);
    }
    payouts.reload();
    refunds.reload();
    staff.reload();
  }

  async function payCrew() {
    const biz = (await api<Biz[]>("/businesses"))[0];
    const lines = Object.entries(amounts).filter(([, v]) => Number(v) > 0).map(([staff_id, amount]) => ({ staff_id, amount: Number(amount).toFixed(2) }));
    if (!lines.length) return setMsg("Enter at least one amount.");
    await act(() => post("/payouts", { business_id: biz.id, lines, memo: "Tips from the dashboard" }), "Payout proposed: the policy engine decided (see below)");
    setAmounts({});
  }

  async function addStaff() {
    const biz = (await api<Biz[]>("/businesses"))[0];
    await act(() => post("/staff", { business_id: biz.id, name: form.name, paypal_email: form.email }), `Added ${form.name}`);
    setForm({ name: "", email: "" });
  }

  return (
    <div className="space-y-4">
      <ErrorNote error={payouts.error} />
      {msg && <div className="text-sm rounded-md border border-line bg-panel px-3 py-2">{msg}</div>}
      <Card title={`Approval queue (${pendingP.length + pendingR.length})`} right={<span className="text-xs text-muted">Auto under the limit · owner approves above · hard limits deny</span>}>
        {!pendingP.length && !pendingR.length && <div className="text-sm text-muted">Nothing waiting. Small payouts and refunds were handled automatically.</div>}
        <div className="grid md:grid-cols-2 gap-3">
          {pendingP.map((p) => (
            <div key={p.id} className="rounded-lg border border-warn/40 p-3 space-y-2">
              <div className="flex justify-between"><span className="font-medium">Crew payout {money(p.total)}</span><span className="text-xs text-muted">{ago(p.created_at)}</span></div>
              <div className="text-xs text-muted">{p.items.map((i) => `${i.name}: ${money(i.amount)}`).join(" · ")}</div>
              <div className="text-xs">{p.error ?? p.policy.reasons.join("; ")}</div>
              <div className="flex gap-2">
                <Button tone="primary" onClick={() => act(() => post(`/payouts/${p.id}/approve`, { by: "owner" }), "Approved and sent to PayPal Payouts")}>Approve &amp; pay</Button>
                <Button tone="danger" onClick={() => act(() => post(`/payouts/${p.id}/reject`, { by: "owner" }), "Rejected")}>Reject</Button>
              </div>
            </div>
          ))}
          {pendingR.map((r) => (
            <div key={r.id} className="rounded-lg border border-warn/40 p-3 space-y-2">
              <div className="flex justify-between"><span className="font-medium">Refund {money(r.amount)}</span><span className="text-xs text-muted">order #{r.order_id.slice(0, 6)}</span></div>
              <div className="text-xs">{r.reason} · {r.error ?? r.policy.reasons.join("; ")}</div>
              <div className="flex gap-2">
                <Button tone="primary" onClick={() => act(() => post(`/refunds/${r.id}/approve`), "Refund sent through PayPal")}>Approve refund</Button>
                <Button tone="danger" onClick={() => act(() => post(`/refunds/${r.id}/reject`), "Refund rejected")}>Reject</Button>
              </div>
            </div>
          ))}
        </div>
      </Card>
      <div className="grid lg:grid-cols-3 gap-4">
        <Card title="Crew" className="lg:col-span-1">
          <div className="space-y-2">
            {(staff.data ?? []).map((s) => (
              <div key={s.id} className="flex items-center gap-2 text-sm">
                <div className="flex-1">
                  <div className="font-medium">{s.name}</div>
                  <div className="text-xs text-muted">{s.paypal_email}</div>
                </div>
                <input className="w-20 rounded-md border border-line bg-transparent px-2 py-1 text-sm" placeholder="$0.00" inputMode="decimal"
                  value={amounts[s.id] ?? ""} onChange={(e) => setAmounts({ ...amounts, [s.id]: e.target.value })} />
              </div>
            ))}
            <Button tone="primary" onClick={payCrew}>Pay crew with PayPal</Button>
            <div className="pt-3 mt-3 border-t border-line space-y-2">
              <div className="text-xs text-muted">Add crew member (PayPal email)</div>
              <input className="w-full rounded-md border border-line bg-transparent px-2 py-1 text-sm" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              <input className="w-full rounded-md border border-line bg-transparent px-2 py-1 text-sm" placeholder="email@example.com" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              <Button onClick={addStaff} disabled={!form.name || !form.email}>Add</Button>
            </div>
          </div>
        </Card>
        <Card title="Payout history" className="lg:col-span-2">
          <Grid<Payout>
            rows={payouts.data}
            height={420}
            getRowId={(r) => r.id}
            cols={[
              { headerName: "Created", field: "created_at", valueFormatter: (p) => ago(p.value), maxWidth: 110 },
              { headerName: "Memo", field: "memo", flex: 2 },
              { headerName: "Total", field: "total", valueFormatter: (p) => money(p.value), maxWidth: 100 },
              { headerName: "Status", field: "status", cellRenderer: (p: { value: string }) => <Badge tone={statusTone(p.value)}>{p.value}</Badge> },
              { headerName: "Policy", valueGetter: (p) => p.data?.policy.decision, cellRenderer: (p: { value: string }) => <Badge tone={statusTone(p.value)}>{p.value}</Badge>, maxWidth: 110 },
              { headerName: "Decided by", field: "decided_by", maxWidth: 120 },
              { headerName: "PayPal batch", field: "paypal_batch_id" },
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
