"use client";

import { Badge, Card, ErrorNote } from "@/components/ui";
import { ago, api, usePoll } from "@/lib/api";

type Entry = {
  id: number;
  ts: string;
  actor: string;
  action: string;
  entity: string;
  entity_id: string;
  data: Record<string, unknown>;
  hash: string;
};
type Verification = { valid: boolean; checked: number; broken_at: number | null; head?: string };

export default function AuditPage() {
  const entries = usePoll<Entry[]>("/audit", 5000);
  const verification = usePoll<Verification>("/audit/verify", 5000);

  async function verifyNow() {
    await api<Verification>("/audit/verify");
    verification.reload();
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Money action audit</h1>
        <p className="text-sm text-muted">Append-only records linked by SHA-256 hashes. Verification detects changed or removed entries.</p>
      </div>
      <ErrorNote error={entries.error ?? verification.error} />
      <Card title="Chain integrity" right={<button onClick={verifyNow} className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-fg/5">Verify now</button>}>
        {verification.data && (
          <div className="flex items-center gap-2 text-sm">
            <Badge tone={verification.data.valid ? "green" : "red"}>{verification.data.valid ? "Chain valid" : `Broken at #${verification.data.broken_at}`}</Badge>
            <span className="text-muted">{verification.data.checked} entries checked</span>
          </div>
        )}
        {verification.data?.head && <div className="mt-2 break-all font-mono text-[10px] text-muted">Head hash: {verification.data.head}</div>}
      </Card>
      <Card title={`Recent entries (${entries.data?.length ?? 0})`}>
        {!entries.data?.length ? <div className="text-sm text-muted">Money and provider-control actions will appear here.</div> : (
          <div className="space-y-2">
            {entries.data.map((entry) => (
              <article key={entry.id} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge>{entry.action}</Badge>
                  <span className="font-mono text-xs">{entry.entity} #{entry.entity_id.slice(0, 12)}</span>
                  <span className="ml-auto text-xs text-muted">{ago(entry.ts)} · {entry.actor}</span>
                </div>
                <pre className="mt-2 whitespace-pre-wrap break-all text-xs text-muted">{JSON.stringify(entry.data, null, 2)}</pre>
                <div className="mt-2 truncate font-mono text-[10px] text-muted">SHA-256 · {entry.hash}</div>
              </article>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
