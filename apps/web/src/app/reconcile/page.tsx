"use client";

import { useCallback, useEffect, useState } from "react";
import Grid from "@/components/Grid";
import { Badge, Button, Card, Stat } from "@/components/ui";
import { ago, api, money } from "@/lib/api";

type Row = {
  order_id: string; capture_id: string | null; order_total: string; paid_at: string | null;
  paypal_amount: string | null; paypal_fee: string | null; paypal_status: string | null; result: string;
};
type Unknown = { transaction_id: string; amount: string; event_code: string; date: string | null };
type Report = {
  window_days: number; generated_at: string; paypal_transactions: number; note: string;
  summary: {
    orders: number; matched: number; amount_mismatch: number; pending_in_paypal: number; missing_in_paypal: number;
    unknown_in_paypal: number; gross: string; fees: string; net: string;
  };
  rows: Row[]; unknown: Unknown[];
};

const LABEL: Record<string, [string, "green" | "red" | "amber"]> = {
  matched: ["Matched", "green"],
  amount_mismatch: ["Amount differs", "red"],
  pending_in_paypal: ["Not in report yet", "amber"],
  missing_in_paypal: ["Missing in PayPal", "red"],
};

function errorText(e: unknown) {
  const raw = (e as Error).message;
  try {
    return JSON.parse(raw).error ?? raw;
  } catch {
    return raw;
  }
}

export default function ReconcilePage() {
  const [days, setDays] = useState(7);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (d: number) => {
    setBusy(true);
    setError(null);
    try {
      setReport(await api<Report>(`/reconciliation?days=${d}`));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    run(days);
  }, [run, days]);

  const s = report?.summary;
  const problems = s ? s.amount_mismatch + s.missing_in_paypal + s.unknown_in_paypal : 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">PayPal reconciliation</h1>
          <p className="text-sm text-muted">Every paid order checked against PayPal&apos;s own transaction report (Transaction Search API). Read-only.</p>
        </div>
        <div className="flex items-center gap-2">
          {[1, 7, 30].map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={`rounded-md border px-3 py-1.5 text-sm ${days === d ? "border-brand bg-brand/10 text-brand" : "border-line hover:bg-fg/5"}`}>
              {d === 1 ? "24 hours" : `${d} days`}
            </button>
          ))}
          <Button tone="primary" disabled={busy} onClick={() => run(days)}>{busy ? "Checking…" : "Run now"}</Button>
        </div>
      </div>
      {error && <div className="rounded-md border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">{error}</div>}
      {s && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label="Paid orders" value={s.orders} hint={`${report.paypal_transactions} PayPal transactions read`} />
            <Stat label="Matched" value={s.matched} hint={problems ? `${problems} need a look` : "nothing to chase"} />
            <Stat label="Not in report yet" value={s.pending_in_paypal} hint="PayPal reports lag ~3 hours" />
            <Stat label="PayPal fees" value={money(Math.abs(Number(s.fees)))} hint={`gross ${money(s.gross)}`} />
            <Stat label="Net received" value={money(s.net)} hint={`checked ${ago(report.generated_at)}`} />
          </div>
          <Card title="Orders" right={<Badge tone={problems ? "red" : "green"}>{problems ? `${problems} to review` : "All clear"}</Badge>}>
            <Grid<Row>
              rows={report.rows}
              height={380}
              getRowId={(r) => r.order_id}
              cols={[
                { headerName: "Paid", field: "paid_at", valueFormatter: (p) => ago(p.value), maxWidth: 110 },
                { headerName: "Order", field: "order_id", valueFormatter: (p) => `#${String(p.value).slice(0, 6)}`, maxWidth: 100 },
                { headerName: "Our total", field: "order_total", valueFormatter: (p) => money(p.value), maxWidth: 110 },
                { headerName: "PayPal amount", field: "paypal_amount", valueFormatter: (p) => money(p.value), maxWidth: 130 },
                { headerName: "Fee", field: "paypal_fee", valueFormatter: (p) => (p.value == null ? "–" : money(Math.abs(Number(p.value)))), maxWidth: 90 },
                { headerName: "PayPal capture", field: "capture_id" },
                {
                  headerName: "Result", field: "result",
                  cellRenderer: (p: { value: string }) => <Badge tone={LABEL[p.value]?.[1] ?? "amber"}>{LABEL[p.value]?.[0] ?? p.value}</Badge>,
                },
              ]}
            />
            <p className="mt-2 text-xs text-muted">{report.note}</p>
          </Card>
          {report.unknown.length > 0 && (
            <Card title={`Money in PayPal with no matching order (${report.unknown.length})`}>
              <ul className="space-y-1 text-sm">
                {report.unknown.map((u) => (
                  <li key={u.transaction_id} className="flex flex-wrap gap-3">
                    <span className="font-mono text-xs">{u.transaction_id}</span>
                    <span>{money(u.amount)}</span>
                    <span className="text-muted">{u.date ? new Date(u.date).toLocaleString() : ""} · {u.event_code}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
