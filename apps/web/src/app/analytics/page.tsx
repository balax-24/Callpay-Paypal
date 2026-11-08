"use client";

import { useState } from "react";
import { Badge, Button, Card } from "@/components/ui";
import { post } from "@/lib/api";

type Answer = { question: string; answer: string; metric: string; window: string; llm: string | null; data: { source: string } };

const SUGGESTIONS = [
  "How much did we make today?",
  "What's our busiest hour this week?",
  "What are the best sellers this month?",
  "How many callers hung up before paying?",
  "How much did we pay the crew this week?",
  "Did any AI provider fail over today?",
];

export default function Analytics() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [err, setErr] = useState<string | null>(null);

  async function ask(question: string) {
    if (!question.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const a = await post<Answer>("/analytics/ask", { question });
      setAnswers((prev) => [a, ...prev]);
      setQ("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Ask your business</h1>
        <p className="text-sm text-muted">The Analyst agent picks a metric from a fixed catalog; code runs the query (ClickHouse, or the main database if it&apos;s down). It can&apos;t make up numbers.</p>
      </div>
      <Card>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
          <input className="flex-1 rounded-md border border-line bg-transparent px-3 py-2 text-sm" placeholder="e.g. What's my busiest hour?" value={q} onChange={(e) => setQ(e.target.value)} />
          <Button tone="primary" disabled={busy}>{busy ? "Thinking…" : "Ask"}</Button>
        </form>
        <div className="flex flex-wrap gap-2 mt-3">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => ask(s)} className="text-xs rounded-full border border-line px-3 py-1 hover:bg-fg/5">{s}</button>
          ))}
        </div>
        {err && <div className="text-xs text-bad mt-2">{err}</div>}
      </Card>
      {answers.map((a, i) => (
        <Card key={i}>
          <div className="text-xs text-muted">{a.question}</div>
          <div className="text-lg mt-1">{a.answer}</div>
          <div className="flex gap-2 mt-2">
            <Badge tone="blue">{a.metric}</Badge>
            <Badge>{a.window}</Badge>
            <Badge tone={a.data.source === "clickhouse" ? "green" : "amber"}>{a.data.source}</Badge>
            <Badge>{a.llm ? `routed by ${a.llm}` : "routed by rules"}</Badge>
          </div>
        </Card>
      ))}
    </div>
  );
}
