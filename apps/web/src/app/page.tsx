import Link from "next/link";

const STEPS: [string, string][] = [
  ["The phone rings", "CallPay answers every call, in English, Hindi, Tamil or Spanish, and takes the order from your real menu."],
  ["A PayPal link arrives", "The caller gets a secure PayPal checkout by text, or as a QR code on screen. Prices come from your menu, never from the AI."],
  ["Paid before they hang up", "PayPal confirms, and the agent says “got your payment” on the same call. The ticket goes to the kitchen."],
  ["The crew gets paid", "Tips and the crew's share go out through PayPal Payouts. Small amounts go automatically; larger ones wait for you."],
];

const CHAINS: [string, string[]][] = [
  ["AI brain", ["Claude", "OpenAI", "Gemini", "Local model", "Rules engine"]],
  ["Speech in", ["Deepgram", "AssemblyAI", "Whisper", "Browser"]],
  ["Voice out", ["ElevenLabs", "Cartesia", "OpenAI", "Browser"]],
  ["Phone and SMS", ["Twilio", "Telnyx", "Browser call"]],
  ["Payment", ["PayPal Orders", "PayPal Invoicing"]],
  ["Workflow", ["Temporal", "In-process runner"]],
  ["Events and data", ["Kafka → Flink → ClickHouse", "Postgres"]],
];

const RULES: [string, string][] = [
  ["The AI never sets a price", "Items, totals, tips and refunds are computed by code from your menu and orders. A reply that mentions a made-up amount is thrown away."],
  ["You approve what matters", "Payouts over $50 and refunds over $20 wait for your OK. Flagged callers get a lower checkout cap, and every refund for them comes to you."],
  ["Every money action is on record", "A hash-chained audit log covers each order, payout, refund and menu change. One click verifies nothing was altered."],
];

const PAYPAL = ["Orders", "Capture", "Payouts", "Refunds", "Disputes", "Webhooks", "Invoicing", "Transaction Search"];

const TRANSCRIPT: ["caller" | "agent", string][] = [
  ["agent", "Hi, thanks for calling Rosa's Taco Truck! What can I get started for you?"],
  ["caller", "Two carne asada tacos and a horchata, no onions."],
  ["agent", "Got it. That's $9.75. I've sent a PayPal link to your phone."],
  ["agent", "Got your payment of $9.75, thank you! Ready in about 10 minutes."],
];

export default function Landing() {
  return (
    <div>
      <section className="hero-glow border-b border-line">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-14 md:py-20 lg:grid-cols-2">
          <div className="rise">
            <p className="text-sm font-medium text-brand">AI phone agent for local businesses</p>
            <h1 className="mt-3 text-4xl font-semibold leading-[1.08] tracking-tight text-balance md:text-6xl">
              Every call answered. Paid before they hang up.
            </h1>
            <p className="mt-5 max-w-xl text-lg text-muted text-pretty">
              CallPay takes the order by voice, sends a PayPal link, confirms the payment on the same call, and pays your crew.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/call" className="rounded-xl bg-brand px-6 py-3 font-medium text-white hover:opacity-90">Try a call now</Link>
              <Link href="/dashboard" className="rounded-xl border border-line bg-panel px-6 py-3 font-medium hover:bg-fg/5">See the owner dashboard</Link>
            </div>
            <p className="mt-4 text-sm text-muted">Runs on the PayPal sandbox. No real money moves.</p>
          </div>

          <div className="rise rounded-3xl border border-line bg-panel p-5 shadow-xl shadow-black/5 [animation-delay:120ms]" aria-label="Example call">
            <div className="flex items-center justify-between border-b border-line pb-3 text-sm">
              <span className="flex items-center gap-2 font-medium">
                <span className="h-2 w-2 rounded-full bg-ok" /> Call in progress
              </span>
              <span className="text-xs text-muted">Example</span>
            </div>
            <div className="space-y-2.5 py-4">
              {TRANSCRIPT.map(([who, text], i) => (
                <div key={i} className={`flex ${who === "caller" ? "justify-end" : ""}`}>
                  <div className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${who === "caller" ? "bg-brand text-white" : "bg-fg/5"}`}>{text}</div>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between rounded-2xl bg-ok/10 px-4 py-3 text-sm">
              <span className="font-medium text-ok">Paid with PayPal</span>
              <span className="font-semibold tabular-nums">$9.75</span>
            </div>
            <div className="mt-2 flex items-center justify-between px-1 text-xs text-muted">
              <span>Kitchen ticket sent</span>
              <span>Crew payout $0.98 sent</span>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-14">
        <h2 className="text-2xl font-semibold tracking-tight">From ring to paid in one call</h2>
        <ol className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map(([title, body], i) => (
            <li key={title} className="rounded-2xl border border-line bg-panel p-5">
              <div className="grid h-8 w-8 place-items-center rounded-full bg-brand/10 text-sm font-semibold text-brand">{i + 1}</div>
              <h3 className="mt-3 font-semibold">{title}</h3>
              <p className="mt-1.5 text-sm text-muted">{body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="border-y border-line bg-panel">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <h2 className="text-2xl font-semibold tracking-tight">It keeps working when a provider doesn&apos;t</h2>
            <p className="mt-3 text-muted">
              Every layer has a backup that takes over by itself. Switch a provider off in the dashboard during a call and the call carries on.
            </p>
            <Link href="/dashboard" className="mt-5 inline-block text-sm font-medium text-brand hover:underline">Try the kill switch →</Link>
          </div>
          <dl className="space-y-3 lg:col-span-3">
            {CHAINS.map(([layer, chain]) => (
              <div key={layer} className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-4">
                <dt className="w-32 shrink-0 text-sm font-medium">{layer}</dt>
                <dd className="flex flex-wrap items-center gap-1.5 text-sm">
                  {chain.map((name, i) => (
                    <span key={name} className="flex items-center gap-1.5">
                      {i > 0 && <span className="text-muted" aria-hidden>→</span>}
                      <span className={`rounded-full border px-2.5 py-0.5 ${i === 0 ? "border-brand/30 bg-brand/10 text-brand" : "border-line text-muted"}`}>{name}</span>
                    </span>
                  ))}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-14">
        <h2 className="text-2xl font-semibold tracking-tight">Money stays under your rules</h2>
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          {RULES.map(([title, body]) => (
            <div key={title} className="rounded-2xl border border-line bg-panel p-5">
              <h3 className="font-semibold">{title}</h3>
              <p className="mt-1.5 text-sm text-muted">{body}</p>
            </div>
          ))}
        </div>
        <div className="mt-10 flex flex-wrap items-center gap-2 text-sm">
          <span className="mr-1 text-muted">Built on PayPal:</span>
          {PAYPAL.map((p) => (
            <span key={p} className="rounded-full border border-line bg-panel px-3 py-1">{p}</span>
          ))}
        </div>
      </section>

      <section className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-5 px-4 py-12 md:flex-row md:items-center">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">Order two tacos and watch it happen</h2>
            <p className="mt-1 text-muted">Talk or type. It takes about a minute.</p>
          </div>
          <Link href="/call" className="rounded-xl bg-brand px-6 py-3 font-medium text-white hover:opacity-90">Try a call now</Link>
        </div>
        <footer className="mx-auto flex max-w-6xl flex-wrap justify-between gap-2 px-4 pb-8 text-xs text-muted">
          <span>CallPay · built for the PayPal AI Hackathon 2026 · MIT license</span>
          <a href="https://github.com/balax-24/Paypal_Hackathon" className="hover:text-fg hover:underline">Source on GitHub</a>
        </footer>
      </section>
    </div>
  );
}
