"use client";

import { useState } from "react";
import Grid from "@/components/Grid";
import { Button, Card, ErrorNote } from "@/components/ui";
import { api, money, post, usePoll } from "@/lib/api";

type Item = { id: string; name: string; price: string };
type Biz = { id: string; name: string; menu: Item[] };

const input = "rounded-md border border-line bg-transparent px-3 py-2 text-sm";

export default function MenuPage() {
  const { data, error, reload } = usePoll<Biz[]>("/businesses", 10000);
  const [form, setForm] = useState({ name: "", price: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const biz = data?.[0];

  async function run(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      setMsg({ ok: true, text: ok });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
    reload();
  }

  function edited(row: Item, field: string, value: unknown, old: unknown) {
    if (value === old) return;
    if (field === "price") {
      const n = Number(value);
      if (!Number.isFinite(n) || n <= 0) {
        setMsg({ ok: false, text: "Price must be a number above 0." });
        return reload();
      }
      return run(() => api(`/menu/${row.id}`, { method: "PUT", body: JSON.stringify({ price: n.toFixed(2) }) }), `${row.name} is now ${money(n)}.`);
    }
    return run(() => api(`/menu/${row.id}`, { method: "PUT", body: JSON.stringify({ name: String(value) }) }), `Renamed to ${String(value)}.`);
  }

  async function add() {
    if (!biz) return;
    await run(() => post(`/businesses/${biz.id}/menu`, { name: form.name, price: Number(form.price).toFixed(2) }), `Added ${form.name}.`);
    setForm({ name: "", price: "" });
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Menu</h1>
        <p className="text-sm text-muted">
          Click a name or price to edit it. The phone agent sells from this list on the very next call, and it can never change a price itself.
        </p>
      </div>
      <ErrorNote error={error} />
      {msg && (
        <div className={`rounded-md border px-3 py-2 text-sm ${msg.ok ? "border-ok/30 bg-ok/10 text-ok" : "border-bad/30 bg-bad/10 text-bad"}`}>{msg.text}</div>
      )}
      <Card title={biz ? biz.name : "Menu"} right={<span className="text-xs text-muted">{biz?.menu.length ?? 0} items</span>}>
        <Grid<Item>
          rows={biz?.menu ?? null}
          height={360}
          getRowId={(r) => r.id}
          onCellEdited={edited}
          cols={[
            { headerName: "Item", field: "name", editable: true, flex: 2 },
            { headerName: "Price (USD)", field: "price", editable: true, valueFormatter: (p) => money(p.value), maxWidth: 160 },
            {
              headerName: "", maxWidth: 110, sortable: false, filter: false,
              cellRenderer: (p: { data?: Item }) =>
                p.data ? <Button small tone="danger" onClick={() => run(() => api(`/menu/${p.data!.id}`, { method: "DELETE" }), `Removed ${p.data!.name}.`)}>Remove</Button> : null,
            },
          ]}
        />
      </Card>
      <Card title="Add an item">
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); add(); }}>
          <label className="flex-1 min-w-[180px] text-xs text-muted">
            Name
            <input className={`${input} mt-1 w-full text-fg`} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Churro" />
          </label>
          <label className="w-32 text-xs text-muted">
            Price (USD)
            <input className={`${input} mt-1 w-full text-fg`} inputMode="decimal" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} placeholder="2.50" />
          </label>
          <Button tone="primary" disabled={!form.name.trim() || !(Number(form.price) > 0)}>Add item</Button>
        </form>
        <p className="mt-3 text-xs text-muted">Every change is written to the audit log. Past orders keep the name and price they were sold at.</p>
      </Card>
    </div>
  );
}
